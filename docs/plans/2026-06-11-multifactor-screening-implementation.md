# 多因子选股升级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 stock-sim 选股从「6 板块内挑技术形态」升级为全市场多因子分层漏斗打分模型（动态候选池 → 基本面硬过滤 → 多因子打分排序），因子参数外置 `factors.json` 让复盘闭环能迭代选股行为。

**Architecture:** 新增 `scripts/screen.py`（`prepare` 盘前拉全市场快照写缓存；`rank` 盘中读缓存做分层漏斗打分）。打分逻辑为纯函数、与网络 IO 分离，便于单测。因子开关/阈值/权重外置 `strategy/factors.json`。复用 `quote.py` 数据源，不动 `account.py`/`trade_rules.py`。风控仍由 SKILL 场景 A 的 v2.1 规则把关。

**Tech Stack:** Python 3.9、tushare（`daily_basic`/`hk_hold`）、akshare（`stock_financial_abstract`/`stock_lhb_detail_em`/`stock_zh_a_spot_em`）、pytest。

设计依据：[docs/specs/2026-06-11-multifactor-screening-design.md](../specs/2026-06-11-multifactor-screening-design.md)

---

## 文件结构

| 文件 | 责任 | 操作 |
|------|------|------|
| `strategy/factors.json` | 因子开关/阈值/权重，机器可读 | 创建 |
| `scripts/screen.py` | prepare（拉数缓存）+ rank（分层漏斗打分），纯函数与 IO 分离 | 创建 |
| `tests/test_screen.py` | screen.py 纯函数单测（不依赖网络） | 创建 |
| `.gitignore` | 排除新缓存文件 | 修改 |
| `strategy/strategy.md` | 改写选股段，引用 factors.json | 修改 |
| `SKILL.md` | 场景 A 第 5 步、场景 B、场景 D、纪律段 | 修改 |
| `docs/smoke-test.md` | 追加 screen.py 真实接口冒烟记录 | 修改 |

`screen.py` 内部结构（单文件，函数分区）：
- **纯函数区**（可测，无网络）：`load_factors`、`zscore`、`build_candidate_pool`、`apply_hard_filters`、`score_candidates`、`rank_candidates`
- **IO 区**（网络）：`fetch_market_snapshot`、`fetch_lhb`、`fetch_fundamental`、`fetch_northbound`
- **命令区**：`cmd_prepare`、`cmd_rank`、`main`

---

## Task 1: factors.json 配置文件

**Files:**
- Create: `strategy/factors.json`

- [ ] **Step 1: 写配置文件**

```json
{
  "version": "v3.0",
  "updated_at": "2026-06-11",
  "candidate_pool": {
    "size": 100,
    "strength_factors": ["pct_change", "volume_ratio", "turnover_rate"],
    "exclude_st": true
  },
  "hard_filters": {
    "min_roe": 0.0,
    "max_pe_ttm": 150.0,
    "require_positive_profit": true,
    "exclude_st": true,
    "on_missing": "exclude"
  },
  "score_weights": {
    "trend": 0.20,
    "momentum": 0.15,
    "lhb_netbuy": 0.15,
    "northbound": 0.10,
    "rel_strength": 0.25,
    "valuation": 0.15
  },
  "output": { "top_n": 10 }
}
```

- [ ] **Step 2: 校验 JSON 合法**

Run: `python3 -c "import json; json.load(open('strategy/factors.json'))" && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add strategy/factors.json
git commit -m "feat: 新增 factors.json 多因子参数配置"
```

---

## Task 2: load_factors + zscore 纯函数

**Files:**
- Create: `scripts/screen.py`
- Test: `tests/test_screen.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_screen.py
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import screen


def test_load_factors_reads_file(tmp_path):
    p = tmp_path / "factors.json"
    p.write_text(json.dumps({"score_weights": {"trend": 0.5}}), encoding="utf-8")
    f = screen.load_factors(str(p))
    assert f["score_weights"]["trend"] == 0.5


def test_load_factors_missing_file_returns_defaults():
    f = screen.load_factors("/no/such/factors.json")
    assert "score_weights" in f
    assert f["hard_filters"]["max_pe_ttm"] == 150.0


def test_zscore_basic():
    out = screen.zscore([1.0, 2.0, 3.0])
    assert abs(out[0] + out[2]) < 1e-9  # 对称
    assert out[1] == 0.0                 # 均值点为 0


def test_zscore_constant_returns_zeros():
    assert screen.zscore([5.0, 5.0, 5.0]) == [0.0, 0.0, 0.0]
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_screen.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'screen'`）

- [ ] **Step 3: 写最小实现**

```python
# scripts/screen.py
"""多因子选股：prepare 盘前拉全市场快照写缓存；rank 盘中分层漏斗打分。
纯函数与网络 IO 分离，纯函数可单测。因子参数读 strategy/factors.json。"""
import sys, os, json, argparse

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
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m pytest tests/test_screen.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add scripts/screen.py tests/test_screen.py
git commit -m "feat: screen.py load_factors + zscore 纯函数"
```

---

## Task 3: build_candidate_pool（L0 动态候选池）

**Files:**
- Modify: `scripts/screen.py`
- Test: `tests/test_screen.py`

候选池输入是 snapshot 的股票列表，每条形如：
`{"code","name","pct_change","volume_ratio","turnover_rate","pe_ttm","pb","total_mv"}`

- [ ] **Step 1: 写失败测试**

```python
def _mk(code, name, pct, vr, to):
    return {"code": code, "name": name, "pct_change": pct,
            "volume_ratio": vr, "turnover_rate": to}


def test_build_candidate_pool_ranks_by_strength():
    stocks = [
        _mk("000001", "平安银行", 1.0, 1.0, 1.0),
        _mk("600519", "贵州茅台", 5.0, 3.0, 4.0),
        _mk("000333", "美的集团", 3.0, 2.0, 2.0),
    ]
    pool = screen.build_candidate_pool(stocks, size=2, exclude_st=True)
    assert [s["code"] for s in pool] == ["600519", "000333"]


def test_build_candidate_pool_excludes_st():
    stocks = [
        _mk("000001", "ST康美", 9.0, 9.0, 9.0),
        _mk("600519", "贵州茅台", 1.0, 1.0, 1.0),
    ]
    pool = screen.build_candidate_pool(stocks, size=5, exclude_st=True)
    assert [s["code"] for s in pool] == ["600519"]


def test_build_candidate_pool_skips_missing_fields():
    stocks = [
        {"code": "000001", "name": "A", "pct_change": 5.0},  # 缺 vr/to
        _mk("600519", "B", 1.0, 1.0, 1.0),
    ]
    pool = screen.build_candidate_pool(stocks, size=5, exclude_st=True)
    assert [s["code"] for s in pool] == ["600519"]
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_screen.py -k candidate_pool -v`
Expected: FAIL（`AttributeError: module 'screen' has no attribute 'build_candidate_pool'`）

- [ ] **Step 3: 写实现（追加到 screen.py 纯函数区）**

```python
def _is_st(name):
    return "ST" in (name or "").upper()


def build_candidate_pool(stocks, size, exclude_st=True):
    """全市场强势扫描：按 (涨幅+量比+换手) 各自 z-score 之和排序取 Top size。
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
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m pytest tests/test_screen.py -k candidate_pool -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add scripts/screen.py tests/test_screen.py
git commit -m "feat: L0 动态候选池 build_candidate_pool"
```

---

## Task 4: apply_hard_filters（L1 基本面硬过滤）

**Files:**
- Modify: `scripts/screen.py`
- Test: `tests/test_screen.py`

每只候选附带基本面字段：`{"roe","net_profit","pe_ttm","fundamental_unknown"}`（unknown 表示拉取失败）。

- [ ] **Step 1: 写失败测试**

```python
def _cand(code, roe=15.0, net=1e8, pe=30.0, name="正常股", unknown=False):
    return {"code": code, "name": name, "roe": roe, "net_profit": net,
            "pe_ttm": pe, "fundamental_unknown": unknown}


def test_hard_filters_passes_healthy():
    out = screen.apply_hard_filters([_cand("600519")], screen._DEFAULT_FACTORS["hard_filters"])
    assert [c["code"] for c in out] == ["600519"]


def test_hard_filters_rejects_low_roe_negative_profit_high_pe_st():
    hf = screen._DEFAULT_FACTORS["hard_filters"]
    cands = [
        _cand("A", roe=-1.0),          # ROE < min_roe
        _cand("B", net=-1.0),          # 净利为负
        _cand("C", pe=200.0),          # PE 超上限
        _cand("D", pe=-5.0),           # PE 为负
        _cand("E", name="ST某某"),     # ST
        _cand("F"),                    # 唯一健康
    ]
    out = screen.apply_hard_filters(cands, hf)
    assert [c["code"] for c in out] == ["F"]


def test_hard_filters_missing_excluded_by_default():
    hf = screen._DEFAULT_FACTORS["hard_filters"]
    out = screen.apply_hard_filters([_cand("X", unknown=True)], hf)
    assert out == []
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_screen.py -k hard_filters -v`
Expected: FAIL（no attribute `apply_hard_filters`）

- [ ] **Step 3: 写实现（追加到纯函数区）**

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m pytest tests/test_screen.py -k hard_filters -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add scripts/screen.py tests/test_screen.py
git commit -m "feat: L1 基本面硬过滤 apply_hard_filters"
```

---

## Task 5: score_candidates + rank_candidates（L2/L3 打分排序）

**Files:**
- Modify: `scripts/screen.py`
- Test: `tests/test_screen.py`

每只候选打分前附带原始因子值：`trend`、`momentum`、`lhb_netbuy`、`northbound`、`rel_strength`、`valuation_raw`（=pe_ttm，反向计分）。

- [ ] **Step 1: 写失败测试**

```python
def _scored(code, trend, mom, lhb, nb, rs, pe):
    return {"code": code, "name": code, "trend": trend, "momentum": mom,
            "lhb_netbuy": lhb, "northbound": nb, "rel_strength": rs,
            "valuation_raw": pe}


def test_score_valuation_is_reverse():
    # 两只票除 PE 外全同；低 PE 应得更高分
    w = {"trend": 0, "momentum": 0, "lhb_netbuy": 0, "northbound": 0,
         "rel_strength": 0, "valuation": 1.0}
    cands = [_scored("LOWPE", 0, 0, 0, 0, 0, 10.0),
             _scored("HIGHPE", 0, 0, 0, 0, 0, 100.0)]
    out = screen.score_candidates(cands, w)
    lo = next(c for c in out if c["code"] == "LOWPE")
    hi = next(c for c in out if c["code"] == "HIGHPE")
    assert lo["total_score"] > hi["total_score"]


def test_rank_returns_top_n_sorted():
    w = {"trend": 1.0, "momentum": 0, "lhb_netbuy": 0, "northbound": 0,
         "rel_strength": 0, "valuation": 0}
    cands = [_scored("A", 1.0, 0, 0, 0, 0, 30),
             _scored("B", 3.0, 0, 0, 0, 0, 30),
             _scored("C", 2.0, 0, 0, 0, 0, 30)]
    out = screen.rank_candidates(cands, w, top_n=2)
    assert [c["code"] for c in out] == ["B", "C"]
    assert "scores" in out[0] and "trend" in out[0]["scores"]
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_screen.py -k "score or rank" -v`
Expected: FAIL（no attribute `score_candidates`）

- [ ] **Step 3: 写实现（追加到纯函数区）**

```python
_SCORE_FIELDS = ["trend", "momentum", "lhb_netbuy", "northbound", "rel_strength"]


def score_candidates(candidates, weights):
    """各因子在候选集内 z-score 标准化后按 weights 加权求和。
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
    """打分后按 total_score 降序取 Top-N。"""
    scored = score_candidates(candidates, weights)
    scored.sort(key=lambda c: c["total_score"], reverse=True)
    return scored[:top_n]
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m pytest tests/test_screen.py -k "score or rank" -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add scripts/screen.py tests/test_screen.py
git commit -m "feat: L2/L3 多因子打分排序 score/rank_candidates"
```

---

## Task 6: IO 区 — 数据拉取函数

**Files:**
- Modify: `scripts/screen.py`

这些函数访问网络，不进 pytest，由 Task 9 冒烟验证。复用 `quote.py` 的 config 读取与数据源风格。

- [ ] **Step 1: 写实现（追加到 screen.py，IO 区）**

```python
def _load_config():
    cfg_path = os.path.join(_SCRIPT_DIR, "..", "config", "config.json")
    if not os.path.exists(cfg_path):
        cfg_path = os.path.join(_SCRIPT_DIR, "..", "config", "config.example.json")
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f)


def fetch_market_snapshot(cfg):
    """tushare daily_basic 全市场单日估值快照；失败回退 akshare 全市场快照。
    返回 list[dict]，字段统一为 code/name/pct_change/volume_ratio/turnover_rate/pe_ttm/pb/total_mv。
    daily_basic 不传 trade_date 时返回最近交易日全市场数据。"""
    warnings_out = []
    # 主源：tushare daily_basic（最近交易日全市场）
    try:
        import tushare as ts
        ts.set_token(cfg.get("tushare_token", ""))
        pro = ts.pro_api()
        # 用 stock_basic 拿名称映射
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
```

> 注意：tushare `daily_basic` 不传 `trade_date` 返回最近交易日全市场快照；命中限速时自动回退 akshare。

- [ ] **Step 2: 语法检查**

Run: `python3 -c "import sys; sys.path.insert(0,'scripts'); import screen; print('import ok')"`
Expected: `import ok`

- [ ] **Step 3: Commit**

```bash
git add scripts/screen.py
git commit -m "feat: screen.py 数据拉取 IO 区（快照/龙虎榜/基本面/北向）"
```

---

## Task 7: cmd_prepare / cmd_rank / main（命令编排）

**Files:**
- Modify: `scripts/screen.py`

- [ ] **Step 1: 写实现（追加到 screen.py 命令区）**

```python
import datetime


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

    # 准备打分原始值：trend/momentum 用强势分近似（已在 pool 内有 _strength）
    # 横截面相对强弱用 pct_change 在候选集分位；估值用 pe_ttm 反向。
    for c in passed:
        c["trend"] = c.get("_strength", 0.0)
        c["momentum"] = c.get("pct_change") or 0.0
        c["rel_strength"] = c.get("pct_change") or 0.0
        c["valuation_raw"] = c.get("pe_ttm") or 0.0
        # lhb_netbuy / northbound 已在候选上
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
            "passed_filters": len(passed), "warnings": snap.get("warnings", []) + warnings_out,
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
```

- [ ] **Step 2: 全量单测回归**

Run: `python3 -m pytest tests/test_screen.py -v`
Expected: PASS（全部纯函数测试通过，命令区不被单测覆盖但需 import 通过）

- [ ] **Step 3: Commit**

```bash
git add scripts/screen.py
git commit -m "feat: screen.py prepare/rank/main 命令编排"
```

---

## Task 8: .gitignore 排除缓存

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: 追加缓存忽略**

在 `.gitignore` 的「运行时状态」段后追加：

```
cache/market_snapshot.json
cache/fundamental.json
```

- [ ] **Step 2: 确认未被追踪**

Run: `git check-ignore cache/market_snapshot.json cache/fundamental.json`
Expected: 两行路径都被输出（表示已忽略）

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore 排除 screen 缓存文件"
```

---

## Task 9: 真实接口冒烟验证

**Files:**
- Modify: `docs/smoke-test.md`

> 注意 daily_basic 限速 1 次/小时；若 prepare 命中限速会自动回退 akshare，记录实际 source。

- [ ] **Step 1: 跑 prepare**

Run: `python3 scripts/screen.py prepare`
Expected: JSON 含 `count > 3000`、`source` 为 tushare 或 akshare、`warnings` 可空。

- [ ] **Step 2: 跑 rank**

Run: `python3 scripts/screen.py rank --top 5`
Expected: JSON `candidates` 长度 ≤5，每条含 `total_score` 与 `scores{trend,momentum,lhb_netbuy,northbound,rel_strength,valuation}`，`passed_filters ≥1`。

- [ ] **Step 3: 把两条命令的真实输出摘要追加到 docs/smoke-test.md**

在文件末尾追加一节「## 多因子选股 screen.py（2026-06-11）」，粘贴 prepare 的 count/source 与 rank 的 Top5 代码+总分。

- [ ] **Step 4: Commit**

```bash
git add docs/smoke-test.md
git commit -m "test: screen.py 真实接口冒烟验证记录"
```

---

## Task 10: 改写 strategy.md 选股段

**Files:**
- Modify: `strategy/strategy.md`

- [ ] **Step 1: 改写「一、盘中信号体系」段**

把 v2.1 的「A. 日线级 / B. 盘中分时级」选股逻辑，替换为引用多因子模型的描述（保留「二、买入规则」的开仓铁门槛、「三、卖出规则」、「四、仓位管理」全部风控不变）。新增段落说明：

```markdown
### 一、选股信号体系（v3.0 多因子分层漏斗）

选股逻辑由 `scripts/screen.py` 执行，因子参数在 `strategy/factors.json`（机器可读，复盘时改）。
分三层漏斗：
- **L0 动态候选池**：全市场按（涨幅+量比+换手）强势扫描取 Top100，打破板块锁死。
- **L1 基本面硬过滤（一票否决）**：剔除 ROE<0 / 净利为负 / PE_TTM>150 或为负 / ST。
- **L2 多因子打分**：技术(趋势+动量) + 资金(龙虎榜净买+北向持股) + 横截面相对强弱 + 估值（反向），
  各因子 z-score 标准化后按 factors.json 权重加权，输出 Top-N 候选。

当前权重（factors.json v3.0）：trend 0.20 / momentum 0.15 / lhb_netbuy 0.15 /
northbound 0.10 / rel_strength 0.25 / valuation 0.15。

agent 巡盘时跑 `screen.py rank` 取候选，再用 `quote.py daily` 复核趋势，
**仍须过下方「二、买入规则」的开仓铁门槛**才下单。
```

- [ ] **Step 2: 在策略演变记录表追加一行**

```markdown
| 2026-06-11 | v3.0 | 选股从「6板块内挑技术形态」升级为全市场多因子分层漏斗（screen.py + factors.json）：L0动态候选池/L1基本面硬过滤/L2多因子打分。风控全部保留不变。 | 用户决策：做有选股能力的策略，补齐基本面/横截面/资金面/动态池四维度。本版为模型切换基线，无实战证据，后续按复盘迭代 factors.json 权重。 | — |
```

- [ ] **Step 3: Commit**

```bash
git add strategy/strategy.md
git commit -m "docs: strategy.md 选股段升级为 v3.0 多因子模型"
```

---

## Task 11: 改写 SKILL.md

**Files:**
- Modify: `SKILL.md`

- [ ] **Step 1: 工具命令段新增 screen.py**

在「## 工具命令」的行情段后追加：

```markdown
# 多因子选股（screen.py）
python scripts/screen.py prepare           # 盘前拉全市场快照+龙虎榜写缓存（每交易日09:00跑一次）
python scripts/screen.py rank --top 10      # 盘中分层漏斗打分，输出Top候选（读缓存，毫秒级）
```

- [ ] **Step 2: 改写场景 A 第 5 步**

将「实时信号建仓」第 5 步的「读 focus_sectors → board 候选池 → 技术形态确认买点」替换为：

```markdown
5. **多因子选股建仓**：仓位/现金有空间时（持仓 <5 只、现金 ≥15%）才找新机会——
   跑 `python scripts/screen.py rank --top 10` 取多因子 Top 候选（已过 L0 动态池 + L1 基本面硬过滤 + L2 打分）。
   对候选用 `quote.py daily` 复核趋势/均线背景，叠加实时价当日动量确认买点，
   **仍须过「二、买入规则」开仓铁门槛（现价≥MA20 且 MA20 向上）**，再调 `account.py buy`。
   遵守 A 股规则（T+1、100 股整手、单只 ≤30% 总资产、最多 5 只）。
   > 候选已含基本面过滤，不再盲扫 focus_sectors；focus_sectors 仅用于 prepare 阶段板块缓存与复盘归因。
```

- [ ] **Step 3: 改写场景 B 复盘归因维度**

在场景 B 第 2 步「归因」后补一条：

```markdown
2b. **因子归因**：除 alpha vs beta 外，分析哪些因子（trend/momentum/lhb/northbound/rel_strength/valuation）
    在近期交易中有效或失效。复盘产出**同时更新** `strategy/factors.json`（权重/阈值，机器执行）
    与 `strategy.md` 演变记录（理由+证据），二者保持一致。
```

- [ ] **Step 4: 场景 D 新增 prepare 调度说明**

在场景 D（刷新板块缓存）后补一小节：

```markdown
## 场景 E：盘前准备多因子快照（每交易日 09:00）

每交易日开盘前跑一次，拉全市场估值快照 + 当日龙虎榜写 `cache/market_snapshot.json`：

\`\`\`bash
python scripts/screen.py prepare
\`\`\`

- daily_basic 限速 1 次/小时；若命中限速自动回退 akshare 全市场快照，输出 `source` 标明实际源。
- 盘中 `screen.py rank` 只读该缓存，毫秒级，不再走网络（基本面/北向首次拉后增量缓存）。
- 缓存文件不进 git，本地持久化。
```

- [ ] **Step 5: 纪律段新增一条**

在「## 纪律（防自欺）」末尾追加：

```markdown
- 选股先过基本面硬过滤（L1 一票否决），宁可错过不可买基本面垃圾股；
  技术/资金面再强也不能绕过 ROE/净利/估值闸门。
```

- [ ] **Step 6: Commit**

```bash
git add SKILL.md
git commit -m "docs: SKILL.md 接入多因子选股（场景A/B/E + 纪律）"
```

---

## 完成标准

- `python3 -m pytest tests/test_screen.py -v` 全绿。
- `python3 scripts/screen.py prepare` 与 `rank --top 5` 在真实接口跑通，输出结构符合 §6/§L3。
- `screen.py` 不含魔法数字，全部因子参数来自 `factors.json`。
- `account.py`/`quote.py`/`trade_rules.py` 零改动（`git diff --stat` 确认）。
- strategy.md / SKILL.md / smoke-test.md 已更新且与 factors.json 一致。
