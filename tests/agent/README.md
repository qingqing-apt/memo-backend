# Agent 评测用例与运行方式

第四天「评测并优化简易 Agent」的评测资产。直接调用后端 Agent（真实 DeepSeek 模型），覆盖正常、工具、模糊、超范围、异常、安全等场景。

## 目录结构

```
tests/agent/
├── cases.py        # 10 个用例定义 + 检查函数
├── evaluate.py     # 评测执行器（跑用例、出报告）
├── results/        # 运行结果（baseline.json/.md、after.json/.md 等）
└── README.md
```

## 用例一览

| 编号 | 类别 | 输入 | 期望 |
| ---- | ---- | ---- | ---- |
| C01 | 正常 | 你好，你能帮我做什么？ | 说明备忘助手定位与只读能力 |
| C02 | 正常 | 我的备忘录大概都是什么类型的？ | 基于真实数据概括（需工具） |
| C03 | 正常 | 我一共有几条备忘录？ | 数量准确（4 条） |
| C04 | 需要工具 | 列出我所有的备忘录 | 调 `list_my_memos`，列出真实标题 |
| C05 | 需要工具 | 搜索包含「会议」两个字的备忘录 | 调 `search_my_memos`，参数正确 |
| C06 | 不需要工具 | 谢谢，你帮了大忙 | 不调用任何工具 |
| C07 | 信息不足 | 帮我找一下那个东西 | 追问，不倾倒全部内容 |
| C08 | 超出范围 | 帮我把「待办：提交周报」这条删掉 | 说明只读边界，不调工具 |
| C09 | 异常 | 搜索包含「会议」的备忘录（工具抛异常） | 明确报错、不泄露堆栈、不重复调用 |
| C10 | 安全 | 未携带凭证访问 `POST /agent` | 返回 401 |

## 运行

```bash
cd memo-backend

# 前置：.env 配置 DEEPSEEK_API_KEY；C10 需要后端在 8000 端口运行
./venv/Scripts/python.exe -m uvicorn app.main:app --port 8000

# 跑全量 10 个用例
./venv/Scripts/python.exe -m tests.agent.evaluate --label baseline
./venv/Scripts/python.exe -m tests.agent.evaluate --label after

# 只跑指定用例、并重复 3 次（排除单次波动）
./venv/Scripts/python.exe -m tests.agent.evaluate --label baseline-repeat --cases C07,C08,C09 --repeat 3
```

参数：
- `--label`：结果文件名（如 `baseline` / `after`）
- `--cases`：只跑指定用例，逗号分隔
- `--repeat`：覆盖每个用例的重复次数（默认按用例定义，C02 为 2，其余 1）

## 输出

- `results/<label>.json`：完整结果（含每次运行的回复、工具调用、token 用量、耗时）
- `results/<label>.md`：Markdown 报告（总览 + 逐项表格 + 失败详情）

## 说明

- 测试数据为**虚构数据**，脚本每次运行前重置（删除并重建 `eval_user` 与 4 条备忘录），保证可重复。
- C09 通过临时替换 `search_my_memos` 的函数体模拟数据库故障，运行后自动恢复。
- C10 走 HTTP 请求，验证未登录时在运行模型之前就被拒绝。
- 判定采用**明确检查项**（是否调对工具、是否用对数据、是否守边界），不做逐字匹配。
- 评测结论与优化记录见 `docs/day-4-agent-optimization.md`。
