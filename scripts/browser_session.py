"""通用浏览器登录态复用模块（可被其它脚本 import）。

模型：人工有头登录一次（browser_login.py 导出登录态）→ 本模块 headless 复用。
登录态按站点名隔离存储于 cache/sessions/<site>.json（storage_state 格式，含 cookie，
已 gitignore）。对外暴露：

    has_session(site)                 登录态文件是否存在
    session_path(site)                登录态文件路径
    fetch_json(site, url, params)     带登录态 headless 请求接口，返回解析后的 JSON
    fetch_page_xhr(site, url, pats)   打开页面捕获匹配的 XHR 响应（探查接口用）

graceful degradation：未装 playwright / 无登录态 → 抛 SessionError；登录态失效（接口
401/403/跳登录页）→ 抛 SessionExpiredError。调用方（如 quote.py 的 board 源）catch 后
返回 None 自动放行给后续源，绝不破坏现有链路。
"""
import os
import json

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SESSIONS_DIR = os.path.join(_SCRIPT_DIR, "..", "cache", "sessions")

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class SessionError(Exception):
    """无登录态 / 未装 playwright 等不可恢复的前置错误。"""
    pass


class SessionExpiredError(SessionError):
    """登录态存在但已失效（接口返回 401/403 或跳转登录页）。需重新登录。"""
    pass


def session_path(site):
    """返回站点登录态文件路径 cache/sessions/<site>.json。"""
    return os.path.join(_SESSIONS_DIR, "%s.json" % site)


def has_session(site):
    """登录态文件是否存在。"""
    return os.path.exists(session_path(site))


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return sync_playwright
    except ImportError:
        raise SessionError(
            "未安装 playwright，无法使用登录态抓取。安装：pip3 install playwright "
            "&& python3 -m playwright install chromium")


def _load_storage_state(site):
    path = session_path(site)
    if not os.path.exists(path):
        raise SessionError("无 %s 登录态（%s 不存在）。先跑 browser_login.py %s 登录。"
                           % (site, path, site))
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError) as e:
        raise SessionExpiredError("%s 登录态文件损坏：%s" % (site, e))


def fetch_json(site, url, params=None, timeout=20):
    """用 <site> 的登录态 headless 请求 url，返回解析后的 JSON（dict/list）。

    用浏览器原生 page.request.get() 发请求（携带登录态 cookie，复用浏览器 TLS 指纹，
    绕过部分接口对 python-requests 的拦截）。

    异常：
      SessionError         无登录态 / 未装 playwright
      SessionExpiredError  接口 401/403 或返回非 JSON（多为跳登录页）——登录态失效
    """
    sync_playwright = _require_playwright()
    storage_state = _load_storage_state(site)

    if params:
        from urllib.parse import urlencode
        sep = "&" if "?" in url else "?"
        url = url + sep + urlencode(params)

    timeout_ms = int(timeout * 1000)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(storage_state=storage_state, user_agent=_UA)
            resp = context.request.get(url, timeout=timeout_ms)
            status = resp.status
            body = resp.text()
            if status in (401, 403):
                raise SessionExpiredError(
                    "%s 接口返回 %d，登录态已失效，请重新登录：browser_login.py %s"
                    % (site, status, site))
            try:
                return json.loads(body)
            except ValueError:
                # 返回非 JSON：通常是被重定向到登录页的 HTML
                raise SessionExpiredError(
                    "%s 接口返回非 JSON（status=%d），疑似登录态失效或接口变更。"
                    % (site, status))
        finally:
            browser.close()


def fetch_page_xhr(site, url, url_patterns, wait_ms=3000, use_session=True):
    """打开页面，捕获 URL 含 url_patterns 任一子串的 XHR/fetch 响应，用于探查接口。

    返回 list，每项 {"url", "status", "json"|"text"}。use_session=False 时以访客身份打开。
    """
    sync_playwright = _require_playwright()
    storage_state = _load_storage_state(site) if use_session else None
    if isinstance(url_patterns, str):
        url_patterns = [url_patterns]

    captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(storage_state=storage_state, user_agent=_UA)
            page = context.new_page()

            def _on_response(resp):
                u = resp.url
                if any(pat in u for pat in url_patterns):
                    item = {"url": u, "status": resp.status}
                    try:
                        item["json"] = resp.json()
                    except Exception:
                        try:
                            item["text"] = resp.text()[:2000]
                        except Exception:
                            item["text"] = "<unreadable>"
                    captured.append(item)

            page.on("response", _on_response)
            page.goto(url, timeout=30000, wait_until="networkidle")
            page.wait_for_timeout(wait_ms)
        finally:
            browser.close()

    return captured


if __name__ == "__main__":
    # 自检/探查入口：python3 browser_session.py <site> fetch <url>
    #               python3 browser_session.py <site> xhr <page_url> <pattern>
    import argparse
    ap = argparse.ArgumentParser(description="登录态抓取自检/探查")
    ap.add_argument("site")
    ap.add_argument("mode", choices=["fetch", "xhr", "check"])
    ap.add_argument("url", nargs="?")
    ap.add_argument("pattern", nargs="?")
    a = ap.parse_args()

    if a.mode == "check":
        print(json.dumps({"site": a.site, "has_session": has_session(a.site),
                          "path": session_path(a.site)}, ensure_ascii=False))
    elif a.mode == "fetch":
        try:
            data = fetch_json(a.site, a.url)
            print(json.dumps(data, ensure_ascii=False)[:4000])
        except SessionError as e:
            print("SessionError: %s" % e)
    elif a.mode == "xhr":
        try:
            for item in fetch_page_xhr(a.site, a.url, a.pattern or ""):
                print(json.dumps(item, ensure_ascii=False)[:2000])
        except SessionError as e:
            print("SessionError: %s" % e)
