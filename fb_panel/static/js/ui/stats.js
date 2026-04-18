/** Stats panel + engine status UI updates */
import { state } from '../state.js';
import { DOM, setText } from './dom.js';

export function updateStats(data) {
    if (data.success !== undefined && typeof data.success === 'number') { state.stats.success = data.success; setText(DOM.statSuccess, data.success); }
    if (data.checkpoint !== undefined)   { state.stats.checkpoint = data.checkpoint; setText(DOM.statCheckpoint, data.checkpoint); }
    if (data.invalid !== undefined)      { const v = (data.invalid||0) + (data['2fa_required']||0); state.stats.invalid = v; setText(DOM.statInvalid, v); }
    if (data.error !== undefined)        { state.stats.errors = data.error; setText(DOM.statErrors, data.error); }
    if (data.pending !== undefined)      setText(DOM.qsQueue, data.pending);
    if (data.codes !== undefined)        { state.stats.codesFound = data.codes; setText(DOM.qsCodes, data.codes); }
}

export function resetStats() {
    state.stats = { success: 0, checkpoint: 0, invalid: 0, errors: 0, codesFound: 0 };
    [DOM.statSuccess, DOM.statCheckpoint, DOM.statInvalid, DOM.statErrors, DOM.qsQueue, DOM.qsCodes]
        .forEach(el => setText(el, '0'));
}

export function updateEngineStatusUI() {
    if (DOM.engineStatus) {
        DOM.engineStatus.textContent = state.isRunning ? '▶ Uruchomiony' : '⏸ Zatrzymany';
        DOM.engineStatus.className = 'engine-badge ' + (state.isRunning ? 'running' : '');
    }
    if (DOM.btnStart) {
        DOM.btnStart.classList.toggle('running', state.isRunning);
        const svg = DOM.btnStart.querySelector('svg');
        const textNode = DOM.btnStart.childNodes[DOM.btnStart.childNodes.length - 1];
        if (state.isRunning && textNode) textNode.textContent = ' Zatrzymaj sprawdzanie';
        else if (textNode) textNode.textContent = ' Rozpocznij sprawdzanie';
    }
    if (DOM.btnStop) DOM.btnStop.disabled = !state.isRunning;
}
