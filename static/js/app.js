/**
 * 小说写作 Agent - 前端交互逻辑
 */

let currentViewMode = 'draft';
let pollInterval = null;

// ============================================================
// 初始化
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    // 每3秒轮询状态
    pollInterval = setInterval(loadStatus, 3000);
});

// ============================================================
// API 调用封装
// ============================================================

async function apiCall(endpoint, method = 'GET', body = null) {
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json',
        },
    };
    if (body) {
        options.body = JSON.stringify(body);
    }
    
    const res = await fetch(`/api${endpoint}`, options);
    const data = await res.json();
    
    if (!res.ok) {
        throw new Error(data.error || '请求失败');
    }
    
    return data;
}

function showLoading(text = '处理中...') {
    document.getElementById('loading-text').textContent = text;
    document.getElementById('loading').style.display = 'flex';
}

function hideLoading() {
    document.getElementById('loading').style.display = 'none';
}

function addLog(message, type = 'info') {
    const logStream = document.getElementById('log-stream');
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.textContent = message;
    logStream.appendChild(entry);
    logStream.scrollTop = logStream.scrollHeight;
    
    // 同步到完整日志
    const fullLogs = document.getElementById('full-logs');
    if (fullLogs) {
        const fullEntry = entry.cloneNode(true);
        fullLogs.appendChild(fullEntry);
        fullLogs.scrollTop = fullLogs.scrollHeight;
    }
}

// ============================================================
// 主操作处理器
// ============================================================

async function handleStart() {
    const premise = document.getElementById('input-premise').value.trim();
    const genre = document.getElementById('input-genre').value;
    
    if (!premise) {
        alert('请输入创意描述！');
        return;
    }
    
    try {
        showLoading('启动新项目...');
        await apiCall('/start', 'POST', { premise, genre });
        addLog(`🚀 新项目启动 | 类型:${genre || '自动'} | 创意:${premise.slice(0, 50)}...`, 'success');
        
        // 启用世界构建按钮
        document.getElementById('btn-build-world').disabled = false;
        updateStepNav('input');
        
    } catch (err) {
        addLog(`❌ 错误：${err.message}`, 'error');
        alert(err.message);
    } finally {
        hideLoading();
    }
}

async function handleBuildWorld() {
    try {
        showLoading('正在构建世界观，这可能需要几秒钟...');
        const res = await apiCall('/build-world', 'POST');
        
        if (res.status === 'started') {
            addLog('🌍 开始构建世界观...', 'info');
            document.getElementById('btn-build-world').disabled = true;
            updateStepNav('world_building');
            
            // 等待完成后启用下一步
            setTimeout(() => {
                document.getElementById('btn-outline').disabled = false;
                addLog('✅ 世界观构建完成！可以生成大纲了', 'success');
                updateStepNav('outline');
            }, 8000);
        }
    } catch (err) {
        addLog(`❌ 错误：${err.message}`, 'error');
        alert(err.message);
    } finally {
        hideLoading();
    }
}

async function handleOutline() {
    const chapterCount = parseInt(document.getElementById('input-chapters').value) || 10;
    
    try {
        showLoading(`正在生成${chapterCount}章大纲...`);
        const res = await apiCall('/generate-outline', 'POST', { chapter_count: chapterCount });
        
        if (res.status === 'started') {
            addLog(`📋 开始生成大纲（${chapterCount}章）...`, 'info');
            document.getElementById('btn-outline').disabled = true;
            document.getElementById('btn-write-all').disabled = false;
            updateStepNav('writing');
            
            setTimeout(() => {
                loadOutline();
                addLog(`✅ 大纲生成完成！可以开始写作了`, 'success');
            }, 8000);
        }
    } catch (err) {
        addLog(`❌ 错误：${err.message}`, 'error');
        alert(err.message);
    } finally {
        hideLoading();
    }
}

async function handleWriteAll() {
    try {
        showLoading('正在逐章写作全部内容，这可能需要几分钟...');
        const res = await apiCall('/write-all', 'POST');
        
        if (res.status === 'started') {
            addLog('✍️ 开始逐章写作...', 'info');
            document.getElementById('btn-write-all').disabled = true;
            updateStepNav('done');
            
            // 轮询会更新进度
        }
    } catch (err) {
        addLog(`❌ 错误：${err.message}`, 'error');
        alert(err.message);
    } finally {
        hideLoading();
    }
}

async function handleExport() {
    try {
        showLoading('正在导出文件...');
        window.open('/api/export', '_blank');
        addLog('📥 导出成功！', 'success');
    } catch (err) {
        addLog(`❌ 导出失败：${err.message}`, 'error');
        alert(err.message);
    } finally {
        hideLoading();
    }
}

async function handleReset() {
    if (!confirm('确定要重置项目吗？所有未导出的内容将丢失。')) {
        return;
    }
    
    try {
        await apiCall('/reset', 'POST');
        addLog('🔄 项目已重置', 'warning');
        
        // 重置 UI
        document.getElementById('input-premise').value = '';
        document.getElementById('input-genre').value = '';
        document.getElementById('btn-build-world').disabled = true;
        document.getElementById('btn-outline').disabled = true;
        document.getElementById('btn-write-all').disabled = true;
        document.getElementById('btn-export').disabled = true;
        
        document.getElementById('bible-content').textContent = '暂无数据，请先完成世界构建...';
        document.getElementById('outline-content').textContent = '暂无数据，请先生成大纲...';
        document.getElementById('chapter-content').textContent = '选择一个章节查看内容...';
        document.getElementById('chapter-select').innerHTML = '<option value="">选择章节...</option>';
        
        updateStepNav('input');
        
    } catch (err) {
        addLog(`❌ 错误：${err.message}`, 'error');
    }
}

// ============================================================
// 状态加载与更新
// ============================================================

async function loadStatus() {
    try {
        const status = await apiCall('/status');
        
        // 更新状态面板
        document.getElementById('cur-step').textContent = status.step || '准备就绪';
        document.getElementById('bible-title').textContent = status.bible_title || '-';
        document.getElementById('genre').textContent = status.genre || '-';
        document.getElementById('char-count').textContent = status.character_count || 0;
        document.getElementById('written-count').textContent = 
            `${status.written_chapters.length}/${status.total_chapters || 0}`;
        
        const statusMsg = document.getElementById('status-message');
        statusMsg.textContent = status.message || '等待输入创意...';
        
        if (status.is_running) {
            statusMsg.className = 'status-msg running';
            document.getElementById('progress-wrap').style.display = 'block';
            
            // 更新进度条
            const progress = status.written_chapters.length / (status.total_chapters || 1) * 100;
            document.getElementById('progress-fill').style.width = `${progress}%`;
        } else {
            statusMsg.className = status.message.includes('错误') ? 'status-msg error' : 'status-msg success';
            document.getElementById('progress-wrap').style.display = 'none';
        }
        
        // 更新日志
        if (status.logs && status.logs.length > 0) {
            const logStream = document.getElementById('log-stream');
            const lastLog = logStream.lastChild;
            const latestLog = status.logs[status.logs.length - 1];
            
            if (!lastLog || !lastLog.textContent.includes(latestLog)) {
                status.logs.forEach(log => {
                    if (!lastLog || !lastLog.textContent.includes(log)) {
                        const type = log.includes('✅') ? 'success' :
                                    log.includes('❌') ? 'error' :
                                    log.includes('⚠️') ? 'warning' : 'info';
                        addLog(log, type);
                    }
                });
            }
        }
        
        // 根据步骤启用按钮
        if (status.step === 'world_building' || status.step === 'outline') {
            document.getElementById('btn-build-world').disabled = true;
        }
        if (status.step === 'outlining' || status.step === 'writing') {
            document.getElementById('btn-outline').disabled = true;
        }
        if (status.step === 'done' || status.written_chapters.length > 0) {
            document.getElementById('btn-export').disabled = false;
            updateChapterSelect(status.written_chapters);
        }
        
        // 更新步骤导航
        updateStepNav(status.step);
        
    } catch (err) {
        console.error('加载状态失败:', err);
    }
}

function updateStepNav(currentStep) {
    const steps = ['input', 'world_building', 'outline', 'writing', 'done'];
    const currentIndex = steps.indexOf(currentStep);
    
    document.querySelectorAll('.step-item').forEach(item => {
        const step = item.dataset.step;
        const idx = steps.indexOf(step);
        
        item.classList.remove('active', 'completed');
        
        if (idx < currentIndex) {
            item.classList.add('completed');
        } else if (idx === currentIndex) {
            item.classList.add('active');
        }
    });
}

function updateChapterSelect(chapters) {
    const select = document.getElementById('chapter-select');
    const currentValue = select.value;
    
    let html = '<option value="">选择章节...</option>';
    chapters.forEach(num => {
        html += `<option value="${num}">第${num}章</option>`;
    });
    
    select.innerHTML = html;
    if (currentValue && chapters.includes(parseInt(currentValue))) {
        select.value = currentValue;
    }
}

// ============================================================
// Tab 切换
// ============================================================

window.switchTab = function(tabName) {
    // 更新 Tab 按钮
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    
    // 更新 Tab 内容
    document.querySelectorAll('.tab-pane').forEach(pane => {
        pane.classList.toggle('active', pane.id === `tab-${tabName}`);
    });
    
    // 加载对应数据
    if (tabName === 'bible') {
        loadBible();
    } else if (tabName === 'outline-view') {
        loadOutline();
    } else if (tabName === 'chapters') {
        loadChapterSelect();
    } else if (tabName === 'logs') {
        loadFullLogs();
    }
};

async function loadBible() {
    try {
        const bible = await apiCall('/bible');
        document.getElementById('bible-content').textContent = 
            JSON.stringify(bible, null, 2);
    } catch (err) {
        document.getElementById('bible-content').textContent = '加载失败...';
    }
}

async function loadOutline() {
    try {
        const outline = await apiCall('/outline');
        if (outline && Object.keys(outline).length > 0) {
            document.getElementById('outline-content').textContent = 
                JSON.stringify(outline, null, 2);
        } else {
            document.getElementById('outline-content').textContent = '暂无数据，请先生成大纲...';
        }
    } catch (err) {
        document.getElementById('outline-content').textContent = '加载失败...';
    }
}

function loadChapterSelect() {
    loadStatus(); // 这会触发章节选择器更新
}

async function loadChapter() {
    const chapterNum = document.getElementById('chapter-select').value;
    if (!chapterNum) {
        document.getElementById('chapter-content').textContent = '选择一个章节查看内容...';
        document.getElementById('chapter-check').style.display = 'none';
        return;
    }
    
    try {
        const chapter = await apiCall(`/chapter/${chapterNum}`);
        const content = currentViewMode === 'polished' ? 
                       (chapter.polished || chapter.draft) : 
                       chapter.draft;
        
        document.getElementById('chapter-content').textContent = content;
        
        // 显示检查报告
        if (chapter.check_report) {
            document.getElementById('check-report-content').textContent = 
                JSON.stringify(chapter.check_report, null, 2);
            document.getElementById('chapter-check').style.display = 'block';
        } else {
            document.getElementById('chapter-check').style.display = 'none';
        }
        
    } catch (err) {
        document.getElementById('chapter-content').textContent = '加载失败...';
    }
}

window.setViewMode = function(mode) {
    currentViewMode = mode;
    document.getElementById('view-draft').classList.toggle('active', mode === 'draft');
    document.getElementById('view-polished').classList.toggle('active', mode === 'polished');
    loadChapter();
};

async function loadFullLogs() {
    try {
        const status = await apiCall('/status');
        const fullLogs = document.getElementById('full-logs');
        fullLogs.innerHTML = '';
        
        if (status.logs && status.logs.length > 0) {
            status.logs.forEach(log => {
                const entry = document.createElement('div');
                entry.className = `log-entry ${
                    log.includes('✅') ? 'success' :
                    log.includes('❌') ? 'error' :
                    log.includes('⚠️') ? 'warning' : 'info'
                }`;
                entry.textContent = log;
                fullLogs.appendChild(entry);
            });
        } else {
            fullLogs.innerHTML = '<div class="log-entry info">暂无日志</div>';
        }
    } catch (err) {
        document.getElementById('full-logs').innerHTML = '加载失败...';
    }
}
