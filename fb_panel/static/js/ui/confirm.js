/** Reusable confirm dialog */

let _resolve = null;

const els = {};

export function initConfirm() {
    els.dialog  = document.getElementById('confirm-dialog');
    els.title   = document.getElementById('confirm-title');
    els.message = document.getElementById('confirm-message');
    els.ok      = document.getElementById('confirm-ok');
    els.cancel  = document.getElementById('confirm-cancel');
    els.close   = document.getElementById('confirm-close');
    els.overlay = document.getElementById('confirm-overlay');

    els.cancel?.addEventListener('click', () => close(false));
    els.close?.addEventListener('click', () => close(false));
    els.overlay?.addEventListener('click', () => close(false));
    els.ok?.addEventListener('click', () => close(true));
}

function close(result) {
    els.dialog.classList.add('hidden');
    if (_resolve) { _resolve(result); _resolve = null; }
}

/**
 * Show confirm dialog and return a Promise<boolean>.
 * @param {string} title   - Header text
 * @param {string} message - Body text
 * @param {string} [okText='Usuń'] - Confirm button label
 */
export function confirm(title, message, okText = 'Usuń') {
    els.title.textContent = title;
    els.message.textContent = message;
    els.ok.textContent = okText;
    els.dialog.classList.remove('hidden');
    return new Promise(resolve => { _resolve = resolve; });
}
