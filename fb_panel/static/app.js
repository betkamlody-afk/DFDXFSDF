/**
 * FB Panel — Main Entry Point (ES Module)
 * Multi-page dashboard with sidebar navigation
 */
import { CONFIG } from './js/config.js';
import { state } from './js/state.js';
import { cacheDOM, DOM, setText } from './js/ui/dom.js';
import { showToast } from './js/ui/toast.js';
import { updateStats, resetStats, updateEngineStatusUI } from './js/ui/stats.js';
import { renderLogsList, setOnSuccessClick } from './js/ui/logs-list.js';
import { renderWorkers } from './js/ui/workers-list.js';

import * as ws from './js/ws/socket.js';

import { bindAuthEvents, checkExistingSession } from './js/handlers/auth.js';
import { bindProxyEvents, onValidationProgress, onValidationDone } from './js/handlers/proxy.js';
import { bindLogsEvents, onLogUpdated } from './js/handlers/logs.js';
import { bindEngineEvents, onEngineStarted, onEngineStopped, onEngineStatus } from './js/handlers/engine.js';
import { bindWorkersEvents, updateAntiConnectUI, refreshWorkers, onWorkerUpdate } from './js/handlers/workers.js';
import { bindSettingsEvents, initSettingsUI } from './js/handlers/settings.js';
import { bindModalEvents } from './js/handlers/modal.js';
import { bindExportEvents } from './js/handlers/export.js';
import { bindFilterEvents } from './js/handlers/filter.js';
import { bindSessionEvents, openSessionView, openSessionPreview, launchAndOpen, onSessionCreated, onSessionUpdated } from './js/handlers/session.js';
import { initConfirm } from './js/ui/confirm.js';

import * as proxyApi from './js/api/proxy.js';
import * as logsApi from './js/api/logs.js';
import * as engineApi from './js/api/engine.js';
import * as workersApi from './js/api/workers.js';
import * as sessionApi from './js/api/session.js';
import { getSystemInfo } from './js/api/system.js';

// ══════════════════════════════════════════════════════════════
// PAGE TITLES
// ══════════════════════════════════════════════════════════════
const PAGE_TITLES = {
    home: 'Główna',
    proxy: 'Proxy',
    logs: 'Logi',
    sessions: 'Sesje',
};

// ══════════════════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════════════════

function init() {
    console.log('%c🚀 FB Panel v3.0 — Multi-page', 'color:#10b981;font-size:16px;font-weight:bold');
    cacheDOM();
    bindAll();
    bindNavigation();
    initConfirm();
    initSettingsUI();
    checkExistingSession(showDashboard);

    // When user clicks a success log → choose launch mode first
    setOnSuccessClick(async (log) => {
        // Check if a live session already exists
        try {
            const r = await sessionApi.listSessions();
            if (r.success && r.sessions) {
                state.sessions = r.sessions;
                const session = r.sessions.find(s => s.log_id === log.id && s.status !== 'closed');
                if (session) { openSessionView(session); return; }
            }
        } catch(_){}
        openSessionPreview(log, null, true);
    });
}

document.addEventListener('DOMContentLoaded', init);

// ══════════════════════════════════════════════════════════════
// EVENT BINDING
// ══════════════════════════════════════════════════════════════

function bindAll() {
    bindAuthEvents(showDashboard);
    bindProxyEvents();
    bindLogsEvents();
    bindEngineEvents();
    bindWorkersEvents();
    bindSettingsEvents();
    bindModalEvents();
    bindExportEvents();
    bindFilterEvents();
    bindSessionEvents(showDashboard);

    // Logout event from auth handler — with animation
    window.addEventListener('fb:logout', () => {
        const overlay = document.getElementById('logout-overlay');
        if (overlay) overlay.classList.remove('hidden');
        ws.disconnect();
        stopTimers();
        resetStats();
        setTimeout(() => {
            showAuthScreen();
            if (overlay) overlay.classList.add('hidden');
        }, 1200);
    });

    // WS event subscriptions
    ws.on('log_updated',               onLogUpdated);
    ws.on('log_update',                onLogUpdated);
    ws.on('stats_update',              updateStats);
    ws.on('engine_started',            onEngineStarted);
    ws.on('engine_stopped',            onEngineStopped);
    ws.on('engine_status',             onEngineStatus);
    ws.on('proxy_validation_progress', onValidationProgress);
    ws.on('proxy_validation_done',     (d) => { onValidationDone(d); if (d.proxies) renderProxyTable(d.proxies); });
    ws.on('worker_update',             onWorkerUpdate);
    ws.on('session_created',           onSessionCreated);
    ws.on('session_updated',           onSessionUpdated);
    ws.on('geo_progress',              () => { clearTimeout(window._geoTimer); window._geoTimer = setTimeout(refreshProxyList, 2000); });
    ws.on('error', d => showToast(d.message || 'Błąd', 'error'));
}

// ══════════════════════════════════════════════════════════════
// SIDEBAR NAVIGATION
// ══════════════════════════════════════════════════════════════

function bindNavigation() {
    document.querySelectorAll('.nav-item[data-page]').forEach(btn => {
        btn.addEventListener('click', () => switchPage(btn.dataset.page));
    });
}

function switchPage(pageName) {
    // Update nav items
    document.querySelectorAll('.nav-item[data-page]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.page === pageName);
    });
    // Update pages
    document.querySelectorAll('.page').forEach(p => {
        p.classList.toggle('active', p.id === `page-${pageName}`);
    });
    // Update title
    const titleEl = document.getElementById('page-title');
    if (titleEl) titleEl.textContent = PAGE_TITLES[pageName] || pageName;
    state.currentPage = pageName;

    // Refresh data for the page
    if (pageName === 'proxy') refreshProxyList();
    if (pageName === 'sessions') refreshSessionsList();
}

async function refreshProxyList() {
    try {
        const r = await proxyApi.listProxies();
        if (r.success && r.proxies) {
            renderProxyTable(r.proxies);
            const countEl = document.getElementById('proxy-list-count');
            if (countEl) countEl.textContent = r.proxies.length;
        }
    } catch(_){}
}

function renderProxyTable(proxies) {
    const tbody = document.getElementById('proxy-table-body');
    const empty = document.getElementById('proxy-empty');
    if (!tbody) return;
    if (!proxies.length) {
        tbody.innerHTML = '';
        if (empty) empty.style.display = '';
        return;
    }
    if (empty) empty.style.display = 'none';

    const flagEmoji = (cc) => {
        if (!cc || cc.length !== 2) return '';
        const a = 0x1F1E6;
        return String.fromCodePoint(a + cc.charCodeAt(0) - 65, a + cc.charCodeAt(1) - 65);
    };

    tbody.innerHTML = proxies.map(p => {
        const proto = (p.detected_protocol || p.real_protocol || p.protocol || '—').toUpperCase();
        const isValid = p.is_validated && p.is_available;
        const isFailed = p.is_validated && !p.is_available;
        const statusClass = isValid ? 'valid' : (isFailed ? 'failed' : 'pending');
        const statusText = isValid ? 'OK' : (isFailed ? 'Fail' : '—');
        // HOST: show external_ip (real exit IP) if available, otherwise address
        const hostDisplay = p.external_ip || p.address || '—';
        // For rotating proxies, show short username as label
        const userLabel = p.username ? `<span class="proxy-user-label" title="${esc(p.username)}">${esc(p.username.substring(0, 16))}…</span>` : '';
        // LOKALIZACJA: flag + IP + city, country
        const loc = p.country
            ? `${flagEmoji(p.country_code)} ${p.city || ''}, ${p.country}`
            : (p.external_ip ? `<span class="mono proxy-ip">${esc(p.external_ip)}</span>` : '<span class="geo-pending">Ładowanie…</span>');
        const latency = p.latency_ms ? `${p.latency_ms}ms` : '—';
        return `<tr>
            <td class="mono">${esc(hostDisplay)}${userLabel ? '<br>' + userLabel : ''}</td>
            <td class="mono">${esc(String(p.port || '—'))}</td>
            <td><span class="proxy-type-chip ${proto.toLowerCase()}">${proto}</span></td>
            <td>${loc}</td>
            <td><span class="proxy-status-badge ${statusClass}"></span> ${statusText}</td>
            <td class="mono">${latency}</td>
        </tr>`;
    }).join('');
}
// Expose for proxy handler
window._renderProxyTable = renderProxyTable;

async function refreshSessionsList() {
    try {
        const r = await sessionApi.listSessions();
        if (r.success && r.sessions) {
            state.sessions = r.sessions;
            renderSessionCards(r.sessions);
            const countEl = document.getElementById('sessions-count');
            if (countEl) countEl.textContent = r.sessions.filter(s => s.status !== 'closed').length;
        }
    } catch(_){}
}

function renderSessionCards(sessions) {
    const container = document.getElementById('sessions-list');
    if (!container) return;
    const active = sessions.filter(s => s.status !== 'closed');
    if (!active.length) {
        container.innerHTML = `<div class="empty-state">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="40" height="40"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            <p>Brak aktywnych sesji</p>
            <p class="empty-hint">Otwórz sesję klikając na zalogowany log ze statusem „Sukces"</p>
        </div>`;
        return;
    }
    container.innerHTML = active.map(s => `
        <div class="session-card" data-session-id="${esc(s.id)}">
            <div class="session-card-header">
                <span class="session-card-email">${esc(s.email)}</span>
                <span class="session-card-status"></span>
            </div>
            <div class="session-card-detail"><span>Proxy</span><span>${esc(s.proxy || '—')}</span></div>
            <div class="session-card-detail"><span>Status</span><span>${esc(s.status)}</span></div>
        </div>
    `).join('');

    container.querySelectorAll('.session-card').forEach(card => {
        card.addEventListener('click', () => {
            const session = active.find(s => s.id === card.dataset.sessionId);
            if (session) openSessionView(session);
        });
    });
}

function esc(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

// ══════════════════════════════════════════════════════════════
// SCREEN TRANSITIONS
// ══════════════════════════════════════════════════════════════

function showDashboard() {
    DOM.authScreen?.classList.add('hidden');
    DOM.dashboard?.classList.remove('hidden');
    switchPage('home');
    ws.connect();
    loadInitialData();
    startTimers();
}

function showAuthScreen() {
    DOM.dashboard?.classList.add('hidden');
    DOM.authScreen?.classList.remove('hidden');
    DOM.authScreen?.classList.remove('hidden');
    if (DOM.authKey) DOM.authKey.value = '';
    DOM.authMessage?.classList.add('hidden');
}

// ══════════════════════════════════════════════════════════════
// TIMERS
// ══════════════════════════════════════════════════════════════

function startTimers() {
    stopTimers();
    state._workersTimer = setInterval(refreshWorkers, CONFIG.WORKERS_POLL_MS);
    state._statsTimer   = setInterval(refreshStats,   CONFIG.STATS_POLL_MS);
}

function stopTimers() {
    if (state._workersTimer) { clearInterval(state._workersTimer); state._workersTimer = null; }
    if (state._statsTimer)   { clearInterval(state._statsTimer);   state._statsTimer = null; }
}

// ══════════════════════════════════════════════════════════════
// INITIAL DATA LOAD
// ══════════════════════════════════════════════════════════════

async function loadInitialData() {
    try {
        const [sys, ps, ls, es, ac] = await Promise.all([
            getSystemInfo().catch(()=>null),
            proxyApi.getProxyStats().catch(()=>null),
            logsApi.getStats().catch(()=>null),
            engineApi.getEngineStatus().catch(()=>null),
            workersApi.getAntiConnectStatus().catch(()=>null),
        ]);
        if (sys) console.log('System:', sys);
        if (ps?.success) {
            state.proxyTotal = ps.total||0;
            state.proxyValidated = ps.validated||0;
            setText(DOM.proxyCount, state.proxyTotal);
            setText(DOM.proxyValidCount, '✓ ' + state.proxyValidated);
            setText(DOM.qsProxy, ps.available||state.proxyTotal);
            setText(DOM.qsProxyValid, state.proxyValidated);
        }
        if (ls?.success) updateStats(ls);
        if (es?.success) { state.isRunning = !!es.running; updateEngineStatusUI(); }
        if (ac) { state.settings.antiConnect = ac.enabled !== false; updateAntiConnectUI(); }

        const allLogs = await logsApi.getAll().catch(()=>null);
        if (allLogs?.success && allLogs.logs) { state.logs = allLogs.logs; renderLogsList(); }
        await refreshWorkers();
    } catch(e) { console.error('loadInitialData:', e); }
}

async function refreshStats() {
    if (!state.isAuthorized) return;
    try {
        const [ps, ls] = await Promise.all([proxyApi.getProxyStats().catch(()=>null), logsApi.getStats().catch(()=>null)]);
        if (ps?.success) { setText(DOM.qsProxy, ps.available||0); setText(DOM.qsProxyValid, ps.validated||0); setText(DOM.proxyCount, ps.total||0); }
        if (ls?.success) updateStats(ls);
    } catch(_){}
}

// ══════════════════════════════════════════════════════════════
// DEBUG EXPORT
// ══════════════════════════════════════════════════════════════
window.FBPanel = { state, showToast, DOM };

