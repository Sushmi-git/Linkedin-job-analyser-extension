export type HighlightCategory = "salary" | "experience" | "required" | "preferred";

export interface JobHighlight {
  text: string;
  category: HighlightCategory;
}

export interface JobAnalysis {
  summary: string;
  compulsory_skills: string[];
  preferred_skills: string[];
  other_requirements: string[];
  experience: string | null;
  salary: string | null;
  highlights: JobHighlight[];
}

export interface ResumeComparison {
  match_summary: string;
  strengths: string[];
  gaps: string[];
  suggested_additions: string[];
  resume_modifications: string[];
}

export interface Message {
  type: string;
  [key: string]: unknown;
}
