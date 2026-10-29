"""备忘 Agent 的只读工具。

安全约束：
- 只读：仅提供查询，不提供创建 / 更新 / 删除工具。
- 数据隔离：user_id 只从后端已验证的登录身份（ContextVar）读取，
  工具签名不暴露 user_id 参数，模型和浏览器都无法指定用户。
- 拿不到登录身份时直接拒绝（安全失败），绝不返回任何数据。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from agent_framework import tool

from .. import models
from ..database import SessionLocal
from .auth_scope import get_current_user_id


def _serialize_memo(m: models.Memo) -> dict:
    return {
        "id": m.id,
        "title": m.title,
        "content": m.content or "",
        "is_public": m.is_public,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


@tool(
    name="list_my_memos",
    description="列出当前登录用户自己的全部备忘录（标题、内容、是否公开、更新时间）。只读，不接收任何用户 ID 参数。",
)
def list_my_memos() -> str:
    """列出当前登录用户的全部备忘录。"""
    user_id = get_current_user_id()
    if user_id is None:
        return "拒绝访问：未获取到已登录用户身份。"

    db = SessionLocal()
    try:
        memos = (
            db.query(models.Memo)
            .filter(models.Memo.owner_id == user_id)
            .order_by(models.Memo.created_at.desc())
            .all()
        )
        if not memos:
            return "你还没有任何备忘录。"
        items = [_serialize_memo(m) for m in memos]
        return "当前用户的备忘录（共 %d 条）：\n%s" % (
            len(items),
            json.dumps(items, ensure_ascii=False, indent=2),
        )
    finally:
        db.close()


@tool(
    name="search_my_memos",
    description="在当前登录用户自己的备忘录中按关键词搜索（匹配标题和内容）。只读。",
)
def search_my_memos(keyword: str) -> str:
    """按关键词搜索当前用户的备忘录。"""
    user_id = get_current_user_id()
    if user_id is None:
        return "拒绝访问：未获取到已登录用户身份。"

    db = SessionLocal()
    try:
        pattern = f"%{keyword}%"
        memos = (
            db.query(models.Memo)
            .filter(models.Memo.owner_id == user_id)
            .filter(
                (models.Memo.title.like(pattern))
                | (models.Memo.content.like(pattern))
            )
            .order_by(models.Memo.created_at.desc())
            .all()
        )
        if not memos:
            return f"没有找到包含「{keyword}」的备忘录。"
        items = [_serialize_memo(m) for m in memos]
        return f"命中「{keyword}」的备忘录（共 %d 条）：\n%s" % (
            len(items),
            json.dumps(items, ensure_ascii=False, indent=2),
        )
    finally:
        db.close()


@tool(
    name="memo_stats",
    description="统计当前登录用户自己的备忘录数量：总数、公开数、私有数。只读。",
)
def memo_stats() -> str:
    """统计当前用户的备忘录数量。"""
    user_id = get_current_user_id()
    if user_id is None:
        return "拒绝访问：未获取到已登录用户身份。"

    db = SessionLocal()
    try:
        total = db.query(models.Memo).filter(models.Memo.owner_id == user_id).count()
        public = (
            db.query(models.Memo)
            .filter(models.Memo.owner_id == user_id, models.Memo.is_public.is_(True))
            .count()
        )
        private = total - public
        return json.dumps(
            {"total": total, "public": public, "private": private},
            ensure_ascii=False,
        )
    finally:
        db.close()


TOOLS = [list_my_memos, search_my_memos, memo_stats]
