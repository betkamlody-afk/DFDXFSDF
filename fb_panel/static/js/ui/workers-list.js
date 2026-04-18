/** Workers list rendering */
import { state } from '../state.js';
import { DOM, setText, esc } from './dom.js';

const OS_ICON = { 'Linux':'🐧', 'Windows 10':'🪟', 'Windows 11':'🪟', 'MacOS':'🍎' };
const STATUS_TXT = { idle:'Gotowy', validating_proxy:'Walidacja proxy…', connecting_proxy:'Łączenie…', processing:'Sprawdzanie…', done:'Zakończony', error:'Błąd' };

export function renderWorkers() {
    if (!DOM.workersList) return;
    setText(DOM.workersActive, state.workers.length);

    if (!state.workers.length) {
        DOM.workersList.innerHTML = '<div class="logs-empty" style="padding:16px"><span style="opacity:0.5">Brak aktywnych workerów</span></div>';
        return;
    }

    DOM.workersList.innerHTML = state.workers.map(w => {
        const icon = OS_ICON[w.os] || '💻';
        const cls = w.status === 'processing' ? 'worker-processing' : w.status === 'validating_proxy' ? 'worker-validating' : 'worker-idle';
        return `<div class="worker-item ${cls}">
            <div class="worker-id">#${w.id}</div>
            <div class="worker-info"><span class="worker-os">${icon} ${esc(w.os||'?')}</span><span class="worker-email">${esc(w.email||'...')}</span></div>
            <div class="worker-status">${esc(STATUS_TXT[w.status]||w.status||'?')}</div>
            <div class="worker-proxy" title="${esc(w.proxy||'')}">${esc(w.proxy ? w.proxy.split(':')[0] : '—')}</div>
        </div>`;
    }).join('');
}
