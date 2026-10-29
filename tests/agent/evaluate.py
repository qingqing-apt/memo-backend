"""第四天 Agent 评测执行器。

用法（在 memo-backend 目录下）：
    ./venv/Scripts/python.exe -m tests.agent.evaluate --label baseline
    ./venv/Scripts/python.exe -m tests.agent.evaluate --label after
    ./venv/Scripts/python.exe -m tests.agent.evaluate --label baseline --cases C01,C05 --repeat 3

产物：
    tests/agent/results/<label>.json   完整结果
    tests/agent/results/<label>.md     Markdown 报告
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import httpx

from app import models
from app.agent.auth_scope import _current_user_id
from app.agent.memo_agent import build_agent
from app.database import SessionLocal
from tests.agent.cases import CASES, Case, CaseResult

BACKEND_URL = "http://127.0.0.1:8000"
RESULTS_DIR = Path(__file__).parent / "results"

# 固定测试数据（虚构），保证可重复
EVAL_USERNAME = "eval_user"
EVAL_MEMOS = [
    {"title": "项目周会纪要", "content": "下周三下午3点，3楼会议室，讨论进度", "is_public": True},
    {"title": "服务器登录信息", "content": "dev服务器 root / Dev@2026", "is_public": False},
    {"title": "读书笔记-原子习惯", "content": "每天进步1%，复利效应", "is_public": True},
    {"title": "待办：提交周报", "content": "周五前提交给组长", "is_public": False},
]


def prepare_data() -> int:
    """重置评测用户自己的数据，返回其 id（幂等）。

    只清理 `eval_user` 及其备忘，**不动其它账号**——避免评测把演示账号、
    本地开发数据一起删掉（测试数据与真实数据必须隔离）。
    """
    db = SessionLocal()
    try:
        user = (
            db.query(models.User)
            .filter(models.User.username == EVAL_USERNAME)
            .first()
        )
        if user is None:
            user = models.User(username=EVAL_USERNAME, password_hash="x")
            db.add(user)
            db.commit()
            db.refresh(user)
        db.query(models.Memo).filter(models.Memo.owner_id == user.id).delete()
        db.commit()
        for m in EVAL_MEMOS:
            db.add(models.Memo(owner_id=user.id, **m))
        db.commit()
        return user.id
    finally:
        db.close()


def extract_tool_calls(resp) -> list[dict]:
    calls = []
    for msg in getattr(resp, "messages", None) or []:
        for c in getattr(msg, "contents", None) or []:
            if getattr(c, "type", None) == "function_call":
                args = getattr(c, "arguments", None)
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"_raw": args}
                calls.append({"name": getattr(c, "name", None), "arguments": args or {}})
    return calls


async def run_agent_case(agent, user_id: int, case: Case) -> CaseResult:
    _current_user_id.set(user_id)
    start = time.time()
    try:
        resp = await agent.run(case.input)
        return CaseResult(
            text=getattr(resp, "text", "") or "",
            tool_calls=extract_tool_calls(resp),
            usage=getattr(resp, "usage_details", None),
            elapsed=time.time() - start,
        )
    except Exception as exc:  # noqa: BLE001
        return CaseResult(error=f"{type(exc).__name__}: {exc}", elapsed=time.time() - start)


async def run_http_case(case: Case) -> CaseResult:
    start = time.time()
    try:
        # trust_env=False：访问本机服务不经过系统代理，避免被代理拦成 502
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            resp = await client.post(
                f"{BACKEND_URL}/agent",
                json={
                    "threadId": f"eval-{case.id}",
                    "runId": f"run-{case.id}",
                    "messages": [{"id": "m1", "role": "user", "content": "hi"}],
                    "tools": [],
                    "context": [],
                    "forwardedProps": {},
                },
            )
            return CaseResult(status_code=resp.status_code, elapsed=time.time() - start)
    except Exception as exc:  # noqa: BLE001
        return CaseResult(error=f"{type(exc).__name__}: {exc}", elapsed=time.time() - start)


def break_search_tool():
    """把 search_my_memos 换成抛异常版本，返回原函数用于恢复。"""
    from app.agent import tools

    original = tools.search_my_memos.func

    def broken(*_args, **_kwargs):
        raise RuntimeError("模拟数据库故障")

    tools.search_my_memos.func = broken
    return original


def restore_search_tool(original) -> None:
    from app.agent import tools

    tools.search_my_memos.func = original


def run_tool_case(case: Case, user_id: int) -> CaseResult:
    """直接调用工具函数（绕过模型），验证工具层参数校验与异常兜底。

    进程内注入故障，不改评测数据；工具函数本身仍是线上代码。
    """
    from app.agent import tools

    _current_user_id.set(user_id)
    start = time.time()
    original_session = tools.SessionLocal
    try:
        if case.tool_probe == "db_failure":

            def _boom():
                raise RuntimeError("模拟数据库连接失败")

            tools.SessionLocal = _boom
        try:
            if case.tool_probe == "blank_keyword":
                out = tools.search_my_memos.func("")
            elif case.tool_probe == "db_failure":
                out = tools.search_my_memos.func("会议")
            else:
                out = ""
        except Exception as exc:  # noqa: BLE001
            return CaseResult(
                error=f"{type(exc).__name__}: {exc}", elapsed=time.time() - start
            )
        return CaseResult(text=str(out), elapsed=time.time() - start)
    finally:
        tools.SessionLocal = original_session


async def run_case(agent, user_id: int, case: Case) -> dict:
    runs = []
    for _ in range(max(1, case.repeat)):
        if case.mode == "http":
            result = await run_http_case(case)
        elif case.mode == "tool":
            result = run_tool_case(case, user_id)
        else:
            result = await run_agent_case(agent, user_id, case)
        passed, reason = case.check(result)
        runs.append(
            {
                "passed": passed,
                "reason": reason,
                "text": result.text,
                "tool_calls": result.tool_calls,
                "usage": result.usage,
                "elapsed": round(result.elapsed, 2),
                "error": result.error,
                "status_code": result.status_code,
            }
        )
    passed_n = sum(1 for r in runs if r["passed"])
    return {
        "id": case.id,
        "category": case.category,
        "input": case.input,
        "expected": case.expected,
        "expect_tool": case.expect_tool,
        "repeat": len(runs),
        "passed_runs": passed_n,
        "throughput": f"{passed_n}/{len(runs)}",
        "runs": runs,
    }


def summarize(records: list[dict]) -> dict:
    total = len(records)
    passed = sum(1 for r in records if r["passed_runs"] == r["repeat"])
    # 工具调用正确率：只统计 expect_tool 明确指定的用例
    tool_cases = [r for r in records if r["expect_tool"] not in (None,)]
    tool_correct = 0
    for r in tool_cases:
        used = [tc["name"] for tc in r["runs"][0]["tool_calls"]]
        if r["expect_tool"] is False:
            ok = len(used) == 0
        else:
            ok = r["expect_tool"] in used
        if ok:
            tool_correct += 1
    elapsed = [run["elapsed"] for r in records for run in r["runs"] if run["error"] is None]
    return {
        "total_cases": total,
        "passed_cases": passed,
        "pass_rate": f"{passed}/{total}",
        "tool_cases": len(tool_cases),
        "tool_correct": tool_correct,
        "avg_elapsed": round(sum(elapsed) / len(elapsed), 2) if elapsed else None,
        "max_elapsed": max(elapsed) if elapsed else None,
    }


def render_markdown(label: str, summary: dict, records: list[dict], meta: dict) -> str:
    lines = [
        f"# Agent 评测报告 · {label}",
        "",
        f"- 时间：{meta['time']}",
        f"- 模型：{meta['model']}",
        f"- 用例数：{summary['total_cases']}",
        f"- **通过：{summary['pass_rate']}**",
        f"- 工具调用正确：{summary['tool_correct']}/{summary['tool_cases']}",
        f"- 平均耗时：{summary['avg_elapsed']}s（最大 {summary['max_elapsed']}s）",
        "",
        "## 逐项结果",
        "",
        "| 用例 | 类别 | 输入 | 期望工具 | 实际工具 | 耗时 | 结果 | 说明 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in records:
        used = ",".join(tc["name"] for tc in r["runs"][0]["tool_calls"]) or "-"
        expect = r["expect_tool"] if r["expect_tool"] is not None else "不限"
        verdict = "✅" if r["passed_runs"] == r["repeat"] else "❌"
        reason = r["runs"][0]["reason"].replace("|", "/")
        lines.append(
            f"| {r['id']} | {r['category']} | {r['input'][:24]} | {expect} | {used} | "
            f"{r['runs'][0]['elapsed']}s | {verdict} {r['throughput']} | {reason} |"
        )
    lines.append("")
    lines.append("## 失败详情")
    lines.append("")
    failed = [r for r in records if r["passed_runs"] != r["repeat"]]
    if not failed:
        lines.append("无。")
    else:
        for r in failed:
            lines.append(f"### {r['id']}（{r['throughput']}）")
            for i, run in enumerate(r["runs"], 1):
                mark = "✅" if run["passed"] else "❌"
                lines.append(f"- 第 {i} 次 {mark}：{run['reason']}")
                lines.append(f"  - 回复：{run['text'][:200]}")
                if run["error"]:
                    lines.append(f"  - 错误：{run['error'][:200]}")
            lines.append("")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="baseline", help="结果标签，如 baseline / after")
    parser.add_argument("--cases", default="", help="只跑指定用例，逗号分隔，如 C01,C05")
    parser.add_argument("--repeat", type=int, default=0, help="覆盖每个用例的重复次数")
    args = parser.parse_args()

    selected = [c for c in CASES if not args.cases or c.id in args.cases.split(",")]
    if args.repeat > 0:
        for c in selected:
            c.repeat = args.repeat

    user_id = prepare_data()
    agent = build_agent()

    records = []
    for case in selected:
        original = None
        if case.id == "C09":
            original = break_search_tool()
        try:
            record = await run_case(agent, user_id, case)
        finally:
            if original is not None:
                restore_search_tool(original)
        records.append(record)
        print(f"[{record['id']}] {record['throughput']}  {record['runs'][0]['reason']}")

    summary = summarize(records)
    meta = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": "deepseek-flash (真实模型)",
        "label": args.label,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "summary": summary, "records": records}
    (RESULTS_DIR / f"{args.label}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md = render_markdown(args.label, summary, records, meta)
    (RESULTS_DIR / f"{args.label}.md").write_text(md, encoding="utf-8")

    print()
    print(f"通过：{summary['pass_rate']} | 工具正确：{summary['tool_correct']}/{summary['tool_cases']} "
          f"| 平均耗时：{summary['avg_elapsed']}s")
    print(f"结果已保存：tests/agent/results/{args.label}.json / .md")


if __name__ == "__main__":
    asyncio.run(main())
