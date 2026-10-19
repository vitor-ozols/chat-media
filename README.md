# Chat Media

Interface leve em **HTML, CSS e JavaScript nativo**, servida pelo **Flask + Waitress**.
Sem Streamlit, Node, bundler, fontes externas ou dependências de frontend.

- **Chat** — texto em streaming, comentários públicos do agente, comandos, buscas,
  alterações de arquivos e plano de execução; painel de atividades expansível,
  botão para interromper o turno, histórico pesquisável na lateral, skills,
  preferências e rascunho locais;
- **Torrents** — painel para adicionar, pausar, retomar, reiniciar e acompanhar torrents;
- API compatível para cadastrar URLs do YouTube e magnets e consultar o caminho final.

Layout adaptado para desktop e celular, navegação por teclado, respostas com Markdown
sem executar HTML, cópia de respostas e rolagem que respeita a leitura do usuário.
`Enter` envia, `Shift Enter` quebra linha e `Alt N` abre uma conversa nova.

Os eventos chegam por **Server-Sent Events (SSE)**. A execução continua no servidor
quando a página desconecta; o navegador reconecta e recupera o turno ao recarregar.
Até dois turnos podem executar simultaneamente, sem dois escritores na mesma conversa.
Eventos ficam em memória por uma hora após o término (até 21 turnos concluídos);
as conversas continuam persistidas no estado do Codex. Reiniciar o servidor interrompe
turnos ativos e remove o buffer temporário; reabra a conversa pelo histórico.
O painel mostra atividades e comentários públicos, sem expor raciocínio interno.

O chat usa o Codex SDK local. As skills instaladas em `~/.codex/skills` e
`~/.agents/skills` ficam disponíveis dentro do contêiner; o Codex pode ativá-las
implicitamente ou por menção explícita, como `$nome-da-skill`.

## API

A API escuta na porta `5000` por padrão e compartilha o mesmo serviço de downloads da interface.
Também está disponível na porta `8501`. O chat usa `/chat/api/` por padrão.

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
python app.py
```

Acesse `http://localhost:8501/chat/`. A interface e a API iniciam juntas,
compartilhando o mesmo motor de downloads e o mesmo gerenciador de turnos.
Para executar apenas o servidor da porta da API (que também serve a interface):

```bash
python api.py
```

## Docker

```bash
make start
make logs
```

Variáveis principais:

- `BASE_PATH` — prefixo da interface e da API do chat, padrão `chat`; vazio para `/`;
- `PORT` — porta da interface, padrão `8501`;
- `HOST` — endereço da interface, padrão `0.0.0.0`;
- `API_PORT` — porta Flask, padrão `5000`;
- `DATA_DIR` e `DOWNLOADS_DIR` — mounts Docker de persistência e downloads;
- `MUSIC_DIR` e `MOVIES_DIR` — mounts de mídia existentes.
- `CODEX_CONFIG_DIR` — estado exclusivo do chat-media (padrão: `./data/codex`); evite compartilhar bancos SQLite com o Codex do host;
- `CODEX_AGENTS_DIR` — diretório `~/.agents` do usuário no host (padrão desta máquina: `/home/ozols/.agents`).
- `CODEX_BIN` — executável do Codex CLI usado pelo SDK (padrão desta máquina: `/home/ozols/.local/bin/codex`).

O SQLite em `data/` mantém a fila, o estado dos torrents e o histórico de eventos entre reinícios.
As conversas do chat são as threads persistidas pelo próprio Codex no diretório montado `~/.codex`.

### Importar conversas / recuperar histórico corrompido

Antes de iniciar o serviço, importe o estado antigo para um diretório **vazio**:

```bash
python -m media_manager.codex_home /caminho/do/codex-antigo ./data/codex --runtime-home /home/appuser/.codex
```

Execute como o usuário do serviço, com acesso ao diretório de origem. O comando
preserva a origem, copia login/configuração/sessões e usa o backup SQLite para o
índice de threads. Não copia o banco `thread_history_*.sqlite`: o Codex cria
um banco novo, preservando os registros das sessões. Históricos paginados que a API
retorna sem turnos são exibidos pela leitura local dos registros de sessão,
restrita ao diretório do app. Uma importação incompleta
permanece no destino para inspeção; use outro diretório vazio para tentar novamente.
Após importar, `make start` aplica o mount separado. Novas conversas do host não
são sincronizadas automaticamente. Se o login expirar, renove-o no estado do app.

## Testes

```bash
python -m unittest discover -s tests -v
```

Os testes usam serviços simulados e não fazem chamadas ao modelo nem downloads.
Para validar a interface em Chromium, desktop e celular:

```bash
pip install playwright
python -m playwright install chromium
python tests/browser_smoke.py
```

Os screenshots ficam em `/tmp/chat-media-previews`. Um proxy reverso deve preservar
`/chat/`, desativar buffering de SSE e permitir conexões longas. O Nginx existente
com `proxy_buffering off` continua compatível.
