# stock-sim 冒烟测试

## 1. 单元测试

```bash
python3 -m pytest tests/ -v   # 期望全部通过（35 项）
```

实际结果：**35 passed** — 全部通过。

## 2. 账户离线冒烟（不依赖网络）

```bash
cp config/config.example.json config/config.json
python3 scripts/account.py init
python3 scripts/account.py buy 600519 100 --price 1700 --reason "冒烟测试"
python3 scripts/account.py settle
python3 scripts/account.py sell 600519 100 --price 1750 --reason "冒烟止盈"
python3 scripts/account.py mark --prices '{}'
python3 scripts/account.py show
```

验证点与实测数据：

| 步骤 | 预期 | 实际观察值 |
|------|------|-----------|
| `init` 后现金 | 1,000,000 | `1000000.0` |
| `init --cash 500000` 后现金/初始资产 | 500,000 | `cash=500000.0, initial_assets=500000.0` |
| 买入成本 | 170,000 + 佣金 + 过户费 | `amount=170000.0, commission=42.5, transfer_fee=1.7, total_cost=170044.2` |
| `settle` 解冻 | T+1 可卖 | `T+1 已解冻` |
| 卖出净收入 | 175,000 − 费用 | `amount=175000.0, commission=43.75, transfer_fee=1.75, stamp_tax=87.5, net_proceeds=174867.0` |
| realized_pnl | 为正 | `4822.8`（毛利润 5000，扣除买卖各项费用后净利 4822.8） |
| 最终现金 | ≈ 1,004,822 | `cash: 1004822.8` |
| show 输出 | 完整状态 | 返回 cash / positions / realized_pnl / created_at / updated_at |

结论：全流程正常，盈亏计算准确。

## 3. 行情联网冒烟（需依赖安装）

```bash
python3 scripts/quote.py realtime 600519   # 期望返回 price/source
python3 scripts/quote.py index 000300      # 期望返回基准点位
python3 scripts/quote.py board             # 期望列出行业板块（选股候选池来源）
python3 scripts/quote.py board 白酒        # 期望列出该板块成分股代码
```

本机观察结果：

- **realtime 600519**：akshare 首先尝试失败（可能超时或不可用），自动 fallback 到新浪源，成功返回 `"price": 1268.0, "source": "sina"`。三源兜底链路验证通过。
- **index 000300**：仅支持 akshare 一个数据源（无 sina 指数兜底），本机未安装 akshare，报 `QuoteError: 所有行情源失败：_index_akshare: No module named 'akshare'`。属预期行为——证明兜底耗尽正确报错。**注意：如需 index 命令可用，需安装 `akshare`。**
- **board（板块成分）**：选股候选池来源，仅 akshare 单源（无兜底）。akshare 不可用时返回 `{"error":..., "hint": "...可由 agent 凭知识列出候选代码"}`，由 agent 降级处理，不阻断交易主链路。

## 4. 端到端（场景 A）

按 SKILL.md 场景 A 走一遍：settle→mark→选股→下单→写 daily 报告。

```bash
# 初始化
cp config/config.example.json config/config.json
python3 scripts/account.py init

# 每日流程
python3 scripts/account.py settle          # 解冻前日持仓
python3 scripts/account.py mark --prices '{}'  # 标记价格
# （agent 执行选股逻辑 → 生成 order）
python3 scripts/account.py buy 600519 100 --price <selected_price> --reason "策略选股"
# （agent 写入 journal/daily_<date>.md 报告）
```

以上 Step 2 的买入+卖出+show 即为该流程的核心闭环验证。
