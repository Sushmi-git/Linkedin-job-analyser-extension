from typing import Literal

from pydantic import BaseModel, Field


HighlightCategory = Literal["salary", "experience", "required", "preferred"]


class JobAnalysisRequest(BaseModel):
    description: str = Field(min_length=100, max_length=40000)


class ResumeUploadRequest(BaseModel):
    pdf_base64: str = Field(min_length=16, max_length=11_200_000)


class ResumeComparisonRequest(BaseModel):
    description: str = Field(min_length=100, max_length=40000)


class JobHighlight(BaseModel):
    text: str = Field(min_length=2, max_length=180)
    category: HighlightCategory


class JobAnalysis(BaseModel):
    summary: str = Field(min_length=1, max_length=1200)
    compulsory_skills: list[str] = Field(default_factory=list, max_length=20)
    preferred_skills: list[str] = Field(default_factory=list, max_length=20)
    other_requirements: list[str] = Field(default_factory=list, max_length=20)
    experience: str | None = Field(default=None, max_length=500)
    salary: str | None = Field(default=None, max_length=500)
    highlights: list[JobHighlight] = Field(default_factory=list, max_length=60)


class ResumeComparison(BaseModel):
    match_summary: str = Field(min_length=1, max_length=1200)
    strengths: list[str] = Field(default_factory=list, max_length=15)
    gaps: list[str] = Field(default_factory=list, max_length=15)
    suggested_additions: list[str] = Field(default_factory=list, max_length=15)
    resume_modifications: list[str] = Field(default_factory=list, max_length=15)
