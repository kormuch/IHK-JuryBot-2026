# IHK JuryBot 2026 — TODO

## Open Questions
- [ ] Exact time window for follow-up task execution?
- [ ] Will teams submit task solutions as git push or show live?
- [ ] Do human jurors see bot scores during or after deliberation?
- [ ] Repo access format: GitHub URL, ZIP upload, or both?

---

## Do 03.07 — Repo Analyzer + Scoring Pipeline
- [ ] Project setup (FastAPI, folder structure, dependencies)
- [ ] Repo analyzer: structure scan (files, languages, frameworks, entry points)
- [ ] Repo analyzer: README parser (goals, features, setup instructions)
- [ ] Repo analyzer: code reader (prioritize key files: main, config, routes, models, tests)
- [ ] LLM scoring pipeline: send structured summary → get scores per rubric category
- [ ] LLM scoring pipeline: generate written justifications (English internal → German output)
- [ ] Task generation: identify gaps/weaknesses → generate 2–3 candidate tasks

## Fr 04.07 — Task Generation + UI Skeleton
- [ ] Task generation: calibrate difficulty across teams
- [ ] Task generation: make tasks editable before assigning
- [ ] UI: dashboard with 5 team cards + status
- [ ] UI: team view — repo analysis summary + scores
- [ ] UI: team view — generated task display

## Sa 05.07 — STT Integration
- [ ] Whisper/Deepgram integration (mic input → transcript)
- [ ] Auto language detection (DE/EN)
- [ ] Live transcript display in UI
- [ ] Handle technical terms / code jargon

## So 06.07 — TTS + Evaluation Flow
- [ ] TTS integration (Edge TTS or browser SpeechSynthesis, German voice)
- [ ] Task assignment via TTS (bot speaks task aloud)
- [ ] Evaluation screen: final scores + justifications (editable)
- [ ] Review & submit flow (human approval gate)
- [ ] Results overview: all 5 teams ranked

## Mo 07.07 — Polish + Testing
- [ ] End-to-end test with own IHK repo
- [ ] Test with noisy audio / bad mic
- [ ] Edge cases: empty repos, missing README, non-standard structure
- [ ] Export results (PDF or Markdown)
- [ ] UI polish

## Di 08.07 — Event Day
- [ ] Morning: final test run at venue
- [ ] 13:00: go live
