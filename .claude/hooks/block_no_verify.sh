#!/usr/bin/env bash
# Bloque `git commit/push --no-verify` (et l'alias court -n de `git commit`).
# Règle CLAUDE.md : jamais --no-verify. PreToolUse Bash, exit 2 = bloquant.
#
# Parse argv via shlex (PAS de regex sur la string brute) → zéro faux positif :
# un message de commit ou un `echo` contenant "--no-verify" ne déclenche rien.
input=$(cat)
# Le JSON passe par variable d'env (PAS stdin) : avec un heredoc, python3 lirait
# le script depuis stdin et json.load(sys.stdin) tomberait sur du vide.
verdict=$(HOOK_JSON="$input" python3 <<'PY'
import os, json, shlex, re

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
segments, cur = [], []
for t in toks:
    if t in SEP:
        if cur:
            segments.append(cur); cur = []
    else:
        cur.append(t)
if cur:
    segments.append(cur)

def offends(seg):
    if "git" not in seg:
        return False
    rest = seg[seg.index("git") + 1:]
    # sauter les options globales de git (-C <path>, -c <kv>) avant la sous-commande
    sub, i = None, 0
    while i < len(rest):
        a = rest[i]
        if a in ("-C", "-c"):
            i += 2; continue
        if a.startswith("-"):
            i += 1; continue
        sub = a; rest = rest[i + 1:]; break
    if sub not in ("commit", "push"):
        return False
    if "--no-verify" in rest:
        return True
    # -n (et clusters courts type -nm) = no-verify pour commit uniquement
    # (pour push, -n = --dry-run, inoffensif → on ne bloque pas)
    if sub == "commit" and any(re.fullmatch(r"-[a-zA-Z]*n[a-zA-Z]*", t) for t in rest):
        return True
    return False

print("block" if any(offends(s) for s in segments) else "ok")
PY
)
if [ "$verdict" = "block" ]; then
  echo "⛔ --no-verify / 'git commit -n' interdit (CLAUDE.md). Corrige ce que le hook bloque, ne le contourne pas." >&2
  exit 2
fi
exit 0
