'use strict';

const $ = id => document.getElementById(id);
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

const titles = {radar: '项目库', research: 'AI问答', weekly: '每周推荐', settings: '设置', logs: '任务记录'};
const descriptions = {
  radar: '发现感兴趣的项目，先读资料，再决定研究什么。',
  research: '围绕已保存的资料提问，打开来源核对重要结论。',
  weekly: '每周挑几项，留时间慢慢看懂。',
  settings: '先设置AI连接和找项目的关键词，其余按需要调整。',
  logs: '查看操作的具体结果，了解最近的调用和用量。',
};
const settingsNotice = '修改后点击保存。输入的Key只用于当前服务进程。';
const actionNames = {
  scan: '查找新项目', import: '添加项目', analysis: '介绍项目', tutorial: '生成学习教程',
  recover: '取回原结果', digest: '整理每周推荐', email: '发送周报', research: 'AI问答',
  research_resume: '取回原回答', research_continue: '继续回答', tick: '自动检查',
};
const operationStates = {
  queued: '等待处理', running: '正在处理', done: '操作已结束', failed: '操作未完成', unknown: '结果待核对',
};
const statusNames = {
  running: '正在回答', queued: '等待处理', done: '已回答', failed: '未能完成回答', unknown: '结果待核对',
  empty: '没有匹配资料', limited: '已达到本题限制', paused: '可取回原结果', blocked: '提交结果待核对',
  continuable: '等待你确认继续', cancelled: '已停止', archived: '已收藏',
};
const jobStates = {
  prepared: '准备提交', submitting: '已开始提交', unknown: '结果待核对', received: '已收到原响应',
  invalid: '结果需检查', completed: '结果已保存', failed: '未完成',
};
const categoryNames = {
  'API连接': 'AI连接', '检索来源': '找项目的关键词', '研究画像': '我的学习方向',
  '项目研究': '问答用量', '发现与筛选': '推荐规则', '初始分析': '项目简介', '深入教程': '学习教程',
};
const mainCategories = ['API连接', '检索来源', '研究画像', '项目研究', '发现与筛选'];
const paidActions = new Set(['analysis', 'tutorial', 'research', 'research_continue']);
const completed = new Set();
const controlsPending = new Set();
let state = null;
let csrf = '';
let selectedProject = null;
let selectedProjectName = '';
let selectedResearch = null;
let currentPage = 'radar';
let polling = false;
let stopped = false;
let initialized = false;
let submitting = false;
let pendingOperation = null;
let lastResearch = '';
let lastWeek = '';
let weekRequest = 0;
let projectRequest = 0;
let searchRequest = 0;
let searchTimer = null;
let projectSearchResults = null;
let settings = null;
let settingsLoading = null;
let settingsCategory = 'API连接';
let settingsDirty = false;
let saving = false;
let keywordComplex = [];
let simpleKeywordsEdited = false;
let keywordError = '';

function notice(text, error = false) {
  $('notice').textContent = text;
  $('notice').classList.toggle('error', error);
}

async function api(path, data) {
  const options = {credentials: 'same-origin', cache: 'no-store'};
  if (data !== undefined) {
    options.method = 'POST';
    options.headers = {'Content-Type': 'application/json', 'X-Stars-CSRF': csrf};
    options.body = JSON.stringify(data);
  }
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '请求未完成，请查看任务记录。');
  return result;
}

function safe(task) {
  return async event => {
    try { await task(event); }
    catch (error) { notice(error.message, true); }
  };
}

function button(text, callback, className = '') {
  const node = el('button', text, className);
  node.type = 'button';
  node.addEventListener('click', safe(callback));
  return node;
}

function link(text, address) {
  const node = el('a', text);
  try {
    const url = new URL(address);
    if (url.protocol === 'https:' && url.hostname === 'github.com' && !url.username && !url.password) {
      node.href = url.href;
      node.target = '_blank';
      node.rel = 'noopener noreferrer';
    }
  } catch { /* Untrusted URLs remain plain text. */ }
  return node;
}

function busy() {
  return stopped || submitting || pendingOperation !== null || Boolean(state?.busy);
}

function aiEnabled() {
  return state?.ai_enabled ?? settings?.config?.ai?.enabled ?? false;
}

function updateButtons() {
  for (const node of document.querySelectorAll('.task-button')) {
    node.disabled = busy() || (node.classList.contains('ai-button') && !aiEnabled());
    node.title = node.classList.contains('ai-button') && !aiEnabled() ? '请先在设置中开启AI连接。' : '';
  }
  $('save-settings').disabled = busy() || saving || !settings;
  $('reload-settings').disabled = saving;
  $('theme-choice').disabled = busy() || saving;
  const setup = $('research-ai-setup');
  if (setup) setup.classList.toggle('hidden', aiEnabled());
  for (const node of document.querySelectorAll('[data-control]')) {
    node.disabled = stopped || controlsPending.has(node.dataset.control);
  }
  for (const node of document.querySelectorAll('[data-study-state]')) node.disabled = busy();
  if (stopped) document.querySelectorAll('button').forEach(node => { node.disabled = true; });
}

function taskButton(text, name, args, className = '') {
  return button(text, () => action(name, args), 'task-button ' + (paidActions.has(name) ? 'ai-button ' : '') + className);
}

function controlButton(text, name, args) {
  const node = button(text, () => control(name, args));
  node.dataset.control = name + ':' + args.job_id;
  return node;
}

async function openSettingsCategory(name = 'API连接') {
  switchPage('settings');
  await loadSettings();
  selectSettingsCategory(name);
}

function aiSetupButton() {
  return button('先设置AI连接', () => openSettingsCategory('API连接'));
}

async function action(name, args = {}) {
  if (busy()) return false;
  if (paidActions.has(name) && !aiEnabled()) {
    notice('请先在设置中开启AI连接，并填写可用的Key和模型。', true);
    return false;
  }
  // Lock before the first await, including the HTTP submission itself.
  submitting = true;
  const id = crypto.randomUUID().replaceAll('-', '');
  pendingOperation = id;
  updateButtons();
  try {
    const result = await api('/api/action', {id, action: name, args});
    if (name === 'research') selectedResearch = id;
    notice('已提交，可在任务记录中查看具体结果。');
    await refresh();
    return result;
  } catch (error) {
    if (pendingOperation === id) pendingOperation = null;
    throw error;
  } finally {
    submitting = false;
    updateButtons();
  }
}

async function control(name, args) {
  const key = name + ':' + (args.job_id ?? args.repo_id);
  if (controlsPending.has(key)) return;
  controlsPending.add(key);
  updateButtons();
  try {
    const result = await api('/api/control', {action: name, args});
    if (result.state === 'deleted' && selectedResearch === args.job_id) clearResearch();
    await refresh();
    if (args.job_id && selectedResearch === args.job_id && result.state !== 'deleted') await loadResearch(args.job_id);
    return result;
  } finally {
    controlsPending.delete(key);
    updateButtons();
  }
}

function clearResearch() {
  selectedResearch = null;
  lastResearch = '';
  const box = $('research-answer');
  box.classList.add('empty');
  box.textContent = '从左侧重看已有回答，或在上方发送一个新问题。';
  for (const id of ['research-controls', 'research-sources']) $(id).replaceChildren();
  for (const id of ['source-text', 'research-trace', 'research-organization']) $(id).textContent = '';
  $('sources-details').open = false;
}

function switchPage(name) {
  const leavingSettings = currentPage === 'settings' && name !== 'settings';
  currentPage = name;
  document.querySelectorAll('.page').forEach(page => page.classList.toggle('hidden', page.id !== 'page-' + name));
  document.querySelectorAll('#navigation button').forEach(node => node.classList.toggle('active', node.dataset.page === name));
  $('page-title').textContent = titles[name];
  $('page-description').textContent = descriptions[name];
  if (leavingSettings && $('notice').textContent === settingsNotice) notice(descriptions[name]);
  if (name === 'settings') {
    notice(settingsNotice);
    loadSettings().catch(error => notice(error.message, true));
  }
  if (name === 'logs') loadLogs().catch(error => notice(error.message, true));
  if (name === 'weekly') loadWeek().catch(error => notice(error.message, true));
}

async function refresh() {
  if (polling || stopped) return;
  polling = true;
  try {
    state = await api('/api/state');
    csrf = state.csrf;
    document.documentElement.dataset.theme = state.theme;
    $('theme-choice').value = state.theme;
    $('version').textContent = '版本 ' + state.version;
    $('summary').textContent = state.project_count + ' 个项目 · ' + (busy() ? '正在处理' : '可以开始');
    const pending = (state.operations || []).find(row => row.id === pendingOperation);
    if (pending && ['done', 'failed', 'unknown'].includes(pending.state)) pendingOperation = null;
    renderTopics();
    renderProjects();
    renderHistory();
    renderWeeks();
    renderOperations();
    const scope = $('research-scope');
    const previous = scope.value;
    scope.replaceChildren(new Option('全部已保存项目', ''));
    for (const repo of state.projects || []) scope.add(new Option(repo.name, String(repo.id)));
    if (selectedProject && !Array.from(scope.options).some(option => option.value === String(selectedProject))) {
      scope.add(new Option(selectedProjectName, String(selectedProject)));
    }
    if (Array.from(scope.options).some(option => option.value === previous)) scope.value = previous;
    for (const operation of state.operations || []) {
      if (!['done', 'failed', 'unknown'].includes(operation.state) || completed.has(operation.id)) continue;
      completed.add(operation.id);
      const result = parseResult(operation.result);
      if (result.research_job_id && selectedResearch === operation.id) selectedResearch = result.research_job_id;
      if (initialized) {
        notice(operation.error || result.message || '操作已结束，请查看具体结果。', operation.state !== 'done');
        if (operation.state === 'done' && ['scan', 'import'].includes(operation.action) && $('search').value.trim()) {
          $('search').dispatchEvent(new Event('input'));
        }
        if (selectedProject) await loadProject(selectedProject);
        if (currentPage === 'weekly') await loadWeek(true);
      }
    }
    if (selectedResearch && [...(state.research || []), ...(state.bookmarks || [])].some(job => job.id === selectedResearch)) {
      await loadResearch(selectedResearch);
    }
    initialized = true;
    if (currentPage === 'logs') await loadLogs();
    if (currentPage === 'weekly') await loadWeek();
  } finally {
    polling = false;
    $('summary').textContent = (state?.project_count ?? 0) + ' 个项目 · ' + (busy() ? '正在处理' : '可以开始');
    updateButtons();
  }
}

function parseResult(value) {
  try { return typeof value === 'string' ? JSON.parse(value || '{}') : value || {}; }
  catch { return {}; }
}

function parseSimpleQuery(value) {
  const match = value.trim().match(/^(?:"([^"\\]+)"|([^\s:"\\]+))(?:\s+in:name,description(?:,topics)?)?$/);
  if (!match) return null;
  const word = (match[1] || match[2]).trim();
  return validKeyword(word) ? word : null;
}

function validKeyword(value) {
  const length = Array.from(value).length;
  return length >= 2 && length <= 50 && !/[:："'“”‘’\\]/.test(value);
}

function renderTopics() {
  const queries = state.research_queries || [];
  const topics = queries.map(query => parseSimpleQuery(query) || query.match(/(?:^|\s)topic:([^\s]+)/)?.[1] || query.match(/"([^"\\]+)"/)?.[1]).filter(Boolean);
  const unique = Array.from(new Set(topics));
  $('search-topics').textContent = unique.length ? unique.slice(0, 6).join('、') + (unique.length > 6 ? ' 等' + unique.length + '项' : '') : '可在设置中添加关键词';
  $('search-topics').title = queries.join('\n');
}

function renderProjects() {
  const query = $('search').value.toLowerCase();
  const list = $('project-list');
  list.replaceChildren();
  const rows = projectSearchResults ?? state.projects ?? [];
  for (const repo of rows.filter(row => (row.name + ' ' + (row.description || '')).toLowerCase().includes(query))) {
    const node = button('', () => loadProject(repo.id), 'project-card' + (repo.id === selectedProject ? ' selected' : ''));
    node.append(el('div', repo.name, 'project-name'), el('div', repo.description || '暂时没有简介', 'project-description'));
    node.append(el('div', '★ ' + repo.stars + ' · 匹配 ' + Number(repo.score).toFixed(1) + ' · ' + (state.study_states?.[repo.study_state] || repo.study_state), 'meta'));
    list.append(node);
  }
  if (!list.childElementCount) list.append(el('p', query ? '没有找到匹配的已保存项目。' : '还没有项目。可以按关键词查找，或添加一个GitHub链接。', 'muted'));
}

function renderAnalysis(box, analysis, title = 'AI介绍') {
  box.append(el('h3', title));
  for (const [key, label] of [['summary', '这个项目做什么'], ['relevance', '和我的方向有什么关系'], ['usage', '可以怎样开始'], ['tutorial', '可以怎样学习'], ['related_projects', '相关项目'], ['limitations', '还需要核对什么']]) {
    const value = analysis[key];
    if (!value) continue;
    box.append(el('h3', label));
    appendMarkdown(box, Array.isArray(value) ? value.map(item => typeof item === 'string' ? item : item.name || item.relationship || '').join('\n') : String(value));
  }
}

async function loadProject(id) {
  const sequence = ++projectRequest;
  selectedProject = id;
  const repo = await api('/api/project?id=' + encodeURIComponent(id));
  if (sequence !== projectRequest || selectedProject !== id) return;
  selectedProjectName = repo.name;
  renderProjects();
  const scope = $('research-scope');
  if (!Array.from(scope.options).some(option => option.value === String(id))) scope.add(new Option(repo.name, String(id)));
  const box = $('project-detail');
  box.replaceChildren(el('h2', repo.name), link('在GitHub查看原项目', 'https://github.com/' + repo.name), el('p', repo.metadata?.description || '作者没有填写简介。', 'muted'));
  const tools = el('div', undefined, 'toolbar');
  const status = el('select');
  status.setAttribute('aria-label', '项目研究状态');
  status.dataset.studyState = String(id);
  for (const [value, label] of Object.entries(state.study_states || {})) status.add(new Option(label, value));
  status.value = repo.study_state;
  status.addEventListener('change', safe(() => control('study_state', {repo_id: id, state: status.value})));
  tools.append(status, taskButton('让AI介绍项目', 'analysis', {repo_id: id}), taskButton('生成学习教程', 'tutorial', {repo_id: id}));
  box.append(tools);
  const questions = el('div', undefined, 'toolbar');
  questions.append(button('问问AI', () => {
    scope.value = String(id);
    switchPage('research');
    $('question').focus();
  }));
  if (!aiEnabled()) questions.append(aiSetupButton());
  box.append(questions);
  const available = repo.tutorial_available ?? (repo.jobs || []).some(job => job.kind === 'tutorial' && job.status === 'completed');
  if (available) {
    const download = el('a', '下载已有学习教程');
    download.href = '/api/tutorial?id=' + encodeURIComponent(id);
    box.append(download);
  } else {
    box.append(el('p', '还没有已完成的学习教程；生成后可在这里下载。', 'field-help'));
  }
  if (repo.analysis) renderAnalysis(box, repo.analysis);
  if (repo.legacy?.length) {
    const legacy = el('details');
    legacy.append(el('summary', '以前保存的介绍'));
    for (const value of repo.legacy) renderAnalysis(legacy, value, '旧版内容');
    box.append(legacy);
  }
  if (repo.jobs?.length) {
    const jobs = el('details');
    jobs.append(el('summary', '生成与恢复记录'));
    for (const job of repo.jobs) {
      const row = el('div', undefined, 'operation');
      row.append(el('strong', (actionNames[job.kind] || '旧版内容') + ' · ' + (jobStates[job.status] || job.status)));
      if (job.error) row.append(el('p', job.error, 'muted'));
      if (['submitting', 'unknown', 'received', 'invalid'].includes(job.status) && ['analysis', 'tutorial'].includes(job.kind)) {
        row.append(taskButton('取回原结果', 'recover', {repo_id: id, kind: job.kind}));
      }
      jobs.append(row);
    }
    box.append(jobs);
  }
  const readme = el('details');
  readme.append(el('summary', '阅读项目原文（README）'), el('pre', repo.readme || '尚未保存README。可以重新添加该项目，读取最新资料。'));
  box.append(readme);
  updateButtons();
}

function shortQuestion(value) {
  const text = value.replace(/\s+/g, ' ').trim();
  return text.length > 42 ? text.slice(0, 42) + '…' : text;
}

function renderHistory() {
  const box = $('research-history');
  box.replaceChildren();
  const seen = new Set();
  for (const job of [...(state.research || []), ...(state.bookmarks || [])]) {
    if (seen.has(job.id)) continue;
    seen.add(job.id);
    const node = button('', () => {
      selectedResearch = job.id;
      return loadResearch(job.id);
    }, 'history-card' + (job.id === selectedResearch ? ' selected' : ''));
    node.append(el('div', shortQuestion(job.question)), el('span', statusNames[job.state] || job.state || '已收藏', 'history-status'));
    node.title = job.question;
    box.append(node);
  }
  if (!box.childElementCount) box.append(el('p', '问过的问题会显示在这里，收藏的回答也会保留。', 'muted'));
}

async function loadResearch(id) {
  let job;
  try { job = await api('/api/research?id=' + encodeURIComponent(id)); }
  catch (error) { if (state?.busy || selectedResearch !== id) return; throw error; }
  if (selectedResearch !== id) return;
  const snapshot = JSON.stringify(job);
  if (snapshot === lastResearch) return;
  lastResearch = snapshot;
  $('source-text').textContent = '';
  const box = $('research-answer');
  box.classList.remove('empty');
  box.replaceChildren(el('h2', '回答'), el('p', job.question, 'muted small'), el('p', (statusNames[job.state] || job.state) + ' · ' + (job.calls || 0) + ' 次模型调用', 'muted'));
  for (const claim of job.result?.claims || []) {
    const row = el('div', undefined, 'claim');
    row.append(el('div', claim.text));
    for (const label of claim.sources || []) row.append(button('查看来源 ' + label, () => showSource(job, label), 'citation'));
    box.append(row);
  }
  if (job.error) box.append(el('p', job.error, 'muted'));
  for (const text of job.result?.limitations || []) box.append(el('p', text, 'muted'));
  const controls = $('research-controls');
  controls.replaceChildren();
  if (job.can_resume) controls.append(taskButton('取回原结果', 'research_resume', {job_id: id}));
  if (job.can_continue) controls.append(taskButton('确认继续回答', 'research_continue', {job_id: id}));
  if (['running', 'paused', 'continuable', 'blocked'].includes(job.state)) controls.append(controlButton('停止后续步骤', 'research_cancel', {job_id: id}));
  if (['done', 'archived'].includes(job.state)) controls.append(controlButton(job.saved ? '取消收藏' : '收藏回答', 'research_bookmark', {job_id: id, saved: !job.saved}));
  if (job.state === 'done') {
    for (const [label, rating] of [['有用', 'useful'], ['不相关', 'irrelevant'], ['清除反馈', 'clear']]) controls.append(controlButton(label, 'research_feedback', {job_id: id, rating}));
  }
  const sources = $('research-sources');
  sources.replaceChildren();
  for (const source of job.sources || []) sources.append(button('查看来源 ' + source.label + ' · ' + source.name, () => showSource(job, source.label), 'citation'));
  $('research-trace').textContent = (job.trace || []).map((entry, index) => (index + 1) + '. ' + entry.action + '\n' + entry.detail).join('\n\n');
  $('research-organization').textContent = JSON.stringify(job.organization || {}, null, 2);
  renderHistory();
  updateButtons();
}

function showSource(job, label) {
  const source = (job.sources || []).find(row => row.label === label);
  if (!source) return;
  const text = source.text || '此收藏仅保留答案与来源位置，原文已到期清理，请重新打开来源核对。';
  $('sources-details').open = true;
  $('source-text').textContent = '来源 ' + source.label + ' · ' + source.name + '\n地址：' + source.url + '\n资料版本：' + source.sha + '\n保存时间：' + source.captured + '\n\n' + text;
  $('source-text').scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

function renderWeeks() {
  const select = $('weeks');
  const previous = select.value;
  select.replaceChildren();
  for (const row of state.digests || []) select.add(new Option(row.week + ' · ' + row.note, row.week));
  if (Array.from(select.options).some(option => option.value === previous)) select.value = previous;
}

function appendSafeText(target, text) {
  const parts = String(text).split(/(https:\/\/github\.com\/[^\s<>"']+)/g);
  for (const part of parts) {
    if (part.startsWith('https://github.com/')) {
      const address = part.replace(/[.,;，。；)）]+$/, '');
      target.append(link(address, address));
      if (address.length < part.length) target.append(el('span', part.slice(address.length)));
    } else {
      target.append(el('span', part));
    }
  }
}

function appendMarkdown(target, text) {
  let paragraph = [];
  let list = null;
  let code = null;
  function flush() {
    if (paragraph.length) {
      const node = el('p');
      appendSafeText(node, paragraph.join('\n'));
      target.append(node);
    }
    paragraph = [];
    list = null;
  }
  for (const line of String(text).split(/\r?\n/)) {
    if (/^\s*```/.test(line)) {
      flush();
      if (code) { target.append(code); code = null; }
      else code = el('pre', '');
      continue;
    }
    if (code) { code.textContent += line + '\n'; continue; }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    const item = line.match(/^\s*(?:[-*]|\d+\.)\s+(.+)$/);
    if (!line.trim()) { flush(); continue; }
    if (/^\s*---\s*$/.test(line)) { flush(); target.append(el('hr')); continue; }
    if (heading) { flush(); target.append(el('h' + heading[1].length, heading[2])); continue; }
    if (item) {
      if (paragraph.length) flush();
      if (!list) { list = el('ul'); target.append(list); }
      const node = el('li');
      appendSafeText(node, item[1]);
      list.append(node);
      continue;
    }
    list = null;
    paragraph.push(line);
  }
  flush();
  if (code) target.append(code);
}

async function loadWeek(force = false) {
  const week = $('weeks').value;
  if (!week) {
    $('weekly-text').replaceChildren(el('p', '还没有已有周报。可以先查找新项目，再整理本周推荐。', 'muted'));
    lastWeek = '';
    return;
  }
  if (!force && week === lastWeek) return;
  const sequence = ++weekRequest;
  const result = await api('/api/digest?week=' + encodeURIComponent(week));
  if (sequence !== weekRequest || $('weeks').value !== week) return;
  const box = $('weekly-text');
  box.replaceChildren();
  appendMarkdown(box, result.text);
  lastWeek = week;
}

function renderOperations() {
  const box = $('operations');
  box.replaceChildren();
  for (const row of state.operations || []) {
    const node = el('div', undefined, 'operation');
    const result = parseResult(row.result);
    node.append(el('strong', (actionNames[row.action] || row.action) + ' · ' + (operationStates[row.state] || row.state)));
    if (row.error || result.message) node.append(el('p', row.error || result.message, 'muted'));
    box.append(node);
  }
  if (!box.childElementCount) box.append(el('p', '还没有任务记录。', 'muted'));
}

async function loadLogs() {
  const logs = await api('/api/logs');
  $('logs-text').textContent = JSON.stringify(logs, null, 2);
  const rows = [...(logs.jobs || []), ...(logs.research_steps || [])];
  const known = rows.filter(row => Number.isFinite(row.input_tokens) && Number.isFinite(row.output_tokens));
  const tokens = known.reduce((total, row) => total + row.input_tokens + row.output_tokens, 0);
  const unknown = rows.length - known.length;
  const summary = $('usage-summary');
  summary.replaceChildren();
  for (const [label, value, note] of [
    ['最近任务', (state.operations || []).length + ' 条', '显示最近记录，不代表全部历史。'],
    ['最近模型记录', rows.length + ' 条', '包含项目介绍、教程和问答步骤。'],
    ['已知用量', known.length ? tokens.toLocaleString() + ' Token' : '尚无已知用量', unknown ? unknown + '条记录用量不完整；不能视为零费用，费用以平台账单为准。' : '仅统计返回了完整用量的记录，费用以平台账单为准。'],
  ]) {
    const card = el('article', undefined, 'usage-card');
    card.append(el('h2', label), el('strong', value), el('p', note));
    summary.append(card);
  }
  const events = $('recent-events');
  events.replaceChildren();
  for (const row of logs.events || []) {
    const node = el('div', undefined, 'event-item');
    const time = new Date(row.created);
    const label = {ERROR: '需要查看', WARNING: '提醒', INFO: '消息'}[row.level] || '消息';
    node.append(el('strong', label + (Number.isNaN(time.getTime()) ? '' : ' · ' + time.toLocaleString('zh-CN'))), el('p', row.message, 'muted'));
    events.append(node);
  }
  if (!events.childElementCount) events.append(el('p', '暂无运行消息。', 'muted'));
}

function markSettingsDirty() {
  settingsDirty = true;
}

function advancedSection(id, title) {
  const node = el('details', undefined, 'advanced-settings');
  if (id) node.id = id;
  node.append(el('summary', title));
  return node;
}

function fieldFor(spec, value) {
  const field = el('div', undefined, 'field');
  let input;
  if (spec.choices?.length) {
    input = el('select');
    for (const choice of spec.choices) input.add(new Option(choice, choice));
    input.value = value;
  } else if (spec.type === 'list' || spec.key === 'prompt' || spec.key === 'description') {
    input = el('textarea');
    input.rows = spec.key === 'prompt' ? 8 : 4;
    input.value = Array.isArray(value) ? value.join('\n') : value;
  } else {
    input = el('input');
    input.type = spec.type === 'bool' ? 'checkbox' : ['int', 'float'].includes(spec.type) ? 'number' : 'text';
    if (spec.type === 'bool') input.checked = value;
    else input.value = value;
    if (spec.type === 'float') input.step = 'any';
  }
  input.dataset.section = spec.section;
  input.dataset.key = spec.key;
  input.dataset.type = spec.type;
  input.id = 'setting-' + spec.section + '-' + spec.key;
  const labels = {'ai.enabled': '开启AI功能', 'ai.model': '常用模型名称', 'ai.auto_analyze': '自动生成项目简介（使用AI额度）'};
  const label = el('label', labels[spec.section + '.' + spec.key] || spec.label);
  label.htmlFor = input.id;
  field.append(label, input);
  return field;
}

function secretField(kind, text) {
  const field = el('div', undefined, 'field');
  const input = el('input');
  input.type = 'password';
  input.autocomplete = 'new-password';
  input.dataset.secret = kind;
  input.id = 'secret-' + kind;
  const label = el('label', text);
  label.htmlFor = input.id;
  field.append(label, input);
  return field;
}

function queryLines(value) {
  return value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
}

function syncKeywordsFromAdvanced() {
  const queries = queryLines($('setting-discovery-research_queries').value);
  const words = [];
  keywordComplex = [];
  for (const query of queries) {
    const word = parseSimpleQuery(query);
    if (word) words.push(word);
    else keywordComplex.push(query);
  }
  $('simple-keywords').value = Array.from(new Set(words)).join('\n');
  simpleKeywordsEdited = false;
  keywordError = '';
  $('simple-keywords').setCustomValidity('');
}

function syncKeywordsToAdvanced() {
  const input = $('simple-keywords');
  const words = Array.from(new Set(queryLines(input.value)));
  const invalid = words.find(word => !validKeyword(word));
  keywordError = invalid ? '每个关键词需为2～50字，不能包含冒号、引号或反斜杠：' + invalid : '';
  input.setCustomValidity(keywordError);
  if (keywordError) return false;
  $('setting-discovery-research_queries').value = [...words.map(word => '"' + word + '" in:name,description,topics'), ...keywordComplex].join('\n');
  return true;
}

function addSimpleKeywords(section) {
  section.append(el('p', '每行写一个想找的主题。复杂的GitHub查询会保留在高级设置中。', 'section-intro'));
  const field = el('div', undefined, 'field');
  const label = el('label', '想找什么项目');
  label.htmlFor = 'simple-keywords';
  const input = el('textarea');
  input.id = 'simple-keywords';
  input.rows = 6;
  input.placeholder = '例如：具身智能\nembodied\nvision-language-action';
  field.append(label, input, el('p', '每个关键词2～50字，不填写GitHub语法。修改后需要点击保存。', 'field-help'));
  section.append(field);
  const preset = button('填入具身智能关键词', () => {
    input.value = '具身智能\nembodied\nvision-language-action';
    simpleKeywordsEdited = true;
    syncKeywordsToAdvanced();
    markSettingsDirty();
    notice('已填入关键词，尚未保存。不会自动查找项目。');
  });
  preset.id = 'preset-embodied';
  section.append(preset);
  input.addEventListener('input', () => {
    simpleKeywordsEdited = true;
    syncKeywordsToAdvanced();
    markSettingsDirty();
  });
}

function selectSettingsCategory(name) {
  settingsCategory = name;
  for (const section of $('settings-form').querySelectorAll('.setting-section')) section.classList.toggle('hidden', section.dataset.category !== name);
  for (const tab of $('settings-nav').querySelectorAll('button')) {
    const active = tab.dataset.category === name;
    tab.classList.toggle('active', active);
    if (active && tab.closest('details')) tab.closest('details').open = true;
  }
}

function renderSettings() {
  const nav = $('settings-nav');
  const form = $('settings-form');
  nav.replaceChildren();
  form.replaceChildren();
  const more = advancedSection('settings-more', '更多设置');
  const byName = new Map(settings.schema.map(category => [category.name, category]));
  const ordered = [...mainCategories.filter(name => byName.has(name)), ...settings.schema.map(category => category.name).filter(name => !mainCategories.includes(name))];
  for (const name of ordered) {
    const category = byName.get(name);
    const section = el('section', undefined, 'setting-section');
    section.dataset.category = name;
    section.append(el('h2', categoryNames[name] || name));
    const tab = button(categoryNames[name] || name, () => selectSettingsCategory(name));
    tab.dataset.category = name;
    (mainCategories.includes(name) ? nav : more).append(tab);
    let advanced = null;
    if (name === 'API连接') {
      section.append(el('p', 'Key只用于当前服务进程。留空会保留已有凭据。开启AI表示允许调用，连接和模型是否可用以实际请求结果为准。', 'note'));
      section.append(secretField('openai', 'AI服务的Key'));
      advanced = advancedSection('api-advanced', '高级：凭据来源和各用途模型');
      advanced.append(secretField('github', 'GitHub Token（可选）'));
    }
    if (name === '邮件推送') {
      section.append(el('p', '启用后，到期检查可能发送邮件。SMTP接受不代表已经进入收件箱。', 'note'));
      section.append(secretField('smtp', 'SMTP授权码'));
    }
    if (name === '检索来源') {
      addSimpleKeywords(section);
      advanced = advancedSection('keywords-advanced', '高级：GitHub完整查询');
    }
    for (const spec of category.fields) {
      const field = fieldFor(spec, settings.config[spec.section][spec.key]);
      const primaryAPI = spec.section === 'ai' && ['enabled', 'model'].includes(spec.key);
      (advanced && (name !== 'API连接' || !primaryAPI) ? advanced : section).append(field);
    }
    if (name === 'API连接') {
      const common = button('问答和教程也用这个模型', () => {
        const model = $('setting-ai-model').value.trim();
        if (!model) throw new Error('请先填写AI连接中的模型。');
        for (const target of ['setting-research-model', 'setting-tutorial-model']) $(target).value = model;
        markSettingsDirty();
        notice('已复制到问答和教程模型，尚未保存；截图模型保持原值。');
      });
      common.id = 'use-common-model';
      section.append(common);
    }
    if (advanced) section.append(advanced);
    form.append(section);
  }
  if (more.querySelector('button')) nav.append(more);
  if ($('setting-discovery-research_queries')) {
    syncKeywordsFromAdvanced();
    $('setting-discovery-research_queries').addEventListener('input', syncKeywordsFromAdvanced);
  }
  selectSettingsCategory(byName.has(settingsCategory) ? settingsCategory : ordered[0]);
  updateButtons();
}

async function loadSettings(force = false) {
  if (settingsLoading) return settingsLoading;
  if (settings && !force) return settings;
  settingsLoading = (async () => {
    const current = await api('/api/config');
    settings = current;
    renderSettings();
    settingsDirty = false;
    return current;
  })();
  try { return await settingsLoading; }
  finally { settingsLoading = null; }
}

async function saveSettings() {
  if (saving || busy()) return;
  saving = true;
  updateButtons();
  try {
    await loadSettings();
    if (simpleKeywordsEdited && !syncKeywordsToAdvanced()) {
      selectSettingsCategory('检索来源');
      throw new Error(keywordError);
    }
    const config = structuredClone(settings.config);
    const secrets = {};
    for (const input of $('settings-form').querySelectorAll('[data-section]')) {
      let value = input.type === 'checkbox' ? input.checked : input.value;
      if (input.dataset.type === 'list') value = queryLines(value);
      if (['int', 'float'].includes(input.dataset.type)) {
        if (!String(value).trim()) throw new Error('数值不能为空。');
        value = Number(value);
        if (!Number.isFinite(value) || (input.dataset.type === 'int' && !Number.isInteger(value))) throw new Error('请填写有效的数值。');
      }
      config[input.dataset.section][input.dataset.key] = value;
    }
    for (const input of $('settings-form').querySelectorAll('[data-secret]')) if (input.value.trim()) secrets[input.dataset.secret] = input.value;
    $('settings-form').querySelectorAll('input, textarea, select, button').forEach(node => { node.disabled = true; });
    const result = await api('/api/settings', {config, revision: settings.revision, secrets});
    settings.config = config;
    settings.revision = result.revision;
    settingsDirty = false;
    simpleKeywordsEdited = false;
    document.querySelectorAll('[data-secret]').forEach(input => { input.value = ''; });
    notice(result.message);
    await refresh();
  } finally {
    saving = false;
    $('settings-form').querySelectorAll('input, textarea, select, button').forEach(node => { node.disabled = false; });
    updateButtons();
  }
}

async function ask() {
  if (busy() || !aiEnabled()) return;
  // FileReader is asynchronous too; hold the same guard before reading attachments.
  submitting = true;
  updateButtons();
  try {
    const input = $('images');
    const images = Array.from(input.files);
    const allow = $('allow-images').checked;
    if (images.length && !allow) throw new Error('请先勾选“仅本题允许读图”。');
    if (images.length > ($('research-mode').value === 'standard' ? 1 : 2)) throw new Error('截图超过所选回答方式的数量限制。');
    const attachments = [];
    for (const file of images) {
      if (file.size > 2000000 || !file.name.toLowerCase().endsWith('.png')) throw new Error('请选择每张最多2MB的PNG。');
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(',')[1]);
        reader.onerror = () => reject(new Error('无法读取截图。'));
        reader.readAsDataURL(file);
      });
      attachments.push({data});
    }
    const scope = $('research-scope').value;
    submitting = false;
    const result = await action('research', {question: $('question').value, mode: $('research-mode').value, repo_ids: scope ? [Number(scope)] : null, allow_images: allow, attachments});
    if (result) { input.value = ''; $('allow-images').checked = false; }
  } finally {
    submitting = false;
    updateButtons();
  }
}

for (const node of document.querySelectorAll('#navigation button')) node.addEventListener('click', () => switchPage(node.dataset.page));
$('ask').classList.add('ai-button');
const questionNote = el('p', '发送新问题会使用AI额度；重看历史回答不会重新调用AI。', 'field-help');
questionNote.id = 'research-cost-note';
$('question').before(questionNote);
const setup = aiSetupButton();
setup.id = 'research-ai-setup';
$('ask').parentElement.append(setup);
$('refresh').addEventListener('click', safe(refresh));
$('scan').addEventListener('click', safe(() => action('scan')));
$('import').addEventListener('click', safe(() => action('import', {text: $('import-text').value})));
$('import-text').addEventListener('keydown', safe(async event => {
  if (event.key !== 'Enter' || event.isComposing) return;
  event.preventDefault();
  await action('import', {text: $('import-text').value});
}));
$('edit-keywords').addEventListener('click', safe(() => openSettingsCategory('检索来源')));
$('ask').addEventListener('click', safe(ask));
$('digest').addEventListener('click', safe(() => action('digest')));
for (const node of document.querySelectorAll('[data-question]')) node.addEventListener('click', () => {
  $('question').value = node.dataset.question;
  $('question').focus();
});
$('search').addEventListener('input', () => {
  clearTimeout(searchTimer);
  const query = $('search').value;
  const sequence = ++searchRequest;
  projectSearchResults = null;
  renderProjects();
  searchTimer = setTimeout(async () => {
    try {
      const result = query ? await api('/api/projects?q=' + encodeURIComponent(query)) : null;
      if (sequence !== searchRequest || $('search').value !== query) return;
      projectSearchResults = result?.projects ?? null;
      renderProjects();
    } catch (error) {
      if (sequence === searchRequest) notice(error.message, true);
    }
  }, 200);
});
$('weeks').addEventListener('change', safe(() => loadWeek(true)));
$('view-week').addEventListener('click', safe(() => loadWeek(true)));
$('settings-form').addEventListener('submit', event => event.preventDefault());
$('settings-form').addEventListener('input', markSettingsDirty);
$('settings-form').addEventListener('change', markSettingsDirty);
$('save-settings').addEventListener('click', safe(saveSettings));
$('reload-settings').addEventListener('click', safe(async () => {
  if (saving) return;
  if (settingsDirty && !window.confirm('有尚未保存的修改。重新加载会丢弃这些修改，是否继续？')) return;
  await loadSettings(true);
  notice('已重新读取保存的设置。');
}));
$('stop-server').addEventListener('click', safe(async () => {
  if (busy()) throw new Error('请先等待任务结束，或停止问答的后续步骤。');
  if (!window.confirm('停止后，此页面将断开。确认停止本机网页服务？')) return;
  const result = await api('/api/shutdown', {});
  stopped = true;
  notice(result.message);
  updateButtons();
}));
$('theme-choice').addEventListener('change', safe(async () => {
  const current = await api('/api/config');
  const choice = $('theme-choice').value;
  const result = await api('/api/settings', {config: {appearance: {theme: choice}}, revision: current.revision, secrets: {}});
  if (settings && settings.revision === current.revision) {
    settings.config.appearance.theme = choice;
    settings.revision = result.revision;
  }
  document.documentElement.dataset.theme = choice;
  notice('页面外观已保存。');
}));
for (const format of ['html', 'markdown']) $('export-' + format).addEventListener('click', safe(() => {
  const week = $('weeks').value;
  if (!week) throw new Error('请先选择已有周报。');
  window.location.assign('/api/report?week=' + encodeURIComponent(week) + '&format=' + format);
}));
for (const [id, retry] of [['send-mail', false], ['retry-mail', true]]) $(id).addEventListener('click', safe(async () => {
  const week = $('weeks').value;
  if (!week) throw new Error('请先选择已有周报。');
  if (!window.confirm(retry ? '重发可能产生重复邮件。确认已经检查原状态和收件箱？' : '将按已保存的邮件设置发送本周报，是否继续？')) return;
  await action('email', {week, retry});
}));

updateButtons();
refresh().then(() => {
  notice('已连接这台电脑上的项目库。先选择项目，或设置找项目的关键词。');
  setInterval(() => refresh().catch(error => notice(error.message, true)), 1500);
}).catch(error => notice(error.message, true));
