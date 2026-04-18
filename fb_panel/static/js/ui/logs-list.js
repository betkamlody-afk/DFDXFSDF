/** Logs list rendering + filtering */
import { state } from '../state.js';
import { DOM, esc, setText } from './dom.js';
import * as logsApi from '../api/logs.js';
import { showToast } from './toast.js';
import { confirm } from './confirm.js';

const STATUS_CLASS = { success:'status-success', checkpoint:'status-warning', invalid:'status-error', '2fa_required':'status-error', processing:'status-processing', error:'status-error', pending:'status-pending', code_sent:'status-success' };
const STATUS_TEXT  = { success:'Zalogowano', checkpoint:'Checkpoint', invalid:'Nieprawidłowe', '2fa_required':'2FA wymagane', processing:'Sprawdzanie...', error:'Błąd', pending:'W kolejce', code_sent:'Kod wysłany' };

const FB_ICON = `<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg>`;
const SPINNER_ICON = `<svg class="log-spinner" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M12 2a10 10 0 0 1 10 10" /></svg>`;
const RETRY_ICON = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`;

let _onSuccessClick = null;

/** Register callback for when a success log is clicked (opens session view). */
export function setOnSuccessClick(fn) { _onSuccessClick = fn; }

export function renderLogsList() {
    const filtered = _getFiltered();

    // ── Render into home page results (#logs-list) ──
    _renderInto(DOM.logsList, filtered, true);

    // ── Render into logs page list (#logs-list-page) ──
    _renderInto(DOM.logsListPage, state.logs, false);

    // ── Update count badge on logs page ──
    setText(DOM.logsCount, state.logs.length);
}

function _getFiltered() {
    if (state.currentFilter === 'all') return state.logs;
    return state.logs.filter(l => {
        if (state.currentFilter === 'success')    return l.status === 'success';
        if (state.currentFilter === 'processing') return l.status === 'processing' || l.status === 'pending';
        if (state.currentFilter === 'error')      return ['invalid','checkpoint','2fa_required','error'].includes(l.status);
        return true;
    });
}

function _renderInto(container, list, isResults) {
    if (!container) return;
    if (!list.length) {
        const msg = isResults
            ? '<div class="logs-empty"><span class="empty-icon">📭</span><p>Brak wyników</p><p class="empty-hint">Wklej logi i kliknij START</p></div>'
            : '<div class="logs-empty"><span class="empty-icon">📭</span><p>Brak logów</p><p class="empty-hint">Wklej logi i kliknij Załaduj</p></div>';
        container.innerHTML = msg;
        return;
    }
    container.innerHTML = list.map(log => renderItem(log, !isResults)).join('');

    // attach click handlers
    container.querySelectorAll('.log-item').forEach(el => {
        // Main click → detail or session
        el.addEventListener('click', (e) => {
            if (e.target.closest('.log-delete-btn') || e.target.closest('.log-retry-btn')) return;
            const log = state.logs.find(l => l.id === el.dataset.id);
            if (!log) return;
            if (log.status === 'success' && _onSuccessClick) {
                _onSuccessClick(log);
            } else {
                openDetailModal(log);
            }
        });
    });

    // attach delete buttons
    container.querySelectorAll('.log-delete-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const id = btn.dataset.id;
            const log = state.logs.find(l => l.id === id);
            const label = log?.email || id;
            const ok = await confirm('Usuń log', `Czy na pewno chcesz usunąć log "${label}"?`);
            if (!ok) return;
            try {
                const r = await logsApi.deleteLog(id);
                if (r.success) {
                    state.logs = state.logs.filter(l => l.id !== id);
                    renderLogsList();
                    showToast('Log usunięty', 'info');
                }
            } catch (err) { showToast(err.message, 'error'); }
        });
    });

    // attach retry buttons
    container.querySelectorAll('.log-retry-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const id = btn.dataset.id;
            btn.classList.add('spinning');
            try {
                const r = await logsApi.retryLog(id);
                if (r.success) {
                    const idx = state.logs.findIndex(l => l.id === id);
                    if (idx !== -1) state.logs[idx] = r.log;
                    renderLogsList();
                    showToast('Ponowiono sprawdzanie', 'info');
                }
            } catch (err) { showToast(err.message, 'error'); }
            btn.classList.remove('spinning');
        });
    });
}

function renderItem(log, showDelete) {
    const cls  = STATUS_CLASS[log.status] || 'status-pending';
    const isProcessing = log.status === 'processing';
    // Use error detail for invalid/error/checkpoint if available, otherwise generic text
    const statusDetail = (log.status === 'invalid' || log.status === 'error' || log.status === 'checkpoint') && log.error
        ? esc(log.error)
        : (STATUS_TEXT[log.status] || log.status || '?');
    // Show code badge (FB-8D, NO-FB etc.)
    const codeBadge = log.code
        ? `<span class="log-code-badge">${esc(log.code)}</span>`
        : '';
    const deleteBtn = showDelete
        ? `<button class="log-delete-btn" data-id="${log.id}" title="Usuń log">✕</button>`
        : '';
    const isFinished = ['success','invalid','checkpoint','error','2fa_required'].includes(log.status);
    const retryBtn = isFinished
        ? `<button class="log-retry-btn" data-id="${log.id}" title="Ponów sprawdzanie">${RETRY_ICON}</button>`
        : '';
    const rightIcon = isProcessing ? SPINNER_ICON : (log.status === 'pending' ? '<div class="log-arrow">→</div>' : '');
    return `<div class="log-item ${cls}" data-id="${log.id}">
        <div class="log-icon">${FB_ICON}</div>
        <div class="log-info"><div class="log-email">${esc(log.email)}${codeBadge}</div><div class="log-status">${statusDetail}${log.worker_os ? ' · ' + esc(log.worker_os) : ''}</div></div>
        ${retryBtn}
        ${deleteBtn}
        ${rightIcon}
    </div>`;
}

function openDetailModal(log) {
    if (!DOM.modal) return;
    const set = (el, v) => { if (el) el.textContent = v || '—'; };
    set(DOM.modalEmail, log.email);
    set(DOM.modalCode,  log.code);
    set(DOM.modalProxy, log.proxy);
    DOM.modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

export function closeModal() {
    DOM.modal?.classList.add('hidden');
    document.body.style.overflow = '';
}
