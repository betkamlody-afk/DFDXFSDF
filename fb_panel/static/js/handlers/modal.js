/** Modal handlers */
import { DOM, click } from '../ui/dom.js';
import { closeModal } from '../ui/logs-list.js';

export function bindModalEvents() {
    click(DOM.modalClose, closeModal);
    click(DOM.modalOverlay, closeModal);
}
