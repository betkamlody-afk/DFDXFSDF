/** Auth API */
import { request } from './client.js';

export const generateKey  = ()    => request('/api/generate-key', { method: 'POST' });
export const authorize    = (key) => request('/api/authorize', { method: 'POST', body: JSON.stringify({ key }) });
export const checkSession = ()    => request('/api/check-session');
export const logout       = ()    => request('/api/logout', { method: 'POST' });
