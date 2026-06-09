# Plan — Meditation 思考工具(Claude Code 内运行版)

> 本文件是动手前的实现计划。确认无误后再写 skill 与脚本。
> 目标形态:**配置 ②**——Claude Code 内部的闭关思考工具。大脑 = Claude(CC 会话本身),控制层 = skill + helper 脚本,推理层 = 外置 prompt。

---

## 0. 一句话定义

给定一个话题与轮数,`/meditate` 让 Claude **自己连续闭关思考 N 轮**:每轮先翻记忆、必要时(受 5次/小时硬限制)才搜、做联想反思、固定吐 4 段输出,并把本轮反问自动喂给下一轮;关键内容滚动写入分层记忆并按 token 压缩。最终输出是**历史记忆的纵向综合**,不是单轮快照。

---

## 1. 范围(v1)与非目标

**v1 要做:**
- `/meditate` skill:N 轮自动连跑,轮间不阻塞。
- 搜索频控脚本:可靠强制 5 次/小时。
- 分层记忆脚本:working / episodic / semantic 的读 / 写 / 压缩 / 持久化,按 session 累积。
- 4 段输出契约(吸收 `docs/PROMPT_SPEC.md`)。
- 每轮即时打印输出供"瞄一眼",但不暂停等待。

**v1 非目标(后续/或留给 `python-standalone` 分支):**
- 脱离 CC 的独立运行 / API 化 / MCP server。
- 精确 token 计数(v1 用启发式估算)。
- eval / 多模型 / UI。
- 自动判定"主题已收敛"而提前终止(v1 跑满 N 轮,只在输出里提示收敛度)。

---

## 2. 两条分支

| 分支 | 来源 | 用途 | 现在动它吗 |
|------|------|------|-----------|
| `cc-thinking-tool` | `main` | **本计划的实现**:CC 内思考工具 | ✅ 主战场 |
| `python-standalone` | n2lavy 原型 | 独立 Python 产品化的**种子/提示**,后续回来做配置 ③ | ❌ 仅占位 |

---

## 3. 架构:三层各司其职

| 层 | 谁负责 | 内容 |
|----|--------|------|
| **推理层** | Claude(我) | 联想反思、4 段输出、压缩时的"高质量摘要"、语义提炼 |
| **控制层** | helper 脚本(确定性) | 搜索频控的**计数与强制**、记忆的**持久化**、token 预算的**触发判定** |
| **编排层** | SKILL.md | 把上面两者串成"每轮流程 + N 轮循环",规定何时调哪个脚本 |

> 核心原则:**内容质量交给模型,硬约束交给脚本**。频控和压缩触发是本项目卖点,必须确定性可强制——这正是不能用纯 markdown skill 的原因。

---

## 4. 文件结构(落在 `cc-thinking-tool`)

```text
.claude/skills/meditate/
  SKILL.md                # 触发方式 + 角色 + 循环协议 + 输出契约 + 何时调哪个脚本
  scripts/
    search_limiter.py     # 搜索频控:can / record / remaining(全局滑动窗口)
    memory.py             # 分层记忆:recall / write / compress / promote / status
  prompt/
    system.md             # 推理层 system prompt(吸收 PROMPT_SPEC.md,可独立迭代)
.meditation/              # 运行时数据(加入 .gitignore,不入库)
  search_log.json         # 全局搜索时间戳(5次/小时跨 session 共享)
  <session>/
    working.json          # 近几轮关键内容(受 token 预算约束)
    episodic.json         # 阶段摘要(压缩产物)
    semantic.json         # 稳定事实 / 偏好 / 策略(跨 session 复用)
    meta.json             # 轮次计数、token 估算、session 状态、起止时间
plan.md                   # 本文件
```

---

## 5. 调用接口

```bash
/meditate "<话题或问题>" [--rounds N] [--no-search] [--session <id>] [--new]
```
- `--rounds N`:闭关轮数,默认 **3**。
- `--no-search`:本次纯内省,完全禁用搜索。
- `--session <id>`:指定 / 续接某条思考线;默认 `default`。
- `--new`:把当前 session 归档进 semantic 后,开一条干净的(对应"新建 session 后结束")。

---

## 6. 单轮流程(实现 `docs/LOOP.md`)

每轮 `r`(1..N)严格按序执行:

1. **Recall** — `memory.py recall --session S`
   - 返回"最小充分"上下文:已确认结论 / 已修正观点 / 未决问题 + 相关 semantic 事实。
2. **Search Gate** — 记忆优先,判断是否真的缺信息。
   - 若需要搜索:先 `search_limiter.py can` →
     - 允许 → 调内置 **WebSearch** → `search_limiter.py record`;
     - 拒绝(配额用尽)→ 不搜,明确标注缺口,用现有记忆给临时最优解。
   - `--no-search` 时直接跳过。
3. **Think(联想反思)** — 围绕 输入 + 记忆 +(可选)搜索结果发散,但保持相关;不强求本轮收敛。
4. **Emit 4 段** —(立即打印,供"瞄一眼")
   - `Meditation Summary`(2–5 条洞察 + 相对上轮的增量)
   - `Memory-History Synthesis`(历史强化 / 历史修正 / 未解决)
   - `Current Best Answer`(允许保留不确定性)
   - `Counter-Question`(且仅 1 个,作为下轮输入)
5. **Memory Write** — `memory.py write --session S --entry <json>`
   - entry 含打分:importance / novelty / reusability / relevance。
   - 脚本返回信号:
     - `compress`:working 超 token 预算 → **我**对最旧的若干条产出高密度摘要(保留:关键结论 / 核心分歧 / 高价值反问 / 失败路径;丢弃低密度重复)→ `memory.py write-episodic`。
     - `promote`:高分项 → **我**提炼稳定语义 → `memory.py promote`。
6. **Chain** — 用本轮 `Counter-Question` 作为下一轮输入。

**收尾(N 轮后)**:一段简短结语——本主题当前收敛度、仍开放的核心问题、可作为下次入口的反问。不冗长。

> "瞄一眼但不影响效率":每轮一完成就把 4 段打出来形成可读的流;轮间只跑必要脚本调用,不提问、不等待、不加仪式。

---

## 7. 记忆设计(实现 `docs/MEMORY.md`,nanobot 风格)

**分层与流向:**
- `working`:近几轮原始关键信息;超预算时最旧的被折叠。
- `episodic`:working 压缩成的阶段摘要(保因果链/观点变化/未决)。
- `semantic`:抽象后的稳定事实/偏好/策略,跨 session 复用。

**压缩(关键设计·混合):**
- **脚本决定"何时压"**(确定性):`memory.py` 用启发式估算 token,working 超 `WORKING_TOKEN_BUDGET`(默认 ~2000,可配)即触发。
- **模型决定"压成什么"**(高质量):由我产出密集摘要,再写回。
- 这样既保证"压缩必然发生"(卖点),又不牺牲摘要质量。v1 另留**纯启发式 fallback**,供脚本单独调用时用。

**写入打分**:importance / novelty / reusability / relevance;仅高分进 semantic。

**注入原则**:recall 遵循"最小充分",不把全部历史塞进上下文。

**session 生命周期(对齐你的点 3)**:
- 同一 session 内 **跨 N 轮、跨多次 `/meditate` 调用持续累积**。
- `--new` 或换新 `--session`:当前线归档(working+episodic 蒸馏进 semantic)→ 开干净的 working。
- *待确认*:这是我对"会累计 / 新建 session 后结束"的理解,见 §10。

---

## 8. 搜索频控设计(实现 `docs/TOOLS.md`)

- 全局滑动窗口:`.meditation/search_log.json` 存 ISO 时间戳列表。
- `search_limiter.py can`:剔除 1 小时前的,`len < 5` 则允许(退出码/打印 yes+remaining)。
- `search_limiter.py record`:追加当前时间戳。
- `search_limiter.py remaining`:打印剩余次数。
- 跨 session 共享(5次/小时是对外部世界的真实约束,非每条思考线各 5 次)。
- SKILL.md 强约束:搜索非默认动作;能由记忆/上下文得出结论时禁止搜。

---

## 9. 构建顺序(批准后执行)

1. `.gitignore` 加 `.meditation/`。
2. `scripts/search_limiter.py` + 自测(can/record/remaining 滑动窗口正确)。
3. `scripts/memory.py` + 自测(recall/write/compress 触发/promote/持久化往返)。
4. `prompt/system.md`(从 `docs/PROMPT_SPEC.md` 迁移并精炼)。
5. `SKILL.md`(编排:单轮流程 + N 轮循环 + 何时调哪个脚本 + 输出契约)。
6. 端到端试跑:`/meditate "<测试话题>" --rounds 3`,验证连跑、打印、记忆落盘、频控生效。
7. 跑第二次同 session,验证跨 session 记忆续接;`--new` 验证归档重置。

---

## 10. 开工前待你确认的假设

1. **session 生命周期**:同 session 持续累积、`--new` 归档重置——这样理解对吗?
2. **默认轮数 3** 合适?还是你常用别的数(如 5)。
3. **token 预算用启发式估算**(非精确)在 v1 可接受?(精确计数留到 `python-standalone`。)
4. **压缩摘要由我(模型)产出、脚本只管触发+落盘** 的混合方案——认可吗?(纯脚本启发式质量差。)

> 以上无异议,我按 §9 顺序开始实现。
