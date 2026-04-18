/** Export handler */
import { state } from '../state.js';
import { DOM } from '../ui/dom.js';
import { showToast } from '../ui/toast.js';

export function bindExportEvents() {
    DOM.btnExport?.addEventListener('click', handleExport);
}

function handleExport() {
    const ok = state.logs.filter(l => l.status === 'success');
    if (!ok.length) { showToast('Brak wyników do eksportu','error'); return; }
    const content = ok.map(l => l.code ? `${l.email}|${l.code}` : l.email).join('\n');
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `fb_panel_export_${Date.now()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    showToast(`Wyeksportowano ${ok.length} wyników`,'success');
}
