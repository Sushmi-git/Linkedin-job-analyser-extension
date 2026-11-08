import type { Message } from "./types";

const DEFAULT_BACKEND = "http://localhost:8001";

chrome.runtime.onInstalled.addListener(() => {
  void chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
});

async function backendUrl(): Promise<string> {
  const { backendUrl: saved } = await chrome.storage.local.get("backendUrl");
  if (typeof saved !== "string" || !saved.trim()) return DEFAULT_BACKEND;
  let url: URL;
  try {
    url = new URL(saved.trim());
  } catch {
    throw new Error("The saved backend URL is invalid. Use http://localhost:8001.");
  }
  if (
    url.protocol !== "http:" ||
    !["localhost", "127.0.0.1"].includes(url.hostname) ||
    url.port !== "8001" ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  ) {
    throw new Error("For privacy, RoleLens only sends job descriptions to a local backend on port 8001.");
  }
  return url.origin;
}

async function sendToPage(tabId: number, message: Message): Promise<unknown> {
  try {
    return await chrome.tabs.sendMessage(tabId, message);
  } catch (error) {
    const messageText = error instanceof Error ? error.message : "";
    if (!/receiving end does not exist|could not establish connection/i.test(messageText)) {
      throw error;
    }

    const files = (chrome.runtime.getManifest().content_scripts ?? [])
      .flatMap((script) => script.js ?? []);
    if (files.length === 0) {
      throw new Error("RoleLens has no page script configured. Rebuild and reload the extension.");
    }

    try {
      await chrome.scripting.executeScript({ target: { tabId }, files });
      return await chrome.tabs.sendMessage(tabId, message);
    } catch (injectionError) {
      throw new Error(
        "RoleLens could not connect to this page. Make sure this is a regular website tab (not a Chrome settings page or Web Store), then reload the page and try again.",
        { cause: injectionError },
      );
    }
  }
}

chrome.runtime.onMessage.addListener((message: Message, sender, sendResponse) => {
  if (message.type === "API_REQUEST") {
    void (async () => {
      try {
        const base = await backendUrl();
        const path = message.path;
        const method = message.method;
        const allowedRequests = [
          "POST /analyze",
          "GET /resume/status",
          "POST /resume/upload",
          "DELETE /resume",
          "POST /compare",
        ];
        if (
          typeof path !== "string" ||
          typeof method !== "string" ||
          !allowedRequests.includes(`${method} ${path}`)
        ) {
          throw new Error("Unsupported backend endpoint.");
        }
        const response = await fetch(`${base}${path}`, {
          method,
          headers: { "Content-Type": "application/json" },
          ...(method === "GET" || method === "DELETE"
            ? {}
            : { body: JSON.stringify(message.body) }),
        });
        const contentType = response.headers.get("content-type") ?? "";
        const responseText = await response.text();
        let payload: unknown;
        try {
          payload = JSON.parse(responseText);
        } catch {
          const hint = contentType.includes("text/html") || responseText.trimStart().startsWith("<")
            ? "The backend returned an HTML page instead of JSON. Check that the backend URL points to RoleLens (the local server is usually http://localhost:8001) and that the API is running."
            : "The backend returned an invalid response. Check that the RoleLens API is running.";
          throw new Error(`${hint} HTTP ${response.status} from ${base}${path}.`);
        }
        if (!response.ok) {
          const detail = typeof payload === "object" && payload !== null && "detail" in payload
            ? String(payload.detail)
            : `Backend returned HTTP ${response.status}.`;
          throw new Error(detail);
        }
        sendResponse({ ok: true, data: payload });
      } catch (error) {
        sendResponse({ ok: false, error: error instanceof Error ? error.message : "Backend request failed." });
      }
    })();
    return true;
  }

  if (message.type === "PAGE_CHANGED" || message.type === "GUIDANCE_CONTROL") {
    void chrome.runtime.sendMessage({ ...message, type: `FORWARDED_${message.type}` }).catch(() => undefined);
    return false;
  }

  if (
    message.type === "EXTRACT_JOB_DESCRIPTION" ||
    message.type === "APPLY_JOB_HIGHLIGHTS" ||
    message.type === "CLEAR_JOB_HIGHLIGHTS"
  ) {
    const tabId = sender.tab?.id ?? message.tabId;
    if (typeof tabId !== "number") {
      sendResponse({ ok: false, error: "No active tab is available." });
      return false;
    }
    void sendToPage(tabId, message).then(
      (data) => sendResponse({ ok: true, data }),
      (error: unknown) => sendResponse({ ok: false, error: error instanceof Error ? error.message : "The page script is unavailable." }),
    );
    return true;
  }
  return false;
});
