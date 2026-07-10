---
name: torrent-download
description: Baixar magnet links ou arquivos .torrent com acompanhamento de progresso, peers, seeds, ETA e eventos.
---

# Torrent Download Skill

Use esta skill quando o usuario colar um magnet link, anexar um `.torrent`, ou pedir acompanhamento de torrent.

## Workflow

1. Receba um ou mais links `magnet:?xt=urn:btih:...` ou arquivos `.torrent`.
2. Classifique o destino por heuristica local:
   musicas em `media/music`, filmes/videos em `media/movies`.
3. Adicione ao `TorrentService`.
4. Sincronize o torrent para a fila unificada de downloads.
5. Mostre progresso real, taxa, peers, seeds, ETA e eventos pela pagina `Downloads`.
6. Para status por chat, responda usando `/status` ou `/downloads`, sempre consultando o estado local.

## Backend

- Servico principal: `torrent_manager.service.TorrentService`.
- UI detalhada: `torrent_manager.ui.render_dashboard`.
- Persistencia de torrents: `data/app.db`.
- Persistencia unificada: `data/media.db`, tabela `downloads`.
- Motor externo: `libtorrent`.
