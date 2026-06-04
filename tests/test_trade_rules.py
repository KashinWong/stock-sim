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
