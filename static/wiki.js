// Local Wikipedia: dump explorer and a Gemma chat grounded on it.
import { markdown } from './markdown.js';

const $ = (id) => document.getElementById(id);
const escape = (text) => String(text).replace(/[&<>"']/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
const LINK = /⟦([^❘⟧]*)❘([^⟧]*)⟧/g;
const storage = {
  read(key, fallback = null) { try { return JSON.parse(localStorage.getItem(`chat-media:wiki-${key}`)) ?? fallback; } catch { return fallback; } },
  write(key, value) { try { localStorage.setItem(`chat-media:wiki-${key}`, JSON.stringify(value)); } catch { /* Optional. */ } },
};

let ctx;  // {apiBase, api, node, toast, setTitle}
const wiki = { status: null, statusLoading: null, article: null, results: [], history: storage.read('history', []),
  busy: false, controller: null, pinned: null, timer: null, suggestTimer: null, lastQuery: '' };

const hashLink = (title) => `#wiki=${encodeURIComponent(title)}`;
const bytes = (value) => {
  if (!value) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.max(0, Math.min(4, Math.floor(Math.log(value) / Math.log(1024))));
  return `${(value / 1024 ** index).toLocaleString('pt-BR', {maximumFractionDigits: index > 1 ? 1 : 0})} ${units[index]}`;
};
const number = (value) => Number(value || 0).toLocaleString('pt-BR');
const dumpName = () => $('wiki-dump').value || '';
const withDump = (path) => `${path}${path.includes('?') ? '&' : '?'}dump=${encodeURIComponent(dumpName())}`;

function wikiHtml(text) {
  // Text is escaped first; only our own link marks become anchors.
  return escape(text).replace(LINK, (_, target, label) => `<a class="wiki-link" href="${escape(hashLink(target))}">${label}</a>`);
}

function paragraphHtml(paragraph) {
  const lines = paragraph.split('\n');
  if (lines.every((line) => line.startsWith('- '))) return `<ul>${lines.map((line) => `<li>${wikiHtml(line.slice(2))}</li>`).join('')}</ul>`;
  return `<p>${lines.map(wikiHtml).join('<br>')}</p>`;
}

// ---------------------------------------------------------------- status
async function loadStatus(force = false) {
  if (wiki.status && !force) return wiki.status;
  if (!wiki.statusLoading) {
    wiki.statusLoading = ctx.api('wiki/status').then((data) => {
      wiki.status = data; renderStatus(); return data;
    }).finally(() => { wiki.statusLoading = null; });
  }
  return wiki.statusLoading;
}

function renderStatus() {
  const data = wiki.status;
  const ready = data.dumps.filter((dump) => dump.ready);
  const saved = storage.read('dump', '');
  for (const select of [$('wiki-dump'), $('wiki-chat-dump')]) {
    const current = select.value || saved;
    select.replaceChildren(...ready.map((dump) => new Option(dump.dbname || dump.name, dump.name)));
    if (ready.some((dump) => dump.name === current)) select.value = current;
    select.disabled = ready.length < 2;
  }
  const dump = ready.find((item) => item.name === dumpName()) || ready[0];
  $('wiki-stats').replaceChildren();
  if (dump) {
    const built = new Date(Number(dump.dump_mtime) * 1000).toLocaleDateString('pt-BR');
    for (const [label, value, unit] of [['Artigos', number(dump.articles), dump.dbname], ['Redirecionamentos', number(dump.redirects), 'títulos alternativos'],
      ['Dump comprimido', bytes(dump.dump_bytes), `de ${built}`], ['Índice SQLite', bytes(dump.db_bytes), `${number(dump.blocks)} blocos bz2`]]) {
      const stat = ctx.node('div', 'stat'); stat.append(ctx.node('span', '', label), ctx.node('strong', '', String(value)), document.createTextNode(' '), ctx.node('small', '', unit));
      $('wiki-stats').append(stat);
    }
  }
  const problems = [];
  if (!ready.length) problems.push(`Nenhum dump indexado em ${data.root}. Baixe um *-pages-articles-multistream e rode python -m wiki.build (veja o README).`);
  for (const item of data.dumps) if (item.building) problems.push(`${item.name}: construindo índice (${item.building}).`);
  if (data.model_error) problems.push(data.model_error);
  else if (!data.model_ready) problems.push(`O modelo ${data.model} não está baixado no Ollama. Rode: ollama pull ${data.model}`);
  $('wiki-notice').hidden = !problems.length; $('wiki-notice').textContent = problems.join(' ');
  $('wiki-random').disabled = !ready.length;
  $('wiki-model-label').textContent = `${data.model.toUpperCase()} · ${data.model_ready ? 'PRONTO' : 'INDISPONÍVEL'}`;
  $('wiki-model-hint').textContent = `${data.model} via Ollama`;
  $('wiki-use').disabled = !ready.length;
  if (!ready.length) $('wiki-use').checked = false;
}

// -------------------------------------------------------------- explorer
// While reading or searching, the overview (stats, intro) gets out of the way.
function reading(on) { $('wiki-view').classList.toggle('wiki-reading', on); }
function renderResults(query) {
  const container = $('wiki-results'); container.replaceChildren();
  if (!query) return;
  if (!wiki.results.length) {
    const empty = ctx.node('div', 'download-empty');
    empty.append(ctx.node('span', '', 'W'), ctx.node('h3', '', 'Nada encontrado'), ctx.node('p', '', 'O dump está em inglês: tente o termo em inglês ou outra grafia.'));
    container.append(empty); return;
  }
  container.append(ctx.node('p', 'wiki-results-count', `${wiki.results.length} resultado${wiki.results.length === 1 ? '' : 's'} para “${query}”`));
  for (const item of wiki.results) {
    const link = ctx.node('a', 'wiki-result');
    link.href = hashLink(item.title);
    const heading = ctx.node('div', 'torrent-heading');
    heading.append(ctx.node('h3', '', item.title), ctx.node('span', 'wiki-size', bytes(item.size)));
    link.append(heading);
    if (item.via) link.append(ctx.node('small', 'wiki-via', `via “${item.via}”`));
    link.append(ctx.node('p', '', item.lead || 'Sem resumo.'));
    container.append(link);
  }
}

async function search(query) {
  query = query.trim();
  $('wiki-article').hidden = true; wiki.article = null; reading(!!query);
  $('wiki-query').value = query; wiki.lastQuery = query;
  ctx.setTitle(query ? `Busca: ${query}` : 'Wikipédia');
  if (!query) { renderResults(''); return; }
  $('wiki-results').replaceChildren(ctx.node('p', 'wiki-results-count', 'Buscando…'));
  try {
    const data = await ctx.api(withDump(`wiki/search?q=${encodeURIComponent(query)}&limit=20`));
    if (query !== wiki.lastQuery) return;
    wiki.results = data.results; renderResults(query);
  } catch (error) { $('wiki-results').replaceChildren(ctx.node('p', 'notice', error.message)); }
}

async function openArticle(title, raw = false) {
  const container = $('wiki-article');
  $('wiki-results').replaceChildren(); container.hidden = false; reading(true);
  container.replaceChildren(ctx.node('p', 'wiki-results-count', `Lendo “${title}” do dump…`));
  ctx.setTitle(title);
  try {
    const data = await ctx.api(withDump(`wiki/article?title=${encodeURIComponent(title)}${raw ? '&raw=1' : ''}`));
    wiki.article = data; renderArticle(data);
    $('wiki-view').scrollTop = 0;
  } catch (error) {
    container.replaceChildren(ctx.node('p', 'notice', error.message));
  }
}

function renderArticle(data) {
  const container = $('wiki-article');
  const toc = data.sections.filter((section) => section.title);
  const header = `<header class="wiki-article-header"><span class="eyebrow">${escape(dumpName().toUpperCase())} · ${escape(bytes(data.size))} DE WIKITEXTO</span>
    <h2>${escape(data.title)}</h2>${data.redirected_from ? `<p class="wiki-via">Redirecionado de “${escape(data.redirected_from)}”</p>` : ''}
    <div class="wiki-article-actions"><button class="primary-button" data-wiki-ask>✦ Perguntar sobre este artigo</button>
    <button class="subtle-button" data-wiki-raw>${data.wikitext ? 'Ocultar wikitexto' : '{ } Ver wikitexto'}</button>
    ${data.url ? `<a class="subtle-button" href="${escape(data.url)}" target="_blank" rel="noopener noreferrer">Abrir online ↗</a>` : ''}
    <button class="subtle-button" data-wiki-back>← Voltar à busca</button></div></header>`;
  const infobox = data.infobox.length ? `<aside class="wiki-infobox"><h3>Dados</h3><dl>${data.infobox.map((line) => {
    const [key, ...rest] = line.split(': ');
    return `<dt>${escape(key)}</dt><dd>${escape(rest.join(': '))}</dd>`;
  }).join('')}</dl></aside>` : '';
  const nav = toc.length > 2 ? `<nav class="wiki-toc" aria-label="Seções">${toc.map((section, index) => `<a href="#" data-section="${index}" class="level-${section.level}">${escape(section.title)}</a>`).join('')}</nav>` : '';
  let index = 0;
  const body = data.sections.map((section) => {
    const heading = section.title ? `<h${Math.min(5, section.level + 1)} id="wiki-section-${index++}">${escape(section.title)}</h${Math.min(5, section.level + 1)}>` : '';
    return heading + section.paragraphs.map(paragraphHtml).join('');
  }).join('');
  const raw = data.wikitext ? `<details class="wiki-raw" open><summary>Wikitexto original</summary><pre>${escape(data.wikitext)}</pre></details>` : '';
  container.innerHTML = `${header}<div class="wiki-article-layout"><div class="wiki-article-body">${raw}${body || '<p>Artigo vazio.</p>'}</div>${infobox || nav ? `<div class="wiki-side">${infobox}${nav}</div>` : ''}</div>`;
  container.querySelector('[data-wiki-ask]').addEventListener('click', () => { pin(data.title); location.hash = 'wiki-chat'; });
  container.querySelector('[data-wiki-raw]').addEventListener('click', () => openArticle(data.title, !data.wikitext));
  container.querySelector('[data-wiki-back]').addEventListener('click', () => { location.hash = wiki.lastQuery ? `wiki-search=${encodeURIComponent(wiki.lastQuery)}` : 'wiki'; });
  container.querySelectorAll('[data-section]').forEach((link) => link.addEventListener('click', (event) => {
    event.preventDefault(); $(`wiki-section-${link.dataset.section}`)?.scrollIntoView({behavior: 'smooth', block: 'start'});
  }));
}

async function suggest() {
  const value = $('wiki-query').value.trim();
  if (value.length < 2 || !wiki.status?.dumps.some((dump) => dump.ready)) return;
  try {
    const data = await ctx.api(withDump(`wiki/suggest?q=${encodeURIComponent(value)}`));
    $('wiki-suggestions').replaceChildren(...data.titles.map((title) => new Option(title)));
  } catch { /* Suggestions are optional. */ }
}

// ------------------------------------------------------------------ chat
function pin(title) {
  wiki.pinned = title;
  $('wiki-pinned').hidden = !title; $('wiki-pinned-title').textContent = title || '';
  if (title) { $('wiki-use').checked = true; $('wiki-prompt').placeholder = `Pergunte sobre ${title}…`; }
  else $('wiki-prompt').placeholder = 'O que você quer saber?';
}

function scrollChat() { $('wiki-conversation').scrollTop = $('wiki-conversation').scrollHeight; }

function addMessage(role, text = '', sources = null) {
  $('wiki-welcome').hidden = true;
  const article = ctx.node('article', `message ${role}`);
  if (role === 'assistant') {
    const heading = ctx.node('div', 'assistant-heading');
    heading.append(ctx.node('span', 'agent-avatar wiki-avatar', 'G'), ctx.node('span', '', 'Gemma'));
    article.append(heading);
  }
  const content = ctx.node('div', 'message-content');
  const message = {article, content, text, sources: sources || []};
  renderMessage(message);
  article.append(content);
  $('wiki-messages').append(article); scrollChat();
  return message;
}

function renderMessage(message) {
  if (message.article.classList.contains('user')) { message.content.textContent = message.text; return; }
  const bySource = new Map(message.sources.map((source) => [String(source.n), source]));
  message.content.innerHTML = markdown(message.text || '…').replace(/\\?\[(\d{1,2})\]/g, (match, n) => {
    const source = bySource.get(n);
    return source ? `<a class="wiki-cite" href="${escape(hashLink(source.title))}" title="${escape(source.title)}">${n}</a>` : match;
  });
}

function renderSources(message, info = '') {
  message.article.querySelector('.wiki-sources')?.remove();
  if (!message.sources.length && !info) return;
  const box = ctx.node('div', 'wiki-sources');
  if (message.sources.length) {
    box.append(ctx.node('span', 'eyebrow', 'CONTEXTO'));
    for (const source of message.sources) {
      const link = ctx.node('a', 'wiki-source', `${source.n} · ${source.title}`);
      link.href = hashLink(source.title);
      link.title = `${source.chars} caracteres enviados ao modelo${source.via ? ` · via ${source.via}` : ''}`;
      box.append(link);
    }
  }
  if (info) box.append(ctx.node('small', 'wiki-stats-line', info));
  message.article.append(box);
}

function setBusy(busy) {
  wiki.busy = busy;
  $('wiki-send').hidden = busy; $('wiki-stop').hidden = !busy;
  $('wiki-prompt').disabled = busy; $('wiki-clear').disabled = busy;
  $('wiki-run-status').hidden = !busy;
  $('wiki-send').disabled = !$('wiki-prompt').value.trim();
  clearInterval(wiki.timer);
  if (busy) {
    const started = Date.now();
    const tick = () => { $('wiki-run-time').textContent = `${Math.floor((Date.now() - started) / 1000)}s`; };
    tick(); wiki.timer = setInterval(tick, 1000);
  }
}

function saveHistory() { storage.write('history', wiki.history.slice(-30)); }

function outcome(text, error = false) {
  const element = ctx.node('div', `turn-outcome${error ? ' error' : ''}`, text);
  $('wiki-messages').append(element); scrollChat();
}

async function ask(question) {
  question = question.trim();
  if (!question || wiki.busy) return;
  addMessage('user', question);
  const history = wiki.history.map(({role, content}) => ({role, content}));
  wiki.history.push({role: 'user', content: question}); saveHistory();
  $('wiki-prompt').value = ''; resizePrompt();
  const reply = addMessage('assistant', '');
  reply.article.classList.add('live');
  setBusy(true); $('wiki-run-label').textContent = 'Enviando ao modelo';
  wiki.controller = new AbortController();
  let stats = null, failed = null;
  try {
    const response = await fetch(`${ctx.apiBase}wiki/chat`, {method: 'POST', signal: wiki.controller.signal,
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question, history, article: wiki.pinned, use_wiki: $('wiki-use').checked, dump: $('wiki-chat-dump').value || null})});
    if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.error || `Falha (${response.status}).`); }
    const reader = response.body.getReader(); const decoder = new TextDecoder();
    let buffer = '', frame = null;
    const flush = () => { frame = null; renderMessage(reply); scrollChat(); };
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      const lines = buffer.split('\n'); buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === 'status') $('wiki-run-label').textContent = event.label;
        else if (event.type === 'sources') { reply.sources = event.sources; renderSources(reply); }
        else if (event.type === 'delta') { reply.text += event.text; if (!frame) frame = requestAnimationFrame(flush); $('wiki-run-label').textContent = 'Escrevendo resposta'; }
        else if (event.type === 'done') stats = event.stats;
        else if (event.type === 'error') failed = event.error;
      }
    }
    if (frame) cancelAnimationFrame(frame);
  } catch (error) {
    failed = error.name === 'AbortError' ? null : error.message;
    if (error.name === 'AbortError') outcome('Resposta interrompida.');
  }
  reply.article.classList.remove('live');
  renderMessage(reply);
  const info = stats ? `${stats.model} · ${stats.prompt_tokens ?? '?'} tokens de contexto · ${stats.tokens ?? '?'} gerados · ${stats.tokens_per_second ?? '?'} tok/s · ${stats.seconds}s` : '';
  renderSources(reply, info);
  if (reply.text.trim()) { wiki.history.push({role: 'assistant', content: reply.text, sources: reply.sources}); saveHistory(); }
  else if (!failed) reply.article.remove();
  if (failed) outcome(failed, true);
  setBusy(false); wiki.controller = null;
  $('wiki-prompt').focus();
}

function resizePrompt() {
  const prompt = $('wiki-prompt');
  prompt.style.height = 'auto'; prompt.style.height = `${Math.min(prompt.scrollHeight, 180)}px`;
  $('wiki-send').disabled = wiki.busy || !prompt.value.trim();
}

function restoreHistory() {
  $('wiki-messages').replaceChildren();
  $('wiki-welcome').hidden = !!wiki.history.length;
  for (const item of wiki.history) {
    const message = addMessage(item.role, item.content, item.sources);
    if (item.role === 'assistant') renderSources(message);
  }
}

// ----------------------------------------------------------------- views
export function wikiTitle(view) {
  if (view === 'wiki-chat') return wiki.pinned ? `Sobre ${wiki.pinned}` : 'Pergunte à Wiki';
  return wiki.article?.title || (wiki.lastQuery ? `Busca: ${wiki.lastQuery}` : 'Wikipédia');
}

export async function showWiki(view, hash) {
  try { await loadStatus(); } catch (error) { $('wiki-notice').hidden = false; $('wiki-notice').textContent = error.message; return; }
  if (view === 'wiki-chat') { $('wiki-prompt').focus(); return; }
  let value = '';
  try { value = decodeURIComponent(hash.slice(hash.indexOf('=') + 1)); } catch { /* Invalid bookmark. */ }
  if (hash.startsWith('wiki=') && value) openArticle(value);
  else if (hash.startsWith('wiki-search=')) search(value);
  else { $('wiki-article').hidden = true; wiki.article = null; reading(false); renderResults(wiki.lastQuery); ctx.setTitle(wikiTitle('wiki')); $('wiki-query').focus(); }
}

export function initWiki(helpers) {
  ctx = helpers;
  restoreHistory();
  $('wiki-search-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const query = $('wiki-query').value.trim();
    location.hash = query ? `wiki-search=${encodeURIComponent(query)}` : 'wiki';
  });
  $('wiki-query').addEventListener('input', () => { clearTimeout(wiki.suggestTimer); wiki.suggestTimer = setTimeout(suggest, 180); });
  $('wiki-random').addEventListener('click', async () => {
    try { const data = await ctx.api(withDump('wiki/random')); if (data.title) location.hash = `wiki=${encodeURIComponent(data.title)}`; }
    catch (error) { ctx.toast(error.message); }
  });
  for (const id of ['wiki-dump', 'wiki-chat-dump']) $(id).addEventListener('change', () => {
    storage.write('dump', $(id).value);
    for (const other of ['wiki-dump', 'wiki-chat-dump']) $(other).value = $(id).value;
    renderStatus();
  });
  $('wiki-composer').addEventListener('submit', (event) => { event.preventDefault(); ask($('wiki-prompt').value); });
  $('wiki-prompt').addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('wiki-composer').requestSubmit(); } });
  $('wiki-prompt').addEventListener('input', resizePrompt);
  $('wiki-stop').addEventListener('click', () => wiki.controller?.abort());
  $('wiki-unpin').addEventListener('click', () => { pin(null); ctx.setTitle(wikiTitle('wiki-chat')); });
  $('wiki-clear').addEventListener('click', () => { wiki.history = []; saveHistory(); restoreHistory(); });
  document.querySelectorAll('[data-wiki-prompt]').forEach((button) => button.addEventListener('click', () => ask(button.dataset.wikiPrompt)));
  resizePrompt();
}
