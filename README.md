# RoleLens | AI Job Search Assistant

## Problem

Reviewing long job descriptions and comparing them with a resume is repetitive. Key requirements—such as must-have skills, experience, salary, and preferred qualifications—can be easy to miss.

## Solution

RoleLens is a locally run Chrome extension that turns a LinkedIn job description into a concise, structured breakdown, highlights relevant phrases, and optionally compares the role with a saved resume. It surfaces strengths, requirements not clearly evidenced, and truthful resume-edit suggestions.

## How it works

The extension reads the visible job description (or accepts pasted text) and sends it to a local FastAPI backend. The backend calls Groq for structured analysis, checks quoted details against the source text, and returns results for the extension to display and highlight. For resume comparison, it extracts text from a local PDF and analyzes it alongside the job description.

<img width="460" height="840" alt="image" src="https://github.com/user-attachments/assets/2c810855-f962-46b5-9654-38214f692559" />
<img width="428" height="878" alt="image" src="https://github.com/user-attachments/assets/0acbd311-bad6-47cd-b9ff-cfb5c6fdc331" />
<img width="555" height="810" alt="image" src="https://github.com/user-attachments/assets/7ee2aa8a-19f7-45b3-8763-68803376d297" />


The AI is Groq-hosted **OpenAI GPT-OSS 20B** by default, with **GPT-OSS 120B** as a rate-limit fallback. Prompts request grounded JSON; there is no fine-tuning, embedding model, vector database, or retrieval corpus.

## AI and process-improvement focus

This project explores how to make an information-heavy task faster and more consistent: extracting decision-relevant details, separating explicit requirements from preferences, and presenting the output where it is useful. It combines an LLM with deterministic checks for evidence and experience ranges, plus a human-in-the-loop workflow—the user reviews every insight and decides whether to act on it. It is a local prototype, not a production hiring or candidate-scoring system.

## Tech stack

- **Product/UI:** Chrome Manifest V3, TypeScript, HTML, CSS
- **API:** Python, FastAPI, Uvicorn, Pydantic
- **AI:** Groq API, GPT-OSS models, prompt-based structured generation
- **Document handling:** pypdf for text-based PDF resumes
- **Build and validation:** Vite, CRXJS, pytest, TypeScript

## Run locally

Requirements: Python 3.11+, Node.js 20+, Chrome, and a Groq API key.

1. Build the extension:
   ```powershell
   cd extension
   npm install
   npm run build
   ```
   In `chrome://extensions`, enable Developer mode, select **Load unpacked**,
   and choose `extension/dist`.
2. Set up the backend:
   ```powershell
   cd backend
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   Copy-Item .env.example .env
   ```
   Add `GROQ_API_KEY`, `GROQ_MODEL`, and the extension's
   `EXTENSION_ORIGIN` to `backend/.env`, then run:
   ```powershell
   uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
   ```
3. Open a LinkedIn job, click RoleLens, and analyze it. Optionally upload a text-based PDF resume to compare it with the analyzed role.

## Privacy

The API listens on your computer; no public hosting is required. Job text is sent to Groq for analysis. Resume PDFs stay in the local, Git-ignored `backend/data/` folder, but comparison sends the extracted resume text and job description to Groq. Scanned PDFs are not supported.

## Checks

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend\tests
npm --prefix extension run typecheck
npm --prefix extension run build
```
