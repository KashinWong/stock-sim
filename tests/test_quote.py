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
