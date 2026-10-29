"""备忘 Agent：定义 + 模型配置 + AG-UI 端点挂载。

使用 Microsoft Agent Framework 定义 Agent，通过官方 AG-UI 集成在 FastAPI 暴露
受登录保护的接口。模型密钥只从服务端环境变量读取，绝不进代码 / 前端。
"""

from __future__ import annotations

import logging
import os

from agent_framework import Agent
from agent_framework.ag_ui import add_agent_framework_fastapi_endpoint
from agent_framework.ollama import OllamaChatClient
from agent_framework.openai import OpenAIChatCompletionClient

from .auth_scope import resolve_authorization_scope
from .tools import TOOLS

logger = logging.getLogger(__name__)

AGENT_NAME = "MemoAssistant"
AGENT_DESCRIPTION = "备忘录助手：只读查询当前登录用户自己的备忘录。"
AGENT_INSTRUCTIONS = """你是「备忘录助手」，帮助用户查询他自己的备忘录。

能力范围（只能使用提供的只读工具）：
- list_my_memos：列出当前用户自己的全部备忘录
- search_my_memos：按关键词搜索当前用户的备忘录
- memo_stats：统计当前用户备忘录数量

安全约束（必须严格遵守）：
1. 只能查询当前已登录用户自己的数据，绝不能访问或推断其他用户的数据。
2. 工具签名不接受任何用户 ID，你也不要试图传入用户 ID；身份由后端自动限定。
3. 只能读取，不能新增、修改或删除备忘录。
4. 只用工具返回的真实数据回答，绝不编造、猜测或补全不存在的备忘内容。
5. 工具返回数据后再作答；若工具返回「拒绝访问」等错误，如实转告用户。
6. 用简体中文、简洁地回答。"""


def build_model_client():
    """按服务端环境变量选择模型 client（密钥只保留在服务端）。

    优先级：Ollama（本地免费）> OpenAI > Azure OpenAI；都未配置时回退到本地 Ollama。
    """
    ollama_model = os.getenv("OLLAMA_MODEL")
    if ollama_model:
        logger.info("使用 Ollama 本地模型：%s", ollama_model)
        return OllamaChatClient(model=ollama_model)

    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
        logger.info("使用 OpenAI 模型：%s", model)
        return OpenAIChatCompletionClient(model=model, api_key=openai_key)

    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_model = os.getenv("AZURE_OPENAI_MODEL")
    if azure_endpoint and azure_model:
        logger.info("使用 Azure OpenAI 模型：%s", azure_model)
        return OpenAIChatCompletionClient(
            azure_endpoint=azure_endpoint, model=azure_model
        )

    # 未配置：回退到本地 Ollama（常见免费开发方案），应用仍可启动。
    fallback = os.getenv("OLLAMA_MODEL", "llama3.2")
    logger.warning(
        "未检测到任何模型配置，回退到本地 Ollama（%s @ 默认 localhost:11434）。"
        "请设置 OPENAI_API_KEY 或 OLLAMA_MODEL 环境变量。",
        fallback,
    )
    return OllamaChatClient(model=fallback)


def build_agent() -> Agent:
    """构建备忘 Agent。"""
    return Agent(
        client=build_model_client(),
        name=AGENT_NAME,
        description=AGENT_DESCRIPTION,
        instructions=AGENT_INSTRUCTIONS,
        tools=TOOLS,
    )


def register_agent_endpoint(app) -> None:
    """在 FastAPI 应用上挂载受登录保护的 AG-UI 端点。

    端点路径 /agent（前端经 Vite 代理 /api/agent 访问）。
    authorization_scope_resolver 负责校验 JWT 并按用户隔离会话状态。
    """
    agent = build_agent()
    add_agent_framework_fastapi_endpoint(
        app,
        agent,
        "/agent",
        authorization_scope_resolver=resolve_authorization_scope,
    )
