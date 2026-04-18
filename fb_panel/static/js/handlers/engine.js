/** Engine start/stop handlers */
import { state } from '../state.js';
import { DOM } from '../ui/dom.js';
import { showToast } from '../ui/toast.js';
import { updateEngineStatusUI } from '../ui/stats.js';
import * as engineApi from '../api/engine.js';

export function bindEngineEvents() {
    DOM.btnStart?.addEventListener('click', handleStart);
    DOM.btnStop?.addEventListener('click', handleStop);
}

async function handleStart() {
    // Validate: logs and proxy must be loaded first
    if (!state.logs || !state.logs.length) {
        showToast('Najpierw załaduj logi! (zakładka Logi → Załaduj)', 'error');
        return;
    }
    const pendingCount = state.logs.filter(l => l.status === 'pending').length;
    if (!pendingCount) {
        showToast('Brak logów do sprawdzenia (wszystkie już przetworzone)', 'error');
        return;
    }
    if (!state.proxyTotal || state.proxyTotal === 0) {
        showToast('Najpierw załaduj proxy! (zakładka Proxy → Załaduj)', 'error');
        return;
    }
    if (state.isRunning) {
        // Already running → stop
        return handleStop();
    }
    try {
        DOM.btnStart.disabled = true;
        const r = await engineApi.startEngine(state.settings.concurrency);
        if (r.success) { state.isRunning = true; updateEngineStatusUI(); showToast(`Silnik uruchomiony! (${pendingCount} logów, ${state.proxyTotal} proxy)`,'success'); }
        else throw new Error(r.error);
    } catch(e) { showToast(e.message,'error'); }
    finally { DOM.btnStart.disabled = false; }
}

async function handleStop() {
    try {
        DOM.btnStop.disabled = true;
        const r = await engineApi.stopEngine();
        if (r.success) { state.isRunning = false; updateEngineStatusUI(); showToast('Silnik zatrzymany','info'); }
    } catch(e) { showToast(e.message,'error'); }
    finally { DOM.btnStop.disabled = false; }
}

// WS handlers
export function onEngineStarted()  { state.isRunning = true;  updateEngineStatusUI(); showToast('Silnik uruchomiony','success'); }
export function onEngineStopped()  { state.isRunning = false; updateEngineStatusUI(); showToast('Silnik zatrzymany','info'); }
export function onEngineStatus(d)  { state.isRunning = !!d.running; updateEngineStatusUI(); }
