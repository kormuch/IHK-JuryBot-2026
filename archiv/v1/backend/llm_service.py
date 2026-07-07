"""
LLM service — dual-provider support for Groq and Gemini.

Methods:
    evaluate_repo()           — Score repo against 5-category rubric (Architecture, Code Quality,
                                 Completeness, Innovation, Documentation). Returns JSON with scores + German justifications.
    generate_tasks()          — Generate 2-3 follow-up tasks based on repo weaknesses. Tasks in German.
    evaluate_presentation()   — Score presentation quality from STT transcript.
    evaluate_task_solution()  — Compare original vs updated repo after follow-up task execution.

All LLM calls use temperature=0.3 and JSON response format.
Internal evaluation language: English. Output justifications: German.
"""

import json
import logging

from backend.config import Settings

logger = logging.getLogger(__name__)

EVALUATION_SYSTEM_PROMPT = """You are a strict but fair technical jury member evaluating hackathon projects.
You receive a structured analysis of a team's code repository.

EVALUATION RUBRIC — score each category 1-10:

1. **Architecture & Design** (25% weight)
   - Clean project structure with logical separation of concerns
   - Appropriate technology choices for the problem
   - Scalability considerations
   - Score 1-3: monolithic mess, no structure, wrong tech
   - Score 4-6: basic structure but issues, some separation
   - Score 7-8: clean architecture, good separation, appropriate tech
   - Score 9-10: exemplary design, clear patterns, production-ready structure

2. **Code Quality** (20% weight)
   - Readability, naming conventions, consistency
   - Error handling and edge cases
   - No obvious anti-patterns or security issues
   - Score 1-3: unreadable, inconsistent, no error handling
   - Score 4-6: readable but inconsistent, basic error handling
   - Score 7-8: clean, consistent, proper error handling
   - Score 9-10: exemplary quality, defensive coding, well-tested

3. **Completeness** (20% weight)
   - Does the solution actually work end-to-end?
   - How much of the stated scope is implemented vs placeholder/TODO?
   - Are core features functional or just stubs?
   - Score 1-3: mostly stubs, nothing works
   - Score 4-6: partial implementation, core works but gaps
   - Score 7-8: mostly complete, main features work
   - Score 9-10: fully implemented, polished, no dead code

4. **Innovation** (15% weight)
   - Creative problem-solving approaches
   - Smart use of tools, APIs, or libraries
   - Non-obvious solutions, going beyond the obvious
   - Score 1-3: boilerplate only, no creativity
   - Score 4-6: some creative elements
   - Score 7-8: clever approaches, good API usage
   - Score 9-10: truly innovative, surprising solutions

5. **Documentation** (10% weight)
   - README quality (setup instructions, feature description, architecture overview)
   - API documentation if applicable
   - Inline comments where needed (not excessive)
   - Score 1-3: no README or empty, no docs
   - Score 4-6: basic README, minimal docs
   - Score 7-8: good README, API docs, clear setup instructions
   - Score 9-10: comprehensive docs, architecture diagrams, examples

IMPORTANT INSTRUCTIONS:
- Be critical. Hackathon projects are time-constrained, but don't inflate scores.
- Reference SPECIFIC files and code in your justifications.
- Each justification must be 2-3 sentences in GERMAN.
- The overall summary must be in GERMAN (3-5 sentences).
- Return valid JSON only.

Response format:
{
  "scores": {
    "architecture": {"score": <1-10>, "justification": "<German text>"},
    "code_quality": {"score": <1-10>, "justification": "<German text>"},
    "completeness": {"score": <1-10>, "justification": "<German text>"},
    "innovation": {"score": <1-10>, "justification": "<German text>"},
    "documentation": {"score": <1-10>, "justification": "<German text>"}
  },
  "overall_score": <weighted average as float>,
  "summary": "<German text, 3-5 sentences overall assessment>"
}"""

TASK_GENERATION_SYSTEM_PROMPT = """You are a hackathon jury member generating follow-up tasks for teams.
Based on the repository analysis and evaluation scores, generate 2-3 follow-up tasks.

REQUIREMENTS for each task:
- Must be feasible in 15-20 minutes
- Must be relevant to the team's existing codebase
- Should target gaps, weaknesses, or missing features found in the analysis
- Should reveal whether the team truly understands their own code
- Difficulty should be calibrated: one easier, one harder
- All text must be in GERMAN

IMPORTANT: Tasks should be specific and actionable, referencing actual files/endpoints/features from their repo.

Response format (JSON):
{
  "tasks": [
    {
      "title": "<German, short title>",
      "description": "<German, 2-4 sentences describing exactly what to do>",
      "difficulty": "easy|medium|hard",
      "rationale": "<German, why this task is relevant based on analysis>"
    }
  ]
}"""

PRESENTATION_EVAL_SYSTEM_PROMPT = """You are a hackathon jury member evaluating a team's live presentation.
You have the repo analysis and existing scores for context. Now evaluate the PRESENTATION.

Evaluate the presentation transcript for:
- Clarity of explanation
- Logical structure (intro, demo, conclusion)
- Technical depth vs buzzword usage
- How well they explained their architecture decisions
- Demo quality (did they show it working?)

Score the Presentation category 1-10:
- Score 1-3: confusing, no structure, no demo
- Score 4-6: basic explanation, some structure
- Score 7-8: clear, well-structured, good demo
- Score 9-10: excellent communication, compelling narrative, flawless demo

Response format (JSON):
{
  "presentation": {"score": <1-10>, "justification": "<German, 2-3 sentences>"},
  "updated_summary": "<German, updated overall summary incorporating presentation>"
}"""

TASK_EVAL_SYSTEM_PROMPT = """You are a hackathon jury member evaluating how well a team completed an assigned follow-up task.

You receive:
1. The original repo analysis (before task)
2. The updated repo analysis (after task)
3. The task that was assigned

Evaluate:
- Did they complete the task as specified?
- Quality of the implementation
- Did they break anything in the process?
- Speed and correctness under pressure

Response format (JSON):
{
  "task_score": <1-10>,
  "justification": "<German, 2-3 sentences>",
  "changes_summary": "<German, what changed between original and updated repo>"
}"""


class LLMService:
    def __init__(self, config: Settings):
        self.config = config
        self.provider = config.LLM_PROVIDER.lower()

    async def evaluate_repo(self, analysis: dict) -> dict:
        """Send repo analysis to LLM with scoring rubric. Return structured scores."""
        user_prompt = self._build_repo_prompt(analysis)
        raw = await self._call_llm(EVALUATION_SYSTEM_PROMPT, user_prompt)
        return self._parse_json(raw)

    async def generate_tasks(self, analysis: dict, scores: dict) -> list:
        """Generate 2-3 follow-up tasks based on analysis and scores."""
        user_prompt = (
            "REPO ANALYSIS:\n"
            f"{json.dumps(analysis['summary'], indent=2, ensure_ascii=False)}\n\n"
            "EVALUATION SCORES:\n"
            f"{json.dumps(scores, indent=2, ensure_ascii=False)}\n\n"
            "FILE TREE:\n"
            f"{chr(10).join(analysis['structure']['file_tree'][:100])}\n\n"
            "Generate 2-3 follow-up tasks targeting the weaknesses and gaps."
        )
        raw = await self._call_llm(TASK_GENERATION_SYSTEM_PROMPT, user_prompt)
        result = self._parse_json(raw)
        return result.get("tasks", [])

    async def evaluate_presentation(
        self, transcript: str, repo_analysis: dict, repo_scores: dict
    ) -> dict:
        """Evaluate presentation from transcript + repo context."""
        user_prompt = (
            "REPO SUMMARY:\n"
            f"{json.dumps(repo_analysis.get('summary', {}), indent=2, ensure_ascii=False)}\n\n"
            "EXISTING SCORES:\n"
            f"{json.dumps(repo_scores, indent=2, ensure_ascii=False)}\n\n"
            "PRESENTATION TRANSCRIPT:\n"
            f"{transcript}\n\n"
            "Evaluate the presentation quality."
        )
        raw = await self._call_llm(PRESENTATION_EVAL_SYSTEM_PROMPT, user_prompt)
        return self._parse_json(raw)

    async def evaluate_task_solution(
        self,
        original_analysis: dict,
        new_analysis: dict,
        task: dict,
    ) -> dict:
        """Compare original vs updated repo after task execution."""
        user_prompt = (
            "ASSIGNED TASK:\n"
            f"{json.dumps(task, indent=2, ensure_ascii=False)}\n\n"
            "ORIGINAL REPO SUMMARY:\n"
            f"{json.dumps(original_analysis.get('summary', {}), indent=2, ensure_ascii=False)}\n\n"
            "ORIGINAL FILE COUNT: "
            f"{original_analysis['structure']['total_files']}\n\n"
            "UPDATED REPO SUMMARY:\n"
            f"{json.dumps(new_analysis.get('summary', {}), indent=2, ensure_ascii=False)}\n\n"
            "UPDATED FILE COUNT: "
            f"{new_analysis['structure']['total_files']}\n\n"
            "NEW/CHANGED FILES (in updated but different):\n"
        )
        # Find changed files by comparing key_files content
        orig_files = set(original_analysis.get("key_files", {}).keys())
        new_files = set(new_analysis.get("key_files", {}).keys())
        added = new_files - orig_files
        for f in sorted(added):
            user_prompt += f"\n--- NEW FILE: {f} ---\n{new_analysis['key_files'][f][:2000]}\n"

        # Show changed content for existing files
        for f in orig_files & new_files:
            if original_analysis["key_files"].get(f) != new_analysis["key_files"].get(f):
                user_prompt += f"\n--- CHANGED FILE: {f} ---\n{new_analysis['key_files'][f][:2000]}\n"

        raw = await self._call_llm(TASK_EVAL_SYSTEM_PROMPT, user_prompt)
        return self._parse_json(raw)

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call Groq or Gemini based on config. Return raw response text."""
        if self.provider == "groq":
            return await self._call_groq(system_prompt, user_prompt)
        elif self.provider == "gemini":
            return await self._call_gemini(system_prompt, user_prompt)
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider}")

    async def _call_groq(self, system_prompt: str, user_prompt: str) -> str:
        from groq import AsyncGroq

        client = AsyncGroq(api_key=self.config.GROQ_API_KEY)
        response = await client.chat.completions.create(
            model=self.config.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        return response.choices[0].message.content

    async def _call_gemini(self, system_prompt: str, user_prompt: str) -> str:
        from google import genai

        client = genai.Client(api_key=self.config.GEMINI_API_KEY)
        response = await client.aio.models.generate_content(
            model=self.config.LLM_MODEL,
            contents=user_prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        return response.text

    def _build_repo_prompt(self, analysis: dict) -> str:
        """Build a detailed prompt from repo analysis for evaluation."""
        summary = analysis["summary"]
        structure = analysis["structure"]
        key_files = analysis["key_files"]

        parts = [
            "REPOSITORY ANALYSIS",
            "=" * 40,
            f"Total files: {summary['total_files']}",
            f"Total lines: {summary['total_lines']}",
            f"Languages: {json.dumps(summary['languages'], ensure_ascii=False)}",
            f"Frameworks: {', '.join(summary['frameworks']) if summary['frameworks'] else 'None detected'}",
            f"Entry points: {', '.join(summary['entry_points']) if summary['entry_points'] else 'None detected'}",
            f"Has README: {summary['has_readme']}",
            f"Has Tests: {summary['has_tests']}",
            f"Has Docker: {summary['has_docker']}",
            "",
            "FILE TREE:",
            "\n".join(f"  {f}" for f in structure["file_tree"][:150]),
            "",
            "KEY FILE CONTENTS:",
            "=" * 40,
        ]

        for filepath, content in key_files.items():
            parts.append(f"\n--- {filepath} ---")
            parts.append(content)

        parts.append("\n" + "=" * 40)
        parts.append(
            "Evaluate this repository according to the rubric. "
            "Be specific, reference files, and write justifications in German."
        )

        return "\n".join(parts)

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """Parse JSON from LLM response, handling potential markdown wrapping."""
        text = raw.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM response as JSON: %s", text[:500])
            return {"error": "Failed to parse LLM response", "raw": text[:1000]}
