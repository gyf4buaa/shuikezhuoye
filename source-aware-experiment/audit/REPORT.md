# P0/P1 真实项目实验报告：OpenTTD 15.3

状态：**P0 已完成**；**P1 工具链已完成，真实模型实验未执行**（本机没有 API Key，未发起任何付费调用）。因此本报告不提供任何 A/B/C 翻译质量、延迟或费用数字；这些项目全部是“未测”，不是 0，也不是估算值。

## 1. 真实项目与可复现语料

| 项目 | 值 |
|---|---|
| 项目 | OpenTTD |
| 版本 / commit | 15.3 / `14ec60f248547d4d062a1160f0fc26d742319888` |
| License | GPL-2.0，仓库内 `COPYING.md` |
| 仓库 | https://github.com/OpenTTD/OpenTTD |
| 归档 | `https://codeload.github.com/OpenTTD/OpenTTD/tar.gz/14ec60f248547d4d062a1160f0fc26d742319888` |
| 归档 SHA-256 | `df5962cf5fc4938171607a40db69585e2fe3a2a8c8cfe2831862c9e61ff107d7` |
| 字符串表 | `src/lang/english.txt`，4721 个 StringID |
| 本地解压目录 | `.corpus/openttd-15.3`（gitignored，不随仓库分发） |

选择理由：这是一个真实、成熟、GPL-2.0 的游戏，字符串量足够大，且引用形式覆盖 C++ 直接 token、`.ini` 设置模板、cargo token-pasting 宏、基础图形 `.obg` 元数据和多类 computed StringID。它的多语言表还可用于验证“不得把目标语言表当检索证据”的硬性约束。

语料不 vendor；仓库只保存带 `path:line` 的短证据引用。完整机器可读证据在 `audit/results.json`。

## 2. P0 方法

1. 只读取 `src/lang/english.txt`，按 `##id` 段解析连续 StringID；定义行单独保存，绝不当作“使用位置”。
2. 检索白名单：`src/**/*.{cpp,c,h,hpp}`、`src/table/settings/*.ini`、`media/baseset/*.{obg,obs}`。拒绝所有其他 `src/lang/*`、`src/3rdparty/`、`.po/.mo`、docs/regression、gold/reference 路径。
3. 引用识别：
   - 直接 token；
   - cargo 宏（`MK_STR_CARGO_PLURAL/SINGULAR`、`MK_STR_QUANTITY`、`MK_STR_ABBREV`）与 `_default_cargo` 行；
   - settings 模板的 `strval` + 数字 `min/max`，并按 `src/settings.cpp` 的 `str_val - min_val + value` 规则换算；
   - 只对人工核验过的连续 StringID family 做算术推断（颜色、目标按钮、购买窗口标题、月份、日期、分组、小地图类型等）；
   - `.obg/.obs` 中的 `@description_STR_...@` 资源绑定。
4. 状态区分：`direct`、`macro`、`settings`、`arithmetic`、`dynamic_unresolved`、`missing`、`unknown_key`。`missing` 不等于“字符串已死”；`dynamic_unresolved` 表示可能有引用但当前规则无法证明。
5. 人工从源码逐条核验 33 条样本的 expected context、expected location、同词干扰项。核验结果在 `audit/cases.json`。

真实语料上的定位器覆盖（不是样本准确率）：

| 状态 | 数量 |
|---|---:|
| direct | 3795 |
| macro | 120 |
| settings | 75 |
| arithmetic | 124 |
| dynamic_unresolved | 252 |
| missing | 355 |
| **合计** | **4721** |

证据文件 1324 个；cargo 相关 key 128（其中 120 个最终状态为 macro）；settings 范围可解释的 key 247（其中 75 个仅靠 settings 命中，其余有更高优先级的直接证据）；算术 family 可解释的 key 139（其中 124 个最终状态为 arithmetic）；车辆名 `+ local_id` 部分覆盖 4 个基址。

## 3. 33 条人工核验样本

表里的 expected location 是人工从源码核验的“应找到位置”，不是模型输出。`✅ (dead)` 表示该 key 在允许的源码中确实没有引用，定位器正确地没有伪造证据。

| # | case | key | category | expected | locator status | hit |
|---|---|---|---|---|---|---|
| 1 | `placeholder.plane_crash` | `STR_NEWS_PLANE_CRASH_OUT_OF_FUEL` | placeholder | `src/aircraft_cmd.cpp:1361` | direct | ✅ |
| 2 | `placeholder.company_merger` | `STR_NEWS_COMPANY_MERGER_DESCRIPTION` | placeholder | `src/economy.cpp:1993` | direct | ✅ |
| 3 | `placeholder.measure_length` | `STR_MEASURE_LENGTH` | placeholder | `src/viewport.cpp:2865` | direct | ✅ |
| 4 | `placeholder.performance_percent` | `STR_PERFORMANCE_DETAIL_PERCENT` | placeholder | `src/graph_gui.cpp:1596` | direct | ✅ |
| 5 | `placeholder.league_rank` | `STR_COMPANY_LEAGUE_COMPANY_RANK` | placeholder | `src/league_gui.cpp:335` | direct | ✅ |
| 6 | `placeholder.smallmap_industry` | `STR_SMALLMAP_INDUSTRY` | placeholder | `src/smallmap_gui.cpp:1537` | direct | ✅ |
| 7 | `placeholder.industry_construction` | `STR_NEWS_INDUSTRY_CONSTRUCTION` | placeholder | `src/table/build_industry.h:1158` | direct | ✅ |
| 8 | `placeholder.config_setting_label` | `STR_CONFIG_SETTING_NOSERVICE` | placeholder | `src/table/settings/game_settings.ini:65` | direct | ✅ |
| 9 | `same_text.cargo_plural` | `STR_CARGO_PLURAL_COAL` | same_text | `src/table/cargo_const.h:59` | macro | ✅ |
| 10 | `same_text.cargo_singular` | `STR_CARGO_SINGULAR_COAL` | same_text | `src/table/cargo_const.h:59` | macro | ✅ |
| 11 | `same_text.colour_default` | `STR_COLOUR_DEFAULT` | same_text | `src/company_gui.cpp:595` | direct | ✅ |
| 12 | `same_text.station_class_default` | `STR_STATION_CLASS_DFLT` | same_text | `src/newgrf_station.cpp:39` | direct | ✅ |
| 13 | `same_text.vehicle_interval_default` | `STR_VEHICLE_DETAILS_DEFAULT` | same_text | `src/vehicle_gui.cpp:2393` | direct | ✅ |
| 14 | `same_text.none_generic` | `STR_NONE` | same_text | `src/road_gui.cpp:1824` | direct | ✅ |
| 15 | `same_text.group_by_none` | `STR_GROUP_BY_NONE` | same_text | `src/vehicle_gui.cpp:155` | direct | ✅ |
| 16 | `same_text.config_none` | `STR_CONFIG_SETTING_NONE` | same_text | `src/table/settings/game_settings.ini:235` | direct | ✅ |
| 17 | `dynamic.colour_pale_green` | `STR_COLOUR_PALE_GREEN` | dynamic | `src/company_gui.cpp:595` | arithmetic | ✅ |
| 18 | `dynamic.colour_grey` | `STR_COLOUR_GREY` | dynamic | `src/company_gui.cpp:595` | arithmetic | ✅ |
| 19 | `dynamic.goal_ok` | `STR_GOAL_QUESTION_BUTTON_OK` | dynamic | `src/goal_gui.cpp:353` | arithmetic | ✅ |
| 20 | `dynamic.goal_close` | `STR_GOAL_QUESTION_BUTTON_CLOSE` | dynamic | `src/goal_gui.cpp:353` | arithmetic | ✅ |
| 21 | `dynamic.buy_ship_caption` | `STR_BUY_VEHICLE_SHIP_CAPTION` | dynamic | `src/build_vehicle_gui.cpp:1770` | arithmetic | ✅ |
| 22 | `dynamic.buy_aircraft_caption` | `STR_BUY_VEHICLE_AIRCRAFT_CAPTION` | dynamic | `src/build_vehicle_gui.cpp:1770` | arithmetic | ✅ |
| 23 | `dynamic.month_february` | `STR_MONTH_FEB` | dynamic | `src/date_gui.cpp:134` | arithmetic | ✅ |
| 24 | `dynamic.day_31` | `STR_DAY_NUMBER_31ST` | dynamic | `src/date_gui.cpp:133` | arithmetic | ✅ |
| 25 | `dynamic.ai_speed_slow` | `STR_AI_SPEED_SLOW` | dynamic | `src/table/settings/difficulty_settings.ini:162` | settings | ✅ |
| 26 | `dynamic.group_all_ships` | `STR_GROUP_ALL_SHIPS` | dynamic | `src/group_gui.cpp:312` | arithmetic | ✅ |
| 27 | `dynamic.smallmap_industries` | `STR_SMALLMAP_TYPE_INDUSTRIES` | dynamic | `src/smallmap_gui.cpp:1519` | arithmetic | ✅ |
| 28 | `missing.scenedit_separator` | `STR_SCENEDIT_FILE_MENU_SEPARATOR` | missing | — | missing | ✅ (dead) |
| 29 | `missing.show_hidden_ship` | `STR_SHOW_HIDDEN_ENGINES_VEHICLE_SHIP` | missing | `src/autoreplace_gui.cpp:285` | missing | ❌ |
| 30 | `missing.toolbar_map_tooltip` | `STR_TOOLBAR_TOOLTIP_DISPLAY_MAP` | missing | `src/toolbar_gui.cpp:2228` | missing | ❌ |
| 31 | `resource.basegraphics_dos` | `STR_BASEGRAPHICS_DOS_DESCRIPTION` | resource_binding | `media/baseset/orig_dos.obg:9` | direct | ✅ |
| 32 | `missing.month_abbrev_feb` | `STR_MONTH_ABBREV_FEB` | missing | `src/strings.cpp:569` | missing | ❌ |
| 33 | `missing.secondary_colour_setting` | `STR_COLOUR_SECONDARY_PALE_GREEN` | missing | `src/table/settings/gui_settings.ini:377` | missing | ❌ |

其中 placeholder 8 条、same-text 8 条、computed/dynamic 11 条、missing 5 条、resource binding 1 条。

## 4. 指标：实用定位器 vs 朴素全文扫描

“朴素”基线：对每个 key 和数据文件做 key 子串扫描，再对去掉样式码后的显示文本做子串扫描；它不区分定义行与使用行，也不建模宏/设置/算术。两条路径使用同一份 allowlist 语料。

| 指标 | 实用定位器 | 朴素基线 |
|---|---:|---:|
| 找到人工核验位置 | **28 / 33** | 15 / 33 |
| 正确判定为 dead | 1 | — |
| 人工核验存在但漏检 | **4** | 18 |
| 把定义行当成使用位置 | **0** | **33 / 33** |
| 同词 key 合并（本组样本） | 0 | 0 |
| computed/dynamic 命中 | **11 / 11** | **0 / 11** |

分类结果：

| category | cases | practical hit | naive hit |
|---|---:|---:|---:|
| placeholder | 8 | 8 | 8 |
| same_text | 8 | 8 | 6 |
| dynamic | 11 | 11 | 0 |
| missing | 5 | 0（其中 1 条正确 dead） | 0 |
| resource_binding | 1 | 1 | 1 |

结论边界：这是**人工挑选**的 33 条，不是随机抽样，不能把 28/33 当成全体 4721 个 key 的总体准确率。它证明了“宏/设置/算术/资源元数据能显著超过全文扫描”，同时也暴露了 4 个真实漏检。

同词不同义样本：`Default` 出现在颜色、站点 class、车辆保养间隔三个不同 key；`None` 出现在通用下拉、group-by、设置枚举；`Coal` 的 plural/singular 文本完全相同但槽位不同。定位器按 key/槽位区分，没有把它们合并；朴素文本扫描则无法区分定义行里的同文条目。

## 5. 至少 5 个真实失败样本

以下命令均以仓库根目录 `source-aware-experiment/` 为工作目录；语料由 `python3 scripts/fetch_corpus.py` 下载。输出中的 `status=missing` 是定位器实际结果，不是人工猜测。

通用查询命令：

```bash
python3 - <<'PY'
import json
d=json.load(open('audit/results.json'))
for c in d['cases']:
    if c['key'] in {'STR_SHOW_HIDDEN_ENGINES_VEHICLE_SHIP','STR_TOOLBAR_TOOLTIP_DISPLAY_MAP',
                    'STR_MONTH_ABBREV_FEB','STR_COLOUR_SECONDARY_PALE_GREEN',
                    'STR_SCENEDIT_FILE_MENU_SEPARATOR','STR_NEWS_INDUSTRY_CONSTRUCTION'}:
        print(c['key'], c['practical']['status'], c['expected_locations'], c['practical']['evidence'][:2])
PY
```

### F1. `STR_SHOW_HIDDEN_ENGINES_VEHICLE_SHIP` — 车辆类型偏移 family 未建模

- 源码证据：`src/autoreplace_gui.cpp:285`
  `widget->SetStringTip(STR_SHOW_HIDDEN_ENGINES_VEHICLE_TRAIN + vehicletype, ...)`
- 人工核验：ship 是 `+ vehicletype` 的一个偏移，`STR_SHOW_HIDDEN_ENGINES_VEHICLE_*` 连续。
- 定位器：`status=missing`，0 条证据。
- 原因：只建模了人工确认过的 family 列表，没有把该 tooltip family 加入；`vehicletype` 的取值也来自运行时数据。
- 复现：`grep -n "STR_SHOW_HIDDEN_ENGINES_VEHICLE_TRAIN + vehicletype" .corpus/openttd-15.3/src/autoreplace_gui.cpp`；再跑上面的通用查询。
- 影响：这是覆盖失败，不是字符串已死；不能把 `missing` 当成“可删除”。

### F2. `STR_TOOLBAR_TOOLTIP_DISPLAY_MAP` — widget→tooltip 稀疏映射不可推断

- 源码证据：`src/toolbar_gui.cpp:2228`
  `... STR_TOOLBAR_TOOLTIP_PAUSE_GAME + widget`
- 人工核验：toolbar 的 widget 编号是稀疏枚举，显示地图按钮的偏移不是简单连续计数。
- 定位器：`status=missing`。
- 原因：通用 `base + index` 推断在稀疏 widget 映射上不安全；强行推断会产生错误关联，因此选择不猜。
- 复现：`grep -n "STR_TOOLBAR_TOOLTIP_PAUSE_GAME + widget" .corpus/openttd-15.3/src/toolbar_gui.cpp`。

### F3. `STR_MONTH_ABBREV_FEB` — 只建模了全月份，没有建模缩写月份

- 源码证据：`src/strings.cpp:569`
  `MakeParameters(..., STR_MONTH_ABBREV_JAN + ymd.month, ...)`
- 人工核验：`ymd.month` 是 1-based，2 月对应 `STR_MONTH_ABBREV_FEB`。
- 定位器：`status=missing`。
- 原因：`STR_MONTH_JAN + ymd.month` 有人工 family，`STR_MONTH_ABBREV_JAN + ymd.month` 没有；families 列表不完整。
- 复现：`grep -n "STR_MONTH_ABBREV_JAN + ymd.month" .corpus/openttd-15.3/src/strings.cpp`。

### F4. `STR_COLOUR_SECONDARY_PALE_GREEN` — 设置范围上界是符号常量

- 源码证据：`src/table/settings/gui_settings.ini:377`
  `strval   = STR_COLOUR_SECONDARY_DARK_BLUE`，同一段 `max = COLOUR_END`。
- 人工核验：这是“secondary company colour”设置的下拉选项，`COLOUR_END` 是 16 色枚举上界。
- 定位器：`status=missing`，只认出 `strval` 不够，因为 gap 规则需要数字 `min/max`，而 `COLOUR_END` 是符号。
- 原因：settings 解析器只接受字面量数字，未解析枚举常量。
- 复现：`grep -n "strval   = STR_COLOUR_SECONDARY_DARK_BLUE\|max      = COLOUR_END" .corpus/openttd-15.3/src/table/settings/gui_settings.ini`。

### F5. `STR_NEWS_INDUSTRY_CONSTRUCTION` — 找到表行，但没有跟到字段的运行时使用

- 表行证据：`src/table/build_industry.h:1158`（`IndustrySpec::new_industry_text` 槽位）。
- 实际运行时调用：`src/industry_cmd.cpp:1719`
  `GetEncodedString(ind_spc->new_industry_text, ind_spc->name, STR_TOWN_NAME, ind->town->index)`
- 定位器：`status=direct`，命中表行；但返回的 34 条证据里没有 `industry_cmd.cpp:1719`，因为它不跟踪结构体字段的数据流。
- 这是“部分成功”的失败样本：位置找到了，但 `{STRING}` 是工业名、`{TOWN}` 是城镇、以及真实参数顺序只能靠人工读 `IndustrySpec` 与调用点确认。当前已把 NewGRF 兼容映射降权，表行现在排在 C 证据的第一条；`industry_cmd.cpp:1719` 仍不在返回结果中。
- 复现：`grep -n "new_industry_text" .corpus/openttd-15.3/src/industry_cmd.cpp .corpus/openttd-15.3/src/table/build_industry.h`。

### F6. `STR_SCENEDIT_FILE_MENU_SEPARATOR` — 真实 dead string

- 允许的 `src/**` 中没有任何引用；它只出现在语言表。
- 定位器：`status=missing`，0 条证据。
- 这不是漏检：人工 grep 也找不到使用位置。它说明 `missing` 必须分成“已确认 dead”和“未建模”两类，不能混为一个指标。
- 复现：`grep -RIn "STR_SCENEDIT_FILE_MENU_SEPARATOR" .corpus/openttd-15.3/src --include='*.cpp' --include='*.h' --include='*.ini'`（无输出）。

另外，朴素基线在 **33/33** 个样本上都把 `src/lang/english.txt` 的定义行当成了检索结果；`STR_NONE`/`STR_COLOUR_DEFAULT` 的显示文本还会命中其他同文 key 的定义行。这是“同词不同义”下的错误关联风险，实用定位器用 key + 定义/使用分离避免了它。

## 6. P1：A/B/C 工具链

三臂的**唯一**差异：

| arm | user prompt 内容 |
|---|---|
| A | `Source text (English): "..."` |
| B | `String key: STR_...` + 同一段 source text |
| C | key + source text + 检索到的证据块（最多 4 条，每条含 `path:line`、scope、调用参数、关系、短 snippet） |

固定项：`target_locale=zh-CN`、同一 system prompt、`temperature=0`、`max_output_tokens=256`、同一份 source text、prompt version `p1-v1`。system prompt 要求只输出 `{"translation": "..."}`，保留 `{STRING}`/`{NUM}`/`{COMMA}` 等占位符和 `{BLACK}` 等样式码。

运行记录包含：语料 commit、dataset SHA-256、prompt version、每臂 prompt 的 SHA-256、evidence IDs、retrieval status。manifest 还记录模型名、base URL、预算和 `live_executed`。**没有记录 API key**；live 配置只写 `[from environment; not recorded]`。

### 当前执行状态

```text
mode=dry_run
live_executed=false
cases=33
prompts_built=99
live_calls=0
```

真实模型实验 **未执行**：本机没有 `SOURCEAWARE_API_KEY`，也没有提供其他兼容 endpoint。没有模拟调用、没有伪造翻译、没有用离线模板冒充模型输出。因此：

| 指标 | 状态 |
|---|---|
| A/B/C 语境义准确率 | 未测 |
| A/B/C 术语一致性 | 未测 |
| A/B/C 占位符保持 | 未测 |
| A/B/C 目标语言流畅度 | 未测 |
| 额外 token | 未测 |
| 额外延迟 | 未测 |
| 费用 | 未测（无价格表，`cost_usd=null`） |

### Live 入口与预算

```bash
# 没有 key 时：退出码 2，不写任何文件，不发起请求
python3 scripts/evaluate.py --corpus .corpus/openttd-15.3 --out runs/live-1 --live

# 有 key 时（示例；本报告没有执行）
SOURCEAWARE_API_KEY=... python3 scripts/evaluate.py \
  --corpus .corpus/openttd-15.3 --out runs/live-1 --live \
  --model deepseek-chat \
  --max-total-tokens 20000 \
  --input-price-per-1k 0.0001 --output-price-per-1k 0.0002
```

硬约束：`--live` 必须同时有 key 和正数 `--max-total-tokens`；每一轮先做 token 预检，超预算或请求数上限就停止并保留部分结果（`aborted: true`）；HTTP/网络错误记录为 `transport_error` 后停止；JSON 解析失败记录为 `parse_error`，不做二次“修复”调用。价格不提供时费用为 `null`。

### 人工评分

评分表在 dry run 的 `review_template.csv`：`context_sense`、`terminology`、`placeholders`、`fluency`、`overall`，每项 1-5。`scripts/review.py` 只汇总已填分数，空值不插补；C vs A / C vs B 的配对比较只在同一 case 两臂都有 `overall` 时计算。

**当前没有人工评分，因此没有任何质量结论。**

## 7. 复现命令

```bash
cd source-aware-experiment

# 1) 下载、SHA-256 校验、解压到 .corpus/（唯一联网步骤）
python3 scripts/fetch_corpus.py

# 2) P0：33 条真实样本 + 朴素基线对比
python3 scripts/audit.py --corpus .corpus/openttd-15.3
# -> audit/results.json，stdout 打印汇总

# 3) P1 dry run：生成 99 条 A/B/C prompt 与人工评分表，不联网
python3 scripts/evaluate.py --corpus .corpus/openttd-15.3 --out runs/dryrun-1

# 4) 单测（离线；fixture 语料，不下载真实 corpus）
python3 -m unittest discover -s tests -v

# 5) P1 评分汇总（人工填完 review_template.csv 后）
python3 scripts/review.py --scores runs/live-1/review_template.csv \
  --out runs/live-1/review_summary.json
```

单独查看某个失败样本：

```bash
python3 - <<'PY'
import json
d=json.load(open('audit/results.json'))
for c in d['cases']:
    if c['key'] == 'STR_TOOLBAR_TOOLTIP_DISPLAY_MAP':
        print(json.dumps(c['practical'], indent=2))
PY
```

## 8. 批判性评估与限制

1. **没有真实模型结果，不能声称 C 优于 B。** dry run 只能证明工具链、prompt 隔离和泄漏防护可运行；A/B/C 的质量差异仍未验证。Key-only（B）完全可能已经足够，尤其是同词 key 在代码里本来就是唯一的。
2. **样本是人工挑选的，不是随机抽样。** 28/33 不能外推为全体 4721 个 key 的准确率；它覆盖的是我们预先知道的难点（宏、设置、算术、资源元数据）。
3. **4 个漏检是真的。** 其中 2 个是 family 列表不完整（vehicle tooltip、month abbrev），1 个是稀疏 widget 映射，1 个是符号上界设置。继续扩 family 会提高覆盖，也会增加错误推断风险；当前选择“不猜”。
4. **字段数据流缺口比 token 匹配更难。** `STR_NEWS_INDUSTRY_CONSTRUCTION` 能找到表行，但 `new_industry_text` 到 `industry_cmd.cpp:1719` 的字段链路没有自动跟到；这类上下文对翻译参数含义很关键，却是当前定位器最弱的部分。
5. **证据排序仍会污染 C。** 该 key 返回了 34 条引用，C 只截取前 4 条；兼容映射已经降权，但字段调用 `industry_cmd.cpp:1719` 仍不在前 4 条。真实实验前应补字段数据流/调用点证据，否则 C 的额外证据仍可能是噪声。
6. **朴素基线较弱。** 它没有 IR、没有语义，只用来证明“全量正则/文本扫描”会在定义行和 computed key 上失败；它不是强 baseline，不能据此夸大实用定位器的优势。
7. **同词不同义样本在代码层是 key 唯一的。** 真正困难的同词歧义发生在“显示文本相同”而非“key 相同”；当前 8 条 same-text 主要验证定义/使用分离和宏槽位，不足以证明模型能靠源码消歧。
8. **无目标语言泄漏，但不是形式化证明。** 白名单、CJK 扫描和测试覆盖了 `src/lang/german.txt` 拒绝、路径逃逸、第三方目录；没有做完整的污点分析。
9. **成本模型未验证。** 没有真实 usage 数据；token 数是预检估算，价格和实际账单可能不同。live 预算只能防止失控，不能保证费用精确。
10. **没有人工评分。** 评分 rubric 已固定，但评分者尚未产生数据；任何“C 更好/更差”的说法都不成立。

## 9. License 与归属

OpenTTD 15.3 以 GPL-2.0 发布；`COPYING.md` 随下载语料提供。本仓库只保存短小的、带 `path:line` 的英文源码引用和统计结果，不分发完整语料。`tests/fixtures/tiny_openttd/` 是专门为单测编写的最小 fixture，不是真实游戏构建产物。
