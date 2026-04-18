/** Logs handlers — load, clear */
import { state } from '../state.js';
import { DOM, setText } from '../ui/dom.js';
import { showToast } from '../ui/toast.js';
import { renderLogsList } from '../ui/logs-list.js';
import * as logsApi from '../api/logs.js';
import { confirm } from '../ui/confirm.js';

export function bindLogsEvents() {
    DOM.btnLoadLogs?.addEventListener('click', handleLoad);
    document.getElementById('btn-clear-logs')?.addEventListener('click', handleClear);
}

async function handleLoad() {
    const input = (DOM.logsInput?.value||'').trim();
    if (!input) { showToast('Wprowadź logi!','error'); return; }
    const lines = input.split('\n').map(l=>l.trim()).filter(Boolean);
    try {
        DOM.btnLoadLogs.disabled = true;
        const r = await logsApi.loadLogs(lines);
        if (r.success) {
            setText(DOM.logsCount, r.loaded);
            setText(DOM.qsQueue, r.loaded);
            showToast(`Załadowano ${r.loaded} logów`,'success');
            const all = await logsApi.getAll().catch(()=>null);
            if (all?.success && all.logs) { state.logs = all.logs; renderLogsList(); }
            if (DOM.logsInput) DOM.logsInput.value = '';
        }
    } catch(e) { showToast(e.message,'error'); }
    finally { DOM.btnLoadLogs.disabled = false; }
}

async function handleClear() {
    if (!state.logs.length) { showToast('Lista logów jest pusta','info'); return; }
    const ok = await confirm('Wyczyść logi', `Czy na pewno chcesz usunąć wszystkie logi (${state.logs.length})?`, 'Wyczyść');
    if (!ok) return;
    try {
        const r = await logsApi.clearLogs();
        if (r.success) {
            state.logs = [];
            renderLogsList();
            setText(DOM.logsCount, 0);
            setText(DOM.qsQueue, 0);
            showToast('Wszystkie logi wyczyszczone','info');
        }
    } catch(e) { showToast(e.message,'error'); }
}

// WS handler
export function onLogUpdated(data) {
    const idx = state.logs.findIndex(l => l.id === data.id);
    const existing = idx >= 0 ? state.logs[idx] : null;
    if (idx >= 0) state.logs[idx] = { ...state.logs[idx], ...data };
    else state.logs.push(data);
    // Only increment codesFound if this is a NEW code (not a repeat update)
    if (data.code && (!existing || !existing.code)) {
        state.stats.codesFound++;
        setText(DOM.qsCodes, state.stats.codesFound);
    }
    renderLogsList();
}
