/** Workers + Anti-Connect API */
import { request } from './client.js';

export const getWorkers          = ()        => request('/api/workers');
export const toggleAntiConnect   = (enabled) => request('/api/anti-connect/toggle', { method: 'POST', body: JSON.stringify({ enabled }) });
export const getAntiConnectStatus = ()       => request('/api/anti-connect/status');
