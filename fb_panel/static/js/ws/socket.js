/** WebSocket connection + reconnection + message dispatch */
import { CONFIG } from '../config.js';
import { state } from '../state.js';
import { updateWSStatus } from '../ui/dom.js';

/** @type {Record<string, Function[]>} */
const listeners = {};

export function on(event, fn) {
    (listeners[event] ||= []).push(fn);
}

export function connect() {
    if (state.ws?.readyState === WebSocket.OPEN) return;

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    try {
        state.ws = new WebSocket(`${proto}//${location.host}/ws`);

        state.ws.onopen = () => {
            state.wsReconnects = 0;
            updateWSStatus(true);
        };

        state.ws.onclose = () => {
            updateWSStatus(false);
            if (state.isAuthorized && state.wsReconnects < CONFIG.WS_MAX_RECONNECTS) {
                state.wsReconnects++;
                setTimeout(connect, CONFIG.WS_RECONNECT_DELAY);
            }
        };

        state.ws.onerror = () => {};

        state.ws.onmessage = (ev) => {
            try {
                const msg = JSON.parse(ev.data);
                const event = msg.event || msg.type;
                const data = msg.data || {};
                (listeners[event] || []).forEach(fn => fn(data));
            } catch (_) { /* ignore malformed */ }
        };
    } catch (_) { /* ignore */ }
}

export function disconnect() {
    if (state.ws) {
        state.ws.close();
        state.ws = null;
    }
}
