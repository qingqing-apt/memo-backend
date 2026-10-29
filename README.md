# Memo Platform · 后端 API

备忘录平台的后端服务，基于 **FastAPI + SQLite + JWT**。

## 功能

- 用户注册 / 登录（账号密码 + JWT 鉴权）
- 备忘录增删改查（CRUD）
- 可见性控制：**公开备忘**无需登录即可查看，**私有备忘**仅作者本人登录后可见

## 技术栈

- Python 3.10+ / FastAPI / SQLAlchemy 2.0
- SQLite（零配置，单文件）
- PyJWT（HS256 令牌）

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

## 前端联调

前端项目 `memo-frontend`（React + Vite）默认通过 Vite 代理把 `/api` 转发到 `http://127.0.0.1:8000`，也可直接配置 CORS 直连。
