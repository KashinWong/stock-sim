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

def test_price_limit_exact_boundaries():
    # 昨收 10，主板 ±10% → 边界 9.0 与 11.0 应被接受
    assert tr.within_price_limit(11.0, prev_close=10.0, limit_rate=0.10) is True
    assert tr.within_price_limit(9.0, prev_close=10.0, limit_rate=0.10) is True
    # 略超边界应拒绝
    assert tr.within_price_limit(11.01, prev_close=10.0, limit_rate=0.10) is False
    assert tr.within_price_limit(8.99, prev_close=10.0, limit_rate=0.10) is False


def test_price_limit_st_and_chinext_rates():
    # ST ±5%：昨收 10 → [9.5, 10.5]
    assert tr.within_price_limit(10.5, prev_close=10.0, limit_rate=0.05) is True
    assert tr.within_price_limit(10.6, prev_close=10.0, limit_rate=0.05) is False
    # 创业板/科创板 ±20%：昨收 10 → [8.0, 12.0]
    assert tr.within_price_limit(12.0, prev_close=10.0, limit_rate=0.20) is True
    assert tr.within_price_limit(12.5, prev_close=10.0, limit_rate=0.20) is False


def test_commission_uses_rate_when_above_minimum():
    # 1000 股 * 100 元 = 100000；佣金 = 100000*0.00025 = 25 > 5，应取 25
    r = tr.buy_cost(price=100.0, qty=1000, fees=FEES)
    assert r["amount"] == 100000.0
    assert r["commission"] == 25.0
    s = tr.sell_proceeds(price=100.0, qty=1000, fees=FEES)
    assert s["commission"] == 25.0
    assert s["stamp_tax"] == 50.0  # 100000*0.0005


def test_within_price_limit():
    # 昨收 10，主板 ±10% → [9.0, 11.0]
    assert tr.within_price_limit(10.5, prev_close=10.0, limit_rate=0.10) is True
    assert tr.within_price_limit(11.5, prev_close=10.0, limit_rate=0.10) is False
