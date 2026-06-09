# ET-Spotter — Regras para Claude Code

## Regeneração automática do HTML

Sempre que modificares qualquer ficheiro em `scripts/` que afete o output visual
(especialmente `generate_dashboard.py`, mas também qualquer script cujo resultado
apareça no dashboard), deves **imediatamente a seguir**:

1. Correr `python scripts/generate_dashboard.py` para regenerar o HTML
2. Verificar que o ficheiro foi atualizado (`docs/index.html` e `data/reports/dashboard.html`)
3. Incluir os ficheiros HTML no mesmo commit que as alterações aos scripts

**Nunca** termines uma implementação visual sem regenerar e commitar o HTML.
Esta regra aplica-se mesmo que a tarefa principal seja outra — se tocaste num
script que afeta o dashboard, o HTML tem de acompanhar.

## Deploy automático para GitHub Pages

Após qualquer commit que altere `docs/index.html`, `docs/sw.js` ou `docs/manifest.json`,
faz **sempre** o deploy directo para o branch `gh-pages` sem precisar de ser pedido.

**IMPORTANTE**: O deploy deve incluir TODOS os ficheiros de `docs/` — não só os 4 core.
Nunca omitir as páginas de artigos (`analise-diaria.html`, etc.) nem o `i18n/`.

Procedimento (git plumbing — usar ficheiros temporários para os `printf`, NÃO pipeline directo):

```bash
git fetch origin gh-pages

# Hash todos os ficheiros
NOJEKYLL="e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"  # ficheiro vazio, invariante
BLOB_INDEX=$(git hash-object -w docs/index.html)
BLOB_SW=$(git hash-object -w docs/sw.js)
BLOB_MANI=$(git hash-object -w docs/manifest.json)
BLOB_ROBOTS=$(git hash-object -w docs/robots.txt)
BLOB_SITEMAP=$(git hash-object -w docs/sitemap.xml)
BLOB_I18NJS=$(git hash-object -w docs/i18n.js)
BLOB_ANALISE=$(git hash-object -w docs/analise-diaria.html)
BLOB_VWCE=$(git hash-object -w docs/vwce-vs-iwda.html)
BLOB_MELHOR=$(git hash-object -w docs/melhor-etf-europa.html)
BLOB_ESG=$(git hash-object -w docs/etf-esg-europa.html)
BLOB_ESTRA=$(git hash-object -w docs/estrategia-momentum.html)
BLOB_GUIA=$(git hash-object -w docs/guia-etf-ucits.html)
BLOB_PT=$(git hash-object -w docs/i18n/pt.json)
BLOB_EN=$(git hash-object -w docs/i18n/en.json)

# Subtree i18n (usar ficheiro temporário — nunca pipe directo)
TMPF=$(mktemp)
printf "100644 blob %s\ten.json\n" "$BLOB_EN" >> "$TMPF"
printf "100644 blob %s\tpt.json\n" "$BLOB_PT" >> "$TMPF"
I18N_TREE=$(git mktree < "$TMPF"); rm "$TMPF"

# Árvore raiz completa
TMPF2=$(mktemp)
printf "100644 blob %s\t.nojekyll\n"               "$NOJEKYLL"    >> "$TMPF2"
printf "100644 blob %s\tanalise-diaria.html\n"     "$BLOB_ANALISE" >> "$TMPF2"
printf "100644 blob %s\testrategia-momentum.html\n" "$BLOB_ESTRA"  >> "$TMPF2"
printf "100644 blob %s\tetf-esg-europa.html\n"     "$BLOB_ESG"    >> "$TMPF2"
printf "100644 blob %s\tguia-etf-ucits.html\n"     "$BLOB_GUIA"   >> "$TMPF2"
printf "040000 tree %s\ti18n\n"                    "$I18N_TREE"   >> "$TMPF2"
printf "100644 blob %s\ti18n.js\n"                 "$BLOB_I18NJS" >> "$TMPF2"
printf "100644 blob %s\tindex.html\n"              "$BLOB_INDEX"  >> "$TMPF2"
printf "100644 blob %s\tmanifest.json\n"           "$BLOB_MANI"   >> "$TMPF2"
printf "100644 blob %s\tmelhor-etf-europa.html\n"  "$BLOB_MELHOR" >> "$TMPF2"
printf "100644 blob %s\trobots.txt\n"              "$BLOB_ROBOTS" >> "$TMPF2"
printf "100644 blob %s\tsitemap.xml\n"             "$BLOB_SITEMAP" >> "$TMPF2"
printf "100644 blob %s\tsw.js\n"                   "$BLOB_SW"     >> "$TMPF2"
printf "100644 blob %s\tvwce-vs-iwda.html\n"       "$BLOB_VWCE"   >> "$TMPF2"
NEW_TREE=$(git mktree < "$TMPF2"); rm "$TMPF2"

PARENT=$(git rev-parse origin/gh-pages)
NEW_COMMIT=$(git commit-tree "$NEW_TREE" -p "$PARENT" -m "chore: deploy dashboard")
git push origin "${NEW_COMMIT}:refs/heads/gh-pages"
```
