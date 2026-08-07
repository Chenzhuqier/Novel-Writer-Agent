/**
 * 小说写作 Agent v0.2 前端逻辑
 *
 * 改进点：
 * - 流式输出支持（SSE EventSource）
 * - 成本统计面板
 * - 版本控制面板
 * - 人工确认步骤
 * - 实时日志
 */

// ============================================================
// 全局状态
// ============================================================

const API_BASE = '';
let pollInterval = null;
let currentChapterView = 'draft'; // draft | polished | check
let eventSource = null;

// ============================================================
// API 调用封装
// ============================================================

async function apiCall(endpoint, method = 'GET', body = null) {
    const options = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body) options.body = JSON.stringify(body);

    const res = await fetch(`${API_BASE}/api${endpoint}`, options);
    const data = await res.json();

    if (!res.ok) {
        throw new Error(data.error || `API 错误: ${res.status}`);
    }
    return data;
}

// ============================================================
// 步骤控制
// ============================================================

async function startProject() {
    const premise = document.getElementById('premise').value.trim();
    const genre = document.getElementById('genre').value;

    if (!premise) {
        alert('请输入创意描述！');
        return;
    }

    try {
        await apiCall('/start', 'POST', { premise, genre });
        addLog('success', `🚀 项目已启动 | 类型:${genre || '自动'} | 创意:${premise.slice(0, 50)}...`);

        // 启用后续步骤
        document.getElementById('btn-build-world').disabled = false;
        document.getElementById('btn-start').textContent = '✅ 已初始化';
        document.getElementById('btn-start').disabled = true;

        updateStatus('已初始化', '请点击「构建世界观」');
    } catch (err) {
        addLog('error', err.message);
    }
}

async function buildWorld() {
    setRunning(true);
    addLog('info', '🌍 正在构建世界观...');

    try {
        await apiCall('/build-world', 'POST');
        startPolling();
    } catch (err) {
        setRunning(false);
        addLog('error', err.message);
    }
}

async function generateOutline() {
    const chapterCount = parseInt(document.getElementById('chapter-count').value) || 10;
    setRunning(true);
    addLog('info', `📋 正在生成大纲 (${chapterCount} 章)...`);

    try {
        await apiCall('/generate-outline', 'POST', { chapter_count: chapterCount });
        startPolling();
    } catch (err) {
        setRunning(false);
        addLog('error', err.message);
    }
}

async function writeChapter() {
    const num = parseInt(document.getElementById('single-chapter').value) || 1;
    await doWrite(num);
}

async function writeAll() {
    if (!confirm('确定要写作全部章节吗？这可能需要较长时间。')) return;
    setRunning(true);
    addLog('info', '📝 开始逐章写作...');

    try {
        await apiCall('/write-all', 'POST');
        startPolling();
    } catch (err) {
        setRunning(false);
        addLog('error', err.message);
    }
}

async function doWrite(chapterNum) {
    const useStreaming = document.getElementById('use-streaming').checked;

    setRunning(true);
    addLog('info', `✍️ 开始写第 ${chapterNum} 章${useStreaming ? '（流式模式）' : ''}...`);

    try {
        if (useStreaming) {
            streamWrite(chapterNum);
        } else {
            await apiCall(`/write-chapter/${chapterNum}`, 'POST');
            startPolling();
        }
    } catch (err) {
        setRunning(false);
        addLog('error', err.message);
    }
}

// ============================================================
// 流式输出（SSE）
// ============================================================

function streamWrite(chapterNum) {
    if (eventSource) eventSource.close();

    eventSource = new EventSource(`${API_BASE}/api/stream-write/${chapterNum}`);

    // 清空并显示流式内容
    switchTab('chapter');
    document.getElementById('chapter-output').textContent = '';

    eventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);

        switch (data.type) {
            case 'start':
                addLog('info', `✍️ [流式] 第 ${data.chapter} 章开始生成...`);
                break;

            case 'chunk':
                // 实时追加内容
                const output = document.getElementById('chapter-output');
                output.textContent += data.content;
                // 自动滚动到底部
                output.scrollTop = output.scrollHeight;
                break;

            case 'done':
                addLog('success', `✅ [流式] 第 ${chapterNum} 章完成！共 ${data.word_count} 字`);
                eventSource.close();
                refreshChapterList();
                loadChapter(chapterNum);
                setRunning(false);
                break;

            case 'error':
                addLog('error', `[流式] 错误: ${data.message}`);
                eventSource.close();
                setRunning(false);
                break;
        }
    };

    eventSource.onerror = function() {
        addLog('error', '[流式] 连接中断');
        eventSource.close();
        setRunning(false);
    };
}

// ============================================================
// 人工确认
// ============================================================

async function confirmStep(step) {
    try {
        await apiCall('/confirm', 'POST', { step });
        addLog('success', `✅ 已确认 ${step === 'world' ? '世界观' : step === 'outline' ? '大纲' : '章节'}`);

        // 隐藏确认按钮，启用下一步
        if (step === 'world') {
            document.getElementById('btn-confirm-world').style.display = 'none';
            document.getElementById('btn-outline').disabled = false;
        } else if (step === 'outline') {
            document.getElementById('btn-confirm-outline').style.display = 'none';
            document.getElementById('btn-write-all').disabled = false;
            document.getElementById('btn-write-chapter').disabled = false;
        }
    } catch (err) {
        addLog('error', err.message);
    }
}

// ============================================================
// 轮询状态
// ============================================================

function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(pollStatus, 1500);
    pollStatus(); // 立即执行一次
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

async function pollStatus() {
    try {
        const status = await apiCall('/status');
        updateUI(status);

        if (!status.is_running) {
            stopPolling();
            setRunning(false);
            onStepComplete(status);
        }
    } catch (err) {
        console.warn('轮询失败:', err.message);
    }
}

function updateUI(status) {
    document.getElementById('current-step').textContent = formatStep(status.step);
    document.getElementById('status-message').textContent = status.message;

    // 进度
    const total = status.total_chapters || 0;
    const written = status.written_chapters?.length || 0;
    if (total > 0) {
        const pct = Math.round((written / total) * 100);
        document.getElementById('progress').textContent = `${written}/${total} (${pct}%)`;
        document.getElementById('progress-container').style.display = 'block';
        document.getElementById('progress-bar').style.width = `${pct}%`;
    }

    // Bible 版本
    if (status.bible_version !== undefined) {
        document.getElementById('bible-version').textContent = `v${status.bible_version}`;
    }

    // 更新日志
    if (status.logs?.length) {
        const container = document.getElementById('log-container');
        const existingLogs = container.querySelectorAll('.log-entry').length;
        if (status.logs.length > existingLogs) {
            status.logs.slice(existingLogs).forEach(msg => {
                addLog('info', msg, false); // 不重复添加
            });
        }
    }
}

function onStepComplete(status) {
    const step = status.step;

    if (step === 'world_built' || step.includes('world')) {
        addLog('success', '🌍 世界观构建完成！');
        document.getElementById('btn-confirm-world').style.display = 'inline-flex';
        loadWorldData();
    } else if (step === 'outline_generated' || step.includes('outline')) {
        addLog('success', '📋 大纲生成完成！');
        document.getElementById('btn-confirm-outline').style.display = 'inline-flex';
        loadOutlineData();
    } else if (step === 'chapter_done' || step === 'done') {
        addLog('success', '✍️ 章节写作完成！');
        refreshChapterList();
        if (status.current_chapter) {
            loadChapter(status.current_chapter);
        }
    } else if (step === 'error') {
        addLog('error', `❌ 发生错误: ${status.message}`);
    }

    // 启用导出按钮
    if (status.written_chapters?.length > 0) {
        document.getElementById('btn-export').disabled = false;
    }
}

// ============================================================
// 数据加载
// ============================================================

async function loadWorldData() {
    try {
        const bible = await apiCall('/bible');
        document.getElementById('world-output').textContent = JSON.stringify(bible, null, 2);
        document.getElementById('bible-output').textContent = JSON.stringify(bible, null, 2);
    } catch (err) {
        document.getElementById('world-output').textContent = '加载失败: ' + err.message;
    }
}

async function loadOutlineData() {
    try {
        const outline = await apiCall('/outline');
        document.getElementById('outline-output').textContent = JSON.stringify(outline, null, 2);
    } catch (err) {
        document.getElementById('outline-output').textContent = '加载失败: ' + err.message;
    }
}

function refreshChapterList() {
    const select = document.getElementById('chapter-select');
    select.innerHTML = '<option value="">选择章节...</option>';
    // 通过状态 API 获取已写章节列表
    apiCall('/status').then(status => {
        (status.written_chapters || []).forEach(num => {
            const opt = document.createElement('option');
            opt.value = num;
            opt.textContent = `第 ${num} 章`;
            select.appendChild(opt);
        });
    }).catch(() => {});
}

async function loadChapter(num) {
    if (!num) return;

    try {
        const ch = await apiCall(`/chapter/${num}`);
        window._currentChapterData = ch;

        // 显示元信息
        const metaEl = document.getElementById('chapter-meta');
        let meta = [];
        if (ch.retry_count > 0) meta.push(`重写#${ch.retry_count}`);
        if (ch.check_report?.overall_quality_score) {
            meta.push(`评分: ${ch.check_report.overall_quality_score}`);
        }
        metaEl.textContent = meta.join(' | ') || '';

        // 根据当前视图显示内容
        showChapterContent(ch);
    } catch (err) {
        document.getElementById('chapter-output').textContent = '加载失败: ' + err.message;
    }
}

function showChapterContent(ch) {
    const el = document.getElementById('chapter-output');

    switch (currentChapterView) {
        case 'draft':
            el.textContent = ch.draft || '(无初稿)';
            break;
        case 'polished':
            el.textContent = ch.polished || '(无润色稿)';
            break;
        case 'check':
            el.textContent = ch.check_report
                ? JSON.stringify(ch.check_report, null, 2)
                : '(无检查报告)';
            break;
    }
}

function toggleChapterView(view) {
    currentChapterView = view;

    // 更新按钮状态
    document.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.classList.toggle('active', false);
    });
    event.target.classList.add('active');

    // 刷新显示
    if (window._currentChapterData) {
        showChapterContent(window._currentChapterData);
    }
}

// ============================================================
// Tab 切换
// ============================================================

function switchTab(tabName) {
    // 更新按钮状态
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName + '-tab');
    });

    // 更新内容区域
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === tabName + '-tab');
    });
}

// ============================================================
// 成本统计
// ============================================================

async function showCostPanel() {
    document.getElementById('cost-modal').style.display = 'flex';

    try {
        const data = await apiCall('/cost');
        renderCostData(data);
    } catch (err) {
        document.getElementById('cost-body').innerHTML = `<p style="color:red">${err.message}</p>`;
    }
}

function renderCostData(data) {
    const s = data.summary;
    const html = `
        <div class="cost-summary">
            <h4>📊 总览</h4>
            <div class="cost-grid">
                <div class="item"><span>总调用次数</span><strong>${s.total_calls}</strong></div>
                <div class="item"><span>总 Input Tokens</span><strong>${s.total_input_tokens.toLocaleString()}</strong></div>
                <div class="item"><span>总 Output Tokens</span><strong>${s.total_output_tokens.toLocaleString()}</strong></div>
                <div class="item"><span>预估费用 (USD)</span><strong>$${s.total_cost_usd}</strong></div>
                <div class="item"><span>预估费用 (CNY)</span><strong>¥${s.estimated_cny}</strong></div>
            </div>
        </div>
        <h4>按 Agent 统计</h4>
        <table class="cost-table">
            <thead>
                <tr><th>Agent</th><th>调用次数</th><th>Input Tokens</th><th>Output Tokens</th><th>费用($)</th></tr>
            </thead>
            <tbody>
                ${Object.entries(data.by_agent).map(([name, info]) => `
                    <tr>
                        <td><strong>${name}</strong></td>
                        <td>${info.calls}</td>
                        <td>${info.input_tokens.toLocaleString()}</td>
                        <td>${info.output_tokens.toLocaleString()}</td>
                        <td>$${info.cost.toFixed(4)}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
    document.getElementById('cost-body').innerHTML = html;
}

async function resetCostStats() {
    await apiCall('/cost/reset', 'POST');
    showCostPanel(); // 刷新
    addLog('info', '💰 Token 统计已重置');
}

// ============================================================
// 版本控制
// ============================================================

async function showVersionPanel() {
    document.getElementById('version-modal').style.display = 'flex';

    try {
        const data = await apiCall('/bible/versions');
        renderVersionData(data);
    } catch (err) {
        document.getElementById('version-body').innerHTML = `<p style="color:red">${err.message}</p>`;
    }
}

function renderVersionData(data) {
    const html = `
        <p style="margin-bottom:12px;color:#64748b;font-size:13px;">
            当前版本：<strong>v${data.current_version}</strong> | 共 ${data.total_versions} 个版本
        </p>
        <ul class="version-list">
            ${data.history.map(v => `
                <li class="version-item ${v.version_id === data.current_version ? 'current' : ''}">
                    <div>
                        <strong>v${v.version_id}</strong>
                        <span style="color:#64748b;margin-left:8px">${v.reason || '无备注'}</span>
                        <br>
                        <small style="color:#94a3b8">${v.timestamp}</small>
                    </div>
                    <div style="text-align:right">
                        <code class="hash">${v.hash}</code>
                        <br>
                        ${v.version_id !== data.current_version && v.version_id < data.current_version
                            ? `<button onclick="rollbackTo(${v.version_id})" style="margin-top:4px;padding:2px 8px;font-size:11px;">回滚到此</button>`
                            : ''
                        }
                    </div>
                </li>
            `).join('')}
        </ul>
    `;
    document.getElementById('version-body').innerHTML = html;
}

async function rollbackTo(versionId) {
    if (!confirm(`确定要回滚到版本 v${versionId} 吗？当前更改将丢失。`)) return;

    try {
        await apiCall(`/bible/rollback/${versionId}`, 'POST');
        addLog('success', `📦 已回滚到版本 v${versionId}`);
        showVersionPanel(); // 刷新
        loadWorldData();
    } catch (err) {
        addLog('error', err.message);
    }
}

async function createCheckpoint() {
    const reason = prompt('请输入本次快照的备注（可选）：', '手动创建');
    try {
        await apiCall('/bible/checkpoint', 'POST', { reason: reason || '手动创建' });
        addLog('success', '📦 快照已创建');
        showVersionPanel(); // 刷新
    } catch (err) {
        addLog('error', err.message);
    }
}

// ============================================================
// 导出 & 重置
// ============================================================

async function exportNovel() {
    window.open(`${API_BASE}/api/export`, '_blank');
    addLog('success', '📥 导出请求已发送');
}

async function resetProject() {
    if (!confirm('确定要重置所有数据吗？此操作不可撤销！')) return;

    try {
        await apiCall('/reset', 'POST');
        addLog('info', '🔄 项目已重置');

        // 重置 UI
        location.reload();
    } catch (err) {
        addLog('error', err.message);
    }
}

// ============================================================
// 工具函数
// ============================================================

function setRunning(running) {
    document.querySelectorAll('#btn-build-world, #btn-outline, #btn-write-all, #btn-write-chapter')
        .forEach(btn => btn.disabled = running);

    if (running) {
        document.getElementById('status-message').classList.add('running');
    } else {
        document.getElementById('status-message').classList.remove('running');
    }
}

function updateStatus(step, message) {
    document.getElementById('current-step').textContent = formatStep(step);
    document.getElementById('status-message').textContent = message;
}

function formatStep(step) {
    const map = {
        'idle': '⏸️ 空闲',
        'input': '📝 输入',
        'world_building': '🌍 世界构建中',
        'world_built': '✅ 世界观待确认',
        'outlining': '📋 大纲生成中',
        'outline_generated': '✅ 大纲待确认',
        'writing': '✍️ 写作中',
        'chapter_done': '✅ 章节待确认',
        'done': '🎉 全部完成',
        'error': '❌ 错误',
    };
    return map[step] || step;
}

function addLog(type, message, append = true) {
    const container = document.getElementById('log-container');
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.textContent = message;

    if (append) {
        container.appendChild(entry);
    }
    container.scrollTop = container.scrollHeight;

    // 限制日志条数
    while (container.children.length > 100) {
        container.removeChild(container.firstChild);
    }
}

function closeModal(id) {
    document.getElementById(id).style.display = 'none';
}

// ============================================================
// 初始化
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
    addLog('info', '📖 小说写作 Agent v0.2 已就绪');
    addLog('info', '改进内容：反馈回路 | Token追踪 | 版本控制 | 流式输出 | 多模型路由');

    // 初始轮询一次状态
    pollStatus().catch(() => {});
});
