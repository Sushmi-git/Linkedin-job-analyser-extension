from contextlib import asynccontextmanager
import base64
import binascii
from io import BytesIO
import logging
from pathlib import Path
import re
from time import perf_counter

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from groq import APIConnectionError, APIStatusError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings
from app.llm import analysis_prompt, comparison_prompt, generate_json
from app.logging_config import configure_logging
from app.schemas import (
    JobAnalysis,
    JobAnalysisRequest,
    JobHighlight,
    ResumeComparison,
    ResumeComparisonRequest,
    ResumeUploadRequest,
)

logger = logging.getLogger(__name__)
configure_logging()
RESUME_PATH = Path(__file__).resolve().parents[1] / "data" / "resume.pdf"
MAX_RESUME_BYTES = 8 * 1024 * 1024
MAX_RESUME_PAGES = 50
MAX_RESUME_TEXT_CHARS = 50000


def _groq_failure(status_code: int) -> tuple[int, str]:
    if status_code == 401:
        return 503, "Groq rejected the configured API key (HTTP 401). Check GROQ_API_KEY in backend/.env and restart the backend."
    if status_code == 403:
        return 503, "Groq denied access to the configured model. Check your Groq account and model access."
    if status_code == 404:
        return 503, "Groq could not find the configured model. Check GROQ_MODEL in backend/.env."
    if status_code == 429:
        return 503, "Groq rate limits were reached for both the configured and fallback models. Wait and retry."
    if status_code == 400:
        return 502, "Groq rejected the request. Check GROQ_MODEL and the backend log for the rejected request parameter."
    return 502, f"Groq returned HTTP {status_code}. Check the backend log for details."


def _raise_upstream_error(error: Exception) -> None:
    if isinstance(error, APIStatusError):
        response_status, detail = _groq_failure(error.status_code)
        if error.status_code == 400 and isinstance(error.body, dict):
            payload = error.body.get("error")
            if isinstance(payload, dict):
                code = payload.get("code")
                parameter = payload.get("param")
                logger.error(
                    "Groq API returned HTTP 400 (code=%s, parameter=%s).",
                    code[:80] if isinstance(code, str) else "unknown",
                    parameter[:80] if isinstance(parameter, str) else "unknown",
                )
            else:
                logger.error("Groq API returned HTTP 400.")
        else:
            logger.error("Groq API returned HTTP %s.", error.status_code)
        raise HTTPException(status_code=response_status, detail=detail) from error
    if isinstance(error, APIConnectionError):
        logger.error("Could not connect to the Groq API.")
        raise HTTPException(
            status_code=503,
            detail="Could not connect to the Groq API. Check the backend's internet connection and retry.",
        ) from error
    raise error


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="RoleLens | LinkedIn Job Analyzer", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().extension_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def log_request(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "Unhandled error handling %s %s after %.1f ms.",
            request.method,
            request.url.path,
            (perf_counter() - started) * 1000,
        )
        raise
    logger.info(
        "%s %s returned HTTP %s in %.1f ms.",
        request.method,
        request.url.path,
        response.status_code,
        (perf_counter() - started) * 1000,
    )
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _retain_evidence(analysis: JobAnalysis, description: str) -> JobAnalysis:
    normalized_description = " ".join(description.split()).casefold()

    def is_quoted_evidence(value: str | None) -> bool:
        return value is not None and " ".join(value.split()).casefold() in normalized_description

    analysis.experience = analysis.experience if is_quoted_evidence(analysis.experience) else None
    if analysis.experience is None:
        analysis.experience = _extract_explicit_experience(description)
    analysis.salary = analysis.salary if is_quoted_evidence(analysis.salary) else None
    analysis.compulsory_skills = [
        item for item in analysis.compulsory_skills if is_quoted_evidence(item)
    ]
    analysis.preferred_skills = [
        item for item in analysis.preferred_skills if is_quoted_evidence(item)
    ]
    analysis.other_requirements = [
        item for item in analysis.other_requirements if is_quoted_evidence(item)
    ]
    analysis.highlights = [
        item for item in analysis.highlights if is_quoted_evidence(item.text)
    ]

    existing = {(item.text.casefold(), item.category) for item in analysis.highlights}
    for text, category in (
        (analysis.salary, "salary"),
        (analysis.experience, "experience"),
        *((item, "required") for item in analysis.compulsory_skills),
        *((item, "preferred") for item in analysis.preferred_skills),
    ):
        highlight_text = _shorten_exact_phrase(text, 180) if text else None
        if highlight_text and (highlight_text.casefold(), category) not in existing:
            analysis.highlights.append(JobHighlight(text=highlight_text, category=category))
            existing.add((highlight_text.casefold(), category))
    return analysis


def _shorten_exact_phrase(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    shortened = text[:limit]
    return shortened.rsplit(" ", 1)[0] if " " in shortened else shortened


def _extract_explicit_experience(description: str) -> str | None:
    year_pattern = re.compile(
        r"\b(?:at least\s+|minimum(?: of)?\s+)?"
        r"\d+(?:\s*(?:-|–|—|to)\s*\d+|\s*\+)?\s+years?"
        r"(?:['’]?\s+(?:of\s+)?experience\b|['’]\s+experience\b|\s+"
        r"(?:in|with|working|building|managing|leading|developing|using)\b)",
        re.IGNORECASE,
    )
    match = year_pattern.search(description)
    if not match:
        return None

    start = match.start()
    end_candidates = [
        position
        for delimiter in (".", "!", "?", "\n", ";")
        if (position := description.find(delimiter, match.end())) >= 0
    ]
    end = min(end_candidates) + 1 if end_candidates else len(description)
    phrase = description[start:end].strip()
    return _shorten_exact_phrase(phrase, 500) if phrase else None


def _extract_resume_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("The uploaded file is not a valid PDF.")
    try:
        reader = PdfReader(BytesIO(pdf_bytes), strict=False)
        if reader.is_encrypted:
            raise ValueError("Password-protected PDFs are not supported. Upload an unlocked PDF.")
        if len(reader.pages) > MAX_RESUME_PAGES:
            raise ValueError(f"Resume PDFs must have {MAX_RESUME_PAGES} pages or fewer.")
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except PdfReadError as error:
        raise ValueError("The uploaded PDF could not be read. Try exporting it again as a PDF.") from error
    if len(text) < 100:
        raise ValueError(
            "The PDF contains too little selectable text. Scanned/image-only resumes are not supported; upload a text-based PDF."
        )
    if len(text) > MAX_RESUME_TEXT_CHARS:
        raise ValueError(f"Extracted resume text exceeds {MAX_RESUME_TEXT_CHARS} characters.")
    return text


def _load_resume_text() -> str:
    if not RESUME_PATH.is_file():
        raise HTTPException(status_code=404, detail="No resume is saved yet. Upload a PDF resume first.")
    try:
        return _extract_resume_text(RESUME_PATH.read_bytes())
    except OSError as error:
        logger.exception("Could not read the locally saved resume.")
        raise HTTPException(status_code=500, detail="The saved resume could not be read.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/analyze", response_model=JobAnalysis)
async def analyze_job(body: JobAnalysisRequest) -> JobAnalysis:
    started = perf_counter()
    try:
        prompt = analysis_prompt(body.description)
        analysis = await run_in_threadpool(generate_json, prompt, JobAnalysis)
        analysis = _retain_evidence(analysis, body.description)
        logger.info(
            "POST /analyze stage=analysis duration_ms=%.1f",
            (perf_counter() - started) * 1000,
        )
        return analysis
    except (RuntimeError, ValueError) as error:
        logger.exception("Job description analysis failed due to a backend configuration or data error.")
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (APIStatusError, APIConnectionError) as error:
        _raise_upstream_error(error)
    except Exception as error:
        logger.exception("Job description analysis failed.")
        raise HTTPException(status_code=502, detail="Unable to analyze this job description.") from error


@app.get("/resume/status")
async def resume_status() -> dict[str, bool]:
    return {"has_resume": RESUME_PATH.is_file()}


@app.post("/resume/upload")
async def upload_resume(body: ResumeUploadRequest) -> dict[str, str]:
    try:
        pdf_bytes = base64.b64decode(body.pdf_base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise HTTPException(status_code=400, detail="Resume upload must be valid base64-encoded PDF data.") from error
    if len(pdf_bytes) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=413, detail="Resume PDF must be 8 MB or smaller.")
    try:
        _extract_resume_text(pdf_bytes)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    temporary_path = RESUME_PATH.with_suffix(".pdf.tmp")
    try:
        RESUME_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.write_bytes(pdf_bytes)
        temporary_path.replace(RESUME_PATH)
    except OSError as error:
        logger.exception("Could not save the local resume.")
        raise HTTPException(status_code=500, detail="The resume could not be saved locally.") from error
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return {"status": "saved"}


@app.delete("/resume")
async def delete_resume() -> dict[str, str]:
    try:
        RESUME_PATH.unlink(missing_ok=True)
    except OSError as error:
        logger.exception("Could not remove the local resume.")
        raise HTTPException(status_code=500, detail="The saved resume could not be removed.") from error
    return {"status": "removed"}


@app.post("/compare", response_model=ResumeComparison)
async def compare_resume(body: ResumeComparisonRequest) -> ResumeComparison:
    resume_text = _load_resume_text()
    try:
        prompt = comparison_prompt(body.description, resume_text)
        return await run_in_threadpool(
            generate_json,
            prompt,
            ResumeComparison,
            "comparison_system.txt",
        )
    except (RuntimeError, ValueError) as error:
        logger.exception("Resume comparison failed due to a backend configuration or data error.")
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (APIStatusError, APIConnectionError) as error:
        _raise_upstream_error(error)
    except Exception as error:
        logger.exception("Resume comparison failed.")
        raise HTTPException(status_code=502, detail="Unable to compare this resume with the job.") from error
