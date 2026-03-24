# Architecture

## 1. 系统定位

`meditation` 是一个循环式思维代理（iterative reflective agent）：
- 接收用户主题/问题；
- 必要时获取少量外部信息；
- 进行无强终点的相关联想；
- 产出总结和下一轮反问；
- 借助记忆机制滚动演进。

## 2. 核心模块

1. **Input Router**
   - 接收用户输入。
   - 识别输入类型（事实型/观点型/决策型/开放探索型）。

2. **Search Gate**
   - 决定是否调用 `web_search`。
   - 执行频控策略：每小时最多 5 次。
   - 优先已有记忆和已有上下文，避免重复搜索。

3. **Associative Thinker**
   - 围绕主题进行相关联想（允许发散，但保持相关性）。
   - 对齐“meditation”理念：少量外部刺激 + 持续内部反思。

4. **Memory Engine (Nanobot-style)**
   - 按 `nanobot` 记忆机制进行短期/长期记忆管理。
   - 支持 token 压缩、摘要回写、重要性评分与检索。

5. **Synthesizer**
   - 将本轮思考压缩为结构化总结。
   - 生成可作为下一轮输入的反问。

## 3. 数据流（高层）

`User Input -> Search Gate -> Associative Thinker -> Memory Write -> Summary + Counter-question`

## 4. 设计原则

- **少搜多想**：搜索不是默认动作，是有成本的动作。
- **持续循环**：每轮结果都要能驱动下一轮。
- **记忆优先**：外部信息不足时先看记忆，再决定搜索。
- **可压缩扩展**：随着轮次增长，记忆不会线性膨胀。

