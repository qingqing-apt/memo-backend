# Memo Platform · 后端 API

备忘录平台的后端服务，基于 **FastAPI + SQLite + JWT**。

## 功能

- 用户注册 / 登录（账号密码 + JWT 鉴权）
- 备忘录增删改查（CRUD）
- 可见性控制：**公开备忘**无需登录即可查看，**私有备忘**仅作者本人登录后可见
- **备忘 Agent**（第三天新增）：登录后可对话，Agent 通过只读工具查询你自己的备忘录

## 技术栈

- Python 3.10+ / FastAPI / SQLAlchemy 2.0
- SQLite（零配置，单文件）
- PyJWT（HS256 令牌）
- Microsoft Agent Framework + AG-UI（备忘 Agent）

## 快速开始

```bash
# 1. 创建虚拟环境
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动服务（首次启动自动创建 memo.db 表）
python run.py
# 或
uvicorn app.main:app --reload --port 8000
```

服务默认运行在 `http://127.0.0.1:8000`，交互式 API 文档：`http://127.0.0.1:8000/docs`。

## 容器启动（Docker）

```bash
# 1. 创建共享网络（与前端仓库共用，只需一次）
docker network create memo-network

# 2. 在本仓库目录启动
docker compose up -d --build
```

- 服务运行在 `http://localhost:8000`
- SQLite 数据持久化在 volume `memo-data`
- 模型密钥通过宿主机 `.env` 或环境变量注入（`DEEPSEEK_API_KEY`），不写入镜像

> ⚠️ 本机当前未安装 Docker，容器配置**尚未实际验证**，安装 Docker 后按上述步骤即可复现。

## 接口一览

| 方法 | 路径 | 说明 | 是否需要登录 |
| ---- | ---- | ---- | ---- |
| POST | `/auth/register` | 注册并返回 token | 否 |
| POST | `/auth/login` | 登录并返回 token | 否 |
| GET | `/auth/me` | 当前用户信息 | 是 |
| GET | `/memos` | 备忘录列表（公开 + 本人私有） | 可选 |
| POST | `/memos` | 新建备忘录 | 是 |
| GET | `/memos/{id}` | 单条详情（受可见性约束） | 可选 |
| PUT | `/memos/{id}` | 修改（仅作者） | 是 |
| DELETE | `/memos/{id}` | 删除（仅作者） | 是 |

> 说明：`/memos` 未登录时只返回 `is_public=true` 的备忘；登录后额外返回本人的私有备忘。

## 环境变量

复制 `.env.example` 为 `.env` 后按需修改：

- `SECRET_KEY`：JWT 签名密钥（生产必须更换）
- `ACCESS_TOKEN_EXPIRE_MINUTES`：令牌有效期，默认 60 分钟
- `DATABASE_URL`：数据库地址，默认 `sqlite:///./memo.db`
- Agent 模型配置（多选一，密钥只保留在服务端，绝不进代码/前端）：
  - `DEEPSEEK_API_KEY` + `DEEPSEEK_MODEL`（默认 `deepseek-flash`）：DeepSeek（OpenAI 兼容，推荐）
  - `OLLAMA_MODEL`：本地 Ollama（免费，需本地运行 ollama）
  - `OPENAI_API_KEY` + `OPENAI_CHAT_MODEL`：OpenAI
  - `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_MODEL`：Azure OpenAI

> 都未配置时会回退到本地 Ollama（`llama3.2` @ `localhost:11434`），并打印警告。

## 备忘 Agent（第三天）

基于 **Microsoft Agent Framework** 定义 Agent，通过官方 **AG-UI** 集成在 FastAPI 暴露接口。

- **端点**：`POST /agent`（前端经 Vite 代理 `/api/agent` 访问）
- **登录保护**：请求必须携带 `Authorization: Bearer <token>`；未登录 / 无效 token 在运行模型前即返回 `401`
- **只读工具**（后端真实执行）：
  - `list_my_memos`：列出当前用户全部备忘（单条内容截断 200 字、最多 20 条）
  - `search_my_memos`：按关键词搜索当前用户备忘（**keyword 必填，空关键词被工具层直接拒绝**，不会退化成返回全部）
  - `memo_stats`：统计数量（总数 / 公开 / 私有）
- **安全边界**：
  - 工具只读取**后端从 JWT 解析出的已验证 user_id**（通过 ContextVar 注入），工具签名不暴露 user_id，模型与浏览器都无法指定用户
  - 仅只读，无新增 / 修改 / 删除工具
  - 会话状态按用户隔离（`authorization_scope_resolver` 返回 `user:<id>` 作为 scope）
- **会话行为**：
  - 对话上下文由 AG-UI 的 `threadId` 关联，同一 `threadId` 的多轮对话在进程内有效
  - 历史保存在**内存快照**（`InMemoryAGUIThreadSnapshotStore`），**服务重启后清空**；今天不要求数据库持久化

### 实际安装版本

- `agent-framework==1.23.0`
- `agent-framework-ag-ui==1.7.0`
- `agent-framework-openai==1.17.0`
- `agent-framework-ollama==1.0.0b261022`（预发布，随 `agent-framework-core[all]` 自动带入）

### 已知问题 / 未完成项

- **容器未实测**：`Dockerfile` / `docker-compose.yml` 已写好，但开发机未安装 Docker，未做容器内复现
- **会话不持久化**：历史在内存中，服务重启后清空
- **评测判定非语义**：`tests/agent/` 的检查依赖关键词匹配，遇到表达变体可能误判

## Agent 评测与优化（第四天）

- **评测用例**：`tests/agent/`，12 个用例（正常 / 需要工具 / 不需要工具 / 模糊 / 超范围 / 异常 / 安全 / 工具层），运行方式见 `tests/agent/README.md`
- **优化记录**：`docs/day-4-agent-optimization.md`（基线、问题分析、改动、前后对比、限制、复现步骤、复盘）
- **本轮改动**：
  - `app/agent/memo_agent.py`：新增 3 条交互规则（含糊请求先追问、写操作直接说明只读、工具报错不重复调用）
  - `app/agent/tools.py`：关键词非空 + 长度校验、数据库异常统一兜底（错误码 `DB_UNAVAILABLE`，不泄露堆栈）、输出条数与长度上限
- **结果**：同一套 12 个用例，通过 **10/12 → 12/12**，工具调用正确 **4/5 → 5/5**；登录保护、用户隔离、只读工具权限未削弱
- **复现**：
  ```bash
  ./venv/Scripts/python.exe -m uvicorn app.main:app --port 8000   # C10 安全用例需要
  ./venv/Scripts/python.exe -m tests.agent.evaluate --label after
  ```

## 前端联调

前端项目 `memo-frontend`（React + Vite）默认通过 Vite 代理把 `/api` 转发到 `http://127.0.0.1:8000`，也可直接配置 CORS 直连。
