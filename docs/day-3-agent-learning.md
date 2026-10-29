# 第三天学习：Agent 交互原理与我的实现

> 本文是我在完成「备忘录 Agent」过程中，对 Microsoft Agent Framework、CopilotKit、AG-UI 三者职责与交互链路的理解。所有结论都对照了我仓库里的实际代码（`memo-backend` / `memo-frontend` 的 `feat/agent-chat` 分支），不是照抄官网。

## 1. Microsoft Agent Framework 解决什么问题？

它解决的是「把一个大模型变成一个能干活、能调工具、能管会话的 Agent」这件事。

单靠一个 LLM，你只能拿到一段文本。但一个有用的 Agent 需要：

- **角色与指令**：告诉模型「你是谁、只能做什么」。我的实现里 `Agent(name="MemoAssistant", instructions=...)` 就定义了这个边界。
- **工具**：模型光会说话不行，还要能查真实数据。我的 Agent 挂了 3 个只读工具 `list_my_memos` / `search_my_memos` / `memo_stats`。
- **模型**：真正做推理的那一层，我这里用的是 DeepSeek（`deepseek-flash`），通过 `OpenAIChatCompletionClient` 接入。
- **会话状态**：多轮对话的历史由框架管理，模型每次都能拿到「历史 + 新消息」。

三者的关系可以概括为：**模型是大脑，工具是手脚，Agent 是那个同时管着大脑和手脚、并规定「什么能做、什么不能做」的协调者。** Agent Framework 的价值在于把这些零件用统一的抽象组织起来，并额外提供中间件、会话、流式输出等企业级能力，而不是我自己手搓一套工具调用循环。

## 2. CopilotKit 在 React 应用中做什么？

它是**前端那一层**，把「一个跑在后端的 Agent」变成「网页里能用的聊天界面」。

如果自己手写一个聊天输入框，我要处理的远不止「发文字、收文字」：

- **流式渲染**：回复是一段一段 delta 过来的，要边收边显示，而不是等整段好了再一次性 `setState`。
- **状态管理**：`RUN_STARTED`、文本增量、`RUN_FINISHED`、报错、中断，每种状态都要有对应 UI。
- **工具调用的可视反馈**：模型在查数据时，前端最好能显示「正在查询…」。
- **认证**：怎么把登录 token 一路带到后端 Agent。
- **会话/线程**：怎么让「新对话」「继续上一段」正常工作。

CopilotKit 用 `<CopilotKit>` Provider + `<CopilotPopup>` 这类预置组件把这些都封装好了。我的前端只写了十来行：Provider 上配 `runtimeUrl`、`agent`、`headers`，里面放一个 `CopilotPopup`，流式、状态、输入框全都自带。**区别就在于：手写是「我自己实现 AG-UI 客户端」，CopilotKit 是「一个现成的、能正确消费 AG-UI 事件流的 React SDK」。**

## 3. AG-UI 是什么？和 JSON 接口、HTTP、SSE 是什么关系？

先说最关键的一点：**AG-UI 是「事件协议」，不是「传输方式」**。

- 它定义的是「一次 Agent 运行中会发生哪些事件」以及每个事件的形状，比如 `RUN_STARTED`、`TEXT_MESSAGE_CONTENT`（带 `delta` 文本增量）、`TOOL_CALL_START`、`RUN_FINISHED`。
- 它**不规定**用 HTTP 还是 WebSocket 还是别的来传这些事件。

几个概念的层级关系：

| 概念 | 层级 | 例子 |
| ---- | ---- | ---- |
| HTTP | 传输层（应用协议） | 一次请求/响应 |
| SSE | 传输方式（基于 HTTP 的流式） | 一条连接持续推送增量 |
| JSON | 数据格式 | 每个事件的载荷是 JSON |
| AG-UI | 事件协议（语义层） | 「文本增量」这个事件长什么样 |

所以正确说法是：**AG-UI 事件流通过 HTTP 承载，用 SSE 作为流式传输方式，每个事件是 JSON 编码**。常见误区是把「SSE」说成「WebSocket」——它们完全不是一回事：SSE 是单向（服务器 → 客户端）、基于 HTTP 的长连接；WebSocket 是双向、需要协议升级的独立连接。我的实现里，Python 后端的 `/agent` 端点就是用 SSE 持续吐 AG-UI 事件，前端（经 Runtime）消费这些事件。

## 4. 从点击发送到显示回复，消息经过哪些组件？

以我的实现为例，一条消息走完整条链路：

1. **浏览器（React + CopilotKit）**：用户输入 → `CopilotPopup` 把消息组装成 AG-UI 的 `RunAgentInput`（含 `threadId`、`messages`、`runId`），随请求带上 `Authorization: Bearer <JWT>`，发往 Runtime。
2. **CopilotKit Runtime（Node Express）**：收到请求，`identifyUser` 从 JWT 解析出用户名做线程隔离；再把请求转发给注册的 `HttpAgent`，同时把 `authorization` header 一并转发（这是它默认行为，我利用它来传登录态）。
3. **Python `/agent`（FastAPI + Agent Framework AG-UI 适配）**：`authorization_scope_resolver` 校验 JWT，解析出 user_id 写入 ContextVar，并返回 `user:<id>` 作为 scope（隔离不同用户的会话状态）。
4. **Agent（MemoAssistant）**：框架把消息交给 DeepSeek；模型决定「要不要调工具」。
5. **只读工具**：若模型要查数据，工具函数从 ContextVar 取 user_id，只查这个用户自己的备忘录，返回结果给模型。
6. **模型再作答**：模型基于工具结果生成最终文本。
7. **事件回流**：每一步都变成 AG-UI 事件，经 SSE 流回 Runtime → 浏览器，前端逐步渲染文本、工具状态、结束标记。

每个组件「收到什么、返回什么」在图上（`docs/diagrams/day-3-agent-interaction.png`）有完整标注。

## 5. CopilotKit Runtime 部署在哪、做什么？为什么 Vite 不能直接当 Runtime？

**Runtime 是一个独立的 Node 服务**，我的实现里它在 `memo-frontend/runtime/server.ts`，跑在 `localhost:3000`。它做三件事：

- **注册 Agent**：`new HttpAgent({ url: "http://127.0.0.1:8000/agent" })`，告诉它「后端 Agent 在哪」。
- **转发 + 认证中介**：把前端请求转发给 Agent，并透传 `authorization` header。
- **线程管理**：`identifyUser` 按用户隔离线程列表。

**Vite 开发服务器不能当 Runtime**，因为 Vite 只是个「前端打包 + 静态资源 + 开发热更新」的服务器，它不懂 AG-UI 协议，没有「注册 Agent、转发事件流、管线程」这套逻辑。Vite 的 `proxy` 只能做「原样转发 HTTP 请求」这种粗活，替代不了 Runtime 的语义层。所以架构里必须有 Runtime 这一层（任务文档也明确要求：前端仓库加一个轻量 Node 服务）。

## 6. 流式回复如何逐步显示？

靠的是 AG-UI 的事件序列，前端「认事件不认整段文本」：

- **开始**：收到 `RUN_STARTED`，前端进入「正在回复」状态。
- **增量**：连续收到多个 `TEXT_MESSAGE_CONTENT` 事件，每个带一小段 `delta`，前端把 delta **追加**到当前消息末尾，于是文字「一个字一个字」出来。
- **结束**：收到 `RUN_FINISHED`，前端结束加载态。
- **失败**：收到 `RUN_ERROR`（或连接中断），前端展示错误并结束等待。

关键在于「流式」不是前端做了个假打字动画，而是**真实收到一条条增量事件后逐步更新 UI**。这也解释了为什么 nginx 里必须 `proxy_buffering off`：一旦反向代理把 SSE 缓冲起来，前端就会「等整段结束才一次性显示」，流式效果就没了。

## 7. 登录凭证和模型 API Key 分别由谁保存、发给谁？

两者是**完全不同**的东西，我特意分开处理：

- **登录凭证（JWT）**：保存在**浏览器**（localStorage）。前端把它放进请求的 `Authorization` header → Runtime 透传 → Python `/agent` 校验。它用来回答「你是谁、能看哪些数据」。
- **模型 API Key（DeepSeek）**：只保存在**后端服务端**（`memo-backend/.env` 的 `DEEPSEEK_API_KEY`），由后端在调模型时使用，**从不发给浏览器、不进前端、不进镜像**。

**为什么模型密钥不能进浏览器**：浏览器里的一切都能被用户（或 XSS）直接看到、抄走。密钥一旦进了前端 bundle 或环境变量，就等同于公开了，任何人都能用你的额度、甚至产生账单。而 JWT 放浏览器是正常的——它本身就是发给用户、让用户带着走的「门票」，后端靠它识别身份，真正敏感的数据（密钥、他人数据）都留在服务端。

## 8. 对话上下文来自哪里？thread/run 和登录会话有什么区别？

- **登录会话（JWT）**回答「你是谁」，由 `/auth/login` 签发，有效期 60 分钟，过期要重新登录。
- **Agent 对话的 `threadId`** 回答「这是哪一段对话」。AG-UI 里每次运行带一个 `threadId`，同一个 `threadId` 的历史消息会被后端 session 记住，实现多轮上下文。`runId` 则是「这一次运行」的标识（一个 thread 里可以有多次 run）。

两者不能混用：`threadId` 不是登录凭证。所以我的后端做了两层隔离：

- `authorization_scope_resolver` 返回 `user:<id>`，把**不同用户的 thread 状态隔开**——你拿别人的 `threadId` 也读不到别人的对话。
- 工具层再按 ContextVar 里的 user_id 过滤数据，**不信任浏览器或模型传入的任何用户标识**。

退出登录时，前端把 Agent 整个卸载（`user && <AgentChat/>`），本地 token 清除；换账号后重新登录，新的 JWT → 新的 scope，不会串到上一个账号的上下文。

---

## 附录 A：本次实际使用的版本

| 组件 | 版本 |
| ---- | ---- |
| agent-framework | 1.23.0 |
| agent-framework-ag-ui | 1.7.0 |
| agent-framework-openai | 1.17.0 |
| ag-ui-protocol | 0.1.22 |
| @copilotkit/react-core / runtime | 1.83.0 |
| @ag-ui/client | 1.0.3 |
| express | 5.3.0 |
| DeepSeek 模型 | deepseek-flash（DeepSeek-V4.1-Flash） |

## 附录 B：参考链接

- Microsoft Agent Framework Overview：https://learn.microsoft.com/en-us/agent-framework/overview/
- Python AG-UI README：https://github.com/microsoft/agent-framework/blob/main/python/packages/ag-ui/README.md
- CopilotKit 架构：https://docs.copilotkit.ai/concepts/architecture
- CopilotKit 认证：https://docs.copilotkit.ai/auth
- HttpAgent：https://docs.ag-ui.com/sdk/js/client/http-agent
- DeepSeek API 文档：https://api-docs.deepseek.com/

## 附录 C：阅读后仍不理解的 2~3 个问题

1. AG-UI 的 `STATE_SNAPSHOT` / `STATE_DELTA`（共享状态）与 thread 快照 `snapshot_store` 具体是什么关系？我只用到了 thread 层面的会话，state 机制还没吃透。
2. Agent Framework 的 `checkpoint_storage` 和 AG-UI 的 `snapshot_store` 各自负责哪一段持久化，边界在哪。
3. CopilotKit 的「Intelligence（云托管线程）」和我本地用的 `InMemoryAgentRunner` 在行为上有哪些隐性差异，尤其是并发场景。

## 附录 D：一个通过自己调试才弄懂的细节

**「工具怎么安全地拿到当前登录用户」这件事，我最初想当然地以为在工具函数里读个全局变量就行，结果发现没那么简单。**

我的工具是同步函数，而 Agent Framework 会把它丢到 `asyncio.to_thread` 里跑。于是我写了个小实验，分别测了 `asyncio.to_thread`、`loop.run_in_executor`、`asyncio.create_task` 三种方式下 `contextvars.ContextVar` 会不会传播——结果 `to_thread` 和 `create_task` 都能传播，唯独 `run_in_executor` 会丢失。

为了确认框架到底用哪种，我去读了 `agent_framework/_tools.py` 第 916 行的实现，看到同步工具确实是 `await asyncio.to_thread(...)`，这才放心用 ContextVar 方案：在 `authorization_scope_resolver`（登录校验时）把 user_id 写进 ContextVar，工具里读取。这个「读源码验证运行时行为」的过程，让我真正理解了 Python 的 contextvars 在不同异步执行方式下的传播差异，也让我确定了自己的方案不是「碰巧能跑」，而是有依据的。
