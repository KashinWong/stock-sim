# 开户初始化功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 stock-sim 增加「开户初始化」环节，对话采集初始信息并分三处落盘（profile/account/config），据画像微调初始策略。

**Architecture:** 唯一代码改动是 `account.py init` 增加可选 `--cash` 参数；其余为新增 profile 模板、SKILL.md 场景 0、README 与 .gitignore 文档改动。profile 无脚本，由 agent 按 schema 直接写。

**Tech Stack:** Python 3.9（stdlib argparse/json）、Markdown 文档、JSON 模板。

---

### Task 1: account.py init 增加 `--cash` 参数

**Files:**
- Modify: `scripts/account.py:146`（init 子命令定义）和 `scripts/account.py:160-162`（init 分支）
- Test: `tests/test_account.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_account.py` 末尾追加（该文件用 `Account` 类直接测，CLI 的 `--cash` 行为通过验证 `init` 接受显式 cash 值覆盖来体现；此处补一个显式覆盖测试）：

```python
def test_init_with_explicit_cash_overrides_default():
    tmp = tempfile.mkdtemp()
    try:
        e = make_engine(tmp)
        e.init(initial_cash=500000, date="2026-06-04")
        assert e.state["cash"] == 500000
        assert e.state["initial_assets"] == 500000
    finally:
        shutil.rmtree(tmp)
```

- [ ] **Step 2: 运行测试确认通过（init 已接受 initial_cash）**

Run: `python -m pytest tests/test_account.py::test_init_with_explicit_cash_overrides_default -v`
Expected: PASS（`Account.init` 已支持 initial_cash；本测试锁定 initial_assets 也随之锚定）

注：本任务的核心是 CLI 层，`Account.init` 无需改。下面改 CLI。

- [ ] **Step 3: 给 init 子命令加 `--cash` 参数**

修改 `scripts/account.py` 第 146 行：

```python
    p_init = sub.add_parser("init")
    p_init.add_argument("--cash", type=float, default=None,
                        help="初始本金；缺省回退 config.json 的 initial_cash")
```

- [ ] **Step 4: init 分支使用 `--cash` 或回退 config**

修改 `scripts/account.py` 第 160-162 行的 init 分支：

```python
    if args.cmd == "init":
        cash = args.cash if args.cash is not None else cfg["initial_cash"]
        e.init(initial_cash=cash)
        print(json.dumps({"ok": True, "cash": e.state["cash"]}, ensure_ascii=False))
```

- [ ] **Step 5: 手动验证 CLI 两条路径**

Run:
```bash
cd /tmp && rm -rf sim_init_test && cp -r /Users/hjx/projects/stock-sim sim_init_test && cd sim_init_test
python scripts/account.py init --cash 500000
python -c "import json; d=json.load(open('account/account.json')); print(d['cash'], d['initial_assets'])"
python scripts/account.py init
python -c "import json; d=json.load(open('account/account.json')); print(d['cash'], d['initial_assets'])"
cd /tmp && rm -rf sim_init_test
```
Expected: 第一组打印 `500000.0 500000.0`；第二组打印 `1000000.0 1000000.0`（回退 config 默认）。

- [ ] **Step 6: 运行全部账户测试**

Run: `python -m pytest tests/test_account.py -v`
Expected: 全部 PASS（原 9 个 + 新增 1 个 = 10 个）

- [ ] **Step 7: 提交**

```bash
git add scripts/account.py tests/test_account.py
git commit -m "feat: account.py init 增加 --cash 参数，支持初始化指定本金"
```

---

### Task 2: 新增 profile.example.json 模板与 .gitignore 忽略

**Files:**
- Create: `profile/profile.example.json`
- Modify: `.gitignore`

- [ ] **Step 1: 创建画像模板**

创建 `profile/profile.example.json`：

```json
{
  "risk_preference": "稳健",
  "focus_sectors": [],
  "run_frequency": "每交易日",
  "review_cycle": "每周",
  "notes": "",
  "created_at": "",
  "updated_at": ""
}
```

- [ ] **Step 2: .gitignore 忽略用户私有画像**

在 `.gitignore` 的「本地配置」段落下方追加：

```
# 用户私有投资画像（由初始化对话生成）
profile/profile.json
```

- [ ] **Step 3: 验证模板是合法 JSON 且会被忽略**

Run:
```bash
python -c "import json; json.load(open('profile/profile.example.json')); print('ok')"
cp profile/profile.example.json profile/profile.json
git check-ignore profile/profile.json
rm profile/profile.json
```
Expected: 打印 `ok`，且 `git check-ignore` 输出 `profile/profile.json`（确认被忽略）。

- [ ] **Step 4: 提交**

```bash
git add profile/profile.example.json .gitignore
git commit -m "feat: 新增 profile.example.json 投资画像模板，gitignore 忽略用户画像"
```

---

### Task 3: SKILL.md 新增「场景 0：开户初始化」

**Files:**
- Modify: `SKILL.md`（在「## 工具命令」之后、「## 场景 A」之前插入场景 0；并在 init 命令示例处补 `--cash`）

- [ ] **Step 1: 在工具命令的账户段补 init --cash 示例**

修改 `SKILL.md` 账户命令块，把 `python scripts/account.py show` 上方补一行 init 示例。找到：

```bash
# 账户
python scripts/account.py show                      # 查账
```

改为：

```bash
# 账户
python scripts/account.py init --cash 1000000       # 开户（初始化，仅首次）
python scripts/account.py show                      # 查账
```

- [ ] **Step 2: 插入场景 0 段落**

在 `## 场景 A：每日选股交易（收盘后）` 之前插入：

```markdown
## 场景 0：开户初始化（首次使用）

当用户说"初始化""开户""第一次用""建账"时，通过对话逐项采集初始信息（每项给默认值、可跳过）：

1. **对话采集**：
   - 初始本金（默认 1000000）
   - 风险偏好：保守 / 稳健 / 激进（默认稳健）
   - 关注板块·行业（可多个，留空=全市场）
   - 运行频率 & 复盘周期（默认 每交易日 / 每周）
   - tushare token（可留空，走 akshare→新浪兜底）
2. **建账**：`python scripts/account.py init --cash <本金>`。
3. **写画像**：把偏好信息按 schema 写入 `profile/profile.json`（从 `profile/profile.example.json` 复制后填写，含 created_at/updated_at）。
4. **写 token**（若提供）：`cp config/config.example.json config/config.json`（若尚无），填入 `tushare_token`。
5. **画像驱动策略**：依据风险偏好/关注板块微调 `strategy/strategy.md` 的 v1，并在「策略演变记录」追加一行，理由写"初始化画像（风险偏好=X，关注=Y）"：
   - 激进：可提高单只仓位上限、放宽量能阈值。
   - 保守：降低单只仓位上限、提高现金保留。
   - 关注板块：选股时优先扫描这些行业。
6. **确认输出**：打印账户摘要（现金/初始本金）+ 画像摘要（风险偏好/关注板块/节奏）。

### profile.json schema

```json
{
  "risk_preference": "稳健",
  "focus_sectors": ["白酒", "新能源"],
  "run_frequency": "每交易日",
  "review_cycle": "每周",
  "notes": "",
  "created_at": "2026-06-04",
  "updated_at": "2026-06-04"
}
```

```

- [ ] **Step 3: 验证 SKILL.md 结构完整**

Run: `grep -n "场景 0\|场景 A\|profile.json\|init --cash" SKILL.md`
Expected: 能看到「场景 0：开户初始化」「场景 A」标题、profile.json schema、init --cash 示例。

- [ ] **Step 4: 提交**

```bash
git add SKILL.md
git commit -m "docs: SKILL.md 新增场景 0 开户初始化工作流"
```

---

### Task 4: README 部署步骤补充初始化说明

**Files:**
- Modify: `README.md`（部署第 3 步与目录约定）

- [ ] **Step 1: 部署第 3 步改为初始化引导**

修改 `README.md` 第 20-23 行：

```markdown
3. 初始化账户（首次部署）：
   ```bash
   python scripts/account.py init --cash 1000000
   ```
   交由 agent 执行场景 0「开户初始化」会更完整——它会对话采集风险偏好、关注板块、
   运行节奏并写入 `profile/profile.json`，同时据画像微调初始策略。详见 `SKILL.md`。
```

- [ ] **Step 2: 目录约定补充 profile**

修改 `README.md` 目录约定列表，在 `strategy/strategy.md` 行之后追加：

```markdown
- `profile/profile.json`：投资画像（风险偏好/关注板块/运行节奏，初始化生成，私有不入库）
```

- [ ] **Step 3: 验证 README 引用一致**

Run: `grep -n "init --cash\|profile/profile.json\|场景 0\|开户初始化" README.md`
Expected: 能看到 init --cash 示例与 profile.json 目录说明。

- [ ] **Step 4: 提交**

```bash
git add README.md
git commit -m "docs: README 部署步骤补充开户初始化与 profile 说明"
```

---

### Task 5: 更新冒烟测试文档计数与初始化用例

**Files:**
- Modify: `docs/smoke-test.md`

- [ ] **Step 1: 读取当前冒烟文档**

Run: `grep -n "28\|init\|测试" docs/smoke-test.md`
Expected: 看到现有测试计数（28）与相关条目，确认要更新处。

- [ ] **Step 2: 更新单测计数 28 → 29 并补 init --cash 用例**

把文档中「28 个单测」相关表述更新为「29 个单测」，并在手动冒烟用例处追加一条：

```markdown
- `python scripts/account.py init --cash 500000` → account.json 的 cash 与 initial_assets 均为 500000.0
```

（若文档结构不同，按其既有格式插入等价内容。）

- [ ] **Step 3: 验证**

Run: `grep -n "29\|init --cash" docs/smoke-test.md`
Expected: 计数已更新且含 init --cash 用例。

- [ ] **Step 4: 提交**

```bash
git add docs/smoke-test.md
git commit -m "docs: 冒烟文档更新单测计数与初始化用例"
```

---

## Self-Review

- **Spec coverage:** §4 落盘分工→Task 1(本金)+Task 2(profile)+Task 3(token 写入步骤)；§5 代码改动→Task 1；§6 场景 0→Task 3；§7 文件结构/.gitignore→Task 2；§9 验收点→Task 1/2/5 覆盖。README→Task 4。全部有任务对应。
- **Placeholder scan:** 无 TBD/TODO；每个代码步骤含实际代码或精确命令。
- **Type consistency:** profile.json schema 在 spec、Task 2 模板、Task 3 SKILL.md 三处一致（risk_preference/focus_sectors/run_frequency/review_cycle/notes/created_at/updated_at）。`--cash` 参数名在 Task 1/3/4/5 一致。
