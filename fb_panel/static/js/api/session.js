/** Session API — 3-tab session management with live Selenium browsers */
import { request } from './client.js';

// Launch + CRUD
export const launchSession   = (log_id, worker_os = '', mode = 'selenium') => request('/api/sessions/launch', { method: 'POST', body: JSON.stringify({ log_id, worker_os, mode }) });
export const listSessions    = ()    => request('/api/sessions');
export const getSession      = (sid) => request(`/api/sessions/${sid}`);
export const getVncStatus    = (sid) => request(`/api/sessions/${sid}/vnc-status`);
export const closeSession    = (sid) => request(`/api/sessions/${sid}/close`, { method: 'POST' });
export const changeProxy     = (sid) => request(`/api/sessions/${sid}/change-proxy`, { method: 'POST' });

// Browser actions
export const loginEmail      = (sid) => request(`/api/sessions/${sid}/login-email`, { method: 'POST' });
export const extractCode     = (sid) => request(`/api/sessions/${sid}/extract-code`, { method: 'POST' });
export const enterCode       = (sid, code = '') => request(`/api/sessions/${sid}/enter-code`, { method: 'POST', body: JSON.stringify({ code }) });
export const openProfile     = (sid) => request(`/api/sessions/${sid}/open-profile`, { method: 'POST' });
export const refreshBrowserTab = (sid, tab) => request(`/api/sessions/${sid}/refresh-tab`, { method: 'POST', body: JSON.stringify({ tab }) });

/** Get screenshot URL (use as img.src with cache-busting) */
export const screenshotUrl   = (sid, tab) => `/api/sessions/${sid}/screenshot/${tab}?t=${Date.now()}`;

// Auto-action toggles
export const toggleAutoLogout       = (sid, enabled) => request(`/api/sessions/${sid}/auto-logout`, { method: 'POST', body: JSON.stringify({ enabled }) });
export const toggleAutoDisconnect   = (sid, enabled) => request(`/api/sessions/${sid}/auto-disconnect`, { method: 'POST', body: JSON.stringify({ enabled }) });
export const toggleAutoDeletePosts  = (sid, enabled) => request(`/api/sessions/${sid}/auto-delete-posts`, { method: 'POST', body: JSON.stringify({ enabled }) });
export const toggleAutoDeleteStories= (sid, enabled) => request(`/api/sessions/${sid}/auto-delete-stories`, { method: 'POST', body: JSON.stringify({ enabled }) });

// Manual actions
export const deletePosts            = (sid) => request(`/api/sessions/${sid}/delete-posts`, { method: 'POST' });
export const deleteStories          = (sid) => request(`/api/sessions/${sid}/delete-stories`, { method: 'POST' });
export const disconnectConnections  = (sid) => request(`/api/sessions/${sid}/disconnect`, { method: 'POST' });
