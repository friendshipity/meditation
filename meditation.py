#!/usr/bin/env python3
"""Meditation: iterative reflective agent (runnable prototype)."""

from __future__ import annotations

import argparse
import json
import re
import textwrap
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional
from urllib.parse import quote
from urllib.request import urlopen


# ----------------------------
# Utility
# ----------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def estimate_tokens(text: str) -> int:
    # cheap approximation: 1 token ~= 0.75 words
    words = max(1, len(text.split()))
    return int(words / 0.75)


def trim_text(text: str, max_chars: int = 260) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def extract_keywords(text: str, top_n: int = 4) -> List[str]:
    stop = {
        "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is", "are", "be", "that", "this", "it", "as",
        "我", "你", "他", "她", "它", "我们", "你们", "他们", "的", "了", "和", "是", "在", "就", "也", "与", "及", "一个", "可以", "需要",
    }
    words = re.findall(r"[\w\u4e00-\u9fff]{2,}", text.lower())
    freq: Dict[str, int] = {}
    for w in words:
        if w in stop:
            continue
        freq[w] = freq.get(w, 0) + 1
    sorted_words = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in sorted_words[:top_n]]


# ----------------------------
# Tool: web_search with rate limit
# ----------------------------

@dataclass
class WebSearchLimiter:
    max_calls_per_hour: int = 5
    calls: Deque[datetime] = field(default_factory=deque)

    def can_call(self) -> bool:
        self._cleanup()
        return len(self.calls) < self.max_calls_per_hour

    def remaining(self) -> int:
        self._cleanup()
        return max(0, self.max_calls_per_hour - len(self.calls))

    def record(self) -> None:
        self._cleanup()
        self.calls.append(now_utc())

    def _cleanup(self) -> None:
        cutoff = now_utc() - timedelta(hours=1)
        while self.calls and self.calls[0] < cutoff:
            self.calls.popleft()


def web_search(query: str, timeout: int = 8) -> str:
    """Best-effort public search summary via Wikipedia API (no key required)."""
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(query)}"
    try:
        with urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        extract = data.get("extract")
        if extract:
            return trim_text(extract, max_chars=500)
        return "No concise summary found from web source."
    except Exception as exc:
        return f"Web search unavailable: {exc.__class__.__name__}"


# ----------------------------
# Memory engine (nanobot-style inspired)
# ----------------------------

@dataclass
class MemoryEntry:
    round_id: int
    timestamp: str
    user_input: str
    summary: str
    best_answer: str
    counter_question: str
    keywords: List[str]


@dataclass
class MemoryEngine:
    working: List[MemoryEntry] = field(default_factory=list)
    episodic: List[str] = field(default_factory=list)
    semantic: Dict[str, str] = field(default_factory=dict)
    max_working_entries: int = 6
    token_budget: int = 1400

    def recall(self) -> Dict[str, str]:
        recent = self.working[-3:]
        confirmed = [e.summary for e in recent if e.summary]
        unresolved = [e.counter_question for e in recent if e.counter_question]
        semantic_points = [f"{k}: {v}" for k, v in list(self.semantic.items())[:5]]
        return {
            "confirmed": " | ".join(trim_text(x, 120) for x in confirmed) if confirmed else "(none)",
            "unresolved": " | ".join(trim_text(x, 80) for x in unresolved) if unresolved else "(none)",
            "semantic": " | ".join(semantic_points) if semantic_points else "(none)",
        }

    def write(self, entry: MemoryEntry) -> None:
        self.working.append(entry)
        for kw in entry.keywords[:3]:
            self.semantic[kw] = trim_text(entry.best_answer, 100)
        self._compress_if_needed()

    def _compress_if_needed(self) -> None:
        while len(self.working) > self.max_working_entries:
            chunk = self.working[:2]
            self.working = self.working[2:]
            summary = self._compress_chunk(chunk)
            self.episodic.append(summary)

        all_text = "\n".join([e.summary + " " + e.best_answer for e in self.working])
        if estimate_tokens(all_text) > self.token_budget and len(self.working) >= 2:
            chunk = self.working[:2]
            self.working = self.working[2:]
            self.episodic.append(self._compress_chunk(chunk))

    def _compress_chunk(self, entries: List[MemoryEntry]) -> str:
        topics = []
        for e in entries:
            topics.extend(e.keywords)
        topic_str = ", ".join(sorted(set(topics))[:6]) or "general"
        concl = "; ".join(trim_text(e.summary, 80) for e in entries)
        unresolved = "; ".join(trim_text(e.counter_question, 60) for e in entries)
        return f"[episodic] topics={topic_str}; conclusions={concl}; unresolved={unresolved}"

    def synthesis(self, latest_summary: str) -> str:
        reinforced = self.episodic[-1] if self.episodic else "历史中暂无已归档章节，当前以工作记忆为主。"
        revised = "当前轮对先前观点进行了细化和边界收敛。"
        unresolved = self.working[-1].counter_question if self.working else "(none)"
        return (
            f"历史强化: {trim_text(reinforced, 180)}\n"
            f"历史修正: {revised}\n"
            f"未解决问题: {trim_text(unresolved, 120)}\n"
            f"本轮整合: {trim_text(latest_summary, 150)}"
        )

    def to_dict(self) -> dict:
        return {
            "working": [e.__dict__ for e in self.working],
            "episodic": self.episodic,
            "semantic": self.semantic,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEngine":
        eng = cls()
        for e in data.get("working", []):
            eng.working.append(MemoryEntry(**e))
        eng.episodic = data.get("episodic", [])
        eng.semantic = data.get("semantic", {})
        return eng


# ----------------------------
# Agent
# ----------------------------

@dataclass
class MeditationAgent:
    memory: MemoryEngine = field(default_factory=MemoryEngine)
    limiter: WebSearchLimiter = field(default_factory=WebSearchLimiter)
    round_id: int = 0

    def run_round(self, user_input: str) -> Dict[str, str]:
        self.round_id += 1
        recall = self.memory.recall()

        need_search = self._should_search(user_input, recall)
        search_note = ""
        if need_search and self.limiter.can_call():
            self.limiter.record()
            search_result = web_search(user_input)
            search_note = f"外部信息: {search_result}"
        elif need_search:
            search_note = f"外部信息: 跳过搜索（达到每小时上限 5 次，剩余 {self.limiter.remaining()} 次）"

        summary = self._meditation_summary(user_input, recall, search_note)
        best_answer = self._best_answer(user_input, recall, search_note)
        counter_q = self._counter_question(user_input)

        entry = MemoryEntry(
            round_id=self.round_id,
            timestamp=now_utc().isoformat(),
            user_input=user_input,
            summary=summary,
            best_answer=best_answer,
            counter_question=counter_q,
            keywords=extract_keywords(user_input + " " + best_answer),
        )
        self.memory.write(entry)

        synthesis = self.memory.synthesis(summary)

        return {
            "Meditation Summary": summary,
            "Memory-History Synthesis": synthesis,
            "Current Best Answer": best_answer,
            "Counter-Question": counter_q,
            "meta": f"search_remaining_this_hour={self.limiter.remaining()}",
        }

    def _should_search(self, user_input: str, recall: Dict[str, str]) -> bool:
        trigger = ["最新", "today", "news", "数据", "证据", "research", "统计", "事实", "quote"]
        if any(t in user_input.lower() for t in trigger):
            return True
        if recall["confirmed"] == "(none)":
            return True
        return False

    def _meditation_summary(self, user_input: str, recall: Dict[str, str], search_note: str) -> str:
        kws = extract_keywords(user_input)
        points = [
            f"主题聚焦在 {', '.join(kws) if kws else '核心问题'}。",
            "先以内在推理为主，再用外部信息做必要校准。",
            f"记忆回放：已确认={trim_text(recall['confirmed'], 90)}。",
        ]
        if search_note:
            points.append(trim_text(search_note, 110))
        return " ".join(points)

    def _best_answer(self, user_input: str, recall: Dict[str, str], search_note: str) -> str:
        base = (
            f"针对“{trim_text(user_input, 100)}”，当前最优策略是："
            "先定义问题边界，再拆成可验证假设，"
            "利用记忆中已验证片段进行递进式反思，"
            "仅在关键不确定点触发外部搜索。"
        )
        if search_note:
            base += " 本轮已纳入有限外部信息进行校准。"
        if recall["semantic"] != "(none)":
            base += " 同时复用了语义记忆中的稳定结论。"
        return base

    def _counter_question(self, user_input: str) -> str:
        kws = extract_keywords(user_input, top_n=2)
        seed = " / ".join(kws) if kws else "当前主题"
        return f"如果只允许再验证一个关键假设，你会优先验证 {seed} 中的哪一条，为什么？"


# ----------------------------
# Persistence + CLI
# ----------------------------

def load_agent(memory_file: Path) -> MeditationAgent:
    if memory_file.exists():
        data = json.loads(memory_file.read_text(encoding="utf-8"))
        agent = MeditationAgent(memory=MemoryEngine.from_dict(data.get("memory", {})))
        agent.round_id = int(data.get("round_id", 0))
        return agent
    return MeditationAgent()


def save_agent(agent: MeditationAgent, memory_file: Path) -> None:
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {"round_id": agent.round_id, "memory": agent.memory.to_dict()}
    memory_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def print_round(result: Dict[str, str]) -> None:
    print("\n## Meditation Summary")
    print(textwrap.fill(result["Meditation Summary"], width=100))
    print("\n## Memory-History Synthesis")
    print(textwrap.fill(result["Memory-History Synthesis"], width=100))
    print("\n## Current Best Answer")
    print(textwrap.fill(result["Current Best Answer"], width=100))
    print("\n## Counter-Question")
    print(result["Counter-Question"])
    print(f"\n(meta) {result['meta']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Meditation iterative reflective agent (prototype)")
    parser.add_argument("--topic", type=str, help="Initial topic/question")
    parser.add_argument("--rounds", type=int, default=1, help="How many rounds to run")
    parser.add_argument("--auto", action="store_true", help="Auto-feed counter-question to next round")
    parser.add_argument("--memory-file", type=Path, default=Path(".meditation/memory.json"))
    args = parser.parse_args()

    agent = load_agent(args.memory_file)

    if args.topic:
        current_input = args.topic
    else:
        current_input = input("输入你的话题/问题: ").strip()

    for i in range(max(1, args.rounds)):
        if not current_input:
            break
        print(f"\n===== Round {agent.round_id + 1} =====")
        result = agent.run_round(current_input)
        print_round(result)
        save_agent(agent, args.memory_file)

        if i == args.rounds - 1:
            break

        if args.auto:
            current_input = result["Counter-Question"]
        else:
            nxt = input("\n下一轮输入（直接回车则使用反问）: ").strip()
            current_input = nxt if nxt else result["Counter-Question"]


if __name__ == "__main__":
    main()
