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
            "initial_assets": float(initial_cash),
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
            pos["bought_date"] = date
        else:
            self.state["positions"][code] = {
                "qty": qty, "available": 0, "cost": round(c["total_cost"] / qty, 4),
                "bought_date": date,
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
        date = date or _today()
        for pos in self.state["positions"].values():
            if pos.get("bought_date", "") < date:
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
    p_init = sub.add_parser("init")
    p_init.add_argument("--cash", type=float, default=None,
                        help="初始本金；缺省回退 config.json 的 initial_cash")
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
        cash = args.cash if args.cash is not None else cfg["initial_cash"]
        e.init(initial_cash=cash)
        print(json.dumps({"ok": True, "cash": e.state["cash"]}, ensure_ascii=False))
    elif args.cmd == "show":
        print(json.dumps(e.state, ensure_ascii=False, indent=2))
    elif args.cmd == "settle":
        e.settle()
        print(json.dumps({"ok": True, "msg": "T+1 已解冻"}, ensure_ascii=False))
    elif args.cmd == "buy":
        try:
            r = e.buy(args.code, args.qty, args.price, reason=args.reason)
        except TradeError as ex:
            print(json.dumps({"ok": False, "error": str(ex)}, ensure_ascii=False))
            sys.exit(1)
        print(json.dumps({"ok": True, "cost": r}, ensure_ascii=False))
    elif args.cmd == "sell":
        try:
            r = e.sell(args.code, args.qty, args.price, reason=args.reason)
        except TradeError as ex:
            print(json.dumps({"ok": False, "error": str(ex)}, ensure_ascii=False))
            sys.exit(1)
        print(json.dumps({"ok": True, "proceeds": r}, ensure_ascii=False))
    elif args.cmd == "mark":
        try:
            prices = json.loads(args.prices)
        except json.JSONDecodeError as ex:
            parser.error("--prices 不是合法 JSON：%s" % ex)
        snap = e.mark(prices=prices)
        print(json.dumps(snap, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
