/** Proxy handlers — load, validate, type selector */
import { state } from '../state.js';
import { DOM, setText } from '../ui/dom.js';
import { showToast } from '../ui/toast.js';
import { showProxyProgress, hideProxyProgress } from '../ui/progress.js';
import * as proxyApi from '../api/proxy.js';
import { confirm } from '../ui/confirm.js';

let _loadRefreshTimer = null;

export function bindProxyEvents() {
    DOM.btnLoadProxy?.addEventListener('click', handleLoad);
    DOM.btnValidateProxy?.addEventListener('click', handleValidate);
    document.getElementById('btn-clear-proxy')?.addEventListener('click', handleClearProxy);
    DOM.proxyTypeBtns?.forEach(btn => btn.addEventListener('click', () => {
        state.proxyType = btn.dataset.type;
        DOM.proxyTypeBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        if (DOM.proxyType) DOM.proxyType.value = state.proxyType;
    }));
}

async function handleLoad() {
    const input = (DOM.proxyInput?.value||'').trim();
    if (!input) { showToast('Wprowadź proxy!','error'); return; }
    const lines = input.split('\n').map(l=>l.trim()).filter(Boolean);
    try {
        DOM.btnLoadProxy.disabled = true;
        const r = await proxyApi.loadProxy(lines, state.proxyType);
        if (r.success) {
            // Update total from full list (not just loaded count)
            const total = r.proxies ? r.proxies.length : (state.proxyTotal + r.loaded);
            state.proxyTotal = total;
            setText(DOM.proxyCount, total);
            setText(DOM.qsProxy, total);

            if (r.loaded === 0) {
                showToast('Wszystkie proxy już są na liście (duplikaty)','warning');
            } else {
                showToast(`Dodano ${r.loaded} proxy [${state.proxyType}] (razem: ${total})`,'success');
            }

            // Render proxies immediately from the response
            if (r.proxies && window._renderProxyTable) {
                window._renderProxyTable(r.proxies);
                const countEl = document.getElementById('proxy-list-count');
                if (countEl) countEl.textContent = r.proxies.length;
            }

            // Clear textarea after successful load
            if (DOM.proxyInput) DOM.proxyInput.value = '';

            // Cancel previous timer, schedule refresh for geo data
            clearTimeout(_loadRefreshTimer);
            clearTimeout(window._geoTimer);
            _loadRefreshTimer = setTimeout(async () => {
                try {
                    const list = await proxyApi.listProxies();
                    if (list.success && list.proxies && window._renderProxyTable) {
                        window._renderProxyTable(list.proxies);
                    }
                } catch(_){}
            }, 3000);
        }
    } catch(e) { showToast(e.message,'error'); }
    finally { DOM.btnLoadProxy.disabled = false; }
}

async function handleValidate() {
    if (state.isValidating) return;
    if (!state.proxyTotal) { showToast('Najpierw załaduj proxy!','error'); return; }
    try {
        state.isValidating = true;
        DOM.btnValidateProxy.disabled = true;
        showProxyProgress(0);
        showToast('Walidacja proxy…','info');
        await proxyApi.validateProxy();
    } catch(e) { showToast(e.message,'error'); hideProxyProgress(); state.isValidating = false; DOM.btnValidateProxy.disabled = false; }
}

// ── WS event handlers (called from main) ─────────────────────
export function onValidationProgress(data) {
    showProxyProgress(data.percent || 0);
    if (data.validated !== undefined) {
        state.proxyValidated = data.validated;
        setText(DOM.proxyValidCount, '✓ ' + data.validated);
        setText(DOM.qsProxyValid, data.validated);
    }
}

export function onValidationDone(data) {
    state.isValidating = false;
    DOM.btnValidateProxy.disabled = false;
    state.proxyValidated = data.validated || 0;
    setText(DOM.proxyValidCount, '✓ ' + state.proxyValidated);
    setText(DOM.qsProxyValid, state.proxyValidated);
    setText(DOM.qsProxy, data.available || state.proxyValidated);
    showProxyProgress(100);
    setTimeout(hideProxyProgress, 1500);
    showToast(`Walidacja: ${state.proxyValidated}/${state.proxyTotal} aktywnych`,'success');
}

async function handleClearProxy() {
    if (!state.proxyTotal) { showToast('Lista proxy jest pusta','info'); return; }
    const ok = await confirm('Wyczyść proxy', `Czy na pewno chcesz usunąć wszystkie proxy (${state.proxyTotal})?`, 'Wyczyść');
    if (!ok) return;

    // Cancel pending refresh timers
    clearTimeout(_loadRefreshTimer);
    clearTimeout(window._geoTimer);

    try {
        const r = await proxyApi.clearProxy();
        if (r.success) {
            state.proxyTotal = 0;
            state.proxyValidated = 0;
            setText(DOM.proxyCount, 0);
            setText(DOM.proxyValidCount, '✓ 0');
            setText(DOM.qsProxy, 0);
            setText(DOM.qsProxyValid, 0);
            const tbody = document.getElementById('proxy-table-body');
            if (tbody) tbody.innerHTML = '';
            const badge = document.getElementById('proxy-list-count');
            if (badge) badge.textContent = '0';
            const empty = document.getElementById('proxy-empty');
            if (empty) empty.style.display = '';
            showToast('Proxy wyczyszczone','info');
        }
    } catch(e) { showToast(e.message,'error'); }
}
