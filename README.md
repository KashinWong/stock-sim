# stock-sim — 模拟炒股 Agent Skill

给 agent 一个虚拟 A 股账户进行模拟买卖：自主选股、每日报告、周期复盘、迭代策略。
所有状态以文件持久化，行情基于真实数据（三源兜底）。

## 部署（目标环境 agent 自举）

1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```

2. 准备配置：
   ```bash
   cp config/config.example.json config/config.json
   ```
   编辑 `config/config.json`，填入 `tushare_token`（在 https://tushare.pro 注册免费获取；
   留空则跳过 Tushare，仅用 AKShare + 新浪兜底）。其余字段可用默认值。

3. 初始化账户：
   ```bash
   python scripts/account.py init
   ```

4. 验证行情通畅：
   ```bash
   python scripts/quote.py realtime 600519
   ```
   能返回价格 JSON 即部署成功。

## 目录约定

- `account/account.json`：账户唯一真相源（现金/持仓/盈亏）
- `account/trades.jsonl`：逐笔成交明细（只追加）
- `strategy/strategy.md`：自然语言策略文档（agent 自迭代）
- `journal/`：每日报告、复盘、操作总账

详细工作流见 `SKILL.md`。
