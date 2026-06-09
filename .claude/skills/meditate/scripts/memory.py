#!/usr/bin/env python3
"""memory.py — nanobot-style layered memory for the meditation skill.

Division of labour (the core design): this script owns *deterministic* state —
persistence, token budgeting, and WHEN to compress. The model (Claude) owns
*quality* — it produces the actual summaries / distillations and hands them
back here to be stored. Recall injects only a "minimal-sufficient" slice.

Three layers, per session, under <root>/<session>/:
    working.json   recent rounds (raw key content; bounded by WORKING budget)
    episodic.json  stage summaries (compressed working; bounded by EPISODIC budget)
    semantic.json  stable distilled knowledge (reused across sessions/lines)
    meta.json      round counter, line counter, status, last observer note

Token compression is RECURSIVE so arbitrarily long meditation never overflows:
    working over budget  -> signal `compress`     (model folds oldest into episodic)
    episodic over budget -> signal `consolidate`  (model distills oldest into semantic)

Commands (run from project root):
    write           --session S          # entry JSON on stdin -> JSON {signals}
    recall          --session S          # -> markdown injection bundle
    replace-working --session S --drop 1,2   # episodic summary on stdin (commit a compress)
    replace-episodic --session S --count 2   # semantic statement on stdin (commit a consolidate)
    promote         --session S          # semantic statement on stdin
    set-observer    --session S          # observer note on stdin (feed-forward)
    reset-volatile  --session S          # clear working+episodic, keep semantic (for --new)
    status          --session S          # -> JSON state

Budget overrides (also useful for tests): --working-budget, --episodic-budget, --max-working
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKING_TOKEN_BUDGET = 1800
EPISODIC_TOKEN_BUDGET = 1200
MAX_WORKING_ENTRIES = 8
PROMOTE_IMPORTANCE = 0.7   # promote candidate when importance >= this ...
PROMOTE_REUSABILITY = 0.6  # ... and reusability >= this


# ---------------------------------------------------------------- utilities
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def estimate_tokens(text: str) -> int:
    """Heuristic token estimate. CJK chars count ~1 token each; ASCII ~words/0.75.
    Approximate by design (precise counting is left to the python-standalone branch)."""
    if not text:
        return 0
    cjk = len(re.findall(r"[一-鿿]", text))
    ascii_part = re.sub(r"[一-鿿]", " ", text)
    words = len(ascii_part.split())
    return cjk + int(round(words / 0.75))


def _entry_tokens(e: dict) -> int:
    return sum(estimate_tokens(str(e.get(k, "")))
               for k in ("input", "summary", "synthesis", "answer", "counter_question"))


def _safe_session(name: str) -> str:
    name = re.sub(r"[^0-9A-Za-z._-]", "-", (name or "default").strip())
    return name or "default"


# ---------------------------------------------------------------- storage
def _sdir(root: Path, session: str) -> Path:
    return root / _safe_session(session)


def _read(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_all(root: Path, session: str):
    d = _sdir(root, session)
    working = _read(d / "working.json", [])
    episodic = _read(d / "episodic.json", [])
    semantic = _read(d / "semantic.json", [])
    meta = _read(d / "meta.json", {})
    if not meta:
        meta = {"session": _safe_session(session), "rounds": 0, "line": 1,
                "status": "active", "created": _now(), "updated": _now(),
                "last_observer_note": ""}
    return d, working, episodic, semantic, meta


def _save_all(d: Path, working=None, episodic=None, semantic=None, meta=None) -> None:
    if working is not None:
        _write(d / "working.json", working)
    if episodic is not None:
        _write(d / "episodic.json", episodic)
    if semantic is not None:
        _write(d / "semantic.json", semantic)
    if meta is not None:
        meta["updated"] = _now()
        _write(d / "meta.json", meta)


# ---------------------------------------------------------------- compression selection
def _select_compress(working, budget: int, max_entries: int):
    """Oldest-first entries to fold so the remainder fits budget AND max_entries.
    Always keeps at least the newest entry."""
    rem_tokens = sum(_entry_tokens(e) for e in working)
    rem_n = len(working)
    drop, i = [], 0
    while (rem_tokens > budget or rem_n > max_entries) and i < len(working) - 1:
        drop.append(working[i])
        rem_tokens -= _entry_tokens(working[i])
        rem_n -= 1
        i += 1
    return drop


def _select_consolidate(episodic, budget: int):
    rem = sum(estimate_tokens(e.get("summary", "")) for e in episodic)
    drop, i = [], 0
    while rem > budget and i < len(episodic) - 1:
        drop.append(episodic[i])
        rem -= estimate_tokens(episodic[i].get("summary", ""))
        i += 1
    return drop


# ---------------------------------------------------------------- commands
def cmd_write(root, session, args) -> int:
    raw = sys.stdin.read()
    try:
        entry = json.loads(raw)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": f"invalid entry JSON: {exc}"}, ensure_ascii=False))
        return 2

    d, working, episodic, semantic, meta = _load_all(root, session)
    meta["rounds"] = int(meta.get("rounds", 0)) + 1
    entry.setdefault("round", meta["rounds"])
    entry.setdefault("ts", _now())
    entry.setdefault("scores", {})
    working.append(entry)
    _save_all(d, working=working, meta=meta)

    drop = _select_compress(working, args.working_budget, args.max_working)
    cons = _select_consolidate(episodic, args.episodic_budget)
    scores = entry.get("scores", {}) or {}
    promote = (float(scores.get("importance", 0)) >= PROMOTE_IMPORTANCE
               and float(scores.get("reusability", 0)) >= PROMOTE_REUSABILITY)

    signals = {
        "compress": ({"drop_ids": [e.get("round") for e in drop], "entries": drop}
                     if drop else None),
        "consolidate": ({"count": len(cons),
                         "summaries": [e.get("summary", "") for e in cons]}
                        if cons else None),
        "promote": ({"entry": entry} if promote else None),
    }
    print(json.dumps({
        "ok": True,
        "round": meta["rounds"],
        "working_tokens": sum(_entry_tokens(e) for e in working),
        "working_budget": args.working_budget,
        "working_count": len(working),
        "max_working": args.max_working,
        "episodic_tokens": sum(estimate_tokens(e.get("summary", "")) for e in episodic),
        "episodic_budget": args.episodic_budget,
        "signals": signals,
    }, ensure_ascii=False))
    return 0


def _bullets(items, n, empty="(暂无)"):
    items = [x for x in items if x]
    if not items:
        return empty
    return "\n".join(f"- {x}" for x in items[-n:])


def cmd_recall(root, session, args) -> int:
    d, working, episodic, semantic, meta = _load_all(root, session)
    recent = working[-3:]
    confirmed = [f"R{e.get('round')}: {e.get('summary','')}" for e in recent]
    open_threads = [f"R{e.get('round')}: {e.get('counter_question','')}" for e in recent]
    epi = [e.get("summary", "") for e in episodic[-2:]]
    sem = [s.get("statement", "") if isinstance(s, dict) else str(s) for s in semantic[-6:]]
    obs = meta.get("last_observer_note", "")

    wtok = sum(_entry_tokens(e) for e in working)
    etok = sum(estimate_tokens(e.get("summary", "")) for e in episodic)

    out = []
    out.append(f"# 记忆回放 — session: {meta.get('session')} | 已进行 {meta.get('rounds',0)} 轮 | line {meta.get('line',1)}")
    out.append("（注入遵循「最小充分」，仅给关键轨迹，不灌全历史）\n")
    out.append("## 已确认 / 近期结论 (working)")
    out.append(_bullets(confirmed, 3))
    out.append("\n## 开放线索 / 近期反问")
    out.append(_bullets(open_threads, 3))
    out.append("\n## 阶段摘要 (episodic)")
    out.append(_bullets(epi, 2))
    out.append("\n## 稳定知识 (semantic)")
    out.append(_bullets(sem, 6))
    out.append("\n## 上一轮 Observer 批判（feed-forward）")
    out.append(obs.strip() if obs.strip() else "(暂无)")
    out.append("\n## 预算状态")
    out.append(f"working: {wtok}/{args.working_budget} tok · {len(working)} 条 | "
               f"episodic: {etok}/{args.episodic_budget} tok · {len(episodic)} 条 | "
               f"semantic: {len(semantic)} 条")
    print("\n".join(out))
    return 0


def cmd_replace_working(root, session, args) -> int:
    summary = sys.stdin.read().strip()
    if not summary:
        print(json.dumps({"ok": False, "error": "empty episodic summary on stdin"}, ensure_ascii=False))
        return 2
    drop_ids = {int(x) for x in str(args.drop).split(",") if x.strip().isdigit()} if args.drop else set()
    d, working, episodic, semantic, meta = _load_all(root, session)
    covered = [e.get("round") for e in working if e.get("round") in drop_ids]
    working = [e for e in working if e.get("round") not in drop_ids]
    episodic.append({"id": len(episodic) + 1, "ts": _now(), "summary": summary, "covers": covered})
    _save_all(d, working=working, episodic=episodic, meta=meta)
    print(json.dumps({"ok": True, "folded_rounds": covered,
                      "working_count": len(working), "episodic_count": len(episodic),
                      "episodic_tokens": sum(estimate_tokens(e.get("summary", "")) for e in episodic)},
                     ensure_ascii=False))
    return 0


def cmd_replace_episodic(root, session, args) -> int:
    statement = sys.stdin.read().strip()
    if not statement:
        print(json.dumps({"ok": False, "error": "empty semantic statement on stdin"}, ensure_ascii=False))
        return 2
    k = max(1, int(args.count))
    d, working, episodic, semantic, meta = _load_all(root, session)
    dropped, episodic = episodic[:k], episodic[k:]
    semantic.append({"id": len(semantic) + 1, "ts": _now(), "statement": statement,
                     "from_episodic": [e.get("id") for e in dropped]})
    _save_all(d, episodic=episodic, semantic=semantic, meta=meta)
    print(json.dumps({"ok": True, "consolidated": len(dropped),
                      "episodic_count": len(episodic), "semantic_count": len(semantic)},
                     ensure_ascii=False))
    return 0


def cmd_promote(root, session, args) -> int:
    statement = sys.stdin.read().strip()
    if not statement:
        print(json.dumps({"ok": False, "error": "empty statement on stdin"}, ensure_ascii=False))
        return 2
    d, working, episodic, semantic, meta = _load_all(root, session)
    semantic.append({"id": len(semantic) + 1, "ts": _now(), "statement": statement, "from_episodic": []})
    _save_all(d, semantic=semantic, meta=meta)
    print(json.dumps({"ok": True, "semantic_count": len(semantic)}, ensure_ascii=False))
    return 0


def cmd_set_observer(root, session, args) -> int:
    note = sys.stdin.read().strip()
    d, working, episodic, semantic, meta = _load_all(root, session)
    meta["last_observer_note"] = note
    _save_all(d, meta=meta)
    print(json.dumps({"ok": True, "stored_chars": len(note)}, ensure_ascii=False))
    return 0


def cmd_reset_volatile(root, session, args) -> int:
    d, working, episodic, semantic, meta = _load_all(root, session)
    meta["line"] = int(meta.get("line", 1)) + 1
    meta["last_observer_note"] = ""
    _save_all(d, working=[], episodic=[], meta=meta)
    print(json.dumps({"ok": True, "line": meta["line"], "semantic_kept": len(semantic)},
                     ensure_ascii=False))
    return 0


def cmd_status(root, session, args) -> int:
    d, working, episodic, semantic, meta = _load_all(root, session)
    print(json.dumps({
        "ok": True,
        "session": meta.get("session"),
        "rounds": meta.get("rounds", 0),
        "line": meta.get("line", 1),
        "working_count": len(working),
        "working_tokens": sum(_entry_tokens(e) for e in working),
        "working_budget": args.working_budget,
        "episodic_count": len(episodic),
        "episodic_tokens": sum(estimate_tokens(e.get("summary", "")) for e in episodic),
        "episodic_budget": args.episodic_budget,
        "semantic_count": len(semantic),
        "has_observer_note": bool(meta.get("last_observer_note")),
    }, ensure_ascii=False))
    return 0


COMMANDS = {
    "write": cmd_write,
    "recall": cmd_recall,
    "replace-working": cmd_replace_working,
    "replace-episodic": cmd_replace_episodic,
    "promote": cmd_promote,
    "set-observer": cmd_set_observer,
    "reset-volatile": cmd_reset_volatile,
    "status": cmd_status,
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Layered memory engine for meditation")
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("--session", default="default")
    ap.add_argument("--root", default=".meditation", type=Path)
    ap.add_argument("--drop", default="", help="comma-separated working round ids (replace-working)")
    ap.add_argument("--count", default=1, type=int, help="oldest episodic entries to fold (replace-episodic)")
    ap.add_argument("--working-budget", dest="working_budget", default=WORKING_TOKEN_BUDGET, type=int)
    ap.add_argument("--episodic-budget", dest="episodic_budget", default=EPISODIC_TOKEN_BUDGET, type=int)
    ap.add_argument("--max-working", dest="max_working", default=MAX_WORKING_ENTRIES, type=int)
    args = ap.parse_args()
    return COMMANDS[args.command](args.root, args.session, args)


if __name__ == "__main__":
    sys.exit(main())
