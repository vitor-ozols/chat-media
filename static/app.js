import { markdown } from './markdown.js';

const $ = (id) => document.getElementById(id);
const apiBase = document.body.dataset.api;
const storage = {
  read(key, fallback = null) { try { return JSON.parse(localStorage.getItem(`chat-media:${key}`)) ?? fallback; } catch { return fallback; } },
  write(key, value) { try { localStorage.setItem(`chat-media:${key}`, JSON.stringify(value)); } catch { /* Private mode or full storage. */ } },
  remove(key) { try { localStorage.removeItem(`chat-media:${key}`); } catch { /* Optional persistence. */ } },
};
const state = { thread: null, threads: [], busy: false, run: null, source: null, timer: null, view: 'chat',
  liveMessages: new Map(), activities: new Map(), panel: null, plan: null, finalNode: null,
  pinned: true, loadingThread: 0, downloads: [], downloadTimer: null, downloadLoading: false,
  bootstrap: null, lastPrompt: '', initialized: false, threadLoading: false };

function node(tag, className = '', text = '') {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

async function api(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    ...options, headers: { ...(options.body && !(options.body instanceof FormData) ? {'Content-Type': 'application/json'} : {}), ...options.headers },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || `Não foi possível concluir (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return data;
}

let toastTimer;
function toast(message) {
  $('toast').textContent = message; $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 6500);
}

function connection(label, mode = '') {
  $('connection-label').textContent = label;
  $('connection').className = `connection ${mode}`;
}

function setSidebar(open) {
  const mobile = window.matchMedia('(max-width: 760px)').matches;
  $('sidebar').inert = mobile && !open;
  $('sidebar').classList.toggle('open', open);
  $('sidebar-backdrop').hidden = !open;
  $('menu-toggle').setAttribute('aria-expanded', String(open));
  if (open) $('new-chat').focus();
  else if (mobile && $('sidebar').contains(document.activeElement)) $('menu-toggle').focus();
}

function updateControls() {
  $('send').hidden = state.busy;
  $('stop').hidden = !state.busy;
  $('send').disabled = !state.initialized || state.threadLoading || !$('prompt').value.trim();
  $('prompt').disabled = state.busy || state.threadLoading;
  $('new-chat').disabled = state.busy;
  $('model').disabled = state.busy;
  $('run-status').hidden = !state.busy;
  document.querySelectorAll('.thread-button').forEach((button) => { button.disabled = state.busy; });
}

function scrollToBottom(force = false) {
  if (state.pinned || force) {
    $('conversation').scrollTop = $('conversation').scrollHeight;
    $('jump-bottom').hidden = true;
  } else $('jump-bottom').hidden = false;
}

function titleForThread() { return state.threads.find((thread) => thread.id === state.thread)?.name || (state.thread ? 'Conversa' : 'Nova conversa'); }
function updateTitle() {
  const title = state.view === 'downloads' ? 'Downloads' : titleForThread();
  $('page-title').textContent = title;
  document.title = `${title} · Chat Media`;
}

function renderThreads() {
  const container = $('threads'); container.replaceChildren();
  const query = $('thread-search').value.trim().toLocaleLowerCase('pt-BR');
  const shown = state.threads.filter((thread) => `${thread.name} ${thread.preview || ''}`.toLocaleLowerCase('pt-BR').includes(query));
  if (!shown.length) { container.append(node('p', 'sidebar-hint', query ? 'Nenhuma conversa encontrada.' : 'Suas conversas vão aparecer aqui.')); return; }
  let lastGroup = '';
  const today = new Date().toDateString();
  for (const thread of shown) {
    const date = new Date(Number(thread.updated_at) * 1000);
    const group = date.toDateString() === today ? 'HOJE' : 'ANTERIORES';
    if (group !== lastGroup) { container.append(node('div', 'thread-date', group)); lastGroup = group; }
    const button = node('button', `thread-button${thread.id === state.thread ? ' active' : ''}`, thread.name || 'Conversa sem título');
    button.title = thread.name;
    button.disabled = state.busy;
    if (thread.id === state.thread) button.setAttribute('aria-current', 'true');
    button.addEventListener('click', () => { if (!state.busy) location.hash = `thread=${encodeURIComponent(thread.id)}`; });
    container.append(button);
  }
  updateTitle();
}

async function loadThreads() {
  $('refresh-threads').disabled = true;
  try { const data = await api('threads'); state.threads = data.threads; renderThreads(); }
  catch (error) {
    if (!state.threads.length) $('threads').replaceChildren(node('p', 'sidebar-hint', `Não foi possível carregar o histórico. ${error.message}`));
    else toast(error.message);
  } finally { $('refresh-threads').disabled = false; }
}

function addMessage(role, text = '', phase = '', live = false) {
  $('welcome').hidden = true;
  const commentary = phase === 'commentary';
  const article = node('article', `message ${role}${commentary ? ' commentary' : ''}`);
  if (role === 'assistant' && !commentary) {
    const heading = node('div', 'assistant-heading');
    heading.append(node('span', 'agent-avatar', 'C'), node('span', '', 'Codex'));
    article.append(heading);
  }
  const content = node('div', 'message-content');
  if (role === 'user') content.textContent = text;
  else content.innerHTML = markdown(text);
  article.append(content);
  const result = { article, content, text, phase };
  if (role === 'assistant' && !commentary && !live) addCopyButton(result);
  $('messages').append(article);
  scrollToBottom();
  return result;
}

function addCopyButton(message) {
  if (message.article.querySelector('.message-actions')) return;
  const actions = node('div', 'message-actions');
  const copy = node('button', 'subtle-button', 'Copiar');
  copy.addEventListener('click', async () => {
    try { await copyText(message.text); copy.textContent = '✓ Copiado'; setTimeout(() => { copy.textContent = 'Copiar'; }, 2000); }
    catch { toast('Não foi possível copiar automaticamente. Selecione o texto para copiar.'); }
  });
  actions.append(copy); message.article.append(actions);
}

async function copyText(text) {
  try {
    if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); return; }
  } catch { /* LAN deployments over HTTP use the selection fallback below. */ }
  const previous = document.activeElement;
  const textarea = node('textarea', 'sr-only');
  textarea.value = text; textarea.readOnly = true; document.body.append(textarea);
  textarea.select();
  let copied;
  try { copied = document.execCommand('copy'); }
  finally { textarea.remove(); previous?.focus({preventScroll:true}); }
  if (!copied) throw new Error('Clipboard unavailable');
}

function resetConversation() {
  $('messages').replaceChildren(); $('welcome').hidden = false;
  state.liveMessages.clear(); state.activities.clear(); state.panel = null; state.plan = null; state.finalNode = null;
  state.pinned = true; $('jump-bottom').hidden = true;
}

async function openThread(threadId, recovery = null) {
  const requestId = ++state.loadingThread;
  state.thread = threadId;
  state.threadLoading = !!threadId;
  updateControls();
  storage.write('thread', threadId);
  resetConversation(); renderThreads(); updateTitle();
  if (!threadId) return;
  $('welcome').hidden = true;
  const loading = node('p', 'turn-outcome', 'Carregando conversa…'); $('messages').append(loading);
  try {
    const data = await api(`threads/${encodeURIComponent(threadId)}/messages`);
    if (requestId !== state.loadingThread) return;
    loading.remove();
    let messages = data.messages;
    // A running turn may already have persisted its user message and final answer.
    // Replay that turn from its events instead of rendering it twice on reload.
    if (recovery) {
      const lastUser = messages.findLastIndex((message) => message.role === 'user');
      if (lastUser >= 0 && messages[lastUser].content === recovery.prompt) messages = messages.slice(0, lastUser);
    }
    for (const message of messages) addMessage(message.role, message.content);
    if (!messages.length && !recovery) $('welcome').hidden = false;
    scrollToBottom(true);
  } catch (error) {
    if (requestId === state.loadingThread) { loading.remove(); showOutcome(`Não foi possível abrir esta conversa: ${error.message}`, true); }
  } finally {
    if (requestId === state.loadingThread) { state.threadLoading = false; updateControls(); }
  }
}

function route() {
  const hash = location.hash.slice(1);
  const view = hash === 'torrents' || (!hash && location.pathname.endsWith('/torrents')) ? 'downloads' : 'chat';
  state.view = view;
  $('chat-view').hidden = view !== 'chat'; $('downloads-view').hidden = view !== 'downloads';
  $('chat-nav').classList.toggle('active', view === 'chat'); $('torrents-nav').classList.toggle('active', view === 'downloads');
  $('section-label').textContent = view === 'downloads' ? 'DOWNLOADS' : 'CONVERSAS';
  setSidebar(false);
  clearTimeout(state.downloadTimer);
  if (view === 'downloads') refreshDownloads();
  else if (!state.busy && hash.startsWith('thread=')) {
    let threadId;
    try { threadId = decodeURIComponent(hash.slice(7)); } catch { return; }
    if (threadId !== state.thread) openThread(threadId);
  }
  updateTitle();
}

function ensureActivities() {
  if (state.panel) return;
  const panel = node('details', 'activity-panel');
  const summary = node('summary');
  summary.append(node('span', 'spinner'), node('span', 'activity-summary', 'Atividade do agente'));
  const list = node('div', 'activity-list'); panel.append(summary, list);
  $('messages').append(panel); state.panel = { panel, summary, list };
}

function renderActivity(event) {
  ensureActivities();
  let activity = state.activities.get(event.id);
  if (!activity) {
    const row = node('div', 'activity-row');
    const symbol = node('span', 'activity-symbol');
    const body = node('div'); const label = node('span'); const detail = node('code');
    body.append(label, detail); row.append(symbol, body); state.panel.list.append(row);
    activity = { row, symbol, label, detail }; state.activities.set(event.id, activity);
  }
  const failed = ['failed', 'declined', 'error'].includes(event.status);
  activity.row.className = `activity-row ${event.done ? failed ? 'failed' : 'completed' : 'running'}`;
  activity.symbol.textContent = event.done ? failed ? '!' : '✓' : '◌';
  activity.label.textContent = event.label;
  activity.detail.textContent = event.detail || ''; activity.detail.hidden = !event.detail;
  state.panel.summary.querySelector('.activity-summary').textContent = `${state.activities.size} atividade${state.activities.size === 1 ? '' : 's'} · ${event.done ? event.label : `${event.label}…`}`;
  if (!event.done) $('run-label').textContent = event.label;
  scrollToBottom();
}

let renderFrame;
const dirtyMessages = new Set();
function flushMessages() {
  renderFrame = null;
  for (const message of dirtyMessages) message.content.innerHTML = markdown(message.text);
  dirtyMessages.clear(); scrollToBottom();
}

function renderLiveMessage(event) {
  let message = state.liveMessages.get(event.id);
  if (!message) { message = addMessage('assistant', '', event.phase, true); state.liveMessages.set(event.id, message); }
  const phase = event.phase || message.phase;
  if (phase !== message.phase) {
    message.phase = phase;
    message.article.classList.toggle('commentary', phase === 'commentary');
    if (phase === 'commentary') message.article.querySelector('.assistant-heading')?.remove();
  }
  message.text = event.text ?? (message.text + (event.delta || ''));
  if (phase !== 'commentary') state.finalNode = message;
  else if (state.finalNode === message) state.finalNode = null;
  dirtyMessages.add(message);
  if (!renderFrame) renderFrame = requestAnimationFrame(flushMessages);
  $('run-label').textContent = phase === 'commentary' ? 'O agente está trabalhando' : 'Escrevendo resposta';
}

function renderPlan(event) {
  if (!state.plan) { state.plan = node('div', 'plan'); $('messages').append(state.plan); }
  state.plan.replaceChildren();
  if (event.explanation) state.plan.append(node('p', '', event.explanation));
  for (const step of event.steps) {
    const row = node('div', `plan-step ${step.status}`);
    row.append(node('span', '', step.status === 'completed' ? '✓' : ['inProgress', 'in_progress'].includes(step.status) ? '◌' : '○'), node('span', '', step.step));
    state.plan.append(row);
  }
  scrollToBottom();
}

function showOutcome(text, error = false, retry = false) {
  const outcome = node('div', `turn-outcome${error ? ' error' : ''}`, text);
  if (retry) {
    const button = node('button', '', 'Editar e tentar novamente');
    button.addEventListener('click', () => { $('prompt').value = state.lastPrompt; resizePrompt(); $('prompt').focus(); updateControls(); });
    outcome.append(button);
  }
  $('messages').append(outcome); scrollToBottom();
}

function finishRun(event) {
  if (!state.busy) return;
  state.source?.close(); state.source = null;
  clearInterval(state.timer);
  if (renderFrame) { cancelAnimationFrame(renderFrame); flushMessages(); }
  if (event.thread_id) { state.thread = event.thread_id; storage.write('thread', state.thread); }
  if (event.type === 'done') {
    if (state.finalNode) {
      state.finalNode.text = event.reply;
      state.finalNode.content.innerHTML = markdown(event.reply);
      addCopyButton(state.finalNode);
    } else addMessage('assistant', event.reply);
    showOutcome('✓ Concluído');
  } else if (event.type === 'cancelled') showOutcome('Execução interrompida. Você pode continuar a conversa.');
  else showOutcome(event.error || 'A execução terminou com erro.', true, true);
  if (state.panel) {
    state.panel.summary.querySelector('.spinner')?.remove();
    const count = state.activities.size;
    state.panel.summary.querySelector('.activity-summary').textContent = `${count} atividade${count === 1 ? '' : 's'} · ${event.type === 'done' ? count === 1 ? 'concluída' : 'concluídas' : event.type === 'cancelled' ? 'execução interrompida' : 'execução com erro'}`;
    state.panel.list.querySelectorAll('.running').forEach((row) => { row.classList.remove('running'); row.querySelector('.activity-symbol').textContent = '–'; });
  }
  state.busy = false; state.run = null;
  storage.remove('active-run');
  connection(navigator.onLine ? 'Pronto para ajudar' : 'Sem conexão', navigator.onLine ? '' : 'offline');
  $('stop').disabled = false; $('stop').lastChild.textContent = ' Parar';
  updateControls();
  loadThreads();
  if (state.thread && state.view === 'chat') history.replaceState(null, '', `#thread=${encodeURIComponent(state.thread)}`);
  scrollToBottom();
}

function handleEvent(event) {
  if (event.type === 'thread') {
    state.thread = event.thread_id; state.run.thread = event.thread_id;
    storage.write('thread', state.thread); storage.write('active-run', state.run);
  } else if (event.type === 'status') $('run-label').textContent = event.label;
  else if (event.type === 'activity') renderActivity(event);
  else if (event.type === 'message') renderLiveMessage(event);
  else if (event.type === 'plan') renderPlan(event);
  else if (event.type === 'snapshot') {
    for (const message of state.liveMessages.values()) message.article.remove();
    state.liveMessages.clear(); state.activities.clear(); state.panel?.panel.remove(); state.panel = null; state.finalNode = null;
    state.plan?.remove(); state.plan = null;
    if (event.thread_id) handleEvent({type: 'thread', thread_id: event.thread_id});
    for (const activity of event.activities) renderActivity(activity);
    if (event.plan) renderPlan(event.plan);
    for (const message of event.messages) renderLiveMessage(message);
  } else if (['done', 'failure', 'cancelled'].includes(event.type)) finishRun(event);
}

function connectRun(run) {
  state.run = run; state.busy = true; state.lastPrompt = run.prompt;
  state.liveMessages.clear(); state.activities.clear(); state.panel = null; state.plan = null; state.finalNode = null;
  storage.write('active-run', run);
  connection('Agente em ação', 'busy');
  $('run-label').textContent = 'Conectando ao agente';
  const tick = () => { const seconds = Math.max(0, Math.floor((Date.now() - run.started) / 1000)); $('run-time').textContent = seconds >= 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${seconds}s`; };
  tick(); state.timer = setInterval(tick, 1000);
  updateControls();
  const source = new EventSource(`${apiBase}runs/${encodeURIComponent(run.id)}/events`);
  state.source = source;
  source.onmessage = (message) => {
    try { handleEvent(JSON.parse(message.data)); }
    catch (error) { console.error('Falha ao exibir evento do agente', error); }
  };
  source.onopen = () => { if (state.busy) connection('Agente em ação', 'busy'); };
  source.onerror = async () => {
    if (!state.busy || state.source !== source) return;
    connection('Reconectando…', 'offline');
    $('run-label').textContent = 'Conexão interrompida. Tentando reconectar…';
    try { await api(`runs/${encodeURIComponent(run.id)}`); }
    catch (error) { if (error.status === 404 && state.source === source) finishRun({type: 'failure', error: 'A execução não está mais disponível. O serviço pode ter sido reiniciado; reabra a conversa pelo histórico.'}); }
  };
}

function resizePrompt() {
  $('prompt').style.height = 'auto'; $('prompt').style.height = `${Math.min($('prompt').scrollHeight, 180)}px`;
}

async function submitPrompt(event) {
  event.preventDefault();
  const prompt = $('prompt').value.trim();
  if (!prompt || state.busy || state.threadLoading || !state.initialized) return;
  state.busy = true; updateControls();
  try {
    const data = await api('runs', {method: 'POST', body: JSON.stringify({prompt, thread_id: state.thread,
      model: $('model').value || null, effort: $('effort').value, sandbox: $('sandbox').value})});
    state.pinned = true; addMessage('user', prompt);
    $('prompt').value = ''; storage.remove('draft'); resizePrompt();
    connectRun({id: data.id, prompt, thread: state.thread, started: Date.now()});
  } catch (error) { state.busy = false; updateControls(); toast(error.message); $('prompt').focus(); }
}

function newChat() {
  if (state.busy) return;
  state.loadingThread++;
  state.threadLoading = false;
  state.thread = null; storage.remove('thread');
  history.replaceState(null, '', apiBase.replace(/api\/$/, ''));
  resetConversation(); route(); renderThreads(); updateTitle();
  updateControls();
  $('prompt').focus();
}

function openSettings() { $('settings-dialog').showModal(); }

async function bootstrap() {
  try {
    const data = await api('bootstrap'); state.bootstrap = data;
    $('sdk-status').textContent = data.available ? 'Agente conectado' : 'SDK indisponível';
    connection(data.available ? 'Pronto para ajudar' : 'Agente indisponível', data.available ? '' : 'offline');
    const selected = storage.read('model', '');
    for (const model of data.models) $('model').append(new Option(model.name || model.id, model.id));
    if (selected && !data.models.some((model) => model.id === selected)) $('model').append(new Option(selected, selected));
    $('model').value = selected;
    $('skills-count').textContent = String(data.skills.length);
    $('skills-list').replaceChildren();
    for (const skill of data.skills) {
      const button = node('button', 'skill-button', `$${skill.name}`);
      button.addEventListener('click', () => {
        if (state.busy) { toast('Aguarde a execução atual para enviar outra mensagem.'); return; }
        $('prompt').value = `${$('prompt').value}${$('prompt').value ? ' ' : ''}$${skill.name} `;
        $('settings-dialog').close(); location.hash = state.thread ? `thread=${encodeURIComponent(state.thread)}` : 'chat';
        resizePrompt(); updateControls(); $('prompt').focus();
      });
      $('skills-list').append(button);
    }
    if (!data.skills.length) $('skills-list').append(node('p', 'field-hint', 'Nenhuma skill instalada neste ambiente.'));
    $('download-dir').value = data.download_dir;
    if (data.model_error) toast(`Não foi possível carregar os modelos: ${data.model_error}`);
  } catch (error) { connection('Falha ao conectar', 'offline'); toast(error.message); }
  finally { state.initialized = true; updateControls(); }
}

const statusLabels = {queued:'Na fila', fetching_metadata:'Buscando metadados', checking:'Verificando', downloading:'Baixando', seeding:'Compartilhando', paused:'Pausado', completed:'Concluído', error:'Com erro'};
function bytes(value) {
  if (!value) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.max(0, Math.min(4, Math.floor(Math.log(value) / Math.log(1024))));
  return `${(value / 1024 ** index).toLocaleString('pt-BR', {maximumFractionDigits: index > 1 ? 1 : 0})} ${units[index]}`;
}
const isActive = (item) => ['queued', 'fetching_metadata', 'checking', 'downloading', 'seeding'].includes(item.status);
function renderDownloads() {
  const query = $('download-search').value.trim().toLocaleLowerCase('pt-BR');
  const filter = $('download-filter').value;
  const rows = state.downloads.filter((item) => item.name.toLocaleLowerCase('pt-BR').includes(query) &&
    (filter === 'all' || (filter === 'active' ? isActive(item) : filter === 'completed' ? item.progress >= 1 : item.status === filter)));
  const container = $('download-list'); container.replaceChildren();
  if (!rows.length) {
    const empty = node('div', 'download-empty');
    empty.append(node('span', '', '↓'), node('h3', '', state.downloads.length ? 'Nenhum resultado por aqui' : 'Sua próxima descoberta começa aqui'),
      node('p', '', state.downloads.length ? 'Experimente outro nome ou filtro.' : 'Adicione um link magnet ou arquivo .torrent para começar.'));
    container.append(empty); return;
  }
  for (const item of rows) {
    const card = node('article', 'torrent-card');
    const heading = node('div', 'torrent-heading');
    heading.append(node('h3', '', item.name), node('span', `torrent-status ${item.status}`, statusLabels[item.status] || item.status));
    const progress = node('div', 'torrent-progress');
    const bar = document.createElement('progress'); bar.max = 1; bar.value = Math.max(0, Math.min(1, item.progress)); bar.setAttribute('aria-label', `Progresso de ${item.name}`);
    progress.append(bar, node('span', '', `${(item.progress * 100).toFixed(1)}%`));
    const meta = node('div', 'torrent-meta');
    for (const text of [`${bytes(item.downloaded)} de ${bytes(item.total_size)}`, `↓ ${bytes(item.download_rate)}/s`, `↑ ${bytes(item.upload_rate)}/s`, `${item.peers} peers`, item.eta_seconds ? `~${Math.ceil(item.eta_seconds / 60)} min` : '']) if (text) meta.append(node('span', '', text));
    const actions = node('div', 'torrent-actions');
    for (const [action, label] of [[item.status === 'paused' || item.status === 'error' ? 'resume' : 'pause', item.status === 'paused' || item.status === 'error' ? '▶ Retomar' : 'Ⅱ Pausar'], ['restart', '↻ Reiniciar'], ['recheck', 'Verificar'], ['files', 'Arquivos'], ['remove', 'Remover da fila']]) {
      const button = node('button', '', label);
      button.addEventListener('click', async () => {
        if (action === 'files') { showTorrentFiles(item); return; }
        button.disabled = true;
        try { await api(`torrents/${encodeURIComponent(item.id)}/${action}`, {method: 'POST'}); toast(action === 'remove' ? 'Torrent removido da fila. Os arquivos foram preservados.' : 'Ação aplicada.'); await refreshDownloads(true); }
        catch (error) { toast(error.message); button.disabled = false; }
      });
      actions.append(button);
    }
    card.append(heading, progress, meta, node('div', 'torrent-path', item.download_dir));
    if (item.error_message) card.append(node('p', 'torrent-error', item.error_message));
    card.append(actions); container.append(card);
  }
}

async function refreshDownloads(force = false) {
  clearTimeout(state.downloadTimer);
  if (document.hidden || state.view !== 'downloads' || state.downloadLoading) return;
  state.downloadLoading = true; $('refresh-downloads').disabled = true;
  try {
    const data = await api('torrents'); state.downloads = data.torrents;
    // Keep focused action buttons stable between background updates.
    if (force || !$('download-list').contains(document.activeElement)) renderDownloads();
    $('download-stats').replaceChildren();
    for (const [label, value, unit] of [['Na fila', data.torrents.length, 'torrents'], ['Em andamento', data.torrents.filter(isActive).length, 'ativos'], ['Download', bytes(data.engine.download_rate), '/s'], ['Upload', bytes(data.engine.upload_rate), '/s']]) {
      const stat = node('div', 'stat'); stat.append(node('span', '', label), node('strong', '', String(value)), document.createTextNode(' '), node('small', '', unit)); $('download-stats').append(stat);
    }
    $('engine-notice').hidden = data.engine.available;
    $('engine-notice').textContent = data.engine.message;
    $('engine-events').replaceChildren();
    for (const event of data.events) {
      const row = node('div', 'engine-event');
      row.append(node('time', '', new Date(event.created_at).toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'})), node('span', '', event.message)); $('engine-events').append(row);
    }
  } catch (error) { $('engine-notice').hidden = false; $('engine-notice').textContent = `Falha ao atualizar: ${error.message}`; }
  finally { state.downloadLoading = false; $('refresh-downloads').disabled = false; if (state.view === 'downloads' && !document.hidden) state.downloadTimer = setTimeout(refreshDownloads, 4000); }
}

async function showTorrentFiles(item) {
  $('files-dialog').showModal(); $('torrent-file-list').textContent = 'Carregando arquivos…';
  try {
    const data = await api(`torrents/${encodeURIComponent(item.id)}/files`);
    $('torrent-file-list').replaceChildren();
    if (!data.files.length) $('torrent-file-list').append(node('p', 'field-hint', 'Os arquivos aparecem quando os metadados do torrent estiverem disponíveis.'));
    for (const file of data.files) { const row = node('div', 'file-row', file.path); row.append(node('small', '', `${bytes(file.size)} · ${(file.progress * 100).toFixed(1)}%`)); $('torrent-file-list').append(row); }
  } catch (error) { $('torrent-file-list').textContent = error.message; }
}

$('menu-toggle').addEventListener('click', () => setSidebar(!$('sidebar').classList.contains('open')));
$('sidebar-backdrop').addEventListener('click', () => setSidebar(false));
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') setSidebar(false);
  if (event.altKey && event.key.toLowerCase() === 'n') { event.preventDefault(); newChat(); }
});
$('new-chat').addEventListener('click', newChat);
document.querySelector('.brand').addEventListener('click', (event) => { event.preventDefault(); if (!state.busy) newChat(); else { location.hash = state.thread ? `thread=${encodeURIComponent(state.thread)}` : 'chat'; route(); } });
$('chat-nav').addEventListener('click', () => { location.hash = state.thread ? `thread=${encodeURIComponent(state.thread)}` : 'chat'; route(); });
$('torrents-nav').addEventListener('click', () => { location.hash = 'torrents'; });
$('thread-search').addEventListener('input', renderThreads);
$('refresh-threads').addEventListener('click', loadThreads);
$('settings-open').addEventListener('click', openSettings);
$('composer-settings').addEventListener('click', openSettings);
$('skills-suggestion').addEventListener('click', openSettings);
document.querySelectorAll('[data-close-dialog]').forEach((button) => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach((dialog) => dialog.addEventListener('click', (event) => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close(); } }));
document.querySelectorAll('[data-prompt]').forEach((button) => button.addEventListener('click', () => { $('prompt').value = button.dataset.prompt; resizePrompt(); updateControls(); $('prompt').focus(); }));
$('composer').addEventListener('submit', submitPrompt);
$('prompt').addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('composer').requestSubmit(); } });
$('prompt').addEventListener('input', () => { resizePrompt(); updateControls(); storage.write('draft', $('prompt').value); });
for (const [id, fallback, allowed] of [['effort', 'medium', ['low','medium','high','xhigh']], ['sandbox', 'full', ['read','write','full']]]) {
  const saved = storage.read(id, fallback); $(id).value = allowed.includes(saved) ? saved : fallback;
  $(id).addEventListener('change', () => storage.write(id, $(id).value));
}
$('model').addEventListener('change', () => storage.write('model', $('model').value));
$('stop').addEventListener('click', async () => {
  if (!state.run) return;
  $('stop').disabled = true; $('stop').lastChild.textContent = ' Parando…';
  try { await api(`runs/${encodeURIComponent(state.run.id)}/cancel`, {method:'POST'}); if (state.busy) $('run-label').textContent = 'Interrompendo execução…'; }
  catch (error) { toast(error.message); $('stop').disabled = false; $('stop').lastChild.textContent = ' Parar'; }
});
$('conversation').addEventListener('scroll', () => {
  const element = $('conversation'); state.pinned = element.scrollHeight - element.scrollTop - element.clientHeight < 100;
  if (state.pinned) $('jump-bottom').hidden = true;
}, {passive:true});
$('jump-bottom').addEventListener('click', () => { state.pinned = true; scrollToBottom(true); });
$('add-download-open').addEventListener('click', () => $('download-dialog').showModal());
$('refresh-downloads').addEventListener('click', refreshDownloads);
$('download-search').addEventListener('input', renderDownloads);
$('download-filter').addEventListener('change', renderDownloads);
$('download-form').addEventListener('submit', async (event) => {
  event.preventDefault(); $('download-form-error').textContent = '';
  const button = $('download-form').querySelector('button[type=submit]'); button.disabled = true;
  try {
    const files = $('torrent-files').files;
    const magnets = $('magnets').value.split('\n').map((value) => value.trim()).filter(Boolean);
    if (!files.length && !magnets.length) throw new Error('Informe um magnet ou selecione um arquivo .torrent.');
    if (files.length && magnets.length) throw new Error('Adicione links magnet ou arquivos em cada envio.');
    if (files.length) {
      const form = new FormData(); for (const file of files) form.append('files', file);
      form.append('download_dir', $('download-dir').value); form.append('start_paused', String($('start-paused').checked));
      await api('torrents', {method:'POST', body:form});
    } else await api('torrents', {method:'POST', body:JSON.stringify({magnets, download_dir:$('download-dir').value, start_paused:$('start-paused').checked})});
    $('download-dialog').close(); $('magnets').value = ''; $('torrent-files').value = '';
    toast('Torrent adicionado à fila.'); refreshDownloads(true);
  } catch (error) { $('download-form-error').textContent = error.message; }
  finally { button.disabled = false; }
});
window.addEventListener('hashchange', route);
window.matchMedia('(max-width: 760px)').addEventListener('change', () => setSidebar(false));
window.addEventListener('offline', () => connection('Sem conexão', 'offline'));
window.addEventListener('online', () => { connection(state.busy ? 'Reconectando…' : 'Pronto para ajudar', state.busy ? 'busy' : ''); if (state.view === 'downloads') refreshDownloads(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) clearTimeout(state.downloadTimer); else if (state.view === 'downloads') refreshDownloads(); });

async function init() {
  $('prompt').value = storage.read('draft', ''); resizePrompt(); updateControls();
  const saved = storage.read('active-run');
  const recovery = saved && typeof saved.id === 'string' && typeof saved.prompt === 'string' && Number.isFinite(saved.started) ? saved : null;
  state.busy = !!recovery;
  let hashThread = null;
  try { if (location.hash.startsWith('#thread=')) hashThread = decodeURIComponent(location.hash.slice(8)); } catch { /* Invalid bookmark. */ }
  const thread = recovery?.thread || hashThread || storage.read('thread');
  state.thread = thread;
  const setup = bootstrap(); const history = loadThreads();
  route();
  await openThread(thread, recovery);
  if (recovery) { addMessage('user', recovery.prompt); connectRun(recovery); }
  await Promise.allSettled([setup, history]);
  updateControls();
}
init();
