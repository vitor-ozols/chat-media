# Chat Media

App em Streamlit para gerenciar downloads de midia por conversa.

O projeto combina:

- chat com Gemini
- download de audio do YouTube com `yt-dlp`
- suporte a magnet e arquivos `.torrent`
- classificacao de midia entre `music` e `movie`
- fila de downloads com acompanhamento
- historico persistente

## O que o app faz

- Recebe links do YouTube no chat e coloca o download na fila.
- Baixa musica e organiza em `artista/album/faixa` quando houver metadados suficientes.
- Se faltar `artista` ou `album`, pausa o item e pede essa informacao no chat.
- Recebe magnet links e arquivos `.torrent`.
- Decide entre musica e filme para salvar em `media/music` ou `media/movies`.
- Mostra progresso e historico na interface.
- Permite limpar chat, limpar historico e remover downloads individualmente.

## Estrutura da interface

- `Home`
  Chat principal do agente.
- `Downloads`
  Fila unificada, acoes rapidas de magnet e upload `.torrent`, e detalhes de torrents.
- `Historico`
  Tabela com downloads e historico do chat.

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

- [app.py](/home/ozolsvoz/projects/chat-media/app.py:1)
- [pages/2_Downloads.py](/home/ozolsvoz/projects/chat-media/pages/2_Downloads.py:1)
- [pages/3_Historico.py](/home/ozolsvoz/projects/chat-media/pages/3_Historico.py:1)
- [media_manager/service.py](/home/ozolsvoz/projects/chat-media/media_manager/service.py:1)
- [media_manager/youtube.py](/home/ozolsvoz/projects/chat-media/media_manager/youtube.py:1)
- [torrent_manager/service.py](/home/ozolsvoz/projects/chat-media/torrent_manager/service.py:1)

## Requisitos

- Python 3.11
- `ffmpeg`
- `libtorrent` para torrents
- `GEMINI_API_KEY` para respostas com Gemini

Dependencias Python:

```text
streamlit
google-genai
yt-dlp
libtorrent
```

## Executando localmente

Instale dependencias:

```bash
pip install -r requirements.txt
```

Exporte a chave da Gemini:

```bash
export GEMINI_API_KEY=...
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

Se existir um `.env`, o `Makefile` usa `--env-file`. Se nao existir, repassa `GEMINI_API_KEY` do ambiente para o container sem imprimir o valor.

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

Se faltarem dados, o agente pede algo assim:

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

Na aba `Downloads`, voce pode:

- colar magnet links
- anexar arquivos `.torrent`

Torrents de musica vao para `media/music`.
Torrents de video/filme vao para `media/movies`.

## Persistencia

O app usa SQLite em `data/`:

- `data/app.db`
  Estado e historico de torrents.
- `data/media.db`
  Chat, downloads unificados e historico de midia.

## Observacoes importantes

- O agente responde melhor sobre status quando voce pergunta algo como `terminou?`, `como esta o download?` ou `qual o status?`, porque ele consulta a fila real.
- Torrents removidos individualmente pela fila unificada sao removidos do cliente para parar seed, mas nao apagam os arquivos baixados.
- Playlists do YouTube dependem de o `yt-dlp` conseguir expandir os itens publicos da playlist.

## Desenvolvimento

Arquitetura resumida:

- `media_manager/`
  Regras de chat, YouTube, historico, classificacao e sincronizacao.
- `torrent_manager/`
  Gerenciador de torrent reaproveitado e adaptado do projeto `../streamlito`.
- `ui_shell.py`
  Shell visual e configuracao compartilhada do Streamlit.

## Proximos passos naturais

- associar artista/album por playlist com menos perguntas
- adicionar delecao fisica opcional de arquivos
- melhorar o agrupamento visual de playlists na aba `Downloads`
