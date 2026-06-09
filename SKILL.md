---
name: stock-sim
version: 1.0.0
description: "模拟炒股 agent：用虚拟 A 股账户盘中定点巡盘、实时价止盈止损与选股建仓、每日报告、周期复盘并迭代策略，行情基于真实数据（三源兜底）"
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
python scripts/quote.py daily 600519 --days 60     # 日线（akshare→tushare→腾讯HTTP兜底）
python scripts/quote.py index 000300               # 沪深300（基准）
python scripts/quote.py board                       # 列出全部行业板块
python scripts/quote.py board 白酒                  # 列出某板块成分股（选股候选池）

# 账户
python scripts/account.py init --cash 1000000       # 开户（初始化，仅首次）
python scripts/account.py show                      # 查账
python scripts/account.py settle                    # T+1 解冻（每个交易日开始调一次）
python scripts/account.py buy 600519 100 --price 1700 --reason "趋势突破"
python scripts/account.py sell 600519 100 --price 1750 --reason "止盈"
python scripts/account.py mark --prices '{"600519":1750.0}'   # 估值快照
```

## 场景 0：开户初始化（首次使用）

当用户说"初始化""开户""第一次用""建账"时，通过对话逐项采集初始信息（每项给默认值、可跳过）：

1. **对话采集**：
   - 初始本金（默认 1000000）
   - 风险偏好：保守 / 稳健 / 激进（默认稳健）
   - 关注板块·行业（可多个，留空=全市场）
   - 运行频率 & 复盘周期（默认 每交易日 / 每周）
   - tushare token（可留空，走 akshare→新浪兜底）
2. **建账**：`python scripts/account.py init --cash <本金>`。
3. **写画像**：把偏好信息按 schema 写入 `profile/profile.json`
   （从 `profile/profile.example.json` 复制后填写，含 created_at/updated_at）。
4. **写 token**（若提供）：`cp config/config.example.json config/config.json`（若尚无），
   填入 `tushare_token`。
5. **画像驱动策略**：依据风险偏好/关注板块微调 `strategy/strategy.md` 的 v1，
   并在"策略演变记录"追加一行，理由写"初始化画像（风险偏好=X，关注=Y）"：
   - 激进：可提高单只仓位上限、放宽量能阈值。
   - 保守：降低单只仓位上限、提高现金保留。
   - 关注板块：选股时优先扫描这些行业。
6. **确认输出**：打印账户摘要（现金/初始本金）+ 画像摘要（风险偏好/关注板块/节奏）。

### profile.json schema

```json
{
  "risk_preference": "稳健",
  "focus_sectors": ["白酒", "新能源"],
  "run_frequency": "每交易日",
  "review_cycle": "每周",
  "notes": "",
  "created_at": "2026-06-04",
  "updated_at": "2026-06-04"
}
```

## 场景 A：盘中定点巡盘交易（交易时段内）

每个交易日在若干**定点巡盘时刻**被触发（如 10:00 / 11:15 / 14:30），每次拉**实时价**做
决策。设计成无状态的「每次巡盘自包含」：先对持仓做止盈止损风控，再用实时信号找建仓机会。
当用户说"巡盘""盘中操作""跑一次""今日交易"时，按下面流程走**当前这一次**巡盘：

1. **解冻 T+1**：`python scripts/account.py settle`（每日首次巡盘必做）。settle 按持仓买入
   日期解冻——只放行昨日及更早的仓，当天买入的仓恒为不可卖，故盘中任意次巡盘重复调用都安全、
   不会造成 T+0。
2. **刷新实时估值**：读 account.json 持仓 → `quote.py realtime <持仓代码...>` 取**实时价** →
   `account.py mark --prices {...}` 得到当前总资产与每只浮盈亏。同时 `quote.py index 000300`
   取基准当前点位。
3. **读策略**：读 `strategy/strategy.md` 的止盈/止损线、量能/趋势阈值、仓位上限。
4. **持仓风控（卖出优先）**：对每只持仓按实时浮盈亏比对策略的止盈/止损线——
   触发止盈线（如 +15% 减半、+25% 清仓）或止损线（如 -8% 清仓）即调 `account.py sell`，
   `--reason` 写清"盘中止盈/止损 @实时价 X，浮盈亏 Y%"。这是盘中操作区别于收盘批量的核心：
   **每次巡盘都先保护已有持仓，再谈进攻。**
5. **实时信号建仓**：仓位/现金有空间时（持仓 <5 只、现金 ≥20%）才找新机会——
   读 `profile/profile.json` 的 `focus_sectors`，对每个关注板块用 `quote.py board <板块名>`
   取成分股（留空则全市场/agent 凭知识列候选）；用 `quote.py daily` 看趋势/均线背景，
   叠加**实时价相对昨收的当日动量**确认买点，再调 `account.py buy`。遵守 A 股规则
   （T+1、100 股整手、单只 ≤20% 总资产、最多 5 只）。board 仅 akshare 单源，失败退回 agent
   自列候选，不阻断交易。
6. **写/更新当日报告**：生成或**覆盖重写** `journal/YYYY-MM-DD-daily.md`（不是追加，
   每次巡盘从当日全部操作投影出完整报告，保证最后一次巡盘后报告即为当日终稿），包含：
   - 各次巡盘时刻与决策（卖出风控动作 + 建仓动作）
   - 资金操作明细（买/卖了什么、实时价、金额、费用）
   - 账户盈亏：总资产、当日盈亏、累计收益率
   - **vs 沪深300**：账户收益率 与 基准同期收益率 并列
7. **追加总账**：每笔成交同步追加到 `journal/record.md`（人读叙事）与
   `journal/operations.jsonl`（结构化：datetime/action/code/price/reason/pnl）。

> 触发方式：agent 非常驻进程，由定时器（cron / 计划任务）在各巡盘时刻拉起跑一次本流程。
> 每次巡盘独立、幂等：不依赖上一轮内存状态，全部真相从 account.json / 实时价重建。

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
- 盘中巡盘以「持仓风控」为先、「建仓」为后；无信号则空仓观望，
  禁止为操作而操作——频繁进出会被手续费/印花税吃掉收益。
