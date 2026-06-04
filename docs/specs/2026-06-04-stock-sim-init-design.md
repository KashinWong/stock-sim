# stock-sim 开户初始化功能 — 设计文档

日期：2026-06-04
状态：已确认，待进入实现计划

## 1. 目标

给 stock-sim skill 增加一个「开户初始化」环节：在 agent 首次使用账户前，
通过对话式引导收集必要的初始信息，分别落盘到职责清晰的三个文件，并据投资画像
微调初始策略。

## 2. 背景与动机

原 skill 的 `account.py init` 只从 `config.json` 读取固定 `initial_cash` 初始化账户，
没有采集用户的风险偏好、关注板块、运行节奏等信息。这导致：

- agent 无从知道用户的风险承受度与偏好行业，选股缺乏个性化锚点。
- 运行参数（token / 频率 / 复盘周期）散落或缺失，部署到新 hermes 时不明确。

因此需要一个显式的初始化场景，把"开始前总得知道的初始信息"系统化采集并落盘。

## 3. 已确认决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 采集哪些信息 | 初始本金 / 风险偏好 / 关注板块·行业 / 运行参数(token·频率·复盘周期) | 覆盖账户、画像、运行三类 |
| 采集形态 | agent 对话式引导（逐项问，带默认值，可跳过） | 符合 LLM 交互优势，低门槛 |
| 落盘方式 | 拆分 profile / account / config 三处各司其职 | 职责清晰，不污染账户真相源 |
| 是否新增脚本 | 不新增 profile.py | profile 是声明式偏好，无金融不变量，agent 按 schema 直接写 |

## 4. 落盘分工

| 信息 | 落到 | 写入方式 |
|------|------|----------|
| 初始本金 | `account/account.json` | `account.py init --cash <本金>` |
| 风险偏好 / 关注板块 / 运行频率 / 复盘周期 | `profile/profile.json`（新增） | agent 按 schema 直接写 |
| tushare token | `config/config.json` | agent 写入 `tushare_token` 字段 |

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

字段说明：
- `risk_preference`：保守 / 稳健 / 激进 之一。
- `focus_sectors`：字符串数组，留空 `[]` 表示全市场。
- `run_frequency`：运行节奏，如"每交易日"。
- `review_cycle`：复盘周期，如"每周"/"每月"。
- `notes`：自由备注。
- `created_at` / `updated_at`：YYYY-MM-DD。

## 5. 代码改动范围

**唯一代码改动**：`scripts/account.py` 的 `init` 增加可选 `--cash` 参数。

- CLI：`init` 子命令增加 `--cash`（type=float，可选）。
- 行为：`--cash` 提供时用其值；缺省时回退 `config.json` 的 `initial_cash`。
- `Account.init(initial_cash, date=None)` 签名不变（已接受 initial_cash），
  只是 main() 里决定传入哪个值。
- `initial_assets` 锚点继续等于实际初始本金（已实现）。

其余均为文档/模板/工作流改动，无新增脚本。

## 6. 工作流改动（SKILL.md 新增「场景 0：开户初始化」）

触发词："初始化" / "开户" / "第一次用" / "建账"。

agent 执行步骤：

1. **对话采集**：逐项询问，每项给默认值并允许跳过：
   - 初始本金（默认 1000000）
   - 风险偏好（保守/稳健/激进，默认稳健）
   - 关注板块·行业（可多个，留空=全市场）
   - 运行频率 & 复盘周期（默认 每交易日 / 每周）
   - tushare token（可留空，走 akshare→sina 兜底）
2. **建账**：`python scripts/account.py init --cash <本金>`。
3. **写画像**：把偏好类信息按 schema 写入 `profile/profile.json`。
4. **写 token**：若提供 token，写入 `config/config.json` 的 `tushare_token`
   （从 config.example.json 复制为 config.json 后修改）。
5. **画像驱动策略**：依据风险偏好/关注板块微调 `strategy/strategy.md` 的 v1，
   并在「策略演变记录」追加一行，理由写"初始化画像（风险偏好=X，关注=Y）"。
   - 激进：可提高单只仓位上限、放宽量能阈值。
   - 保守：降低单只仓位上限、提高现金保留。
   - 关注板块：选股时优先扫描这些行业。
6. **确认输出**：打印账户摘要 + 画像摘要。

## 7. 文件结构改动

```
stock-sim/
├── profile/
│   └── profile.example.json     # 新增：画像模板
├── config/
│   └── config.example.json      # 不变
├── scripts/
│   └── account.py               # 改动：init 加 --cash
├── SKILL.md                     # 新增场景 0
├── README.md                    # 部署步骤补充初始化说明
└── .gitignore                   # 新增忽略 profile/profile.json
```

`profile/profile.json` 为用户私有运行态，纳入 `.gitignore`（同 config.json / account / journal）；
仓库提供 `profile/profile.example.json` 模板。

## 8. 防自欺/纪律影响

- 画像不改变既有纪律（基准对比、策略举证、成交只走 account.py）。
- 画像作为策略初始锚点，但后续策略迭代仍须以交易证据为准，不得仅凭画像反复改策略。

## 9. 验收点

- `account.py init --cash 500000` 后 account.json 的 cash 与 initial_assets 均为 500000。
- `account.py init`（无 --cash）回退 config 的 initial_cash，行为与改动前一致。
- 仓库含 `profile/profile.example.json`，`.gitignore` 忽略 `profile/profile.json`。
- SKILL.md 含「场景 0：开户初始化」完整步骤。
- 现有 28 个单测仍全绿；新增针对 `--cash` 的测试通过。
