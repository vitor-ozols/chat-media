# Chat Media

App em Streamlit para gerenciar downloads de midia por conversa, usando skills locais e integracao opcional com o Codex CLI/SDK.

O projeto combina:

- skills locais para YouTube, torrents, status e comandos Codex
- download de audio do YouTube com `yt-dlp`
- suporte a magnet e arquivos `.torrent`
- classificacao local de midia entre `music` e `movie`
- fila de downloads com acompanhamento
- historico persistente de sessoes no sidebar

## O que o app faz

- Recebe links do YouTube no chat e coloca o download na fila.
- Baixa musica e organiza em `artista/album/faixa` quando houver metadados suficientes.
- Se faltar `artista` ou `album`, pausa o item e pede essa informacao no chat.
- Recebe magnet links e arquivos `.torrent`.
- Decide entre musica e filme para salvar em `media/music` ou `media/movies`.
- Mostra progresso e historico na interface.
- Permite iniciar um chat novo, alternar sessoes e limpar o chat atual.
- Exibe comandos slash principais, incluindo `/status`.

## Skills locais

- `youtube_music`: baixa video ou playlist do YouTube como audio e organiza em `media/music`.
- `torrent_download`: baixa magnet ou `.torrent` com acompanhamento por progresso, peers, seeds, ETA e eventos.
- `download_status`: responde status real da fila local.
- `codex_cli`: mostra comandos slash e disponibilidade do Codex CLI/SDK no ambiente.

## Skills globais do Codex

- `gws-cli`: Google Workspace via CLI (`gws`) para Gmail, Drive, Calendar, Sheets e Docs.
- `pointbot-orcamentos`: cotacoes da Point Viagens usando o projeto `/mnt/sata/pointbot`, com HTML/PDF, carrinho/checkout e envio por email apos confirmacao.

## Comandos do chat

```text
/help       lista comandos disponiveis
/status     mostra status do Codex CLI/SDK e resumo de downloads
/skills     lista skills locais
/pointbot   mostra como iniciar a skill pointbot-orcamentos
/pointbot pdf disponibiliza no chat o PDF mais recente de /mnt/sata/pointbot/out
/downloads  resume a fila
/new        orienta usar o botao Novo chat no sidebar
```

## Estrutura da interface

- `Home`
  Chat principal por skills, com historico de sessoes no sidebar.
- `Downloads`
  Fila unificada, acoes rapidas de magnet e upload `.torrent`, e detalhes de torrents.
- `Historico`
  Tabela com downloads, sessoes e historico do chat.

## Estrutura de pastas

```text
data/
media/
  music/
  movies/
downloads/
prompts/
```

Arquivos relevantes:

- `app.py`
- `ui_shell.py`
- `media_manager/service.py`
- `media_manager/skills.py`
- `media_manager/codex_runtime.py`
- `media_manager/youtube.py`
- `torrent_manager/service.py`
- `pages/2_Downloads.py`
- `pages/3_Historico.py`
- `codex-skills/youtube-music/SKILL.md`
- `codex-skills/torrent-download/SKILL.md`

## Requisitos

- Python 3.11
- `ffmpeg`
- `libtorrent` para torrents
- `codex` CLI instalado no ambiente se voce quiser status/integracao Codex real

Dependencias Python:

```text
streamlit
yt-dlp
libtorrent
```

## Executando localmente

Instale dependencias:

```bash
pip install -r requirements.txt
```

Opcionalmente exporte uma chave OpenAI para o Codex:

```bash
export OPENAI_API_KEY=...
```

Suba o app:

```bash
streamlit run app.py
```

## Executando com Docker

Build e start:

```bash
make start
```

Parar:

```bash
make stop
```

Logs:

```bash
make logs
```

O container monta os caminhos:

- `/app/data`
- `/app/media/music`
- `/app/media/movies`
- `/app/downloads`

Voce pode apontar para diretorios reais da maquina:

```bash
export MUSIC_DIR=/mnt/sata/musics
export MOVIES_DIR=/mnt/sata/streamlito/downloads
make start
```

## Como usar

### Baixar uma musica do YouTube

No chat:

```text
baixa esse link https://www.youtube.com/watch?v=...
```

Se o video tiver metadados completos, o arquivo vai para:

```text
media/music/Nome Artista/Nome Album/Nome Musica.mp3
```

Se faltarem dados, a skill pede algo assim:

```text
artista: Nome do artista, album: Nome do album, musica: Nome da faixa
```

### Baixar uma playlist inteira

O app aceita:

```text
https://www.youtube.com/playlist?list=...
```

e tambem links no formato:

```text
https://www.youtube.com/watch?v=...&list=...
```

As faixas sao expandidas e entram na fila individualmente.

### Adicionar torrent

Na aba `Downloads` ou no chat, voce pode:

- colar magnet links
- anexar arquivos `.torrent`

Torrents de musica vao para `media/music`.
Torrents de video/filme vao para `media/movies`.

## Persistencia

O app usa SQLite em `data/`:

- `data/app.db`
  Estado e historico de torrents.
- `data/media.db`
  Sessoes, mensagens, downloads unificados e historico de midia.

## Observacoes importantes

- O app responde melhor sobre status quando voce pergunta `terminou?`, `como esta o download?`, `qual o status?` ou usa `/status`.
- Torrents removidos individualmente pela fila unificada sao removidos do cliente para parar seed, mas nao apagam os arquivos baixados.
- Playlists do YouTube dependem de o `yt-dlp` conseguir expandir os itens publicos da playlist.
- O Codex CLI nao e empacotado no Dockerfile; o app apenas detecta se `codex` esta disponivel no ambiente de execucao.
- Os manifests de skills do Codex ficam em `codex-skills/` porque `.codex/` pode estar montado como leitura em alguns ambientes.
