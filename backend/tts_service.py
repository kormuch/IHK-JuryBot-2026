"""
Text-to-Speech service using Microsoft Edge TTS.

Default voice: de-DE-FlorianMultilingualNeural (German male).
Output format: MP3 saved to tts_output/ directory.
"""

import logging
import re
import time

import edge_tts
from pathlib import Path

logger = logging.getLogger("jurybot.tts")

# Anglicism replacements — catches terms the LLM might still use despite prompt instructions.
# Case-insensitive, whole-word matches. Order matters for overlapping terms.
_ANGLICISM_MAP = [
    # Multi-word first (matched before single words)
    ("State Management", "Zustandsverwaltung"),
    ("Confidence Gate", "Schwellwertprüfung"),
    # Technical anglicisms
    ("Frontend", "Oberfläche"),
    ("Backend", "Serverseite"),
    ("Endpoints", "Schnittstellen"),
    ("Endpoint", "Schnittstelle"),
    ("Features", "Funktionen"),
    ("Feature", "Funktion"),
    ("Deployment", "Bereitstellung"),
    ("Placeholder", "Platzhalter"),
    ("Boilerplate", "Gerüstcode"),
    ("Repositories", "Projektverzeichnisse"),
    ("Repository", "Projektverzeichnis"),
    ("Frameworks", "Rahmenwerke"),
    ("Framework", "Rahmenwerk"),
    ("Pipelines", "Verarbeitungsketten"),
    ("Pipeline", "Verarbeitungskette"),
    ("Routing", "Weiterleitung"),
    ("Responsive", "bildschirmangepasst"),
    ("Repo", "Codebasis"),
    # Business/fachsprech anglicisms
    ("Governance", "Steuerung"),
    ("Compliance", "Regelkonformität"),
    ("Usability", "Bedienbarkeit"),
    ("Scalability", "Skalierbarkeit"),
    ("Scope", "Umfang"),
    ("Passport", "Kennung"),
    ("Workflow", "Arbeitsablauf"),
    ("Workflows", "Arbeitsabläufe"),
    ("Dashboard", "Übersicht"),
    ("Performance", "Leistung"),
    ("Feedback", "Rückmeldung"),
    ("Tool", "Werkzeug"),
    ("Tools", "Werkzeuge"),
    ("Input", "Eingabe"),
    ("Output", "Ausgabe"),
    ("Scale", "Skalierung"),
    # Dev/engineering anglicisms
    ("Refactoring", "Umstrukturierung"),
    ("Debugging", "Fehlersuche"),
    ("Hosting", "Bereitstellung"),
    ("Templates", "Vorlagen"),
    ("Template", "Vorlage"),
    ("Hardcoded", "fest eingetragen"),
    ("Middleware", "Zwischenschicht"),
    ("Authentication", "Anmeldung"),
    ("Authorization", "Berechtigung"),
    ("Scheduler", "Zeitsteuerung"),
    ("Caching", "Zwischenspeicherung"),
    ("Logging", "Protokollierung"),
    ("Mapping", "Zuordnung"),
    ("Release", "Veröffentlichung"),
    ("Sprint", "Arbeitsphase"),
    ("Reviews", "Prüfungen"),
    ("Review", "Prüfung"),
    ("Merge", "Zusammenführung"),
    ("Branch", "Entwicklungszweig"),
    ("Commit", "Änderungssatz"),
    ("Fetch", "Abruf"),
    ("Payload", "Nutzlast"),
    ("Requests", "Anfragen"),
    ("Request", "Anfrage"),
    ("Response", "Antwort"),
    ("Callbacks", "Rückrufe"),
    ("Callback", "Rückruf"),
    ("Lifecycle", "Lebenszyklus"),
]


def _replace_anglicisms(text: str) -> str:
    """Replace common anglicisms with German equivalents for cleaner TTS output."""
    for eng, deu in _ANGLICISM_MAP:
        text = re.sub(rf'\b{re.escape(eng)}\b', deu, text, flags=re.IGNORECASE)
    return text


DEFAULT_VOICE = "de-DE-FlorianMultilingualNeural"


async def generate_speech(
    text: str,
    output_path: str,
    voice: str | None = None,
) -> str:
    """Generate German TTS audio file using edge-tts. Return file path."""
    if voice is None:
        voice = DEFAULT_VOICE
    text = _replace_anglicisms(text)
    logger.info("TTS: %d Zeichen, Voice=%s → %s", len(text), voice, output_path)
    logger.debug("TTS Text: %s", text[:200])
    t0 = time.time()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)
    size = Path(output_path).stat().st_size
    logger.info("TTS: OK (%.1fs), Datei: %s (%d bytes)", time.time() - t0, output_path, size)
    return output_path
