/** Logs API */
import { request } from './client.js';

export const loadLogs  = (lines) => request('/api/logs/load', { method: 'POST', body: JSON.stringify({ lines }) });
export const getStats  = ()      => request('/api/logs/stats');
export const getAll    = ()      => request('/api/logs/all');
export const clearLogs = ()      => request('/api/logs/clear', { method: 'POST' });
export const getLog    = (id)    => request(`/api/logs/${encodeURIComponent(id)}`);
export const deleteLog = (id)    => request(`/api/logs/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const retryLog  = (id)    => request(`/api/logs/${encodeURIComponent(id)}/retry`, { method: 'POST' });
