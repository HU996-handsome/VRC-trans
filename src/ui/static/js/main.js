/* VRC-Translator Web UI JavaScript */
(function() {
    'use strict';

    const API_BASE = '';

    // ── Tab Navigation ──────────────────────────────────────────
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
        });
    });

    // ── Subtitle Polling ────────────────────────────────────────
    async function pollSubtitles() {
        try {
            const r = await fetch(API_BASE + '/api/subtitles');
            const d = await r.json();

            setText('outgoing-original', d.outgoing.original || '-');
            setText('outgoing-translated', d.outgoing.translated || '-');
            setText('incoming-original', d.incoming.original || '-');
            setText('incoming-translated', d.incoming.translated || '-');

            const dot = document.getElementById('status-indicator');
            dot.className = 'status-dot' + (d.status.is_listening ? ' active' : '');

            const muteBtn = document.getElementById('btn-toggle-mute');
            muteBtn.className = 'btn btn-sm' + (d.status.is_muted ? ' active' : '');
            muteBtn.textContent = d.status.is_muted ? '🔊 开麦' : '🔇 闭麦';

            const revBtn = document.getElementById('btn-toggle-reverse');
            revBtn.className = 'btn btn-sm' + (d.status.is_reverse_active ? ' active' : '');
        } catch (e) {}
    }

    function setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    setInterval(pollSubtitles, 500);
    pollSubtitles();

    // ── Control Buttons ─────────────────────────────────────────
    document.getElementById('btn-toggle-mute').addEventListener('click', async () => {
        await fetch(API_BASE + '/api/toggle-mute', { method: 'POST' });
    });

    document.getElementById('btn-toggle-reverse').addEventListener('click', async () => {
        await fetch(API_BASE + '/api/toggle-reverse', { method: 'POST' });
    });

    // ── Manual Text Input ───────────────────────────────────────
    const textInput = document.getElementById('manual-text');
    const sendBtn = document.getElementById('btn-send-text');

    async function sendText() {
        const text = textInput.value.trim();
        if (!text) return;
        try {
            await fetch(API_BASE + '/api/send-text', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text }),
            });
            textInput.value = '';
        } catch (e) {
            console.error('Send text error:', e);
        }
    }

    sendBtn.addEventListener('click', sendText);
    textInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') sendText();
    });

    // ── VRChat Detection & Pipeline ─────────────────────────────
    let vrcCheckTimer = null;
    let pipelineActive = false;

    async function checkVRChat() {
        try {
            const r = await fetch(API_BASE + '/api/vrchat/status');
            const d = await r.json();
            const panel = document.getElementById('startup-panel');
            const icon = document.getElementById('vrc-status-icon');
            const title = document.getElementById('vrc-status-title');
            const detail = document.getElementById('vrc-status-detail');
            const btnStart = document.getElementById('btn-start-pipeline');
            const btnStop = document.getElementById('btn-stop-pipeline');

            if (d.vrchat_running) {
                panel.className = 'startup-panel vrc-detected' + (pipelineActive ? ' pipeline-active' : '');
                icon.textContent = '🎮';
                title.textContent = 'VRChat 已检测到';
                detail.textContent = d.message;
                btnStart.disabled = pipelineActive;
            } else {
                panel.className = 'startup-panel';
                icon.textContent = '🎮';
                title.textContent = 'VRChat 未检测到';
                detail.textContent = '未检测到 VRChat，仍可启动翻译（请稍后打开 VRChat）';
                btnStart.disabled = pipelineActive;
            }
        } catch (e) {}
    }

    async function checkPipelineStatus() {
        try {
            const r = await fetch(API_BASE + '/api/status');
            const d = await r.json();
            pipelineActive = d.pipeline_active || false;
            const btnStart = document.getElementById('btn-start-pipeline');
            const btnStop = document.getElementById('btn-stop-pipeline');
            btnStart.style.display = pipelineActive ? 'none' : '';
            btnStop.style.display = pipelineActive ? '' : 'none';
            btnStart.disabled = pipelineActive;
            checkVRChat();
        } catch (e) {}
    }

    document.getElementById('btn-start-pipeline').addEventListener('click', async () => {
        const btn = document.getElementById('btn-start-pipeline');
        btn.textContent = '启动中...';
        btn.disabled = true;
        try {
            const r = await fetch(API_BASE + '/api/pipeline/start', { method: 'POST' });
            const d = await r.json();
            if (d.ok) {
                pipelineActive = true;
                document.getElementById('btn-start-pipeline').style.display = 'none';
                document.getElementById('btn-stop-pipeline').style.display = '';
                document.getElementById('startup-panel').className = 'startup-panel pipeline-active';
                document.getElementById('vrc-status-title').textContent = '翻译运行中';
                document.getElementById('vrc-status-detail').textContent = '语音识别和翻译已启动';
            } else {
                alert(d.error || '启动失败');
            }
        } catch (e) {
            alert('启动失败: ' + e.message);
        }
        btn.innerHTML = '<span class="btn-icon">▶</span> 启动翻译';
        btn.disabled = false;
    });

    document.getElementById('btn-stop-pipeline').addEventListener('click', async () => {
        try {
            await fetch(API_BASE + '/api/pipeline/stop', { method: 'POST' });
            pipelineActive = false;
            document.getElementById('btn-start-pipeline').style.display = '';
            document.getElementById('btn-stop-pipeline').style.display = 'none';
            checkVRChat();
        } catch (e) {}
    });

    document.getElementById('btn-refresh-vrc').addEventListener('click', checkVRChat);

    // Auto-check VRChat every 5 seconds
    checkPipelineStatus();
    vrcCheckTimer = setInterval(checkVRChat, 5000);

    // Auto-start pipeline if setting enabled
    setTimeout(async () => {
        if (!pipelineActive) {
            try {
                const sr = await fetch(API_BASE + '/api/settings');
                const settings = await sr.json();
                if (!settings.ui || !settings.ui.auto_start_pipeline) return;

                const r = await fetch(API_BASE + '/api/status');
                const d = await r.json();
                if (!d.pipeline_active) {
                    console.log('[Auto] Starting pipeline...');
                    const pr = await fetch(API_BASE + '/api/pipeline/start', { method: 'POST' });
                    const pd = await pr.json();
                    console.log('[Auto] Result:', pd);
                    if (pd.ok) {
                        pipelineActive = true;
                        document.getElementById('btn-start-pipeline').style.display = 'none';
                        document.getElementById('btn-stop-pipeline').style.display = '';
                        document.getElementById('startup-panel').className = 'startup-panel pipeline-active';
                        document.getElementById('vrc-status-title').textContent = '翻译运行中';
                        document.getElementById('vrc-status-detail').textContent = '语音识别和翻译已启动';
                    }
                }
            } catch (e) {
                console.log('[Auto] Auto-start failed:', e);
            }
        }
    }, 2000);

    // ── API Keys ────────────────────────────────────────────────
    function toggleVis(btn) {
        const input = btn.previousElementSibling;
        if (input.type === 'password') {
            input.type = 'text';
            btn.textContent = '🙈';
        } else {
            input.type = 'password';
            btn.textContent = '👁';
        }
    }
    window.toggleVis = toggleVis;

    async function loadKeys() {
        try {
            const r = await fetch(API_BASE + '/api/keys');
            const keys = await r.json();
            if (keys.DASHSCOPE_API_KEY) document.getElementById('api-key-dashscope').placeholder = keys.DASHSCOPE_API_KEY;
            if (keys.DEEPL_API_KEY) document.getElementById('api-key-deepl').placeholder = keys.DEEPL_API_KEY;
            if (keys.OPENROUTER_API_KEY) document.getElementById('api-key-openrouter').placeholder = keys.OPENROUTER_API_KEY;
            if (keys.SONIOX_API_KEY) document.getElementById('api-key-soniox').placeholder = keys.SONIOX_API_KEY;
        } catch (e) {}
    }

    document.getElementById('btn-save-keys').addEventListener('click', async () => {
        const status = document.getElementById('keys-save-status');
        status.textContent = '保存中...';
        status.style.color = '#4fc3f7';
        const data = {
            dashscope: document.getElementById('api-key-dashscope').value,
            deepl: document.getElementById('api-key-deepl').value,
            openrouter: document.getElementById('api-key-openrouter').value,
            soniox: document.getElementById('api-key-soniox').value,
        };
        try {
            const r = await fetch(API_BASE + '/api/keys', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data),
            });
            const result = await r.json();
            if (result.ok) {
                status.textContent = '已保存到 config/.env ✓';
                status.style.color = '#81c784';
                // Clear inputs
                ['api-key-dashscope','api-key-deepl','api-key-openrouter','api-key-soniox'].forEach(id => {
                    document.getElementById(id).value = '';
                });
                loadKeys();
            }
        } catch (e) {
            status.textContent = '保存失败';
            status.style.color = '#f44336';
        }
        setTimeout(() => status.textContent = '', 3000);
    });

    // ── Settings ────────────────────────────────────────────────
    async function loadSettings() {
        try {
            const r = await fetch(API_BASE + '/api/settings');
            const s = await r.json();

            // ASR
            setVal('asr-backend', s.asr.backend);
            setVal('asr-language', s.asr.language_hint);
            toggleLocalModelSection(s.asr.backend);

            // Translation
            setVal('translation-backend', s.translation.primary_backend);
            setVal('target-language', s.translation.target_language);

            // Reverse
            setChecked('reverse-enabled', s.reverse_translation.enabled);
            setVal('reverse-target-language', s.reverse_translation.target_language);
            setChecked('self-suppress', s.reverse_translation.self_suppress);
            setVal('loopback-device', s.reverse_translation.loopback_device);

            // Sync header buttons with settings state
            const muteBtn = document.getElementById('btn-toggle-mute');
            muteBtn.textContent = s.osc.mic_control_enabled ? '🔇 闭麦' : '🔊 开麦';

            const revBtn = document.getElementById('btn-toggle-reverse');
            revBtn.className = 'btn btn-sm' + (s.reverse_translation.enabled ? ' active' : '');

            // Display
            setChecked('show-partial', s.display.show_partial_results);
            setChecked('ja-furigana', s.display.enable_ja_furigana);
            setChecked('zh-pinyin', s.display.enable_zh_pinyin);
            setVal('text-style', s.display.text_fancy_style);

            // OSC
            setChecked('osc-enabled', s.osc.enabled);
            setVal('osc-send-port', s.osc.send_port);
            setVal('osc-listen-port', s.osc.listen_port);
            setChecked('mic-control', s.osc.mic_control_enabled);

            // UI
            setChecked('auto-start-pipeline', s.ui.auto_start_pipeline);
        } catch (e) {
            console.error('Load settings error:', e);
        }
    }

    function setVal(id, val) {
        const el = document.getElementById(id);
        if (el) el.value = val || '';
    }

    function setChecked(id, val) {
        const el = document.getElementById(id);
        if (el) el.checked = !!val;
    }

    function getVal(id) {
        const el = document.getElementById(id);
        return el ? el.value : '';
    }

    function getChecked(id) {
        const el = document.getElementById(id);
        return el ? el.checked : false;
    }

    // Show/hide local model section
    document.getElementById('asr-backend').addEventListener('change', (e) => {
        toggleLocalModelSection(e.target.value);
    });

    function toggleLocalModelSection(backend) {
        const section = document.getElementById('local-model-section');
        section.style.display = backend.startsWith('local_') ? 'block' : 'none';
    }

    // Save settings
    document.getElementById('btn-save-settings').addEventListener('click', async () => {
        const settings = {
            asr: {
                backend: getVal('asr-backend'),
                language_hint: getVal('asr-language'),
            },
            translation: {
                primary_backend: getVal('translation-backend'),
                target_language: getVal('target-language'),
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
            await fetch(API_BASE + '/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings),
            });
            const status = document.getElementById('save-status');
            status.textContent = '已保存 ✓';
            setTimeout(() => status.textContent = '', 2000);
        } catch (e) {
            console.error('Save settings error:', e);
        }
    });

    // ── Device Lists ────────────────────────────────────────────
    async function loadDevices() {
        try {
            const r = await fetch(API_BASE + '/api/asr/devices');
            const devices = await r.json();
            const sel = document.getElementById('mic-device');
            sel.innerHTML = '<option value="">默认设备</option>';
            devices.forEach(d => {
                sel.innerHTML += `<option value="${d.index}">${d.name}</option>`;
            });
        } catch (e) {}

        try {
            const r = await fetch(API_BASE + '/api/asr/loopback-devices');
            const devices = await r.json();
            const sel = document.getElementById('loopback-device');
            sel.innerHTML = '<option value="">自动检测</option>';
            devices.forEach(d => {
                sel.innerHTML += `<option value="${d.name}">${d.name}</option>`;
            });
        } catch (e) {}
    }

    document.getElementById('btn-refresh-devices').addEventListener('click', loadDevices);
    document.getElementById('btn-refresh-loopback').addEventListener('click', loadDevices);

    // ── Dictionary ──────────────────────────────────────────────
    document.getElementById('btn-update-dict').addEventListener('click', async () => {
        const status = document.getElementById('dict-status');
        status.textContent = '更新中...';
        try {
            const r = await fetch(API_BASE + '/api/dictionary/update', { method: 'POST' });
            const d = await r.json();
            status.textContent = d.ok ? '已更新 ✓' : '更新失败';
        } catch (e) {
            status.textContent = '更新失败';
        }
    });

    document.getElementById('btn-add-rule').addEventListener('click', async () => {
        const pattern = document.getElementById('dict-pattern').value.trim();
        const replacement = document.getElementById('dict-replacement').value.trim();
        if (!pattern || !replacement) return;
        try {
            await fetch(API_BASE + '/api/dictionary/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ patterns: [pattern], replacement }),
            });
            document.getElementById('dict-pattern').value = '';
            document.getElementById('dict-replacement').value = '';
        } catch (e) {}
    });

    // ── Model Download ──────────────────────────────────────────
    document.getElementById('btn-download-model').addEventListener('click', async () => {
        const status = document.getElementById('model-status');
        status.textContent = '下载中...';
        try {
            await fetch(API_BASE + '/api/models/sensevoice/download', { method: 'POST' });
            status.textContent = '下载已开始, 请稍候...';
        } catch (e) {
            status.textContent = '下载失败';
        }
    });

    // ── Init ────────────────────────────────────────────────────
    loadDevices().then(() => loadSettings());
    loadKeys();
})();
