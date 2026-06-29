#!/usr/bin/env bash
# Bloque `git commit`/`git push` sur OU vers une branche protégée (main|development).
# Règle CLAUDE.md : 1 issue = 1 branche feature ; jamais de commit/push direct sur
# main/development (incidents #121 / #169-171). PreToolUse Bash, exit 2 = bloquant.
#
# Parse argv via shlex (PAS de regex) → zéro faux positif (echo, message de commit).
input=$(cat)
# Court-circuit : aucune mention de git → rien à vérifier.
case "$input" in
  *git*) ;;
  *) exit 0 ;;
esac
# Branche courante, lue une fois (vide hors repo → aucune correspondance).
cur_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
verdict=$(HOOK_JSON="$input" CUR_BRANCH="$cur_branch" python3 <<'PY'
import os, json, shlex

PROTECTED = {"main", "development"}

try:
    data = json.loads(os.environ.get("HOOK_JSON", "") or "{}")
except json.JSONDecodeError:
    print("ok"); raise SystemExit(0)
cmd = (data.get("tool_input", {}) or {}).get("command", "") or ""
cur = (os.environ.get("CUR_BRANCH", "") or "").strip()
try:
    toks = shlex.split(cmd, comments=False, posix=True)
except ValueError:
    print("ok"); raise SystemExit(0)

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

def sub_and_rest(s):
    # (sous-commande git, tokens suivants) en sautant les options globales de git
    # (-C <path>, -c <kv>) avant la sous-commande.
    if "git" not in s:
        return None, []
    rest = s[s.index("git") + 1:]
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("-C", "-c"):
            i += 2; continue
        if a.startswith("-"):
            i += 1; continue
        return a, rest[i + 1:]
    return None, []

def offends(s):
    sub, rest = sub_and_rest(s)
    if sub == "commit":
        return cur in PROTECTED
    if sub == "push":
        if cur in PROTECTED:           # push depuis main/development
            return True
        # refspecs = positionnels apres le remote ; dest = apres ':' (ou le token).
        positionals = [t for t in rest if not t.startswith("-")]
        for rs in positionals[1:]:
            dest = rs.split(":")[-1].lstrip("+")     # dst du refspec, sans le '+' force
            if dest.startswith("refs/heads/"):       # HEAD:refs/heads/main, :refs/heads/dev
                dest = dest[len("refs/heads/"):]
            if dest in PROTECTED:       # ex. `git push origin development`
                return True
    return False

print("block" if any(offends(s) for s in segments) else "ok")
PY
)
if [ "$verdict" = "block" ]; then
  echo "⛔ commit/push sur 'main'/'development' interdit (CLAUDE.md). Branche feature/<issue> + PR ; merge = Emmanuel." >&2
  exit 2
fi
exit 0
