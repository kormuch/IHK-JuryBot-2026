"""
End-to-End Test — JuryBot 2026
Testet den kompletten Flow automatisch gegen den laufenden Server.

Voraussetzung: Server läuft auf http://127.0.0.1:8000
Starten: python test_e2e.py

Schritte:
  1. Team anlegen
  2. Repo analysieren (+ warten bis fertig)
  3. Analyse abrufen & Scores prüfen
  4. Aufgabe zuweisen
  5. Task-TTS generieren
  6. Bewertung generieren (+ warten)
  7. Verdict-TTS generieren
  8. Bewertung abgeben
  9. Ergebnisse abrufen
  10. Markdown-Export
  11. Team löschen (Cleanup)
"""

import sys
import time
import requests

BASE = "http://127.0.0.1:8000"
API = f"{BASE}/api"
TEST_REPO = "https://github.com/kormuch/ihk-theben-challenge-2026"

passed = 0
failed = 0
errors = []


def step(name, fn):
    global passed, failed
    print(f"\n{'='*60}")
    print(f"  SCHRITT: {name}")
    print(f"{'='*60}")
    try:
        result = fn()
        print(f"  OK: OK")
        passed += 1
        return result
    except Exception as e:
        print(f"  FAIL: FEHLER: {e}")
        failed += 1
        errors.append(f"{name}: {e}")
        return None


def check_server():
    r = requests.get(f"{BASE}/", timeout=5)
    assert r.status_code == 200, f"Server antwortet nicht (HTTP {r.status_code})"
    print(f"  Server erreichbar, HTTP {r.status_code}")


def create_team():
    r = requests.post(f"{API}/teams", json={"name": "E2E-Test", "repo_url": TEST_REPO}, timeout=10)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
    data = r.json()
    assert "id" in data, f"Keine Team-ID in Antwort: {data}"
    print(f"  Team erstellt: id={data['id']}, name={data['name']}")
    return data["id"]


def analyze_repo(team_id):
    r = requests.post(f"{API}/teams/{team_id}/analyze", timeout=10)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
    print(f"  Analyse gestartet, warte auf Abschluss...")

    for i in range(90):  # max 90 Sekunden
        time.sleep(2)
        r = requests.get(f"{API}/teams", timeout=10)
        teams = r.json()
        team = next((t for t in teams if t["id"] == team_id), None)
        if not team:
            raise Exception("Team nicht mehr in DB!")
        status = team["status"]
        print(f"  ... [{i*2}s] Status: {status}")
        if status == "analyzed":
            return
        if status == "error":
            error_msg = team.get("error_message", "unbekannt")
            raise Exception(f"Analyse fehlgeschlagen: {error_msg}")

    raise Exception("Timeout: Analyse dauert >180s")


def get_analysis(team_id):
    r = requests.get(f"{API}/teams/{team_id}/analysis", timeout=10)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
    data = r.json()

    scores = data.get("scores", {})
    print(f"  Scores: { {k: v.get('score', v) if isinstance(v, dict) else v for k, v in scores.items()} }")

    for cat in ["ambition", "praktikabilitaet", "umsetzung"]:
        assert cat in scores, f"Score '{cat}' fehlt"
        entry = scores[cat]
        if isinstance(entry, dict):
            s = entry.get("score", 0)
        else:
            s = entry
        assert 1 <= s <= 10, f"Score '{cat}' außerhalb 1-10: {s}"

    # Check final_score was computed during analysis
    final = data.get("final_score", 0)
    print(f"  Final Score: {final}")
    assert final > 0, f"Final Score ist 0"

    return data


def verdict_text(team_id):
    r = requests.post(f"{API}/teams/{team_id}/verdict-text", timeout=60)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
    data = r.json()
    text = data.get("text", "")
    print(f"  Verdict Text: {text[:200]}...")
    assert text, "Kein Verdict-Text"
    assert len(text) > 50, f"Verdict-Text zu kurz: {len(text)} Zeichen"


def verdict_tts(team_id):
    r = requests.post(f"{API}/teams/{team_id}/verdict-tts", timeout=60)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
    data = r.json()
    text = data.get("text", "")
    audio_url = data.get("audio_url", "")
    print(f"  Verdict Text: {text[:100]}...")
    print(f"  Audio URL: {audio_url}")
    assert text, "Kein Verdict-Text"
    assert audio_url, "Keine audio_url"

    r2 = requests.get(f"{BASE}{audio_url}", timeout=10)
    assert r2.status_code == 200, f"Audio nicht erreichbar: HTTP {r2.status_code}"
    print(f"  Audio OK: {len(r2.content)} bytes")



def get_results():
    r = requests.get(f"{API}/results", timeout=10)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
    data = r.json()
    print(f"  {len(data)} Teams in Ergebnisliste")
    assert len(data) >= 1, "Keine Ergebnisse"


def export_results():
    r = requests.get(f"{API}/results/export", timeout=10)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
    data = r.json()
    md = data.get("markdown", "")
    print(f"  Markdown: {len(md)} Zeichen")
    assert "Gesamtnote" in md, "Markdown enthält kein 'Gesamtnote'"
    print(f"  Export OK")


def delete_team(team_id):
    r = requests.delete(f"{API}/teams/{team_id}", timeout=10)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
    print(f"  Team {team_id} gelöscht")


def main():
    global passed, failed
    print("=" * 60)
    print("  JuryBot 2026 — E2E Test")
    print("=" * 60)

    team_id = None

    step("1. Server erreichbar?", check_server)
    team_id = step("2. Team anlegen", create_team)
    if not team_id:
        print("\nFAIL: Abbruch: Team konnte nicht erstellt werden")
        sys.exit(1)

    step("3. Repo analysieren", lambda: analyze_repo(team_id))
    step("4. Analyse & Scores prüfen", lambda: get_analysis(team_id))
    step("5. Verdict-Text generieren", lambda: verdict_text(team_id))
    step("6. Verdict-TTS generieren", lambda: verdict_tts(team_id))
    step("7. Ergebnisse abrufen", lambda: get_results())
    step("8. Markdown-Export", lambda: export_results())
    step("9. Cleanup: Team löschen", lambda: delete_team(team_id))

    print("\n" + "=" * 60)
    print(f"  ERGEBNIS: {passed} bestanden, {failed} fehlgeschlagen")
    print("=" * 60)

    if errors:
        print("\n  FEHLER:")
        for e in errors:
            print(f"    FAIL: {e}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
