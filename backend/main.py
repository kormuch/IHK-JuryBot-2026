"""
FastAPI application — IHK JuryBot 2026 v2.

API endpoints:
    Teams:       POST/GET/DELETE /api/teams, GET /api/teams/{id}
    Analysis:    POST /api/teams/{id}/analyze, GET /api/teams/{id}/analysis
    Verdict:     POST /api/teams/{id}/verdict-text, POST /api/teams/{id}/verdict-tts
    Results:     GET /api/results, GET /api/results/export

Static mounts:
    /tts_output  — generated TTS audio files
    /            — frontend SPA (must be last)

Run: python -m backend.main
"""

import json
import logging
import logging.handlers
import time
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import settings
from backend.database import init_db, get_db
from backend.repo_analyzer import clone_repo, analyze_repo
from backend.llm_service import LLMService
from backend.tts_service import generate_speech

# ─── Logging Setup ─────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = PROJECT_ROOT / "jurybot.log"

log_level = logging.DEBUG if settings.DEBUG_MODE else logging.INFO
log_format = logging.Formatter(
    "[%(asctime)s] %(levelname)-8s %(name)-25s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(log_level)
console_handler.setFormatter(log_format)

# File handler — rotiert bei 5MB, behält 3 Backups
file_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8",
)
file_handler.setLevel(log_level)
file_handler.setFormatter(log_format)

# Root logger konfigurieren — alle Module loggen hierhin
root_logger = logging.getLogger()
root_logger.setLevel(log_level)
root_logger.handlers.clear()
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

logger = logging.getLogger("jurybot.main")

app = FastAPI(title="IHK JuryBot 2026", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

llm = LLMService(settings)

logger.info("=" * 60)
logger.info("JuryBot 2026 v2.0.0 startet")
logger.info("DEBUG_MODE: %s", settings.DEBUG_MODE)
logger.info("LLM_PROVIDER: %s | LLM_MODEL: %s", settings.LLM_PROVIDER, settings.LLM_MODEL)
logger.info("HOST: %s | PORT: %s", settings.HOST, settings.PORT)
logger.info("REPOS_DIR: %s", settings.repos_path)
logger.info("LOG_FILE: %s", LOG_FILE)
logger.info("DEEPSEEK_API_KEY: %s", "gesetzt" if settings.DEEPSEEK_API_KEY else "FEHLT")
logger.info("GROQ_API_KEY: %s", "gesetzt" if settings.GROQ_API_KEY else "FEHLT")
logger.info("GEMINI_API_KEY: %s", "gesetzt" if settings.GEMINI_API_KEY else "FEHLT")
logger.info("=" * 60)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    logger.debug("→ %s %s", request.method, request.url.path)
    try:
        response = await call_next(request)
        duration = (time.time() - start) * 1000
        logger.debug("← %s %s → %d (%.0fms)", request.method, request.url.path, response.status_code, duration)
        return response
    except Exception as e:
        duration = (time.time() - start) * 1000
        logger.error("← %s %s → EXCEPTION (%.0fms): %s", request.method, request.url.path, duration, e)
        raise

TTS_DIR = PROJECT_ROOT / "tts_output"
TTS_DIR.mkdir(exist_ok=True)
FRONTEND_DIR = PROJECT_ROOT / "frontend"


# ─── Pydantic models ───────────────────────────────────────────────

class TeamCreate(BaseModel):
    name: str
    repo_url: str | None = None




class TTSRequest(BaseModel):
    text: str
    voice: str | None = None


class ConfigUpdate(BaseModel):
    evaluation_prompt: str | None = None
    verdict_prompt: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    tts_voice: str | None = None
    score_weights: dict | None = None


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
            for field in ("repo_summary", "scores", "justifications"):
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
    logger.info("[ANALYSE t%d] ====== START ======", team_id)
    t_start = time.time()
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
        team = await cursor.fetchone()
        if not team:
            logger.error("[ANALYSE t%d] Team nicht in DB gefunden — Abbruch", team_id)
            return

        team = dict(team)
        logger.info("[ANALYSE t%d] Team: %s | repo_url: %s", team_id, team["name"], team["repo_url"])
        await db.execute(
            "UPDATE teams SET status = ? WHERE id = ?", ("analyzing", team_id)
        )
        await db.commit()

        try:
            # Schritt 1: Clone
            repo_url = team["repo_url"]
            target = str(settings.repos_path / f"team_{team_id}")

            if repo_url:
                logger.info("[ANALYSE t%d] SCHRITT 1/5: git clone %s → %s", team_id, repo_url, target)
                t1 = time.time()
                repo_path = await clone_repo(repo_url, target)
                logger.info("[ANALYSE t%d] SCHRITT 1/5: Clone OK (%.1fs) → %s", team_id, time.time() - t1, repo_path)
            elif team.get("repo_path"):
                repo_path = team["repo_path"]
                logger.info("[ANALYSE t%d] SCHRITT 1/5: Kein Clone nötig, nutze existierenden Pfad: %s", team_id, repo_path)
            else:
                raise ValueError("Keine repo_url und kein repo_path gesetzt")

            await db.execute(
                "UPDATE teams SET repo_path = ? WHERE id = ?", (repo_path, team_id)
            )
            await db.commit()

            # Schritt 2: Repo scannen
            logger.info("[ANALYSE t%d] SCHRITT 2/5: Repo scannen...", team_id)
            t2 = time.time()
            analysis = await analyze_repo(repo_path)
            summary = analysis["summary"]
            key_files_count = len(analysis["key_files"])
            key_files_chars = sum(len(v) for v in analysis["key_files"].values())
            logger.info(
                "[ANALYSE t%d] SCHRITT 2/5: Scan OK (%.1fs) — %d Dateien, %d Zeilen, %d Key-Files (%d chars), Sprachen: %s, Frameworks: %s",
                team_id, time.time() - t2, summary["total_files"], summary["total_lines"],
                key_files_count, key_files_chars,
                json.dumps(summary["languages"], ensure_ascii=False),
                summary["frameworks"],
            )

            # Schritt 3: LLM Evaluation
            logger.info("[ANALYSE t%d] SCHRITT 3/5: LLM Evaluation (Provider: %s)...", team_id, settings.LLM_PROVIDER)
            t3 = time.time()
            scores = await llm.evaluate_repo(analysis)
            logger.info("[ANALYSE t%d] SCHRITT 3/5: LLM OK (%.1fs) — Scores: %s",
                team_id, time.time() - t3,
                {k: v.get("score", v) if isinstance(v, dict) else v for k, v in scores.get("scores", {}).items()},
            )
            if scores.get("_plausibility_warning"):
                logger.warning("[ANALYSE t%d] PLAUSIBILITY WARNING: %s", team_id, scores["_plausibility_warning"])

            # Gewichteten Score berechnen
            weights = {"ambition": 0.35, "praktikabilitaet": 0.35, "umsetzung": 0.30}
            score_data = scores.get("scores", {})
            weighted_sum = 0.0
            total_weight = 0.0
            for cat, weight in weights.items():
                entry = score_data.get(cat, {})
                if isinstance(entry, dict) and "score" in entry:
                    weighted_sum += entry["score"] * weight
                    total_weight += weight
            final_score = round(weighted_sum / total_weight, 2) if total_weight > 0 else 0.0
            logger.info("[ANALYSE t%d] Final Score: %.2f", team_id, final_score)

            # In DB speichern
            logger.debug("[ANALYSE t%d] Ergebnisse in DB speichern...", team_id)
            await db.execute(
                """INSERT INTO analyses (team_id, repo_summary, scores, justifications, final_score)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    team_id,
                    json.dumps(analysis["summary"], ensure_ascii=False),
                    json.dumps(score_data, ensure_ascii=False),
                    json.dumps(
                        {k: v.get("justification", "") for k, v in score_data.items()},
                        ensure_ascii=False,
                    ),
                    final_score,
                ),
            )
            await db.commit()

            # Schritt 4: Verdict-Text automatisch generieren
            logger.info("[ANALYSE t%d] SCHRITT 4/5: Verdict-Text generieren...", team_id)
            t4 = time.time()
            try:
                justifications_map = {k: v.get("justification", "") for k, v in score_data.items()}
                summary_text = " ".join(justifications_map.values())
                verdict = await llm.generate_speech_verdict(
                    team_name=team["name"], scores=score_data, summary=summary_text,
                )
                # Letzte Analysis-ID holen und verdict_text speichern
                cursor = await db.execute(
                    "SELECT id FROM analyses WHERE team_id = ? ORDER BY id DESC LIMIT 1",
                    (team_id,),
                )
                analysis_row = await cursor.fetchone()
                if analysis_row:
                    await db.execute(
                        "UPDATE analyses SET verdict_text = ? WHERE id = ?",
                        (verdict, analysis_row["id"]),
                    )
                logger.info("[ANALYSE t%d] SCHRITT 4/5: Verdict OK (%.1fs, %d Zeichen)",
                    team_id, time.time() - t4, len(verdict))
            except Exception as ve:
                logger.warning("[ANALYSE t%d] SCHRITT 4/5: Verdict fehlgeschlagen (%.1fs): %s",
                    team_id, time.time() - t4, ve)

            # Schritt 5: TTS Audio automatisch generieren
            if analysis_row and verdict:
                logger.info("[ANALYSE t%d] SCHRITT 5/5: TTS Audio generieren...", team_id)
                t5 = time.time()
                try:
                    tts_filename = f"verdict_team_{team_id}_{uuid.uuid4().hex[:8]}.mp3"
                    tts_path = str(TTS_DIR / tts_filename)
                    await generate_speech(verdict, tts_path)
                    audio_url = f"/tts_output/{tts_filename}"
                    await db.execute(
                        "UPDATE analyses SET audio_url = ? WHERE id = ?",
                        (audio_url, analysis_row["id"]),
                    )
                    logger.info("[ANALYSE t%d] SCHRITT 5/5: TTS OK (%.1fs) → %s", team_id, time.time() - t5, audio_url)
                except Exception as te:
                    logger.warning("[ANALYSE t%d] SCHRITT 5/5: TTS fehlgeschlagen (%.1fs): %s",
                        team_id, time.time() - t5, te)

            # Status NACH Verdict+TTS setzen — Frontend pollt auf diesen Status
            await db.execute(
                "UPDATE teams SET status = ?, error_message = NULL WHERE id = ?", ("analyzed", team_id)
            )
            await db.commit()
            logger.info("[ANALYSE t%d] ====== FERTIG (%.1fs gesamt) ======", team_id, time.time() - t_start)

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            logger.error("[ANALYSE t%d] ====== FEHLGESCHLAGEN (%.1fs) ======", team_id, time.time() - t_start)
            logger.error("[ANALYSE t%d] Fehler: %s", team_id, error_msg)
            logger.debug("[ANALYSE t%d] Traceback:\n%s", team_id, traceback.format_exc())
            await db.execute(
                "UPDATE teams SET status = ?, error_message = ? WHERE id = ?",
                ("error", error_msg[:500], team_id),
            )
            await db.commit()
    finally:
        await db.close()


@app.post("/api/teams/{team_id}/analyze")
async def trigger_analysis(team_id: int, background_tasks: BackgroundTasks):
    logger.info("API: POST /teams/%d/analyze", team_id)
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
        team = await cursor.fetchone()
        if not team:
            logger.warning("API: Team %d nicht gefunden", team_id)
            raise HTTPException(404, "Team not found")

        logger.info("API: Analyse für Team %d (%s) gestartet als Background-Task", team_id, team["name"])
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
        for field in ("repo_summary", "scores", "justifications"):
            if result.get(field):
                result[field] = json.loads(result[field])
        return result
    finally:
        await db.close()


# ─── Verdict ───────────────────────────────────────────────────────

@app.post("/api/teams/{team_id}/verdict-text")
async def verdict_text(team_id: int):
    """Generate jury verdict text and store it in analysis."""
    logger.info("API: POST /teams/%d/verdict-text", team_id)
    db = await get_db()
    try:
        cursor = await db.execute("SELECT name FROM teams WHERE id = ?", (team_id,))
        team_row = await cursor.fetchone()
        if not team_row:
            raise HTTPException(404, "Team not found")

        cursor = await db.execute(
            "SELECT id, scores, justifications FROM analyses WHERE team_id = ? ORDER BY id DESC LIMIT 1",
            (team_id,),
        )
        analysis = await cursor.fetchone()
        if not analysis:
            raise HTTPException(404, "No analysis found.")

        scores = json.loads(analysis["scores"]) if analysis["scores"] else {}
        justifications = json.loads(analysis["justifications"]) if analysis["justifications"] else {}
        summary = " ".join(justifications.values())

        verdict = await llm.generate_speech_verdict(
            team_name=team_row["name"], scores=scores, summary=summary,
        )
        logger.info("API: Verdict-Text generiert (%d Zeichen)", len(verdict))

        await db.execute(
            "UPDATE analyses SET verdict_text = ? WHERE id = ?",
            (verdict, analysis["id"]),
        )
        await db.commit()

        return {"text": verdict}
    finally:
        await db.close()


@app.post("/api/teams/{team_id}/verdict-tts")
async def verdict_tts(team_id: int):
    """Generate TTS audio from stored verdict text."""
    logger.info("API: POST /teams/%d/verdict-tts", team_id)
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT verdict_text FROM analyses WHERE team_id = ? ORDER BY id DESC LIMIT 1",
            (team_id,),
        )
        row = await cursor.fetchone()
        if not row or not row["verdict_text"]:
            raise HTTPException(400, "Verdict text not generated yet. Call verdict-text first.")

        verdict = row["verdict_text"]
        filename = f"verdict_team_{team_id}_{uuid.uuid4().hex[:8]}.mp3"
        output_path = str(TTS_DIR / filename)
        await generate_speech(verdict, output_path)

        return {"audio_url": f"/tts_output/{filename}", "text": verdict}
    finally:
        await db.close()




# ─── Results ────────────────────────────────────────────────────────

@app.get("/api/results")
async def get_results():
    """All teams ranked by final score."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT t.id, t.name, t.status, a.final_score, a.scores
            FROM teams t
            LEFT JOIN analyses a ON a.team_id = t.id
                AND a.id = (SELECT MAX(a2.id) FROM analyses a2 WHERE a2.team_id = t.id)
            ORDER BY a.final_score DESC NULLS LAST
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
    """Markdown export of all results."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT t.name, a.final_score, a.scores, a.justifications
            FROM teams t
            JOIN analyses a ON a.team_id = t.id
                AND a.id = (SELECT MAX(a2.id) FROM analyses a2 WHERE a2.team_id = t.id)
            ORDER BY a.final_score DESC
        """)
        rows = await cursor.fetchall()

        lines = ["# IHK JuryBot 2026 — Ergebnisse\n"]

        category_labels = {
            "ambition": "Ambition & Originalität",
            "praktikabilitaet": "Praktikabilität",
            "umsetzung": "Umsetzung",
        }

        for rank, r in enumerate(rows, 1):
            r = dict(r)
            scores = json.loads(r["scores"]) if r["scores"] else {}
            justifications = json.loads(r["justifications"]) if r["justifications"] else {}

            lines.append(f"## {rank}. {r['name']} — Gesamtnote: {r['final_score']:.1f}/10\n")

            for key, label in category_labels.items():
                entry = scores.get(key, {})
                score = entry.get("score", "—") if isinstance(entry, dict) else "—"
                justification = justifications.get(key, "")
                lines.append(f"- **{label}**: {score}/10")
                if justification:
                    lines.append(f"  {justification}")

            lines.append("")
            lines.append("---\n")

        return {"markdown": "\n".join(lines)}
    finally:
        await db.close()


# ─── Configuration ─────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    """Return current bot configuration including prompts, provider, weights, voice."""
    import backend.llm_service as llm_mod
    import backend.tts_service as tts_mod

    return {
        "evaluation_prompt": llm_mod.EVALUATION_SYSTEM_PROMPT,
        "verdict_prompt": llm_mod.SPEECH_VERDICT_SYSTEM_PROMPT,
        "llm_provider": settings.LLM_PROVIDER,
        "llm_model": settings.LLM_MODEL,
        "tts_voice": tts_mod.DEFAULT_VOICE,
        "score_weights": {"ambition": 0.35, "praktikabilitaet": 0.35, "umsetzung": 0.30},
        "available_voices": [
            {"id": "de-DE-FlorianMultilingualNeural", "label": "Florian (natürlich, warm)"},
            {"id": "de-DE-ConradNeural", "label": "Conrad (neutral)"},
            {"id": "de-DE-KillianNeural", "label": "Killian (kräftig)"},
            {"id": "de-DE-KatjaNeural", "label": "Katja (weiblich, klar)"},
            {"id": "de-DE-AmalaNeural", "label": "Amala (weiblich, warm)"},
        ],
        "available_providers": [
            {"id": "deepseek", "label": "DeepSeek", "has_key": bool(settings.DEEPSEEK_API_KEY)},
            {"id": "groq", "label": "Groq", "has_key": bool(settings.GROQ_API_KEY)},
            {"id": "gemini", "label": "Google Gemini", "has_key": bool(settings.GEMINI_API_KEY)},
        ],
    }


@app.put("/api/config")
async def update_config(config: ConfigUpdate):
    """Update bot configuration at runtime. Changes are NOT persisted to .env."""
    import backend.llm_service as llm_mod
    import backend.tts_service as tts_mod

    changes = []

    if config.evaluation_prompt is not None:
        llm_mod.EVALUATION_SYSTEM_PROMPT = config.evaluation_prompt
        changes.append("evaluation_prompt")

    if config.verdict_prompt is not None:
        llm_mod.SPEECH_VERDICT_SYSTEM_PROMPT = config.verdict_prompt
        changes.append("verdict_prompt")

    if config.llm_provider is not None:
        settings.LLM_PROVIDER = config.llm_provider
        llm.provider = config.llm_provider.lower()
        changes.append("llm_provider")

    if config.llm_model is not None:
        settings.LLM_MODEL = config.llm_model
        changes.append("llm_model")

    if config.tts_voice is not None:
        tts_mod.DEFAULT_VOICE = config.tts_voice
        changes.append("tts_voice")

    if config.score_weights is not None:
        total = sum(config.score_weights.values())
        if abs(total - 1.0) > 0.05:
            raise HTTPException(400, f"Gewichtungen müssen 1.0 ergeben (aktuell: {total:.2f})")
        changes.append("score_weights")

    logger.info("Config updated: %s", ", ".join(changes))
    return {"updated": changes}


# ─── TTS ────────────────────────────────────────────────────────────

@app.post("/api/tts")
async def tts_generate(data: TTSRequest):
    """Generate TTS for arbitrary text."""
    filename = f"tts_{uuid.uuid4().hex[:8]}.mp3"
    output_path = str(TTS_DIR / filename)
    await generate_speech(data.text, output_path, voice=data.voice)
    return {"audio_url": f"/tts_output/{filename}"}


# ─── Static file mounts ────────────────────────────────────────────

app.mount("/tts_output", StaticFiles(directory=str(TTS_DIR)), name="tts_output")

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
        reload_dirs=["backend", "frontend"],
        reload_excludes=["repos", "tts_output", "*.db", "*.db-journal", "*.log"],
    )
