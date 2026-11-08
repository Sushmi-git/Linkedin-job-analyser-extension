import json
import logging
import re
import time
from pathlib import Path
from time import perf_counter
from typing import TypeVar

from groq import Groq, RateLimitError
from pydantic import BaseModel, ValidationError

from app.config import get_settings

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
FALLBACK_MODEL = "openai/gpt-oss-120b"


def _template(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _completion(client: Groq, model: str, system: str, prompt: str) -> str:
    started = perf_counter()
    outcome = "error"
    try:
        result = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_completion_tokens=3000,
            **({"reasoning_effort": "low"} if model.startswith("openai/gpt-oss-") else {}),
        )
        outcome = "success"
    finally:
        logger.info(
            "Groq completion model=%s duration_ms=%.1f outcome=%s",
            model,
            (perf_counter() - started) * 1000,
            outcome,
        )
    content = result.choices[0].message.content
    if not content:
        raise ValueError("Groq returned an empty response.")
    return content


def _request_json(system: str, prompt: str, model_name: str) -> dict:
    started = perf_counter()
    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not configured in the backend environment.")
    client = Groq(api_key=settings.groq_api_key, timeout=30, max_retries=0)
    model = model_name or settings.groq_model
    try:
        for attempt in range(3):
            try:
                return json.loads(_completion(client, model, system, prompt))
            except RateLimitError:
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
                if model == FALLBACK_MODEL:
                    raise
                logger.warning("Groq rate limit on %s; retrying with fallback model.", model)
                model = FALLBACK_MODEL
                for fallback_attempt in range(2):
                    try:
                        return json.loads(_completion(client, model, system, prompt))
                    except RateLimitError:
                        if fallback_attempt == 1:
                            raise
                        time.sleep(2**fallback_attempt)
        raise RuntimeError("Groq request retries were exhausted.")
    finally:
        logger.info(
            "Groq request sequence duration_ms=%.1f",
            (perf_counter() - started) * 1000,
        )


def _normalize_highlight_categories(data: dict) -> dict:
    highlights = data.get("highlights")
    if not isinstance(highlights, list):
        return data

    aliases = {
        "salary": "salary",
        "compensation": "salary",
        "pay": "salary",
        "experience": "experience",
        "work_experience": "experience",
        "years_experience": "experience",
        "required": "required",
        "required_skill": "required",
        "required_skills": "required",
        "compulsory": "required",
        "compulsory_skill": "required",
        "compulsory_skills": "required",
        "mandatory": "required",
        "must_have": "required",
        "preferred": "preferred",
        "preferred_skill": "preferred",
        "preferred_skills": "preferred",
        "desirable": "preferred",
        "nice_to_have": "preferred",
    }
    normalized = dict(data)
    normalized_highlights = []
    for highlight in highlights:
        if not isinstance(highlight, dict):
            normalized_highlights.append(highlight)
            continue
        item = dict(highlight)
        category = item.get("category")
        if isinstance(category, str):
            key = "_".join(category.strip().lower().replace("-", " ").split())
            item["category"] = aliases.get(key, category)
        text = item.get("text")
        if isinstance(text, str) and len(text) > 180:
            shortened = text[:180]
            if " " in shortened:
                shortened = shortened.rsplit(" ", 1)[0]
            item["text"] = shortened
        normalized_highlights.append(item)
    normalized["highlights"] = normalized_highlights
    return normalized


def generate_json(
    prompt: str,
    response_model: type[T],
    system_prompt_name: str = "system.txt",
) -> T:
    started = perf_counter()
    system = _template(system_prompt_name)
    malformed_error: Exception | None = None
    try:
        for attempt in range(2):
            try:
                retry_prompt = prompt
                if attempt:
                    retry_prompt += (
                        "\n\nYour previous response did not match the required output. "
                        "Return one complete JSON object with all required fields and "
                        "correct value types. Do not include markdown or extra text."
                    )
                data = _request_json(system, retry_prompt, get_settings().groq_model)
                data = _normalize_highlight_categories(data)
                return response_model.model_validate(data)
            except json.JSONDecodeError as error:
                malformed_error = error
                logger.warning(
                    "Groq returned invalid JSON (error=%s, character=%s).",
                    error.msg,
                    error.pos,
                )
                if attempt == 1:
                    raise ValueError(
                        "Groq returned invalid JSON after a retry. Check the configured model and backend logs."
                    ) from error
            except ValidationError as error:
                malformed_error = error
                issues = error.errors(include_input=False)
                details = ", ".join(
                    f"{'.'.join(str(part) for part in issue['loc']) or 'response'}:{issue['type']}"
                    for issue in issues[:8]
                )
                logger.warning("Groq JSON did not match the response schema (%s).", details)
                if attempt == 0:
                    continue
                raise ValueError(
                    f"Groq returned JSON that does not match the analysis schema ({details}). "
                    "Check the configured model and backend logs."
                ) from error
        raise ValueError("Groq returned invalid JSON for the required response schema.") from malformed_error
    finally:
        logger.info(
            "LLM generation and validation duration_ms=%.1f",
            (perf_counter() - started) * 1000,
        )


def analysis_prompt(description: str) -> str:
    return _template("analysis.txt").replace(
        "{description}", json.dumps(description, ensure_ascii=False)
    )


def comparison_prompt(description: str, resume: str) -> str:
    values = {
        "description": json.dumps(description, ensure_ascii=False),
        "resume": json.dumps(resume, ensure_ascii=False),
    }
    return re.sub(
        r"\{(description|resume)\}",
        lambda match: values[match.group(1)],
        _template("comparison.txt"),
    )
