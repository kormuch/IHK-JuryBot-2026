const API = 'http://127.0.0.1:8000/api';

// ── State ──────────────────────────────────────────────
let teams = [];
let currentView = 'dashboard';
let currentTeamId = null;
let currentTeamTab = 'analysis'; // analysis | session | evaluation
let sttSocket = null;
let mediaRecorder = null;
let timerInterval = null;
let timerSeconds = 0;
let timerRunning = false;
let pollingInterval = null;
let analysisCache = {};
let transcriptCache = {};
let evaluationCache = {};

const SCORE_CATEGORIES = [
    { key: 'architecture', label: 'Architecture & Design', weight: 0.25 },
    { key: 'code_quality', label: 'Code Quality', weight: 0.20 },
    { key: 'completeness', label: 'Completeness', weight: 0.20 },
    { key: 'innovation', label: 'Innovation', weight: 0.15 },
    { key: 'documentation', label: 'Documentation', weight: 0.10 },
    { key: 'presentation', label: 'Presentation', weight: 0.10 },
];

// ── Toast ──────────────────────────────────────────────
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ── Modal ──────────────────────────────────────────────
function showModal(title, body, onConfirm) {
    const overlay = document.getElementById('modal-overlay');
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').textContent = body;
    overlay.classList.remove('hidden');

    const confirmBtn = document.getElementById('modal-confirm');
    const cancelBtn = document.getElementById('modal-cancel');

    const cleanup = () => {
        overlay.classList.add('hidden');
        confirmBtn.replaceWith(confirmBtn.cloneNode(true));
        cancelBtn.replaceWith(cancelBtn.cloneNode(true));
        document.getElementById('modal-cancel').addEventListener('click', () => {
            document.getElementById('modal-overlay').classList.add('hidden');
        });
    };

    confirmBtn.onclick = () => { cleanup(); onConfirm(); };
    cancelBtn.onclick = cleanup;
}

// ── Router ─────────────────────────────────────────────
function navigate(view, teamId = null) {
    currentView = view;
    currentTeamId = teamId;
    if (view !== 'team') currentTeamTab = 'analysis';
    stopPolling();

    // Update nav tabs
    document.querySelectorAll('.nav-tab').forEach(t => {
        t.classList.toggle('active', t.dataset.view === view ||
            (view === 'team' && t.dataset.view === 'dashboard'));
    });

    render();
}

function render() {
    const app = document.getElementById('app');
    switch (currentView) {
        case 'dashboard': renderDashboard(app); break;
        case 'team': renderTeamView(app); break;
        case 'results': renderResults(app); break;
    }
}

// ── API Helpers ────────────────────────────────────────
async function apiFetch(path, options = {}) {
    try {
        const res = await fetch(`${API}${path}`, {
            headers: { 'Content-Type': 'application/json', ...options.headers },
            ...options,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        return res.json();
    } catch (e) {
        if (e.name === 'TypeError' && e.message.includes('fetch')) {
            showToast('Backend nicht erreichbar', 'error');
        } else {
            showToast(e.message, 'error');
        }
        throw e;
    }
}

async function fetchTeams() {
    teams = await apiFetch('/teams');
    return teams;
}

async function createTeam(name, repoUrl) {
    const team = await apiFetch('/teams', {
        method: 'POST',
        body: JSON.stringify({ name, repo_url: repoUrl }),
    });
    teams.push(team);
    return team;
}

async function deleteTeam(id) {
    await apiFetch(`/teams/${id}`, { method: 'DELETE' });
    teams = teams.filter(t => t.id !== id);
    delete analysisCache[id];
    delete transcriptCache[id];
    delete evaluationCache[id];
}

async function analyzeRepo(teamId) {
    return apiFetch(`/teams/${teamId}/analyze`, { method: 'POST' });
}

async function getAnalysis(teamId) {
    const data = await apiFetch(`/teams/${teamId}/analysis`);
    analysisCache[teamId] = data;
    return data;
}

async function getTranscript(teamId) {
    const data = await apiFetch(`/teams/${teamId}/transcript`);
    transcriptCache[teamId] = data;
    return data;
}

async function assignTask(teamId, taskIndex) {
    return apiFetch(`/teams/${teamId}/assign-task`, {
        method: 'POST',
        body: JSON.stringify({ task_index: taskIndex }),
    });
}

async function generateTaskTTS(teamId) {
    return apiFetch(`/teams/${teamId}/task-tts`, { method: 'POST' });
}

async function triggerEvaluation(teamId) {
    return apiFetch(`/teams/${teamId}/evaluate`, { method: 'POST' });
}

async function getEvaluation(teamId) {
    const data = await apiFetch(`/teams/${teamId}/evaluation`);
    evaluationCache[teamId] = data;
    return data;
}

async function updateEvaluation(teamId, data) {
    return apiFetch(`/teams/${teamId}/evaluation`, {
        method: 'PUT',
        body: JSON.stringify(data),
    });
}

async function submitEvaluation(teamId) {
    return apiFetch(`/teams/${teamId}/submit`, { method: 'POST' });
}

async function getResults() {
    return apiFetch('/results');
}

async function exportResults() {
    return apiFetch('/results/export');
}

// ── Render: Dashboard ──────────────────────────────────
async function renderDashboard(app) {
    app.innerHTML = `
        <div class="section-header">
            <div>
                <div class="section-title">Teams</div>
                <div class="section-subtitle">Kollege Codex — IHK Innovationstage 2026</div>
            </div>
        </div>
        <div class="team-grid" id="team-grid">
            <div class="loading-center"><div class="spinner spinner-lg"></div><span>Lade Teams...</span></div>
        </div>
    `;

    try {
        await fetchTeams();
    } catch {
        app.querySelector('#team-grid').innerHTML = '<div class="empty-state">Fehler beim Laden der Teams.</div>';
        return;
    }

    renderTeamGrid();
}

function renderTeamGrid() {
    const grid = document.getElementById('team-grid');
    if (!grid) return;

    let html = '';
    for (const team of teams) {
        html += `
        <div class="card card-clickable" onclick="navigate('team', ${team.id})">
            <div class="team-card-header">
                <div class="team-card-name">${esc(team.name)}</div>
                ${badgeHTML(team.status)}
            </div>
            <div class="team-card-repo">${esc(team.repo_url || 'Kein Repo')}</div>
            <div class="team-card-actions">
                ${team.status === 'pending' ? `<button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); handleAnalyze(${team.id})">Repo analysieren</button>` : ''}
                ${team.status === 'analyzing' ? `<span class="flex items-center gap-8"><span class="spinner"></span> Analyse läuft...</span>` : ''}
                <button class="btn btn-icon btn-sm" onclick="event.stopPropagation(); handleDeleteTeam(${team.id})" title="Löschen">&times;</button>
            </div>
        </div>`;
    }

    // Add team card
    html += `
    <div class="card add-team-card" id="add-team-card" onclick="showAddTeamForm()">
        <div class="add-team-icon">+</div>
        <div class="add-team-label">Team hinzufügen</div>
    </div>`;

    grid.innerHTML = html;
}

function showAddTeamForm() {
    const card = document.getElementById('add-team-card');
    card.onclick = null;
    card.style.cursor = 'default';
    card.innerHTML = `
        <div class="add-form">
            <div class="form-group">
                <label>Teamname</label>
                <input type="text" id="new-team-name" placeholder="z.B. Team Alpha">
            </div>
            <div class="form-group">
                <label>Repo URL</label>
                <input type="url" id="new-team-repo" placeholder="https://github.com/...">
            </div>
            <div class="flex gap-8 mt-8">
                <button class="btn btn-primary btn-sm" onclick="handleCreateTeam()">Erstellen</button>
                <button class="btn btn-secondary btn-sm" onclick="renderTeamGrid()">Abbrechen</button>
            </div>
        </div>
    `;
    document.getElementById('new-team-name').focus();
}

async function handleCreateTeam() {
    const name = document.getElementById('new-team-name').value.trim();
    const repo = document.getElementById('new-team-repo').value.trim();
    if (!name) { showToast('Teamname ist erforderlich', 'error'); return; }
    try {
        await createTeam(name, repo);
        showToast(`Team "${name}" erstellt`, 'success');
        renderTeamGrid();
    } catch { /* toast already shown */ }
}

async function handleDeleteTeam(id) {
    const team = teams.find(t => t.id === id);
    showModal('Team löschen', `"${team?.name}" wirklich löschen? Alle Daten gehen verloren.`, async () => {
        try {
            await deleteTeam(id);
            showToast('Team gelöscht', 'success');
            renderTeamGrid();
        } catch { /* toast */ }
    });
}

async function handleAnalyze(teamId) {
    try {
        await analyzeRepo(teamId);
        showToast('Analyse gestartet', 'info');
        // Update local status
        const team = teams.find(t => t.id === teamId);
        if (team) team.status = 'analyzing';
        renderTeamGrid();
        startAnalysisPolling(teamId);
    } catch { /* toast */ }
}

function startAnalysisPolling(teamId) {
    stopPolling();
    pollingInterval = setInterval(async () => {
        try {
            await fetchTeams();
            const team = teams.find(t => t.id === teamId);
            if (team && team.status !== 'analyzing') {
                stopPolling();
                showToast(`Analyse für "${team.name}" abgeschlossen`, 'success');
            }
            if (currentView === 'dashboard') renderTeamGrid();
            else if (currentView === 'team' && currentTeamId === teamId) render();
        } catch { /* silence */ }
    }, 2000);
}

// ── Render: Team View ──────────────────────────────────
async function renderTeamView(app) {
    const team = teams.find(t => t.id === currentTeamId);
    if (!team) {
        // Try fetching
        try {
            await fetchTeams();
        } catch { /* */ }
    }
    const t = teams.find(t2 => t2.id === currentTeamId);
    if (!t) {
        app.innerHTML = '<div class="empty-state">Team nicht gefunden.</div>';
        return;
    }

    // Start polling if analyzing
    if (t.status === 'analyzing') startAnalysisPolling(t.id);

    app.innerHTML = `
        <div class="back-row">
            <button class="btn btn-secondary btn-sm" onclick="navigate('dashboard')">&#8592; Dashboard</button>
        </div>
        <div class="section-header">
            <div>
                <div class="section-title">${esc(t.name)} ${badgeHTML(t.status)}</div>
                <div class="section-subtitle">${esc(t.repo_url || '')}</div>
            </div>
        </div>
        <div class="tabs">
            <button class="tab ${currentTeamTab === 'analysis' ? 'active' : ''}" onclick="switchTeamTab('analysis')">Analyse</button>
            <button class="tab ${currentTeamTab === 'session' ? 'active' : ''}" onclick="switchTeamTab('session')">Live Session</button>
            <button class="tab ${currentTeamTab === 'evaluation' ? 'active' : ''}" onclick="switchTeamTab('evaluation')">Bewertung</button>
        </div>
        <div id="team-tab-content"></div>
    `;

    switch (currentTeamTab) {
        case 'analysis': renderAnalysisTab(t); break;
        case 'session': renderSessionTab(t); break;
        case 'evaluation': renderEvaluationTab(t); break;
    }
}

function switchTeamTab(tab) {
    currentTeamTab = tab;
    render();
}

// ── Analysis Tab ───────────────────────────────────────
async function renderAnalysisTab(team) {
    const container = document.getElementById('team-tab-content');

    if (team.status === 'pending') {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">&#128269;</div>
                <p>Noch keine Analyse durchgeführt.</p>
                <button class="btn btn-primary mt-16" onclick="handleAnalyze(${team.id})">Repo analysieren</button>
            </div>`;
        return;
    }

    if (team.status === 'analyzing') {
        container.innerHTML = `<div class="loading-center"><div class="spinner spinner-lg"></div><span>Analyse läuft...</span></div>`;
        return;
    }

    // Load analysis data
    container.innerHTML = `<div class="loading-center"><div class="spinner spinner-lg"></div></div>`;
    let analysis;
    try {
        analysis = analysisCache[team.id] || await getAnalysis(team.id);
    } catch {
        container.innerHTML = '<div class="empty-state">Analyse konnte nicht geladen werden.</div>';
        return;
    }

    const scores = tryParse(analysis.scores);
    const justifications = tryParse(analysis.justifications);
    const tasks = tryParse(analysis.generated_tasks);

    let scoresHTML = '';
    for (const cat of SCORE_CATEGORIES) {
        const score = scores?.[cat.key]?.score ?? scores?.[cat.key] ?? 0;
        const just = justifications?.[cat.key] || scores?.[cat.key]?.justification || '';
        scoresHTML += `
            <div class="score-row">
                <div class="score-label">${cat.label}</div>
                <div class="score-bar-wrap">
                    <div class="score-bar ${scoreColorClass(score)}" style="width: ${score * 10}%"></div>
                </div>
                <div class="score-value">${score}</div>
            </div>
            ${just ? `<div class="justification-block"><label>Begründung</label><textarea rows="2" onchange="handleAnalysisJustChange(${team.id}, '${cat.key}', this.value)">${esc(just)}</textarea></div>` : ''}
        `;
    }

    let tasksHTML = '';
    if (Array.isArray(tasks) && tasks.length > 0) {
        tasksHTML = '<div class="section-title mb-16 mt-24">Generierte Aufgaben</div>';
        tasks.forEach((task, i) => {
            const selected = analysis.assigned_task === i;
            const disabled = analysis.assigned_task !== undefined && analysis.assigned_task !== null && analysis.assigned_task !== i;
            tasksHTML += `
                <div class="task-card ${selected ? 'task-selected' : ''} ${disabled ? 'task-disabled' : ''}">
                    <div class="task-card-header">
                        <div class="task-card-title">${esc(task.title || `Aufgabe ${i + 1}`)}</div>
                        ${task.difficulty ? `<span class="badge badge-${task.difficulty}">${esc(task.difficulty)}</span>` : ''}
                    </div>
                    <div class="task-card-desc">${esc(task.description || task.text || '')}</div>
                    ${task.rationale ? `<div class="task-card-rationale">${esc(task.rationale)}</div>` : ''}
                    <button class="btn btn-primary btn-sm" onclick="handleAssignTask(${team.id}, ${i})" ${selected ? 'disabled' : ''}>
                        ${selected ? '&#10003; Zugewiesen' : 'Zuweisen'}
                    </button>
                </div>`;
        });
    }

    container.innerHTML = `
        ${analysis.repo_summary ? `<div class="repo-summary mb-24"><pre>${esc(analysis.repo_summary)}</pre></div>` : ''}
        <div class="section-title mb-16">Score Breakdown</div>
        ${scoresHTML}
        ${tasksHTML}
    `;
}

async function handleAssignTask(teamId, taskIndex) {
    try {
        await assignTask(teamId, taskIndex);
        showToast('Aufgabe zugewiesen', 'success');
        // Update local cache
        if (analysisCache[teamId]) analysisCache[teamId].assigned_task = taskIndex;
        render();
    } catch { /* toast */ }
}

function handleAnalysisJustChange(teamId, key, value) {
    // Store locally; actual save would go through updateEvaluation
    if (!analysisCache[teamId]) return;
    const just = tryParse(analysisCache[teamId].justifications) || {};
    just[key] = value;
    analysisCache[teamId].justifications = JSON.stringify(just);
}

// ── Session Tab ────────────────────────────────────────
async function renderSessionTab(team) {
    const container = document.getElementById('team-tab-content');
    const transcript = transcriptCache[team.id]?.content || '';

    container.innerHTML = `
        <div class="two-col">
            <div>
                <div class="section-title mb-16">Aufnahme</div>
                <div class="flex gap-12 mb-16">
                    <button class="btn btn-primary" id="btn-rec-start" onclick="startRecording(${team.id})">&#9679; Aufnahme starten</button>
                    <button class="btn btn-danger" id="btn-rec-stop" onclick="stopRecording()" disabled>&#9632; Stoppen</button>
                    <span id="rec-status"></span>
                </div>

                <div class="section-title mb-8">Transkript</div>
                <div class="transcript-box" id="transcript-box">${esc(transcript) || 'Noch kein Transkript vorhanden.'}</div>

                <div class="audio-section mt-16">
                    <div class="section-title mb-8">Aufgabe vorlesen (TTS)</div>
                    <button class="btn btn-secondary" onclick="handleSpeakTask(${team.id})">&#128266; Aufgabe vorlesen</button>
                    <div id="tts-player" class="mt-8"></div>
                </div>
            </div>
            <div>
                <div class="section-title mb-16 text-center">Timer</div>
                <div class="timer-display" id="timer-display">05:00</div>
                <div class="timer-controls">
                    <button class="btn btn-primary btn-sm" onclick="startTimer(300)" id="btn-timer-start">Start (5 min)</button>
                    <button class="btn btn-secondary btn-sm" onclick="toggleTimer()" id="btn-timer-toggle" disabled>Pause</button>
                    <button class="btn btn-secondary btn-sm" onclick="resetTimer()">Reset</button>
                </div>
                <div class="flex justify-between mt-16">
                    <button class="btn btn-secondary btn-sm" onclick="startTimer(900)">15 min</button>
                    <button class="btn btn-secondary btn-sm" onclick="startTimer(1200)">20 min</button>
                    <div class="form-group" style="flex-direction:row;align-items:center;gap:6px">
                        <input type="number" id="custom-timer" value="5" min="1" max="60" style="width:60px">
                        <button class="btn btn-secondary btn-sm" onclick="startTimer(parseInt(document.getElementById('custom-timer').value)*60||300)">min</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Restore timer display if running
    if (timerRunning || timerSeconds > 0) updateTimerDisplay();

    // Load existing transcript
    try {
        const data = await getTranscript(team.id);
        if (data?.content) {
            const box = document.getElementById('transcript-box');
            if (box) box.textContent = data.content;
        }
    } catch { /* no transcript yet */ }
}

// ── Evaluation Tab ─────────────────────────────────────
async function renderEvaluationTab(team) {
    const container = document.getElementById('team-tab-content');
    container.innerHTML = `<div class="loading-center"><div class="spinner spinner-lg"></div></div>`;

    let evaluation;
    try {
        evaluation = evaluationCache[team.id] || await getEvaluation(team.id);
    } catch {
        // No evaluation yet
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">&#128202;</div>
                <p>Noch keine Bewertung vorhanden.</p>
                <button class="btn btn-primary mt-16" onclick="handleTriggerEval(${team.id})">Bewertung generieren</button>
            </div>`;
        return;
    }

    const scores = tryParse(evaluation.scores) || {};
    const justifications = tryParse(evaluation.justifications) || {};
    const submitted = evaluation.submitted;
    const weighted = calculateWeightedScore(scores);

    let scoresHTML = '';
    for (const cat of SCORE_CATEGORIES) {
        const score = scores[cat.key]?.score ?? scores[cat.key] ?? 0;
        const just = justifications[cat.key] || scores[cat.key]?.justification || '';
        scoresHTML += `
            <div class="score-row">
                <div class="score-label">${cat.label} (${(cat.weight * 100).toFixed(0)}%)</div>
                <div class="score-bar-wrap">
                    <div class="score-bar ${scoreColorClass(score)}" style="width: ${score * 10}%"></div>
                </div>
                <div class="score-value">${score}</div>
            </div>
            <div class="justification-block">
                <label>Begründung</label>
                <textarea rows="2" data-cat="${cat.key}" ${submitted ? 'disabled' : ''} oninput="recalcWeighted()">${esc(just)}</textarea>
            </div>
        `;
    }

    container.innerHTML = `
        <div class="weighted-score-card">
            <div class="weighted-score-value" id="weighted-score">${weighted.toFixed(1)}</div>
            <div class="weighted-score-label">Gewichtete Gesamtbewertung</div>
        </div>
        ${scoresHTML}
        <div class="flex gap-12 mt-24">
            ${!submitted ? `
                <button class="btn btn-primary" onclick="handleTriggerEval(${team.id})">Bewertung neu generieren</button>
                <button class="btn btn-primary" onclick="handleSaveEval(${team.id})">Speichern</button>
                <button class="btn btn-danger" onclick="handleSubmitEval(${team.id})">Endgültig abgeben</button>
            ` : '<span class="badge badge-submitted">Abgegeben</span>'}
        </div>
    `;
}

function recalcWeighted() {
    // Read scores from evaluation cache; the UI doesn't edit scores, only justifications
    // In a full version you'd make scores editable too
}

async function handleTriggerEval(teamId) {
    try {
        showToast('Bewertung wird generiert...', 'info');
        await triggerEvaluation(teamId);
        delete evaluationCache[teamId];
        showToast('Bewertung generiert', 'success');
        // Update team status
        const team = teams.find(t => t.id === teamId);
        if (team) team.status = 'evaluated';
        render();
    } catch { /* toast */ }
}

async function handleSaveEval(teamId) {
    const textareas = document.querySelectorAll('#team-tab-content textarea[data-cat]');
    const justifications = {};
    textareas.forEach(ta => { justifications[ta.dataset.cat] = ta.value; });
    try {
        await updateEvaluation(teamId, { justifications });
        delete evaluationCache[teamId];
        showToast('Gespeichert', 'success');
    } catch { /* toast */ }
}

async function handleSubmitEval(teamId) {
    showModal('Bewertung abgeben', 'Bewertung endgültig abgeben? Dies kann nicht rückgängig gemacht werden.', async () => {
        // Save first
        await handleSaveEval(teamId);
        try {
            await submitEvaluation(teamId);
            const team = teams.find(t => t.id === teamId);
            if (team) team.status = 'submitted';
            delete evaluationCache[teamId];
            showToast('Bewertung abgegeben', 'success');
            render();
        } catch { /* toast */ }
    });
}

// ── Results View ───────────────────────────────────────
async function renderResults(app) {
    app.innerHTML = `
        <div class="section-header">
            <div class="section-title">Ergebnisse</div>
            <button class="btn btn-secondary" onclick="handleExport()">&#128196; Als Markdown exportieren</button>
        </div>
        <div id="results-list" class="results-list">
            <div class="loading-center"><div class="spinner spinner-lg"></div></div>
        </div>
    `;

    let results;
    try {
        results = await getResults();
    } catch {
        document.getElementById('results-list').innerHTML = '<div class="empty-state">Keine Ergebnisse vorhanden.</div>';
        return;
    }

    if (!results || (Array.isArray(results) && results.length === 0)) {
        document.getElementById('results-list').innerHTML = '<div class="empty-state">Noch keine Bewertungen abgegeben.</div>';
        return;
    }

    const list = Array.isArray(results) ? results : [];
    // Sort by final_score descending
    list.sort((a, b) => (b.final_score || 0) - (a.final_score || 0));

    let html = '';
    list.forEach((r, i) => {
        const rank = i + 1;
        const scores = tryParse(r.scores) || {};
        let breakdownHTML = '';
        for (const cat of SCORE_CATEGORIES) {
            const s = scores[cat.key]?.score ?? scores[cat.key] ?? '-';
            breakdownHTML += `
                <div class="result-cat">
                    <div class="result-cat-label">${cat.key.slice(0, 4)}</div>
                    <div class="result-cat-score">${s}</div>
                </div>`;
        }

        html += `
            <div class="result-row ${rank === 1 ? 'rank-1' : ''}">
                <div class="result-rank ${rank === 1 ? 'rank-1' : ''}">#${rank}</div>
                <div class="result-name">${esc(r.team_name || r.name || `Team ${r.team_id}`)}</div>
                <div class="result-score">${(r.final_score || 0).toFixed(1)}</div>
                <div class="result-breakdown">${breakdownHTML}</div>
            </div>`;
    });

    document.getElementById('results-list').innerHTML = html;
}

async function handleExport() {
    try {
        const data = await exportResults();
        // data should be markdown text or an object with content
        const text = typeof data === 'string' ? data : (data.content || data.markdown || JSON.stringify(data, null, 2));
        const blob = new Blob([text], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'jurybot_ergebnisse.md';
        a.click();
        URL.revokeObjectURL(url);
        showToast('Export heruntergeladen', 'success');
    } catch { /* toast */ }
}

// ── Audio / STT ────────────────────────────────────────
async function startRecording(teamId) {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream, {
            mimeType: 'audio/webm;codecs=opus',
        });

        // Open WebSocket
        const wsUrl = API.replace(/^http/, 'ws').replace('/api', '') + `/ws/stt/${teamId}`;
        sttSocket = new WebSocket(wsUrl);

        sttSocket.onopen = () => {
            showToast('Verbindung hergestellt', 'success');
        };

        sttSocket.onmessage = (event) => {
            const box = document.getElementById('transcript-box');
            if (box) {
                const data = JSON.parse(event.data);
                const text = data.text || data.transcript || event.data;
                box.textContent += text + ' ';
                box.scrollTop = box.scrollHeight;
            }
        };

        sttSocket.onerror = () => {
            showToast('WebSocket Fehler', 'error');
        };

        sttSocket.onclose = () => {
            const status = document.getElementById('rec-status');
            if (status) status.innerHTML = '';
        };

        mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0 && sttSocket?.readyState === WebSocket.OPEN) {
                sttSocket.send(e.data);
            }
        };

        mediaRecorder.start(1500); // chunk every 1.5s

        // Update UI
        const startBtn = document.getElementById('btn-rec-start');
        const stopBtn = document.getElementById('btn-rec-stop');
        const status = document.getElementById('rec-status');
        if (startBtn) startBtn.disabled = true;
        if (stopBtn) stopBtn.disabled = false;
        if (status) status.innerHTML = '<span class="rec-indicator"><span class="rec-dot"></span>Aufnahme</span>';

    } catch (err) {
        showToast('Mikrofon-Zugriff verweigert: ' + err.message, 'error');
    }
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
        mediaRecorder.stream.getTracks().forEach(t => t.stop());
        mediaRecorder = null;
    }
    if (sttSocket) {
        sttSocket.close();
        sttSocket = null;
    }

    const startBtn = document.getElementById('btn-rec-start');
    const stopBtn = document.getElementById('btn-rec-stop');
    const status = document.getElementById('rec-status');
    if (startBtn) startBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = true;
    if (status) status.innerHTML = '';
    showToast('Aufnahme beendet', 'info');
}

// ── TTS ────────────────────────────────────────────────
async function handleSpeakTask(teamId) {
    try {
        showToast('TTS wird generiert...', 'info');
        const data = await generateTaskTTS(teamId);
        const baseUrl = API.replace('/api', '');
        const audioUrl = data.audio_url ? `${baseUrl}${data.audio_url}` : '';
        const player = document.getElementById('tts-player');
        if (player) {
            player.innerHTML = `<audio controls autoplay src="${audioUrl}"></audio>`;
        }
    } catch { /* toast */ }
}

// ── Timer ──────────────────────────────────────────────
function startTimer(seconds = 300) {
    clearInterval(timerInterval);
    timerSeconds = seconds;
    timerRunning = true;
    updateTimerDisplay();

    const toggleBtn = document.getElementById('btn-timer-toggle');
    if (toggleBtn) { toggleBtn.disabled = false; toggleBtn.textContent = 'Pause'; }

    timerInterval = setInterval(() => {
        if (!timerRunning) return;
        timerSeconds--;
        updateTimerDisplay();
        if (timerSeconds <= 0) {
            clearInterval(timerInterval);
            timerRunning = false;
            showToast('Zeit abgelaufen!', 'error');
            // Flash effect
            const display = document.getElementById('timer-display');
            if (display) display.classList.add('timer-danger');
        }
    }, 1000);
}

function toggleTimer() {
    timerRunning = !timerRunning;
    const btn = document.getElementById('btn-timer-toggle');
    if (btn) btn.textContent = timerRunning ? 'Pause' : 'Weiter';
}

function resetTimer() {
    clearInterval(timerInterval);
    timerSeconds = 0;
    timerRunning = false;
    updateTimerDisplay();
    const btn = document.getElementById('btn-timer-toggle');
    if (btn) { btn.disabled = true; btn.textContent = 'Pause'; }
}

function updateTimerDisplay() {
    const display = document.getElementById('timer-display');
    if (!display) return;
    const m = Math.floor(timerSeconds / 60);
    const s = timerSeconds % 60;
    display.textContent = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;

    display.classList.remove('timer-warning', 'timer-danger');
    if (timerSeconds <= 0) display.classList.add('timer-danger');
    else if (timerSeconds <= 30) display.classList.add('timer-danger');
    else if (timerSeconds <= 60) display.classList.add('timer-warning');
}

// ── Score Calculation ──────────────────────────────────
function calculateWeightedScore(scores) {
    let total = 0;
    for (const cat of SCORE_CATEGORIES) {
        const s = scores?.[cat.key]?.score ?? scores?.[cat.key] ?? 0;
        total += s * cat.weight;
    }
    return Math.round(total * 10) / 10;
}

// ── Polling ────────────────────────────────────────────
function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

// ── Helpers ────────────────────────────────────────────
function esc(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = String(str);
    return d.innerHTML;
}

function tryParse(val) {
    if (!val) return null;
    if (typeof val === 'object') return val;
    try { return JSON.parse(val); } catch { return null; }
}

function scoreColorClass(score) {
    if (score <= 3) return 'score-low';
    if (score <= 6) return 'score-mid';
    if (score <= 8) return 'score-high';
    return 'score-top';
}

function badgeHTML(status) {
    const labels = {
        pending: 'Ausstehend',
        analyzing: 'Analyse...',
        analyzed: 'Analysiert',
        presenting: 'Präsentation',
        task: 'Aufgabe',
        evaluated: 'Bewertet',
        submitted: 'Abgegeben',
    };
    return `<span class="badge badge-${status || 'pending'}">${labels[status] || status || 'Ausstehend'}</span>`;
}

// ── Init ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Nav tab clicks
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.addEventListener('click', () => navigate(tab.dataset.view));
    });

    // Modal cancel
    document.getElementById('modal-cancel').addEventListener('click', () => {
        document.getElementById('modal-overlay').classList.add('hidden');
    });

    navigate('dashboard');
});
