/** Settings — concurrency slider */
import { state } from '../state.js';
import { DOM, setText } from '../ui/dom.js';

export function bindSettingsEvents() {
    DOM.concurrency?.addEventListener('input', () => {
        state.settings.concurrency = parseInt(DOM.concurrency.value);
        setText(DOM.concurrencyValue, state.settings.concurrency);
    });
}

export function initSettingsUI() {
    if (DOM.concurrency) { DOM.concurrency.value = state.settings.concurrency; setText(DOM.concurrencyValue, state.settings.concurrency); }
}
