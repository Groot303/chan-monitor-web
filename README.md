# chan-monitor-web

美股缠论信号与自动模拟策略、A股连板研究工作台（FastAPI + 静态前端）。**美股规则为启发式，未确认信号可能重绘；A股为观察数据，不提供买卖点或自动交易。**

## 后续建设范围

美股与 A 股分别建设。A股已替换为连板研究：当日题材归因、涨停梯队、炸板观察、题材接力、昨日涨停表现和本机关注清单。旧A股缠论运行任务、页面和通知已停用。
不要默认把美股入场/筛选/撮合规则套用于 A 股。详见 [市场建设范围](docs/market-scope.md)。

## 信号类型
缠论 1/2/3 买卖点 + 中枢沿(ZG_S 上沿卖 / ZD_B 下沿买,`kind=pivot_edge`)。详情默认交互 K 线。

## 自动部署（CI/CD）
push 到 main → GitHub Actions「Deploy to VPS」→ SSH 到 VPS 执行 `/opt/chan-monitor/deploy.sh`：
1. `git pull --ff-only` 拉取最新代码（只快进，绝不 rebase/reset/force）
2. 只在 `api.py` / `api.service` 变更时才重启 `chan-api`；只改 `site/` 等静态内容时不重启
3. 健康检查通过才算部署成功；失败自动回滚

通常 30 秒内生效。**不需要任何人再去 VPS 上手动 `git pull`。**

## 结构
- `site/` 静态网页(无需构建):`index.html`、`style.css`、`app.js`、`chart.js`、`vendor/lightweight-charts.min.js`、`data/signals.json`、`data/charts/*.json`、`img/*.png`
- `scripts/build_data.py` 把分析输出(`out/signals.json`、`out/*_chan2.png`)整理进 `site/data` 与 `site/img`,并在有 CSV 时导出交互图 JSON
- `scripts/export_chart.py` 从 `data2_SYM_*.csv` + chan2 导出 `site/data/charts/{SYM}.json`(OHLC + 笔/线段/中枢/买卖点)。目前样例为 NVDA
- `chan.py` / `chan2.py` / `run2.py` 分析代码(从 chan-monitor 复制,GitHub Actions 需要它们才能在 runner 里重新计算)
- `.github/workflows/deploy.yml` 部署工作流（push main / 手动触发 → SSH 到 VPS 执行 `deploy.sh`）。旧的定时分析工作流 `update.yml` 已删除：调度由 VPS 后端 APScheduler 接管（pipeline 每 15 分钟，IBKR Flex 每 6 小时）。
- `DOCS_chan2.md` 规则与评分说明

## 本地预览
    cd site && python3 -m http.server 8000   # 打开 http://localhost:8000

本地重新计算:
    pip install -r requirements.txt   # 或使用项目 .venv
    mkdir -p out && python run2.py && python scripts/build_data.py out
(设置 `CACHED=1` 可复用已下载的 `data2_*.csv`。)
仅导出 NVDA 交互图:
    .venv/bin/python scripts/export_chart.py NVDA

交互 K 线目前先支持 **NVDA**(详情抽屉内可缩放拖动,叠加笔/线段/中枢/买卖点);其他标的仍用静态 PNG。

## 部署（已迁移，不再用 Cloudflare Pages）
Cloudflare Pages 已于 2026-10-13 停用。现由阿里云 VPS（FastAPI + Caddy，域名 `groot303.duckdns.org`）直接提供服务，部署见上文「自动部署（CI/CD）」。

## GitHub Actions 注意
- 部署工作流所需 Secrets（仓库 Settings → Secrets and variables → Actions）：`VPS_HOST`、`VPS_USER`、`VPS_SSH_KEY_B64`。
- 行情来自 Alpaca(IEX 免费实时)，API Key 放在 VPS `/opt/chan-monitor/.env`，不在 GitHub Secrets 里。失败标的记录在 `failures`。

## A股连板研究

只读接口 `/api/cn/research`，及[题材接力观察](docs/cn-theme-relay.md)接口 `/api/cn/relay`。后台独立按分钟采集东财观察池及开盘啦当日题材归因，保存原始来源和网站观察日志；无可用数据时明确显示未知或过期。交易日选择只展示实际已采集记录，不伪造历史回放。

详见 [连板研究数据契约与验收](docs/cn-limitup-research.md)。`run_cn.py`、`cn_symbols.py`及旧生成文件仅作为离线遗留资料保留，不参与网站运行、调度或通知。静态 `http.server` 仅可预览外观，研究数据需 FastAPI 后端。
