"""Quick boot test — does the app start and log correctly?"""
import os, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from backend.main import app
print("OK: app importiert")
# Check log file
from pathlib import Path
log = Path("jurybot.log")
if log.exists():
    print(f"Log-Datei: {log} ({log.stat().st_size} bytes)")
    print("Inhalt:")
    print(log.read_text(encoding="utf-8"))
else:
    print("FEHLER: jurybot.log wurde nicht erstellt!")
