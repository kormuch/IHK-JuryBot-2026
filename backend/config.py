"""
Application configuration — loads from .env file at project root.

Environment variables:
    DEEPSEEK_API_KEY — API key for DeepSeek (primary)
    GROQ_API_KEY     — API key for Groq (fallback)
    GEMINI_API_KEY   — API key for Google Gemini (fallback)
    LLM_PROVIDER     — "deepseek", "groq", or "gemini" (default: deepseek)
    LLM_MODEL        — Model identifier (default: deepseek-chat)
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
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "deepseek")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek-chat")
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8000"))
    REPOS_DIR: str = os.getenv("REPOS_DIR", "./repos")
    DEBUG_MODE: bool = os.getenv("DEBUG_MODE", "1").lower() in ("1", "true", "yes", "on")
    ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "")

    @property
    def repos_path(self) -> Path:
        p = Path(self.REPOS_DIR)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent / p
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
