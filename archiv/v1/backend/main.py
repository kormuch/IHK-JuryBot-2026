"""
FastAPI application — IHK JuryBot 2026.

API endpoints:
    Teams:       POST/GET/DELETE /api/teams, GET /api/teams/{id}
    Analysis:    POST /api/teams/{id}/analyze, GET /api/teams/{id}/analysis
    Transcript:  POST/GET /api/teams/{id}/transcript
    STT:         WebSocket /ws/stt/{team_id} (placeholder)
    Tasks:       GET /api/teams/{id}/tasks, POST /api/teams/{id}/assign-task, POST /api/teams/{id}/task-tts
    Evaluation:  POST /api/teams/{id}/evaluate, GET/PUT /api/teams/{id}/evaluation, POST /api/teams/{id}/submit
    Results:     GET /api/results, GET /api/results/export
    TTS:         POST /api/tts

Static mounts:
    /tts_output  — generated TTS audio files
    /            — frontend SPA (must be last)

Run: python -m backend.main
"""

import json
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import settings
from backend.database import init_db, get_db
from backend.repo_analyzer import clone_repo, analyze_repo
from backend.llm_service import LLMService
from backend.tts_service import generate_speech

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="IHK JuryBot 2026", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

llm = LLMService(settings)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TTS_DIR = PROJECT_ROOT / "tts_output"
TTS_DIR.mkdir(exist_ok=True)
FRONTEND_DIR = PROJECT_ROOT / "frontend"


# ─── Pydantic models ───────────────────────────────────────────────

class TeamCreate(BaseModel):
    name: str
    repo_url: str | None = None


class TranscriptAppend(BaseModel):
    text: str


class TaskAssign(BaseModel):
    task_index: int


class EvaluationUpdate(BaseModel):
    scores: dict | None = None
    justifications: dict | None = None


class TTSRequest(BaseModel):
    text: str


# ─── Startup ────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    await init_db()
    logger.info("Database initialized")


# ─── Teams ──────────────────────────────────────────────────────────

@app.post("/api/teams")
async def create_team(team: TeamCreate):
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO teams (name, repo_url) VALUES (?, ?)",
            (team.name, team.repo_url),
        )
        await db.commit()
        team_id = cursor.lastrowid
        return {"id": team_id, "name": team.name, "repo_url": team.repo_url, "status": "pending"}
    finally:
        await db.close()


@app.get("/api/teams")
async def list_teams():
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM teams ORDER BY id")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.get("/api/teams/{team_id}")
async def get_team(team_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
        team = await cursor.fetchone()
        if not team:
            raise HTTPException(404, "Team not found")

        result = dict(team)

        # Attach latest analysis
        cursor = await db.execute(
            "SELECT * FROM analyses WHERE team_id = ? ORDER BY id DESC LIMIT 1",
            (team_id,),
        )
        analysis = await cursor.fetchone()
        if analysis:
            a = dict(analysis)
            for field in ("repo_summary", "scores", "justifications", "generated_tasks"):
                if a.get(field):
                    a[field] = json.loads(a[field])
            result["analysis"] = a

        # Attach latest evaluation
        cursor = await db.execute(
            "SELECT * FROM evaluations WHERE team_id = ? ORDER BY id DESC LIMIT 1",
            (team_id,),
        )
        evaluation = await cursor.fetchone()
        if evaluation:
            e = dict(evaluation)
            for field in ("scores", "justifications"):
                if e.get(field):
                    e[field] = json.loads(e[field])
            result["evaluation"] = e

        return result
    finally:
        await db.close()


@app.delete("/api/teams/{team_id}")
async def delete_team(team_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM teams WHERE id = ?", (team_id,))
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Team not found")
        return {"ok": True}
    finally:
        await db.close()


# ─── Repo Analysis ─────────────────────────────────────────────────

async def _run_analysis(team_id: int):
    """Background task: clone repo, analyze, LLM score, generate tasks."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
        team = await cursor.fetchone()
        if not team:
            return

        team = dict(team)
        await db.execute(
            "UPDATE teams SET status = ? WHERE id = ?", ("analyzing", team_id)
        )
        await db.commit()

        try:
            # Clone
            repo_url = team["repo_url"]
            target = str(settings.repos_path / f"team_{team_id}")

            if repo_url:
                repo_path = await clone_repo(repo_url, target)
            elif team.get("repo_path"):
                repo_path = team["repo_path"]
            else:
                raise ValueError("No repo URL or path set")

            await db.execute(
                "UPDATE teams SET repo_path = ? WHERE id = ?", (repo_path, team_id)
            )
            await db.commit()

            # Analyze
            analysis = await analyze_repo(repo_path)

            # LLM evaluation
            scores = await llm.evaluate_repo(analysis)

            # Generate tasks
            tasks = await llm.generate_tasks(analysis, scores)

            # Store results
            await db.execute(
                """INSERT INTO analyses (team_id, repo_summary, scores, justifications, generated_tasks)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    team_id,
                    json.dumps(analysis["summary"], ensure_ascii=False),
                    json.dumps(scores.get("scores", {}), ensure_ascii=False),
                    json.dumps(
                        {k: v.get("justification", "") for k, v in scores.get("scores", {}).items()},
                        ensure_ascii=False,
                    ),
                    json.dumps(tasks, ensure_ascii=False),
                ),
            )
            await db.execute(
                "UPDATE teams SET status = ? WHERE id = ?", ("analyzed", team_id)
            )
            await db.commit()
            logger.info("Analysis complete for team %d", team_id)

        except Exception as e:
            logger.exception("Analysis failed for team %d", team_id)
            await db.execute(
                "UPDATE teams SET status = ? WHERE id = ?", ("error", team_id)
            )
            await db.commit()
    finally:
        await db.close()


@app.post("/api/teams/{team_id}/analyze")
async def trigger_analysis(team_id: int, background_tasks: BackgroundTasks):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
        team = await cursor.fetchone()
        if not team:
            raise HTTPException(404, "Team not found")

        background_tasks.add_task(_run_analysis, team_id)
        return {"status": "analyzing", "message": "Analysis started in background"}
    finally:
        await db.close()


@app.get("/api/teams/{team_id}/analysis")
async def get_analysis(team_id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM analyses WHERE team_id = ? ORDER BY id DESC LIMIT 1",
            (team_id,),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "No analysis found for this team")

        result = dict(row)
        for field in ("repo_summary", "scores", "justifications", "generated_tasks"):
            if result.get(field):
                result[field] = json.loads(result[field])
        return result
    finally:
        await db.close()


# ─── Transcript ─────────────────────────────────────────────────────

@app.post("/api/teams/{team_id}/transcript")
async def append_transcript(team_id: int, data: TranscriptAppend):
    db = await get_db()
    try:
        # Get existing transcript or create new
        cursor = await db.execute(
            "SELECT id, content FROM transcripts WHERE team_id = ? ORDER BY id DESC LIMIT 1",
            (team_id,),
        )
        row = await cursor.fetchone()

        if row:
            existing = row["content"] or ""
            updated = existing + "\n" + data.text if existing else data.text
            await db.execute(
                "UPDATE transcripts SET content = ? WHERE id = ?",
                (updated, row["id"]),
            )
        else:
            await db.execute(
                "INSERT INTO transcripts (team_id, content) VALUES (?, ?)",
                (team_id, data.text),
            )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@app.get("/api/teams/{team_id}/transcript")
async def get_transcript(team_id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM transcripts WHERE team_id = ? ORDER BY id DESC LIMIT 1",
            (team_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return {"team_id": team_id, "content": ""}
        return dict(row)
    finally:
        await db.close()


# ─── WebSocket STT (placeholder) ───────────────────────────────────

@app.websocket("/ws/stt/{team_id}")
async def websocket_stt(websocket: WebSocket, team_id: int):
    await websocket.accept()
    logger.info("WebSocket STT connected for team %d", team_id)
    try:
        while True:
            data = await websocket.receive_bytes()
            # Placeholder: echo back a confirmation
            # In production, send to Whisper API and return transcript
            await websocket.send_json({
                "team_id": team_id,
                "type": "transcript_update",
                "text": "[STT placeholder — audio received, transcription not yet implemented]",
            })
    except WebSocketDisconnect:
        logger.info("WebSocket STT disconnected for team %d", team_id)


# ─── Task Assignment ───────────────────────────────────────────────

@app.get("/api/teams/{team_id}/tasks")
async def get_tasks(team_id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT generated_tasks FROM analyses WHERE team_id = ? ORDER BY id DESC LIMIT 1",
            (team_id,),
        )
        row = await cursor.fetchone()
        if not row or not row["generated_tasks"]:
            raise HTTPException(404, "No tasks generated yet. Run analysis first.")
        return {"tasks": json.loads(row["generated_tasks"])}
    finally:
        await db.close()


@app.post("/api/teams/{team_id}/assign-task")
async def assign_task(team_id: int, data: TaskAssign):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT generated_tasks FROM analyses WHERE team_id = ? ORDER BY id DESC LIMIT 1",
            (team_id,),
        )
        row = await cursor.fetchone()
        if not row or not row["generated_tasks"]:
            raise HTTPException(404, "No tasks generated yet.")

        tasks = json.loads(row["generated_tasks"])
        if data.task_index < 0 or data.task_index >= len(tasks):
            raise HTTPException(400, f"Invalid task_index. Must be 0-{len(tasks)-1}")

        selected = tasks[data.task_index]
        await db.execute(
            "UPDATE teams SET status = ? WHERE id = ?", ("task_assigned", team_id)
        )
        await db.commit()
        return {"assigned_task": selected, "task_index": data.task_index}
    finally:
        await db.close()


@app.post("/api/teams/{team_id}/task-tts")
async def task_tts(team_id: int):
    """Generate TTS audio for the assigned task."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT generated_tasks FROM analyses WHERE team_id = ? ORDER BY id DESC LIMIT 1",
            (team_id,),
        )
        row = await cursor.fetchone()
        if not row or not row["generated_tasks"]:
            raise HTTPException(404, "No tasks generated yet.")

        tasks = json.loads(row["generated_tasks"])
        # Use first task by default; in practice the assigned one would be tracked
        task = tasks[0]
        text = f"{task['title']}. {task['description']}"

        filename = f"task_team_{team_id}_{uuid.uuid4().hex[:8]}.mp3"
        output_path = str(TTS_DIR / filename)
        await generate_speech(text, output_path)

        return {"audio_url": f"/tts_output/{filename}", "text": text}
    finally:
        await db.close()


# ─── Evaluation ─────────────────────────────────────────────────────

@app.post("/api/teams/{team_id}/evaluate")
async def trigger_evaluation(team_id: int, background_tasks: BackgroundTasks):
    """Trigger final evaluation combining repo analysis + transcript + task results."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
        team = await cursor.fetchone()
        if not team:
            raise HTTPException(404, "Team not found")

        background_tasks.add_task(_run_evaluation, team_id)
        return {"status": "evaluating", "message": "Evaluation started in background"}
    finally:
        await db.close()


async def _run_evaluation(team_id: int):
    """Background: combine repo scores + presentation evaluation into final scores."""
    db = await get_db()
    try:
        # Get analysis scores
        cursor = await db.execute(
            "SELECT * FROM analyses WHERE team_id = ? ORDER BY id DESC LIMIT 1",
            (team_id,),
        )
        analysis_row = await cursor.fetchone()
        if not analysis_row:
            logger.error("No analysis found for team %d, cannot evaluate", team_id)
            return

        repo_scores = json.loads(analysis_row["scores"]) if analysis_row["scores"] else {}
        repo_summary = json.loads(analysis_row["repo_summary"]) if analysis_row["repo_summary"] else {}

        # Get transcript for presentation evaluation
        cursor = await db.execute(
            "SELECT content FROM transcripts WHERE team_id = ? ORDER BY id DESC LIMIT 1",
            (team_id,),
        )
        transcript_row = await cursor.fetchone()

        all_scores = dict(repo_scores)
        presentation_score = None

        if transcript_row and transcript_row["content"]:
            try:
                pres_result = await llm.evaluate_presentation(
                    transcript_row["content"],
                    {"summary": repo_summary},
                    repo_scores,
                )
                presentation_score = pres_result.get("presentation", {})
                all_scores["presentation"] = presentation_score
            except Exception:
                logger.exception("Presentation evaluation failed for team %d", team_id)

        # Calculate final weighted score
        weights = {
            "architecture": 0.25,
            "code_quality": 0.20,
            "completeness": 0.20,
            "innovation": 0.15,
            "documentation": 0.10,
            "presentation": 0.10,
        }

        total_weight = 0.0
        weighted_sum = 0.0
        justifications = {}

        for cat, weight in weights.items():
            entry = all_scores.get(cat, {})
            if isinstance(entry, dict) and "score" in entry:
                weighted_sum += entry["score"] * weight
                total_weight += weight
                justifications[cat] = entry.get("justification", "")

        final_score = round(weighted_sum / total_weight, 2) if total_weight > 0 else 0.0

        await db.execute(
            """INSERT INTO evaluations (team_id, scores, justifications, final_score)
               VALUES (?, ?, ?, ?)""",
            (
                team_id,
                json.dumps(all_scores, ensure_ascii=False),
                json.dumps(justifications, ensure_ascii=False),
                final_score,
            ),
        )
        await db.execute(
            "UPDATE teams SET status = ? WHERE id = ?", ("evaluated", team_id)
        )
        await db.commit()
        logger.info("Evaluation complete for team %d: %.2f", team_id, final_score)

    except Exception:
        logger.exception("Evaluation failed for team %d", team_id)
    finally:
        await db.close()


@app.get("/api/teams/{team_id}/evaluation")
async def get_evaluation(team_id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM evaluations WHERE team_id = ? ORDER BY id DESC LIMIT 1",
            (team_id,),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "No evaluation found for this team")

        result = dict(row)
        for field in ("scores", "justifications"):
            if result.get(field):
                result[field] = json.loads(result[field])
        return result
    finally:
        await db.close()


@app.put("/api/teams/{team_id}/evaluation")
async def update_evaluation(team_id: int, data: EvaluationUpdate):
    """Human edits to evaluation scores/justifications."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, scores, justifications FROM evaluations WHERE team_id = ? ORDER BY id DESC LIMIT 1",
            (team_id,),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "No evaluation found for this team")

        eval_id = row["id"]
        current_scores = json.loads(row["scores"]) if row["scores"] else {}
        current_justifications = json.loads(row["justifications"]) if row["justifications"] else {}

        if data.scores:
            current_scores.update(data.scores)
        if data.justifications:
            current_justifications.update(data.justifications)

        # Recalculate final score
        weights = {
            "architecture": 0.25, "code_quality": 0.20, "completeness": 0.20,
            "innovation": 0.15, "documentation": 0.10, "presentation": 0.10,
        }
        total_weight = 0.0
        weighted_sum = 0.0
        for cat, weight in weights.items():
            entry = current_scores.get(cat, {})
            if isinstance(entry, dict) and "score" in entry:
                weighted_sum += entry["score"] * weight
                total_weight += weight

        final_score = round(weighted_sum / total_weight, 2) if total_weight > 0 else 0.0

        await db.execute(
            "UPDATE evaluations SET scores = ?, justifications = ?, final_score = ? WHERE id = ?",
            (
                json.dumps(current_scores, ensure_ascii=False),
                json.dumps(current_justifications, ensure_ascii=False),
                final_score,
                eval_id,
            ),
        )
        await db.commit()
        return {"ok": True, "final_score": final_score}
    finally:
        await db.close()


@app.post("/api/teams/{team_id}/submit")
async def submit_evaluation(team_id: int):
    """Mark evaluation as submitted (human approved)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM evaluations WHERE team_id = ? ORDER BY id DESC LIMIT 1",
            (team_id,),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "No evaluation found for this team")

        await db.execute(
            "UPDATE evaluations SET submitted = 1 WHERE id = ?", (row["id"],)
        )
        await db.execute(
            "UPDATE teams SET status = ? WHERE id = ?", ("submitted", team_id)
        )
        await db.commit()
        return {"ok": True, "status": "submitted"}
    finally:
        await db.close()


# ─── Results ────────────────────────────────────────────────────────

@app.get("/api/results")
async def get_results():
    """All teams ranked by final score."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT t.id, t.name, t.status, e.final_score, e.scores, e.submitted
            FROM teams t
            LEFT JOIN evaluations e ON e.team_id = t.id
                AND e.id = (SELECT MAX(e2.id) FROM evaluations e2 WHERE e2.team_id = t.id)
            ORDER BY e.final_score DESC NULLS LAST
        """)
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            entry = dict(r)
            if entry.get("scores"):
                entry["scores"] = json.loads(entry["scores"])
            results.append(entry)
        return results
    finally:
        await db.close()


@app.get("/api/results/export")
async def export_results():
    """Markdown export of all evaluations."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT t.name, e.final_score, e.scores, e.justifications, e.submitted
            FROM teams t
            JOIN evaluations e ON e.team_id = t.id
                AND e.id = (SELECT MAX(e2.id) FROM evaluations e2 WHERE e2.team_id = t.id)
            ORDER BY e.final_score DESC
        """)
        rows = await cursor.fetchall()

        lines = ["# IHK JuryBot 2026 — Ergebnisse\n"]

        for rank, r in enumerate(rows, 1):
            r = dict(r)
            scores = json.loads(r["scores"]) if r["scores"] else {}
            justifications = json.loads(r["justifications"]) if r["justifications"] else {}

            lines.append(f"## {rank}. {r['name']} — Gesamtnote: {r['final_score']:.1f}/10\n")

            category_labels = {
                "architecture": "Architektur & Design",
                "code_quality": "Code-Qualität",
                "completeness": "Vollständigkeit",
                "innovation": "Innovation",
                "documentation": "Dokumentation",
                "presentation": "Präsentation",
            }

            for key, label in category_labels.items():
                entry = scores.get(key, {})
                score = entry.get("score", "—") if isinstance(entry, dict) else "—"
                justification = justifications.get(key, "")
                lines.append(f"- **{label}**: {score}/10")
                if justification:
                    lines.append(f"  {justification}")

            submitted = "Ja" if r.get("submitted") else "Nein"
            lines.append(f"\n*Eingereicht: {submitted}*\n")
            lines.append("---\n")

        return {"markdown": "\n".join(lines)}
    finally:
        await db.close()


# ─── TTS ────────────────────────────────────────────────────────────

@app.post("/api/tts")
async def tts_generate(data: TTSRequest):
    """Generate TTS for arbitrary text."""
    filename = f"tts_{uuid.uuid4().hex[:8]}.mp3"
    output_path = str(TTS_DIR / filename)
    await generate_speech(data.text, output_path)
    return {"audio_url": f"/tts_output/{filename}"}


# ─── Static file mounts ────────────────────────────────────────────

# TTS output files
app.mount("/tts_output", StaticFiles(directory=str(TTS_DIR)), name="tts_output")

# Frontend (must be last — catches all remaining routes)
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


# ─── Entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
    )
