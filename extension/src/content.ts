import type { HighlightCategory, JobHighlight, Message } from "./types";

const MAX_DESCRIPTION_CHARS = 40000;
const MAX_HIGHLIGHTS = 160;
const DESCRIPTION_SELECTORS = [
  ".jobs-description__content",
  ".jobs-box__html-content",
  ".jobs-description-content__text",
  ".job-view-layout .jobs-box__html-content",
  "#job-details",
  "[id*='job-description' i]",
  "[data-test*='job-description' i]",
  "[data-testid*='job-description' i]",
  "[aria-label*='job description' i]",
  "[class*='jobs-description']",
];
const DESCRIPTION_HEADINGS = [
  "about the job",
  "about this job",
  "job description",
  "about the role",
  "responsibilities",
];
const COLORS: Record<HighlightCategory, { background: string; border: string; label: string }> = {
  salary: { background: "#b7e4c7b8", border: "#16803c", label: "Salary" },
  experience: { background: "#b6d7f7b8", border: "#1769aa", label: "Experience" },
  required: { background: "#ffe08ab8", border: "#a65b00", label: "Required skill" },
  preferred: { background: "#e1c4f7b8", border: "#7133a3", label: "Preferred skill" },
};

interface PageHighlight {
  range: Range;
  category: HighlightCategory;
}

let activeHighlights: PageHighlight[] = [];
let highlightContainer: HTMLDivElement | null = null;
let positionFrame = 0;

function isLinkedInPage(): boolean {
  return location.hostname === "linkedin.com" || location.hostname.endsWith(".linkedin.com");
}

function descriptionElements(selector: string): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>(selector))
    .filter((element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" &&
        rect.width > 0 && rect.height > 0;
    });
}

function findJobDescriptionElement(): HTMLElement | null {
  for (const selector of DESCRIPTION_SELECTORS) {
    const directMatch = descriptionElements(selector)
      .filter((element) => (element.innerText || "").trim().length >= 100)
      .sort((left, right) => right.innerText.length - left.innerText.length)[0];
    if (directMatch) return directMatch;
  }

  const headings = Array.from(document.querySelectorAll<HTMLElement>("h1,h2,h3,h4,[role='heading']"))
    .filter((heading) => DESCRIPTION_HEADINGS.includes((heading.innerText || "").trim().toLowerCase()));
  const sectionCandidates: HTMLElement[] = [];
  for (const heading of headings) {
    let ancestor = heading.parentElement;
    for (let depth = 0; ancestor && depth < 5; depth += 1, ancestor = ancestor.parentElement) {
      if (ancestor === document.body || ancestor === document.documentElement) break;
      const textLength = (ancestor.innerText || "").trim().length;
      if (textLength >= 100 && textLength <= MAX_DESCRIPTION_CHARS * 2) {
        sectionCandidates.push(ancestor);
      }
    }
  }
  return sectionCandidates.sort(
    (left, right) => left.innerText.length - right.innerText.length,
  )[0] ?? null;
}

async function extractJobDescription(): Promise<{ description: string; truncated: boolean; pageUrl: string }> {
  if (!isLinkedInPage()) {
    throw new Error("Open a LinkedIn job listing, or paste its description into RoleLens.");
  }
  let descriptionElement = findJobDescriptionElement();
  for (let attempt = 0; !descriptionElement && attempt < 5; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 300));
    descriptionElement = findJobDescriptionElement();
  }
  const text = (descriptionElement?.innerText || "").replace(/\s+/g, " ").trim();
  if (text.length >= 100) {
    return {
      description: text.slice(0, MAX_DESCRIPTION_CHARS),
      truncated: text.length > MAX_DESCRIPTION_CHARS,
      pageUrl: location.href,
    };
  }
  throw new Error("I couldn't find the job description on this page. Paste it into the side panel instead.");
}

function removeHighlights(): void {
  if (positionFrame) cancelAnimationFrame(positionFrame);
  positionFrame = 0;
  highlightContainer?.remove();
  highlightContainer = null;
  activeHighlights = [];
  window.removeEventListener("scroll", scheduleHighlightPosition, true);
  window.removeEventListener("resize", scheduleHighlightPosition);
}

function scheduleHighlightPosition(): void {
  if (positionFrame) return;
  positionFrame = requestAnimationFrame(positionHighlights);
}

function addLegend(shadow: ShadowRoot): void {
  const legend = document.createElement("aside");
  legend.style.cssText = "position:fixed;right:16px;bottom:16px;display:grid;gap:6px;padding:10px 12px;border:1px solid #d6d6d6;border-radius:8px;background:#fff;color:#202124;box-shadow:0 2px 12px #0002;font:12px/1.3 system-ui,sans-serif;pointer-events:auto";
  const heading = document.createElement("div");
  heading.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:16px";
  const title = document.createElement("strong");
  title.textContent = "Job details highlighted";
  const closeButton = document.createElement("button");
  closeButton.type = "button";
  closeButton.textContent = "×";
  closeButton.setAttribute("aria-label", "Close job highlights and legend");
  closeButton.title = "Close job highlights";
  closeButton.style.cssText = "border:0;border-radius:4px;padding:0 4px;background:transparent;color:#5f6368;font:20px/1 system-ui,sans-serif;cursor:pointer";
  closeButton.addEventListener("click", removeHighlights);
  heading.append(title, closeButton);
  legend.append(heading);
  for (const category of ["salary", "experience", "required", "preferred"] as const) {
    if (!activeHighlights.some((highlight) => highlight.category === category)) continue;
    const item = document.createElement("span");
    const swatch = document.createElement("i");
    swatch.style.cssText = `display:inline-block;width:10px;height:10px;margin-right:6px;border:1px solid ${COLORS[category].border};background:${COLORS[category].background}`;
    item.append(swatch, document.createTextNode(COLORS[category].label));
    legend.append(item);
  }
  shadow.append(legend);
}

function positionHighlights(): void {
  positionFrame = 0;
  const root = highlightContainer?.shadowRoot;
  if (!root) return;
  root.querySelectorAll(".phrase-highlight").forEach((element) => element.remove());
  for (const { range, category } of activeHighlights) {
    if (!range.startContainer.isConnected || !range.endContainer.isConnected) continue;
    const style = COLORS[category];
    for (const rect of Array.from(range.getClientRects())) {
      if (rect.width <= 0 || rect.height <= 0) continue;
      const mark = document.createElement("span");
      mark.className = "phrase-highlight";
      mark.style.cssText = `position:fixed;left:${rect.left}px;top:${rect.top}px;width:${rect.width}px;height:${rect.height}px;background:${style.background};border-bottom:2px solid ${style.border};border-radius:2px;box-sizing:border-box;pointer-events:none`;
      root.append(mark);
    }
  }
}

function termPattern(term: string): RegExp {
  const normalized = term.trim();
  const escaped = normalized.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+");
  const startsWithWordCharacter = /^[\p{L}\p{N}_]/u.test(normalized);
  const endsWithWordCharacter = /[\p{L}\p{N}_]$/u.test(normalized);
  const leftBoundary = startsWithWordCharacter ? "(?<![\\p{L}\\p{N}_])" : "";
  const rightBoundary = endsWithWordCharacter ? "(?![\\p{L}\\p{N}_])" : "";
  return new RegExp(`${leftBoundary}${escaped}${rightBoundary}`, "giu");
}

function highlightJobDescription(highlights: JobHighlight[]): number {
  removeHighlights();
  const descriptionElement = isLinkedInPage() ? findJobDescriptionElement() : null;
  if (!descriptionElement) return 0;
  const terms = highlights
    .filter((item) => item.text.trim().length >= 2 && item.text.length <= 180)
    .sort((left, right) => right.text.length - left.text.length);
  if (!terms.length) return 0;

  const walker = document.createTreeWalker(descriptionElement, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent || parent.closest("[data-rolelens-highlights]")) return NodeFilter.FILTER_REJECT;
      if (parent.closest("script,style,noscript,textarea,input,select,option,button,[contenteditable='true']")) {
        return NodeFilter.FILTER_REJECT;
      }
      if (!node.textContent?.trim()) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });

  let node: Node | null;
  while ((node = walker.nextNode())) {
    if (activeHighlights.length >= MAX_HIGHLIGHTS) break;
    const value = node.textContent ?? "";
    for (const term of terms) {
      if (activeHighlights.length >= MAX_HIGHLIGHTS) break;
      const pattern = termPattern(term.text);
      let match: RegExpExecArray | null;
      let count = 0;
      while ((match = pattern.exec(value)) && count < 10 && activeHighlights.length < MAX_HIGHLIGHTS) {
        const range = document.createRange();
        range.setStart(node, match.index);
        range.setEnd(node, match.index + match[0].length);
        activeHighlights.push({ range, category: term.category });
        count += 1;
        if (!match[0].length) pattern.lastIndex += 1;
      }
    }
  }

  if (!activeHighlights.length) return 0;
  highlightContainer = document.createElement("div");
  highlightContainer.setAttribute("data-rolelens-highlights", "true");
  highlightContainer.style.cssText = "position:fixed;inset:0;z-index:2147483647;pointer-events:none";
  const shadow = highlightContainer.attachShadow({ mode: "open" });
  addLegend(shadow);
  document.documentElement.append(highlightContainer);
  positionHighlights();
  window.addEventListener("scroll", scheduleHighlightPosition, true);
  window.addEventListener("resize", scheduleHighlightPosition);
  return activeHighlights.length;
}

chrome.runtime.onMessage.addListener((message: Message, _sender, sendResponse) => {
  if (message.type === "EXTRACT_JOB_DESCRIPTION") {
    void extractJobDescription().then(
      (data) => sendResponse({ ok: true, ...data }),
      (error: unknown) => sendResponse({
        ok: false,
        error: error instanceof Error ? error.message : "Could not read the job description.",
      }),
    );
    return true;
  }
  if (message.type === "APPLY_JOB_HIGHLIGHTS") {
    const highlights = Array.isArray(message.highlights) ? message.highlights as JobHighlight[] : [];
    sendResponse({ ok: true, highlightedCount: highlightJobDescription(highlights) });
    return false;
  }
  if (message.type === "CLEAR_JOB_HIGHLIGHTS") {
    removeHighlights();
    sendResponse({ ok: true });
    return false;
  }
});
