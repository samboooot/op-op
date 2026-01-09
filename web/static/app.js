/**
 Frontend JavaScript
 */

// ==================== STATE ====================

let currentPage = 'dashboard';
let activeTasks = [];
let currentWs = null;
let settings = {
    minVolume: 5,
    interval: 5
};

// ==================== INITIALIZATION ====================

document.addEventListener('DOMContentLoaded', () => {
    // Navigation
    document.querySelectorAll('[data-page]').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const page = item.dataset.page;
            navigateTo(page);
        });
    });

    // Task type toggle (radio buttons)
    document.querySelectorAll('input[name="task-type"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            const isMarketMaker = e.target.value === 'market_maker';
            document.getElementById('market-maker-fields').style.display = isMarketMaker ? 'block' : 'none';
            document.getElementById('sell-shares-fields').style.display = isMarketMaker ? 'none' : 'block';
        });
    });

    // Tabs
    document.querySelectorAll('[data-tab]').forEach(tab => {
        tab.addEventListener('click', (e) => {
            e.preventDefault();
            document.querySelectorAll('[data-tab]').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            loadTasks(tab.dataset.tab);
        });
    });

    // Load initial data
    loadDashboard();

    // Refresh every 10 seconds
    setInterval(loadDashboard, 10000);
});

// ==================== NAVIGATION ====================

function navigateTo(page) {
    currentPage = page;

    // Update nav
    document.querySelectorAll('[data-page]').forEach(item => {
        item.classList.toggle('active', item.dataset.page === page);
    });

    // Update pages
    document.querySelectorAll('.page-content').forEach(p => {
        p.style.display = p.id === `page-${page}` ? 'block' : 'none';
    });

    // Load page data
    if (page === 'dashboard') loadDashboard();
    else if (page === 'tasks') loadTasks('running');
    else if (page === 'trades') loadTrades();
    else if (page === 'settings') loadSettingsPage();
}

function loadSettingsPage() {
    // Load settings from localStorage
    const saved = localStorage.getItem('settings');
    if (saved) {
        try {
            const parsed = JSON.parse(saved);
            settings = { ...settings, ...parsed };
        } catch (e) { }
    }

    // Populate form
    document.getElementById('setting-min-volume').value = settings.minVolume || 5;
    document.getElementById('setting-interval').value = settings.interval || 5;
    document.getElementById('setting-auth-token').value = settings.authToken || '';

    // Update token status display
    updateTokenDateDisplay();
}

// ==================== DASHBOARD ====================

async function loadDashboard() {
    try {
        // Load status
        const status = await api('/api/status');
        document.getElementById('running-tasks').textContent = status.running_tasks || 0;
        document.getElementById('total-trades').textContent = status.total_trades || 0;
        document.getElementById('total-profit').textContent = `$${(status.total_profit || 0).toFixed(2)}`;

        // Load active tasks
        const tasks = await api('/api/tasks');
        activeTasks = tasks.filter(t => t.status === 'running');
        renderActiveTasks();

        // Load recent trades
        const trades = await api('/api/trades?limit=5');
        renderRecentTrades(trades.trades || []);

    } catch (e) {
        console.error('Failed to load dashboard:', e);
    }
}

function renderActiveTasks() {
    const container = document.getElementById('active-tasks-list');

    if (activeTasks.length === 0) {
        container.innerHTML = '<p class="text-muted">No active tasks</p>';
        return;
    }

    container.innerHTML = `
        <div class="table-responsive">
            <table class="table table-vcenter card-table">
                <tbody>
                    ${activeTasks.map(task => `
                        <tr>
                            <td>
                                <div class="fw-bold">${getTaskName(task)}</div>
                                <div class="text-muted small">${task.type.replace('_', ' ')}</div>
                            </td>
                            <td>
                                <span class="badge bg-success text-white">Running</span>
                            </td>
                            <td class="text-end">
                                <div class="btn-list flex-nowrap">
                                    <button class="btn btn-sm" onclick="showLogs('${task.id}')">
                                        <i class="ti ti-terminal me-1"></i> Logs
                                    </button>
                                    <button class="btn btn-sm btn-danger" onclick="stopTask('${task.id}')">
                                        <i class="ti ti-circle-minus me-1"></i> Stop
                                    </button>
                                </div>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function renderRecentTrades(trades) {
    const container = document.getElementById('recent-trades');

    if (trades.length === 0) {
        container.innerHTML = '<p class="empty-state">No trades yet</p>';
        return;
    }

    container.innerHTML = `
        <table class="trades-table">
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Event</th>
                    <th>Side</th>
                    <th>Action</th>
                    <th>Price</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                ${trades.map(t => `
                    <tr>
                        <td>${formatTime(t.timestamp)}</td>
                        <td>${t.outcome_name || '-'}</td>
                        <td><span class="badge ${t.side?.toLowerCase()}">${t.side || '-'}</span></td>
                        <td><span class="badge ${t.action?.toLowerCase()}">${t.action || '-'}</span></td>
                        <td>${t.price?.toFixed(3) || '-'}</td>
                        <td><span class="badge ${t.status}">${t.status || '-'}</span></td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

// ==================== TASKS ====================

async function loadTasks(filter = 'running') {
    try {
        const tasks = await api('/api/tasks');
        const filtered = filter === 'running'
            ? tasks.filter(t => t.status === 'running')
            : tasks;

        const container = document.getElementById('tasks-container');

        if (filtered.length === 0) {
            container.innerHTML = '<p class="text-muted">No tasks</p>';
            return;
        }

        container.innerHTML = `
            <div class="table-responsive">
                <table class="table table-vcenter card-table">
                    <thead>
                        <tr>
                            <th>Type</th>
                            <th>Name</th>
                            <th>Status</th>
                            <th>Created</th>
                            <th class="w-1">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${filtered.map(task => `
                            <tr>
                                <td><span class="badge ${getTypeBadgeClass(task.type)}">${task.type.replace('_', ' ')}</span></td>
                                <td>${getTaskName(task)}</td>
                                <td>
                                    <span class="badge ${getStatusBadgeClass(task.status)}">
                                        ${task.status}
                                    </span>
                                </td>
                                <td class="text-muted">${formatTime(task.created_at)}</td>
                                <td>
                                    <div class="btn-list flex-nowrap">
                                        <button class="btn btn-sm" onclick="showLogs('${task.id}')">
                                            <i class="ti ti-terminal me-1"></i> Logs
                                        </button>
                                        ${task.status === 'running' ? `
                                            <button class="btn btn-sm btn-danger" onclick="stopTask('${task.id}')">
                                                <i class="ti ti-circle-minus me-1"></i> Stop
                                            </button>
                                        ` : task.status === 'pending' ? `
                                            <button class="btn btn-sm btn-primary" onclick="startTask('${task.id}')">
                                                <i class="ti ti-player-play me-1"></i> Start
                                            </button>
                                        ` : ''}
                                    </div>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;

    } catch (e) {
        console.error('Failed to load tasks:', e);
    }
}

function getTaskName(task) {
    const config = task.config || {};
    if (config.outcome) {
        return config.outcome;
    }
    if (config.url) {
        const match = config.url.match(/topicId=(\d+)/);
        return match ? `Topic ${match[1]}` : 'Unknown';
    }
    return task.type === 'sell_shares' ? 'Sell All Shares' : task.id;
}

function getTypeBadgeClass(type) {
    switch (type) {
        case 'market_maker': return 'bg-azure" style="color: white !important;';
        case 'sell_shares': return 'bg-orange" style="color: white !important;';
        default: return 'bg-secondary" style="color: white !important;';
    }
}

function getStatusBadgeClass(status) {
    switch (status) {
        case 'running': return 'bg-success text-white';
        case 'stopped': return 'bg-secondary text-white';
        case 'error': return 'bg-danger text-white';
        case 'pending': return 'bg-warning text-dark';
        case 'completed': return 'bg-azure text-white';
        default: return 'bg-secondary text-white';
    }
}

function formatTime(timestamp) {
    if (!timestamp) return '-';
    const d = new Date(timestamp);
    return d.toLocaleString();
}

// ==================== TRADES ====================

async function loadTrades() {
    try {
        // Load stats
        const stats = await api('/api/trades/stats');
        document.getElementById('trades-total').textContent = stats.total_trades || 0;
        document.getElementById('trades-profit').textContent = `$${(stats.total_profit || 0).toFixed(2)}`;
        document.getElementById('trades-wins').textContent = stats.wins || 0;
        document.getElementById('trades-losses').textContent = stats.losses || 0;

        // Load trades
        const result = await api('/api/trades?limit=100');
        const trades = result.trades || [];

        const tbody = document.getElementById('trades-tbody');

        if (trades.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No trades yet</td></tr>';
            return;
        }

        tbody.innerHTML = trades.map(t => `
            <tr>
                <td>${formatTime(t.timestamp)}</td>
                <td>${t.event_name || '-'}</td>
                <td><span class="badge ${t.side?.toLowerCase()}">${t.side || '-'}</span></td>
                <td><span class="badge ${t.action?.toLowerCase()}">${t.action || '-'}</span></td>
                <td>${t.price?.toFixed(3) || '-'}</td>
                <td>${t.shares?.toFixed(2) || '-'}</td>
                <td>$${t.amount_usdt?.toFixed(2) || '-'}</td>
                <td><span class="badge ${t.status}">${t.status || '-'}</span></td>
            </tr>
        `).join('');

    } catch (e) {
        console.error('Failed to load trades:', e);
    }
}

// ==================== TASK ACTIONS ====================

let logsModal = null;

async function createTask() {
    const type = document.querySelector('input[name="task-type"]:checked')?.value || 'market_maker';

    if (type === 'market_maker') {
        const url = document.getElementById('task-url').value;
        const outcome = document.getElementById('task-outcome').value;
        const minVolume = parseFloat(document.getElementById('task-min-volume').value) || 5;

        if (!url || !outcome) {
            alert('Please fill URL and Outcome');
            return;
        }

        // Show loading
        const footer = document.getElementById('new-task-footer');
        if (footer) footer.innerHTML = '<span class="text-muted">Loading prices...</span>';

        try {
            const preview = await api('/api/preview', 'POST', {
                url,
                outcome,
                amount: 15,
                min_volume: minVolume,
                auth_token: settings.authToken || null
            });

            showPreview(preview, { url, outcome, min_volume: minVolume });

        } catch (e) {
            alert('Failed to get prices: ' + e.message);
            resetNewTaskForm();
        }
    } else {
        // Sell shares - get positions first
        getMyShares();
    }
}

// ==================== SELL SHARES ====================

async function getMyShares() {
    const topicId = document.getElementById('sell-topic-id')?.value;

    const footer = document.getElementById('new-task-footer');
    if (footer) footer.innerHTML = '<span class="text-muted">Loading positions...</span>';

    try {
        const result = await api('/api/positions', 'POST', {
            topic_id: topicId ? parseInt(topicId) : null,
            auth_token: settings.authToken || null
        });

        showPositions(result.positions);

    } catch (e) {
        alert('Failed to get positions: ' + e.message);
        resetNewTaskForm();
    }
}

let currentPositions = null;

function showPositions(positions) {
    currentPositions = positions;

    const body = document.getElementById('sell-shares-body');
    const footer = document.getElementById('new-task-footer');

    if (positions.length === 0) {
        body.innerHTML = '<div class="alert alert-info">No positions available to sell</div>';
        footer.innerHTML = `
            <button type="button" class="btn" onclick="resetNewTaskForm()">
                <i class="ti ti-arrow-left me-1"></i> Back
            </button>
        `;
        return;
    }

    body.innerHTML = `
        <h4 class="mb-3">Your Positions (${positions.length})</h4>
        <div class="table-responsive mb-4">
            <table class="table table-vcenter">
                <thead>
                    <tr>
                        <th>Event</th>
                        <th>Outcome</th>
                        <th>Side</th>
                        <th>Shares</th>
                        <th>Value</th>
                    </tr>
                </thead>
                <tbody>
                    ${positions.map(pos => `
                        <tr>
                            <td><small class="text-muted">${pos.title}</small></td>
                            <td>${pos.outcome}</td>
                            <td><span class="badge ${pos.side === 'YES' ? 'bg-success' : 'bg-danger'}">${pos.side}</span></td>
                            <td>${pos.shares}</td>
                            <td>$${pos.value}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
        
        <div class="mb-3">
            <label class="form-label">Sell Mode</label>
            <div class="btn-group w-100" role="group" style="max-width: 400px;">
                <input type="radio" class="btn-check" name="sell-mode" id="sell-mode-standard" value="standard" checked>
                <label class="btn btn-outline-primary" for="sell-mode-standard">
                    Standard (Best Bid)
                </label>
                <input type="radio" class="btn-check" name="sell-mode" id="sell-mode-spread" value="spread">
                <label class="btn btn-outline-primary" for="sell-mode-spread">
                    Spread (First in Queue)
                </label>
            </div>
        </div>
    `;

    footer.innerHTML = `
        <button type="button" class="btn" onclick="resetNewTaskForm()">
            <i class="ti ti-arrow-left me-1"></i> Back
        </button>
        <button type="button" class="btn btn-warning" onclick="confirmSellShares()">
            <i class="ti ti-coin me-1"></i> Sell All Positions
        </button>
    `;
}

async function confirmSellShares() {
    if (!currentPositions || currentPositions.length === 0) return;

    const mode = document.querySelector('input[name="sell-mode"]:checked')?.value || 'standard';
    const topicId = document.getElementById('sell-topic-id')?.value;

    const config = {
        mode: mode,
        min_volume: settings.minVolume,
        interval: settings.interval,
        auth_token: settings.authToken || null
    };
    if (topicId) config.topic_id = parseInt(topicId);

    try {
        const footer = document.getElementById('new-task-footer');
        if (footer) footer.innerHTML = '<span class="text-muted">Starting sell task...</span>';

        const result = await api('/api/tasks', 'POST', { type: 'sell_shares', config });
        await api(`/api/tasks/${result.id}/start`, 'POST');

        navigateTo('tasks');
        loadDashboard();
        showLogs(result.id);

    } catch (e) {
        alert('Failed: ' + e.message);
        resetNewTaskForm();
    }
}

function resetModalFooter() {
    const footer = document.getElementById('new-task-footer');
    if (footer) {
        footer.innerHTML = `
            <button type="button" class="btn btn-primary" onclick="createTask()">
                <i class="ti ti-chart-candle me-1"></i> Get Prices
            </button>
        `;
    }
}

function resetNewTaskForm() {
    location.reload();
}

let currentPreview = null;

function showPreview(preview, config) {
    currentPreview = { preview, config };

    const hasSpread = preview.yes.has_spread || preview.no.has_spread;

    // Build orderbook display
    function renderBidTable(data) {
        const bids = data.bids || [];
        let rows = '';
        for (let i = 0; i < 5; i++) {
            const bid = bids[i];
            if (bid) {
                const price = parseFloat(bid[0]);
                const size = parseFloat(bid[1]);
                const total = (price * size).toFixed(2);
                rows += `<tr><td class="text-muted">${total}</td><td>${size.toFixed(1)}</td><td class="text-success fw-bold">${price.toFixed(3)}</td></tr>`;
            } else {
                rows += `<tr><td>-</td><td>-</td><td>-</td></tr>`;
            }
        }
        return rows;
    }

    function renderAskTable(data) {
        const asks = data.asks || [];
        let rows = '';
        for (let i = 0; i < 5; i++) {
            const ask = asks[i];
            if (ask) {
                const price = parseFloat(ask[0]);
                const size = parseFloat(ask[1]);
                const total = (price * size).toFixed(2);
                rows += `<tr><td class="text-danger fw-bold">${price.toFixed(3)}</td><td>${size.toFixed(1)}</td><td class="text-muted">${total}</td></tr>`;
            } else {
                rows += `<tr><td>-</td><td>-</td><td>-</td></tr>`;
            }
        }
        return rows;
    }

    const body = document.getElementById('new-task-body');
    const footer = document.getElementById('new-task-footer');

    if (body) body.innerHTML = `
        <div class="mb-4">
            <h3 class="mb-3">${preview.outcome}</h3>
            
            <div class="row g-4">
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">
                            <span class="badge bg-success text-white">YES</span>
                        </div>
                        <div class="row g-0">
                            <div class="col-6 border-end">
                                <div class="p-2 text-center small text-muted">BID</div>
                                <table class="table table-sm orderbook-table">
                                    <thead><tr><th>Total</th><th>Size</th><th>Price</th></tr></thead>
                                    <tbody>${renderBidTable(preview.yes)}</tbody>
                                </table>
                            </div>
                            <div class="col-6">
                                <div class="p-2 text-center small text-muted">ASK</div>
                                <table class="table table-sm orderbook-table">
                                    <thead><tr><th>Price</th><th>Size</th><th>Total</th></tr></thead>
                                    <tbody>${renderAskTable(preview.yes)}</tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">
                            <span class="badge bg-danger text-white">NO</span>
                        </div>
                        <div class="row g-0">
                            <div class="col-6 border-end">
                                <div class="p-2 text-center small text-muted">BID</div>
                                <table class="table table-sm orderbook-table">
                                    <thead><tr><th>Total</th><th>Size</th><th>Price</th></tr></thead>
                                    <tbody>${renderBidTable(preview.no)}</tbody>
                                </table>
                            </div>
                            <div class="col-6">
                                <div class="p-2 text-center small text-muted">ASK</div>
                                <table class="table table-sm orderbook-table">
                                    <thead><tr><th>Price</th><th>Size</th><th>Total</th></tr></thead>
                                    <tbody>${renderAskTable(preview.no)}</tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="mb-3">
            <label class="form-label">Amount (USDT per side)</label>
            <input type="number" class="form-control" id="preview-amount" value="15" step="1" min="1" style="max-width: 200px;">
        </div>
        
        <div class="mb-3">
            <label class="form-label">Mode</label>
            <div class="form-selectgroup">
                <label class="form-selectgroup-item">
                    <input type="radio" name="mode" value="standard" class="form-selectgroup-input" checked>
                    <span class="form-selectgroup-label">
                        <strong>Standard</strong> — YES - ${preview.yes.bid}, NO - ${preview.no.bid}
                    </span>
                </label>
                ${hasSpread ? `
                <label class="form-selectgroup-item">
                    <input type="radio" name="mode" value="spread" class="form-selectgroup-input">
                    <span class="form-selectgroup-label">
                        <strong>Spread</strong> — YES - ${preview.yes.spread_buy || preview.yes.bid}${preview.yes.has_spread ? '' : ''}, 
                        NO - ${preview.no.spread_buy || preview.no.bid}${preview.no.has_spread ? '' : ''}
                    </span>
                </label>
                ` : ''}
            </div>
        </div>
        
        <div class="mb-3">
            <label class="form-check form-switch">
                <input class="form-check-input" type="checkbox" id="preview-single-order" onchange="togglePreviewSingleOrder()">
                <span class="form-check-label">Single Order</span>
            </label>
        </div>
        <div class="mb-3" id="preview-single-order-side" style="display: none;">
            <label class="form-label"></label>
            <div class="btn-group w-100" role="group" style="max-width: 300px;">
                <input type="radio" class="btn-check" name="preview-order-side" id="preview-order-side-yes" value="yes" checked>
                <label class="btn btn-outline-success" for="preview-order-side-yes">
                    <i class="ti ti-check me-1"></i> YES
                </label>
                <input type="radio" class="btn-check" name="preview-order-side" id="preview-order-side-no" value="no">
                <label class="btn btn-outline-danger" for="preview-order-side-no">
                    <i class="ti ti-x me-1"></i> NO
                </label>
            </div>
        </div>
    `;

    if (footer) footer.innerHTML = `
        <button type="button" class="btn" onclick="resetNewTaskForm()">
            <i class="ti ti-arrow-left me-1"></i> Back
        </button>
        <button type="button" class="btn btn-primary" onclick="confirmAndStart()">
            <i class="ti ti-send me-1"></i> Place Orders
        </button>
    `;
}

function togglePreviewSingleOrder() {
    const toggle = document.getElementById('preview-single-order');
    const sideDiv = document.getElementById('preview-single-order-side');
    if (sideDiv) sideDiv.style.display = toggle?.checked ? 'block' : 'none';
}

async function confirmAndStart() {
    if (!currentPreview) return;

    const { config } = currentPreview;
    const mode = document.querySelector('input[name="mode"]:checked')?.value || 'standard';
    const amount = parseFloat(document.getElementById('preview-amount')?.value || 15);
    const minVolume = config.min_volume || settings.minVolume;
    const singleOrderEnabled = document.getElementById('preview-single-order')?.checked || false;
    const singleOrderSide = document.querySelector('input[name="preview-order-side"]:checked')?.value || 'yes';

    const fullConfig = {
        url: config.url,
        outcome: config.outcome,
        amount: amount,
        mode: mode,
        min_volume: minVolume,
        interval: settings.interval,
        auth_token: settings.authToken || null
    };

    // Add single order side if enabled
    if (singleOrderEnabled) {
        fullConfig.single_order_side = singleOrderSide;
    }

    try {
        const footer = document.getElementById('new-task-footer');
        if (footer) footer.innerHTML = '<span class="text-muted">Placing orders...</span>';

        const result = await api('/api/tasks', 'POST', { type: 'market_maker', config: fullConfig });
        await api(`/api/tasks/${result.id}/start`, 'POST');

        navigateTo('tasks');
        loadDashboard();
        showLogs(result.id);

    } catch (e) {
        alert('Failed: ' + e.message);
        resetModalFooter();
    }
}

async function startTask(taskId) {
    try {
        await api(`/api/tasks/${taskId}/start`, 'POST');
        loadTasks();
        loadDashboard();
    } catch (e) {
        alert('Failed to start task: ' + e.message);
    }
}

async function stopTask(taskId) {
    try {
        await api(`/api/tasks/${taskId}/stop`, 'POST');
        loadTasks();
        loadDashboard();
    } catch (e) {
        alert('Failed to stop task: ' + e.message);
    }
}

// ==================== LOGS ====================

let logsPollingInterval = null;
let currentLogsTaskId = null;

function showLogs(taskId) {
    if (logsPollingInterval) {
        clearInterval(logsPollingInterval);
        logsPollingInterval = null;
    }

    if (!logsModal) {
        logsModal = new bootstrap.Modal(document.getElementById('logs-modal'));
    }
    logsModal.show();

    const container = document.getElementById('logs-container');
    container.innerHTML = '<div class="log-entry">Loading logs...</div>';

    currentLogsTaskId = taskId;

    // Initial load
    loadLogsOnce(taskId, container);

    // Start  every 2 seconds
    logsPollingInterval = setInterval(() => {
        if (currentLogsTaskId === taskId) {
            loadLogsOnce(taskId, container);
        }
    }, 2000);
}

async function loadLogsOnce(taskId, container) {
    try {
        const result = await api(`/api/tasks/${taskId}/logs?limit=200`);
        const logs = result.logs || [];

        if (logs.length === 0) {
            container.innerHTML = '<div class="log-entry">No logs yet...</div>';
            return;
        }

        container.innerHTML = logs.map(log =>
            `<div class="log-entry">${escapeHtml(log)}</div>`
        ).join('');

        container.scrollTop = container.scrollHeight;
    } catch (e) {
        console.error('Failed to load logs:', e);
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function closeLogsModal() {
    if (logsModal) {
        logsModal.hide();
    }
    if (logsPollingInterval) {
        clearInterval(logsPollingInterval);
        logsPollingInterval = null;
    }
    currentLogsTaskId = null;
}

function copyLogs() {
    const container = document.getElementById('logs-container');
    if (!container) return;

    // Get content from all log 
    const entries = container.querySelectorAll('.log-entry');
    const text = Array.from(entries).map(e => e.textContent).join('\n');

    navigator.clipboard.writeText(text).then(() => {
        alert('Logs copied to clipboard!');
    }).catch(err => {
        alert('Failed to copy logs: ' + err);
    });
}

// ==================== SETTINGS ====================

async function saveSettings() {
    settings.minVolume = parseFloat(document.getElementById('setting-min-volume').value);
    settings.interval = parseFloat(document.getElementById('setting-interval').value);

    const newToken = document.getElementById('setting-auth-token').value;

    // Check if token changed - update timestamp
    if (newToken && newToken !== settings.authToken) {
        settings.authTokenUpdatedAt = new Date().toISOString();
    }

    settings.authToken = newToken;
    localStorage.setItem('settings', JSON.stringify(settings));

    // Update token on server for running tasks
    if (settings.authToken) {
        try {
            await api('/api/settings/token', 'POST', { auth_token: settings.authToken });
            updateTokenDateDisplay();
            alert('Settings saved! Token updated for all running tasks.');
        } catch (e) {
            alert('Settings saved locally, but failed to update running tasks: ' + e.message);
        }
    } else {
        alert('Settings saved!');
    }
}

function updateTokenDateDisplay() {
    const container = document.getElementById('token-status');
    if (!container) return;

    if (!settings.authToken || !settings.authTokenUpdatedAt) {
        container.innerHTML = '<span class="text-muted">No token saved</span>';
        return;
    }

    const updatedAt = new Date(settings.authTokenUpdatedAt);
    const now = new Date();
    const expiresAt = new Date(updatedAt.getTime() + 24 * 60 * 60 * 1000); // +24 hours
    const remainingMs = expiresAt - now;

    // Format: DD.MM, HH:MM
    const day = String(updatedAt.getDate()).padStart(2, '0');
    const month = String(updatedAt.getMonth() + 1).padStart(2, '0');
    const hours = String(updatedAt.getHours()).padStart(2, '0');
    const mins = String(updatedAt.getMinutes()).padStart(2, '0');
    const updatedStr = `${day}.${month}, ${hours}:${mins}`;

    if (remainingMs <= 0) {
        // Expired
        container.innerHTML = `
            <span class="text-danger">
                <i class="ti ti-alert-circle me-1"></i>
                Token EXPIRED! Updated: ${updatedStr}
            </span>
        `;
    } else {
        // Calculate remaining time
        const remHours = Math.floor(remainingMs / (1000 * 60 * 60));
        const remMins = Math.floor((remainingMs % (1000 * 60 * 60)) / (1000 * 60));

        const isWarning = remHours < 2;
        const colorClass = isWarning ? 'text-warning' : 'text-success';
        const icon = isWarning ? 'ti-clock-exclamation' : 'ti-clock-check';

        container.innerHTML = `
            <span class="${colorClass}">
                <i class="ti ${icon} me-1"></i>
                Updated: ${updatedStr} | Expires in: ${remHours}h ${remMins}m
            </span>
        `;
    }
}

async function pasteToken() {
    try {
        const text = await navigator.clipboard.readText();
        document.getElementById('setting-auth-token').value = text;
    } catch (e) {
        alert('Failed to paste from clipboard. Please paste manually.');
    }
}

function toggleSingleOrder() {
    const toggle = document.getElementById('single-order-toggle');
    const sideDiv = document.getElementById('single-order-side');
    sideDiv.style.display = toggle.checked ? 'block' : 'none';
}

// Load settings from localStorage
const savedSettings = localStorage.getItem('settings');
if (savedSettings) {
    settings = JSON.parse(savedSettings);
    document.getElementById('setting-min-volume').value = settings.minVolume;
    document.getElementById('setting-interval').value = settings.interval;
    if (settings.authToken) {
        document.getElementById('setting-auth-token').value = settings.authToken;
    }
}

// ==================== HELPERS ====================

async function api(url, method = 'GET', body = null) {
    const options = {
        method,
        headers: { 'Content-Type': 'application/json' }
    };
    if (body) options.body = JSON.stringify(body);

    const response = await fetch(url, options);
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'API Error');
    }
    return response.json();
}

function formatTime(timestamp) {
    if (!timestamp) return '-';
    const date = new Date(timestamp);
    return date.toLocaleTimeString();
}

function getTaskName(task) {
    if (task.config?.outcome) return task.config.outcome;
    if (task.config?.topic_id) return `Topic #${task.config.topic_id}`;
    return task.id;
}

function getStatusIcon(status) {
    const icons = {
        'running': '<span class="material-icons" style="font-size: 14px">play_arrow</span>',
        'stopped': '<span class="material-icons" style="font-size: 14px">stop</span>',
        'completed': '<span class="material-icons" style="font-size: 14px">check</span>',
        'error': '<span class="material-icons" style="font-size: 14px">error</span>',
        'pending': '<span class="material-icons" style="font-size: 14px">schedule</span>'
    };
    return icons[status] || '';
}
