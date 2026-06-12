"""多源兜底行情 CLI：realtime / daily / index / board / board-refresh。
realtime: akshare -> tushare -> 新浪 HTTP。
daily: akshare -> tushare -> 腾讯 HTTP（纯 requests，无依赖也能拉）。
index: akshare -> 新浪 HTTP。
board: 本地缓存 -> akshare -> curl_cffi（浏览器指纹绕过东方财富反爬）。
board-refresh: 用 curl_cffi 拉取 focus_sectors 所有板块并写入缓存。
任一成功即返回。"""
import sys, os, json, argparse, datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BOARD_CACHE = os.path.join(_SCRIPT_DIR, "..", "cache", "board_cache.json")
_BOARD_CACHE_DAYS = 30



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


def _daily_tencent(code, days):
    """腾讯日线 HTTP 兜底（前复权，纯 requests）。返回升序、含当日。
    字段顺序：[日期, 开, 收, 高, 低, 量]。"""
    import requests
    secid = ("sh" if code.startswith("6") else "sz") + code
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    try:
        resp = requests.get(url, params={"param": "%s,day,,,%d,qfq" % (secid, days)},
                            timeout=10)
        d = resp.json()
    except Exception:
        return None
    node = d.get("data", {}).get(secid)
    if not node:
        return None
    arr = node.get("qfqday") or node.get("day")
    if not arr:
        return None
    bars = []
    for row in arr:
        # row = [日期, 开, 收, 高, 低, 量]
        try:
            bars.append({
                "date": row[0], "open": float(row[1]), "close": float(row[2]),
                "high": float(row[3]), "low": float(row[4]), "volume": float(row[5]),
            })
        except (ValueError, IndexError):
            continue
    if not bars:
        return None
    return {"code": code, "source": "tencent", "bars": bars}


def get_daily(code, days, cfg):
    token = cfg.get("tushare_token", "")
    return try_sources([
        lambda c: _daily_akshare(c, days),
        lambda c: _daily_tushare(c, days, token),
        lambda c: _daily_tencent(c, days),
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


# ---------- 板块成分 ----------

# 用户 focus_sectors 名称 → THS 对应板块名称映射（THS 行业分类与东方财富不完全一致）
_BOARD_THS_ALIAS = {
    "有色金属": "工业金属",   # THS 把有色细分为工业金属/能源金属/贵金属/小金属，工业金属最大
    "新能源": "新能源汽车",   # THS 概念板块中最接近的名称
}

# 用户 focus_sectors 名称 → 雪球申万一级行业代码映射。
# 雪球只有申万「行业」分类、无「概念」板块，故 PCB/CPO/算力/人工智能/新能源 等概念板块
# 雪球覆盖不了（返回 None 自动交由 THS）。此处仅登记雪球能精确覆盖的行业类。
_BOARD_XUEQIU_INDCODE = {
    "电力": "S4101",
    "有色金属": "S2403",   # 申万「工业金属」，有色中市值最大的子行业
}


def _board_cache_load(name):
    """从本地 JSON 缓存读板块数据；超过 30 天或缓存不存在返回 None。"""
    if not os.path.exists(_BOARD_CACHE):
        return None
    try:
        with open(_BOARD_CACHE, encoding="utf-8") as f:
            data = json.load(f)
        updated = datetime.date.fromisoformat(data.get("updated_at", "2000-01-01"))
        if (datetime.date.today() - updated).days > _BOARD_CACHE_DAYS:
            return None
        boards = data.get("boards", {})
        if name is None:
            return {"type": "list", "source": "cache", "boards": list(boards.keys())}
        stocks = boards.get(name)
        if stocks is None:
            return None
        return {"type": "cons", "board": name, "source": "cache", "stocks": stocks}
    except Exception:
        return None


def _board_cache_save(name, stocks):
    """将单个板块的成分股列表写入缓存文件（增量更新，不覆盖其他板块）。"""
    os.makedirs(os.path.dirname(_BOARD_CACHE), exist_ok=True)
    data = {"boards": {}, "updated_at": datetime.date.today().isoformat()}
    if os.path.exists(_BOARD_CACHE):
        try:
            with open(_BOARD_CACHE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data["boards"][name] = stocks
    data["updated_at"] = datetime.date.today().isoformat()
    with open(_BOARD_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _board_ths(name, _industry_df=None, _concept_df=None):
    """同花顺 web 抓取（JS cookie 绕反爬），支持行业板块 + 概念板块，最多 200 只。
    每页独立生成 v_code 以规避会话级别限速。行业板块用 /thshy/，概念板块用 /gn/。"""
    import re
    import py_mini_racer
    from bs4 import BeautifulSoup
    import requests as _req

    import akshare as _ak
    ths_js_path = os.path.join(os.path.dirname(_ak.__file__), "data", "ths.js")
    with open(ths_js_path) as f:
        _ths_js_src = f.read()

    def _make_v():
        js = py_mini_racer.MiniRacer()
        js.eval(_ths_js_src)
        return js.call("v")

    industry_df = _industry_df if _industry_df is not None else _ak.stock_board_industry_name_ths()
    concept_df = _concept_df if _concept_df is not None else _ak.stock_board_concept_name_ths()

    if name is None:
        boards = (list(industry_df["name"]) + list(concept_df["name"]))
        return {"type": "list", "source": "ths", "boards": boards}

    # 别名映射（如"有色金属"→"工业金属"）
    lookup_name = _BOARD_THS_ALIAS.get(name, name)

    # 精确匹配 → 关键词模糊匹配（行业优先再概念）
    board_code, board_type = None, None
    row = industry_df[industry_df["name"] == lookup_name]
    if not row.empty:
        board_code, board_type = str(row.iloc[0]["code"]), "industry"
    if board_code is None:
        row = concept_df[concept_df["name"] == lookup_name]
        if not row.empty:
            board_code, board_type = str(row.iloc[0]["code"]), "concept"
    if board_code is None:
        keywords = [k for k in re.split(r"[()（）/\s]+", lookup_name) if len(k) >= 2]
        for kw in keywords:
            row = industry_df[industry_df["name"].str.contains(kw, na=False)]
            if not row.empty:
                board_code, board_type = str(row.iloc[0]["code"]), "industry"
                break
        if board_code is None:
            for kw in keywords:
                row = concept_df[concept_df["name"].str.contains(kw, na=False)]
                if not row.empty:
                    board_code, board_type = str(row.iloc[0]["code"]), "concept"
                    break

    if board_code is None:
        return None

    # 翻页抓取，每页重新生成 v_code（规避 THS 会话级速率限制）
    path_prefix = "thshy" if board_type == "industry" else "gn"
    base_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/89"
    stocks = []
    for page in range(1, 11):  # 最多 10 页 ≈ 100–200 只
        url = ("http://q.10jqka.com.cn/%s/detail/code/%s/field/199112/order/desc/page/%d/ajax/1/"
               % (path_prefix, board_code, page))
        r = _req.get(url, headers={"User-Agent": base_ua, "Cookie": "v=%s" % _make_v()}, timeout=10)
        if r.status_code != 200:
            break
        soup = BeautifulSoup(r.text, "lxml")
        table = soup.find("table", {"class": "m-table"})
        if not table:
            break
        page_stocks = []
        for row in table.find_all("tr")[1:]:
            cols = row.find_all("td")
            if len(cols) >= 3:
                page_stocks.append({"code": cols[1].text.strip(), "name": cols[2].text.strip()})
        stocks.extend(page_stocks)
        # 检查是否最后一页
        page_info = soup.find("span", {"class": "page_info"})
        if page_info:
            cur, total = page_info.text.strip().split("/")
            if int(cur) >= int(total):
                break
        elif not page_stocks:
            break

    if not stocks:
        return None
    return {"type": "cons", "board": name, "source": "ths", "stocks": stocks}


def _board_cffi(name):
    """curl_cffi 模拟浏览器 TLS 指纹绕过东方财富反爬（备用源）。"""
    from curl_cffi import requests as cffi_req
    r = cffi_req.get(
        "https://17.push2.eastmoney.com/api/qt/clist/get",
        params={
            "pn": "1", "pz": "300", "po": "1", "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2", "invt": "2", "fid": "f3",
            "fs": "m:90 t:2 f:!50",
            "fields": "f12,f14",
        },
        impersonate="chrome136",
        timeout=15,
    )
    r.raise_for_status()
    diff = r.json()["data"]["diff"]
    items = diff.values() if isinstance(diff, dict) else diff
    board_map = {v["f14"]: v["f12"] for v in items if v.get("f14") and v.get("f12")}

    if name is None:
        return {"type": "list", "source": "cffi",
                "boards": [{"name": n, "code": c} for n, c in board_map.items()]}

    if name not in board_map:
        return None
    code = board_map[name]

    r2 = cffi_req.get(
        "https://29.push2.eastmoney.com/api/qt/clist/get",
        params={
            "pn": "1", "pz": "500", "po": "1", "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2", "invt": "2", "fid": "f3",
            "fs": "b:%s f:!50" % code,
            "fields": "f12,f14",
        },
        impersonate="chrome136",
        timeout=15,
    )
    r2.raise_for_status()
    diff2 = r2.json()["data"]["diff"]
    items2 = diff2.values() if isinstance(diff2, dict) else diff2
    stocks = [{"code": str(v["f12"]), "name": str(v["f14"])}
              for v in items2 if v.get("f12") and v.get("f14")]
    return {"type": "cons", "board": name, "source": "cffi", "stocks": stocks}


def _board_akshare(name):
    """name 为 None 列出行业板块；否则列出该板块成分股。"""
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


def _board_xueqiu(name):
    """雪球申万行业成分股（HTTPS + cookie，仅覆盖行业类板块；概念板块返回 None）。
    通过访问 /hq 获取 xq_a_token cookie，再用 quote/list.json 的 ind_code 拉成分股。"""
    import requests as _req

    indcode = _BOARD_XUEQIU_INDCODE.get(name)
    if name is not None and indcode is None:
        # 未登记的板块（多为概念板块），雪球覆盖不了，交由后续源
        return None

    sess = _req.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                       "AppleWebKit/537.36 Chrome/120 Safari/537.36"})
    sess.get("https://xueqiu.com/hq", timeout=10)  # 取 xq_a_token 等 cookie

    if name is None:
        r = sess.get("https://stock.xueqiu.com/v5/stock/screener/industries.json",
                     params={"category": "cn"}, timeout=10)
        inds = r.json().get("data", {}).get("industries", [])
        if not inds:
            return None
        return {"type": "list", "source": "xueqiu", "boards": [
            {"name": i["name"], "code": i["encode"]} for i in inds
        ]}

    stocks, page = [], 1
    while page <= 10:  # 最多 10 页 = 300 只，足够
        r = sess.get("https://stock.xueqiu.com/v5/stock/screener/quote/list.json",
                     params={"page": str(page), "size": "30", "order": "desc",
                             "order_by": "percent", "market": "CN", "ind_code": indcode},
                     timeout=10)
        d = r.json().get("data", {})
        lst = d.get("list", [])
        if not lst:
            break
        for s in lst:
            sym = s.get("symbol", "")
            code = sym[2:] if sym[:2] in ("SH", "SZ", "BJ") else sym
            stocks.append({"code": code, "name": s.get("name", "")})
        total = d.get("count", 0)
        if len(stocks) >= total:
            break
        page += 1

    if not stocks:
        return None
    return {"type": "cons", "board": name, "source": "xueqiu", "stocks": stocks}


def get_board(name, cfg):
    """优先读本地缓存；缓存过期/不存在则从网络拉取，成功后写缓存。
    源顺序：THS（行业+概念全覆盖）→ 雪球（行业类高质量兜底）→ akshare → cffi。"""
    cached = _board_cache_load(name)
    if cached is not None:
        return cached
    result = try_sources([_board_ths, _board_xueqiu, _board_akshare, _board_cffi], name)
    if result and result.get("type") == "cons" and result.get("stocks"):
        _board_cache_save(name, result["stocks"])
    return result


def _board_refresh_all(cfg):
    """刷新 focus_sectors 全部板块缓存（ths → 雪球 → akshare → cffi 四源兜底）。
    预加载 THS 行业/概念板块名称表以减少重复 HTTP 请求。"""
    profile_path = os.path.join(_SCRIPT_DIR, "..", "profile", "profile.json")
    try:
        with open(profile_path, encoding="utf-8") as f:
            profile = json.load(f)
        sectors = profile.get("focus_sectors", [])
    except Exception as e:
        return {"error": "读取 profile.json 失败: %s" % e}
    if not sectors:
        return {"error": "profile.json 未配置 focus_sectors"}

    # 预加载 THS board name 映射（全局只拉一次）
    try:
        import akshare as _ak
        _industry_df = _ak.stock_board_industry_name_ths()
        _concept_df = _ak.stock_board_concept_name_ths()

        def _ths_preloaded(sector_name):
            return _board_ths(sector_name, _industry_df=_industry_df, _concept_df=_concept_df)
    except Exception:
        _ths_preloaded = _board_ths

    ok, failed = [], []
    for sector in sectors:
        try:
            r = try_sources([_ths_preloaded, _board_xueqiu, _board_akshare, _board_cffi], sector)
            if r and r.get("stocks"):
                _board_cache_save(sector, r["stocks"])
                ok.append({"name": sector, "count": len(r["stocks"]), "source": r.get("source")})
            else:
                failed.append({"name": sector, "error": "所有源返回空"})
        except QuoteError as e:
            failed.append({"name": sector, "error": str(e)})

    return {"updated_at": datetime.date.today().isoformat(), "ok": ok, "failed": failed}


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
    sub.add_parser("board-refresh",
                   help="用 curl_cffi 刷新 focus_sectors 全部板块缓存（每月执行一次）")
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
                              "hint": "所有在线源失败，可运行 board-refresh 预先缓存，或由 agent 凭知识列出候选代码"},
                             ensure_ascii=False, indent=2))
    elif args.cmd == "board-refresh":
        print(json.dumps(_board_refresh_all(cfg), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
