---
name: meditate
description: 循环冥想式思考工具。给定一个话题与轮数,在一个回合内自动连跑 N 轮内省反思:少搜多想(web_search 每小时 5 次硬限)、nanobot 分层记忆 + 递归自动压缩、批判性 Observer 子智能体每轮审视并把批判反馈进下一轮。输出是历史记忆的纵向综合,而非单轮快照。当用户输入 /meditate "<话题>" [--rounds N] [--no-search] [--session S] [--new],或要求"冥想/闭关思考/深度反思某话题"时使用。
---

# /meditate — 闭关冥想式思考

你将扮演 `meditation` 主体,按本文件编排,在**一个回合内自动连跑 N 轮**深度反思。推理人格见 `.claude/skills/meditate/prompt/system.md`(开始前先读它并采纳)。

## 0. 全局约定
- 工作目录 = 项目根。脚本目录 `S=.claude/skills/meditate/scripts`,数据根 `.meditation/`。
- **全程不向用户提问、不等待**。每轮一完成就把四段输出打印出来供用户「瞄一眼」,随即进入下一轮。轮间只做必要的脚本 / observer 调用,不加寒暄、不复述编排步骤。
- 脚本调用一律从项目根执行 `python3 $S/<脚本> ...`。

## 1. 解析参数
从用户输入解析:
- `话题`(必需:第一个引号串;无引号则取整句)
- `--rounds N`(默认 **5**)
- `--no-search`(禁用搜索)
- `--session S`(默认 `default`)
- `--new`(开新思考线)

记住 `SESSION`、`ROUNDS`、`SESS_DIR=.meditation/<SESSION>`。

## 2. 启动准备(仅一次)
1. 读 `.claude/skills/meditate/prompt/system.md`,采纳该人格与各 Policy。
2. 若带 `--new`:先 `python3 $S/memory.py status --session "$SESSION"`;若 working/episodic 非空,`recall` 读出要点 → 蒸馏成 1–2 条稳定知识用 `memory.py promote` 写入 semantic(归档)→ 再 `python3 $S/memory.py reset-volatile --session "$SESSION"`。
3. **准备 Observer**:读 `.claude/skills/meditate/prompt/observer.md` 备用。Observer 采用**每轮新建一个 Haiku 子 agent**的方式(见步骤 5),靠喂入累积的 `insight.md` 获得跨轮连续性(本 harness 无 SendMessage,故不用常驻 agent)。
4. 初始化:`current_input = 话题`,`observer_next = (无)`。

## 3. 单轮循环（for r = 1..ROUNDS,严格按序执行）

**(1) Recall** — `python3 $S/memory.py recall --session "$SESSION"`,读取输出(含上一轮 observer 批判)作为本轮记忆基底。

**(2) Search Gate**（`--no-search` 时整步跳过）
仅当「记忆/上下文确不足以回答 `current_input`,且需要外部事实/证据」时才考虑搜索:
- `python3 $S/search_limiter.py can` → 看返回的 `allowed`;
- 允许:用 **WebSearch** 搜一次 → `python3 $S/search_limiter.py record` → 对结果做高密度提炼;
- 不允许:记下「本小时配额用尽」,改用现有记忆给临时最优解。

**(3) Think** — 围绕 `current_input` + recall +（可选）搜索结果 + `observer_next` 做相关联想与反思。发散但相关,不强求收敛,显式标注不确定。

**(4) Emit 四段（打印给用户）** — 按 system.md 的 Output Contract:
```
===== Round r / ROUNDS =====
## Meditation Summary
…（2–5 条 + 本轮增量）
## Memory-History Synthesis
- 历史强化:…
- 历史修正:…
- 未解决问题:…
## Current Best Answer
…
## Counter-Question
…（仅 1 个）
```

**(5) Observe（feed-forward）** — 用 **Agent** 工具新建一个 Haiku observer(`subagent_type: general-purpose`,`model: haiku`),prompt = `observer.md` 全文 + 截至目前的 `$SESS_DIR/insight.md` 内容(给它跨轮连续性)+ 本轮的 `current_input` + 四段 + 关键思路。若 Agent 不可用/失败则降级跳过本步、收尾说明。拿到它的 `INSIGHT / CRITIQUE / NEXT` 后:
- 追加写入 insight.md：
  ```
  cat >> "$SESS_DIR/insight.md" <<'MD'
  ## Round r — <话题缩写>
  - INSIGHT: …
  - CRITIQUE: …
  - NEXT: …
  MD
  ```
- 存为下一轮反馈:`python3 $S/memory.py set-observer --session "$SESSION"`（把 `CRITIQUE + NEXT` 文本走 stdin 传入），并设 `observer_next = NEXT`。
- 若 observer 处于降级模式则跳过本步。

**(6) Memory Write + 信号处理** — 构造**单行** JSON 条目（各字段单行、精炼;含你对本轮的打分 importance/novelty/reusability/relevance ∈ 0–1）写入:
```
python3 $S/memory.py write --session "$SESSION" <<'JSON'
{"round":r,"input":"…","summary":"…","synthesis":"…","answer":"…","counter_question":"…","keywords":["…"],"scores":{"importance":0.x,"novelty":0.x,"reusability":0.x,"relevance":0.x}}
JSON
```
读返回的 `signals`,**当轮逐一提交**（顺序 compress → consolidate → promote;勿留到下一轮):
- `compress != null`:对其中的 `entries` 产出一段高密度阶段摘要（保留 关键结论/核心分歧/高价值反问/失败路径），提交
  `python3 $S/memory.py replace-working --session "$SESSION" --drop <drop_ids 逗号分隔>`（摘要走 stdin）。
- `consolidate != null`:把给出的最旧 `count` 条 episodic `summaries` 蒸馏成 1 条稳定知识,提交
  `python3 $S/memory.py replace-episodic --session "$SESSION" --count <count>`（蒸馏文本走 stdin）。
- `promote != null`:把该高分条目提炼成 1 条稳定知识
  `python3 $S/memory.py promote --session "$SESSION"`（文本走 stdin）。

**(7) Chain** — `current_input = 本轮 Counter-Question`,进入下一轮(不停顿、不询问用户)。

## 4. 收尾（N 轮后)
打印简短结语:本主题当前收敛度、仍开放的核心问题、可作下次入口的反问;并指出 observer 洞察在 `.meditation/<SESSION>/insight.md`、记忆落盘在 `.meditation/<SESSION>/`。若 observer 曾降级,在此说明。

## 5. 硬约束（复述,务必遵守)
- **少搜多想**:搜索非默认动作,且每次都先问 `search_limiter.py can`。
- **压缩必须执行**:write 返回的信号当轮处理掉,不累积、不跳过。
- **输出永远是历史综合**:`Memory-History Synthesis` 段不可省。
- **全程自动连跑**:只打印,不提问,不等待用户。
