"""Agent 接口的登录校验与用户身份隔离。

核心安全原则：
- Agent 接口必须登录后才能访问，未登录在运行模型之前就被拒绝。
- 工具读取用户数据时，只能使用后端从已验证的 JWT 解析出的 user_id，
  绝不信任浏览器或模型传入的 user_id。
"""

from __future__ import annotations

import contextvars

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..security import decode_token

# 当前请求的已验证用户 id（工具通过它取数据）
_current_user_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "agent_current_user_id", default=None
)

_bearer = HTTPBearer(auto_error=False)


def get_current_user_id() -> int | None:
    """返回当前请求已验证的用户 id（供 Agent 工具使用）。"""
    return _current_user_id.get()


async def resolve_authorization_scope(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> str:
    """AG-UI 入口的授权解析器：校验 JWT 并返回按用户隔离的 scope。

    该函数是 FastAPI 依赖，由 Agent Framework 的 AG-UI 端点调用。
    返回的 scope 是服务端命名空间，用于隔离不同用户的会话/thread 状态。
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = decode_token(credentials.credentials)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        )
    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    # 把已验证的 user_id 注入上下文，供只读工具使用（不是来自模型/浏览器）。
    _current_user_id.set(user.id)

    # scope 是服务端命名空间，不是凭证，不能从客户端输入读取。
    return f"user:{user.id}"
