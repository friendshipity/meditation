# meditation

`meditation` 是一个“低频外部输入 + 高频内在反思”的循环式智能体项目。

## 你现在可以直接运行

```bash
python meditation.py --topic "AI 如何提升长期推理能力？" --rounds 3 --auto
```

- `--rounds`：运行轮数。
- `--auto`：自动把本轮 `Counter-Question` 喂给下一轮。
- `--memory-file`：记忆持久化路径（默认 `.meditation/memory.json`）。

## 核心思想

- 用户输入一个话题或问题。
- 模型在必要时进行外部搜索（受限使用）。
- 模型围绕话题做开放式联想与反思（`think` 没有刚性目标，只要相关即可）。
- 模型每轮固定输出：
  1) `Meditation Summary`
  2) `Memory-History Synthesis`
  3) `Current Best Answer`
  4) `Counter-Question`
- 循环往复，在“内审 + 记忆”的过程中逐步获得更高质量理解。

> meditation 的含义：接受少量外部信息，不断反思、回答，并在内审中累积更高智能。

## 当前原型能力（Runnable Prototype）

- ✅ 可运行 CLI 循环代理。
- ✅ `web_search` 每小时最多 5 次的频控。
- ✅ nanobot-style 分层记忆：working / episodic / semantic。
- ✅ token 压缩：工作记忆超限时自动压缩进 episodic。
- ✅ 输出中强制包含 memory history 综合段。

## 项目目标

1. **构建可持续多轮思考循环**
2. **控制外部搜索依赖（少搜多想）**
3. **引入稳健记忆机制（参考 nanobot）**
4. **输出必须是历史综合，而非单轮快照**
5. **让反问成为下一轮驱动器**

## 文件结构

```text
meditation/
├─ meditation.py              # 可运行原型（CLI）
├─ README.md
└─ docs/
   ├─ ARCHITECTURE.md
   ├─ LOOP.md
   ├─ TOOLS.md
   ├─ MEMORY.md
   └─ PROMPT_SPEC.md
```

## 文档导航

- 架构说明：`docs/ARCHITECTURE.md`
- 循环流程：`docs/LOOP.md`
- 工具规则：`docs/TOOLS.md`
- 记忆机制：`docs/MEMORY.md`
- System Prompt 草案：`docs/PROMPT_SPEC.md`

