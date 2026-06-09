# meditation

`meditation` 是一个“低频外部输入 + 高频内在反思”的循环式智能体项目。

核心思想：
- 用户输入一个话题或问题。
- 模型在必要时进行外部搜索（受限使用）。
- 模型围绕话题做开放式联想与反思（`think` 没有刚性目标，只要相关即可）。
- 模型输出：
  1) 阶段性总结；
  2) 一个反问（该反问会作为下一轮用户输入）；
- 循环往复，在“内审 + 记忆”的过程中逐步获得更高质量的理解与回答。

> meditation 的含义：接受少量外部信息，不断反思、回答，并在内审中累积更高智能。

## 使用说明

本项目以 **Claude Code skill** 的形式落地，命令是 `/meditate`。在项目根目录打开 Claude Code 后，一个回合内即可自动连跑 N 轮反思。

### 安装

skill 随仓库分发（在 `.claude/skills/meditate/`），**无需额外安装**：

```bash
git clone git@github.com:friendshipity/meditation.git
cd meditation
claude            # 在项目根启动 Claude Code，/meditate 即可用
```

依赖：`python3`（脚本仅用标准库，无需 pip 安装）。

> 想在任意目录都能用？把它装成**用户级** skill：
> `cp -r .claude/skills/meditate ~/.claude/skills/`

### 基本用法

```text
/meditate "<话题>" [--rounds N] [--no-search] [--session S] [--new]
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `话题` | 必填 | 第一个引号串即话题；不加引号则取整句 |
| `--rounds N` | `5` | 自动连跑的反思轮数 |
| `--no-search` | 关 | 全程禁用外部搜索，纯内推 |
| `--session S` | `default` | 思考线名称，不同 session 记忆互相隔离 |
| `--new` | 关 | 在同名 session 上开新思考线：先把旧记忆蒸馏归档进 semantic，再清空易失层 |

也可以不打命令，直接说「**闭关思考 / 深度反思 / 冥想一下 XXX**」，skill 会被自动触发。

### 例子

```text
/meditate "什么是好的抽象" --rounds 8
/meditate "复盘这次架构选型的得失" --session arch --new
/meditate "纯逻辑推演电车难题" --no-search --rounds 6
```

### 每轮输出（四段）

每轮跑完会即时打印，供你「瞄一眼」，随即进入下一轮，**全程不向你提问、不等待**：

1. **Meditation Summary** — 本轮 2–5 条洞察 + 相对上轮的增量
2. **Memory-History Synthesis** — 纵向综合：历史强化 / 历史修正 / 未解决问题
3. **Current Best Answer** — 当前阶段最优回答（允许保留不确定性）
4. **Counter-Question** — 1 个高质量反问，作为下一轮输入驱动

> 关键：最终价值在于**历史记忆的纵向综合**，而非任何单轮的孤立答案。

### 运行机制（你不用手动调，了解即可）

- **搜索频控**：`web_search` 每小时硬上限 5 次，由 `scripts/search_limiter.py` 计数强制；提倡「少搜多想」。
- **分层记忆**：`scripts/memory.py` 维护 working → episodic → semantic 三层，跨会话持久化在 `.meditation/<session>/` 下，并递归自动压缩。
- **批判性 Observer**：每轮新建一个 Haiku 子智能体审视推理过程，把 `INSIGHT / CRITIQUE / NEXT` 反馈进下一轮。

### 查看 / 管理记忆（可选，命令行）

```bash
S=.claude/skills/meditate/scripts

# 看某条思考线的记忆状态（各层条数等）
python3 $S/memory.py status  --session default

# 读出当前可召回的记忆轨迹
python3 $S/memory.py recall  --session default

# 看本小时搜索配额还剩几次
python3 $S/search_limiter.py remaining
```

数据目录 `.meditation/` 已在 `.gitignore` 中忽略，不会被提交。

## 项目目标

1. **构建可持续多轮思考循环**
   - 每轮都有输入、联想、总结、反问。
   - 让系统能在没有明确终点的探索中，持续产出有价值中间结论。

2. **控制外部搜索依赖**
   - 提倡“少搜多想”，防止模型被信息噪声牵引。
   - 工具 `web_search` 必须按需调用，不可滥用。

3. **引入稳健记忆机制**
   - 完整参考 `nanobot` 的记忆机制设计。
   - 包含 token 压缩与分层记忆，保证长程对话可持续。

4. **把反问变成下一轮驱动器**
   - 输出问题不是装饰，而是下一轮输入源。
   - 让探索路径可自我推进。

## 当前文档结构

```text
meditation/
├─ README.md                       # 项目目标 + 使用说明
├─ docs/                           # 设计文档
│  ├─ ARCHITECTURE.md              # 系统架构与模块关系
│  ├─ LOOP.md                      # 单轮/多轮循环流程定义
│  ├─ TOOLS.md                     # 工具约束（尤其 web_search 频控）
│  ├─ MEMORY.md                    # 记忆机制（参考 nanobot + token 压缩）
│  └─ PROMPT_SPEC.md               # 面向模型的提示词/行为规范草案
└─ .claude/skills/meditate/        # 已落地的 skill 实现
   ├─ SKILL.md                     # /meditate 编排（主流程）
   ├─ prompt/system.md             # 推理层 system prompt
   ├─ prompt/observer.md           # 批判性 Observer brief
   └─ scripts/
      ├─ memory.py                 # 分层记忆引擎
      └─ search_limiter.py         # 全局搜索频控
```

## 快速导航

- 架构说明：`docs/ARCHITECTURE.md`
- 循环流程：`docs/LOOP.md`
- 工具规则：`docs/TOOLS.md`
- 记忆机制：`docs/MEMORY.md`
- Prompt 草案：`docs/PROMPT_SPEC.md`

