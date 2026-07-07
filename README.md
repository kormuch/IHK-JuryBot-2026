# IHK JuryBot 2026

AI-powered virtual juror for the **Kollege Codex** hackathon at IHK Innovationstage Zollernalb (08.07.2026, Theben AG, Haigerloch). Evaluates 5 teams as one voice among human jurors.

---

## Quick Start

```bash
# 1. Clone & enter
cd C:/Users/kormu/projekte/IHK-JuryBot-2026

# 2. Create virtual environment
python -m venv .venv
.venv/Scripts/activate    # Windows
# source .venv/bin/activate  # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
# Edit .env → add GROQ_API_KEY or GEMINI_API_KEY

# 5. Run
python -m backend.main
```

Open **http://127.0.0.1:8000** in browser.

---

## How It Works

```
  Team submits repo
        │
        ▼
  ┌─────────────┐     ┌──────────┐     ┌──────────────┐
  │ Repo Analyzer├────►│ LLM Eval ├────►│ Task Gen     │
  │ (clone+scan) │     │ (scores) │     │ (2-3 tasks)  │
  └─────────────┘     └──────────┘     └──────┬───────┘
                                              │
  Team presents (5 min)                       │
        │                                     │
        ▼                                     ▼
  ┌──────────┐     ┌───────────────┐    ┌──────────┐
  │ Mic→STT  ├────►│ Transcript    │    │ TTS      │
  │ (Whisper) │     │ (live feed)   │    │ speaks   │
  └──────────┘     └───────────────┘    │ task     │
                                        └──────────┘
                                              │
  Team works on task (timeboxed)              │
        │                                     │
        ▼                                     ▼
  ┌───────────────────────────────────────────────┐
  │ Final Evaluation                              │
  │ repo scores + presentation + task completion  │
  │ → human review → submit                      │
  └───────────────────────────────────────────────┘
```

---

## Project Structure

```
IHK-JuryBot-2026/
├── backend/
│   ├── __init__.py
│   ├── config.py           # Settings from .env (API keys, LLM provider, host/port)
│   ├── database.py         # SQLite via aiosqlite (teams, analyses, transcripts, evaluations)
│   ├── repo_analyzer.py    # Clone, scan structure, read key files, build analysis dict
│   ├── llm_service.py      # Groq/Gemini dual provider, scoring prompts, task generation
│   ├── tts_service.py      # Edge TTS, German voice (de-DE-ConradNeural)
│   └── main.py             # FastAPI app, all API endpoints, static file mounts
├── frontend/
│   ├── index.html          # SPA shell (navbar, modal, toast container)
│   ├── style.css           # Dark theme, team grid, score bars, timer, badges
│   └── app.js              # Full SPA logic (~900 lines), German UI
├── repos/                  # Cloned team repos (gitignored, created at runtime)
├── tts_output/             # Generated TTS audio files (created at runtime)
├── .env.example            # Template for environment variables
├── requirements.txt        # Python dependencies
├── CONCEPT.md              # Full concept document with architecture, rubric, timeline
├── TODO.md                 # Day-by-day task tracking
└── README.md               # This file
```

---

## API Reference

Base URL: `http://127.0.0.1:8000/api`

### Teams

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/teams` | Create team `{name, repo_url}` |
| `GET` | `/teams` | List all teams |
| `GET` | `/teams/{id}` | Get team with analysis + evaluation data |
| `DELETE` | `/teams/{id}` | Delete team and all related data |

### Repo Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/teams/{id}/analyze` | Start repo analysis (background task) |
| `GET` | `/teams/{id}/analysis` | Get analysis results (scores, tasks) |

### Transcript

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/teams/{id}/transcript` | Append transcript text `{text}` |
| `GET` | `/teams/{id}/transcript` | Get full transcript |
| `WS` | `/ws/stt/{team_id}` | WebSocket for live STT (placeholder) |

### Tasks

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/teams/{id}/tasks` | Get generated follow-up tasks |
| `POST` | `/teams/{id}/assign-task` | Assign task `{task_index}` |
| `POST` | `/teams/{id}/task-tts` | Generate TTS audio for assigned task |

### Evaluation

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/teams/{id}/evaluate` | Generate final evaluation (background task) |
| `GET` | `/teams/{id}/evaluation` | Get evaluation results |
| `PUT` | `/teams/{id}/evaluation` | Update scores/justifications (human edits) |
| `POST` | `/teams/{id}/submit` | Mark evaluation as submitted |

### Results

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/results` | All teams ranked by final score |
| `GET` | `/results/export` | Markdown export of all evaluations |

### TTS

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/tts` | Generate TTS for any text `{text}` |

---

## Scoring Rubric

Each category 1–10, with weighted contribution to final score:

| Category | Weight | Evaluates |
|----------|--------|-----------|
| Architecture & Design | 25% | Structure, separation of concerns, tech choices |
| Code Quality | 20% | Readability, consistency, error handling |
| Completeness | 20% | Working features vs stubs/placeholders |
| Innovation | 15% | Creative approaches, smart tool usage |
| Documentation | 10% | README quality, API docs, setup instructions |
| Presentation | 10% | Clarity, structure, demo quality (from transcript) |

Each score includes a 2–3 sentence justification in German.

---

## Configuration

All settings via `.env` file:

```env
GROQ_API_KEY=gsk_...              # Required if LLM_PROVIDER=groq
GEMINI_API_KEY=AI...              # Required if LLM_PROVIDER=gemini
LLM_PROVIDER=groq                 # "groq" or "gemini"
LLM_MODEL=llama-3.3-70b-versatile # Model identifier
HOST=127.0.0.1                    # Server bind address
PORT=8000                         # Server port
REPOS_DIR=./repos                 # Where cloned repos are stored
```

---

## Language Strategy

- **Bot speaks:** German (TTS voice: de-DE-ConradNeural)
- **LLM evaluates internally:** English (better reasoning quality)
- **Output justifications:** German
- **Participants speak:** Whatever they want (Whisper auto-detects DE/EN)

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.12 + FastAPI + uvicorn |
| Frontend | Vanilla HTML/CSS/JS (no framework) |
| Database | SQLite via aiosqlite |
| LLM | Groq (Llama 3.3 70B) or Google Gemini |
| TTS | Microsoft Edge TTS (edge-tts) |
| STT | Whisper API / Deepgram (WebSocket placeholder) |

---

## UI Screens

### Dashboard
Team cards in grid layout. Each card shows name, repo URL, status badge, and action buttons. "+" card to add new teams.

### Team View — Analysis Tab
Repo summary, score breakdown with colored bars (red→yellow→green→teal), editable justifications, generated task cards with assign buttons.

### Team View — Live Session Tab
Mic recording controls, live transcript display, TTS playback for task assignment, countdown timer with 5/15/20 min presets.

### Team View — Evaluation Tab
Final weighted score display, all 6 category scores with editable justifications, save/submit buttons with confirmation modal.

### Results
Ranked team list with score breakdowns, markdown export for sharing with human jury.

---

## Team Status Flow

```
pending → analyzing → analyzed → presenting → task_assigned → evaluated → submitted
                ↓
              error
```
