#!/usr/bin/env python3
"""Trace l'usage de l'outillage .claude (agents / skills / commands).

Branché sur PostToolUse (tous tools) + UserPromptSubmit.
Jamais bloquant : exit 0 systématique, try/except global, zéro réseau.
Append-only JSONL dans ~/.claude/logs/tool-usage.jsonl (agrégation multi-repo).

Lecture défensive (.get partout) : robuste si les noms de champs varient
selon la version de Claude Code. ECC_USAGE_VERBOSE=1 logue aussi les tools bruts.
"""

import json
import os
import sys
from datetime import datetime, timezone

LOG = os.path.expanduser("~/.claude/logs/tool-usage.jsonl")


def build_record(data):
    """Retourne un dict à logger, ou None si l'event ne nous intéresse pas."""
    event = data.get("hook_event_name", "")

    if event == "PostToolUse":
        tool = data.get("tool_name", "")
        tool_input = data.get("tool_input", {}) or {}
        if tool in ("Task", "Agent"):
            name = tool_input.get("subagent_type") or data.get("agent_type") or "?"
            return {"kind": "agent", "name": name, "tool": tool}
        if tool == "Skill":
            name = tool_input.get("skill") or tool_input.get("name") or "?"
            return {"kind": "skill", "name": name, "tool": tool}
        if os.environ.get("ECC_USAGE_VERBOSE") == "1":
            return {"kind": "tool", "name": tool, "tool": tool}
        return None

    if event == "UserPromptSubmit":
        prompt = (data.get("prompt") or "").strip()
        if prompt.startswith("/"):
            return {"kind": "command", "name": prompt.split()[0], "tool": ""}
        return None

    return None


def main():
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    rec = build_record(data)
    if not rec:
        return
    rec.update(
        {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cwd": data.get("cwd", ""),
            "session": data.get("session_id", ""),
        }
    )
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # un échec de log ne doit JAMAIS bloquer le flux
    sys.exit(0)
