import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agent.memo_agent import register_agent_endpoint
from .database import Base, engine
from .routers import auth, memos

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 启动时自动建表（demo 用途；生产建议用 Alembic 迁移）
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Memo Platform API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(memos.router)

# 挂载受登录保护的 Agent AG-UI 端点（/agent）
try:
    register_agent_endpoint(app)
    logger.info("Agent 端点已挂载：/agent")
except Exception as exc:  # 模型 client 初始化失败时不阻断整个应用启动
    logger.error("Agent 端点挂载失败（模型未配置或初始化异常）：%s", exc)


@app.get("/")
def root():
    return {"message": "Memo Platform API is running", "docs": "/docs"}
