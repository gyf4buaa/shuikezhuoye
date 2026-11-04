# ⚠️ 合成演示工程（SYNTHETIC DEMO PROJECT）

本目录中的“游戏工程”完全是为了**源码感知翻译 PoC** 人工编写的合成示例，
不是任何真实游戏、企业或产品的源码，也不包含任何私有数据。

- 引擎风格：Unity / C#（仅作结构示意，不接入真实引擎，不能编译运行）
- 字符串表：`Assets/Localization/en.json`、`Assets/Localization/ui_strings.csv`
- 演示点：`Rank`、`Claim` 等文本在多个 UI 面板中被引用；
  相同字面文本在不同代码位置承载不同界面语境。

PoC 对本目录**只读**。只有用户显式配置 API Key 并点击“运行对照翻译”时，
才会把选中的字符串与检索到的少量代码片段发送给已配置的模型服务；
没有 API Key 时只做本地检索，不调用任何模型。
