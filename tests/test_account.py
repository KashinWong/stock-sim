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
        assert e.state["cash"] == 998994.99
        pos = e.state["positions"]["600519"]
        assert pos["qty"] == 100
        assert pos["available"] == 0
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
        assert snap["market_value"] == 1200.0
        assert abs(snap["total_assets"] - (998994.99 + 1200.0)) < 0.01
    finally:
        shutil.rmtree(tmp)
