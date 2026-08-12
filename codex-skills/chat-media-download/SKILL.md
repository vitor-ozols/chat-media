---
name: chat-media-download
description: Enfileirar e acompanhar downloads de magnets BitTorrent, vídeos, playlists e músicas do YouTube pela API HTTP local do projeto chat-media. Usar quando o usuário pedir para baixar mídia via localhost, cadastrar uma ou várias URLs, escolher o caminho final, consultar saúde/fila/progresso/erro ou localizar o arquivo concluído.
---

# Chat Media Download

Usar `scripts/chat_media.py` para acessar a API. Não enviar requisições para a rota Streamlit `/chat`; a API documentada usa `http://localhost:5000` por padrão.

## Fluxo

1. Obter do pedido uma URL magnet ou do YouTube e o caminho de destino. Se qualquer um estiver ausente, perguntar ao usuário.
2. Usar apenas conteúdo que o usuário esteja autorizado a baixar. Recusar ajuda para adquirir cópias não autorizadas de obras protegidas; ainda permitir conteúdo próprio, licenciado, livre ou em domínio público.
3. Verificar a API com `python3 scripts/chat_media.py health`. Se falhar, explicar como iniciar a API conforme `references/api.md`.
4. Antes de cadastrar, executar `add` com `--dry-run` quando o pedido ou o caminho for ambíguo. Não inventar magnets, URLs, metadados nem destinos.
5. Cadastrar o download. Informar o `id`, o estado inicial e o caminho retornado.
6. Se o usuário pedir acompanhamento, consultar `get ID` em intervalos razoáveis até `completed` ou `error`. O `final_path` retornado ao concluir é o caminho efetivo.

## Comandos

Executar a partir da pasta desta skill:

```bash
python3 scripts/chat_media.py health
python3 scripts/chat_media.py list
python3 scripts/chat_media.py get ID
python3 scripts/chat_media.py add --url 'magnet:?xt=urn:btih:...' --final-path /app/downloads
python3 scripts/chat_media.py add --url 'https://www.youtube.com/watch?v=...' --final-path /app/media/music/faixa.mp3
```

Repetir `--url` para cadastrar várias fontes. Usar `--playlist` para playlist do YouTube, `--start-paused` para torrent pausado e `--artist`, `--album`, `--title` ou `--metadata-json` para metadados.

Definir outra origem com `--base-url URL` ou `CHAT_MEDIA_API_URL`. Ler `references/api.md` para payloads, respostas, caminhos e inicialização do serviço.
