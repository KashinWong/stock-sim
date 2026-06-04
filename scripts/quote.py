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
    try:
        price = float(fields[3])
        prev_close = float(fields[2])
    except ValueError:
        return None  # 停牌或字段异常（如 "--"），视为该源失败，交由兜底
    if price <= 0:
        return None  # 停牌时 sina 返回 0 价，视为无效
    return {"code": code, "price": price, "prev_close": prev_close, "source": "sina"}


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


def _daily_tushare(code, days, token):
    if not token:
        return None
    import tushare as ts
    ts.set_token(token)
    pro = ts.pro_api()
    ts_code = code + (".SH" if code.startswith("6") else ".SZ")
    df = pro.daily(ts_code=ts_code, limit=days)
    if df is None or df.empty:
        return None
    df = df.iloc[::-1]  # tushare returns descending; reverse to ascending
    bars = []
    for _, r in df.iterrows():
        d = str(r["trade_date"])
        bars.append({
            "date": "%s-%s-%s" % (d[0:4], d[4:6], d[6:8]),
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
            "volume": float(r["vol"]),
        })
    return {"code": code, "source": "tushare", "bars": bars}


def get_daily(code, days, cfg):
    token = cfg.get("tushare_token", "")
    return try_sources([
        lambda c: _daily_akshare(c, days),
        lambda c: _daily_tushare(c, days, token),
    ], code)


# ---------- 指数（基准） ----------
def _index_akshare(code):
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol=("sh" + code if code.startswith("0") else code))
    if df is None or df.empty:
        return None
    last = df.iloc[-1]
    return {"code": code, "close": float(last["close"]), "date": str(last["date"]),
            "source": "akshare"}


def _index_sina(code):
    """Sina HTTP fallback for index quotes."""
    import requests
    import time
    prefix = "sh" if code.startswith("0") else "sz"
    url = "https://hq.sinajs.cn/list=%s%s" % (prefix, code)
    try:
        resp = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
        resp.encoding = "gbk"
    except Exception:
        return None
    parts = resp.text.split('"')
    if len(parts) < 2:
        return None
    fields = parts[1].split(",")
    if len(fields) < 4:
        return None
    try:
        close = float(fields[3])
    except ValueError:
        return None  # non-numeric (停牌 etc.) → fall through
    if close <= 0:
        return None
    return {"code": code, "close": close,
            "date": time.strftime("%Y-%m-%d"), "source": "sina"}


def get_index(code, cfg):
    return try_sources([_index_akshare, _index_sina], code)


# ---------- 板块成分（选股候选池，单源 akshare，失败可降级） ----------
def _board_akshare(name):
    """name 为 None 列出行业板块；否则列出该板块成分股。仅 akshare 一源。"""
    import akshare as ak
    if name is None:
        df = ak.stock_board_industry_name_em()
        if df is None or df.empty:
            return None
        return {"type": "list", "source": "akshare", "boards": [
            {"name": str(r["板块名称"]), "code": str(r["板块代码"])}
            for _, r in df.iterrows()
        ]}
    df = ak.stock_board_industry_cons_em(symbol=name)
    if df is None or df.empty:
        return None
    return {"type": "cons", "board": name, "source": "akshare", "stocks": [
        {"code": str(r["代码"]), "name": str(r["名称"])}
        for _, r in df.iterrows()
    ]}


def get_board(name, cfg):
    return try_sources([_board_akshare], name)


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
    p_b = sub.add_parser("board")
    p_b.add_argument("name", nargs="?", default=None,
                     help="板块名称（如「白酒」）；省略则列出全部行业板块")
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
    elif args.cmd == "board":
        try:
            print(json.dumps(get_board(args.name, cfg), ensure_ascii=False, indent=2))
        except QuoteError as e:
            print(json.dumps({"error": str(e),
                              "hint": "板块成分仅 akshare 单源，失败时可由 agent 凭知识列出候选代码"},
                             ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
