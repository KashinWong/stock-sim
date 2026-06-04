---
name: stock-sim
version: 1.0.0
description: "模拟炒股 agent：用虚拟 A 股账户自主选股交易、每日报告、周期复盘并迭代策略，行情基于真实数据（三源兜底）"
---

# 模拟炒股 Skill（stock-sim）

给 agent 一个虚拟 A 股账户进行模拟买卖。所有状态以文件持久化，行情基于真实数据。
首次使用前请按 `README.md` 完成部署（装依赖、配 token、`account.py init`）。

## 关键文件

- `account/account.json`：账户唯一真相源（现金/持仓/盈亏）。**只通过 account.py 修改**。
- `account/trades.jsonl`：逐笔成交明细（只追加）。
- `strategy/strategy.md`：选股策略（agent 复盘时迭代）。
- `journal/`：每日报告、复盘、操作总账。

## 工具命令

```bash
# 行情（三源兜底）
python scripts/quote.py realtime 600519 000001    # 批量实时价
python scripts/quote.py daily 600519 --days 60     # 日线
python scripts/quote.py index 000300               # 沪深300（基准）

# 账户
python scripts/account.py show                      # 查账
python scripts/account.py settle                    # T+1 解冻（每个交易日开始调一次）
python scripts/account.py buy 600519 100 --price 1700 --reason "趋势突破"
python scripts/account.py sell 600519 100 --price 1750 --reason "止盈"
python scripts/account.py mark --prices '{"600519":1750.0}'   # 估值快照
```

## 场景 A：每日选股交易（收盘后）

当用户说"今日交易""跑一次""开盘选股"时：

1. **解冻 T+1**：`python scripts/account.py settle`
2. **刷新估值**：读 account.json 持仓 → `quote.py realtime <持仓代码...>` 取价 →
   `account.py mark --prices {...}` 得到当前总资产。同时 `quote.py index 000300` 取基准。
3. **读策略**：读 `strategy/strategy.md` 的当前选股逻辑。
4. **选股**：按策略扫描候选（用 `quote.py daily` 验证均线/量能信号），输出选股思路。
5. **下单**：对买卖决策调 `account.py buy/sell`，`--reason` 写清理由。遵守 A 股规则
   （T+1、100 股整手、单只 ≤20% 总资产、最多 5 只持仓）。
6. **写报告**：生成 `journal/YYYY-MM-DD-daily.md`，包含：
   - 今日选股思路与决策依据
   - 资金操作（买/卖了什么、金额、费用）
   - 账户盈亏：总资产、当日盈亏、累计收益率
   - **vs 沪深300**：账户收益率 与 基准同期收益率 并列
7. **追加总账**：同步追加到 `journal/record.md`（人读叙事）与
   `journal/operations.jsonl`（结构化：date/action/code/reason/pnl）。

## 场景 B：复盘改进策略（周期性，如每周/月底）

当用户说"复盘""改进策略""周度总结"时：

1. **统计**：读近期 trades.jsonl 与 daily 报告，算胜率、盈亏比、**超额收益（vs 基准）**。
2. **归因**：跑赢/跑输是选股 alpha 还是大盘 beta？哪些交易验证或证伪了策略假设？
3. **改策略**：编辑 `strategy/strategy.md`，每处改动在"策略演变记录"表追加一行，
   写明【理由 + 证据（基于哪几笔交易）】。禁止凭感觉改、禁止追逐单次噪声。
4. **写复盘**：生成 `journal/YYYY-MM-DD-review.md`，含统计、归因、策略调整说明。

## 场景 C：查账（随时）

当用户说"查账""看账户""现在多少钱"时：

1. `account.py show` 读状态 → `quote.py realtime <持仓...>` 取价 → `account.py mark`。
2. 输出：总资产、持仓明细（成本/现价/浮盈亏）、累计收益率 vs 基准、近期操作摘要。

## 纪律（防自欺）

- 账户收益必须始终与沪深300基准对比，区分能力与运气。
- 策略改动必须有交易证据支撑。
- 所有成交只走 account.py，不手改 account.json。
- 模拟价格用真实行情，不臆造。
