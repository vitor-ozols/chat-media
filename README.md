# Codex + Torrent Client

Projeto simples com duas páginas:

- **Chat** — cliente do Codex com threads persistentes e uma aba própria de histórico;
- **Torrents** — painel para adicionar, pausar, retomar, reiniciar e acompanhar torrents;
- API Flask para cadastrar URLs do YouTube e magnets e consultar o caminho final.

O chat usa o Codex SDK local. As skills instaladas em `~/.codex/skills` e
`~/.agents/skills` ficam disponíveis dentro do contêiner; o Codex pode ativá-las
implicitamente ou por menção explícita, como `$nome-da-skill`.

## API

A API escuta na porta `5000` por padrão e compartilha o mesmo serviço de downloads do Streamlit.

### Cadastrar um download

```bash
curl -X PUT http://localhost:5000/downloads \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "magnet:?xt=urn:btih:...",
    "final_path": "/app/downloads"
  }'
```

YouTube:

```bash
curl -X PUT http://localhost:5000/downloads \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://www.youtube.com/watch?v=...",
    "final_path": "/app/media/music/meu-audio.mp3"
  }'
```

Também é possível enviar `"urls": [...]`. Campos opcionais: `start_paused`, `playlist` e `metadata`.

### Consultar

```bash
curl http://localhost:5000/downloads
curl http://localhost:5000/downloads/ID
curl http://localhost:5000/health
```

Cada item informa `status`, `progress`, `final_path`, erro e timestamps. Quando o download termina, `final_path` passa a ser o caminho efetivo do arquivo (ou a pasta do torrent).

## Execução local

```bash
pip install -r requirements.txt
streamlit run app.py
```

No Docker, Flask e Streamlit iniciam juntos e compartilham o mesmo motor de downloads. Ao executar
`streamlit run app.py` localmente, a API inicia junto com a primeira sessão da interface. Para executar
somente a API:

```bash
python api.py
```

## Docker

```bash
make start
make logs
```

Variáveis principais:

- `BASE_PATH` — base URL do Streamlit, padrão `chat`;
- `API_PORT` — porta Flask, padrão `5000`;
- `DATA_DIR` e `DOWNLOADS_DIR` — persistência e downloads;
- `MUSIC_DIR` e `MOVIES_DIR` — mounts de mídia existentes.
- `CODEX_CONFIG_DIR` — diretório `~/.codex` do usuário no host (padrão desta máquina: `/home/ozols/.codex`);
- `CODEX_AGENTS_DIR` — diretório `~/.agents` do usuário no host (padrão desta máquina: `/home/ozols/.agents`).
- `CODEX_BIN` — executável do Codex CLI usado pelo SDK (padrão desta máquina: `/home/ozols/.local/bin/codex`).

O SQLite em `data/` mantém a fila, o estado dos torrents e o histórico de eventos entre reinícios.
As conversas do chat são as threads persistidas pelo próprio Codex no diretório montado `~/.codex`.
