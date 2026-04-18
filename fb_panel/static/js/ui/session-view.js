/** Session View — renders 3-tab session panel with live browser screenshots */
import { DOM, setText, esc } from './dom.js';
import { state } from '../state.js';
import { screenshotUrl } from '../api/session.js';

const EMAIL_ICONS = {
    'wp.pl':      '📧', 'o2.pl':      '📧', 'interia.pl': '📧',
    'onet.pl':    '📧', 'gmail.com':  '✉️', 'default':    '📧',
};

const PROVIDER_NAMES = {
    'wp.pl':      'WP Poczta',  'o2.pl':      'O2 Poczta',
    'interia.pl': 'Interia',    'onet.pl':    'Onet Poczta',
    'gmail.com':  'Gmail',
};

const DEFAULT_PLACEHOLDERS = {
    email: 'Kliknij „🔑 Zaloguj do poczty" aby rozpocząć',
    facebook: 'Przeglądarka Facebook uruchamiana...',
    panel: 'Kliknij „📘 Otwórz profil FB" aby załadować',
};

/** All action button IDs that require a live browser session */
const ACTION_BUTTON_IDS = [
    'btn-sv-login-email', 'btn-sv-refresh-inbox', 'btn-sv-search-code',
    'btn-sv-refresh-email-tab', 'btn-sv-extract-code', 'btn-sv-enter-code',
    'btn-sv-refresh-fb-tab', 'btn-sv-open-profile', 'btn-sv-refresh-panel-tab',
    'btn-sv-auto-logout', 'btn-sv-auto-disconnect',
    'btn-sv-auto-delete-posts', 'btn-sv-auto-delete-stories',
    'btn-sv-delete-posts', 'btn-sv-delete-stories', 'btn-sv-disconnect-now',
    'btn-sv-change-proxy',
];

let _screenshotInterval = null;

/**
 * Enable or disable all session action buttons.
 * Called when switching between preview/active/loading/crashed states.
 */
export function setActionButtonsEnabled(enabled) {
    for (const id of ACTION_BUTTON_IDS) {
        const btn = document.getElementById(id);
        if (btn) {
            btn.disabled = !enabled;
            btn.style.opacity = enabled ? '' : '0.4';
            btn.style.pointerEvents = enabled ? '' : 'none';
        }
    }
}

export function renderSessionView(session) {
    if (!session) return;
    state.activeSession = session;

    // Topbar
    setText(document.getElementById('sv-email'), session.email);

    // Proxy display — show IP/country if available (DolphinAnty style)
    const proxyEl = document.getElementById('sv-proxy');
    if (proxyEl) {
        const pi = session.proxy_info;
        if (pi && pi.ip) {
            const flag = pi.country_code ? _countryFlag(pi.country_code) : '';
            proxyEl.innerHTML = `${flag} ${esc(pi.ip)} <span style="opacity:.6">${esc(pi.city || '')} ${esc(pi.country || '')} · ${pi.latency_ms || '?'}ms</span>`;
        } else {
            setText(proxyEl, session.proxy || 'Bezpośrednie');
        }
    }
    const statusEl = document.getElementById('sv-status');
    if (statusEl) {
        if (session.status === 'crashed') {
            statusEl.textContent = '✖ Przeglądarka padła';
            statusEl.style.color = 'var(--danger, #ef4444)';
        } else if (session.status === 'awaiting_vnc') {
            statusEl.textContent = '⏳ Oczekiwanie na VNC';
            statusEl.style.color = 'var(--warning, #f59e0b)';
        } else if (session.status === 'active') {
            statusEl.textContent = session.mode === 'vnc' ? '● VNC połączone' : '● Aktywna';
            statusEl.style.color = 'var(--success)';
        } else if (session.status === 'loading') {
            statusEl.textContent = '⏳ Uruchamianie...';
            statusEl.style.color = 'var(--warning, #f59e0b)';
        } else if (session.status === 'preview') {
            statusEl.textContent = '◌ Podgląd (przeglądarka nieaktywna)';
            statusEl.style.color = 'var(--text-muted)';
        } else {
            statusEl.textContent = '○ Zamknięta';
            statusEl.style.color = 'var(--text-muted)';
        }
    }

    // Enable/disable action buttons based on session state
    const isLive = session.mode !== 'vnc' && session.status === 'active' && !!session.id;
    setActionButtonsEnabled(isLive);

    const launchBtn = document.getElementById('btn-sv-launch-browser');
    if (launchBtn) {
        launchBtn.textContent = session.mode === 'vnc' ? '🖥 Otwórz VNC' : '🚀 Odpal przeglądarkę';
    }

    const vncNote = session.mode === 'vnc'
        ? (session.status === 'active'
            ? 'VNC połączone. Sterowanie odbywa się przez zewnętrzny klient.'
            : 'Uruchom VNC i użyj linku aktywacyjnego, aby połączyć sesję.')
        : null;
    for (const tab of ['email', 'facebook', 'panel']) {
        const placeholder = document.getElementById(`sv-placeholder-${tab}`);
        if (!placeholder) continue;
        if (vncNote) {
            placeholder.innerHTML = `<span class="placeholder-icon">🖥</span><span>${esc(vncNote)}</span>`;
            placeholder.classList.remove('hidden');
        } else {
            const icons = { email: '📧', facebook: '📘', panel: '⚙️' };
            placeholder.innerHTML = `<span class="placeholder-icon">${icons[tab]}</span><span>${DEFAULT_PLACEHOLDERS[tab]}</span>`;
        }
    }

    // Tab statuses
    session.tabs?.forEach(t => {
        const el = document.getElementById(`sv-tab-${t.name === 'facebook' ? 'fb' : t.name}-status`);
        if (el) el.style.color = t.status === 'ready' ? 'var(--success)' : 'var(--text-muted)';
    });

    // ── Tab 1: Email ──
    const provider = session.email_provider || 'default';
    const icon = EMAIL_ICONS[provider] || EMAIL_ICONS.default;
    setText(document.getElementById('sv-email-provider-icon'), icon);
    setText(document.getElementById('sv-email-addr'), session.email);
    setText(document.getElementById('sv-email-provider'), PROVIDER_NAMES[provider] || provider.toUpperCase());
    const loginStatus = document.getElementById('sv-email-login-status');
    if (loginStatus) {
        loginStatus.textContent = session.email_logged_in ? '✓ Zalogowano' : '✗ Niezalogowano';
        loginStatus.className = 'es-value ' + (session.email_logged_in ? 'status-ok' : '');
    }
    setText(document.getElementById('sv-email-inbox'), session.email_inbox_count || 0);
    setText(document.getElementById('sv-email-code'), session.fb_code_extracted || '—');

    // ── Tab 2: Facebook ──
    const code = session.fb_code_extracted || session.code || '--------';
    setText(document.getElementById('sv-fb-code'), code);

    // Update flow steps based on state
    if (code && code !== '--------') {
        const step4 = document.getElementById('sv-fb-step4');
        const step5 = document.getElementById('sv-fb-step5');
        if (step4) { step4.className = 'fb-step completed'; step4.querySelector('.step-icon').textContent = '✓'; step4.querySelector('.step-text').textContent = 'Kod pobrany z poczty'; }
        if (step5) { step5.className = 'fb-step active'; step5.querySelector('.step-icon').textContent = '◌'; }
    }

    // ── Tab 3: Panel ──
    const p = session.profile || {};
    setText(document.getElementById('sv-profile-name'), p.full_name || '—');
    setText(document.getElementById('sv-profile-url'), p.profile_url || 'facebook.com/...');
    setText(document.getElementById('sv-friends'), p.friends_count || 0);
    setText(document.getElementById('sv-gender'), p.gender || '—');
    setText(document.getElementById('sv-location'), p.location || '—');
    setText(document.getElementById('sv-workplace'), p.workplace || '—');

    // Counters
    setText(document.getElementById('sv-posts-deleted'), session.posts_deleted || 0);
    setText(document.getElementById('sv-stories-deleted'), session.stories_deleted || 0);
    setText(document.getElementById('sv-connections-disconnected'), session.connections_disconnected || 0);

    // Toggle states
    updateToggle('btn-sv-auto-logout', 'sv-auto-logout-status', session.auto_logout_active);
    updateToggle('btn-sv-auto-disconnect', 'sv-auto-disconnect-status', session.auto_disconnect_active);
    updateToggle('btn-sv-auto-delete-posts', 'sv-auto-delete-posts-status', session.auto_delete_posts_active);
    updateToggle('btn-sv-auto-delete-stories', 'sv-auto-delete-stories-status', session.auto_delete_stories_active);
}

function updateToggle(btnId, labelId, active) {
    const btn = document.getElementById(btnId);
    const label = document.getElementById(labelId);
    if (btn) btn.classList.toggle('active', !!active);
    if (label) label.textContent = active ? 'ON' : 'OFF';
}

export function switchTab(tabName) {
    // Toggle tab buttons
    document.querySelectorAll('.session-tab').forEach(t => {
        t.classList.toggle('active', t.dataset.tab === tabName);
    });
    // Toggle tab contents
    document.querySelectorAll('.session-tab-content').forEach(c => {
        c.classList.toggle('active', c.id === `tab-${tabName}`);
    });
    // Immediately refresh visible tab screenshot
    refreshScreenshot(tabName);
}

// ── Screenshot Polling ────────────────────────────────────────

export function startScreenshotPolling() {
    stopScreenshotPolling();
    if (state.activeSession?.mode === 'vnc') return;
    // Initial load for all tabs
    ['email', 'facebook', 'panel'].forEach(refreshScreenshot);
    // Poll active tab every 3 seconds
    _screenshotInterval = setInterval(() => {
        const activeTab = document.querySelector('.session-tab.active');
        if (activeTab && state.activeSession) {
            refreshScreenshot(activeTab.dataset.tab);
        }
    }, 3000);
}

export function stopScreenshotPolling() {
    if (_screenshotInterval) {
        clearInterval(_screenshotInterval);
        _screenshotInterval = null;
    }
}

function refreshScreenshot(tab) {
    const s = state.activeSession;
    if (!s || !s.id || s.mode === 'vnc') return;

    const img = document.getElementById(`sv-screenshot-${tab}`);
    const placeholder = document.getElementById(`sv-placeholder-${tab}`);
    if (!img) return;

    const url = screenshotUrl(s.id, tab);

    // Use fetch to detect 410 (session crashed/closed)
    fetch(url).then(resp => {
        if (resp.status === 410) {
            // Session crashed — stop polling, show message
            stopScreenshotPolling();
            if (s) s.status = 'crashed';
            const statusEl = document.getElementById('sv-status');
            if (statusEl) {
                statusEl.textContent = '✖ Przeglądarka padła';
                statusEl.style.color = 'var(--danger, #ef4444)';
            }
            if (placeholder) {
                placeholder.classList.remove('hidden');
                placeholder.textContent = 'Przeglądarka nie żyje — zamknij sesję i otwórz ponownie';
            }
            return;
        }
        if (!resp.ok) return;
        resp.blob().then(blob => {
            const objUrl = URL.createObjectURL(blob);
            // Revoke old blob URL to prevent memory leak
            const oldSrc = img.src;
            img.src = objUrl;
            if (oldSrc && oldSrc.startsWith('blob:')) URL.revokeObjectURL(oldSrc);
            img.classList.add('loaded');
            if (placeholder) placeholder.classList.add('hidden');
        });
    }).catch(() => {});
}

/** Convert country code (e.g. "PL") to emoji flag */
function _countryFlag(cc) {
    if (!cc || cc.length !== 2) return '';
    const offset = 127397;
    return String.fromCodePoint(...[...cc.toUpperCase()].map(c => c.charCodeAt(0) + offset));
}
