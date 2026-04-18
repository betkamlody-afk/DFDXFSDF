/** Reactive application state */
export const state = {
    sessionId: null,
    isAuthorized: false,
    isRunning: false,

    // proxy
    proxyType: 'SOCKS5',
    proxyTotal: 0,
    proxyValidated: 0,
    isValidating: false,

    // data
    logs: [],
    workers: [],
    sessions: [],
    activeSession: null,
    stats: { success: 0, checkpoint: 0, invalid: 0, errors: 0, codesFound: 0 },
    settings: { concurrency: 3, antiConnect: true },
    currentFilter: 'all',

    // ws
    ws: null,
    wsReconnects: 0,

    // timers
    _workersTimer: null,
    _statsTimer: null,
    _previewLog: null,
    _vncStatusTimer: null,
};
