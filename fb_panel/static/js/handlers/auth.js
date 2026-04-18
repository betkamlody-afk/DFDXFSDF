/** Auth handlers — authorize, generate, logout, session restore */
import { CONFIG } from '../config.js';
import { state } from '../state.js';
import { DOM, setText } from '../ui/dom.js';
import { showToast } from '../ui/toast.js';
import * as authApi from '../api/auth.js';

export function bindAuthEvents(showDashboard) {
    DOM.btnAuthorize?.addEventListener('click', () => handleAuthorize(showDashboard));
    DOM.btnGenerate?.addEventListener('click', handleGenerate);
    DOM.authKey?.addEventListener('keypress', e => { if (e.key === 'Enter') handleAuthorize(showDashboard); });
    DOM.authKey?.addEventListener('input', formatKeyInput);
    DOM.btnLogout?.addEventListener('click', handleLogout);
}

export async function checkExistingSession(showDashboard) {
    const saved = sessionStorage.getItem(CONFIG.SESSION_KEY);
    if (!saved) return;
    state.sessionId = saved;
    try {
        const r = await authApi.checkSession();
        if (r.authorized || r.valid) { state.isAuthorized = true; showDashboard(); showToast('Sesja przywrócona','success'); return; }
    } catch(_) {}
    sessionStorage.removeItem(CONFIG.SESSION_KEY);
    state.sessionId = null;
}

async function handleGenerate() {
    try {
        DOM.btnGenerate.disabled = true;
        setMsg('Generowanie klucza…','info');
        const r = await authApi.generateKey();
        if (r.success && r.key) { DOM.authKey.value = r.key; setMsg('Klucz wygenerowany! Kliknij AUTORYZUJ','success'); showToast('Klucz wygenerowany!','success'); }
    } catch(e) { setMsg(e.message,'error'); showToast(e.message,'error'); }
    finally { DOM.btnGenerate.disabled = false; }
}

async function handleAuthorize(showDashboard) {
    const key = (DOM.authKey?.value||'').trim();
    if (!key) { setMsg('Wprowadź klucz!','error'); return; }
    try {
        DOM.btnAuthorize.disabled = true;
        setMsg('Autoryzacja…','info');
        const r = await authApi.authorize(key);
        if (r.success && r.session_id) {
            state.sessionId = r.session_id;
            state.isAuthorized = true;
            sessionStorage.setItem(CONFIG.SESSION_KEY, state.sessionId);
            setMsg('Autoryzacja pomyślna!','success');
            showToast('Zalogowano!','success');
            setTimeout(showDashboard, 400);
        } else throw new Error(r.message || 'Zły klucz');
    } catch(e) { setMsg(e.message,'error'); showToast(e.message,'error'); }
    finally { DOM.btnAuthorize.disabled = false; }
}

async function handleLogout() {
    try { await authApi.logout(); } catch(_){}
    state.sessionId = null;
    state.isAuthorized = false;
    state.logs = [];
    state.workers = [];
    sessionStorage.removeItem(CONFIG.SESSION_KEY);
    // Will be called from main to show auth screen
    window.dispatchEvent(new Event('fb:logout'));
    showToast('Wylogowano','info');
}

function formatKeyInput(e) {
    let v = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g,'');
    const parts = [];
    for (let i = 0; i < v.length && parts.length < 4; i += 4) parts.push(v.substring(i, i+4));
    e.target.value = parts.join('-');
}

function setMsg(text, type) {
    if (DOM.authMessage) { DOM.authMessage.textContent = text; DOM.authMessage.className = `auth-message ${type}`; DOM.authMessage.classList.remove('hidden'); }
    if (DOM.authStatus) DOM.authStatus.textContent = text;
}
