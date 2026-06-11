"""多因子选股：prepare 盘前拉全市场快照写缓存；rank 盘中分层漏斗打分。
纯函数与网络 IO 分离，纯函数可单测。因子参数读 strategy/factors.json。

分层漏斗：
  L0 动态候选池  全市场强势扫描（涨幅+量比+换手）取 Top size
  L1 基本面硬过滤 一票否决：ROE/净利/PE/ST
  L2/L3 多因子打分 z-score 标准化加权 → Top-N
"""
import sys, os, json, argparse, datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_FACTORS = os.path.join(_SCRIPT_DIR, "..", "strategy", "factors.json")
_SNAPSHOT = os.path.join(_SCRIPT_DIR, "..", "cache", "market_snapshot.json")
_FUNDAMENTAL = os.path.join(_SCRIPT_DIR, "..", "cache", "fundamental.json")

_DEFAULT_FACTORS = {
    "candidate_pool": {"size": 100,
                       "strength_factors": ["pct_change", "volume_ratio", "turnover_rate"],
                       "exclude_st": True},
    "hard_filters": {"min_roe": 0.0, "max_pe_ttm": 150.0,
                     "require_positive_profit": True, "exclude_st": True,
                     "on_missing": "exclude"},
    "score_weights": {"trend": 0.20, "momentum": 0.15, "lhb_netbuy": 0.15,
                      "northbound": 0.10, "rel_strength": 0.25, "valuation": 0.15},
    "output": {"top_n": 10},
}

_SCORE_FIELDS = ["trend", "momentum", "lhb_netbuy", "northbound", "rel_strength"]


# ==================== 纯函数区（可单测，无网络） ====================

def load_factors(path=_FACTORS):
    """读 factors.json；文件缺失或字段缺失时用默认值回填。"""
    cfg = dict(_DEFAULT_FACTORS)
    try:
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                merged = dict(_DEFAULT_FACTORS.get(k, {}))
                merged.update(v)
                cfg[k] = merged
            else:
                cfg[k] = v
    except Exception:
        pass
    return cfg


def zscore(values):
    """标准化为 z-score；样本无方差时返回全 0，避免除零。"""
    n = len(values)
    if n == 0:
        return []
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / n
    if var <= 0:
        return [0.0] * n
    std = var ** 0.5
    return [(x - mean) / std for x in values]


def _is_st(name):
    return "ST" in (name or "").upper()


def build_candidate_pool(stocks, size, exclude_st=True):
    """L0：全市场强势扫描，按 (涨幅+量比+换手) 各自 z-score 之和排序取 Top size。
    缺任一强势字段或（exclude_st 时）ST 名称的票剔除。"""
    valid = []
    for s in stocks:
        if exclude_st and _is_st(s.get("name")):
            continue
        if any(s.get(k) is None for k in ("pct_change", "volume_ratio", "turnover_rate")):
            continue
        valid.append(s)
    if not valid:
        return []
    zp = zscore([s["pct_change"] for s in valid])
    zv = zscore([s["volume_ratio"] for s in valid])
    zt = zscore([s["turnover_rate"] for s in valid])
    for i, s in enumerate(valid):
        s["_strength"] = zp[i] + zv[i] + zt[i]
    valid.sort(key=lambda s: s["_strength"], reverse=True)
    return valid[:size]


def apply_hard_filters(candidates, hf):
    """L1 一票否决：基本面不达标即出局。返回通过的候选列表。"""
    passed = []
    for c in candidates:
        if hf.get("exclude_st", True) and _is_st(c.get("name")):
            continue
        if c.get("fundamental_unknown"):
            if hf.get("on_missing", "exclude") == "exclude":
                continue
        roe = c.get("roe")
        if roe is not None and roe < hf.get("min_roe", 0.0):
            continue
        net = c.get("net_profit")
        if hf.get("require_positive_profit", True) and net is not None and net <= 0:
            continue
        pe = c.get("pe_ttm")
        if pe is not None and (pe <= 0 or pe > hf.get("max_pe_ttm", 150.0)):
            continue
        passed.append(c)
    return passed


def score_candidates(candidates, weights):
    """L2：各因子在候选集内 z-score 标准化后按 weights 加权求和。
    估值因子用 -pe_ttm 反向（低估值得高分）。结果写入每条的
    total_score 与 scores{} 分项（标准化后的值）。"""
    if not candidates:
        return []
    zs = {f: zscore([c.get(f, 0.0) or 0.0 for c in candidates]) for f in _SCORE_FIELDS}
    zval = zscore([-(c.get("valuation_raw") or 0.0) for c in candidates])
    for i, c in enumerate(candidates):
        scores = {f: zs[f][i] for f in _SCORE_FIELDS}
        scores["valuation"] = zval[i]
        total = sum(scores[f] * weights.get(f, 0.0) for f in scores)
        c["scores"] = scores
        c["total_score"] = total
    return candidates


def rank_candidates(candidates, weights, top_n):
    """L3：打分后按 total_score 降序取 Top-N。"""
    scored = score_candidates(candidates, weights)
    scored.sort(key=lambda c: c["total_score"], reverse=True)
    return scored[:top_n]


# ==================== IO 区（网络，不进 pytest） ====================

def _f(x):
    """安全转 float；空/NaN/异常返回 None。"""
    try:
        if x is None:
            return None
        v = float(x)
        if v != v:  # NaN
            return None
        return v
    except (ValueError, TypeError):
        return None


def _load_config():
    cfg_path = os.path.join(_SCRIPT_DIR, "..", "config", "config.json")
    if not os.path.exists(cfg_path):
        cfg_path = os.path.join(_SCRIPT_DIR, "..", "config", "config.example.json")
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f)


def fetch_market_snapshot(cfg):
    """tushare daily_basic 全市场单日估值快照；失败回退 akshare 全市场快照。
    返回 {stocks, source, warnings}，每只字段统一为
    code/name/pct_change/volume_ratio/turnover_rate/pe_ttm/pb/total_mv。
    daily_basic 不传 trade_date 时返回最近交易日全市场数据。"""
    warnings_out = []
    # 主源：tushare daily_basic（最近交易日全市场）
    try:
        import tushare as ts
        ts.set_token(cfg.get("tushare_token", ""))
        pro = ts.pro_api()
        names = {}
        try:
            sb = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
            names = {r["ts_code"]: r["name"] for _, r in sb.iterrows()}
        except Exception as e:
            warnings_out.append("stock_basic: %s" % e)
        df = pro.daily_basic(trade_date="", fields=(
            "ts_code,close,pct_chg,turnover_rate,volume_ratio,pe_ttm,pb,total_mv"))
        if df is not None and not df.empty:
            out = []
            for _, r in df.iterrows():
                ts_code = r["ts_code"]
                out.append({
                    "code": ts_code.split(".")[0],
                    "name": names.get(ts_code, ts_code),
                    "pct_change": _f(r.get("pct_chg")),
                    "volume_ratio": _f(r.get("volume_ratio")),
                    "turnover_rate": _f(r.get("turnover_rate")),
                    "pe_ttm": _f(r.get("pe_ttm")),
                    "pb": _f(r.get("pb")),
                    "total_mv": _f(r.get("total_mv")),
                })
            return {"stocks": out, "source": "tushare", "warnings": warnings_out}
    except Exception as e:
        warnings_out.append("daily_basic: %s" % e)
    # 兜底：akshare 全市场快照
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        out = []
        for _, r in df.iterrows():
            out.append({
                "code": str(r["代码"]), "name": str(r["名称"]),
                "pct_change": _f(r.get("涨跌幅")), "volume_ratio": _f(r.get("量比")),
                "turnover_rate": _f(r.get("换手率")), "pe_ttm": _f(r.get("市盈率-动态")),
                "pb": _f(r.get("市净率")), "total_mv": _f(r.get("总市值")),
            })
        return {"stocks": out, "source": "akshare", "warnings": warnings_out}
    except Exception as e:
        warnings_out.append("akshare spot: %s" % e)
    return {"stocks": [], "source": None, "warnings": warnings_out}


def fetch_lhb(date_str):
    """akshare 当日龙虎榜，返回 {code: 净买额} 映射。失败返回空 dict。"""
    try:
        import akshare as ak
        df = ak.stock_lhb_detail_em(start_date=date_str, end_date=date_str)
        if df is None or df.empty:
            return {}
        out = {}
        for _, r in df.iterrows():
            code = str(r.get("代码", "")).zfill(6)
            net = _f(r.get("龙虎榜净买额"))
            if net is not None:
                out[code] = out.get(code, 0.0) + net
        return out
    except Exception:
        return {}


def fetch_fundamental(code):
    """akshare 财务摘要取最新 ROE 与归母净利润。失败返回 unknown。"""
    try:
        import akshare as ak
        df = ak.stock_financial_abstract(symbol=code)
        if df is None or df.empty:
            return {"roe": None, "net_profit": None, "fundamental_unknown": True}
        date_cols = [c for c in df.columns if c not in ("选项", "指标")]
        date_cols.sort(reverse=True)  # 最新报告期在前
        latest = date_cols[0] if date_cols else None

        def pick(keyword):
            rows = df[df["指标"].astype(str).str.contains(keyword, na=False)]
            if rows.empty or latest is None:
                return None
            return _f(rows.iloc[0][latest])

        roe = pick("净资产收益率\\(ROE\\)")
        net = pick("归母净利润")
        return {"roe": roe, "net_profit": net,
                "fundamental_unknown": roe is None and net is None}
    except Exception:
        return {"roe": None, "net_profit": None, "fundamental_unknown": True}


def fetch_northbound(code, cfg):
    """tushare hk_hold 北向持股比例（最新）。失败返回 None。"""
    try:
        import tushare as ts
        ts.set_token(cfg.get("tushare_token", ""))
        pro = ts.pro_api()
        ts_code = code + (".SH" if code.startswith("6") else ".SZ")
        df = pro.hk_hold(ts_code=ts_code, limit=1)
        if df is None or df.empty:
            return None
        return _f(df.iloc[0].get("ratio"))
    except Exception:
        return None


# ==================== 命令区 ====================

def _today():
    return datetime.date.today().isoformat()


def cmd_prepare(cfg):
    """盘前：拉全市场快照 + 当日龙虎榜，合并写 cache/market_snapshot.json。"""
    snap = fetch_market_snapshot(cfg)
    date_compact = _today().replace("-", "")
    lhb = fetch_lhb(date_compact)
    for s in snap["stocks"]:
        s["lhb_netbuy"] = lhb.get(s["code"], 0.0)
    out = {"date": _today(), "source": snap["source"],
           "warnings": snap["warnings"], "stocks": snap["stocks"]}
    os.makedirs(os.path.dirname(_SNAPSHOT), exist_ok=True)
    with open(_SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    return {"date": out["date"], "source": out["source"],
            "count": len(out["stocks"]), "lhb_count": len(lhb),
            "warnings": out["warnings"]}


def _load_snapshot():
    with open(_SNAPSHOT, encoding="utf-8") as f:
        return json.load(f)


def cmd_rank(cfg, top_n=None):
    """盘中：读快照 → L0 候选池 → 补基本面/北向 → L1 过滤 → L2/L3 打分。"""
    factors = load_factors()
    warnings_out = []
    try:
        snap = _load_snapshot()
    except Exception as e:
        return {"error": "无 market_snapshot，请先跑 screen.py prepare：%s" % e,
                "candidates": []}

    cp = factors["candidate_pool"]
    pool = build_candidate_pool(snap["stocks"], cp["size"], cp.get("exclude_st", True))

    # 候选增量补基本面 + 北向（带本地缓存）
    fund_cache = {}
    if os.path.exists(_FUNDAMENTAL):
        try:
            fund_cache = json.load(open(_FUNDAMENTAL, encoding="utf-8"))
        except Exception:
            fund_cache = {}
    for c in pool:
        code = c["code"]
        if code not in fund_cache:
            fc = fetch_fundamental(code)
            fc["northbound"] = fetch_northbound(code, cfg)
            fund_cache[code] = fc
        fc = fund_cache[code]
        c["roe"] = fc.get("roe")
        c["net_profit"] = fc.get("net_profit")
        c["fundamental_unknown"] = fc.get("fundamental_unknown", False)
        c["northbound"] = fc.get("northbound") or 0.0
    try:
        os.makedirs(os.path.dirname(_FUNDAMENTAL), exist_ok=True)
        json.dump(fund_cache, open(_FUNDAMENTAL, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        warnings_out.append("写 fundamental 缓存失败：%s" % e)

    # L1 硬过滤
    passed = apply_hard_filters(pool, factors["hard_filters"])

    # 准备打分原始值
    for c in passed:
        c["trend"] = c.get("_strength", 0.0)
        c["momentum"] = c.get("pct_change") or 0.0
        c["rel_strength"] = c.get("pct_change") or 0.0
        c["valuation_raw"] = c.get("pe_ttm") or 0.0
        c["lhb_netbuy"] = c.get("lhb_netbuy") or 0.0

    n = top_n or factors["output"]["top_n"]
    ranked = rank_candidates(passed, factors["score_weights"], n)
    out = [{"code": c["code"], "name": c["name"],
            "total_score": round(c["total_score"], 4),
            "scores": {k: round(v, 4) for k, v in c["scores"].items()},
            "pe_ttm": c.get("pe_ttm"), "roe": c.get("roe"),
            "lhb_netbuy": c.get("lhb_netbuy"), "northbound": c.get("northbound")}
           for c in ranked]
    return {"date": snap.get("date"), "pool_size": len(pool),
            "passed_filters": len(passed),
            "warnings": snap.get("warnings", []) + warnings_out,
            "candidates": out}


def main():
    cfg = _load_config()
    parser = argparse.ArgumentParser(description="stock-sim 多因子选股")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    p_rank = sub.add_parser("rank")
    p_rank.add_argument("--top", type=int, default=None)
    args = parser.parse_args()
    if args.cmd == "prepare":
        print(json.dumps(cmd_prepare(cfg), ensure_ascii=False, indent=2))
    elif args.cmd == "rank":
        print(json.dumps(cmd_rank(cfg, args.top), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
