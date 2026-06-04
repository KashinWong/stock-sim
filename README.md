# stock-sim — 模拟炒股 Agent Skill

给 agent 一个虚拟 A 股账户进行模拟买卖：自主选股、每日报告、周期复盘、迭代策略。
所有状态以文件持久化，行情基于真实数据（三源兜底）。

## 部署（目标环境 agent 自举）

1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```

2. 准备配置：
   ```bash
   cp config/config.example.json config/config.json
   ```
   编辑 `config/config.json`，填入 `tushare_token`（在 https://tushare.pro 注册免费获取；
   留空则跳过 Tushare，仅用 AKShare + 新浪兜底）。其余字段可用默认值。

3. 初始化账户（首次部署）：
   ```bash
   python scripts/account.py init --cash 1000000
   ```
   交由 agent 执行场景 0「开户初始化」会更完整——它会对话采集风险偏好、关注板块、
   运行节奏并写入 `profile/profile.json`，同时据画像微调初始策略。详见 `SKILL.md`。

4. 验证行情通畅：
   ```bash
   python scripts/quote.py realtime 600519
   ```
   能返回价格 JSON 即部署成功。

## 目录约定

- `account/account.json`：账户唯一真相源（现金/持仓/盈亏）
- `account/trades.jsonl`：逐笔成交明细（只追加）
- `strategy/strategy.md`：自然语言策略文档（agent 自迭代）
- `profile/profile.json`：投资画像（风险偏好/关注板块/运行节奏，初始化生成，私有不入库）
- `journal/`：每日报告、复盘、操作总账

详细工作流见 `SKILL.md`。

## 故障排查

- **行情全部失败**：检查网络；akshare 偶发限频会自动 fallback 到新浪源；
  Tushare 需有效 token 且有积分权限。
- **akshare 接口报错**：`pip install -U akshare`，其接口随版本变动较快。
- **account.json 损坏**：删除 `account/account.json` 后重新 `account.py init`
  （注意会清空账户，trades.jsonl 保留历史）。
- **Python 版本**：需 3.9+，代码未使用 3.10+ 语法。
