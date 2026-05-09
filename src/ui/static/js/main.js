/* VRC-Translator Web UI */
(function () {
    'use strict';

    const API = '';

    // ── State ─────────────────────────────────────────────────
    let pipelineActive = false;
    let vrchatRunning = false;

    // ── DOM Refs ──────────────────────────────────────────────
    const $ = (id) => document.getElementById(id);
    const btnStart = $('btn-start');
    const btnStop = $('btn-stop');
    const btnMute = $('btn-mute');
    const btnReverse = $('btn-reverse');
    const btnSettings = $('btn-settings');
    const btnCloseDrawer = $('btn-close-drawer');
    const drawer = $('settings-drawer');
    const overlay = $('drawer-overlay');
    const statusChip = $('status-chip');
    const statusDot = statusChip.querySelector('.status-dot');
    const statusText = statusChip.querySelector('.status-text');
    const gameChip = $('game-chip');
    const gameText = $('game-text');

    // ── Drawer ────────────────────────────────────────────────
    function openDrawer() {
        drawer.classList.add('open');
        overlay.classList.add('open');
    }

    function closeDrawer() {
        drawer.classList.remove('open');
        overlay.classList.remove('open');
    }

    btnSettings.addEventListener('click', openDrawer);
    btnCloseDrawer.addEventListener('click', closeDrawer);
    overlay.addEventListener('click', closeDrawer);

    // Drawer tabs
    document.querySelectorAll('.drawer-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.drawer-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.drawer-content').forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            $('tab-' + tab.dataset.tab).classList.add('active');
        });
    });

    // ── Pipeline Control ──────────────────────────────────────
    async function startPipeline() {
        btnStart.disabled = true;
        btnStart.innerHTML = '<span class="spinner"></span> 启动中';
        try {
            const r = await fetch(API + '/api/pipeline/start', { method: 'POST' });
            const d = await r.json();
            if (d.ok) {
                setPipelineState(true);
            } else {
                alert(d.error || '启动失败');
            }
        } catch (e) {
            alert('启动失败: ' + e.message);
        }
        btnStart.disabled = false;
        btnStart.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg> 启动';
    }

    async function stopPipeline() {
        try {
            await fetch(API + '/api/pipeline/stop', { method: 'POST' });
            setPipelineState(false);
        } catch (e) {}
    }

    function setPipelineState(active) {
        pipelineActive = active;
        btnStart.style.display = active ? 'none' : '';
        btnStop.style.display = active ? '' : 'none';

        if (active) {
            statusDot.classList.add('active');
            statusText.textContent = '运行中';
        } else {
            statusDot.classList.remove('active');
            statusText.textContent = '离线';
        }
    }

    btnStart.addEventListener('click', startPipeline);
    btnStop.addEventListener('click', stopPipeline);

    // ── Mute & Reverse ────────────────────────────────────────
    btnMute.addEventListener('click', async () => {
        await fetch(API + '/api/toggle-mute', { method: 'POST' });
    });

    btnReverse.addEventListener('click', async () => {
        await fetch(API + '/api/toggle-reverse', { method: 'POST' });
    });

    // ── Subtitle Polling ──────────────────────────────────────
    async function poll() {
        try {
            const r = await fetch(API + '/api/subtitles');
            const d = await r.json();

            setText('outgoing-original', d.outgoing.original || '-');
            setText('outgoing-translated', d.outgoing.translated || '-');
            setText('incoming-original', d.incoming.original || '-');
            setText('incoming-translated', d.incoming.translated || '-');

            // Mute button state
            if (d.status.is_muted) {
                btnMute.classList.add('active');
                $('mute-text').textContent = '闭麦';
            } else {
                btnMute.classList.remove('active');
                $('mute-text').textContent = '开麦';
            }

            // Reverse button state
            if (d.status.is_reverse_active) {
                btnReverse.classList.add('active');
            } else {
                btnReverse.classList.remove('active');
            }
        } catch (e) {}
    }

    function setText(id, text) {
        const el = $(id);
        if (el) el.textContent = text;
    }

    setInterval(poll, 500);
    poll();

    // ── Manual Text Input ─────────────────────────────────────
    const textInput = $('manual-text');
    const sendBtn = $('btn-send');

    async function sendText() {
        const text = textInput.value.trim();
        if (!text) return;
        try {
            await fetch(API + '/api/send-text', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text }),
            });
            textInput.value = '';
        } catch (e) {}
    }

    sendBtn.addEventListener('click', sendText);
    textInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') sendText();
    });

    // ── Status Check ──────────────────────────────────────────
    async function checkStatus() {
        try {
            const r = await fetch(API + '/api/status');
            const d = await r.json();
            setPipelineState(d.pipeline_active || false);

            // Update game status
            if (d.vrchat) {
                vrchatRunning = d.vrchat.vrchat_running;
                if (vrchatRunning) {
                    gameChip.classList.add('active');
                    gameText.textContent = 'VRChat';
                } else {
                    gameChip.classList.remove('active');
                    gameText.textContent = '未检测';
                }
            }

            // Disable start button if VRChat not running
            if (!pipelineActive) {
                btnStart.disabled = !vrchatRunning;
                btnStart.title = vrchatRunning ? '启动翻译' : '请先启动 VRChat';
            }
        } catch (e) {}
    }

    checkStatus();
    setInterval(checkStatus, 5000);

    // ── Auto-start ────────────────────────────────────────────
    setTimeout(async () => {
        if (pipelineActive) return;
        try {
            const sr = await fetch(API + '/api/settings');
            const s = await sr.json();
            if (!s.ui || !s.ui.auto_start_pipeline) return;

            const r = await fetch(API + '/api/status');
            const d = await r.json();
            if (!d.pipeline_active) {
                const pr = await fetch(API + '/api/pipeline/start', { method: 'POST' });
                const pd = await pr.json();
                if (pd.ok) setPipelineState(true);
            }
        } catch (e) {}
    }, 2000);

    // ── API Keys ──────────────────────────────────────────────
    window.toggleVis = function (btn) {
        const input = btn.closest('.input-row').querySelector('input');
        if (input.type === 'password') {
            input.type = 'text';
        } else {
            input.type = 'password';
        }
    };

    async function loadKeys() {
        try {
            const r = await fetch(API + '/api/keys');
            const keys = await r.json();
            if (keys.DASHSCOPE_API_KEY) $('api-key-dashscope').placeholder = keys.DASHSCOPE_API_KEY;
            if (keys.DEEPL_API_KEY) $('api-key-deepl').placeholder = keys.DEEPL_API_KEY;
            if (keys.OPENROUTER_API_KEY) $('api-key-openrouter').placeholder = keys.OPENROUTER_API_KEY;
        } catch (e) {}
    }

    $('btn-save-keys').addEventListener('click', async () => {
        const status = $('keys-save-status');
        status.textContent = '保存中...';
        status.style.color = 'var(--accent)';
        const data = {
            dashscope: $('api-key-dashscope').value,
            deepl: $('api-key-deepl').value,
            openrouter: $('api-key-openrouter').value,
        };
        try {
            const r = await fetch(API + '/api/keys', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            const result = await r.json();
            if (result.ok) {
                status.textContent = '已保存';
                status.style.color = 'var(--green)';
                ['api-key-dashscope', 'api-key-deepl', 'api-key-openrouter'].forEach(id => {
                    $(id).value = '';
                });
                loadKeys();
            }
        } catch (e) {
            status.textContent = '保存失败';
            status.style.color = 'var(--red)';
        }
        setTimeout(() => status.textContent = '', 3000);
    });

    // ── Settings ──────────────────────────────────────────────
    function setVal(id, val) {
        const el = $(id);
        if (el) el.value = val || '';
    }

    function setChecked(id, val) {
        const el = $(id);
        if (el) el.checked = !!val;
    }

    function getVal(id) {
        const el = $(id);
        return el ? el.value : '';
    }

    function getChecked(id) {
        const el = $(id);
        return el ? el.checked : false;
    }

    async function loadSettings() {
        try {
            const r = await fetch(API + '/api/settings');
            const s = await r.json();

            setVal('asr-backend', s.asr.backend);
            setVal('asr-language', s.asr.language_hint);
            setVal('translation-backend', s.translation.primary_backend);
            setVal('target-language', s.translation.target_language);

            setChecked('reverse-enabled', s.reverse_translation.enabled);
            setVal('reverse-target-language', s.reverse_translation.target_language);
            setChecked('self-suppress', s.reverse_translation.self_suppress);
            setVal('loopback-device', s.reverse_translation.loopback_device);

            setChecked('show-partial', s.display.show_partial_results);
            setChecked('dual-line', s.translation.dual_line);
            setChecked('ja-furigana', s.display.enable_ja_furigana);
            setChecked('zh-pinyin', s.display.enable_zh_pinyin);
            setVal('text-style', s.display.text_fancy_style);

            setChecked('osc-enabled', s.osc.enabled);
            setVal('osc-send-port', s.osc.send_port);
            setVal('osc-listen-port', s.osc.listen_port);
            setChecked('mic-control', s.osc.mic_control_enabled);
            setChecked('auto-start-pipeline', s.ui.auto_start_pipeline);
        } catch (e) {}
    }

    $('btn-save-settings').addEventListener('click', async () => {
        const settings = {
            asr: {
                backend: getVal('asr-backend'),
                language_hint: getVal('asr-language'),
            },
            translation: {
                primary_backend: getVal('translation-backend'),
                target_language: getVal('target-language'),
                dual_line: getChecked('dual-line'),
            },
            reverse_translation: {
                enabled: getChecked('reverse-enabled'),
                target_language: getVal('reverse-target-language'),
                self_suppress: getChecked('self-suppress'),
                loopback_device: getVal('loopback-device'),
            },
            display: {
                show_partial_results: getChecked('show-partial'),
                enable_ja_furigana: getChecked('ja-furigana'),
                enable_zh_pinyin: getChecked('zh-pinyin'),
                text_fancy_style: getVal('text-style'),
            },
            osc: {
                enabled: getChecked('osc-enabled'),
                send_port: parseInt(getVal('osc-send-port')) || 9000,
                listen_port: parseInt(getVal('osc-listen-port')) || 9001,
                mic_control_enabled: getChecked('mic-control'),
            },
            ui: {
                auto_start_pipeline: getChecked('auto-start-pipeline'),
            },
        };

        try {
            await fetch(API + '/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings),
            });
            const status = $('save-status');
            status.textContent = '已保存';
            setTimeout(() => status.textContent = '', 2000);
        } catch (e) {}
    });

    // ── Devices ───────────────────────────────────────────────
    async function loadDevices() {
        try {
            const r = await fetch(API + '/api/asr/devices');
            const devices = await r.json();
            const sel = $('mic-device');
            sel.innerHTML = '<option value="">默认设备</option>';
            devices.forEach(d => {
                sel.innerHTML += `<option value="${d.index}">${d.name}</option>`;
            });
        } catch (e) {}

        try {
            const r = await fetch(API + '/api/asr/loopback-devices');
            const devices = await r.json();
            const sel = $('loopback-device');
            sel.innerHTML = '<option value="">自动检测</option>';
            devices.forEach(d => {
                sel.innerHTML += `<option value="${d.name}">${d.name}</option>`;
            });
        } catch (e) {}
    }

    $('btn-refresh-devices').addEventListener('click', loadDevices);
    $('btn-refresh-loopback').addEventListener('click', loadDevices);

    // ── Init ──────────────────────────────────────────────────
    loadDevices().then(() => loadSettings());
    loadKeys();
})();
