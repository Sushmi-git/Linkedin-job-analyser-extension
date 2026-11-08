import base64

from fastapi.testclient import TestClient

import app.main as main
from app.schemas import JobAnalysis, JobHighlight, ResumeComparison


client = TestClient(main.app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_analyze_returns_grounded_fields_and_exact_highlights(monkeypatch) -> None:
    description = (
        "Required: Python and SQL. Preferred: Kubernetes. "
        "Minimum 5 years of experience. Salary: $120,000-$150,000 per year."
    )
    analysis = JobAnalysis(
        summary="Build data products.",
        compulsory_skills=["Python", "SQL"],
        preferred_skills=["Kubernetes"],
        other_requirements=["Lead platform work."],
        experience="Minimum 5 years of experience",
        salary="Salary: $120,000-$150,000 per year",
        highlights=[
            JobHighlight(text="Python", category="required"),
            JobHighlight(text="Kubernetes", category="preferred"),
        ],
    )
    monkeypatch.setattr(main, "generate_json", lambda *_args: analysis)

    response = client.post("/analyze", json={"description": description})

    assert response.status_code == 200
    result = response.json()
    assert result["compulsory_skills"] == ["Python", "SQL"]
    assert result["preferred_skills"] == ["Kubernetes"]
    assert result["other_requirements"] == []
    assert result["experience"] == "Minimum 5 years of experience"
    assert result["salary"] == "Salary: $120,000-$150,000 per year"
    assert {item["category"] for item in result["highlights"]} == {
        "salary",
        "experience",
        "required",
        "preferred",
    }


def test_analyze_drops_salary_experience_and_skills_not_in_source(monkeypatch) -> None:
    description = "This role supports internal reporting and stakeholder meetings. " * 3
    monkeypatch.setattr(
        main,
        "generate_json",
        lambda *_args: JobAnalysis(
            summary="Review reporting needs.",
            compulsory_skills=["Python"],
            preferred_skills=[],
            other_requirements=[],
            experience="5 years",
            salary="$150,000",
            highlights=[
                JobHighlight(text="Python", category="required"),
                JobHighlight(text="$150,000", category="salary"),
            ],
        ),
    )

    response = client.post("/analyze", json={"description": description})

    assert response.status_code == 200
    assert response.json()["compulsory_skills"] == []
    assert response.json()["experience"] is None
    assert response.json()["salary"] is None
    assert response.json()["highlights"] == []


def test_analyze_extracts_explicit_year_range_when_model_misses_it(monkeypatch) -> None:
    experience = (
        "2–4 years in AI operations, workflow automation, business analysis, "
        "or growth strategy (digital marketing / ad-tech preferred)."
    )
    description = (
        f"Requirements: {experience} Hands-on experience building automated "
        "workflows on low-code platforms. " * 2
    )
    monkeypatch.setattr(
        main,
        "generate_json",
        lambda *_args: JobAnalysis(
            summary="Support AI operations.",
            compulsory_skills=[],
            preferred_skills=[],
            other_requirements=[],
            experience=None,
            salary=None,
            highlights=[],
        ),
    )

    response = client.post("/analyze", json={"description": description})

    assert response.status_code == 200
    result = response.json()
    assert result["experience"] == experience
    assert {"text": experience, "category": "experience"} in result["highlights"]


def test_analyze_requires_a_sufficient_description() -> None:
    response = client.post("/analyze", json={"description": "Too short"})
    assert response.status_code == 422


def test_resume_upload_saves_pdf_locally_and_can_be_removed(monkeypatch, tmp_path) -> None:
    resume_path = tmp_path / "resume.pdf"
    monkeypatch.setattr(main, "RESUME_PATH", resume_path)
    monkeypatch.setattr(main, "_extract_resume_text", lambda _data: "Resume text " * 20)
    pdf = b"%PDF-1.7\nfirst resume"

    upload = client.post(
        "/resume/upload",
        json={"pdf_base64": base64.b64encode(pdf).decode("ascii")},
    )

    assert upload.status_code == 200
    assert resume_path.read_bytes() == pdf
    assert client.get("/resume/status").json() == {"has_resume": True}

    removed = client.delete("/resume")

    assert removed.status_code == 200
    assert not resume_path.exists()
    assert client.get("/resume/status").json() == {"has_resume": False}


def test_resume_upload_rejects_non_pdf(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(main, "RESUME_PATH", tmp_path / "resume.pdf")

    response = client.post(
        "/resume/upload",
        json={"pdf_base64": base64.b64encode(b"not a PDF file").decode("ascii")},
    )

    assert response.status_code == 422
    assert "not a valid PDF" in response.json()["detail"]


def test_compare_uses_saved_resume_and_job_description(monkeypatch) -> None:
    description = "Required: Python and SQL. " * 6
    comparison = ResumeComparison(
        match_summary="The resume shows relevant Python experience.",
        strengths=["Python project experience"],
        gaps=["SQL is not clearly evidenced"],
        suggested_additions=["Bring forward the data pipeline project"],
        resume_modifications=["Add the project's measurable impact if accurate."],
    )
    prompts: list[str] = []
    monkeypatch.setattr(main, "_load_resume_text", lambda: "Resume: built Python data pipelines.")
    monkeypatch.setattr(
        main,
        "generate_json",
        lambda prompt, _model, _system_prompt: prompts.append(prompt) or comparison,
    )

    response = client.post("/compare", json={"description": description})

    assert response.status_code == 200
    assert response.json()["gaps"] == ["SQL is not clearly evidenced"]
    assert len(prompts) == 1
    assert "Required: Python and SQL" in prompts[0]
    assert "built Python data pipelines" in prompts[0]


def test_compare_requires_saved_resume(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(main, "RESUME_PATH", tmp_path / "missing.pdf")

    response = client.post("/compare", json={"description": "A job description. " * 8})

    assert response.status_code == 404
    assert "Upload a PDF resume first" in response.json()["detail"]
