# API do chat-media

## Rotas

- `GET /health`: retorna `status` e disponibilidade de `torrent_engine`.
- `GET /downloads`: retorna `{ "downloads": [...] }`.
- `GET /downloads/<id>`: aceita o ID do download ou o ID externo do torrent.
- `PUT /downloads`: cadastra magnets e URLs do YouTube e retorna HTTP 201.

A URL base padrão é `http://localhost:5000`. `/chat` pertence à interface Streamlit e não recebe esses payloads.

## Cadastro

Enviar JSON com:

- `url` ou `urls`: magnet(s) começando com `magnet:?` ou URL(s) cujo host seja YouTube.
- `final_path`: obrigatório. Caminhos relativos são resolvidos a partir da raiz do serviço; preferir caminho absoluto visível pelo processo ou container.
- `start_paused`: opcional; afeta torrents.
- `playlist`: opcional; tratar a URL do YouTube como playlist.
- `metadata`: opcional; objeto como `artist`, `album` e `title`.

Exemplo:

```json
{
  "urls": ["https://www.youtube.com/watch?v=..."],
  "final_path": "/app/media/music/faixa.mp3",
  "playlist": false,
  "metadata": {
    "artist": "Artista",
    "album": "Álbum",
    "title": "Faixa"
  }
}
```

O YouTube é baixado como melhor áudio e convertido para MP3 quando `ffmpeg` está disponível. Um `final_path` com extensão representa o arquivo desejado; sem extensão representa um diretório. Para magnets, o caminho é o diretório de download.

Cada item pode conter `id`, `source_type`, `url`, `name`, `status`, `progress` entre 0 e 1, `final_path`, `torrent_id`, `error` e timestamps. Ao concluir, `final_path` passa a indicar o arquivo efetivo ou a pasta do torrent.

## Inicialização

Na raiz do projeto:

```bash
python api.py
```

Também é possível iniciar Streamlit com `streamlit run app.py`, ou usar `make start` no Docker. A porta pode ser alterada com `API_PORT`; nesse caso ajustar `--base-url` ou `CHAT_MEDIA_API_URL`.
