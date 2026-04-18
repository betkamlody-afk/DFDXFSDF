/** DOM element cache + basic helpers */

export const DOM = {};

const IDS = [
    'auth-screen','dashboard',
    'auth-key','btn-authorize','btn-generate','auth-message','auth-status',
    'btn-stop','btn-logout',
    'stat-success','stat-checkpoint','stat-invalid','stat-errors',
    'proxy-count','proxy-valid-count','proxy-type','proxy-input',
    'btn-load-proxy','btn-validate-proxy','proxy-status-bar','proxy-progress',
    'logs-count','logs-input','btn-load-logs',
    'concurrency','concurrency-value','btn-anti-connect','anti-connect-status',
    'btn-start','logs-list',
    'qs-proxy','qs-proxy-valid','qs-queue','qs-codes',
    'workers-active','workers-list','btn-export',
    'engine-status','ws-status','footer-status',
    'antylogout-label','antylogout-status',
    'modal','modal-email','modal-code','modal-proxy',
    'launch-mode-modal','launch-mode-email','btn-launch-mode-selenium','btn-launch-mode-vnc',
    'vnc-wait-modal','vnc-link','vnc-status-text','btn-open-vnc-link',
    'toast-container',
    'page-title','logout-overlay',
    'proxy-table-body','proxy-list-count','proxy-empty',
    'sessions-list','sessions-count',
    'logs-list-page',
];

export function cacheDOM() {
    for (const id of IDS) {
        const camel = id.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        DOM[camel] = document.getElementById(id);
    }
    DOM.modalClose = document.querySelector('.modal-close');
    DOM.modalOverlay = document.querySelector('.modal-overlay');
    DOM.launchModeOverlay = document.querySelector('#launch-mode-modal .modal-overlay');
    DOM.vncWaitOverlay = document.querySelector('#vnc-wait-modal .modal-overlay');
    DOM.filterBtns = document.querySelectorAll('.filter-btn');
    DOM.proxyTypeBtns = document.querySelectorAll('.proxy-type-btn');
    DOM.navItems = document.querySelectorAll('.nav-item[data-page]');
    DOM.pages = document.querySelectorAll('.page');
}

// ── micro helpers ─────────────────────────────────────────────
export function setText(el, v) { if (el) el.textContent = String(v ?? ''); }
export function click(el, fn) { if (el) el.addEventListener('click', fn); }

export function esc(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

export function updateWSStatus(connected) {
    if (!DOM.wsStatus) return;
    DOM.wsStatus.innerHTML = connected ? '● Połączono' : '○ Rozłączono';
    DOM.wsStatus.className = `ws-status ${connected ? 'connected' : 'disconnected'}`;
}
