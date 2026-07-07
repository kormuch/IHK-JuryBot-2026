# IHK JuryBot 2026 — Concept

**Event:** Kollege Codex — IHK Innovationstage Zollernalb | Mi, 08. Juli 2026
**Venue:** Theben AG, Haigerloch (mixed: on-site jury + remote teams via MS Teams)
**Role:** One AI juror among human jurors
**Teams:** 5
**Language:** Bot speaks German (TTS), LLM evaluates internally in English. Participants speak whatever they want (Whisper auto-detects). Written evaluation output in German.

---

## Core Flow

```
1. REPO ANALYSIS (pre-event / before team presents)
   Teams submit repos → Bot reads README, code, configs, structure
   → Generates: understanding of architecture, completeness, quality
   → Generates: tailored follow-up task per team

2. PRESENTATION (5 min)
   Team presents live (MS Teams / on-site)
   → Audio captured via separate mic → STT → transcript
   → Bot builds context: repo analysis + presentation transcript

3. TASK ASSIGNMENT
   Bot presents a NEW TASK to the team
   → Task is tailored to the team's current solution state
   → Based on gaps, weaknesses, or extension opportunities found in repo analysis
   → TTS speaks the task aloud

4. TASK EXECUTION
   Team works on the task (timeboxed)

5. EVALUATION (5 min window)
   Bot evaluates:
   a) Original repo submission (code quality, architecture, completeness)
   b) Presentation quality (from transcript)
   c) Task solution (new code/changes submitted after task)
   → LLM generates structured evaluation
   → Displayed on review screen for human approval before submission
```

---

## Scoring Rubric (self-defined)

Each category scored 1–10, weighted:

| Category | Weight | What's evaluated |
|---|---|---|
| **Architecture & Design** | 25% | Clean structure, separation of concerns, scalability, appropriate tech choices |
| **Code Quality** | 20% | Readability, consistency, error handling, no obvious anti-patterns |
| **Completeness** | 20% | Does the solution actually work? How much of the stated scope is implemented vs. placeholder? |
| **Innovation** | 15% | Creative approaches, smart use of tools/APIs, non-obvious solutions |
| **Documentation** | 10% | README quality, API docs, setup instructions, inline comments where needed |
| **Presentation** | 10% | Clarity, structure, demo quality (from transcript analysis) |

**Total: weighted sum → 1–10 final score**

Each category gets a 2–3 sentence justification, not just a number.

---

## Task Generation Logic

The follow-up task must be:
- **Feasible** within the timeboxed window (15–20 min?)
- **Relevant** to the team's existing solution (not a random feature)
- **Revealing** — exposes whether the team truly understands their own codebase
- **Comparable** — similar difficulty across teams (LLM must calibrate)

Examples of generated tasks:
- "Your API has no input validation on the /products endpoint. Add schema validation and return proper 422 errors."
- "Your ingestion pipeline handles CSV but your README claims XML support. Implement XML ingestion."
- "Add a /health endpoint that checks DB connectivity and returns system status."

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   JuryBot UI                    │
│         (Web App — browser on jury laptop)      │
│                                                 │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ Team     │  │ Live     │  │ Evaluation    │  │
│  │ Selector │  │ Transcript│  │ Review/Submit │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
└──────────────────┬──────────────────────────────┘
                   │
         ┌─────────┴─────────┐
         │   Backend (API)   │
         │   Python/FastAPI  │
         └──┬──────┬──────┬──┘
            │      │      │
     ┌──────┘      │      └──────┐
     ▼             ▼             ▼
┌─────────┐  ┌──────────┐  ┌─────────┐
│ Repo    │  │ STT      │  │ LLM     │
│ Analyzer│  │ (Whisper/ │  │ (Groq/  │
│         │  │ Deepgram) │  │ Gemini) │
└─────────┘  └──────────┘  └─────────┘
                                │
                           ┌────┴────┐
                           │ TTS     │
                           │ (edge/  │
                           │ browser)│
                           └─────────┘
```

---

## Tech Stack

| Component | Tech | Why |
|---|---|---|
| Backend | Python + FastAPI | Fast to build, async, good LLM ecosystem |
| Frontend | HTML/JS (single page) | No framework overhead, 6 days |
| STT | Whisper API or Deepgram | Reliable, German-capable |
| LLM | Groq (Llama) or Gemini Flash | Fast inference, free/cheap tier |
| TTS | Browser SpeechSynthesis or Edge TTS | Zero cost, good German voices |
| Repo Analysis | git clone + AST parsing + LLM summarization | LLM reads files, scores structure |
| Storage | SQLite | One laptop, 5 teams, no need for PG |
| Deployment | Local (jury laptop) | No cloud dependency at venue |

---

## Repo Analyzer — Detail

Input: Git repo URL or local path

Steps:
1. **Structure scan:** list all files, detect languages, frameworks, identify entry points
2. **README parse:** extract stated goals, setup instructions, claimed features
3. **Code analysis:** read key files (max ~50 files, prioritize by relevance)
   - Entry point (main.py, index.ts, etc.)
   - Config files (docker-compose, .env.example, requirements.txt, package.json)
   - API routes / endpoints
   - Database models / schemas
   - Tests (if any)
4. **LLM evaluation:** send structured summary to LLM with rubric → get scores + justifications
5. **Task generation:** based on gaps found → generate 2–3 candidate tasks → pick best fit
6. **Output:** JSON with scores, justifications, generated task, raw analysis

---

## UI Screens

### 1. Dashboard
- 5 team cards with status (pending / analyzing / presenting / task / evaluated)
- Click to enter team view

### 2. Team View — Repo Analysis
- Repo summary (auto-generated)
- Score breakdown (pre-presentation, code-only)
- Generated follow-up task (editable before assigning)

### 3. Team View — Live Session
- Running transcript (STT feed)
- Task assignment button (TTS speaks task)
- Timer

### 4. Team View — Evaluation
- Final scores (all categories)
- LLM-generated justifications (editable)
- Submit button (human approval required)

### 5. Results Overview
- All 5 teams ranked
- Exportable (PDF or Markdown)

---

## Open Questions

- [ ] Exact time window for follow-up task execution?
- [ ] Will teams submit task solutions as git push, or show live?
- [x] ~~German or English for bot voice / evaluation text?~~ → German output, English internal
- [ ] Do human jurors want to see the bot's scores during deliberation or only after?
- [ ] Repo access: GitHub links? ZIP uploads? Both?

---

## Timeline (6 days)

| Day | Focus |
|---|---|
| Do 03.07 | Repo analyzer + LLM scoring pipeline |
| Fr 04.07 | Task generation + UI skeleton (dashboard, team view) |
| Sa 05.07 | STT integration + live transcript |
| So 06.07 | TTS + evaluation flow + review/submit screen |
| Mo 07.07 | End-to-end test with own repo, polish, edge cases |
| Di 08.07 | Event day — final test morning, go live 13:00 |
