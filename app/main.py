from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routers import auth, memos

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


@app.get("/")
def root():
    return {"message": "Memo Platform API is running", "docs": "/docs"}
