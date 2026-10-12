# 阶段1：仓库审查与接入计划（feat/us-strategy-lab）

生成时间：2026-10-12（本地审查，基于 `/workspace/chan-web` = `Groot303/chan-monitor-web`）

## 1. 仓库现状

| 项 | 结果 |
|---|---|
| 分支 | `main` @ `3ab5b16`（审查后切到 `feat/us-strategy-lab`） |
| 远程 | `origin https://github.com/Groot303/chan-monitor-web.git` |
| 工作区 | 仅未跟踪 `scripts/backtest_pivot_q.py`、`scripts/backtest_q.py`（本地缠论回测草稿，不纳入本阶段） |
| README | 纯静态缠论看板说明：本地预览、Actions 更新、Cloudflare Pages |
| 依赖 | `requirements.txt`: yfinance, pandas, numpy, matplotlib（无后端框架） |
| CI | `.github/workflows/update.yml`：工作日 UTC 14–21 每小时 :35 + 手动；跑 `run2.py` → `build_data.py` → Telegram → commit `site/`+`state/` |
| 前端 | `site/index.html` + `app.js` + `style.css` + Lightweight Charts；深色金融风；无构建步骤 |
| 数据库 | **无** |
| 环境变量示例 | **无** `.env.example`；Telegram 用 GitHub Secrets |
| IBKR | **无任何模块/引用** |
| 通知 | `scripts/notify_telegram.py` + `state/notified.json` 去重 |
| 回测 | 仅本地未入库缠论脚本；无正式策略回测引擎 |

### 目录要点
- `chan.py` / `chan2.py` / `run2.py`：缠论分析与出图
- `scripts/build_data.py`、`export_chart.py`、`notify_telegram.py`
- `site/`：静态站（Cloudflare Pages 输出目录）
- `data2_*.csv`：Yahoo 缓存（多数为指向 `/workspace/chan-monitor` 的 symlink，gitignore）
- `tests/`：缠论/评分/通知/中枢沿单元测试
- `out/`：本地产物（gitignore）

## 2. 技术栈与架构

**技术栈**：Python 3.12/3.13 + pandas/numpy/yfinance/matplotlib；前端原生 HTML/CSS/JS；GitHub Actions 定时批处理；Cloudflare Pages 静态托管。

**架构（当前）**：
```
Yahoo → run2.py/chan2 → out/signals.json + PNG
      → build_data.py → site/data + site/img + charts JSON
      → notify_telegram.py → Telegram
      → git commit → Cloudflare 自动部署
```

**数据流**：出站拉取行情 → 离线计算 → 静态 JSON 展示；无常驻后端、无用户登录、无账户凭据。

**扩展点（最佳接入）**：
1. 新增独立包 `quant/`（与缠论解耦），同一仓库内共存。
2. CLI：`scripts/run_strategy_backtest.py` 产出 `out/strategy_*.json|md` → 复制到 `site/data/strategy/`。
3. 前端新增「策略研究」视图，读取 JSON；无数据时明确「尚未连接 / 等待数据」。
4. 通知复用 Telegram 模式（后续阶段）；**不**改现有缠论 Actions 行为直到显式启用。
5. IBKR：仅留适配器接口 + stub，凭据走环境变量，不进仓库。

**不引入**：Django/FastAPI、数据库、真实下单、复杂实时推送（第一版不必要）。

## 3. 实施计划（阶段2–5，本分支）

| 阶段 | 内容 |
|---|---|
| 2 | 配置、Yahoo/CSV 适配器、IBKR stub、指标、市场状态 |
| 3 | 三策略（趋势/相对强度/突破）+ 0–100 可解释评分 |
| 4 | 风险引擎（0.5% 风险、10% 单股、最多4仓、10%回撤暂停新开） |
| 5 | 日线回测（信号日确认、次日开盘成交、成本模型）+ 报告 + 单元测试 + 前端模块 + README |

**首批标的**：SNDK, MU, AAOI, NVDA, TSLA, SPCX, RKLB  
**基准**：QQQ, SPY  
**成交规则**：信号在日线收盘后确认；**下一交易日开盘价**模拟买入/卖出；止损若开盘跳空穿越则以开盘价成交并记录。

### 预计修改/新增文件
- 新增：`quant/**`、`scripts/run_strategy_backtest.py`、`tests/test_quant_*.py`、`config/strategy.example.yaml`、`.env.example`、`site/data/strategy/`、前端 tab/样式
- 修改：`README.md`、`site/index.html`、`site/app.js`、`site/style.css`、`.gitignore`（如需）
- **不修改**：现有缠论核心逻辑、`update.yml` 默认行为（避免破坏生产更新）

### 风险
1. Yahoo 非官方、限流；SPCX/SNDK 上市短，样本不足。
2. 无 IBKR 时回测 ≠ 实盘可成交性；延迟/复权差异。
3. 策略参数未样本外优化；报告必须标注「研究用，非已验证优势」。
4. Cloudflare 静态站公开 URL：策略报告勿含账户隐私。
5. symlink CSV 在 Actions runner 上不存在 → 适配器必须能下载。

## 4. 阶段1结论

仓库可读、权限可用。采用 **静态站 + Actions + `quant/` 子模块** 增量集成；第一版禁止真实下单；在 `feat/us-strategy-lab` 开发，不 merge main、不生产部署。


---

## 阶段2–5 执行记录（2026-10-12）

### 修改/新增文件
- `quant/`：config、adapters(yahoo+ibkr stub)、indicators、market_regime、strategies×3、scoring、risk、backtest、paper、performance
- `scripts/run_strategy_backtest.py`
- `tests/test_quant_*.py`（4 个文件，16 用例）
- `config/strategy.example.yaml`、`.env.example`
- `site/index.html` / `app.js` / `style.css`：新增「策略研究」视图
- `site/data/strategy/backtest.json`：真实回测瘦身结果（非演示伪造）
- `README.md`：启动/回测/测试说明

### 测试（真实输出）
```
Ran 16 tests in ~0.57s — OK
(指标 / 风险 / 次日成交 / 跳空止损 / 重复订单 / 前视保护)
缠论既有 tests.test_score / test_notify / test_pivot_edge — OK（回归未破坏）
```

### 回测（Yahoo/CSV，2025-07-01 → 数据末日，含成本）
- 标的加载：AAOI, MU, NVDA, RKLB, SNDK, SPCX, TSLA；基准 QQQ/SPY；failures={}
- 已平仓 49 笔；总收益约 +26.1%；最大回撤约 -3.6%；胜率约 44.9%
- **同期 QQQ +37.4%、SPY +26.1%** → 本段样本策略未跑赢 QQQ；不得宣传为优势策略
- IBKR：尚未连接；live_trading=false

### 未解决问题 / 后续
1. 模拟交易日终批处理尚未接入 Actions（避免破坏现有缠论 workflow）
2. IBKR 实盘行情/持仓只读未实现
3. 财报日历过滤、样本外滚动验证未做
4. 策略通知未接入 Telegram
5. 前端权益曲线为简易 SVG，非交互图
6. SPCX/SNDK 上市较短，统计噪声大

### 约束遵守
- 未 merge main、未生产部署、未真实下单、未提交 .venv/secrets
