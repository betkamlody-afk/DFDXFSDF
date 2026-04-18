/** System API */
import { request } from './client.js';

export const getSystemInfo = () => request('/api/system/info');
