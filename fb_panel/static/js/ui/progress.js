/** Proxy validation progress bar */
import { DOM } from './dom.js';

export function showProxyProgress(pct) {
    if (DOM.proxyStatusBar) DOM.proxyStatusBar.style.display = 'block';
    if (DOM.proxyProgress)  DOM.proxyProgress.style.width = Math.min(100, pct) + '%';
}

export function hideProxyProgress() {
    if (DOM.proxyStatusBar) DOM.proxyStatusBar.style.display = 'none';
    if (DOM.proxyProgress)  DOM.proxyProgress.style.width = '0%';
}
