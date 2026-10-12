# chan-monitor-web

缠论(周线/日线/30分钟)信号的纯静态可视化网页。**启发式规则,未回测,不构成投资建议,未确认信号可能重绘。**

## 信号类型
缠论 1/2/3 买卖点 + 中枢沿(ZG_S 上沿卖 / ZD_B 下沿买,`kind=pivot_edge`)。详情默认交互 K 线。

## 结构
- `site/` 静态网页(无需构建):`index.html`、`style.css`、`app.js`、`chart.js`、`vendor/lightweight-charts.min.js`、`data/signals.json`、`data/charts/*.json`、`img/*.png`
- `scripts/build_data.py` 把分析输出(`out/signals.json`、`out/*_chan2.png`)整理进 `site/data` 与 `site/img`,并在有 CSV 时导出交互图 JSON
- `scripts/export_chart.py` 从 `data2_SYM_*.csv` + chan2 导出 `site/data/charts/{SYM}.json`(OHLC + 笔/线段/中枢/买卖点)。目前样例为 NVDA
- `chan.py` / `chan2.py` / `run2.py` 分析代码(从 chan-monitor 复制,GitHub Actions 需要它们才能在 runner 里重新计算)
- `.github/workflows/update.yml` 美股交易时段工作日每小时(UTC :35,14-21点)及手动触发,安装依赖、运行分析、重建 `site/` 并提交回仓库
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

## 部署到 Cloudflare Pages
1. Cloudflare 控制台 → Workers & Pages → Create → Pages → Connect to Git,授权并选择本仓库(私有仓库可用)。
2. Framework preset: None;**Build command: 留空**;**Build output directory: `site`**。
3. 保存部署。之后 Actions 每次把更新提交到主分支,Cloudflare 会自动重新部署。

## GitHub Actions 注意
- 仓库 Settings → Actions → General → Workflow permissions 需为 "Read and write permissions"(workflow 已声明 `contents: write`,但仓库/组织级默认若更严格会覆盖)。
- 定时任务可能延迟几分钟;仓库 60 天无活动时 GitHub 会暂停定时任务(本流程会提交所以通常不会)。
- Yahoo Finance 为非官方接口,runner IP 可能被限流,导致某些标的失败(记录在 `failures`)。
