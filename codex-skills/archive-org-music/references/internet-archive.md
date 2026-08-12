# Internet Archive

- Obter metadados em `https://archive.org/metadata/IDENTIFIER`.
- Baixar arquivos em `https://archive.org/download/IDENTIFIER/NOME` com os segmentos escapados.
- Aceitar somente itens sem erro e arquivos sem `private: true`.
- Para áudio, preferir MP3 com `source: original`; usar derivados apenas quando não houver MP3 original.
- Obter ordem de `track`; usar o prefixo numérico do nome apenas como fallback.
- Obter título do campo `title`; usar o nome do arquivo sem prefixo numérico como fallback.
- Obter artista de `creator`, álbum de `album` ou do título do item e ano de `year` ou `date`. Exigir override quando esses dados não forem confiáveis.
- Preferir JPEG original chamado `cover`, `front` ou `folder`, sem diferenciar maiúsculas/minúsculas. Não usar spectrogramas nem tiles como capa.
- Preservar os bytes do MP3; alterar somente as tags ID3.
- Gravar `TITLE`, `ARTIST`, `ALBUMARTIST`, `ALBUM`, `TRACKNUMBER`, `DISCNUMBER=1` e `DATE` quando conhecida.
