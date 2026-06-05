import sys, os, json, tempfile, shutil, subprocess


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import account as acc

FEES = {"commission_rate": 0.00025, "commission_min": 5.0,
        "stamp_tax_rate": 0.0005, "transfer_fee_rate": 0.00001}


def make_engine(tmp):
    acct_path = os.path.join(tmp, "account.json")
    trades_path = os.path.join(tmp, "trades.jsonl")
    return acc.Account(acct_path, trades_path, fees=FEES)


def test_init_sets_cash():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000000, date="2026-06-04")
        assert e.state["cash"] == 1000000
        assert e.state["positions"] == {}
    finally:
        shutil.rmtree(tmp)


def test_buy_deducts_cash_and_freezes_position():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000000, date="2026-06-04")
        e.buy("600519", qty=100, price=10.0, date="2026-06-04", reason="测试买入")
        assert e.state["cash"] == 998994.99
        pos = e.state["positions"]["600519"]
        assert pos["qty"] == 100
        assert pos["available"] == 0
    finally:
        shutil.rmtree(tmp)


def test_buy_rejects_insufficient_cash():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000, date="2026-06-04")
        try:
            e.buy("600519", qty=100, price=100.0, date="2026-06-04", reason="超买")
            assert False, "应抛出资金不足"
        except acc.TradeError:
            pass
    finally:
        shutil.rmtree(tmp)


def test_settle_unfreezes_position():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000000, date="2026-06-04")
        e.buy("600519", qty=100, price=10.0, date="2026-06-04", reason="买")
        e.settle(date="2026-06-05")
        assert e.state["positions"]["600519"]["available"] == 100
    finally:
        shutil.rmtree(tmp)


def test_sell_rejects_when_not_settled():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000000, date="2026-06-04")
        e.buy("600519", qty=100, price=10.0, date="2026-06-04", reason="买")
        try:
            e.sell("600519", qty=100, price=11.0, date="2026-06-04", reason="当日卖")
            assert False, "T+1 当日不可卖"
        except acc.TradeError:
            pass
    finally:
        shutil.rmtree(tmp)


def test_sell_adds_cash_and_realizes_pnl():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000000, date="2026-06-04")
        e.buy("600519", qty=100, price=10.0, date="2026-06-04", reason="买")
        e.settle(date="2026-06-05")
        e.sell("600519", qty=100, price=12.0, date="2026-06-05", reason="卖")
        assert "600519" not in e.state["positions"]
        assert e.state["realized_pnl"] == 189.38
    finally:
        shutil.rmtree(tmp)


def test_trades_are_appended():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000000, date="2026-06-04")
        e.buy("600519", qty=100, price=10.0, date="2026-06-04", reason="买")
        with open(os.path.join(tmp, "trades.jsonl")) as f:
            lines = f.readlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["code"] == "600519"
        assert rec["side"] == "buy"
    finally:
        shutil.rmtree(tmp)


def test_mark_computes_market_value():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000000, date="2026-06-04")
        e.buy("600519", qty=100, price=10.0, date="2026-06-04", reason="买")
        snap = e.mark(prices={"600519": 12.0})
        assert snap["market_value"] == 1200.0
        assert abs(snap["total_assets"] - (998994.99 + 1200.0)) < 0.01
    finally:
        shutil.rmtree(tmp)


def test_init_with_explicit_cash_overrides_default():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=500000, date="2026-06-04")
        assert e.state["cash"] == 500000
        assert e.state["initial_assets"] == 500000
    finally:
        shutil.rmtree(tmp)


def test_cli_init_cash_and_fallback():
    """集成测试：通过 CLI 子进程覆盖 --cash 和回退 config 两条路径。"""
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    tmp = tempfile.mkdtemp()
    try:
        workdir = os.path.join(tmp, "work")
        shutil.copytree(repo_root, workdir, ignore=shutil.ignore_patterns(
            "account", ".git", "__pycache__", "*.pyc", "tests"))
        acct_dir = os.path.join(workdir, "account")
        cli = [sys.executable, "scripts/account.py", "init"]

        # --- 路径 1：显式 --cash ---
        result = subprocess.run(cli + ["--cash", "500000"], cwd=workdir,
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        state = json.load(open(os.path.join(acct_dir, "account.json")))
        assert state["cash"] == 500000.0

        # --- 路径 2：无 --cash，回退 config.example.json initial_cash === 1_000_000 ---
        if os.path.exists(os.path.join(acct_dir, "account.json")):
            os.remove(os.path.join(acct_dir, "account.json"))
        result = subprocess.run(cli, cwd=workdir, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        state = json.load(open(os.path.join(acct_dir, "account.json")))
        assert state["cash"] == 1000000.0
    finally:
        shutil.rmtree(tmp)


def test_init_records_initial_assets_anchor():
    """init 时应记录初始资产锚点，供后续 return% 计算使用。"""
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=1000000, date="2026-06-04")
        assert e.state["initial_assets"] == 1000000.0
    finally:
        shutil.rmtree(tmp)


def test_cli_sell_t1_block_outputs_clean_json():
    """CLI 卖出遇 T+1 拦截：应输出 {"ok": false, "error": ...}，退出码 1，无 Traceback。"""
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    tmp = tempfile.mkdtemp()
    try:
        workdir = os.path.join(tmp, "work")
        shutil.copytree(repo_root, workdir, ignore=shutil.ignore_patterns(
            "account", ".git", "__pycache__", "*.pyc", "tests"))

        def run(*cli_args):
            return subprocess.run(
                [sys.executable, "scripts/account.py", *cli_args],
                cwd=workdir, capture_output=True, text=True)

        run("init", "--cash", "500000")
        run("buy", "000001", "1000", "--price", "10.0", "--reason", "建仓")
        # 当天卖出应被 T+1 拦截
        result = run("sell", "000001", "1000", "--price", "10.5", "--reason", "测试拦截")
        assert result.returncode == 1, "业务拦截应以非 0 退出"
        assert "Traceback" not in result.stderr, "不应喷 Python 栈"
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert "T+1" in payload["error"]
    finally:
        shutil.rmtree(tmp)


def test_cli_buy_insufficient_cash_outputs_clean_json():
    """CLI 买入资金不足：应输出 {"ok": false, "error": ...}，退出码 1，无 Traceback。"""
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    tmp = tempfile.mkdtemp()
    try:
        workdir = os.path.join(tmp, "work")
        shutil.copytree(repo_root, workdir, ignore=shutil.ignore_patterns(
            "account", ".git", "__pycache__", "*.pyc", "tests"))

        def run(*cli_args):
            return subprocess.run(
                [sys.executable, "scripts/account.py", *cli_args],
                cwd=workdir, capture_output=True, text=True)

        run("init", "--cash", "1000")
        result = run("buy", "600519", "100", "--price", "1700.0", "--reason", "超额")
        assert result.returncode == 1
        assert "Traceback" not in result.stderr
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert "资金不足" in payload["error"]
    finally:
        shutil.rmtree(tmp)
