"""备忘 Agent 的只读工具。

安全约束：
- 只读：仅提供查询，不提供创建 / 更新 / 删除工具。
- 数据隔离：user_id 只从后端已验证的登录身份（ContextVar）读取，
  工具签名不暴露 user_id 参数，模型和浏览器都无法指定用户。
- 拿不到登录身份时直接拒绝（安全失败），绝不返回任何数据。
- 参数校验与异常兜底在工具层完成，不依赖模型自觉：
  * 关键词必须非空，空关键词不会退化成「返回全部内容」
  * 数据库异常统一转换为带错误码的用户可读提示，不向模型/前端泄露堆栈
- 输出有上限，避免一次把过多内容塞进上下文（控制 token 与延迟）。
"""

from __future__ import annotations

import json
import logging

from agent_framework import tool

from .. import models
from ..database import SessionLocal
from .auth_scope import get_current_user_id

logger = logging.getLogger(__name__)

# 输出上限：单条内容截断长度、单次返回条数上限
MAX_CONTENT_CHARS = 200
MAX_ITEMS = 20
MAX_KEYWORD_CHARS = 50

NO_IDENTITY_MSG = "拒绝访问：未获取到已登录用户身份。"
DB_ERROR_MSG = "查询失败：数据库暂时不可用（错误代码 DB_UNAVAILABLE），请稍后重试。"


def _serialize_memo(m: models.Memo) -> dict:
    content = m.content or ""
    if len(content) > MAX_CONTENT_CHARS:
        content = content[:MAX_CONTENT_CHARS] + "…（内容过长已截断）"
    return {
        "id": m.id,
        "title": m.title,
        "content": content,
        "is_public": m.is_public,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


def _safe_query(action: str, fn):
    """执行查询并在工具层兜底异常。

    只把错误码返回给模型，完整异常写服务端日志（不含用户数据），
    避免堆栈 / SQL 细节经模型回复泄露给前端。
    """
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "memo tool query failed: action=%s error=%s", action, type(exc).__name__
        )
        return DB_ERROR_MSG


def _list_memos(user_id: int) -> str:
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
        shown = items[:MAX_ITEMS]
        header = "当前用户的备忘录（共 %d 条" % len(items)
        if len(shown) < len(items):
            header += "，仅显示最近 %d 条" % len(shown)
        header += "）：\n"
        return header + json.dumps(shown, ensure_ascii=False, indent=2)
    finally:
        db.close()


def _search_memos(user_id: int, keyword: str) -> str:
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
        shown = items[:MAX_ITEMS]
        header = "命中「%s」的备忘录（共 %d 条" % (keyword, len(items))
        if len(shown) < len(items):
            header += "，仅显示最近 %d 条" % len(shown)
        header += "）：\n"
        return header + json.dumps(shown, ensure_ascii=False, indent=2)
    finally:
        db.close()


def _count_memos(user_id: int) -> str:
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


@tool(
    name="list_my_memos",
    description=(
        "列出当前登录用户自己的备忘录（标题、内容、是否公开、更新时间）。"
        "只读，不接收任何用户 ID 参数。用户只是打招呼或闲聊时不要调用。"
    ),
)
def list_my_memos() -> str:
    """列出当前登录用户的全部备忘录。"""
    user_id = get_current_user_id()
    if user_id is None:
        return NO_IDENTITY_MSG
    return _safe_query("list", lambda: _list_memos(user_id))


@tool(
    name="search_my_memos",
    description=(
        "在当前登录用户自己的备忘录中按关键词搜索（匹配标题和内容）。只读。"
        "keyword 必填，必须是用户明确说出的实体词（如「会议」「周报」）；"
        "用户没给出关键词时不要调用本工具，先追问。禁止用空字符串搜索。"
    ),
)
def search_my_memos(keyword: str) -> str:
    """按关键词搜索当前用户的备忘录。"""
    user_id = get_current_user_id()
    if user_id is None:
        return NO_IDENTITY_MSG

    kw = (keyword or "").strip()
    if not kw:
        return (
            "参数不合法：缺少搜索关键词。"
            "请提供至少 1 个字符的关键词（例如「会议」）；"
            "未指定关键词时我不会返回全部内容。"
        )
    if len(kw) > MAX_KEYWORD_CHARS:
        return (
            "参数不合法：关键词过长（%d 字符，上限 %d），请缩短后重试。"
            % (len(kw), MAX_KEYWORD_CHARS)
        )

    return _safe_query("search", lambda: _search_memos(user_id, kw))


@tool(
    name="memo_stats",
    description=(
        "统计当前登录用户自己的备忘录数量：总数、公开数、私有数。只读。"
        "用户问「几条」「多少」时优先用本工具，比列出全部内容更省。"
    ),
)
def memo_stats() -> str:
    """统计当前用户的备忘录数量。"""
    user_id = get_current_user_id()
    if user_id is None:
        return NO_IDENTITY_MSG
    return _safe_query("stats", lambda: _count_memos(user_id))


TOOLS = [list_my_memos, search_my_memos, memo_stats]
