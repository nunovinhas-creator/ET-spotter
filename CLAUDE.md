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

Procedimento (git plumbing a partir do repo principal para preservar o signing):

```bash
git fetch origin gh-pages
HTML_BLOB=$(git hash-object -w docs/index.html)
SW_BLOB=$(git hash-object -w docs/sw.js)
MANI_BLOB=$(git hash-object -w docs/manifest.json)
NOJEKYLL=$(git rev-parse origin/gh-pages:.nojekyll)
NEW_TREE=$(printf "100644 blob %s\t.nojekyll\n100644 blob %s\tindex.html\n100644 blob %s\tmanifest.json\n100644 blob %s\tsw.js\n" \
  "$NOJEKYLL" "$HTML_BLOB" "$MANI_BLOB" "$SW_BLOB" | git mktree)
PARENT=$(git rev-parse origin/gh-pages)
NEW_COMMIT=$(git commit-tree "$NEW_TREE" -p "$PARENT" -m "chore: deploy dashboard")
git push origin "${NEW_COMMIT}:refs/heads/gh-pages"
```
