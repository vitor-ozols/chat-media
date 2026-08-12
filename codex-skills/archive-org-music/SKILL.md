---
name: archive-org-music
description: Baixar álbuns e coleções musicais públicas do Internet Archive via HTTP e organizá-los para Navidrome como Artist/Album (year)/01 - Title, com manifesto, tags embutidas, capa e validação de colisões. Usar quando o usuário fornecer uma URL archive.org/details/IDENTIFIER ou archive.org/download/IDENTIFIER e pedir download, importação ou organização na biblioteca de músicas.
---

# Archive.org Music

Usar `scripts/archive_org_music.py`. O comando é somente leitura por padrão; exigir `--apply` para baixar e gravar na biblioteca.

## Fluxo

1. Confirmar que o item é público e que o usuário está autorizado a baixá-lo. Não usar a skill para contornar restrições nem adquirir cópias não autorizadas.
2. Resolver a raiz real da biblioteca; não presumir `/music`.
3. Executar uma auditoria da biblioteca antes da importação quando a skill `navidrome-organize-library` estiver disponível.
4. Executar o script sem `--apply`, salvar o manifesto e conferir artista, álbum, ano, ordem, títulos, capa e colisões.
5. Corrigir metadados incertos com `--artist`, `--album` ou `--year`; não inventar dados.
6. Após autorização explícita do usuário, repetir com `--apply`. Disponibilizar `mutagen` no Python antes de aplicar; o script informa como resolver quando estiver ausente.
7. Auditar novamente a biblioteca e informar faixas, destino, tags, capa, colisões e necessidade de rescan do Navidrome.

## Comandos

```bash
python3 scripts/archive_org_music.py URL --library /caminho/musicas --manifest /tmp/archive-manifest.json
python3 scripts/archive_org_music.py URL --library /caminho/musicas --manifest /tmp/archive-manifest.json --apply
```

O script aceita URLs `/details/IDENTIFIER` e `/download/IDENTIFIER`, baixa somente MP3 públicos, prefere arquivos marcados como originais, usa a capa JPEG original e nunca sobrescreve destinos existentes.

Ler `references/internet-archive.md` para as regras de seleção de arquivos e metadados.
