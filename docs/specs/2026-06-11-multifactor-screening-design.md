# stock-sim 多因子选股升级 — 设计文档

日期：2026-06-11
状态：已确认，待进入实现计划

## 1. 背景与问题

现有 v2.1 策略的「选股」本质是 **在 6 个预设板块（`focus_sectors`）内挑技术形态最强的票**，决策依据只有三个量价信号：站上 MA20、放量 1.3 倍、盘中涨幅靠前（见 `strategy/strategy.md` v2.1 与 `SKILL.md` 场景 A 第 5 步）。

这导致三个结构性缺陷：

1. **纯技术面、无基本面** — 没有估值/盈利/业绩过滤，"放量突破"恰是 A 股消息驱动与游资造形态最易出现的位置，系统性追高接盘垃圾股。
2. **候选池静态锁死** — 只扫 `focus_sectors`，板块轮动时强势主线不在列表内就完全看不到。
3. **无横截面比较** — 对每只票孤立判断"它自己涨没涨"，没有"它在全市场排第几"。真正的选股 alpha 来自横截面排序，而非单票时序信号。

更深层的问题：复盘闭环（场景 B）的归因维度只有"alpha vs beta"，不引导补充新信号维度，**闭环只会在现有窄维度里自我优化，养不出新能力**。

## 2. 目标

把选股从「板块内挑技术形态」升级为 **全市场多因子分层漏斗打分模型**，补齐四个维度：基本面质量、横截面相对强弱、资金面/情绪面、动态候选池。

**非目标（YAGNI）**：
- 不做盘口/滑点模拟（成交价仍取 `quote.py realtime` 最新价）。
- 不做机器学习因子挖掘（因子人工定义，agent 复盘调参）。
- 不替换风控体系（v2.1 止盈止损/急跌减仓/仓位上限/尾盘纪律全部保留）。
- 不改 `account.py` / `trade_rules.py`（交易与成本计算保持不动）。

## 3. 已确认的核心决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 融合架构 | 分层过滤 + 打分漏斗 | 基本面硬过滤一票否决，不被技术高分掩盖；每层可独立调试 |
| 数据获取 | 盘前批量缓存，盘中只读 | `daily_basic` 限速 1 次/小时，盘前一次拉全市场写缓存 |
| 候选池口径 | 全市场强势扫描（涨幅+量比+换手）取 Top100 | 打破板块锁死，纯数据驱动 |
| 与 v2.1 关系 | 替换选股逻辑，保留全部风控 | 复用已被实战验证的风控，只换"选什么" |
| 打分逻辑位置 | 新建 `scripts/screen.py` | 数据管道+打分引擎沉淀为可测代码，不靠 agent 手算 |
| 因子参数 | 外置 `strategy/factors.json`（机器可读） | screen.py 读它执行，agent 复盘改它——让闭环能真正调整选股行为 |

### 3.1 关键设计决策：因子参数外置

打分逻辑在代码（`screen.py`），但因子的开关/阈值/权重属于「策略大脑」、应由 agent 复盘迭代。若硬编码进脚本，复盘就改不动选股行为——正是"闭环养不出能力"的根因。

因此：
- **`strategy/factors.json`**（新增，机器可读）持有所有因子的开关、阈值、权重。
- **`screen.py`** 读 `factors.json` 执行打分，自身不含魔法数字。
- **`strategy/strategy.md`** 仍是人读的策略叙事 + 风控规则 + 演变记录，文字描述当前 factors.json 的取值与理由。
- 复盘时 agent 同时改 `factors.json`（机器执行的参数）与 `strategy.md`（人读的理由+证据），二者一致。

## 4. 数据源能力边界（已实测）

实测当前 tushare token 与 akshare 的可用性，确定每层因子的稳定数据源：

| 因子层 | 数据源 | 接口 | 状态 / 约束 |
|--------|--------|------|------|
| 估值/换手/量比/市值 | tushare | `daily_basic`（trade_date 全市场一次拉） | ✅ 可用，**限速 1 次/小时** → 盘前缓存 |
| 基本面质量(ROE/净利增速) | akshare | `stock_financial_abstract(symbol)` | ✅ 可用，逐票拉，需缓存 |
| 北向持股 | tushare | `hk_hold(ts_code)` | ✅ 可用，逐票 |
| 龙虎榜 | akshare | `stock_lhb_detail_em(start,end)` | ✅ 可用，一次拉全市场当日 |
| 个股/板块实时资金流 | akshare(东财) | `stock_individual_fund_flow` 等 | ⚠️ 反爬不稳，**降级**：用龙虎榜+北向持股作资金面代理 |
| 全市场快照(涨幅/PE) | tushare `daily_basic` | — | ✅ 作为东财快照失败时的兜底主源 |

**硬约束**：
- tushare `fina_indicator` / `moneyflow` / `moneyflow_hsgt` / `top_list` 当前 token **无权限**。基本面走 akshare `stock_financial_abstract`，资金面走龙虎榜+北向持股。
- `daily_basic` **1 次/小时**：决定了全市场估值快照只能盘前拉一次缓存，盘中复用。这与"盘前批量缓存"方案天然契合。

## 5. 架构

```
┌──────────────────────────────────────────────────────────────────┐
│  盘前一次 (cron, 约 09:00):  python scripts/screen.py prepare       │
│  ├─ tushare daily_basic 全市场快照 → cache/market_snapshot.json    │
│  │    (含 PE_TTM/PB/换手/量比/总市值/流通市值, 5000+ 只)            │
│  ├─ akshare 当日龙虎榜 → 并入快照 (资金面: 是否上榜/净买额)         │
│  └─ (rank 阶段对入选候选再增量拉 ROE/北向, 写 cache/fundamental.json)│
└──────────────────────────────────────────────────────────────────┘
                          ↓  盘中只读缓存 + 实时价, 毫秒级
┌──────────────────────────────────────────────────────────────────┐
│  盘中每巡盘:  python scripts/screen.py rank [--top N]               │
│   L0 动态候选池: 全市场快照按 (涨幅 + 量比 + 换手) 复合强势 → Top100 │
│   L1 基本面硬过滤(一票否决): 剔除亏损/ROE过低/PE_TTM过高或为负/ST   │
│   L2 多因子打分: 技术(趋势+动量) + 资金(龙虎榜+北向) + 横截面相对强弱│
│        各因子 z-score 标准化后按 factors.json 权重加权              │
│   L3 输出 Top-N 候选 JSON: 每只含总分 + 分项得分 + 过滤通过标记      │
└──────────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────────┐
│  agent (SKILL 场景 A 第 5 步改写):                                  │
│   读 screen rank 输出 → 对 Top 候选用 quote.py daily 复核趋势       │
│   → 过 v2.1 开仓铁门槛(现价≥MA20 且 MA20 向上) → account.py buy     │
│   风控全部保留: 止盈止损/急跌减仓/仓位上限/主线分散/尾盘纪律        │
└──────────────────────────────────────────────────────────────────┘
```

### 5.1 组件职责

| 组件 | 类型 | 职责 | 是否新增 |
|------|------|------|---------|
| `scripts/screen.py` | 代码 | 数据管道(prepare) + 分层漏斗打分(rank)，输出候选 JSON | 新增 |
| `strategy/factors.json` | 配置 | 因子开关/阈值/权重，机器可读 | 新增 |
| `cache/market_snapshot.json` | 缓存 | 盘前全市场估值+资金面快照（当日，不入 git） | 新增 |
| `cache/fundamental.json` | 缓存 | 候选股 ROE/北向 增量缓存（TTL 数日，不入 git） | 新增 |
| `scripts/quote.py` | 代码 | 行情接口，**复用**（screen.py 内部复用其数据源函数） | 不动 |
| `scripts/account.py` | 代码 | 账户与成交 | 不动 |
| `scripts/trade_rules.py` | 代码 | 成本/规则计算 | 不动 |
| `strategy/strategy.md` | 文档 | 策略叙事+风控+演变记录，引用 factors.json | 改写选股段 |
| `SKILL.md` | 文档 | 场景 A 第 5 步、场景 B、场景 D 更新 | 改写 |

## 6. 分层漏斗细节

### L0 动态候选池（全市场强势扫描）

输入：`cache/market_snapshot.json`。复合强势分 = 标准化后的 `当日涨幅 + 量比 + 换手率`。
排除：停牌、ST（名称含 ST/*ST）、量比或换手缺失。取强势分 Top100 进入 L1。

> 当日涨幅来源：snapshot 缺实时涨幅时，rank 阶段对候选用 `quote.py realtime` 取最新价 vs 昨收补齐（仅 Top100，不拉全市场）。

### L1 基本面硬过滤（一票否决）

对 L0 候选，从 `cache/fundamental.json`（缺失则增量拉 akshare 财务摘要）取最新 ROE 与净利润，按 factors.json 阈值剔除：

- ROE < `min_roe`（默认 0，即剔除亏损/极低 ROE）
- 最新报告期净利润为负
- `pe_ttm` > `max_pe_ttm`（默认 150）或 `pe_ttm` <= 0（亏损/异常）
- ST / *ST（名称匹配）

任一命中即出局，**不进入打分**。这是杜绝"追高接盘基本面垃圾股"的核心闸门。数据缺失的处理见 §8。

### L2 多因子打分

对通过 L1 的候选，计算各因子原始值 → 全候选集内 z-score 标准化 → 按 factors.json 权重加权求和：

| 因子组 | 因子 | 原始值来源 | 方向 |
|--------|------|-----------|------|
| 技术 | 趋势(现价/MA20 - 1) | quote.py daily | 越高越好 |
| 技术 | 动量(近 5 日涨幅) | quote.py daily | 越高越好 |
| 资金 | 龙虎榜净买额 | snapshot(akshare 龙虎榜) | 越高越好；未上榜=0 |
| 资金 | 北向持股比例 | tushare hk_hold | 越高越好；缺失=0 |
| 横截面 | 板块内相对强弱排名 | 候选所属行业内涨幅分位 | 越高越好 |
| 估值 | 估值分位(PE_TTM 反向) | snapshot | 越低 PE 越好（反向计分） |

权重在 factors.json 按 6 个细分因子定义，初始默认见 §7（技术组 trend 0.20+momentum 0.15、资金组 lhb 0.15+northbound 0.10、横截面 rel_strength 0.25、估值 valuation 0.15，合计 1.0），复盘迭代。

### L3 输出

按总分降序输出 Top-N（默认 N=10），JSON 每条含：`code, name, total_score, scores{trend,momentum,lhb,northbound,rel_strength,valuation}, passed_filters, sector`。agent 据此挑选并复核，**仍须过 v2.1 开仓铁门槛**后才下单。

## 7. factors.json schema

```json
{
  "version": "v3.0",
  "updated_at": "2026-06-11",
  "candidate_pool": {
    "size": 100,
    "strength_factors": ["pct_change", "volume_ratio", "turnover_rate"],
    "exclude_st": true
  },
  "hard_filters": {
    "min_roe": 0.0,
    "max_pe_ttm": 150.0,
    "require_positive_profit": true,
    "exclude_st": true
  },
  "score_weights": {
    "trend": 0.20,
    "momentum": 0.15,
    "lhb_netbuy": 0.15,
    "northbound": 0.10,
    "rel_strength": 0.25,
    "valuation": 0.15
  },
  "output": { "top_n": 10 }
}
```

权重之和不强制为 1（z-score 加权对绝对量纲不敏感），但文档建议维持归一以便复盘解读。

## 8. 错误处理与降级

遵循 quote.py 既有的"多源兜底、容错优先"风格：

- **daily_basic 限速命中**：prepare 已写当日 snapshot 则直接复用；无当日 snapshot 时回退用 akshare 全市场快照（`stock_zh_a_spot_em`）兜底，仍失败则 rank 报明确错误提示 agent 改用 `quote.py board` 旧路径，**不阻断交易**。
- **基本面缺失**（财务摘要拉取失败/无数据）：该票 L1 标记 `fundamental_unknown=true`，按 factors.json 的 `on_missing` 策略处理——默认 **保守剔除**（缺数据不进打分），避免盲买。
- **资金面缺失**（未上龙虎榜/北向无数据）：对应因子计 0 分，不剔除（缺席≠负面）。
- **akshare 东财系反爬**：复用 quote.py 已有的 cffi 兜底；个股资金流本就降级，不依赖。
- 所有网络异常 catch 后记入输出 JSON 的 `warnings` 数组，agent 可见但不崩溃。

## 9. 测试策略

`tests/` 已有 pytest 结构。新增 `tests/test_screen.py`，**纯函数与 IO 分离**，对打分/过滤逻辑做单测（不依赖网络）：

- L0 强势分排序：构造 mock snapshot，验证 Top100 顺序与 ST 排除。
- L1 硬过滤：构造边界样例（ROE 恰为 0、PE_TTM 为负、净利负、ST 名称），逐条验证一票否决。
- L2 打分：构造已知 z-score 输入，验证加权求和与方向（估值反向、缺失计 0）。
- factors.json 解析：缺字段时用默认值、权重读取正确。
- 降级路径：mock daily_basic 抛限速异常，验证回退到 akshare 快照。

数据拉取函数（prepare 的网络部分）用真实接口做一次性冒烟验证，写入 `docs/smoke-test.md`，不进 pytest（避免 CI 依赖外网）。

## 10. SKILL.md 改动点

- **场景 A 第 5 步**：把"读 focus_sectors → board 候选池 → 技术形态"改为"读 `screen.py rank` 输出的 Top 候选 → quote.py daily 复核 → 过铁门槛 → buy"。保留风控相关的第 4 步（卖出优先）与第 6/7 步（报告/总账）。
- **场景 B 复盘**：归因维度从"alpha vs beta"扩展为"哪些因子有效/失效"，复盘产出同时更新 `factors.json` 权重/阈值 + `strategy.md` 演变记录（理由+证据）。
- **场景 D**：新增 prepare 的盘前调度说明（每交易日 09:00 跑一次 `screen.py prepare`），与 board-refresh 并列。
- **纪律段**：新增一条"选股先过基本面硬过滤，宁可错过不可买垃圾"。

## 11. 影响范围与风险

- **影响文件**：新增 `screen.py`、`factors.json`、`tests/test_screen.py`；改写 `strategy.md` 选股段、`SKILL.md` 场景 A/B/D；缓存文件加入 .gitignore。`account.py`/`quote.py`/`trade_rules.py` 不动。
- **风险 1**：daily_basic 限速。已通过盘前缓存 + akshare 兜底化解；最坏情况退回 board 旧路径，不阻断。
- **风险 2**：akshare 财务摘要逐票拉慢。仅对 L0 Top100 的入选候选增量拉并缓存，单次巡盘只拉新增票。
- **风险 3**：因子权重初值不一定好。这正是复盘闭环要解决的——首版给合理默认，靠 factors.json 迭代。
- **回溯兼容**：v2.1 风控与 account.py 不变，新模型只替换"选什么"，可随时通过 factors.json 关闭某因子回退到接近原行为。
```
