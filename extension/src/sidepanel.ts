import type { JobAnalysis, JobHighlight, Message, ResumeComparison } from "./types";

interface PageResponse {
  ok: boolean;
  description?: string;
  truncated?: boolean;
  pageUrl?: string;
  highlightedCount?: number;
  error?: string;
}

const $ = <T extends HTMLElement>(id: string): T => {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing side panel element: ${id}`);
  return element as T;
};

const descriptionInput = $("description") as HTMLTextAreaElement;
const backendInput = $("backend") as HTMLInputElement;
const DEFAULT_BACKEND = "http://localhost:8001";
const status = $("status");
const analyzeButton = $("analyze-button") as HTMLButtonElement;
const analysisSection = $("analysis");
const resumeFileInput = $("resume-file") as HTMLInputElement;
const uploadResumeButton = $("upload-resume-button") as HTMLButtonElement;
const removeResumeButton = $("remove-resume-button") as HTMLButtonElement;
const resumeStatus = $("resume-status");
const compareButton = $("compare-button") as HTMLButtonElement;
const comparisonSection = $("comparison");
const compareStatus = $("compare-status");
let analyzedTabId: number | null = null;
let analyzedPageUrl: string | null = null;
let requestVersion = 0;
let analyzedDescription: string | null = null;
let hasSavedResume = false;

function message<T>(payload: Message): Promise<T> {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(payload, (response) => {
      const error = chrome.runtime.lastError;
      if (error) reject(new Error(error.message));
      else if (!response?.ok) reject(new Error(response?.error ?? "Extension request failed."));
      else resolve(response.data as T);
    });
  });
}

async function api<T>(
  path: string,
  method: "GET" | "POST" | "DELETE",
  body?: unknown,
): Promise<T> {
  const backend = localBackendUrl(backendInput.value);
  backendInput.value = backend;
  await chrome.storage.local.set({ backendUrl: backend });
  const response = await message<T>({
    type: "API_REQUEST",
    path,
    method,
    ...(body === undefined ? {} : { body }),
  });
  return response;
}

function localBackendUrl(value: string): string {
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    throw new Error("Use the local backend URL http://localhost:8001.");
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

async function activeTabId(): Promise<number> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (typeof tab?.id !== "number") throw new Error("Open a LinkedIn job listing, or paste its description.");
  return tab.id;
}

async function clearPageHighlights(tabId: number): Promise<void> {
  const page = await message<PageResponse>({
    type: "CLEAR_JOB_HIGHLIGHTS",
    tabId,
  });
  if (!page.ok) throw new Error(page.error ?? "Could not clear previous page highlights.");
}

function addListItems(id: string, values: string[], emptyMessage = "Not explicitly mentioned."): void {
  const list = $(id);
  list.replaceChildren();
  if (!values.length) {
    const item = document.createElement("li");
    item.textContent = emptyMessage;
    list.append(item);
    return;
  }
  for (const value of values) {
    const item = document.createElement("li");
    item.textContent = value;
    list.append(item);
  }
}

function renderAnalysis(result: JobAnalysis): void {
  $("summary").textContent = result.summary;
  $("salary").textContent = result.salary ?? "Not mentioned in the job description.";
  $("experience").textContent = result.experience ?? "Not mentioned in the job description.";
  addListItems("compulsory-skills", result.compulsory_skills);
  addListItems("preferred-skills", result.preferred_skills);
  addListItems("other-requirements", result.other_requirements);
  analysisSection.hidden = false;
}

function isJobHighlightList(value: unknown): value is JobHighlight[] {
  const categories = new Set(["salary", "experience", "required", "preferred"]);
  return Array.isArray(value) && value.every((item) =>
    typeof item === "object" && item !== null &&
    "text" in item && typeof item.text === "string" &&
    "category" in item && typeof item.category === "string" &&
    categories.has(item.category),
  );
}

async function analyze(): Promise<void> {
  const currentVersion = ++requestVersion;
  analyzeButton.disabled = true;
  status.textContent = "Reading and analyzing the job description…";
  analysisSection.hidden = true;
  comparisonSection.hidden = true;
  analyzedDescription = null;
  const previousTabId = analyzedTabId;
  analyzedTabId = null;
  analyzedPageUrl = null;
  try {
    if (previousTabId !== null) await clearPageHighlights(previousTabId);
    const tabId = await activeTabId();
    const pastedDescription = descriptionInput.value.trim();
    let description = pastedDescription;
    let wasTruncated = false;
    const usedPastedText = Boolean(pastedDescription);
    let pageChanged = false;

    if (!description) {
      const page = await message<PageResponse>({
        type: "EXTRACT_JOB_DESCRIPTION",
        tabId,
      });
      if (!page.ok || !page.description) {
        throw new Error(page.error ?? "Could not read the job description.");
      }
      description = page.description;
      wasTruncated = page.truncated === true;
      analyzedTabId = tabId;
      analyzedPageUrl = page.pageUrl ?? null;
    }

    if (description.length < 100) {
      throw new Error("Please provide a longer job description (at least 100 characters).");
    }
    if (description.length > 40000) {
      throw new Error("The job description is over the 40,000 character limit. Shorten it and try again.");
    }

    const result = await api<JobAnalysis>("/analyze", "POST", { description });
    if (currentVersion !== requestVersion) return;
    analyzedDescription = description;
    renderAnalysis(result);
    await refreshResumeStatus();
    compareButton.disabled = false;

    let highlightCount = 0;
    if (analyzedTabId !== null && isJobHighlightList(result.highlights)) {
      const currentTab = await chrome.tabs.get(analyzedTabId);
      if (currentTab.url === analyzedPageUrl) {
        const page = await message<PageResponse>({
          type: "APPLY_JOB_HIGHLIGHTS",
          tabId: analyzedTabId,
          highlights: result.highlights,
        });
        if (!page.ok) throw new Error(page.error ?? "Could not highlight the job description.");
        highlightCount = page.highlightedCount ?? 0;
      } else {
        analyzedTabId = null;
        analyzedPageUrl = null;
        pageChanged = true;
      }
    }

    const notes = [
      wasTruncated ? "Only the first 40,000 characters were analyzed." : "",
      usedPastedText ? "Highlights are unavailable for pasted text." :
        pageChanged ? "Page changed during analysis; review results without highlights." :
        highlightCount ? `${highlightCount} matching phrase${highlightCount === 1 ? "" : "s"} highlighted on the page.` :
          "No exact phrases could be highlighted on the page.",
    ].filter(Boolean);
    status.textContent = notes.join(" ");
  } catch (error) {
    if (currentVersion !== requestVersion) return;
    analyzedTabId = null;
    analyzedPageUrl = null;
    status.textContent = error instanceof Error ? error.message : "Unable to analyze this job.";
  } finally {
    if (currentVersion === requestVersion) analyzeButton.disabled = false;
  }
}

function readPdfAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      if (typeof reader.result !== "string") {
        reject(new Error("Could not read the selected PDF."));
        return;
      }
      const separator = reader.result.indexOf(",");
      if (separator < 0) {
        reject(new Error("Could not encode the selected PDF."));
        return;
      }
      resolve(reader.result.slice(separator + 1));
    });
    reader.addEventListener("error", () => reject(new Error("Could not read the selected PDF.")));
    reader.readAsDataURL(file);
  });
}

async function refreshResumeStatus(): Promise<boolean> {
  try {
    const result = await api<{ has_resume: boolean }>("/resume/status", "GET");
    hasSavedResume = result.has_resume;
    resumeStatus.textContent = hasSavedResume
      ? "A resume is saved locally and ready for comparison."
      : "No resume saved yet.";
    removeResumeButton.hidden = !hasSavedResume;
    compareButton.disabled = analyzedDescription === null;
    compareButton.textContent = hasSavedResume
      ? "Compare with resume"
      : "Upload a resume to compare";
    return hasSavedResume;
  } catch (error) {
    hasSavedResume = false;
    removeResumeButton.hidden = true;
    compareButton.disabled = analyzedDescription === null;
    compareButton.textContent = "Check resume status to compare";
    resumeStatus.textContent = error instanceof Error
      ? `Could not check the saved resume: ${error.message}`
      : "Could not check the saved resume.";
    return false;
  }
}

async function uploadResume(): Promise<void> {
  const file = resumeFileInput.files?.[0];
  if (!file) {
    resumeStatus.textContent = "Choose a PDF resume first.";
    return;
  }
  if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
    resumeStatus.textContent = "Choose a PDF file.";
    return;
  }
  if (file.size > 8 * 1024 * 1024) {
    resumeStatus.textContent = "The PDF must be 8 MB or smaller.";
    return;
  }
  uploadResumeButton.disabled = true;
  resumeStatus.textContent = "Checking and saving the PDF locally…";
  try {
    const pdfBase64 = await readPdfAsBase64(file);
    await api("/resume/upload", "POST", { pdf_base64: pdfBase64 });
    resumeFileInput.value = "";
    await refreshResumeStatus();
    compareStatus.textContent = analyzedDescription
      ? "Resume saved. You can compare it with this job now."
      : "";
  } catch (error) {
    resumeStatus.textContent = error instanceof Error
      ? error.message
      : "Could not save this resume.";
  } finally {
    uploadResumeButton.disabled = false;
  }
}

async function removeResume(): Promise<void> {
  removeResumeButton.disabled = true;
  try {
    await api("/resume", "DELETE");
    hasSavedResume = false;
    compareButton.disabled = true;
    comparisonSection.hidden = true;
    await refreshResumeStatus();
  } catch (error) {
    resumeStatus.textContent = error instanceof Error
      ? `Could not remove the saved resume: ${error.message}`
      : "Could not remove the saved resume.";
  } finally {
    removeResumeButton.disabled = !hasSavedResume;
  }
}

async function compareWithResume(): Promise<void> {
  if (!analyzedDescription) {
    compareStatus.textContent = "Analyze a job description before comparing.";
    return;
  }
  if (!hasSavedResume && !await refreshResumeStatus()) {
    compareStatus.textContent = "Upload and save a PDF resume above to enable comparison.";
    resumeFileInput.focus();
    return;
  }
  compareButton.disabled = true;
  compareButton.textContent = "Comparing…";
  compareStatus.textContent = "Comparing your resume with the job…";
  comparisonSection.hidden = true;
  try {
    const result = await api<ResumeComparison>("/compare", "POST", {
      description: analyzedDescription,
    });
    $("match-summary").textContent = result.match_summary;
    addListItems("resume-strengths", result.strengths, "No clear resume evidence found.");
    addListItems("resume-gaps", result.gaps, "No notable gaps identified.");
    addListItems("resume-additions", result.suggested_additions, "No existing details to bring forward.");
    addListItems("resume-modifications", result.resume_modifications, "No specific edits suggested.");
    comparisonSection.hidden = false;
    compareStatus.textContent = "Comparison complete. Suggestions are based only on the resume text provided.";
  } catch (error) {
    compareStatus.textContent = error instanceof Error
      ? error.message
      : "Unable to compare this resume with the job.";
  } finally {
    compareButton.disabled = false;
    compareButton.textContent = "Compare with resume";
  }
}

async function clearHighlights(): Promise<void> {
  if (analyzedTabId === null) return;
  const tabId = analyzedTabId;
  analyzedTabId = null;
  analyzedPageUrl = null;
  try {
    await clearPageHighlights(tabId);
    status.textContent = "Page highlights cleared.";
  } catch (error) {
    status.textContent = error instanceof Error
      ? `Could not clear page highlights: ${error.message}`
      : "Could not clear page highlights.";
  }
}

analyzeButton.addEventListener("click", () => void analyze());
$("clear-button").addEventListener("click", () => void clearHighlights());
uploadResumeButton.addEventListener("click", () => void uploadResume());
removeResumeButton.addEventListener("click", () => void removeResume());
compareButton.addEventListener("click", () => void compareWithResume());

void chrome.storage.local.get("backendUrl").then(({ backendUrl: saved }) => {
  if (typeof saved !== "string") {
    backendInput.value = DEFAULT_BACKEND;
    return refreshResumeStatus();
  }
  try {
    backendInput.value = localBackendUrl(saved);
    return refreshResumeStatus();
  } catch {
    backendInput.value = DEFAULT_BACKEND;
    status.textContent = "A non-local backend setting was reset. Job descriptions are sent only to your local backend.";
    return refreshResumeStatus();
  }
}).catch((error: unknown) => {
  status.textContent = error instanceof Error
    ? `Could not load the saved backend setting: ${error.message}`
    : "Could not load the saved backend setting.";
});
