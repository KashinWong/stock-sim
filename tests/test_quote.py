import sys, os
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
