/** Proxy API */
import { request } from './client.js';

export const loadProxy     = (lines, proxyType) => request('/api/proxy/load', { method: 'POST', body: JSON.stringify({ lines, proxy_type: proxyType }) });
export const validateProxy = ()                 => request('/api/proxy/validate', { method: 'POST' });
export const getProxyStats = ()                 => request('/api/proxy/stats');
export const clearProxy    = ()                 => request('/api/proxy/clear', { method: 'POST' });
export const listProxies   = ()                 => request('/api/proxy/list');
export const checkProxy    = (proxy)            => request('/api/proxy/check', { method: 'POST', body: JSON.stringify({ proxy }) });
