# LingoGuard · 游戏本地化预检台

> 课程级可运行原型，对应 Issue [#2](https://github.com/gyf4buaa/shuikezhuoye/issues/2)。目标不是替代 CAT/TMS，而是把“模板完整性 + 给定字体/布局假设下的宽度风险 + 有证据来源的消歧与语境缺口”做成一个本地可运行、可复现、可测试的最小闭环。

本项目只声称：**在明确列出的假设下，核心检查可复现、可测试**。不声称解决目标语语法/复数/性数一致，不声称替代游戏引擎内布局验证，也不声称优于现有商业 CAT/TMS 产品。

## 1. 快速运行

环境：Python 3.9+、Pillow 10–11、现代浏览器。项目无前端构建步骤。

```bash
cd shuikezhuoye
python3 -m pip install -r requirements.txt
python3 app.py --port 8000
```

打开 <http://127.0.0.1:8000>。页面会自动载入“中 → 巴西葡语”合成演示；也可在“示例数据集”切换英→葡、中→俄演示。

运行测试：

```bash
python3 -m unittest discover -s tests -v
```

当前 104 个测试通过（2026-11-04，Python 3.9.6 / Pillow 11.3.0）。实际输出见 [docs/测试报告.md](docs/测试报告.md)。

## 2. 演示入口

| 演示 | 内容 | 直达链接（启动后） |
|---|---|---|
| 中 → 巴西葡语 | 占位符错误、ICU 复数分类、标签闭合、2px/38.4px 宽度风险、近阈值、字符基线误判、错误义项、源文缺口、修辞风险 | `/?demo=zh_ptbr` |
| 英 → 巴西葡语 | 同一个 `Rank/Setting/Claim/March` 在不同 UI 语境下的不同译名；证据不足时弃答 | `/?demo=en_ptbr` |
| 中 → 俄语 | 俄语 `one/few/many/other` 分类缺失；ICU 模板不伪造测量；长文本溢出 | `/?demo=zh_ru` |

单条定位示例：

- `/?demo=zh_ptbr&unit=settings.tab.settings`：`Configurações` 比 98px 内容区宽 2.0px。
- `/?demo=en_ptbr&unit=misc.rank_unknown`：`Rank` 无上下文时弃答。
- `/?demo=zh_ru&unit=inventory.items.count`：缺少 `other` 分类，且模板拒绝给出宽度测量。

所有演示数据均为合成数据，项目名、文案和 UI 尺寸不代表任何真实游戏。

## 3. 可验证的核心闭环

### 3.1 模板完整性（确定性）

支持：

- `{name}`、`{0}` 等普通占位符的保留/缺失/多出；
- printf 风格（`%s`、`%d`、`%1$s`）的保留、重排与类型一致性；
- ICU `plural/select/selectordinal` 的括号、分支结构与 CLDR 必需分类（如俄语 `one/few/many/other`，阿拉伯语 6 类）；
- `<b>`、`<color=...>`、`<br/>` 等富文本标签的闭合与结构。

**边界**：`{0}` 没有语义时只验证“保留与重排”，不猜目标语该用单数/复数，也不判断冠词、格、性数一致。`PH012` 只是“可能存在数量影响”的提示，不是语法结论。

### 3.2 宽度风险（确定性，有假设）

用 Pillow/FreeType 加载与浏览器相同的 `assets/fonts/NotoSans-Variable.ttf`，按给定字号、字距、文本框、内边距、行高、最大行数做真实字形测量与贪心换行；同时保留“字符数 × 0.55em”的基线，显示两种方法的分歧。

可复现样本：

| 样本 | 现象 | 说明 |
|---|---|---|
| `settings.tab.settings` | 译文 `Configurações` 实测 100px，内容区 98px，超出 2.0px | 正常宽度风险 |
| `long.banner` | 实测 382.4px / 344px，超出 38.4px | 单行标题不自动换行 |
| `settings.tab.sensitivity` | 宽度占用约 92% | 近阈值预警，不是溢出 |
| `event.year` | `MMXXV` 字符基线判“可容纳”，字体测量判溢出 | `OVF004` 字符基线假阴性 |
| `map.island` | `Ilha` 字符基线判“溢出”，字体测量判可容纳 | `OVF005` 字符基线假阳性 |

**边界**：Pillow 字体宽度 **不等于** 游戏内真实溢出。这里只回答“在上述字体/字号/字距/文本框/换行/无自动缩放/无 fallback 字体链的假设下，宽度风险是什么”。不模拟 Unity/Unreal 的布局、富文本内联样式、自动缩放、字体回退或本地化后的运行时替换。最终仍以目标引擎实测为准。

### 3.3 消歧、源文缺口与修辞（实验性）

- **消歧**：使用人工策展的小型义项库（`data/polysemy.json`），把 key、screen、component、相邻文案、词形等作为证据打分。输出 selected sense、候选义项、证据、置信度；证据不足时明确“弃答”。同一个 `Rank` 在排行榜、军衔、品质三个语境下分别得到 `Classificação`、`Patente`、`Qualidade`；同一个 `Setting` 在设置页和世界观词条下分别得到 `Configurações`、`Ambientação`。
- **源文语境缺口**：对中文源文检测主语省略、时态/体标记不足、指代、占位符语义未知/低置信等情况，输出“需要人工补充什么问题”，而不是替译者补全。
- **修辞风险**：对讽刺、梗、营销语等做启发式标记，建议人工确认语域；不自动改写。
- **可选 LLM**：只用于生成语气/修辞建议，不进入确定性核心；无 API Key 时完全降级。

**边界**：这不是“Agent 理解了文本”。义项库是有限、合成的；关键词/元数据打分可能错；因此设计了弃答路径和反例。`SRC*`、`REG*`、`CTX*` 结果都应视为“需要人确认的线索”，不是自动通过的结论。

## 4. 输入格式与元数据来源

### 4.1 JSON

```json
{
  "project": "my-project",
  "source_locale": "zh-CN",
  "target_locale": "pt-BR",
  "ui_profile": "mobile_dialog",
  "strings": [
    {
      "id": "settings.tab.audio",
      "source": "音频",
      "target": "Áudio",
      "key": "settings.tab.audio",
      "screen": "settings",
      "component": "tab",
      "neighbors": ["画面", "操作"],
      "max_chars": 10,
      "ui": {"profile": "settings_tab"}
    }
  ]
}
```

`ui` 可覆盖默认盒模型；`neighbors` 用于消歧；`max_chars` 只作为字符预算基线，不代替字体测量。单条对象也接受；最多 500 条、单条 4000 字符、请求 2MB。

### 4.2 CSV

```csv
id,source,target,key,screen,component,neighbors,max_chars,profile,box_w
settings.tab.audio,音频,Áudio,settings.tab.audio,settings,tab,画面|操作,10,settings_tab,110
```

文件头可用 `# project=...`、`# target_locale=...`、`# source_locale=...` 注释。

### 4.3 XLIFF 1.2

导入/导出标准 `trans-unit`。额外上下文写入 `<note from="dsh-context">` 的 JSON；问题写入 `<note from="dsh-issue">`。v0.1 会把内联 `<g>/<ph>` 展平为文本，属于已知限制；不支持 XLIFF 2.0。

### 4.4 UI 元数据从哪来

现实接入时，这些字段来自项目已有资源，而不是让译者逐条手填：

| 字段 | 典型来源 |
|---|---|
| `id` / `key` | 字符串表、CAT/TMS 导出、代码扫描 |
| `source` / `target` | 现有翻译导出或待导入批次 |
| `screen` / `component` | 界面路径、控件树、设计稿标注 |
| `neighbors` | 同屏/同一控件附近的文案，可从资源包按 screen 聚合 |
| `max_chars` | 现有设计约束或历史字符预算 |
| `ui.profile` / `box_w/box_h/font_size/...` | 设计稿、引擎 UI 配置、人工整理的小型 profile 表 |

原型会显示 `key/screen/component/neighbors` 的覆盖率；缺失时把条目标为“需上下文”，而不是要求用户填完整表单。当前仓库内置 7 个**合成** UI profile（`data/ui_profiles.json`），接入真实项目时应替换为目标 UI 的实测参数。

## 5. 批量 CLI 流程

```bash
python3 scripts/check.py data/demo_zh_ptbr.json --out out/demo --target pt-BR
# 输出 out/demo/report.json、report.csv（UTF-8 BOM）、checked.xliff
python3 scripts/check.py my.xliff --format xliff --out out/mine --fail-on error
```

`--fail-on error|warning` 可用于 CI；`--llm` 才会请求已配置的实时 LLM。`--out` 目录已加入 `.gitignore`。

## 6. 可选 LLM 配置

```bash
export LLM_API_KEY="..."
export LLM_BASE_URL="https://api.openai.com/v1"   # 任意 OpenAI-compatible 端点
export LLM_MODEL="gpt-4o-mini"                    # 按端点填写
export LLM_TIMEOUT="20"                           # 可选，秒，1–120
python3 app.py --port 8000
```

- 无 `LLM_API_KEY`：确定性模式，所有核心检查正常；勾选 UI 的“LLM 语气建议”也只会降级并在结果中显示“未配置 · 已降级”。
- 有 Key 且勾选：只对 `REG001` 修辞风险逐条请求建议；调用次数、模型名、错误写入报告。请求失败不影响核心检查。
- 页面顶部和结果区的 `LLM` 标签区分“未配置（确定性）”“已配置·未调用”“实时模型·调用 n 次”。
- 不会把 API Key 写入仓库或报告；示例数据不会发送到第三方，除非用户主动勾选并配置 LLM。

## 7. 导出

| 格式 | 内容 |
|---|---|
| JSON | 元数据、汇总、每条 unit、问题、上下文证据、测量假设、引擎边界、LLM 状态 |
| CSV | 便于表格/回导的扁平行；CLI 写 UTF-8 BOM |
| XLIFF 1.2 | 可回导的 `trans-unit`，附上下文与问题 note |

导出只包含当前内存中的批次，不写入磁盘；浏览器下载由前端完成。

## 8. 测试与证据

- 单元/集成/API/CLI：`python3 -m unittest discover -s tests -v`（104 tests）。
- 手工浏览器验证：在 Chrome 中载入 `zh_ptbr` 后，28 条 unit、6 张汇总卡、筛选/搜索/方法弹窗正常；对 `settings.tab.settings`，浏览器 DOM 实测与 Pillow 判定一致（均溢出），页面无横向滚动。
- 截图与对比：[`docs/evidence/`](docs/evidence/)；PR 描述含 Before/After 和基线说明。

## 9. 目录

```text
app.py                     # Web 入口
localization/             # 解析、模板检查、字体测量、消歧、导出、HTTP 服务
web/                      # 无构建的前端
data/                     # 合成演示数据、义项库、UI profile
assets/fonts/             # Noto Sans + OFL 许可证
scripts/check.py          # 可复现批量导入 → 检查 → 导出
tests/                    # 104 个测试
docs/                     # 方案比较、测试报告、演示脚本、接入说明、证据图
```

## 10. 已知边界（请先读）

1. 不判断目标语语法、复数、性数一致；`{0}` 无语义时只检查保留/重排。
2. Pillow 宽度是给定字体/布局假设下的风险测量，不是游戏引擎真实溢出。
3. 消歧/源文缺口/修辞是实验性启发式 + 小型合成义项库，不是语义理解；证据不足会弃答。
4. 不支持 CJK 字形测量（Noto Sans 无 CJK）；不渲染 ICU 分支后测量。
5. 不模拟自动缩放、富文本内联样式、fallback 字体链、引擎布局；不测量运行时替换后的文本。
6. XLIFF 1.2 的 `<g>/<ph>` 会展平；不支持 XLIFF 2.0。
7. 没有厂商访谈、商业产品 A/B 或真实项目基准；与 CAT/TMS 的功能重叠见 [docs/方案比较.md](docs/方案比较.md)。

## 11. 文档

- [方案比较](docs/方案比较.md)：三种以上路线、与 CAT/TMS 的同质化部分、增量价值假设。
- [测试报告](docs/测试报告.md)：环境、命令、实际输出、正常/溢出/近阈值/失败样本。
- [演示脚本](docs/演示脚本.md)：课程答辩 5 分钟流程与可复现命令。
- [接入说明](docs/接入说明.md)：CSV/XLIFF 字段、元数据来源、批量接入步骤。
- [证据图](docs/evidence/)：Before（main 仓库初始状态）与 After（运行中的应用）。

## 12. 课程与合规说明

- 所有示例项目、文案、UI 尺寸、义项库和“失败样本”均为合成数据，已标注“合成”。
- 未进行厂商访谈，不编造厂商反馈或商业数据。
- 仓库为公开仓库；不提交 API Key、私有项目资料或个人信息。
- 字体为 Noto Sans，许可证见 [`assets/fonts/OFL.txt`](assets/fonts/OFL.txt)。
