"""
SQLite database layer using aiosqlite.

Tables:
    teams        — Team metadata (name, repo URL, status)
    analyses     — Repo analysis results (scores, justifications, final_score, verdict)

JSON fields are stored as TEXT with json.dumps/loads.
Database file: jurybot.db in project root.
"""

import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "jurybot.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    repo_url TEXT,
    repo_path TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL,
    repo_summary TEXT,
    scores TEXT,
    justifications TEXT,
    final_score REAL,
    verdict_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);
"""

# Migrations for existing databases
_MIGRATIONS = [
    "ALTER TABLE teams ADD COLUMN error_message TEXT",
    "ALTER TABLE analyses ADD COLUMN final_score REAL",
    "ALTER TABLE analyses ADD COLUMN verdict_text TEXT",
]


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        for migration in _MIGRATIONS:
            try:
                await db.execute(migration)
            except Exception:
                pass  # Column already exists
        await db.commit()


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    return db
