/**
 * 小说写作 Agent —— 前端主逻辑（v0.3 回显续写版）
 *
 * - 全流水线默认走 SSE 推送；关闭「流式输出」时使用后台线程 + 轮询状态。
 * - 打开页面自动回显上次项目数据（创意/大纲/世界观/已写章节），便于继续生成。
 * - 单章写作支持续写：章号超出大纲时自动扩章（后端扩展占位细纲 + 总章数）。
 *
 * SSE 调用方式：
 *   streamPipeline('/api/stream-world')     世界构建
 *   streamPipeline('/api/stream-outline')   大纲生成
 *   streamPipeline('/api/stream-all')       批量写作
 *   streamPipeline('/api/stream-write/3')   单章流式写作（逐字输出）
 */

// ============================================================
// 全局状态
// ============================================================

const AppState = {
  step: 'idle',
  isRunning: false,
  currentChapter: 0,
  totalChapters: 0,
  writtenChapters: [],
  chapterMeta: {},
  bibleTitle: '',
  genre: '',
  premise: '',
  characterCount: 0,
  foreshadowingCount: 0,
  bibleVersion: 0,
  statusMessage: '',
  nextChapter: 1,
  chapterView: 'draft',
};

const STEP_LABELS = {
  idle: '等待初始化',
  input: '待输入 / 可继续',
  world_building: '构建世界中…',
  world_built: '世界观完成（待确认）',
  outlining: '生成大纲中…',
  outline_generated: '大纲完成（待确认）',
  writing: '写作中…',
  chapter_done: '章节完成（可继续写作）',
  done: '全部完成',
  error: '出错了',
};

// ============================================================
// DOM 工具函数
// ============================================================

function $(selector) {
  return document.querySelector(selector);
}

function showEl(el) {
  if (el) el.style.display = '';
}

function hideEl(el) {
  if (el) el.style.display = 'none';
}

function setHTML(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = String(text == null ? '' : text);
  return div.innerHTML;
}

function formatNovelText(text) {
  return escapeHtml(text)
    .replace(/\n/g, '<br>')
    .replace(/　　/g, '&emsp;&emsp;')
    .replace(/第\d+章\s+/g, (m) => `<strong style="color:#0d6efd;font-size:1.1em;">${m}</strong>`);
}

function toggleBtn(selector, enabled) {
  const el = $(selector);
  if (!el) return;
  el.disabled = !enabled;
  el.style.opacity = enabled ? '1' : '0.5';
  el.style.cursor = enabled ? 'pointer' : 'not-allowed';
}

function toggleShow(selector, visible) {
  const el = $(selector);
  if (!el) return;
  el.style.display = visible ? '' : 'none';
}

// ============================================================
// 日志系统
// ============================================================

function addLog(message, level = 'info') {
  const area = $('#log-container');
  if (!area) return;

  const time = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  const colorMap = { info: '#495057', success: '#198754', warning: '#fd7e14', error: '#dc3545' };
  const iconMap = { info: 'ℹ️', success: '✅', warning: '⚠️', error: '❌' };
  const color = colorMap[level] || colorMap.info;
  const icon = iconMap[level] || '';

  const entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.style.cssText = `color:${color};padding:4px 12px;border-bottom:1px solid #f0f0f0;font-size:13px;`;
  entry.innerHTML = `<span style="color:#999;margin-right:8px;">[${time}]</span>${icon} ${escapeHtml(message)}`;
  area.appendChild(entry);
  area.scrollTop = area.scrollHeight;
}

function clearLogs() {
  const area = $('#log-container');
  if (area) area.innerHTML = '';
  area.scrollTop = 0;
}

// ============================================================
// Tab 切换 / 章节查看
// ============================================================

function switchTab(tab) {
  document.querySelectorAll('.tab-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });
  document.querySelectorAll('.tab-content').forEach((el) => {
    el.classList.toggle('active', el.id === `${tab}-tab` || el.id === `${tab}-content`);
  });
}

function renderChapterSelect() {
  const sel = $('#chapter-select');
  if (!sel) return;

  const nums = [].concat(AppState.writtenChapters || []).sort((a, b) => a - b);
  if (!nums.length) {
    sel.innerHTML = '<option value="">暂无已写章节</option>';
    return;
  }
  let html = '<option value="">选择章节...</option>';
  for (const num of nums) {
    const meta = AppState.chapterMeta[num] || {};
    const label = `第 ${num} 章（${meta.word_count || 0} 字${meta.has_polished ? ' · 已润色' : ' · 初稿'}）`;
    html += `<option value="${num}">${label}</option>`;
  }
  sel.innerHTML = html;
}

function loadChapter(num) {
  if (!num) {
    setHTML('chapter-meta', '');
    setHTML('chapter-output', '');
    return;
  }
  fetch(`/api/chapter/${num}`)
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error('章节不存在'))))
    .then((ch) => {
      const meta = AppState.chapterMeta[num] || {};
      const view = AppState.chapterView;
      let content = '';
      if (view === 'polished') {
        content = ch.polished || '(暂无润色稿，请先完成润色)';
      } else if (view === 'check') {
        content = ch.check_report
          ? JSON.stringify(ch.check_report, null, 2)
          : '(暂无检查报告)';
      } else {
        content = ch.draft || '(暂无初稿)';
      }
      $('#chapter-meta').textContent = `${meta.word_count || 0} 字 · 重写 ${meta.retry_count || 0} 次`;
      $('#chapter-output').innerHTML = formatNovelText(content);
    })
    .catch((err) => addLog(`❌ 读取章节失败：${err.message}`, 'error'));
}

function toggleChapterView(view) {
  AppState.chapterView = view;
  document.querySelectorAll('.chapter-view-toggle .toggle-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('onclick').includes(`'${view.toLowerCase()}'`));
  });
  const sel = $('#chapter-select');
  if (sel && sel.value) loadChapter(sel.value);
}

// ============================================================
// UI 状态更新
// ============================================================

function updateUI() {
  const step = AppState.step;
  const running = AppState.isRunning;

  // 顶部状态
  setHTML('current-step', STEP_LABELS[step] || step);
  setHTML('status-message', AppState.statusMessage || '');
  setHTML('progress', `${AppState.writtenChapters.length}/${AppState.totalChapters || 0}`);
  setHTML('bible-version', `v${AppState.bibleVersion}`);
  toggleShow('#progress-container', running);

  // 按钮状态（满足「打开页面即可继续生成」）
  const hasWorld = AppState.characterCount > 0;
  const hasOutline = AppState.totalChapters > 0;
  toggleBtn('#btn-start', !running && step === 'input');
  toggleBtn('#btn-build-world', !running && step === 'input');
  toggleBtn('#btn-outline', !running && hasWorld);
  toggleBtn('#btn-write-all', !running && hasOutline);
  toggleBtn('#btn-write-chapter', !running && hasOutline);
  toggleBtn('#btn-export', !running && AppState.writtenChapters.length > 0);

  // 确认按钮（人工确认状态机）
  toggleShow('#btn-confirm-world', !running && step === 'world_built');
  toggleShow('#btn-confirm-outline', !running && step === 'outline_generated');

  renderChapterSelect();
}

// ============================================================
// SSE 核心调用（统一入口）
// ============================================================

function streamPipeline(url, options = {}) {
  if (AppState.isRunning) {
    addLog('⚠️ 正在运行中，请稍候', 'warning');
    return;
  }

  AppState.isRunning = true;
  updateUI();
  clearLogs();

  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options.body || {}),
  })
    .then((resp) => {
      if (!resp.ok) {
        return resp.json().then((err) => Promise.reject(new Error(err.error || `HTTP ${resp.status}`)));
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      (function read() {
        reader.read().then(({ done, value }) => {
          if (done) {
            onStreamEnd(options);
            return;
          }
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop();
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                handleSSEMessage(JSON.parse(line.slice(6)), options);
              } catch (e) {
                console.warn('SSE 解析失败:', line, e);
              }
            }
          }
          read();
        }).catch((err) => {
          addLog(`❌ 连接错误：${err.message}`, 'error');
          AppState.isRunning = false;
          updateUI();
        });
      })();
    })
    .catch((err) => {
      addLog(`❌ 请求失败：${err.message}`, 'error');
      AppState.isRunning = false;
      updateUI();
    });
}

function handleSSEMessage(data, options) {
  switch (data.type) {
    case 'log':
      addLog(data.message, data.level || 'info');
      break;
    case 'status':
      AppState.step = data.step;
      updateUI();
      break;
    case 'chunk':
      if (typeof options.onChunk === 'function') options.onChunk(data.content);
      break;
    case 'chapter_done':
      onChapterDone(data);
      break;
    case 'done':
      onDone(data, options);
      break;
    case 'error':
      addLog(`❌ ${data.message}`, 'error');
      AppState.isRunning = false;
      updateUI();
      break;
    default:
      console.log('[SSE] 未处理消息:', data.type, data);
  }
}

function onChapterDone(data) {
  if (!AppState.writtenChapters.includes(data.chapter)) {
    AppState.writtenChapters.push(data.chapter);
    AppState.writtenChapters.sort((a, b) => a - b);
  }
  AppState.currentChapter = data.chapter;
  updateUI();
}

function onDone(data, options) {
  AppState.isRunning = false;
  AppState.step = data.step || AppState.step;
  if (data.stats) {
    addLog(
      `🎉 完成！共 ${data.stats.total_chapters_written || data.completed || data.total} 章，` +
      `重写 ${data.stats.total_retries || 0} 次`,
      'success'
    );
  }
  if (typeof options.onComplete === 'function') {
    try { options.onComplete(data); } catch (e) { console.warn(e); }
  }
  updateStatus(); // 拉取最新总章数/章节元信息，便于续写
}

function onStreamEnd(options) {
  if (AppState.isRunning) {
    AppState.isRunning = false;
    updateUI();
  }
}

// ============================================================
// 后台任务（非流式：POST + 轮询状态）
// ============================================================

function runBackgroundTask(url) {
  if (AppState.isRunning) {
    addLog('⚠️ 正在运行中，请稍候', 'warning');
    return;
  }
  AppState.isRunning = true;
  updateUI();
  addLog(`⏳ 后台任务已启动：${url}`, 'info');

  fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    .then((r) => r.json())
    .then((d) => {
      if (d.error) throw new Error(d.error);
    })
    .catch((err) => {
      addLog(`❌ 任务启动失败：${err.message}`, 'error');
      AppState.isRunning = false;
      updateUI();
      return;
    });

  const timer = setInterval(() => {
    fetch('/api/status')
      .then((r) => r.json())
      .then((s) => {
        applyStatus(s);
        if (!s.is_running) {
          clearInterval(timer);
          addLog('✅ 后台任务完成', 'success');
          updateUI();
        }
      })
      .catch(() => {
        clearInterval(timer);
        AppState.isRunning = false;
        updateUI();
      });
  }, 1500);
}

// ============================================================
// 状态同步 / 页面回显
// ============================================================

function applyStatus(status, echo = true) {
  AppState.isRunning = !!status.is_running;
  AppState.step = status.step || AppState.step;
  AppState.statusMessage = status.message || status.status_message || '';
  AppState.currentChapter = status.current_chapter || 0;
  AppState.totalChapters = status.total_chapters || 0;
  AppState.writtenChapters = (status.written_chapters || []).map(Number).sort((a, b) => a - b);
  AppState.chapterMeta = status.chapter_meta || {};
  AppState.genre = status.genre || AppState.genre;
  AppState.premise = status.premise != null ? status.premise : AppState.premise;
  AppState.bibleTitle = status.bible_title || AppState.bibleTitle;
  AppState.characterCount = status.character_count || 0;
  AppState.foreshadowingCount = status.foreshadowing_count || 0;
  AppState.bibleVersion = status.bible_version != null ? status.bible_version : AppState.bibleVersion;
  AppState.nextChapter = status.next_chapter || (AppState.writtenChapters.length + 1);

  if (echo) {
    if ($('#premise')) $('#premise').value = AppState.premise;
    if ($('#genre')) $('#genre').value = AppState.genre;
    if ($('#chapter-count')) $('#chapter-count').value = AppState.totalChapters || 10;
    if ($('#single-chapter')) $('#single-chapter').value = AppState.nextChapter;
  }
  updateUI();
}

function updateStatus() {
  fetch('/api/status')
    .then((r) => r.json())
    .then((s) => {
      applyStatus(s, false);
      renderChapterSelect();
      const last = AppState.writtenChapters.length
        ? AppState.writtenChapters[AppState.writtenChapters.length - 1]
        : null;
      if (last && $('#chapter-select')) {
        $('#chapter-select').value = String(last);
        AppState.chapterView = 'draft';
        loadChapter(String(last));
      }
    })
    .catch((err) => addLog(`⚠️ 状态刷新失败：${err.message}`, 'warning'));
}

function showWorldTab(data) {
  const out = $('#world-output');
  if (!out) return;
  out.textContent = JSON.stringify(data, null, 2);
}

function showOutlineTab(data) {
  const out = $('#outline-output');
  if (!out) return;
  out.textContent = JSON.stringify(data, null, 2);
}

// ============================================================
// 用户操作
// ============================================================

function startProject() {
  const premise = $('#premise').value.trim();
  const genre = $('#genre').value;
  if (!premise) {
    alert('请先填写核心创意描述');
    return;
  }
  fetch('/api/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ premise, genre }),
  })
    .then((r) => r.json())
    .then(() => {
      AppState.premise = premise;
      AppState.genre = genre;
      AppState.step = 'input';
      AppState.totalChapters = 0;
      AppState.writtenChapters = [];
      addLog(`🚀 项目已初始化 | 类型：${genre || '自动检测'}`, 'success');
      updateUI();
    })
    .catch((err) => addLog(`❌ 初始化失败：${err.message}`, 'error'));
}

function buildWorld() {
  streamPipeline('/api/stream-world', {
    onComplete() {
      updateStatus();
      fetch('/api/bible').then((r) => r.json()).then(showWorldTab).catch(() => {});
    },
  });
}

function generateOutline() {
  const count = parseInt($('#chapter-count').value, 10) || 10;
  const volumes = parseInt($('#volume-count').value, 10) || 1;
  streamPipeline('/api/stream-outline', {
    body: { chapter_count: count, volume_count: volumes },
    onComplete() {
      updateStatus();
      fetch('/api/outline').then((r) => r.json()).then(showOutlineTab).catch(() => {});
    },
  });
}

function writeChapter() {
  const num = parseInt($('#single-chapter').value, 10) || (AppState.writtenChapters.length + 1);
  const streaming = $('#use-streaming').checked;

  // 续写场景：章号超出大纲时由后端自动扩章
  if (num > AppState.totalChapters && AppState.totalChapters > 0) {
    const ok = confirm(
      `当前大纲共 ${AppState.totalChapters} 章。\n` +
      `写入第 ${num} 章将作为续写章，自动扩展大纲并基于前文生成。\n\n确定继续吗？`
    );
    if (!ok) return;
  }

  addLog(`📝 开始写第 ${num} 章...`, 'info');

  if (streaming) {
    AppState.currentChapter = num;
    setHTML('chapter-meta', '');
    const preview = $('#chapter-output');
    if (preview) preview.innerHTML = '<em style="color:#999;">正在流式生成...</em>';

    streamPipeline(`/api/stream-write/${num}`, {
      onChunk(text) {
        if (preview) preview.innerHTML = formatNovelText(text);
      },
      onComplete() {
        updateStatus(); // 刷新总章数/进度，续写后自动回显
      },
    });
  } else {
    runBackgroundTask(`/api/write-chapter/${num}`);
  }
}

function writeAll() {
  if (AppState.totalChapters <= 0) {
    alert('请先生成大纲');
    return;
  }
  const streaming = $('#use-streaming').checked;
  const ok = confirm(`即将写作全部 ${AppState.totalChapters} 章，过程较长，确定开始吗？`);
  if (!ok) return;

  if (streaming) {
    streamPipeline('/api/stream-all', {
      onChunk(text) {
        const preview = $('#chapter-output');
        if (preview) preview.innerHTML = formatNovelText(text);
      },
      onComplete() {
        updateStatus();
        fetch('/api/outline').then((r) => r.json()).then(showOutlineTab).catch(() => {});
      },
    });
  } else {
    runBackgroundTask('/api/write-all');
  }
}

function confirmStep(step) {
  fetch('/api/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ step }),
  })
    .then((r) => r.json())
    .then((d) => {
      if (d.error) throw new Error(d.error);
      addLog(`✅ 已确认：${step}`, 'success');
      updateStatus();
    })
    .catch((err) => addLog(`❌ 确认失败：${err.message}`, 'error'));
}

function exportNovel() {
  window.location.href = '/api/export';
}

function resetProject() {
  if (!confirm('确定要重置项目吗？所有进度将丢失！')) return;
  fetch('/api/reset', { method: 'POST' })
    .then((r) => r.json())
    .then(() => location.reload());
}

// ============================================================
// 弹窗 / 辅助面板
// ============================================================

function showCostPanel() {
  fetch('/api/cost')
    .then((r) => r.json())
    .then((data) => {
      const body = $('#cost-body');
      body.innerHTML = '<pre style="white-space:pre-wrap;text-align:left;font-size:12px;">'
        + escapeHtml(JSON.stringify(data, null, 2)) + '</pre>';
      showEl($('#cost-modal'));
    })
    .catch((err) => addLog(`❌ 成本统计失败：${err.message}`, 'error'));
}

function resetCostStats() {
  fetch('/api/cost/reset', { method: 'POST' })
    .then(() => {
      addLog('✅ 成本统计已重置', 'success');
      showCostPanel();
    });
}

function showVersionPanel() {
  fetch('/api/bible/versions')
    .then((r) => r.json())
    .then((data) => {
      const rows = (data.history || []).map((v) =>
        `<tr><td>v${v.version_id}</td><td>${escapeHtml(v.reason || '')}</td>` +
        `<td>${escapeHtml(v.timestamp || '')}</td>` +
        `<td>${escHash(v.hash || '')}</td></tr>`
      ).join('');
      $('#version-body').innerHTML =
        `<p>当前版本：v${data.current_version} / 共 ${data.total_versions} 个快照</p>` +
        `<table style="width:100%;font-size:12px;border-collapse:collapse;">` +
        `<tr style="background:#f5f5f5;"><th style="padding:4px;">版本</th><th>说明</th><th>时间</th><th>哈希</th></tr>${rows}` +
        `</table>`;
      showEl($('#version-modal'));
    })
    .catch((err) => addLog(`❌ 版本历史失败：${err.message}`, 'error'));
}

function escHash(h) {
  return typeof h === 'string' && h.length > 12 ? h.slice(0, 12) : (h || '');
}

function createCheckpoint() {
  const reason = prompt('快照说明（可留空）：') || '手动创建';
  fetch('/api/bible/checkpoint', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
    .then((r) => r.json())
    .then((d) => {
      addLog(`✅ 已创建快照 v${d.version_id}`, 'success');
      showVersionPanel();
    })
    .catch((err) => addLog(`❌ 创建快照失败：${err.message}`, 'error'));
}

function closeModal(modalId) {
  hideEl($(`#${modalId}`));
}

// ============================================================
// 页面加载：自动回显上次进度，便于继续生成
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  fetch('/api/status')
    .then((r) => r.json())
    .then((status) => {
      applyStatus(status, true);

      // 恢复历史日志
      (status.logs || []).forEach((log) => {
        const clean = String(log).replace(/^\s*\[[\d:]+\]\s*/, '');
        if (clean) addLog(clean, 'info');
      });

      // 回显世界观与大纲预览
      if (AppState.characterCount > 0) {
        fetch('/api/bible').then((r) => r.json()).then(showWorldTab).catch(() => {});
      }
      if (AppState.totalChapters > 0) {
        fetch('/api/outline').then((r) => r.json()).then(showOutlineTab).catch(() => {});
      }

      // 自动选中最后一章预览
      const last = AppState.writtenChapters.length
        ? AppState.writtenChapters[AppState.writtenChapters.length - 1]
        : null;
      if (last) {
        $('#chapter-select').value = String(last);
        loadChapter(String(last));
      }

      if (AppState.step !== 'idle' && AppState.step !== 'input') {
        // 数据已回显，用户可直接在左栏继续操作
      }

      addLog('📖 已恢复上次进度，可继续生成', 'success');
    })
    .catch((err) => console.warn('加载状态失败:', err));

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal('cost-modal'), closeModal('version-modal');
  });
});