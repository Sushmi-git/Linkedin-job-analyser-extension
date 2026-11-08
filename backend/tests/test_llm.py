from types import SimpleNamespace

import pytest
from pydantic import BaseModel

import app.llm as llm
from app.llm import _completion
from app.schemas import JobAnalysis


def test_groq_request_uses_completion_tokens_and_low_gpt_oss_reasoning() -> None:
    captured: dict = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"summary":"ok"}'))]
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    assert _completion(client, "openai/gpt-oss-20b", "system", "prompt") == '{"summary":"ok"}'
    assert captured["max_completion_tokens"] == 3000
    assert captured["reasoning_effort"] == "low"
    assert "max_tokens" not in captured


def test_groq_request_omits_gpt_oss_reasoning_for_other_models() -> None:
    captured: dict = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"summary":"ok"}'))]
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    _completion(client, "other/model", "system", "prompt")

    assert "reasoning_effort" not in captured


def test_generate_json_retries_with_schema_guidance(monkeypatch) -> None:
    class Response(BaseModel):
        value: str

    prompts: list[str] = []
    responses = iter([{}, {"value": "ok"}])

    def request_json(_system: str, prompt: str, _model: str) -> dict:
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr(llm, "_request_json", request_json)

    result = llm.generate_json("Analyze this.", Response)

    assert result.value == "ok"
    assert len(prompts) == 2
    assert "previous response did not match" in prompts[1]


def test_generate_json_reports_schema_fields_without_response_data(monkeypatch) -> None:
    class Response(BaseModel):
        value: str

    monkeypatch.setattr(llm, "_request_json", lambda *_args: {"private": "do not log"})

    with pytest.raises(ValueError, match="value:missing") as error:
        llm.generate_json("Analyze this.", Response)

    assert "private" not in str(error.value)


def test_generate_json_normalizes_equivalent_highlight_categories(monkeypatch) -> None:
    response = {
        "summary": "Analyze the role.",
        "compulsory_skills": [],
        "preferred_skills": [],
        "other_requirements": [],
        "experience": None,
        "salary": None,
        "highlights": [
            {"text": "Python", "category": "compulsory skill"},
            {"text": "Kubernetes", "category": "preferred_skills"},
            {"text": "5 years", "category": "work-experience"},
        ],
    }
    calls = 0

    def request_json(*_args) -> dict:
        nonlocal calls
        calls += 1
        return response

    monkeypatch.setattr(llm, "_request_json", request_json)

    result = llm.generate_json("Analyze this.", JobAnalysis)

    assert [item.category for item in result.highlights] == [
        "required",
        "preferred",
        "experience",
    ]
    assert calls == 1


def test_generate_json_shortens_overlong_highlight_to_schema_limit(monkeypatch) -> None:
    long_phrase = " ".join(["requirement"] * 30)
    response = {
        "summary": "Analyze the role.",
        "compulsory_skills": [],
        "preferred_skills": [],
        "other_requirements": [],
        "experience": None,
        "salary": None,
        "highlights": [{"text": long_phrase, "category": "required"}],
    }
    monkeypatch.setattr(llm, "_request_json", lambda *_args: response)

    result = llm.generate_json("Analyze this.", JobAnalysis)

    assert len(result.highlights[0].text) <= 180
    assert long_phrase.startswith(result.highlights[0].text)


def test_comparison_prompt_preserves_braces_in_user_documents() -> None:
    prompt = llm.comparison_prompt(
        'Required skill: Python. Literal token {resume}.',
        'Built a tool that outputs "{description}" for templates.',
    )

    assert "Literal token {resume}." in prompt
    assert "{description}" in prompt
