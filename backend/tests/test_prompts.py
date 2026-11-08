from app.llm import analysis_prompt


def test_analysis_prompt_includes_description_and_evidence_rules() -> None:
    prompt = analysis_prompt("Required: Python. Salary: $120,000 per year.")
    assert "Required: Python. Salary: $120,000 per year." in prompt
    assert "exact phrase copied from the description" in prompt
    assert '"compulsory_skills"' in prompt
    assert "{description}" not in prompt
