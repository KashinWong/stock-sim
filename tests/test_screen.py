import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import screen


# ---------- Task 2: load_factors + zscore ----------
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


# ---------- Task 3: build_candidate_pool ----------
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


# ---------- Task 4: apply_hard_filters ----------
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


# ---------- Task 5: score_candidates + rank_candidates ----------
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
