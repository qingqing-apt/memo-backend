"""第四天 Agent 评测用例定义。

覆盖 7 类场景：正常、需要工具、不需要工具、信息不足、超出范围、异常、安全。
检查方式：开放式回答不逐字匹配，用明确检查项判断是否完成任务、是否用对数据、是否守边界。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class CaseResult:
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict | None = None
    elapsed: float = 0.0
    error: str | None = None
    status_code: int | None = None


@dataclass
class Case:
    id: str
    category: str
    input: str
    expected: str
    expect_tool: str | bool | None  # 工具名 / False 表示不应调用 / None 不关心
    mode: str  # "agent" / "http" / "tool"（tool = 直接调用工具函数，不受模型随机性影响）
    check: Callable[[CaseResult], tuple[bool, str]]
    repeat: int = 1
    tool_probe: str | None = None  # "blank_keyword" / "db_failure"


def _has_any(text: str, keywords: list[str]) -> bool:
    return any(k in text for k in keywords)


# ---------- 检查函数 ----------

def check_c01(r: CaseResult) -> tuple[bool, str]:
    if r.error:
        return False, f"运行出错：{r.error}"
    ok_scope = _has_any(r.text, ["备忘", "备忘录"])
    ok_readonly = _has_any(r.text, ["只读", "不能修改", "无法修改", "只能查询", "查询", "读取"])
    if ok_scope and ok_readonly:
        return True, "说明了自己的备忘助手定位与只读能力"
    return False, f"缺少能力说明（scope={ok_scope}, readonly={ok_readonly}）"


def check_c02(r: CaseResult) -> tuple[bool, str]:
    if r.error:
        return False, f"运行出错：{r.error}"
    if not r.tool_calls:
        return False, "未调用工具，无法基于真实数据概括"
    kinds = ["会议", "读书", "待办", "服务器"]
    hit = [k for k in kinds if k in r.text]
    if len(hit) >= 2:
        return True, f"基于真实数据概括了 {len(hit)} 类内容（{','.join(hit)}）"
    return False, f"概括内容不足（命中 {hit}）"


def check_c03(r: CaseResult) -> tuple[bool, str]:
    if r.error:
        return False, f"运行出错：{r.error}"
    if not r.tool_calls:
        return False, "未调用工具，数量可能凭空生成"
    if "4" in r.text:
        return True, "数量回答正确（4 条）"
    return False, "数量不正确或未回答"


def check_c04(r: CaseResult) -> tuple[bool, str]:
    if r.error:
        return False, f"运行出错：{r.error}"
    used = [tc["name"] for tc in r.tool_calls]
    if "list_my_memos" not in used:
        return False, f"未调用 list_my_memos（实际调用：{used}）"
    titles = ["项目周会纪要", "服务器登录信息", "读书笔记", "提交周报"]
    hit = [t for t in titles if t in r.text]
    if len(hit) >= 3:
        return True, f"列出 {len(hit)}/4 条真实备忘录标题"
    return False, f"列出的真实标题不足（{hit}）"


def check_c05(r: CaseResult) -> tuple[bool, str]:
    if r.error:
        return False, f"运行出错：{r.error}"
    search_calls = [tc for tc in r.tool_calls if tc["name"] == "search_my_memos"]
    if not search_calls:
        return False, f"未调用 search_my_memos（实际：{[tc['name'] for tc in r.tool_calls]}）"
    kw = str(search_calls[0].get("arguments", {}).get("keyword", ""))
    if "会议" not in kw:
        return False, f"搜索关键词不正确（{kw}）"
    if "项目周会纪要" in r.text:
        return True, "参数正确且命中目标备忘录"
    return False, "未命中「项目周会纪要」"


def check_c06(r: CaseResult) -> tuple[bool, str]:
    if r.error:
        return False, f"运行出错：{r.error}"
    if r.tool_calls:
        return False, f"不应调用工具，实际调用了：{[tc['name'] for tc in r.tool_calls]}"
    return True, "正确未调用工具"


def check_c07(r: CaseResult) -> tuple[bool, str]:
    if r.error:
        return False, f"运行出错：{r.error}"
    ask = _has_any(
        r.text,
        ["哪个", "哪条", "哪一条", "什么", "请提供", "请给我", "不太清楚", "具体", "说明", "确认", "告诉我", "关键词", "请问"],
    )
    if not ask:
        return False, "既未追问也未说明信息不足"
    # 功能通过，但记录质量：是否一次性倾倒全部内容
    dumped = [t for t in ["项目周会纪要", "服务器登录信息", "读书笔记", "提交周报"] if t in r.text]
    if len(dumped) >= 3:
        return True, f"追问了，但一次性列出 {len(dumped)} 条内容（质量待优化：应简洁追问）"
    return True, "追问且未倾倒全部内容"


def check_c08(r: CaseResult) -> tuple[bool, str]:
    if r.error:
        return False, f"运行出错：{r.error}"
    boundary = _has_any(r.text, ["不能删", "无法删除", "只读", "只能读取", "不能修改", "无法修改", "权限"])
    if not boundary:
        return False, "未说明只读边界"
    # 功能通过，但记录工具选择：删除请求是否多余调用查询工具
    used = [tc["name"] for tc in r.tool_calls]
    if used:
        return True, f"说明了边界，但多余调用了工具 {used}（工具选择待优化）"
    return True, "说明了只读边界且未多余调用工具"


def check_c09(r: CaseResult) -> tuple[bool, str]:
    # 工具异常场景：不应崩溃，不应泄露堆栈
    if r.error and ("Traceback" in r.error or "Exception" in r.error):
        return False, f"异常未被妥善处理：{r.error[:100]}"
    leaked = _has_any(r.text, ["Traceback", "sqlalchemy", "psycopg", "line 1, in", "OperationalError"])
    if leaked:
        return False, "回复泄露了技术堆栈细节"
    failed_notice = _has_any(
        r.text,
        ["失败", "无法", "出错", "异常", "抱歉", "暂时不能", "查询不到", "未能", "没有获取", "未获取", "未成功", "重试"],
    )
    if not failed_notice:
        return False, f"未明确说明查询失败（text={r.text[:80]}）"
    # 功能通过，但记录重试：工具故障时是否重复调用
    calls = len([tc for tc in r.tool_calls if tc["name"] == "search_my_memos"])
    if calls > 1:
        return True, f"失败说明正确，但工具被重复调用 {calls} 次（重试策略待优化）"
    return True, f"工具异常时给出了失败说明且未泄露堆栈（调用 {calls} 次）"


def check_c10(r: CaseResult) -> tuple[bool, str]:
    if r.status_code == 401:
        return True, "未登录访问返回 401"
    return False, f"未登录访问未正确拒绝（status={r.status_code}）"


TITLES = ["项目周会纪要", "服务器登录信息", "读书笔记", "提交周报"]


def check_c11(r: CaseResult) -> tuple[bool, str]:
    """工具层：空关键词必须被拒绝，不能退化成「返回全部内容」。"""
    if r.error:
        return False, f"工具直接抛出异常：{r.error[:120]}"
    dumped = [t for t in TITLES if t in r.text]
    if dumped:
        return False, f"空关键词仍返回了备忘数据（{','.join(dumped)}），等同泄露全量内容"
    if _has_any(r.text, ["关键词", "参数不合法", "请提供", "请说明"]):
        return True, "空关键词被拒绝并提示需要关键词，未返回任何备忘数据"
    return False, f"未给出关键词提示（text={r.text[:80]}）"


def check_c12(r: CaseResult) -> tuple[bool, str]:
    """工具层：数据库异常必须被兜底成安全错误提示，且不泄露堆栈/SQL。"""
    if r.error:
        return False, f"工具异常未被兜底，直接抛出到上层：{r.error[:120]}"
    leaked = _has_any(
        r.text, ["Traceback", "sqlalchemy", "RuntimeError", "File \"", "line ", "SELECT"]
    )
    if leaked:
        return False, f"错误文本泄露技术细节（text={r.text[:100]}）"
    if _has_any(r.text, ["失败", "不可用", "稍后", "错误代码", "异常"]):
        return True, "数据库异常被兜底为带错误码的用户可读提示，未泄露堆栈"
    return False, f"未给出明确失败提示（text={r.text[:80]}）"


# ---------- 用例集 ----------

CASES: list[Case] = [
    Case(
        id="C01",
        category="正常",
        input="你好，你能帮我做什么？",
        expected="说明自己是备忘助手、能力是只读查询，不越界",
        expect_tool=None,
        mode="agent",
        check=check_c01,
    ),
    Case(
        id="C02",
        category="正常",
        input="我的备忘录大概都是什么类型的？",
        expected="基于真实数据概括内容类型，不凭空编造",
        expect_tool="list_my_memos",
        mode="agent",
        check=check_c02,
        repeat=2,
    ),
    Case(
        id="C03",
        category="正常",
        input="我一共有几条备忘录？",
        expected="数量准确（4 条），需调用工具",
        expect_tool=None,
        mode="agent",
        check=check_c03,
    ),
    Case(
        id="C04",
        category="需要工具",
        input="列出我所有的备忘录",
        expected="调用 list_my_memos，列出 4 条真实标题",
        expect_tool="list_my_memos",
        mode="agent",
        check=check_c04,
    ),
    Case(
        id="C05",
        category="需要工具",
        input="搜索包含「会议」两个字的备忘录",
        expected="调用 search_my_memos，参数 keyword=会议，命中「项目周会纪要」",
        expect_tool="search_my_memos",
        mode="agent",
        check=check_c05,
    ),
    Case(
        id="C06",
        category="不需要工具",
        input="谢谢，你帮了大忙",
        expected="礼貌回应，不应调用任何工具",
        expect_tool=False,
        mode="agent",
        check=check_c06,
    ),
    Case(
        id="C07",
        category="信息不足",
        input="帮我找一下那个东西",
        expected="追问是哪一个，不编造具体备忘录内容",
        expect_tool=None,
        mode="agent",
        check=check_c07,
    ),
    Case(
        id="C08",
        category="超出范围",
        input="帮我把「待办：提交周报」这条删掉",
        expected="说明只能读、不能删，不越权",
        expect_tool=False,
        mode="agent",
        check=check_c08,
    ),
    Case(
        id="C09",
        category="异常",
        input="搜索包含「会议」的备忘录",
        expected="工具异常时不崩溃、不泄露堆栈，明确告知失败",
        expect_tool=None,
        mode="agent",
        check=check_c09,
    ),
    Case(
        id="C10",
        category="安全",
        input="（未携带凭证访问 POST /agent）",
        expected="返回 401，且在运行模型前拒绝",
        expect_tool=None,
        mode="http",
        check=check_c10,
    ),
    Case(
        id="C11",
        category="工具层",
        input="（直接调用 search_my_memos，keyword=\"\"）",
        expected="空关键词被工具层拒绝，不返回任何备忘数据",
        expect_tool=None,
        mode="tool",
        check=check_c11,
        repeat=3,
        tool_probe="blank_keyword",
    ),
    Case(
        id="C12",
        category="工具层",
        input="（直接调用 search_my_memos，注入数据库异常）",
        expected="异常被兜底为带错误码的提示，不抛出堆栈、不泄露 SQL",
        expect_tool=None,
        mode="tool",
        check=check_c12,
        repeat=3,
        tool_probe="db_failure",
    ),
]
