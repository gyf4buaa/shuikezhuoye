# 截图证据说明

这些截图用于 PR 的 Before/After 对比。它们不是 mockup：Before 是实际 GitHub 仓库页，After 是实际运行中的本地应用。

| 文件 | 状态 | 说明 |
|---|---|---|
| `before-main.png` | Before（main@370dd03） | 公开仓库当时的实际页面：只有一个 README，没有任何应用界面。 |
| `after-overview.png` | After | 运行中的预检台，中→葡合成演示 28 条结果、6 张汇总卡。1440×1200。 |
| `after-overflow.png` | After | `settings.tab.settings`：`Configurações` 实测 100px / 内容区 98px，超出 2.0px；含 Pillow/浏览器交叉检查与测量假设。 |
| `after-abstain.png` | After | 英→葡 `misc.rank_unknown`：`Rank` 无上下文，证据不足弃答，三个候选均为 0 分。 |
| `after-icu.png` | After | 中→俄 `inventory.items.count`：缺 `other` 分类；ICU 模板返回 `OVF000` 不测量。 |
| `after-source-gap.png` | After | 中→葡 `dialogue.next_level`：中文主语省略等源文缺口，输出需要人工补充的问题。 |
| `after-mobile.png` | After | 390×844 视口；`scrollWidth == innerWidth`，无横向滚动。 |

## 限制

- 这是 greenfield：main 上从来没有旧版应用，所以 Before 只能是“实际仓库初始状态”，不能伪造旧版 UI。PR 描述中已明确说明。
- 截图没有做逐像素视觉回归；界面验证通过 Chrome DevTools Protocol 读取实际 DOM、字体加载状态和布局数值，截图作为可见证据。
- 截图为 2026-11-04 的实际运行结果；示例项目/文案/UI 尺寸均为合成数据。
- 浏览器测量仍不是游戏引擎布局验证；详见 README 与测试报告。
