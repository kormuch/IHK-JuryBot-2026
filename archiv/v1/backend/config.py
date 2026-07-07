"""
Application configuration — loads from .env file at project root.

Environment variables:
    GROQ_API_KEY     — API key for Groq (Llama models)
    GEMINI_API_KEY   — API key for Google Gemini
    LLM_PROVIDER     — "groq" or "gemini" (default: groq)
    LLM_MODEL        — Model identifier (default: llama-3.3-70b-versatile)
    HOST             — Server bind address (default: 127.0.0.1)
    PORT             — Server port (default: 8000)
    REPOS_DIR        — Directory for cloned team repos (default: ./repos)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


class Settings:
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "groq")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8000"))
    REPOS_DIR: str = os.getenv("REPOS_DIR", "./repos")

    @property
    def repos_path(self) -> Path:
        p = Path(self.REPOS_DIR)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
