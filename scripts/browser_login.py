"""有头浏览器手动登录 CLI——人工登录一次，导出登录态供 headless 复用。

用法：
    python3 scripts/browser_login.py xueqiu --url https://xueqiu.com

弹出真实浏览器窗口 → 你手动完成登录 → 回终端按回车 → 登录态存到
cache/sessions/<site>.json。之后龙虾（headless）通过 browser_session.fetch_json
复用该登录态抓取需登录的接口。

只做"人工登录一次 + 机器复用"，不存账号密码、不模拟登录输入。登录态文件含身份凭证，
已被 .gitignore 排除。
"""
import os
import sys
import argparse

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from browser_session import session_path, _SESSIONS_DIR, _UA  # noqa: E402


def login(site, url):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("未安装 playwright。安装：pip3 install playwright "
              "&& python3 -m playwright install chromium")
        return 1

    os.makedirs(_SESSIONS_DIR, exist_ok=True)
    out = session_path(site)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # 有头：弹真窗口
        context = browser.new_context(user_agent=_UA)
        page = context.new_page()
        print("正在打开 %s ……" % url)
        page.goto(url, timeout=60000)

        print()
        print("=" * 56)
        print(" 请在弹出的浏览器窗口里手动完成 [%s] 登录。" % site)
        print(" 登录成功后，回到本终端按【回车】导出登录态。")
        print("=" * 56)
        try:
            input("登录完成后按回车继续...")
        except (EOFError, KeyboardInterrupt):
            print("\n已取消，未导出登录态。")
            browser.close()
            return 1

        context.storage_state(path=out)
        browser.close()

    print()
    print("✅ 登录态已导出：%s" % out)
    print("   龙虾（headless）将通过 browser_session.fetch_json('%s', ...) 复用它。" % site)
    print("   登录态失效后重跑本命令即可刷新。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="有头浏览器手动登录，导出登录态")
    ap.add_argument("site", help="站点名（登录态存为 cache/sessions/<site>.json），如 xueqiu")
    ap.add_argument("--url", required=True, help="登录页 URL，如 https://xueqiu.com")
    a = ap.parse_args()
    sys.exit(login(a.site, a.url))


if __name__ == "__main__":
    main()
