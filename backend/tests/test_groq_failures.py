from app.main import _groq_failure


def test_groq_failure_messages_are_actionable_and_do_not_include_secrets() -> None:
    assert _groq_failure(401) == (
        503,
        "Groq rejected the configured API key (HTTP 401). Check GROQ_API_KEY in backend/.env and restart the backend.",
    )
    assert "GROQ_MODEL" in _groq_failure(404)[1]
    assert "backend log" in _groq_failure(400)[1]
    assert "Wait and retry" in _groq_failure(429)[1]


def test_unknown_groq_error_recommends_backend_logs() -> None:
    assert _groq_failure(502) == (
        502,
        "Groq returned HTTP 502. Check the backend log for details.",
    )
