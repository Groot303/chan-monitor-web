# chan-monitor-web

缠论(周线/日线/30分钟)信号的纯静态可视化网页。**启发式规则,未回测,不构成投资建议,未确认信号可能重绘。**

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
