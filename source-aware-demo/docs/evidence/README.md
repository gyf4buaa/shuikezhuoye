# 视觉证据说明

## Before / After 对照

| 文件 | 版本 / 状态 | 视口 | 说明 |
| --- | --- | --- | --- |
| `before-main.png` | `main@370dd03`（本 PR 的基线） | 1440×1200 | 实际 GitHub 仓库页面：只有 README，没有任何应用界面 |
| `after-overview.png` | 本 PR 运行版本，无 API Key | 1440×1200 | 真实应用：选中 `ui.leaderboard.rank_column`，6 条检索证据，黄色“未调用模型”提示 |
| `after-compare-offline.png` | 同上，滚动到对照区 | 1440×1200 | 按钮禁用，两张结果卡写“未调用模型，因此没有译文” |
| `after-full.png` | 同上，整页 | 1440×2748 | 完整页面，包括底部边界说明 |
| `after-mobile.png` | 同上，移动视口 | 390×844（截图 780×1688 @2x） | 单列布局，无横向滚动 |

## 状态与主题

- **主题**：浅色（米白/淡蓝背景 + 深蓝顶栏 + 青色强调），与稳定版原型保持一致的视觉语言。
- **场景**：同一合成演示工程、同一 Key（`ui.leaderboard.rank_column`）、同一目标语言（`pt-BR`）、同一无 Key 状态。
- **Before 的诚实说明**：这是 greenfield 仓库，`main@370dd03` 上没有旧版源码感知 UI。Before 是**实际基线仓库状态**，不是伪造的旧应用截图；不存在可对比的旧界面。
- **没有 live 译文截图**：构建时没有可用的 API Key，因此没有真实模型结果可展示。页面严格标明“未调用模型”，没有用示意图/伪译文替代。live 分支由注入 fake transport 的自动化测试覆盖（见 `docs/测试报告.md`），不构成真实模型质量证据。

## 采集方式

- 浏览器：Google Chrome 156.0.8078.80，headless，设备像素比 1（桌面）/ 2（移动）。
- 桌面截图通过 CDP `Emulation.setDeviceMetricsOverride` 固定为 1440×1200；Before 与 After 使用同一视口。
- 同一渲染实例中读取 DOM：6 张证据卡、首条 `Assets/Scripts/UI/LeaderboardPanel.cs:17`、无横向溢出；After 截图不是静态 mockup。
- 截图在应用真实运行、API 实际返回检索结果后采集。
