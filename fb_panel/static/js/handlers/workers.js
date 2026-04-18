/** Workers + anti-connect handlers */
import { state } from '../state.js';
import { DOM, setText } from '../ui/dom.js';
import { showToast } from '../ui/toast.js';
import { renderWorkers } from '../ui/workers-list.js';
import * as workersApi from '../api/workers.js';

export function bindWorkersEvents() {
    DOM.btnAntiConnect?.addEventListener('click', handleToggleAntiConnect);
}

async function handleToggleAntiConnect() {
    const newVal = !state.settings.antiConnect;
    try {
        const r = await workersApi.toggleAntiConnect(newVal);
        if (r.success) {
            state.settings.antiConnect = newVal;
            updateAntiConnectUI();
            showToast('Anti-Connect: ' + (newVal ? 'ON' : 'OFF'), newVal ? 'success' : 'warning');
        }
    } catch(e) { showToast(e.message,'error'); }
}

export function updateAntiConnectUI() {
    if (DOM.btnAntiConnect) DOM.btnAntiConnect.classList.toggle('active', state.settings.antiConnect);
    setText(DOM.antiConnectStatus, state.settings.antiConnect ? 'ON' : 'OFF');
}

export async function refreshWorkers() {
    if (!state.isAuthorized) return;
    try {
        const r = await workersApi.getWorkers();
        if (r.success) { state.workers = r.workers || []; renderWorkers(); }
    } catch(_){}
}

// WS handler
export function onWorkerUpdate(data) {
    const idx = state.workers.findIndex(w => w.id === data.id);
    if (idx >= 0) state.workers[idx] = { ...state.workers[idx], ...data };
    else state.workers.push(data);
    state.workers = state.workers.filter(w => w.status !== 'done');
    renderWorkers();
}
