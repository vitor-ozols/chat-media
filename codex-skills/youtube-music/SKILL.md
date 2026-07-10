---
name: youtube-music
description: Baixar audio do YouTube ou playlists e organizar musicas em artista/album/faixa usando o app Chat Media.
---

# YouTube Music Skill

Use esta skill quando o usuario pedir para baixar uma musica, album ou playlist do YouTube.

## Workflow

1. Receba um link `youtube.com/watch`, `youtu.be` ou `youtube.com/playlist`.
2. Use a skill local `youtube_music` do app para enfileirar o download.
3. Para playlists, trate o link como playlist quando a URL tiver `/playlist` ou quando o usuario disser `playlist inteira`, `album inteiro` ou equivalente.
4. Se faltar `artist` ou `album`, pause o item e peça:
   `artista: Nome, album: Nome, musica: Nome`.
5. Organize o arquivo final em:
   `media/music/Nome Artista/Nome Album/Nome Musica.mp3`.
6. Oriente o usuario a acompanhar progresso em `Downloads` ou com `/status`.

## Backend

- Servico principal: `media_manager.youtube.YouTubeService`.
- Persistencia: `data/media.db`, tabela `downloads`.
- Ferramenta externa: `yt-dlp`.
- Conversao de audio: `ffmpeg`, quando disponivel.
