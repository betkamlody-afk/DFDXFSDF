/** Filter handlers */
import { state } from '../state.js';
import { DOM } from '../ui/dom.js';
import { renderLogsList } from '../ui/logs-list.js';

export function bindFilterEvents() {
    DOM.filterBtns?.forEach(btn => btn.addEventListener('click', () => {
        state.currentFilter = btn.dataset.filter;
        DOM.filterBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderLogsList();
    }));
}
