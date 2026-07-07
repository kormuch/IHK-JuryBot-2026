console.log('[BOOT] app.js geladen — Script-Start');

// Globaler Error Handler — fängt ALLES
window.onerror = function(msg, src, line, col, err) {
    console.error(`[GLOBAL ERROR] ${msg} in ${src}:${line}:${col}`, err);
    document.body.style.background = '#300';
    const el = document.createElement('div');
    el.style.cssText = 'position:fixed;top:0;left:0;right:0;padding:20px;background:red;color:white;font-size:16px;z-index:99999;font-family:monospace;white-space:pre-wrap';
    el.textContent = `JAVASCRIPT FEHLER:\n${msg}\nDatei: ${src}\nZeile: ${line}, Spalte: ${col}\n\n${err?.stack || ''}`;
    document.body.prepend(el);
};

window.addEventListener('unhandledrejection', (e) => {
    console.error('[GLOBAL PROMISE ERROR]', e.reason);
    const el = document.createElement('div');
    el.style.cssText = 'position:fixed;top:0;left:0;right:0;padding:20px;background:darkred;color:white;font-size:16px;z-index:99999;font-family:monospace;white-space:pre-wrap';
    el.textContent = `PROMISE FEHLER:\n${e.reason?.message || e.reason}\n\n${e.reason?.stack || ''}`;
    document.body.prepend(el);
});

const API = 'http://127.0.0.1:8000/api';
console.log('[BOOT] API URL:', API);

// ── State ──────────────────────────────────────────────
let teams = [];
let currentView = 'dashboard';
let currentTeamId = null;
let currentTeamTab = 'analysis'; // analysis | session
let pollingInterval = null;
let analysisCache = {};

const SCORE_CATEGORIES = [
    { key: 'ambition', label: 'Ambition & Originalität', weight: 0.35 },
    { key: 'praktikabilitaet', label: 'Praktikabilität', weight: 0.35 },
    { key: 'umsetzung', label: 'Umsetzung', weight: 0.30 },
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
    console.log(`[NAV] navigate("${view}", ${teamId})`);
    currentView = view;
    currentTeamId = teamId;
    if (view !== 'team') currentTeamTab = 'analysis';
    stopPolling();

    document.querySelectorAll('.nav-tab').forEach(t => {
        t.classList.toggle('active', t.dataset.view === view ||
            (view === 'team' && t.dataset.view === 'dashboard'));
    });

    console.log('[NAV] render() wird aufgerufen...');
    render();
}

function render() {
    console.log(`[RENDER] render() — currentView="${currentView}"`);
    const app = document.getElementById('app');
    console.log('[RENDER] #app Element:', app, '| innerHTML-Länge:', app?.innerHTML?.length);
    if (!app) { console.error('[RENDER] FEHLER: #app nicht gefunden!'); return; }
    switch (currentView) {
        case 'dashboard': console.log('[RENDER] → renderDashboard()'); renderDashboard(app); break;
        case 'team': console.log('[RENDER] → renderTeamView()'); renderTeamView(app); break;
        case 'results': console.log('[RENDER] → renderResults()'); renderResults(app); break;
        case 'config': console.log('[RENDER] → renderConfig()'); renderConfig(app); break;
        default: console.error(`[RENDER] FEHLER: Unbekannte View "${currentView}"`);
    }
}

// ── API Helpers ────────────────────────────────────────
async function apiFetch(path, options = {}) {
    console.log(`[API] fetch ${options.method || 'GET'} ${API}${path}`);
    try {
        const res = await fetch(`${API}${path}`, {
            headers: { 'Content-Type': 'application/json', ...options.headers },
            ...options,
        });
        console.log(`[API] Response: ${res.status} ${res.statusText} für ${path}`);
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        console.log(`[API] Daten erhalten für ${path}:`, typeof data, Array.isArray(data) ? `(${data.length} Einträge)` : '');
        return data;
    } catch (e) {
        console.error(`[API] FEHLER bei ${path}:`, e.message);
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
}

async function analyzeRepo(teamId) {
    return apiFetch(`/teams/${teamId}/analyze`, { method: 'POST' });
}

async function getAnalysis(teamId) {
    const data = await apiFetch(`/teams/${teamId}/analysis`);
    analysisCache[teamId] = data;
    return data;
}

async function generateVerdictText(teamId) {
    return apiFetch(`/teams/${teamId}/verdict-text`, { method: 'POST' });
}

async function generateVerdictTTS(teamId) {
    return apiFetch(`/teams/${teamId}/verdict-tts`, { method: 'POST' });
}


async function getResults() {
    return apiFetch('/results');
}

async function exportResults() {
    return apiFetch('/results/export');
}

// ── Render: Dashboard ──────────────────────────────────
async function renderDashboard(app) {
    console.log('[DASHBOARD] renderDashboard() gestartet');
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
    console.log('[DASHBOARD] Loading-HTML gesetzt, #app innerHTML-Länge:', app.innerHTML.length);

    try {
        console.log('[DASHBOARD] fetchTeams() wird aufgerufen...');
        await fetchTeams();
        console.log('[DASHBOARD] fetchTeams() erfolgreich, teams:', JSON.stringify(teams));
    } catch (e) {
        console.error('[DASHBOARD] fetchTeams() FEHLER:', e);
        app.querySelector('#team-grid').innerHTML = '<div class="empty-state">Fehler beim Laden der Teams.</div>';
        return;
    }

    console.log('[DASHBOARD] renderTeamGrid() wird aufgerufen...');
    renderTeamGrid();
    console.log('[DASHBOARD] renderTeamGrid() abgeschlossen');
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
            ${team.status === 'error' && team.error_message ? `<div class="team-card-error">${esc(team.error_message)}</div>` : ''}
            <div class="team-card-actions">
                ${team.status === 'pending' || team.status === 'error' ? `<button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); handleAnalyze(${team.id})">Repo analysieren</button>` : ''}
                ${team.status === 'analyzing' ? `<span class="flex items-center gap-8"><span class="spinner"></span> Analyse läuft...</span>` : ''}
                <button class="btn btn-icon btn-sm" onclick="event.stopPropagation(); handleDeleteTeam(${team.id})" title="Löschen">&times;</button>
            </div>
        </div>`;
    }

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
        try { await fetchTeams(); } catch { /* */ }
    }
    const t = teams.find(t2 => t2.id === currentTeamId);
    if (!t) {
        app.innerHTML = '<div class="empty-state">Team nicht gefunden.</div>';
        return;
    }

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
        </div>
        <div id="team-tab-content"></div>
    `;

    switch (currentTeamTab) {
        case 'analysis': renderAnalysisTab(t); break;
        case 'session': renderSessionTab(t); break;
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
    // Check for plausibility warning from LLM service
    let warningHTML = '';
    if (scores?._plausibility_warning) {
        warningHTML = `<div class="plausibility-warning">&#9888; ${esc(scores._plausibility_warning)}</div>`;
    }

    let scoresHTML = warningHTML;
    for (const cat of SCORE_CATEGORIES) {
        const score = scores?.[cat.key]?.score ?? scores?.[cat.key] ?? 0;
        const just = justifications?.[cat.key] || scores?.[cat.key]?.justification || '';
        scoresHTML += `
            <div class="score-row">
                <div class="score-label">${cat.label} (${(cat.weight * 100).toFixed(0)}%)</div>
                <div class="score-bar-wrap">
                    <div class="score-bar ${scoreColorClass(score)}" style="width: ${score * 10}%"></div>
                </div>
                <div class="score-value">${score}</div>
            </div>
            ${just ? `<div class="justification-block"><label>Jury-Kommentar</label><div class="justification-text">${esc(just)}</div></div>` : ''}
        `;
    }

    container.innerHTML = `
        ${analysis.repo_summary ? `<details class="repo-summary-details mb-24"><summary class="repo-summary-toggle">Technische Details</summary><pre class="repo-summary-pre">${esc(typeof analysis.repo_summary === 'object' ? JSON.stringify(analysis.repo_summary, null, 2) : analysis.repo_summary)}</pre></details>` : ''}
        <div class="section-title mb-16">Bewertung</div>
        ${scoresHTML}
    `;
}

// ── Session Tab ────────────────────────────────────────
async function renderSessionTab(team) {
    const container = document.getElementById('team-tab-content');

    // Always fetch fresh — verdict_text/audio_url may have been added after initial cache
    let verdictText = '';
    let audioUrl = '';
    try {
        const analysis = await getAnalysis(team.id);
        verdictText = analysis?.verdict_text || '';
        audioUrl = analysis?.audio_url || '';
    } catch { /* ignore */ }

    const bUrl = API.replace('/api', '');
    const fullAudioUrl = audioUrl ? `${bUrl}${audioUrl}` : '';

    container.innerHTML = `
        <div class="section-title mb-16">Jury-Urteil</div>
        <div class="flex gap-12 mb-16">
            <button class="btn btn-secondary" onclick="handleRegenerateAll(${team.id})">&#8635; Neu generieren</button>
        </div>
        <div id="verdict-text" class="mt-8">${verdictText ? `<div class="verdict-card"><p>${esc(verdictText)}</p></div>` : '<div class="empty-state">Kein Urteil vorhanden. Wird automatisch bei der Analyse generiert.</div>'}</div>
        <div id="verdict-player" class="mt-8">${fullAudioUrl ? `<audio controls src="${fullAudioUrl}"></audio>` : ''}</div>
    `;

    if (verdictText) lastVerdictText = verdictText;
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
                    <div class="result-cat-label">${cat.label.slice(0, 6)}</div>
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

// ── Config View ──────────────────────────────────────
async function renderConfig(app) {
    app.innerHTML = `<div class="loading-center"><div class="spinner spinner-lg"></div></div>`;

    let config;
    try {
        config = await apiFetch('/config');
    } catch {
        app.innerHTML = '<div class="empty-state">Konfiguration konnte nicht geladen werden.</div>';
        return;
    }

    const providerOptions = (config.available_providers || []).map(p =>
        `<option value="${p.id}" ${p.id === config.llm_provider ? 'selected' : ''} ${!p.has_key ? 'disabled' : ''}>${p.label}${!p.has_key ? ' (kein Key)' : ''}</option>`
    ).join('');

    const voiceOptions = (config.available_voices || []).map(v =>
        `<option value="${v.id}" ${v.id === config.tts_voice ? 'selected' : ''}>${v.label}</option>`
    ).join('');

    const weights = config.score_weights || {};

    app.innerHTML = `
        <div class="section-header">
            <div class="section-title">Bot-Konfiguration</div>
            <div class="flex gap-12">
                <button class="btn btn-primary" onclick="handleSaveConfig()">Änderungen speichern</button>
            </div>
        </div>

        <div class="config-grid">
            <div class="config-section">
                <div class="config-section-title">LLM-Einstellungen</div>
                <div class="form-group">
                    <label>Anbieter</label>
                    <select id="cfg-provider">${providerOptions}</select>
                </div>
                <div class="form-group">
                    <label>Modell</label>
                    <input type="text" id="cfg-model" value="${esc(config.llm_model || '')}">
                </div>
            </div>

            <div class="config-section">
                <div class="config-section-title">Sprachausgabe</div>
                <div class="form-group">
                    <label>Stimme</label>
                    <select id="cfg-voice">${voiceOptions}</select>
                </div>
                <div class="form-group">
                    <button class="btn btn-secondary btn-sm" onclick="handleTestVoice()">Stimme testen</button>
                    <div id="voice-test-player" class="mt-8"></div>
                </div>
            </div>

            <div class="config-section">
                <div class="config-section-title">Bewertungsgewichtung</div>
                <div class="form-group">
                    <label>Ambition & Originalität</label>
                    <input type="number" id="cfg-w-ambition" value="${weights.ambition || 0.35}" min="0" max="1" step="0.05">
                </div>
                <div class="form-group">
                    <label>Praktikabilität</label>
                    <input type="number" id="cfg-w-praktikabilitaet" value="${weights.praktikabilitaet || 0.35}" min="0" max="1" step="0.05">
                </div>
                <div class="form-group">
                    <label>Umsetzung</label>
                    <input type="number" id="cfg-w-umsetzung" value="${weights.umsetzung || 0.30}" min="0" max="1" step="0.05">
                </div>
                <div class="config-weight-sum" id="cfg-weight-sum"></div>
            </div>
        </div>

        <div class="config-prompts">
            <div class="config-section">
                <div class="config-section-title">Bewertungs-Prompt</div>
                <p class="config-hint">Dieser Prompt wird dem LLM als System-Anweisung gegeben, wenn ein Repository bewertet wird.</p>
                <textarea id="cfg-eval-prompt" class="config-textarea" rows="20">${esc(config.evaluation_prompt || '')}</textarea>
            </div>

            <div class="config-section">
                <div class="config-section-title">Urteil-Prompt</div>
                <p class="config-hint">Dieser Prompt steuert die Generierung des gesprochenen Jury-Urteils.</p>
                <textarea id="cfg-verdict-prompt" class="config-textarea" rows="12">${esc(config.verdict_prompt || '')}</textarea>
            </div>
        </div>
    `;

    updateWeightSum();
    document.getElementById('cfg-w-ambition').addEventListener('input', updateWeightSum);
    document.getElementById('cfg-w-praktikabilitaet').addEventListener('input', updateWeightSum);
    document.getElementById('cfg-w-umsetzung').addEventListener('input', updateWeightSum);
}

function updateWeightSum() {
    const a = parseFloat(document.getElementById('cfg-w-ambition')?.value || 0);
    const p = parseFloat(document.getElementById('cfg-w-praktikabilitaet')?.value || 0);
    const u = parseFloat(document.getElementById('cfg-w-umsetzung')?.value || 0);
    const sum = a + p + u;
    const el = document.getElementById('cfg-weight-sum');
    if (el) {
        const ok = Math.abs(sum - 1.0) < 0.05;
        el.textContent = `Summe: ${sum.toFixed(2)}`;
        el.className = `config-weight-sum ${ok ? 'config-weight-ok' : 'config-weight-err'}`;
    }
}

async function handleSaveConfig() {
    const payload = {
        evaluation_prompt: document.getElementById('cfg-eval-prompt')?.value,
        verdict_prompt: document.getElementById('cfg-verdict-prompt')?.value,
        llm_provider: document.getElementById('cfg-provider')?.value,
        llm_model: document.getElementById('cfg-model')?.value,
        tts_voice: document.getElementById('cfg-voice')?.value,
        score_weights: {
            ambition: parseFloat(document.getElementById('cfg-w-ambition')?.value || 0.35),
            praktikabilitaet: parseFloat(document.getElementById('cfg-w-praktikabilitaet')?.value || 0.35),
            umsetzung: parseFloat(document.getElementById('cfg-w-umsetzung')?.value || 0.30),
        },
    };

    try {
        const data = await apiFetch('/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        showToast(`Gespeichert: ${(data.updated || []).join(', ')}`, 'success');
    } catch (e) {
        showToast('Fehler beim Speichern', 'error');
    }
}

async function handleTestVoice() {
    const voice = document.getElementById('cfg-voice')?.value;
    const text = 'Dies ist ein Test der Jury-Stimme. Was heraussticht, ist die Qualität eurer Umsetzung.';
    try {
        showToast('Teste Stimme...', 'info');
        // Use the TTS endpoint directly with the selected voice
        const res = await fetch(`${API}/tts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, voice }),
        });
        const data = await res.json();
        const baseUrl = API.replace('/api', '');
        const player = document.getElementById('voice-test-player');
        if (player && data.audio_url) {
            player.innerHTML = `<audio controls autoplay src="${baseUrl}${data.audio_url}"></audio>`;
        }
    } catch { showToast('Stimmtest fehlgeschlagen', 'error'); }
}

// ── TTS / Verdict ─────────────────────────────────────
let lastVerdictText = '';

async function handleRegenerateAll(teamId) {
    const verdictDiv = document.getElementById('verdict-text');
    const player = document.getElementById('verdict-player');

    // Show progress bar
    if (verdictDiv) {
        verdictDiv.innerHTML = `
            <div class="verdict-progress">
                <div class="verdict-progress-label">Urteil wird generiert...</div>
                <div class="progress-bar"><div class="progress-bar-fill" id="verdict-progress-fill" style="width: 30%"></div></div>
            </div>`;
    }
    if (player) player.innerHTML = '';

    try {
        // Step 1: Generate verdict text
        const data = await generateVerdictText(teamId);
        lastVerdictText = data.text || '';
        delete analysisCache[teamId];

        if (verdictDiv && lastVerdictText) {
            verdictDiv.innerHTML = `<div class="verdict-card"><p>${esc(lastVerdictText)}</p></div>`;
        }

        // Step 2: Generate TTS
        if (player) {
            player.innerHTML = `
                <div class="verdict-progress">
                    <div class="verdict-progress-label">Audio wird erzeugt...</div>
                    <div class="progress-bar"><div class="progress-bar-fill" style="width: 60%; animation: progress-pulse 1.5s ease-in-out infinite"></div></div>
                </div>`;
        }
        const ttsData = await generateVerdictTTS(teamId);
        const bUrl = API.replace('/api', '');
        const audioUrl = ttsData.audio_url ? `${bUrl}${ttsData.audio_url}` : '';
        if (player && audioUrl) {
            player.innerHTML = `<audio controls src="${audioUrl}"></audio>`;
        }
        showToast('Urteil + Audio fertig', 'success');
    } catch (e) {
        showToast('Fehler: ' + (e.message || e), 'error');
    }
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
        error: 'Fehler',
    };
    return `<span class="badge badge-${status || 'pending'}">${labels[status] || status || 'Ausstehend'}</span>`;
}

// ── Init ───────────────────────────────────────────────
console.log('[BOOT] DOMContentLoaded-Listener wird registriert...');
document.addEventListener('DOMContentLoaded', () => {
    console.log('[INIT] DOMContentLoaded gefeuert');
    console.log('[INIT] document.readyState:', document.readyState);
    console.log('[INIT] #app Element:', document.getElementById('app'));
    console.log('[INIT] .nav-tab Anzahl:', document.querySelectorAll('.nav-tab').length);
    console.log('[INIT] #modal-cancel:', document.getElementById('modal-cancel'));

    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.addEventListener('click', () => navigate(tab.dataset.view));
    });

    const modalCancel = document.getElementById('modal-cancel');
    if (modalCancel) {
        modalCancel.addEventListener('click', () => {
            document.getElementById('modal-overlay').classList.add('hidden');
        });
    } else {
        console.error('[INIT] FEHLER: #modal-cancel nicht gefunden!');
    }

    console.log('[INIT] navigate("dashboard") wird aufgerufen...');
    navigate('dashboard');
    console.log('[INIT] navigate("dashboard") abgeschlossen');
});
