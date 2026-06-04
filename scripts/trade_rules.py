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
