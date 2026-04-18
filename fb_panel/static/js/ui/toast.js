/** Toast notification system */
import { CONFIG } from '../config.js';
import { DOM, esc } from './dom.js';

const ICONS = { success: '✓', error: '✗', warning: '⚠', info: 'ℹ' };

export function showToast(message, type = 'info') {
    if (!DOM.toastContainer) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<span class="toast-icon">${ICONS[type] || 'ℹ'}</span><span class="toast-message">${esc(message)}</span>`;
    DOM.toastContainer.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('show'));
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), CONFIG.ANIM_MS);
    }, CONFIG.TOAST_DURATION);
}
