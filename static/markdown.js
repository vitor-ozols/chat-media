// Small, dependency-free renderer. All input is escaped; raw HTML is never used.
const escape = (text) => String(text).replace(/[&<>"']/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));

function safeHref(value) {
  try {
    const url = new URL(value, location.href);
    return ['http:', 'https:'].includes(url.protocol) ? escape(url.href) : '#';
  } catch { return '#'; }
}

function inline(text) {
  const tokens = [];
  const token = (html) => { tokens.push(html); return `\u0000${tokens.length - 1}\u0000`; };
  let html = escape(text.replace(/\u0000/g, ''));
  html = html.replace(/`([^`\n]+)`/g, (_, code) => token(`<code>${code}</code>`));
  html = html.replace(/\[([^\]\n]+)\]\(([^\s)]+)\)/g, (_, label, href) => {
    // Decode escaped URL entities through a detached textarea, then validate the protocol.
    const decoder = document.createElement('textarea');
    decoder.innerHTML = href;
    return token(`<a href="${safeHref(decoder.value)}" target="_blank" rel="noopener noreferrer">${label}</a>`);
  });
  html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*\n]+)\*/g, '<em>$1</em>')
    .replace(/~~([^~\n]+)~~/g, '<del>$1</del>');
  return html.replace(/\u0000(\d+)\u0000/g, (_, index) => tokens[Number(index)]);
}

export function markdown(text) {
  const lines = String(text).split('<!-- chat-media-artifact', 1)[0].replace(/\r\n/g, '\n').split('\n');
  const result = [];
  let paragraph = [], list = [], listType = '', code = null, language = '';
  const flushParagraph = () => { if (paragraph.length) result.push(`<p>${paragraph.map(inline).join('<br>')}</p>`); paragraph = []; };
  const flushList = () => { if (list.length) result.push(`<${listType}>${list.map((line) => `<li>${inline(line)}</li>`).join('')}</${listType}>`); list = []; listType = ''; };
  const flush = () => { flushParagraph(); flushList(); };
  const renderCode = () => `<pre>${language ? `<span class="code-label">${escape(language)}</span>` : ''}<code>${escape(code.join('\n'))}</code></pre>`;
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index];
    if (/^\s*```/.test(line)) {
      if (code !== null) { result.push(renderCode()); code = null; }
      else { flush(); code = []; language = line.trim().slice(3).trim(); }
      continue;
    }
    if (code !== null) { code.push(line); continue; }
    if (!line.trim()) { flush(); continue; }
    if (line.includes('|') && /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[index + 1] || '')) {
      flush();
      const cells = (row) => row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim());
      const headers = cells(line);
      let table = `<div class="markdown-table"><table><thead><tr>${headers.map((cell) => `<th>${inline(cell)}</th>`).join('')}</tr></thead><tbody>`;
      index += 2;
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) {
        const row = cells(lines[index]);
        table += `<tr>${headers.map((_, column) => `<td>${inline(row[column] || '')}</td>`).join('')}</tr>`;
        index++;
      }
      index--;
      result.push(`${table}</tbody></table></div>`);
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) { flush(); result.push(`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`); continue; }
    const item = line.match(/^\s*(?:([-*+])|\d+\.)\s+(.+)$/);
    if (item) {
      flushParagraph();
      const type = item[1] ? 'ul' : 'ol';
      if (listType && type !== listType) flushList();
      listType = type; list.push(item[2]); continue;
    }
    if (/^>\s?/.test(line)) { flush(); result.push(`<blockquote>${inline(line.replace(/^>\s?/, ''))}</blockquote>`); continue; }
    if (/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(line)) { flush(); result.push('<hr>'); continue; }
    flushList(); paragraph.push(line);
  }
  if (code !== null) result.push(renderCode());
  flush();
  return result.join('');
}
