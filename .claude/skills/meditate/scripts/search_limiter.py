#!/usr/bin/env python3
"""search_limiter.py — deterministic global rate limiter for web_search.

The meditation skill enforces "少搜多想": web_search is capped at MAX calls per
rolling hour, shared across ALL sessions (it is a real-world constraint, not a
per-thread budget). This script owns the *counting and enforcement* — the model
only performs a search when this script says it may. A pure markdown skill could
not guarantee this; that is the whole reason the helper exists.

Run from the project root (data lives in ./.meditation/search_log.json):

    python3 search_limiter.py can        # JSON {allowed, remaining, ...}; exit 0 allowed / 3 blocked
    python3 search_limiter.py record     # record one call now -> JSON; exit 3 if it would exceed
    python3 search_limiter.py remaining  # JSON {remaining}
    python3 search_limiter.py status     # JSON full state

Options:
    --root DIR    data root (default: .meditation)
    --max N       max calls per rolling window (default: 5)
    --window S    rolling window in seconds (default: 3600)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_MAX = 5
DEFAULT_WINDOW = 3600  # seconds


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log_path(root: Path) -> Path:
    return root / "search_log.json"


def _parse(stamp: str):
    try:
        t = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t


def _load(root: Path):
    p = _log_path(root)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return [str(x) for x in data] if isinstance(data, list) else []


def _save(root: Path, stamps) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _log_path(root).write_text(
        json.dumps(stamps, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _active(stamps, window: int):
    cutoff = _now() - timedelta(seconds=window)
    out = []
    for s in stamps:
        t = _parse(s)
        if t is not None and t >= cutoff:
            out.append(s)
    return out


def _state(root: Path, max_calls: int, window: int):
    stamps = _active(_load(root), window)
    remaining = max(0, max_calls - len(stamps))
    next_reset = None
    if stamps:
        oldest = min(_parse(s) for s in stamps)
        next_reset = (oldest + timedelta(seconds=window)).isoformat()
    return stamps, remaining, next_reset


def main() -> int:
    ap = argparse.ArgumentParser(description="Global web_search rate limiter")
    ap.add_argument("command", choices=["can", "record", "remaining", "status"])
    ap.add_argument("--root", default=".meditation", type=Path)
    ap.add_argument("--max", dest="max_calls", default=DEFAULT_MAX, type=int)
    ap.add_argument("--window", default=DEFAULT_WINDOW, type=int)
    args = ap.parse_args()

    root: Path = args.root
    stamps, remaining, next_reset = _state(root, args.max_calls, args.window)
    allowed = remaining > 0

    if args.command == "record":
        if not allowed:
            print(json.dumps(
                {"ok": False, "recorded": False, "reason": "limit_reached",
                 "remaining": 0, "max": args.max_calls, "next_reset": next_reset},
                ensure_ascii=False))
            return 3
        stamps.append(_now().isoformat())
        _save(root, stamps)
        print(json.dumps(
            {"ok": True, "recorded": True,
             "remaining": max(0, args.max_calls - len(stamps)), "max": args.max_calls},
            ensure_ascii=False))
        return 0

    payload = {
        "ok": True,
        "allowed": allowed,
        "remaining": remaining,
        "used": len(stamps),
        "max": args.max_calls,
        "window_seconds": args.window,
        "next_reset": next_reset,
    }
    print(json.dumps(payload, ensure_ascii=False))
    # exit code lets the skill branch on `can` without parsing: 0 = may search, 3 = blocked
    if args.command == "can":
        return 0 if allowed else 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
