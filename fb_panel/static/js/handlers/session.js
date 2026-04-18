/** Session handlers — wires 3-tab session view with live Selenium browser */
import { state } from '../state.js';
import { DOM, setText } from '../ui/dom.js';
import { showToast } from '../ui/toast.js';
import { renderSessionView, switchTab, startScreenshotPolling, stopScreenshotPolling, setActionButtonsEnabled } from '../ui/session-view.js';
import * as sessionApi from '../api/session.js';
import * as proxyApi from '../api/proxy.js';

let _showDashboard = null;

function closeLaunchModeModal() {
    document.getElementById('launch-mode-modal')?.classList.add('hidden');
}

function openLaunchModeModal(logEntry) {
    state._previewLog = logEntry;
    const emailEl = document.getElementById('launch-mode-email');
    if (emailEl) emailEl.textContent = logEntry?.email || '—';
    document.getElementById('launch-mode-modal')?.classList.remove('hidden');
}

function closeVncWaitModal() {
    document.getElementById('vnc-wait-modal')?.classList.add('hidden');
}

function openVncWaitModal(session) {
    const linkEl = document.getElementById('vnc-link');
    const statusEl = document.getElementById('vnc-status-text');
    if (linkEl) {
        linkEl.textContent = session.vnc_register_url || '—';
        linkEl.href = session.vnc_register_url || '#';
    }
    if (statusEl) {
        statusEl.textContent = session.vnc_status === 'connected'
            ? 'VNC zarejestrowane. Wracamy do sesji.'
            : 'Czekam na odpalenie i rejestrację VNC...';
    }
    document.getElementById('vnc-wait-modal')?.classList.remove('hidden');
}

function stopVncStatusPolling() {
    if (state._vncStatusTimer) {
        clearInterval(state._vncStatusTimer);
        state._vncStatusTimer = null;
    }
}

function startVncStatusPolling(sid) {
    stopVncStatusPolling();
    state._vncStatusTimer = setInterval(async () => {
        try {
            const r = await sessionApi.getVncStatus(sid);
            if (!r.success) return;
            const s = state.activeSession;
            if (!s || s.id !== sid) return;
            s.vnc_status = r.status;
            s.vnc_register_url = r.register_url || s.vnc_register_url;
            s.vnc_connected_at = r.connected_at || '';
            s.vnc_launcher = r.launcher || '';
            if (r.status === 'connected') {
                s.status = 'active';
                renderSessionView(s);
                closeVncWaitModal();
                stopVncStatusPolling();
                showToast('VNC zarejestrowane — sesja gotowa', 'success');
            }
        } catch (_) {}
    }, 2000);
}

/** Check if a response indicates the browser session crashed. */
function _handleCrashed(r) {
    if (r && r.crashed) {
        stopScreenshotPolling();
        setActionButtonsEnabled(false);
        const s = state.activeSession;
        if (s) s.status = 'crashed';
        const statusEl = document.getElementById('sv-status');
        if (statusEl) {
            statusEl.textContent = '✖ Przeglądarka padła';
            statusEl.style.color = 'var(--danger, #ef4444)';
        }
        showToast('Przeglądarka umarła — zamknij sesję i otwórz ponownie', 'error');
        return true;
    }
    return false;
}

export function bindSessionEvents(showDashboardFn) {
    _showDashboard = showDashboardFn;

    document.getElementById('btn-launch-mode-selenium')?.addEventListener('click', () => {
        const logEntry = state._previewLog;
        closeLaunchModeModal();
        if (logEntry) openSessionPreview(logEntry, 'selenium');
    });
    document.getElementById('btn-launch-mode-vnc')?.addEventListener('click', () => {
        const logEntry = state._previewLog;
        closeLaunchModeModal();
        if (logEntry) openSessionPreview(logEntry, 'vnc');
    });
    document.querySelector('#launch-mode-modal .modal-overlay')?.addEventListener('click', closeLaunchModeModal);
    document.getElementById('btn-open-vnc-link')?.addEventListener('click', () => {
        const href = document.getElementById('vnc-link')?.href;
        if (href && href !== '#') window.open(href, '_blank', 'noopener');
    });

    // Back button
    document.getElementById('btn-back-dashboard')?.addEventListener('click', goBackToDashboard);

    // Tab switching
    document.querySelectorAll('.session-tab').forEach(tab => {
        tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });

    // Topbar actions
    document.getElementById('btn-sv-check-proxy')?.addEventListener('click', handleCheckProxy);
    document.getElementById('btn-sv-change-proxy')?.addEventListener('click', handleChangeProxy);
    document.getElementById('btn-sv-close-session')?.addEventListener('click', handleCloseSession);

    // Tab 1: Email actions
    document.getElementById('btn-sv-login-email')?.addEventListener('click', handleLoginEmail);
    document.getElementById('btn-sv-refresh-inbox')?.addEventListener('click', handleRefreshInbox);
    document.getElementById('btn-sv-search-code')?.addEventListener('click', handleSearchCode);
    document.getElementById('btn-sv-refresh-email-tab')?.addEventListener('click', () => handleRefreshTab('email'));

    // Tab 2: FB actions
    document.getElementById('btn-sv-extract-code')?.addEventListener('click', handleExtractCode);
    document.getElementById('btn-sv-enter-code')?.addEventListener('click', handleEnterCode);
    document.getElementById('btn-sv-refresh-fb-tab')?.addEventListener('click', () => handleRefreshTab('facebook'));

    // Tab 3: Panel actions
    document.getElementById('btn-sv-open-profile')?.addEventListener('click', handleOpenProfile);
    document.getElementById('btn-sv-refresh-panel-tab')?.addEventListener('click', () => handleRefreshTab('panel'));

    // Tab 3: Auto-action toggles
    document.getElementById('btn-sv-auto-logout')?.addEventListener('click', () => toggleAction('auto-logout'));
    document.getElementById('btn-sv-auto-disconnect')?.addEventListener('click', () => toggleAction('auto-disconnect'));
    document.getElementById('btn-sv-auto-delete-posts')?.addEventListener('click', () => toggleAction('auto-delete-posts'));
    document.getElementById('btn-sv-auto-delete-stories')?.addEventListener('click', () => toggleAction('auto-delete-stories'));

    // Tab 3: Manual actions
    document.getElementById('btn-sv-delete-posts')?.addEventListener('click', handleDeletePosts);
    document.getElementById('btn-sv-delete-stories')?.addEventListener('click', handleDeleteStories);
    document.getElementById('btn-sv-disconnect-now')?.addEventListener('click', handleDisconnectNow);
    // Launch browser button (in session preview)
    document.getElementById('btn-sv-launch-browser')?.addEventListener('click', handleLaunchBrowser);
}

// ── Screen transitions ────────────────────────────────────────

export function openSessionView(session) {
    state.activeSession = session;
    renderSessionView(session);
    switchTab('email');

    // Hide launch button since browser is already running
    const launchBtn = document.getElementById('btn-sv-launch-browser');
    if (launchBtn) launchBtn.classList.add('hidden');

    // Enable action buttons (renderSessionView does this, but ensure it)
    setActionButtonsEnabled(session.status === 'active' && !!session.id);

    document.getElementById('dashboard')?.classList.add('hidden');
    const sv = document.getElementById('session-view');
    if (sv) { sv.classList.remove('hidden'); }

    if (session.mode === 'vnc' && session.status === 'awaiting_vnc') {
        openVncWaitModal(session);
        startVncStatusPolling(session.id);
    } else {
        closeVncWaitModal();
        stopVncStatusPolling();
        startScreenshotPolling();
    }
}

/**
 * Open session panel as a preview (no browser launched yet).
 * Shows log info and a button to launch the browser.
 */
export function openSessionPreview(logEntry, mode = 'selenium', askMode = false) {
    if (askMode) {
        openLaunchModeModal(logEntry);
        return;
    }
    const provider = logEntry.email?.split('@')[1] || 'unknown';
    // Create a fake session object for renderSessionView
    const preview = {
        id: null,
        log_id: logEntry.id,
        email: logEntry.email,
        password: logEntry.password,
        proxy: logEntry.proxy || '',
        worker_os: logEntry.worker_os || '',
        code: logEntry.code || '',
        mode,
        email_provider: provider,
        email_logged_in: false,
        status: 'preview',
        vnc_status: '',
        vnc_register_url: '',
        tabs: [],
        profile: {},
    };
    state.activeSession = preview;
    state._previewLog = logEntry;
    renderSessionView(preview);
    switchTab('email');

    // Disable all action buttons — no live browser yet
    setActionButtonsEnabled(false);

    // Show the launch button
    const launchBtn = document.getElementById('btn-sv-launch-browser');
    if (launchBtn) {
        launchBtn.classList.remove('hidden');
        launchBtn.textContent = mode === 'vnc' ? '🖥 Otwórz VNC' : '🚀 Odpal przeglądarkę';
    }

    document.getElementById('dashboard')?.classList.add('hidden');
    const sv = document.getElementById('session-view');
    if (sv) sv.classList.remove('hidden');
}

function goBackToDashboard() {
    stopScreenshotPolling();
    stopVncStatusPolling();
    closeVncWaitModal();
    closeLaunchModeModal();
    state.activeSession = null;
    state._previewLog = null;
    const sv = document.getElementById('session-view');
    if (sv) sv.classList.add('hidden');
    document.getElementById('dashboard')?.classList.remove('hidden');
}

// ── Launch browser (from preview panel button) ────────────────

async function handleLaunchBrowser() {
    const logEntry = state._previewLog;
    if (!logEntry) {
        showToast('Brak danych loga — wróć do listy', 'error');
        return;
    }
    const mode = state.activeSession?.mode || 'selenium';
    // Disable launch button and show loading state
    const launchBtn = document.getElementById('btn-sv-launch-browser');
    if (launchBtn) { launchBtn.disabled = true; launchBtn.textContent = mode === 'vnc' ? '⏳ Tworzenie VNC...' : '⏳ Uruchamianie...'; }
    setActionButtonsEnabled(false);

    // Update status to loading
    if (state.activeSession) state.activeSession.status = 'loading';
    const statusEl = document.getElementById('sv-status');
    if (statusEl) {
        statusEl.textContent = mode === 'vnc' ? '⏳ Przygotowanie sesji VNC...' : '⏳ Uruchamianie przeglądarki...';
        statusEl.style.color = 'var(--warning, #f59e0b)';
    }

    await launchAndOpen(logEntry, mode);

    // Re-enable launch button if launch failed
    if (state.activeSession && !state.activeSession.id) {
        if (launchBtn) { launchBtn.disabled = false; launchBtn.textContent = mode === 'vnc' ? '🖥 Otwórz VNC' : '🚀 Odpal przeglądarkę'; }
        if (state.activeSession) state.activeSession.status = 'preview';
        renderSessionView(state.activeSession);
    }
}

// ── Launch (called from app.js when user clicks green log) ────

export async function launchAndOpen(logEntry, mode = 'selenium') {
    showToast(mode === 'vnc' ? 'Przygotowanie sesji VNC...' : 'Uruchamianie przeglądarki Selenium...', 'info');
    try {
        const r = await sessionApi.launchSession(logEntry.id, logEntry.worker_os || '', mode);
        if (r.success && r.session) {
            // Attach proxy info (IP/geo) from pre-launch check
            if (r.proxy_info) {
                r.session.proxy_info = r.proxy_info;
            }
            // Attach auto-action results
            if (r.email_logged_in) r.session.email_logged_in = true;
            if (r.fb_code) r.session.fb_code = r.fb_code;

            state.sessions = state.sessions || [];
            state.sessions.push(r.session);
            openSessionView(r.session);

            if (mode === 'vnc') {
                showToast('Sesja VNC utworzona — otwórz link i poczekaj na rejestrację', 'info');
                return;
            }

            // Build summary toast with all auto-results
            const parts = [];
            if (r.proxy_info && r.proxy_info.ip) {
                const pi = r.proxy_info;
                parts.push(`IP: ${pi.ip} (${pi.country || '?'}, ${pi.city || '?'}) ${pi.latency_ms}ms`);
            }
            if (r.email_logged_in) {
                parts.push('✉ Poczta zalogowana');
            } else {
                parts.push('✉ Poczta: ręcznie zaloguj');
            }
            if (r.code_extracted && r.fb_code) {
                parts.push(`🔑 Kod FB: ${r.fb_code} (auto-wpisany)`);
            }
            showToast(parts.join(' | ') || 'Przeglądarka uruchomiona', 'success');
        } else {
            showToast(r.error || 'Nie udało się uruchomić przeglądarki', 'error');
        }
    } catch (e) {
        showToast(e.message, 'error');
    }
}

// ── Topbar actions ────────────────────────────────────────────

async function handleCheckProxy() {
    const s = state.activeSession;
    const proxyStr = s?.proxy || (state._previewLog?.proxy);
    if (!proxyStr) { showToast('Brak proxy do sprawdzenia', 'warning'); return; }

    const btn = document.getElementById('btn-sv-check-proxy');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Sprawdzam...'; }

    try {
        const r = await proxyApi.checkProxy(proxyStr);
        if (r.ok) {
            // Update session proxy_info
            if (s) s.proxy_info = r;
            renderSessionView(s);
            showToast(`Proxy OK — IP: ${r.ip} (${r.country || '?'}, ${r.city || '?'}) ${r.latency_ms}ms`, 'success');
        } else {
            showToast(`Proxy nie działa: ${r.error || 'Nieznany błąd'}`, 'error');
        }
    } catch (e) {
        showToast(`Błąd sprawdzania proxy: ${e.message}`, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '🔍 Check'; }
    }
}

async function handleChangeProxy() {
    const s = state.activeSession;
    if (!s || !s.id) return;

    const btn = document.getElementById('btn-sv-change-proxy');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Zmieniam proxy...'; }
    setActionButtonsEnabled(false);

    try {
        const r = await sessionApi.changeProxy(s.id);
        if (_handleCrashed(r)) return;

        if (r.success) {
            if (r.session) {
                if (r.proxy_info) r.session.proxy_info = r.proxy_info;
                state.activeSession = r.session;
                renderSessionView(r.session);
            }
            setActionButtonsEnabled(true);

            const parts = ['Proxy zmienione'];
            if (r.restarted) parts.push('przeglądarka zrestartowana');
            if (r.proxy_info && r.proxy_info.ip) {
                const pi = r.proxy_info;
                parts.push(`IP: ${pi.ip} (${pi.country || '?'}, ${pi.city || '?'})`);
            }
            if (r.email_logged_in) parts.push('poczta zalogowana ✓');
            showToast(parts.join(' | '), 'success');
        } else {
            showToast(r.error || 'Brak proxy', 'error');
            setActionButtonsEnabled(true);
        }
    } catch (e) {
        showToast(e.message, 'error');
        setActionButtonsEnabled(true);
    }
    if (btn) { btn.disabled = false; btn.textContent = '🔄 Zmień proxy'; }
}

async function handleCloseSession() {
    const s = state.activeSession;
    if (!s || !s.id) { goBackToDashboard(); return; }
    try {
        const r = await sessionApi.closeSession(s.id);
        if (r.success) {
            stopVncStatusPolling();
            closeVncWaitModal();
            showToast(s.mode === 'vnc' ? 'Sesja VNC zamknięta' : 'Sesja zamknięta — przeglądarka zamknięta', 'info');
            goBackToDashboard();
        }
    } catch (e) { showToast(e.message, 'error'); }
}

// ── Tab 1: Email actions (real Selenium) ──────────────────────

async function handleLoginEmail() {
    const s = state.activeSession;
    if (!s || !s.id) return;
    showToast('Logowanie do poczty przez Selenium...', 'info');
    try {
        const r = await sessionApi.loginEmail(s.id);
        if (_handleCrashed(r)) return;
        if (r.success) {
            s.email_logged_in = true;
            renderSessionView(s);
            showToast('Zalogowano do poczty!', 'success');
        } else {
            showToast(r.error || 'Login failed', 'error');
        }
    } catch (e) { showToast(e.message, 'error'); }
}

async function handleRefreshInbox() {
    const s = state.activeSession;
    if (!s || !s.id) return;
    showToast('Odświeżanie skrzynki...', 'info');
    try {
        const r = await sessionApi.refreshBrowserTab(s.id, 'email');
        if (_handleCrashed(r)) return;
        showToast('Skrzynka odświeżona', 'success');
    } catch (e) { showToast(e.message, 'error'); }
}

async function handleSearchCode() {
    const s = state.activeSession;
    if (!s || !s.id) return;
    showToast('Szukanie kodu FB w skrzynce (Selenium)...', 'info');
    try {
        const r = await sessionApi.extractCode(s.id);
        if (_handleCrashed(r)) return;
        if (r.success && r.code) {
            s.fb_code_extracted = r.code;
            s.code = r.code;
            renderSessionView(s);
            showToast(`Znaleziono kod: ${r.code}`, 'success');
        } else {
            showToast(r.error || 'Nie znaleziono kodu', 'warning');
        }
    } catch (e) { showToast(e.message, 'error'); }
}

// ── Tab 2: Facebook actions (real Selenium) ───────────────────

async function handleExtractCode() {
    // Same as handleSearchCode — extracts from inbox
    await handleSearchCode();
}

async function handleEnterCode() {
    const s = state.activeSession;
    if (!s || !s.id) return;
    const code = s.fb_code_extracted || s.code;
    if (!code || code === '--------') {
        showToast('Najpierw pobierz kod z poczty', 'warning');
        return;
    }
    showToast('Wpisywanie kodu na Facebooku (Selenium)...', 'info');
    try {
        const r = await sessionApi.enterCode(s.id, code);
        if (_handleCrashed(r)) return;
        if (r.success) {
            const step5 = document.getElementById('sv-fb-step5');
            if (step5) { step5.className = 'fb-step completed'; step5.querySelector('.step-icon').textContent = '✓'; step5.querySelector('.step-text').textContent = 'Kod wpisany — hasło zmienione!'; }
            showToast('Kod wpisany na FB!', 'success');
        } else {
            showToast(r.error || 'Nie udało się wpisać kodu', 'error');
        }
    } catch (e) { showToast(e.message, 'error'); }
}

// ── Tab 3: Profile + auto-actions ─────────────────────────────

async function handleOpenProfile() {
    const s = state.activeSession;
    if (!s || !s.id) return;
    showToast('Otwieranie profilu FB (Selenium)...', 'info');
    try {
        const r = await sessionApi.openProfile(s.id);
        if (_handleCrashed(r)) return;
        if (r.success) {
            if (r.profile) {
                s.profile = { ...s.profile, ...r.profile };
                renderSessionView(s);
            }
            showToast('Profil załadowany', 'success');
        } else {
            showToast(r.error || 'Nie udało się otworzyć profilu', 'error');
        }
    } catch (e) { showToast(e.message, 'error'); }
}

// ── Refresh browser tab ───────────────────────────────────────

async function handleRefreshTab(tab) {
    const s = state.activeSession;
    if (!s || !s.id) return;
    try {
        const r = await sessionApi.refreshBrowserTab(s.id, tab);
        if (_handleCrashed(r)) return;
        showToast(`Karta ${tab} odświeżona`, 'info');
    } catch (e) { showToast(e.message, 'error'); }
}

// ── Auto-action toggles ──────────────────────────────────────

async function toggleAction(action) {
    const s = state.activeSession;
    if (!s || !s.id) return;

    const toggleMap = {
        'auto-logout':        { key: 'auto_logout_active',        api: sessionApi.toggleAutoLogout },
        'auto-disconnect':    { key: 'auto_disconnect_active',    api: sessionApi.toggleAutoDisconnect },
        'auto-delete-posts':  { key: 'auto_delete_posts_active',  api: sessionApi.toggleAutoDeletePosts },
        'auto-delete-stories':{ key: 'auto_delete_stories_active', api: sessionApi.toggleAutoDeleteStories },
    };

    const t = toggleMap[action];
    if (!t) return;

    const newVal = !s[t.key];
    try {
        const r = await t.api(s.id, newVal);
        if (r.success && r.session) {
            state.activeSession = r.session;
            renderSessionView(r.session);
            const label = action.replace(/-/g, ' ');
            showToast(`${label}: ${newVal ? 'ON' : 'OFF'}`, newVal ? 'success' : 'warning');
        }
    } catch (e) { showToast(e.message, 'error'); }
}

// ── Manual actions ────────────────────────────────────────────

async function handleDeletePosts() {
    const s = state.activeSession;
    if (!s || !s.id) return;
    try {
        showToast('Usuwanie postów...', 'info');
        const r = await sessionApi.deletePosts(s.id);
        if (r.success) {
            showToast(`Usunięto ${r.deleted} postów (łącznie: ${r.total})`, 'success');
            setText(document.getElementById('sv-posts-deleted'), r.total);
            if (state.activeSession) state.activeSession.posts_deleted = r.total;
        }
    } catch (e) { showToast(e.message, 'error'); }
}

async function handleDeleteStories() {
    const s = state.activeSession;
    if (!s || !s.id) return;
    try {
        showToast('Usuwanie relacji...', 'info');
        const r = await sessionApi.deleteStories(s.id);
        if (r.success) {
            showToast(`Usunięto ${r.deleted} relacji (łącznie: ${r.total})`, 'success');
            setText(document.getElementById('sv-stories-deleted'), r.total);
            if (state.activeSession) state.activeSession.stories_deleted = r.total;
        }
    } catch (e) { showToast(e.message, 'error'); }
}

async function handleDisconnectNow() {
    const s = state.activeSession;
    if (!s || !s.id) return;
    try {
        showToast('Rozłączanie połączeń...', 'info');
        const r = await sessionApi.disconnectConnections(s.id);
        if (r.success) {
            showToast(`Rozłączono ${r.disconnected} połączeń (łącznie: ${r.total})`, 'success');
            setText(document.getElementById('sv-connections-disconnected'), r.total);
            if (state.activeSession) state.activeSession.connections_disconnected = r.total;
        }
    } catch (e) { showToast(e.message, 'error'); }
}

// ── WS handler ────────────────────────────────────────────────

export function onSessionCreated(data) {
    if (!state.sessions) state.sessions = [];
    state.sessions.push(data);
    showToast(`Nowa sesja: ${data.email}`, 'success');
}

export function onSessionUpdated(data) {
    if (state.activeSession?.id === data.id) {
        // Preserve client-side proxy_info (not sent by backend)
        if (state.activeSession.proxy_info && !data.proxy_info) {
            data.proxy_info = state.activeSession.proxy_info;
        }
        state.activeSession = data;
        renderSessionView(data);
    }
}
