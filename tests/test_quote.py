import sys, os, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import quote as q


def test_fallback_uses_second_source_when_first_fails():
    def src_fail(code):
        raise RuntimeError("源1挂了")
    def src_ok(code):
        return {"code": code, "price": 12.34, "source": "src_ok"}
    result = q.try_sources([src_fail, src_ok], "600519")
    assert result["price"] == 12.34
    assert result["source"] == "src_ok"


def test_all_sources_fail_raises():
    def src_fail(code):
        raise RuntimeError("挂")
    try:
        q.try_sources([src_fail, src_fail], "600519")
        assert False, "全失败应抛错"
    except q.QuoteError:
        pass


def test_first_source_wins():
    def src_a(code):
        return {"code": code, "price": 1.0, "source": "a"}
    def src_b(code):
        return {"code": code, "price": 2.0, "source": "b"}
    result = q.try_sources([src_a, src_b], "600519")
    assert result["source"] == "a"


def test_none_result_treated_as_failure():
    def src_none(code):
        return None
    def src_ok(code):
        return {"code": code, "price": 9.9, "source": "ok"}
    result = q.try_sources([src_none, src_ok], "600519")
    assert result["source"] == "ok"


def test_sina_returns_none_on_non_numeric_price(monkeypatch):
    """模拟 sina 返回停牌 stock（"--" 价格字段），应返回 None。"""
    fake_resp = types.SimpleNamespace(
        text='var hq_str_sh600519="贵州茅台,--,--,--";', encoding="utf-8"
    )
    fake_requests = types.SimpleNamespace(get=lambda *a, **k: fake_resp)
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    assert q._rt_sina("600519") is None


def test_sina_returns_none_on_zero_price(monkeypatch):
    """模拟 sina 返回 0 价（停牌），应返回 None。"""
    fake_resp = types.SimpleNamespace(
        text='var hq_str_sh600519="贵州茅台,10.00,9.50,0";', encoding="utf-8"
    )
    fake_requests = types.SimpleNamespace(get=lambda *a, **k: fake_resp)
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    assert q._rt_sina("600519") is None


def test_sina_parses_normal_response():
    """正常响应应正确解析。"""
    import types
    fake_resp = types.SimpleNamespace(
        text='var hq_str_sh600519="贵州茅台,1800.00,1750.00,1780.50";', encoding="utf-8"
    )
    import builtins
    real_import = builtins.__import__
    def fake_import(name, *args, **kwargs):
        if name == "requests":
            return types.SimpleNamespace(get=lambda *a, **k: fake_resp)
        return real_import(name, *args, **kwargs)
    builtins.__import__ = fake_import
    try:
        result = q._rt_sina("600519")
        assert result is not None
        assert result["price"] == 1780.50
        assert result["prev_close"] == 1750.00
        assert result["source"] == "sina"
    finally:
        builtins.__import__ = real_import


def test_index_sina_parses_normal_response(monkeypatch):
    """模拟 sina 指数响应，_index_sina 应返回 close 值 + source=sina。"""
    fake_resp = types.SimpleNamespace(
        text='var hq_str_sh000300="沪深300,4897.32,4938.81,4904.75,4938.78,4889.75,0,0,264808910,736143410003,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-06-04,15:35:31,00,";',
        encoding="utf-8",
    )
    fake_requests = types.SimpleNamespace(get=lambda *a, **k: fake_resp)
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    result = q._index_sina("000300")
    assert result is not None
    assert result["close"] == 4904.75
    assert result["source"] == "sina"


def test_index_sina_returns_none_on_non_numeric(monkeypatch):
    """sina 指数返回非当前点位（停牌 "--"），应返回 None。"""
    fake_resp = types.SimpleNamespace(
        text='var hq_str_sh000300="沪深300,--,--,",',
        encoding="utf-8",
    )
    fake_requests = types.SimpleNamespace(get=lambda *a, **k: fake_resp)
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    assert q._index_sina("000300") is None


def test_daily_tushare_parses_and_sorts_ascending(monkeypatch):
    """tushare 日线返回降序，函数应将 bars 升序排列（最早在前）。"""
    import pandas as pd
    df = pd.DataFrame([
        {"trade_date": "20260604", "open": 11.0, "high": 12.0, "low": 10.5, "close": 11.5, "vol": 2000.0},
        {"trade_date": "20260603", "open": 10.0, "high": 10.8, "low": 9.9, "close": 10.5, "vol": 1500.0},
    ])
    class FakePro:
        def daily(self, **kw):
            return df
    fake_ts = types.SimpleNamespace(set_token=lambda t: None, pro_api=lambda: FakePro())
    monkeypatch.setitem(sys.modules, "tushare", fake_ts)
    result = q._daily_tushare("600519", 60, "faketoken")
    assert result["source"] == "tushare"
    assert len(result["bars"]) == 2
    assert result["bars"][0]["date"] == "2026-06-03"  # 升序：最早在前
    assert result["bars"][1]["date"] == "2026-06-04"
    assert result["bars"][1]["close"] == 11.5


def test_daily_tushare_sh_sz_code_mapping(monkeypatch):
    """沪市 6 开头 -> .SH, 深市 -> .SZ。"""
    import pandas as pd

    captured_codes = []
    class FakePro:
        def daily(self, **kw):
            captured_codes.append(kw.get("ts_code"))
            return pd.DataFrame()

    fake_ts = types.SimpleNamespace(set_token=lambda t: None, pro_api=lambda: FakePro())
    monkeypatch.setitem(sys.modules, "tushare", fake_ts)
    q._daily_tushare("600519", 60, "token")
    assert "600519.SH" in captured_codes
    captured_codes.clear()
    q._daily_tushare("000001", 60, "token")
    assert "000001.SZ" in captured_codes


def test_daily_tushare_returns_none_without_token():
    """无 token 时应返回 None。"""
    assert q._daily_tushare("600519", 60, "") is None


def test_board_lists_industries(monkeypatch):
    """无板块名时列出全部行业板块。"""
    import pandas as pd
    df = pd.DataFrame([
        {"板块名称": "白酒", "板块代码": "BK0477"},
        {"板块名称": "半导体", "板块代码": "BK1036"},
    ])
    fake_ak = types.SimpleNamespace(stock_board_industry_name_em=lambda: df)
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)
    result = q._board_akshare(None)
    assert result["type"] == "list"
    assert result["source"] == "akshare"
    assert {"name": "白酒", "code": "BK0477"} in result["boards"]
    assert len(result["boards"]) == 2


def test_board_lists_constituents(monkeypatch):
    """给定板块名时列出成分股代码。"""
    import pandas as pd
    df = pd.DataFrame([
        {"代码": "600519", "名称": "贵州茅台"},
        {"代码": "000858", "名称": "五粮液"},
    ])
    captured = {}
    def cons(symbol):
        captured["symbol"] = symbol
        return df
    fake_ak = types.SimpleNamespace(stock_board_industry_cons_em=cons)
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)
    result = q._board_akshare("白酒")
    assert captured["symbol"] == "白酒"
    assert result["type"] == "cons"
    assert result["board"] == "白酒"
    assert {"code": "600519", "name": "贵州茅台"} in result["stocks"]


def test_board_all_sources_fail_raises(monkeypatch):
    """单源 akshare 不可用时应抛 QuoteError（交由 CLI 降级提示）。"""
    def boom():
        raise RuntimeError("akshare 未安装")
    fake_ak = types.SimpleNamespace(stock_board_industry_name_em=boom)
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)
    try:
        q.get_board(None, {})
        assert False, "应抛 QuoteError"
    except q.QuoteError:
        pass


def test_daily_tencent_parses_fields(monkeypatch):
    """腾讯日线 [日期,开,收,高,低,量] 应正确映射到 bar 字段，升序保留。"""
    payload = {"code": 0, "data": {"sh600519": {"qfqday": [
        ["2026-06-04", "1278.99", "1268.00", "1288.99", "1266.69", "33506"],
        ["2026-06-05", "1278.00", "1272.86", "1283.00", "1267.74", "31304"],
    ]}}}
    fake_resp = types.SimpleNamespace(json=lambda: payload)
    fake_requests = types.SimpleNamespace(get=lambda *a, **k: fake_resp)
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    result = q._daily_tencent("600519", 5)
    assert result["source"] == "tencent"
    assert len(result["bars"]) == 2
    b0 = result["bars"][0]
    assert b0["date"] == "2026-06-04"
    assert b0["open"] == 1278.99 and b0["close"] == 1268.00
    assert b0["high"] == 1288.99 and b0["low"] == 1266.69
    assert b0["volume"] == 33506.0
    assert result["bars"][1]["close"] == 1272.86  # 升序：当日在后


def test_daily_tencent_sh_sz_prefix(monkeypatch):
    """6 开头 -> sh 前缀，其余 -> sz。"""
    captured = {}
    def fake_get(url, params=None, timeout=None):
        captured["param"] = params["param"]
        return types.SimpleNamespace(json=lambda: {"data": {}})
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=fake_get))
    q._daily_tencent("600519", 5)
    assert captured["param"].startswith("sh600519,")
    q._daily_tencent("000001", 5)
    assert captured["param"].startswith("sz000001,")


def test_daily_tencent_returns_none_on_empty(monkeypatch):
    """无数据节点时返回 None（交由 try_sources 视为失败）。"""
    fake_resp = types.SimpleNamespace(json=lambda: {"code": 0, "data": {}})
    monkeypatch.setitem(sys.modules, "requests",
                        types.SimpleNamespace(get=lambda *a, **k: fake_resp))
    assert q._daily_tencent("600519", 5) is None
