# 源码感知翻译 PoC（独立于稳定版 PR #3）

一个可本地运行的最小 PoC：**选字符串 → 真实检索合成游戏工程源码 → 查看文件路径/行号/片段/推断依据 →（配置 API 时）用同一个模型对照“只给文本”与“源文 + 检索上下文”的翻译**。

> ⚠️ **合成数据**：`demo_project/` 是为本演示人工编写的 Unity/C# 风格示例，不是任何真实游戏或企业源码。默认只发送这些合成文本；不会上传真实企业源码。
>
> **没有 API Key 时绝不会伪造调用**：页面只展示本地检索证据，并明确标注“未调用模型”，不会出现任何 AI 译文。

## 60 秒快速开始

```bash
cd source-aware-demo
python3 app.py            # 或 ./run.sh
# 打开 http://127.0.0.1:8010/
```

要求 Python 3.9+，**无第三方依赖**、无 npm 构建。常用参数：`--port 8080`、`--open`（启动后打开浏览器）。

演示脚本见 [`docs/演示脚本.md`](docs/演示脚本.md)。

## 它实际做了什么

1. **读字符串表**：从 `demo_project/Assets/Localization/en.json` 读取 Key 与源文本，计算行号；同时扫描 CSV 表。
2. **真实检索**：用户选中 Key 后，后端在 `demo_project/Assets/{Scripts,Localization}` 中逐文件、逐行搜索：
   - Key 的精确引用（如 `L.Get("ui.leaderboard.rank_column")`）；
   - 与源文本完全相等的引号内字面量（如 `"Rank"`）；
   - 字符串表定义。
3. **返回证据**：每个命中都包含**实际相对路径、1-based 行号、列号、周边代码片段、所在类/方法**。
4. **确定性推断**：用命中行与上下文中的真实标识符/注释词元，给出“按钮/交互”“列表/表头”“等级/身份”“回退/硬编码”等语境标签、依据词元与置信度；表格定义明确“不提供界面语境”。这不是编译器/语义分析，页面标注为“启发式推断”。
5. **同文本歧义**：`Rank` 同时属于 `ui.leaderboard.rank_column` 与 `ui.military.rank_badge`。未直接引用所选 Key 的命中会被标为“同文本候选”，不会冒充直接证据。
6. **可选同模型对照**：配置 OpenAI-compatible API 后，用**同一模型、同一 temperature/max_tokens** 调用两次：
   - A：只给源文本；
   - B：源文本 + 检索出的路径/行号/片段/推断；
   页面把结果标为 `LIVE · 真实 API 调用`，并显示模型、耗时、usage 与所用证据。

## 配置 API（可选）

Key 只从**服务进程环境变量**读取，不接受浏览器输入、不写入磁盘、不返回给前端、不打印到日志。

DeepSeek 示例：

```bash
export SOURCEAWARE_API_KEY=sk-...            # 不要提交到仓库
export SOURCEAWARE_LLM_BASE_URL=https://api.deepseek.com/v1
export SOURCEAWARE_LLM_MODEL=deepseek-chat
python3 app.py
```

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SOURCEAWARE_API_KEY` | 空 | 为空时进入“仅检索”模式，绝不调用模型 |
| `SOURCEAWARE_LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible base URL |
| `SOURCEAWARE_LLM_MODEL` | `deepseek-chat` | 两个对照调用使用同一个模型 |
| `SOURCEAWARE_TIMEOUT_SECONDS` | `20` | 单次请求超时，限制在 1–120 秒 |
| `SOURCEAWARE_MAX_OUTPUT_TOKENS` | `240` | 单次输出上限，限制在 32–1024 |
| `SOURCEAWARE_MAX_CONTEXT_CHARS` | `4000` | 发送给模型的证据字符上限，限制在 500–20000 |

安全提醒：Key 只在服务进程内。默认只监听 `127.0.0.1`；不要把带 Key 的实例暴露到公网。请使用可信的 API 端点。

## 无 Key 时的行为（严格区分）

- `/api/compare` 返回 `status: "disabled"`、`baseline: null`、`contextual: null`，消息明确为“仅上下文检索演示、未调用模型”。
- 页面显示黄色提示条，按钮禁用，结果卡写明“未调用模型，因此没有译文”。
- 单元测试用注入的 fake transport 覆盖真实调用路径（校验同模型、同参数、上下文截断、错误与 Key 脱敏），但**不会把 fake 输出当作真实 API 结果展示**。

## 只读边界与控制

- 所有检索固定根目录 `demo_project/`，路径 `resolve()` 后必须仍位于根目录内；符号链接、隐藏目录与非常规后缀不扫描。
- 只读 `.cs` / `.json` / `.csv`，单文件上限 256 KB，结果上限 40 条，代码片段窗口 ±2 行。
- 静态页面只从 `web/` 提供，并校验后缀与路径边界；拒绝 `..`、编码穿越与源码文件。
- HTTP 请求体上限 8 KB；目标语言为固定白名单；Key 长度上限 120。
- 模型调用：单次超时、`max_tokens`、证据字符上限；错误信息脱敏（包含 Key 时替换为 `[redacted]`）。
- 安全响应头：CSP、`nosniff`、`no-referrer`、`DENY` frame。

## 可复现检查

```bash
cd source-aware-demo
python3 -m unittest discover -s tests -v     # 见 docs/测试报告.md
python3 -m compileall -q sourceaware tests scripts app.py
node --check web/app.js

# 离线检索 CLI（不调用模型），可用于现场快速验证
python3 scripts/lookup.py --list
python3 scripts/lookup.py ui.leaderboard.rank_column
python3 scripts/lookup.py ui.leaderboard.rank_column --json
```

## 目录

```text
source-aware-demo/
├── app.py                 # 启动入口
├── run.sh                 # 一键启动
├── sourceaware/           # 配置 / 读取字符串表 / 检索 / 翻译 / HTTP
├── demo_project/          # ⚠️ 合成 Unity/C# 演示工程（只读）
├── web/                   # 无构建的 HTML/CSS/JS 界面
├── tests/                 # 53 个标准库 unittest
├── scripts/lookup.py      # 可复现的离线检索 CLI
└── docs/                  # 60 秒演示脚本、测试报告、设计说明、截图
```

## 已知限制（避免过度声称）

- 只在合成演示工程上验证；**尚未证明能在任意真实游戏中自动找到完整语义**。
- 检索是字面 Key/文本 + 文件扫描，不解析反射、运行时拼接、数据绑定、序列化或动态资源加载。
- 类/方法定位与语境分类是小型启发式，不是 C# 编译器或语义分析；可能误判，候选证据会要求人工确认。
- 同文本可能跨多个 Key；字面量证据不能证明归属。
- 真实 API 对照未做人工审校，也没有用真实企业数据/密钥验证；输出质量取决于所配置模型。
- 本仓库主分支为 greenfield，本 PoC 是独立目录；与 PR #3 的稳定版互不改动（仅沿用同样的“标准库 + 无构建 Web”取向与视觉语言）。
