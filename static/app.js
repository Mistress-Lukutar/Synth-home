// ZigbeeHUB WebUI - Frontend Logic
let isConnected = false;
let currentPort = null;
let evtSource = null;
let sseReconnectTimer = null;
let sseReconnectDelay = 1000;
let titleEditTimeout = null;
let lastDevices = [];


// === Connection ===

async function refreshPorts() {
    try {
        const res = await fetch('/api/ports');
        const data = await res.json();
        const select = document.getElementById('portSelect');
        const current = select.value;
        select.innerHTML = '<option value="">Select port...</option>';
        data.ports.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p;
            opt.textContent = p;
            select.appendChild(opt);
        });
        if (data.ports.includes(current)) select.value = current;
    } catch (e) {
        logEvent('Failed to list ports: ' + e.message);
    }
}

async function connectPort() {
    const port = document.getElementById('portSelect').value;
    if (!port) {
        alert('Select a COM port');
        return;
    }
    showStatus('Connecting...', 'warning');
    try {
        const res = await fetch('/api/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ port })
        });
        const data = await res.json();
        if (data.success) {
            onConnected(port);
        } else {
            showStatus(data.error || 'Connection failed', 'error');
        }
    } catch (e) {
        showStatus('Connection error', 'error');
    }
}

async function disconnectPort() {
    try {
        await fetch('/api/disconnect', { method: 'POST' });
    } catch (e) {
    } finally {
        onDisconnected();
    }
}

function onConnected(port) {
    isConnected = true;
    currentPort = port;
    showStatus(`Connected: ${port}`, 'success');
    document.getElementById('statusDot').classList.add('connected');
    document.getElementById('disconnectBtn').style.display = 'block';
    document.getElementById('connectionControls').style.display = 'none';

    setControlsEnabled(true);
    document.getElementById('infoPort').textContent = port;
    loadDevices();
    startSSE();
}

function onDisconnected() {
    isConnected = false;
    currentPort = null;
    showStatus('Disconnected', 'none');
    document.getElementById('statusDot').classList.remove('connected');
    document.getElementById('disconnectBtn').style.display = 'none';
    document.getElementById('connectionControls').style.display = 'flex';

    setControlsEnabled(false);
    stopSSE();

    document.getElementById('deviceCards').innerHTML = '<div class="device-empty">Not connected</div>';
    document.getElementById('infoPort').textContent = '-';
    document.getElementById('infoUptime').textContent = '-';
    document.getElementById('infoFw').textContent = '-';
    document.getElementById('netState').textContent = '-';
    document.getElementById('netDevices').textContent = '-';
    document.getElementById('eventLog').innerHTML = '<div class="event-item" style="color:#666;">Waiting for connection...</div>';
}

function setControlsEnabled(enabled) {
    ['devicesPanel', 'networkPanel', 'infoPanel', 'eventsPanel'].forEach(id => {
        const el = document.getElementById(id);
        if (enabled) el.classList.remove('disabled');
        else el.classList.add('disabled');
    });
    document.getElementById('btnRefreshDevices').disabled = !enabled;
    document.getElementById('btnPermit').disabled = !enabled;
}

function showStatus(text, type) {
    const dot = document.getElementById('statusDot');
    const label = document.getElementById('statusText');
    label.textContent = text;
    dot.classList.remove('connected');
    dot.style.background = '';
    if (type === 'success') {
        dot.style.background = '#00ff88';
        dot.classList.add('connected');
    } else if (type === 'error') {
        dot.style.background = '#ff4444';
    } else if (type === 'warning') {
        dot.style.background = '#ffaa00';
    } else {
        dot.style.background = '#ff4444';
    }
}

// === SSE ===

function startSSE() {
    if (evtSource) evtSource.close();
    evtSource = new EventSource('/events');
    evtSource.onopen = () => {
        sseReconnectDelay = 1000;
    };
    evtSource.onmessage = (e) => {
        try {
            const msg = JSON.parse(e.data);
            handleSSEMessage(msg);
        } catch (err) {
            logEvent('SSE raw: ' + e.data);
        }
    };
    evtSource.onerror = () => {
        logEvent('SSE error / disconnected');
        evtSource.close();
        evtSource = null;
        if (!sseReconnectTimer && isConnected) {
            sseReconnectTimer = setTimeout(() => {
                sseReconnectTimer = null;
                startSSE();
            }, sseReconnectDelay);
            sseReconnectDelay = Math.min(sseReconnectDelay * 2, 30000);
        }
    };
}

function stopSSE() {
    if (sseReconnectTimer) {
        clearTimeout(sseReconnectTimer);
        sseReconnectTimer = null;
    }
    if (evtSource) {
        evtSource.close();
        evtSource = null;
    }
    sseReconnectDelay = 1000;
}

function handleSSEMessage(msg) {
    if (msg.type === 'connected') {
        logEvent('Hub connected event');
        document.getElementById('netState').textContent = 'Open';
    } else if (msg.type === 'disconnected') {
        logEvent('Hub disconnected event');
        document.getElementById('netState').textContent = 'Closed';
    } else if (msg.type === 'hub_message') {
        const data = msg.data || {};
        const evt = data.evt || data.event || 'message';
        logEvent(`Hub: ${evt} → ${JSON.stringify(data)}`);
        if (['device_list', 'device_joined', 'device_left', 'state_change'].includes(evt)) {
            loadDevices();
        }
    } else if (msg.type === 'scenario_triggered') {
        const next = msg.next_run_time ? new Date(msg.next_run_time).toLocaleString() : 'N/A';
        logEvent(`⏰ Scenario triggered: ${msg.scenario_name} (id=${msg.scenario_id}) — next run: ${next}`);
    } else if (msg.type === 'scenario_executed') {
        const next = msg.next_run_time ? new Date(msg.next_run_time).toLocaleString() : 'N/A';
        logEvent(`✅ Scenario executed: ${msg.scenario_name} (id=${msg.scenario_id}) — next run: ${next}`);
    } else if (msg.type === 'scenario_execution_failed') {
        const next = msg.next_run_time ? new Date(msg.next_run_time).toLocaleString() : 'N/A';
        logEvent(`❌ Scenario FAILED: ${msg.scenario_name} (id=${msg.scenario_id}) — error: ${msg.error} — next run: ${next}`);
    } else if (msg.type === 'scenario_skipped') {
        const next = msg.next_run_time ? new Date(msg.next_run_time).toLocaleString() : 'N/A';
        logEvent(`⏭️ Scenario skipped: ${msg.scenario_name} (id=${msg.scenario_id}) — reason: ${msg.reason} — next run: ${next}`);
    } else {
        logEvent(`SSE: ${JSON.stringify(msg)}`);
    }
}

// === Devices ===

async function loadDevices() {
    if (!isConnected) {
        document.getElementById('deviceCards').innerHTML = '<div class="device-empty">Not connected</div>';
        return;
    }
    const refreshBtn = document.getElementById('btnRefreshDevices');
    if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.textContent = 'Loading...';
    }
    try {
        const res = await fetch('/api/devices');
        const data = await res.json();
        if (data.success) {
            renderDevices(data.devices || []);
            document.getElementById('netDevices').textContent = (data.devices || []).length;
        }
    } catch (e) {
        console.error('Load devices error:', e);
    } finally {
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.textContent = 'Refresh';
        }
    }
}

function renderDevices(devices) {
    const container = document.getElementById('deviceCards');
    lastDevices = devices;
    if (!devices.length) {
        container.innerHTML = '<div class="device-empty">No devices found</div>';
        return;
    }
    container.innerHTML = devices.map(d => {
        const onlineClass = d.online ? 'device-online' : 'device-offline';
        const onlineText = d.online ? 'Online' : 'Offline';
        return `
            <div class="device-card">
                <div class="device-info">
                    <div class="editable-title">
                        <span class="title-text" onclick="startEditTitle(this.parentElement)">${escapeHtml(d.name || 'Unknown Device')}</span>
                        <svg class="edit-icon" onclick="startEditTitle(this.parentElement)" viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>
                        <input type="text" class="title-input" value="${escapeHtml(d.name || 'Unknown Device')}" data-type="device" data-ieee="${escapeHtml(d.ieee)}" data-original="${escapeHtml(d.name || 'Unknown Device')}" onkeydown="handleTitleKey(event, this)" onblur="handleTitleBlur(this)">
                    </div>
                    <div class="device-details">
                        <span class="device-ieee">${escapeHtml(d.ieee)}</span>
                        <span>EP ${escapeHtml(String(d.endpoint || '-'))}</span>
                        <span class="${onlineClass}">${onlineText}</span>
                    </div>
                </div>
                <div class="device-actions">
                    <button class="btn btn-small btn-on" onclick="sendCommand('${d.ieee}', 'on')">On</button>
                    <button class="btn btn-small btn-off" onclick="sendCommand('${d.ieee}', 'off')">Off</button>
                </div>
            </div>
        `;
    }).join('');
    updateDeviceSelects();
}

function updateDeviceSelects() {
    const selects = [document.getElementById('scDevice')];
    selects.forEach(sel => {
        if (!sel) return;
        const current = sel.value;
        sel.innerHTML = '<option value="">Select device...</option>';
        lastDevices.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.ieee;
            opt.textContent = (d.name || 'Unknown') + ' (' + d.ieee + ')';
            sel.appendChild(opt);
        });
        if (lastDevices.find(x => x.ieee === current)) sel.value = current;
    });
}

async function sendCommand(ieee, action) {
    if (!isConnected) return;
    logEvent(`Command ${action} → ${ieee}`);
    try {
        const res = await fetch(`/api/devices/${ieee}/command`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action })
        });
        const data = await res.json();
        if (!data.success) {
            logEvent('Command failed: ' + (data.error || 'unknown'));
        }
    } catch (e) {
        logEvent('Command error: ' + e.message);
    }
}

// === Network ===

async function permitJoin() {
    if (!isConnected) return;
    const statusMsg = document.getElementById('networkStatusMsg');
    statusMsg.textContent = 'Opening network for 180s...';
    statusMsg.style.background = 'rgba(255,255,255,0.1)';
    statusMsg.style.color = '#fff';
    statusMsg.style.display = 'block';
    try {
        const res = await fetch('/api/network/permit-join', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ duration: 180 })
        });
        const data = await res.json();
        if (data.success) {
            statusMsg.textContent = 'Network open for 180 seconds';
            statusMsg.style.background = 'rgba(0,255,136,0.2)';
            statusMsg.style.color = '#00ff88';
            logEvent('Permit join sent (180s)');
        } else {
            statusMsg.textContent = 'Error: ' + (data.error || 'Unknown');
            statusMsg.style.background = 'rgba(255,68,68,0.2)';
            statusMsg.style.color = '#ff4444';
        }
    } catch (e) {
        statusMsg.textContent = 'Request error';
        statusMsg.style.background = 'rgba(255,68,68,0.2)';
        statusMsg.style.color = '#ff4444';
    }
}

// === Scenarios ===

function updateScenarioForm() {
    const type = document.getElementById('scTriggerType').value;
    const scheduleGroups = document.querySelectorAll('.schedule-fields');
    const triggerConfigGroup = document.getElementById('scTriggerConfigGroup');

    scheduleGroups.forEach(el => {
        el.classList.toggle('visible', type === 'schedule');
    });

    if (triggerConfigGroup) {
        triggerConfigGroup.style.display = (type === 'device_event' || type === 'schedule') ? 'flex' : 'none';
    }
}

async function loadScenarios() {
    try {
        const res = await fetch('/api/scenarios');
        const data = await res.json();
        renderScenarios(data || []);
    } catch (e) {
        console.error('Load scenarios error:', e);
    }
}

function renderScenarios(scenarios) {
    const container = document.getElementById('scenarioList');
    if (!scenarios.length) {
        container.innerHTML = '<div class="list-empty">No scenarios</div>';
        return;
    }
    container.innerHTML = scenarios.map(s => {
        const enabledClass = s.is_enabled ? 'device-online' : 'device-offline';
        const enabledText = s.is_enabled ? 'Enabled' : 'Disabled';
        let details = `Trigger: ${escapeHtml(s.trigger_type)}`;
        if (s.trigger_type === 'schedule' && s.schedule_days) {
            details += ` · ${escapeHtml(s.schedule_days)} ${String(s.schedule_hour||0).padStart(2,'0')}:${String(s.schedule_minute||0).padStart(2,'0')}`;
        }
        details += ` · Action: ${escapeHtml(s.action_type)}`;
        return `
            <div class="list-card">
                <div class="list-info">
                    <div class="editable-title">
                        <span class="title-text" onclick="startEditTitle(this.parentElement)">${escapeHtml(s.name)}</span>
                        <svg class="edit-icon" onclick="startEditTitle(this.parentElement)" viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>
                        <input type="text" class="title-input" value="${escapeHtml(s.name)}" data-type="scenario" data-id="${s.id}" data-original="${escapeHtml(s.name)}" onkeydown="handleTitleKey(event, this)" onblur="handleTitleBlur(this)">
                    </div>
                    <div class="list-details">
                        <span>${details}</span>
                        <span class="${enabledClass}">${enabledText}</span>
                    </div>
                </div>
                <div class="list-actions">
                    <button class="btn btn-small btn-success" onclick="runScenario(${s.id})">Run</button>
                    <button class="btn btn-small btn-toggle" onclick="toggleScenario(${s.id}, ${!s.is_enabled})">${s.is_enabled ? 'Disable' : 'Enable'}</button>
                    <button class="btn btn-small btn-danger" onclick="deleteScenario(${s.id})">Delete</button>
                </div>
            </div>
        `;
    }).join('');
}

async function submitScenario() {
    const name = document.getElementById('scName').value.trim();
    const trigger_type = document.getElementById('scTriggerType').value;
    const action_type = document.getElementById('scActionType').value;
    const action = document.getElementById('scAction').value;
    const device_ieee = document.getElementById('scDevice').value;
    const paramsRaw = document.getElementById('scParams').value.trim();
    const trigger_config_raw = document.getElementById('scTriggerConfig').value.trim();
    const is_enabled = document.getElementById('scEnabled').checked;

    if (!device_ieee) {
        alert('Select a target device');
        return;
    }

    let action_config = { ieee: device_ieee, action, params: {} };
    if (paramsRaw) {
        try {
            action_config.params = JSON.parse(paramsRaw);
        } catch (e) {
            alert('Params must be valid JSON or empty');
            return;
        }
    }

    let trigger_config = null;
    if (trigger_config_raw) {
        try { trigger_config = JSON.parse(trigger_config_raw); } catch (e) {
            alert('Trigger Config must be valid JSON or empty');
            return;
        }
    }

    let schedule_days = null;
    let schedule_hour = null;
    let schedule_minute = null;
    if (trigger_type === 'schedule') {
        schedule_days = Array.from(document.querySelectorAll('.sc-day:checked')).map(cb => cb.value).join(',');
        const timeValue = document.getElementById('scTime').value || '00:00';
        const [h, m] = timeValue.split(':');
        schedule_hour = parseInt(h, 10);
        schedule_minute = parseInt(m, 10);
    }

    const payload = {
        name,
        trigger_type,
        trigger_config: trigger_config ? JSON.stringify(trigger_config) : null,
        action_type,
        action_config: JSON.stringify(action_config),
        schedule_days,
        schedule_hour,
        schedule_minute,
        is_enabled
    };

    try {
        const res = await fetch('/api/scenarios', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            document.getElementById('scenarioForm').reset();
            updateScenarioForm();
            loadScenarios();
        }
    } catch (e) {
        alert('Failed to create scenario');
    }
}

async function deleteScenario(id) {
    if (!confirm('Delete scenario?')) return;
    try {
        await fetch('/api/scenarios/' + id, { method: 'DELETE' });
        loadScenarios();
    } catch (e) {}
}

async function toggleScenario(id, enabled) {
    try {
        await fetch('/api/scenarios/' + id, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_enabled: enabled })
        });
        loadScenarios();
    } catch (e) {}
}

async function runScenario(id) {
    try {
        const res = await fetch('/api/scenarios/' + id + '/trigger', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            logEvent('Scenario ' + id + ' triggered');
        } else {
            logEvent('Scenario trigger failed: ' + (data.error || ''));
        }
    } catch (e) {}
}

function startEditTitle(container) {
    container.classList.add('editing');
    const input = container.querySelector('.title-input');
    input.focus();
    input.select();
}

function handleTitleKey(e, input) {
    if (e.key === 'Enter') {
        e.preventDefault();
        if (titleEditTimeout) { clearTimeout(titleEditTimeout); titleEditTimeout = null; }
        saveTitleEdit(input);
    } else if (e.key === 'Escape') {
        if (titleEditTimeout) { clearTimeout(titleEditTimeout); titleEditTimeout = null; }
        cancelTitleEdit(input);
    }
}

function handleTitleBlur(input) {
    // Delay slightly to allow click-outside handling if needed
    titleEditTimeout = setTimeout(() => {
        titleEditTimeout = null;
        saveTitleEdit(input);
    }, 100);
}

function cancelTitleEdit(input) {
    input.value = input.dataset.original;
    input.parentElement.classList.remove('editing');
}

async function saveTitleEdit(input) {
    if (!input.parentElement.classList.contains('editing')) return;
    const newName = input.value.trim();
    const container = input.parentElement;
    container.classList.remove('editing');
    if (!newName || newName === input.dataset.original) {
        input.value = input.dataset.original;
        return;
    }
    // Optimistically update UI
    const textSpan = container.querySelector('.title-text');
    if (textSpan) textSpan.textContent = newName;
    input.dataset.original = newName;

    const type = input.dataset.type;
    if (type === 'device') {
        const ieee = input.dataset.ieee;
        try {
            const res = await fetch(`/api/devices/${ieee}/rename`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newName })
            });
            if (res.ok) {
                await loadDevices();
            } else {
                // Revert on failure
                if (textSpan) textSpan.textContent = input.dataset.original;
            }
        } catch (e) {
            if (textSpan) textSpan.textContent = input.dataset.original;
        }
    } else if (type === 'scenario') {
        const id = input.dataset.id;
        try {
            const res = await fetch('/api/scenarios/' + id, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newName })
            });
            if (res.ok) {
                await loadScenarios();
            } else {
                if (textSpan) textSpan.textContent = input.dataset.original;
            }
        } catch (e) {
            if (textSpan) textSpan.textContent = input.dataset.original;
        }
    }
}

// === Utils ===

function logEvent(text) {
    const log = document.getElementById('eventLog');
    if (log.children.length === 1 && log.children[0].textContent === 'Waiting for connection...') {
        log.innerHTML = '';
    }
    const div = document.createElement('div');
    div.className = 'event-item';
    const t = new Date().toLocaleTimeString();
    div.innerHTML = `<span class="event-time">[${t}]</span> ${escapeHtml(text)}`;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showPage(name) {
    document.querySelectorAll('.page').forEach(el => el.style.display = 'none');
    const pageEl = document.getElementById(name + 'Page');
    if (pageEl) pageEl.style.display = 'block';
    document.querySelectorAll('.nav-link').forEach(el => el.classList.remove('active'));
    const link = document.querySelector('.nav-link[data-page="' + name + '"]');
    if (link) link.classList.add('active');
    if (name === 'scenarios') { updateScenarioForm(); loadScenarios(); }
}

async function restoreConnection() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        if (data.connected && data.port) {
            const select = document.getElementById('portSelect');
            if (select) select.value = data.port;
            onConnected(data.port);
        }
    } catch (e) {
        // Not connected or server error — stay disconnected
    }
}

// Initialization
(async function init() {
    await refreshPorts();
    await restoreConnection();
})();
