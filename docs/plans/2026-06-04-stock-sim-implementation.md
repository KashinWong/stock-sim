# stock-sim 模拟炒股 Agent Skill 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个可移植的 Claude/hermes skill，给 agent 一个虚拟 A 股账户进行模拟买卖，自主迭代选股策略、每日报告、周期复盘，并能在陌生环境中由 agent 自举安装。

**Architecture:** 三个职责单一的 Python 脚本（`trade_rules` 纯规则计算 / `account` 账户引擎 / `quote` 三源兜底行情）通过 CLI 暴露给 agent，状态以 JSON+JSONL+Markdown 文件持久化；`SKILL.md` 定义三个场景工作流，`README.md` 让目标环境自举安装。

**Tech Stack:** Python 3.9（无 3.10+ 语法）、akshare/tushare/requests（行情三源）、pandas、pytest（TDD）、json/jsonl/markdown（持久化）。

---

## 文件结构

```
stock-sim/
├── README.md                   # 部署/安装说明（让 hermes 自举）— Task 1, Task 7
├── requirements.txt            # 依赖清单 — Task 1
├── SKILL.md                    # skill 主文件，三场景工作流 — Task 6
├── config/
│   └── config.example.json     # 配置模板（tushare token、初始资金、费率）— Task 1
├── scripts/
│   ├── trade_rules.py          # A 股交易规则：费用/整手/涨跌停（纯函数）— Task 2
│   ├── account.py              # 账户引擎：init/show/buy/sell/settle/mark — Task 3
│   └── quote.py                # 三源兜底行情 CLI：realtime/daily/index — Task 4
├── strategy/
│   └── strategy.md             # 初始策略模板 — Task 5
├── tests/
│   ├── test_trade_rules.py     # Task 2
│   ├── test_account.py         # Task 3
│   └── test_quote.py           # Task 4
├── account/                    # 运行时生成（.gitignore）
├── journal/                    # 运行时生成（.gitignore）
└── docs/specs/                 # 已有 spec
```

职责边界：
- **trade_rules.py**：纯函数，无 IO。买入成本、卖出净收益、费用明细、整手校验、涨跌停校验。最易测。
- **account.py**：账户状态机。读写 `account.json`，追加 `trades.jsonl`，执行成交（调 trade_rules），T+1 冻结/解冻，估值。不依赖 quote（价格由 agent 传入），保持低耦合、可测。
- **quote.py**：行情获取。三源按序兜底（akshare→tushare→新浪 HTTP），统一 JSON 输出。

---

## Task 1: 项目骨架（依赖、配置模板、README 初版）

**Files:**
- Create: `requirements.txt`
- Create: `config/config.example.json`
- Create: `README.md`
- Modify: `.gitignore`（已存在，追加 config.json）

- [ ] **Step 1: 写 requirements.txt**

```
akshare>=1.12.0
tushare>=1.2.89
pandas>=1.3.0
requests>=2.28.0
pytest>=7.0.0
```

- [ ] **Step 2: 写 config/config.example.json**

```json
{
  "initial_cash": 1000000,
  "tushare_token": "",
  "fees": {
    "commission_rate": 0.00025,
    "commission_min": 5.0,
    "stamp_tax_rate": 0.0005,
    "transfer_fee_rate": 0.00001
  },
  "benchmark_index": "000300",
  "price_limit": {
    "main": 0.10,
    "st": 0.05,
    "star": 0.20
  }
}
```

- [ ] **Step 3: 追加 .gitignore（保护真实 config）**

在现有 `.gitignore` 末尾追加：

```
config/config.json
```

- [ ] **Step 4: 写 README.md 初版（自举安装说明）**

```markdown
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
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt config/config.example.json README.md .gitignore
git commit -m "chore: 项目骨架——依赖、配置模板、自举安装 README"
```

---

## Task 2: trade_rules.py — A 股交易规则（纯函数，TDD）

**Files:**
- Create: `scripts/trade_rules.py`
- Test: `tests/test_trade_rules.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_trade_rules.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import trade_rules as tr

FEES = {
    "commission_rate": 0.00025,
    "commission_min": 5.0,
    "stamp_tax_rate": 0.0005,
    "transfer_fee_rate": 0.00001,
}

def test_buy_cost_includes_commission_and_transfer_fee():
    # 100 股 * 10 元 = 1000 元市值
    # 佣金 = max(1000*0.00025, 5) = 5；过户费 = 1000*0.00001 = 0.01；买入无印花税
    r = tr.buy_cost(price=10.0, qty=100, fees=FEES)
    assert r["amount"] == 1000.0
    assert r["commission"] == 5.0
    assert r["transfer_fee"] == 0.01
    assert r["stamp_tax"] == 0.0
    assert r["total_cost"] == 1005.01

def test_sell_proceeds_includes_stamp_tax():
    # 100 股 * 10 元 = 1000；佣金 max(0.25,5)=5；印花税 1000*0.0005=0.5；过户费 0.01
    r = tr.sell_proceeds(price=10.0, qty=100, fees=FEES)
    assert r["amount"] == 1000.0
    assert r["commission"] == 5.0
    assert r["stamp_tax"] == 0.5
    assert r["transfer_fee"] == 0.01
    assert r["net_proceeds"] == 994.49

def test_validate_lot_rejects_non_round_lot():
    assert tr.is_valid_lot(100) is True
    assert tr.is_valid_lot(150) is False
    assert tr.is_valid_lot(0) is False

def test_within_price_limit():
    # 昨收 10，主板 ±10% → [9.0, 11.0]
    assert tr.within_price_limit(10.5, prev_close=10.0, limit_rate=0.10) is True
    assert tr.within_price_limit(11.5, prev_close=10.0, limit_rate=0.10) is False
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /Users/hjx/projects/stock-sim && python3 -m pytest tests/test_trade_rules.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'trade_rules'`

- [ ] **Step 3: 实现 trade_rules.py**

```python
# scripts/trade_rules.py
"""A 股交易规则：费用计算、整手校验、涨跌停校验。纯函数，无 IO。"""


def _round2(x):
    return round(x + 1e-9, 2)


def buy_cost(price, qty, fees):
    amount = _round2(price * qty)
    commission = _round2(max(amount * fees["commission_rate"], fees["commission_min"]))
    transfer_fee = _round2(amount * fees["transfer_fee_rate"])
    stamp_tax = 0.0
    total_cost = _round2(amount + commission + transfer_fee)
    return {
        "amount": amount,
        "commission": commission,
        "transfer_fee": transfer_fee,
        "stamp_tax": stamp_tax,
        "total_cost": total_cost,
    }


def sell_proceeds(price, qty, fees):
    amount = _round2(price * qty)
    commission = _round2(max(amount * fees["commission_rate"], fees["commission_min"]))
    transfer_fee = _round2(amount * fees["transfer_fee_rate"])
    stamp_tax = _round2(amount * fees["stamp_tax_rate"])
    net_proceeds = _round2(amount - commission - transfer_fee - stamp_tax)
    return {
        "amount": amount,
        "commission": commission,
        "transfer_fee": transfer_fee,
        "stamp_tax": stamp_tax,
        "net_proceeds": net_proceeds,
    }


def is_valid_lot(qty):
    return isinstance(qty, int) and qty >= 100 and qty % 100 == 0


def within_price_limit(price, prev_close, limit_rate):
    high = prev_close * (1 + limit_rate)
    low = prev_close * (1 - limit_rate)
    return low - 1e-9 <= price <= high + 1e-9
```

- [ ] **Step 4: 运行确认通过**

Run: `cd /Users/hjx/projects/stock-sim && python3 -m pytest tests/test_trade_rules.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add scripts/trade_rules.py tests/test_trade_rules.py
git commit -m "feat: A 股交易规则——费用计算、整手与涨跌停校验"
```

---

## Task 3: account.py — 账户引擎（TDD）

**Files:**
- Create: `scripts/account.py`
- Test: `tests/test_account.py`

账户状态模型（account.json）：
```json
{
  "cash": 994994.99,
  "positions": {
    "600519": {"qty": 100, "available": 0, "cost": 1700.0}
  },
  "realized_pnl": 0.0,
  "created_at": "2026-06-04",
  "updated_at": "2026-06-04"
}
```
- `qty`：总持仓；`available`：可卖（T+1）。买入进 qty，available 不变（当日冻结）；`settle` 把 available 同步为 qty（次日解冻）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_account.py
import sys, os, json, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import account as acc

FEES = {"commission_rate": 0.00025, "commission_min": 5.0,
        "stamp_tax_rate": 0.0005, "transfer_fee_rate": 0.00001}


def make_engine(tmp):
    acct_path = os.path.join(tmp, "account.json")
    trades_path = os.path.join(tmp, "trades.jsonl")
    return acc.Account(acct_path, trades_path, fees=FEES)


def test_init_sets_cash():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000000, date="2026-06-04")
        assert e.state["cash"] == 1000000
        assert e.state["positions"] == {}
    finally:
        shutil.rmtree(tmp)


def test_buy_deducts_cash_and_freezes_position():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000000, date="2026-06-04")
        e.buy("600519", qty=100, price=10.0, date="2026-06-04", reason="测试买入")
        # 总成本 1005.01
        assert e.state["cash"] == 994994.99
        pos = e.state["positions"]["600519"]
        assert pos["qty"] == 100
        assert pos["available"] == 0  # T+1 当日冻结
    finally:
        shutil.rmtree(tmp)


def test_buy_rejects_insufficient_cash():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000, date="2026-06-04")
        try:
            e.buy("600519", qty=100, price=100.0, date="2026-06-04", reason="超买")
            assert False, "应抛出资金不足"
        except acc.TradeError:
            pass
    finally:
        shutil.rmtree(tmp)


def test_settle_unfreezes_position():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000000, date="2026-06-04")
        e.buy("600519", qty=100, price=10.0, date="2026-06-04", reason="买")
        e.settle(date="2026-06-05")
        assert e.state["positions"]["600519"]["available"] == 100
    finally:
        shutil.rmtree(tmp)


def test_sell_rejects_when_not_settled():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000000, date="2026-06-04")
        e.buy("600519", qty=100, price=10.0, date="2026-06-04", reason="买")
        try:
            e.sell("600519", qty=100, price=11.0, date="2026-06-04", reason="当日卖")
            assert False, "T+1 当日不可卖"
        except acc.TradeError:
            pass
    finally:
        shutil.rmtree(tmp)


def test_sell_adds_cash_and_realizes_pnl():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000000, date="2026-06-04")
        e.buy("600519", qty=100, price=10.0, date="2026-06-04", reason="买")
        e.settle(date="2026-06-05")
        e.sell("600519", qty=100, price=12.0, date="2026-06-05", reason="卖")
        assert "600519" not in e.state["positions"]
        assert e.state["realized_pnl"] > 0
    finally:
        shutil.rmtree(tmp)


def test_trades_are_appended():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000000, date="2026-06-04")
        e.buy("600519", qty=100, price=10.0, date="2026-06-04", reason="买")
        with open(os.path.join(tmp, "trades.jsonl")) as f:
            lines = f.readlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["code"] == "600519"
        assert rec["side"] == "buy"
    finally:
        shutil.rmtree(tmp)


def test_mark_computes_market_value():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000000, date="2026-06-04")
        e.buy("600519", qty=100, price=10.0, date="2026-06-04", reason="买")
        snap = e.mark(prices={"600519": 12.0})
        # 持仓市值 1200 + 现金 998994.99
        assert snap["market_value"] == 1200.0
        assert abs(snap["total_assets"] - (998994.99 + 1200.0)) < 0.01
    finally:
        shutil.rmtree(tmp)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /Users/hjx/projects/stock-sim && python3 -m pytest tests/test_account.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'account'`

- [ ] **Step 3: 实现 account.py**

```python
# scripts/account.py
"""账户引擎：init/show/buy/sell/settle/mark。account.json 为唯一真相源。"""
import sys, os, json, argparse, time

sys.path.insert(0, os.path.dirname(__file__))
import trade_rules as tr


class TradeError(Exception):
    pass


def _today():
    return time.strftime("%Y-%m-%d")


def _load_config():
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.json")
    if not os.path.exists(cfg_path):
        cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.example.json")
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f)


class Account:
    def __init__(self, account_path, trades_path, fees):
        self.account_path = account_path
        self.trades_path = trades_path
        self.fees = fees
        self.state = None
        if os.path.exists(account_path):
            self._load()

    def _load(self):
        with open(self.account_path, encoding="utf-8") as f:
            self.state = json.load(f)

    def _save(self):
        os.makedirs(os.path.dirname(self.account_path), exist_ok=True)
        self.state["updated_at"] = _today()
        with open(self.account_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def _append_trade(self, rec):
        os.makedirs(os.path.dirname(self.trades_path), exist_ok=True)
        with open(self.trades_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def init(self, initial_cash, date=None):
        date = date or _today()
        self.state = {
            "cash": float(initial_cash),
            "positions": {},
            "realized_pnl": 0.0,
            "created_at": date,
            "updated_at": date,
        }
        self._save()

    def buy(self, code, qty, price, date=None, reason=""):
        date = date or _today()
        if not tr.is_valid_lot(qty):
            raise TradeError("买入数量必须为 100 股整数倍：%s" % qty)
        c = tr.buy_cost(price, qty, self.fees)
        if c["total_cost"] > self.state["cash"] + 1e-6:
            raise TradeError("资金不足：需 %.2f，现金 %.2f" % (c["total_cost"], self.state["cash"]))
        self.state["cash"] = round(self.state["cash"] - c["total_cost"], 2)
        pos = self.state["positions"].get(code)
        if pos:
            new_qty = pos["qty"] + qty
            pos["cost"] = round((pos["cost"] * pos["qty"] + c["total_cost"]) / new_qty, 4)
            pos["qty"] = new_qty
        else:
            self.state["positions"][code] = {
                "qty": qty, "available": 0, "cost": round(c["total_cost"] / qty, 4)
            }
        self._save()
        self._append_trade({
            "date": date, "code": code, "side": "buy", "qty": qty, "price": price,
            "amount": c["amount"], "fees": c["commission"] + c["transfer_fee"],
            "reason": reason, "ts": int(time.time() * 1000),
        })
        return c

    def sell(self, code, qty, price, date=None, reason=""):
        date = date or _today()
        pos = self.state["positions"].get(code)
        if not pos:
            raise TradeError("无持仓：%s" % code)
        if qty > pos["available"]:
            raise TradeError("可卖不足（T+1）：可卖 %s，欲卖 %s" % (pos["available"], qty))
        r = tr.sell_proceeds(price, qty, self.fees)
        cost_part = round(pos["cost"] * qty, 2)
        realized = round(r["net_proceeds"] - cost_part, 2)
        self.state["cash"] = round(self.state["cash"] + r["net_proceeds"], 2)
        self.state["realized_pnl"] = round(self.state["realized_pnl"] + realized, 2)
        pos["qty"] -= qty
        pos["available"] -= qty
        if pos["qty"] == 0:
            del self.state["positions"][code]
        self._save()
        self._append_trade({
            "date": date, "code": code, "side": "sell", "qty": qty, "price": price,
            "amount": r["amount"], "fees": r["commission"] + r["transfer_fee"] + r["stamp_tax"],
            "realized_pnl": realized, "reason": reason, "ts": int(time.time() * 1000),
        })
        return r

    def settle(self, date=None):
        for pos in self.state["positions"].values():
            pos["available"] = pos["qty"]
        self._save()

    def mark(self, prices):
        market_value = 0.0
        details = []
        for code, pos in self.state["positions"].items():
            px = prices.get(code)
            if px is None:
                continue
            mv = round(px * pos["qty"], 2)
            market_value += mv
            details.append({
                "code": code, "qty": pos["qty"], "cost": pos["cost"], "price": px,
                "market_value": mv, "pnl": round((px - pos["cost"]) * pos["qty"], 2),
            })
        market_value = round(market_value, 2)
        total = round(self.state["cash"] + market_value, 2)
        return {
            "cash": self.state["cash"], "market_value": market_value,
            "total_assets": total, "realized_pnl": self.state["realized_pnl"],
            "positions": details,
        }


def _paths():
    base = os.path.join(os.path.dirname(__file__), "..", "account")
    return os.path.join(base, "account.json"), os.path.join(base, "trades.jsonl")


def main():
    cfg = _load_config()
    acct_path, trades_path = _paths()
    parser = argparse.ArgumentParser(description="stock-sim 账户引擎")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("show")
    sub.add_parser("settle")
    p_buy = sub.add_parser("buy")
    p_buy.add_argument("code"); p_buy.add_argument("qty", type=int)
    p_buy.add_argument("--price", type=float, required=True); p_buy.add_argument("--reason", default="")
    p_sell = sub.add_parser("sell")
    p_sell.add_argument("code"); p_sell.add_argument("qty", type=int)
    p_sell.add_argument("--price", type=float, required=True); p_sell.add_argument("--reason", default="")
    p_mark = sub.add_parser("mark")
    p_mark.add_argument("--prices", required=True, help='JSON，如 {"600519":1700.0}')
    args = parser.parse_args()

    e = Account(acct_path, trades_path, fees=cfg["fees"])
    if args.cmd == "init":
        e.init(initial_cash=cfg["initial_cash"])
        print(json.dumps({"ok": True, "cash": e.state["cash"]}, ensure_ascii=False))
    elif args.cmd == "show":
        print(json.dumps(e.state, ensure_ascii=False, indent=2))
    elif args.cmd == "settle":
        e.settle()
        print(json.dumps({"ok": True, "msg": "T+1 已解冻"}, ensure_ascii=False))
    elif args.cmd == "buy":
        r = e.buy(args.code, args.qty, args.price, reason=args.reason)
        print(json.dumps({"ok": True, "cost": r}, ensure_ascii=False))
    elif args.cmd == "sell":
        r = e.sell(args.code, args.qty, args.price, reason=args.reason)
        print(json.dumps({"ok": True, "proceeds": r}, ensure_ascii=False))
    elif args.cmd == "mark":
        snap = e.mark(prices=json.loads(args.prices))
        print(json.dumps(snap, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行确认通过**

Run: `cd /Users/hjx/projects/stock-sim && python3 -m pytest tests/test_account.py -v`
Expected: PASS（8 passed）

- [ ] **Step 5: Commit**

```bash
git add scripts/account.py tests/test_account.py
git commit -m "feat: 账户引擎——成交/T+1/估值，account.json 为唯一真相源"
```

---

## Task 4: quote.py — 三源兜底行情 CLI（TDD）

**Files:**
- Create: `scripts/quote.py`
- Test: `tests/test_quote.py`

设计：每个源是一个函数，`get_realtime` 按 [akshare, tushare, sina] 顺序尝试，任一返回非空即用，全失败抛错。测试用 monkeypatch 注入假源验证 fallback 逻辑（不真连网络）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_quote.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import quote as q


def test_fallback_uses_second_source_when_first_fails():
    def src_fail(code):
        raise RuntimeError("源1挂了")
    def src_ok(code):
        return {"code": code, "price": 12.34, "source": "src_ok"}
    result = q.try_sources([src_fail, src_ok], "600519")
    assert result["price"] == 12.34
    assert result["source"] == "src_ok"


def test_all_sources_fail_raises():
    def src_fail(code):
        raise RuntimeError("挂")
    try:
        q.try_sources([src_fail, src_fail], "600519")
        assert False, "全失败应抛错"
    except q.QuoteError:
        pass


def test_first_source_wins():
    def src_a(code):
        return {"code": code, "price": 1.0, "source": "a"}
    def src_b(code):
        return {"code": code, "price": 2.0, "source": "b"}
    result = q.try_sources([src_a, src_b], "600519")
    assert result["source"] == "a"


def test_none_result_treated_as_failure():
    def src_none(code):
        return None
    def src_ok(code):
        return {"code": code, "price": 9.9, "source": "ok"}
    result = q.try_sources([src_none, src_ok], "600519")
    assert result["source"] == "ok"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /Users/hjx/projects/stock-sim && python3 -m pytest tests/test_quote.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'quote'`

- [ ] **Step 3: 实现 quote.py**

```python
# scripts/quote.py
"""三源兜底行情 CLI：realtime / daily / index。
源优先级：akshare -> tushare -> 新浪 HTTP。任一成功即返回。"""
import sys, os, json, argparse


class QuoteError(Exception):
    pass


def try_sources(sources, *args):
    """按序尝试各源，返回首个非空结果；全失败抛 QuoteError。"""
    errors = []
    for src in sources:
        try:
            r = src(*args)
            if r:
                return r
        except Exception as e:  # 容错：记下错误继续下一个源
            errors.append("%s: %s" % (getattr(src, "__name__", "src"), e))
    raise QuoteError("所有行情源失败：%s" % "; ".join(errors))


def _load_config():
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.json")
    if not os.path.exists(cfg_path):
        cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.example.json")
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f)


# ---------- 实时价：三源 ----------
def _rt_akshare(code):
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    row = df[df["代码"] == code]
    if row.empty:
        return None
    return {"code": code, "price": float(row.iloc[0]["最新价"]),
            "prev_close": float(row.iloc[0]["昨收"]), "source": "akshare"}


def _rt_tushare(code, token):
    if not token:
        return None
    import tushare as ts
    ts.set_token(token)
    pro = ts.pro_api()
    ts_code = code + (".SH" if code.startswith("6") else ".SZ")
    df = pro.daily(ts_code=ts_code, limit=1)
    if df is None or df.empty:
        return None
    return {"code": code, "price": float(df.iloc[0]["close"]),
            "prev_close": float(df.iloc[0]["pre_close"]), "source": "tushare"}


def _rt_sina(code):
    import requests
    prefix = "sh" if code.startswith("6") else "sz"
    url = "https://hq.sinajs.cn/list=%s%s" % (prefix, code)
    resp = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
    resp.encoding = "gbk"
    parts = resp.text.split('"')
    if len(parts) < 2:
        return None
    fields = parts[1].split(",")
    if len(fields) < 4:
        return None
    return {"code": code, "price": float(fields[3]),
            "prev_close": float(fields[2]), "source": "sina"}


def get_realtime(code, cfg):
    token = cfg.get("tushare_token", "")
    return try_sources([
        _rt_akshare,
        lambda c: _rt_tushare(c, token),
        _rt_sina,
    ], code)


# ---------- 日线 ----------
def _daily_akshare(code, days):
    import akshare as ak
    df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
    if df is None or df.empty:
        return None
    df = df.tail(days)
    return {"code": code, "source": "akshare", "bars": [
        {"date": str(r["日期"]), "open": float(r["开盘"]), "high": float(r["最高"]),
         "low": float(r["最低"]), "close": float(r["收盘"]), "volume": float(r["成交量"])}
        for _, r in df.iterrows()
    ]}


def get_daily(code, days, cfg):
    return try_sources([lambda c: _daily_akshare(c, days)], code)


# ---------- 指数（基准） ----------
def _index_akshare(code):
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol=("sh" + code if code.startswith("0") else code))
    if df is None or df.empty:
        return None
    last = df.iloc[-1]
    return {"code": code, "close": float(last["close"]), "date": str(last["date"]),
            "source": "akshare"}


def get_index(code, cfg):
    return try_sources([_index_akshare], code)


def main():
    cfg = _load_config()
    parser = argparse.ArgumentParser(description="stock-sim 行情（三源兜底）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_rt = sub.add_parser("realtime")
    p_rt.add_argument("codes", nargs="+")
    p_d = sub.add_parser("daily")
    p_d.add_argument("code"); p_d.add_argument("--days", type=int, default=60)
    p_i = sub.add_parser("index")
    p_i.add_argument("code", default="000300", nargs="?")
    args = parser.parse_args()

    if args.cmd == "realtime":
        out = {}
        for code in args.codes:
            try:
                out[code] = get_realtime(code, cfg)
            except QuoteError as e:
                out[code] = {"error": str(e)}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.cmd == "daily":
        print(json.dumps(get_daily(args.code, args.days, cfg), ensure_ascii=False, indent=2))
    elif args.cmd == "index":
        print(json.dumps(get_index(args.code, cfg), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行确认通过**

Run: `cd /Users/hjx/projects/stock-sim && python3 -m pytest tests/test_quote.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add scripts/quote.py tests/test_quote.py
git commit -m "feat: 三源兜底行情 CLI——akshare/tushare/新浪，fallback 逻辑可测"
```

---

## Task 5: strategy.md — 初始策略模板

**Files:**
- Create: `strategy/strategy.md`

- [ ] **Step 1: 写初始策略文档**

```markdown
# 选股策略（agent 自迭代）

> 本文件是 agent 的策略大脑。每次复盘后由 agent 修改，每处改动须记录【理由 + 证据】。

## 当前策略版本：v1（初始）

最后更新：（待 agent 填写）

### 选股逻辑

初始为保守的趋势跟随，agent 可在复盘中替换：

1. **趋势**：股价站上 20 日均线，且 20 日均线方向向上。
2. **量能**：当日成交量 > 过去 5 日平均量的 1.5 倍（放量）。
3. **排除**：排除 ST、退市风险股；排除上市不满 60 个交易日的次新股。

### 买入规则

- 单只买入金额不超过总资产的 20%（分散风险）。
- 买入数量向下取整到 100 股整数倍。
- 同一标的不连续加仓超过 2 次。

### 卖出规则

- 止盈：浮盈达 +15% 减半仓；+25% 清仓。
- 止损：浮亏达 -8% 无条件清仓。
- 跌破 20 日均线清仓。

### 仓位管理

- 最大持仓数：5 只。
- 现金保留：至少保留总资产 20% 现金。

## 策略演变记录

| 日期 | 版本 | 改动 | 理由 | 证据（交易） |
|------|------|------|------|--------------|
| —    | v1   | 初始 | —    | —            |
```

- [ ] **Step 2: Commit**

```bash
git add strategy/strategy.md
git commit -m "feat: 初始选股策略模板，含演变记录表"
```

---

## Task 6: SKILL.md — 三场景工作流

**Files:**
- Create: `SKILL.md`

- [ ] **Step 1: 写 SKILL.md**

````markdown
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
````

- [ ] **Step 2: Commit**

```bash
git add SKILL.md
git commit -m "feat: SKILL.md——三场景工作流（交易/复盘/查账）与防自欺纪律"
```

---

## Task 7: 端到端冒烟 + README 部署说明完善

**Files:**
- Modify: `README.md`
- Create: `docs/smoke-test.md`

- [ ] **Step 1: 全量单测通过**

Run: `cd /Users/hjx/projects/stock-sim && python3 -m pytest tests/ -v`
Expected: PASS（全部，16 passed）

- [ ] **Step 2: 离线账户冒烟（不依赖网络）**

Run:
```bash
cd /Users/hjx/projects/stock-sim
cp config/config.example.json config/config.json
python3 scripts/account.py init
python3 scripts/account.py buy 600519 100 --price 1700 --reason "冒烟测试"
python3 scripts/account.py settle
python3 scripts/account.py sell 600519 100 --price 1750 --reason "冒烟止盈"
python3 scripts/account.py mark --prices '{}'
python3 scripts/account.py show
```
Expected: init 成功 → 买入后现金减少 → settle 后可卖 → 卖出 realized_pnl 为正 → show 显示账户状态。
（完成后可删除测试产生的 account/ 文件：`rm -rf account/`）

- [ ] **Step 3: 写 docs/smoke-test.md（记录冒烟步骤与预期）**

```markdown
# stock-sim 冒烟测试

## 1. 单元测试
```bash
python3 -m pytest tests/ -v   # 期望全部通过
```

## 2. 账户离线冒烟（不依赖网络）
见 README「部署」后执行 buy/settle/sell/show，验证：
- 买入后现金减少、持仓冻结（available=0）
- settle 后 available=qty
- 卖出后 realized_pnl 计算正确、持仓清空
- show 输出完整账户状态

## 3. 行情联网冒烟（需依赖安装）
```bash
python3 scripts/quote.py realtime 600519   # 期望返回 price/source
python3 scripts/quote.py index 000300      # 期望返回基准点位
```
若 akshare 失败，应自动 fallback 到新浪源（source 字段标明实际来源）。

## 4. 端到端（场景 A）
按 SKILL.md 场景 A 走一遍：settle→mark→选股→下单→写 daily 报告。
```

- [ ] **Step 4: 完善 README 的"故障排查"段落**

在 README.md 末尾追加：

```markdown
## 故障排查

- **行情全部失败**：检查网络；akshare 偶发限频会自动 fallback 到新浪源；
  Tushare 需有效 token 且有积分权限。
- **akshare 接口报错**：`pip install -U akshare`，其接口随版本变动较快。
- **account.json 损坏**：删除 `account/account.json` 后重新 `account.py init`
  （注意会清空账户，trades.jsonl 保留历史）。
- **Python 版本**：需 3.9+，代码未使用 3.10+ 语法。
```

- [ ] **Step 5: Commit**

```bash
git add README.md docs/smoke-test.md
git commit -m "docs: 冒烟测试文档与 README 故障排查，完成可自举部署"
```

---

## 自检结论

- **Spec 覆盖**：数据多源兜底→Task 4；A 股交易规则→Task 2；账户 JSON 持久化→Task 3；
  策略自然语言文档→Task 5；三场景工作流→Task 6；record 双份→Task 6 场景 A 步骤 7；
  基准对比→Task 6 场景 A/B；自举部署文档→Task 1+7；Tushare token→Task 1 config + Task 4。
- **类型一致**：`Account` 方法名（init/buy/sell/settle/mark）在 Task 3 测试与实现、Task 6 CLI 一致；
  `try_sources`/`QuoteError`/`TradeError` 跨任务一致；fees 字段名贯穿 config/trade_rules/account 一致。
- **无占位符**：所有代码步骤含完整可运行代码与预期输出。
- **调度**：定时自动运行依赖目标环境（hermes + 系统 crontab），属部署范畴，已在 spec §6 标注；
  本计划交付 skill 本体与自举文档，调度接入由部署方按 README 完成。
```
