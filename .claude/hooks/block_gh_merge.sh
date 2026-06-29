#!/usr/bin/env bash
# Bloque `gh pr merge` — le merge est réservé à Emmanuel (incidents #169/#170/#171/#121).
# Règle CLAUDE.md : « Claude ne merge JAMAIS ». PreToolUse Bash, exit 2 = bloquant.
#
# Parse argv via shlex (PAS de regex sur la string brute) → zéro faux positif :
# `gh pr create --body "merge"` ou un `echo "gh pr merge"` ne déclenchent rien.
input=$(cat)
# Court-circuit : aucune mention de gh → rien à vérifier (évite de lancer python).
case "$input" in
  *gh*) ;;
  *) exit 0 ;;
esac
# Le JSON passe par variable d'env (PAS stdin) : le heredoc occupe déjà stdin.
verdict=$(HOOK_JSON="$input" python3 <<'PY'
import os, json, shlex

try:
    data = json.loads(os.environ.get("HOOK_JSON", "") or "{}")
except json.JSONDecodeError:
    print("ok"); raise SystemExit(0)
cmd = (data.get("tool_input", {}) or {}).get("command", "") or ""
try:
    toks = shlex.split(cmd, comments=False, posix=True)
except ValueError:
    print("ok"); raise SystemExit(0)  # non parsable → on ne bloque pas

SEP = {"&&", "||", "|", ";", "&", "(", ")", "{", "}"}
segments, seg = [], []
for t in toks:
    if t in SEP:
        if seg:
            segments.append(seg); seg = []
    else:
        seg.append(t)
if seg:
    segments.append(seg)

def offends(s):
    if "gh" not in s:
        return False
    # 'pr' immédiatement suivi de 'merge' (adjacence) → pas de faux positif sur un
    # argument 'merge' d'une autre sous-commande ni sur une string quotée.
    for i, t in enumerate(s):
        if t == "pr" and i + 1 < len(s) and s[i + 1] == "merge":
            return True
    return False

print("block" if any(offends(s) for s in segments) else "ok")
PY
)
if [ "$verdict" = "block" ]; then
  echo "⛔ 'gh pr merge' interdit : le merge est réservé à Emmanuel (CLAUDE.md). Crée/màj la PR et laisse Emmanuel merger." >&2
  exit 2
fi
exit 0
