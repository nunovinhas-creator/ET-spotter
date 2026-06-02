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
