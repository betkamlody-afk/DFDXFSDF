/** Base HTTP client — all API calls go through here */
import { CONFIG } from '../config.js';
import { state } from '../state.js';

export async function request(endpoint, options = {}) {
    const url = `${CONFIG.API_BASE}${endpoint}`;
    const headers = { 'Content-Type': 'application/json', ...options.headers };
    if (state.sessionId) headers['X-Session-ID'] = state.sessionId;

    const resp = await fetch(url, { ...options, headers, credentials: 'same-origin' });
    let data;
    try {
        data = await resp.json();
    } catch {
        if (!resp.ok) throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
        throw new Error('Invalid JSON response');
    }
    if (!resp.ok) throw new Error(data.error || data.message || `HTTP ${resp.status}`);
    return data;
}
