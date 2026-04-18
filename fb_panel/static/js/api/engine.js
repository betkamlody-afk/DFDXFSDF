/** Engine API */
import { request } from './client.js';

export const startEngine    = (concurrency) => request('/api/engine/start', { method: 'POST', body: JSON.stringify({ concurrency }) });
export const stopEngine     = ()            => request('/api/engine/stop', { method: 'POST' });
export const getEngineStatus = ()           => request('/api/engine/status');
