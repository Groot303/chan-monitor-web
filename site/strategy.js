/* 美股自动策略观察页：浏览器仅GET，不提交交易、不创建账户、不依赖本地凭据。 */
(function () {
  'use strict';
  const root = document.getElementById('paper-app');
  if (!root) return;
  let busy = false, selected = '', generation = 0, lastReport = null;
  const escape = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = (value, digits = 2) => value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('zh-CN', {minimumFractionDigits:digits,maximumFractionDigits:digits});
  const time = value => value ? new Date(value).toLocaleString('zh-CN', {hour12:false}) : '等待观察';
  const row = (left,right,note) => '<div class="paper-row"><div><strong>'+escape(left)+'</strong><small>'+escape(note)+'</small></div><div class="paper-right">'+escape(right)+'</div></div>';
  const panel = (title, body) => '<section class="paper-panel"><h2>'+title+'</h2>'+body+'</section>';
  const empty = text => '<p class="paper-empty">'+escape(text)+'</p>';
  const visible = () => document.body.dataset.market !== 'cn' && !document.getElementById('view-paper').hidden && !document.hidden;

  function curve(points) {
    if (points.length < 2) return empty('收益曲线从真实运行后的估值点开始积累，不补画历史收益。');
    const values = points.map(p => p.value), lo = Math.min(...values), hi = Math.max(...values), range = hi-lo || 1;
    const coords = values.map((v,i) => (10+i*580/(values.length-1)).toFixed(2)+','+(125-(v-lo)*95/range).toFixed(2)).join(' ');
    return '<svg class="paper-curve" viewBox="0 0 600 160" role="img" aria-label="策略实际运行以来的模拟净资产曲线"><line x1="10" y1="130" x2="590" y2="130"/><polyline fill="none" stroke="currentColor" stroke-width="2.5" points="'+coords+'"/><text x="10" y="154">'+escape(time(points[0].time))+'</text><text x="590" y="154" text-anchor="end">'+escape(time(points[points.length-1].time))+'</text></svg>';
  }

  function render(report) {
    lastReport = report;
    const a = report.account, r = report.runtime, cfg = report.rules;
    const rulesOpen = root.querySelector('.paper-model')?.open;
    const delayed = !r.last_tick || Date.parse(a.server_time)-Date.parse(r.last_tick)>180000;
    const status = delayed ? '等待自动调度' : ({running:'自动观察中',environment_unknown:'环境未知 · 暂停买入',environment_blocked:'熊市环境 · 暂停买入',data_unknown:'数据未知 · 等待核验',warming_up:'建立观察基线'})[r.status] || r.status;
    let html = '<div class="paper-panel"><div class="paper-top"><div><div class="paper-eyebrow">'+escape(cfg.version)+' · 全自动模拟</div><strong id="strategy-status">'+escape(status)+'</strong></div><button type="button" class="btn" id="strategy-refresh">刷新</button></div>'+
      '<p class="paper-note">'+escape(r.detail)+'<br>系统在服务器每分钟运行，关闭页面后继续执行。这里只查看，不需要手动买卖。</p><div class="paper-eyebrow">模拟净资产</div><div class="paper-balance">$'+num(a.equity)+'</div><div class="paper-return">累计收益 '+num(a.return_pct)+'% · 初始 $'+num(a.initial,0)+'</div><div class="paper-metrics">'+
      [['可用现金','$'+num(a.available_cash)],['持仓数量',a.positions.length+' 只'],['累计费用','$'+num(a.fees)],['已记录最大回撤',num(a.max_drawdown_pct)+'%'],['已平仓批次',a.closed_exits+' 笔'],['已平仓胜率',num(a.win_rate_pct)+'%']].map(([k,v])=>'<div><span>'+k+'</span><strong>'+escape(v)+'</strong></div>').join('')+'</div>'+curve(a.curve)+'<p class="paper-note">最后决策检查：'+escape(time(r.last_tick))+'<br>估值：'+(a.valuation_status==='known'?'行情可用':'行情未知，收益暂不展示')+'。模拟结果尚未验证盈利能力；最大回撤仅基于已记录估值点。</p></div>';
    const comparison = a.benchmark_comparison;
    if (comparison) html += panel('同区间参考',row('纳斯达克综合指数',num(comparison.benchmark_return_pct)+'%',time(comparison.since)+' 至 '+time(comparison.as_of))+row('策略模拟账户',num(comparison.account_return_pct)+'%','仅比较双方都有同步估值的区间'));
    html += panel('自动持仓',a.positions.length ? a.positions.map(p=>{
      const stop = a.stops.find(s=>s.symbol===p.symbol && ['active','triggered'].includes(s.status));
      return row(p.symbol,p.qty+' 股 · $'+num(p.value),'浮动盈亏 $'+num(p.unrealized_pnl)+(p.quote?.fresh?'':'（估值待更新）')+(stop?' · 自动止损 $'+num(stop.price)+(stop.status==='triggered'?'（已触发，等待可成交行情）':''):' · 等待核验止损状态'));
    }).join('') : empty('尚无持仓。等待上线后首次新出现、满足V1条件的信号，不追补历史买点。'));
    const pending = a.orders.filter(o=>o.status==='pending');
    html += panel('等待成交',pending.length ? pending.map(o=>row(o.symbol+' · '+(o.side==='buy'?'自动买入':'自动卖出'),o.qty+' 股',time(o.submitted)+' · '+o.message)).join('') : empty('没有待成交订单。'));
    const fills = a.fills.filter(f=>!selected || f.symbol===selected).slice(-30).reverse();
    html += panel('成交记录'+(selected?' · '+escape(selected):''),fills.length ? fills.map(f=>row(f.symbol+' · '+(f.side==='buy'?'买入':'卖出'),f.qty+' 股 × $'+num(f.price),time(f.time || f.market_bar.open_time)+' · '+(f.execution_reason==='automatic_stop'?'自动止损':'策略信号')+' · 费用 $'+num(f.fee)+(f.realized_pnl!=null?' · 已实现 $'+num(f.realized_pnl):''))).join('') : empty('还没有对应的模拟成交。'));
    const decisions = report.decisions.filter(e=>!selected || e.payload.symbol===selected).slice(-50).reverse();
    const labels = {buy:'提交买入',sell:'提交卖出',skip:'跳过',baseline:'历史基线',repaint:'信号重绘'};
    html += panel('决策与原因'+(selected?' · '+escape(selected)+' <button type="button" class="btn" id="strategy-clear">查看全部</button>':''),decisions.length ? decisions.map(e=>row((e.payload.symbol || '账户')+' · '+(labels[e.payload.action] || e.payload.action),time(e.time),e.payload.reason+(e.payload.first_seen_time?' · 首次实际观察 '+time(e.payload.first_seen_time):''))).join('') : empty('等待服务器记录首次观察。'));
    html += '<details class="paper-panel paper-model"'+(rulesOpen?' open':'')+'><summary>V1执行规则与时序说明</summary><p>范围：仅美股监控股票，纳指仅作比较。初始模拟资金 $'+num(cfg.initial,0)+'。日线方向向上，且已完成SPY日线收盘不低于200日均线，才允许新买入。</p><p>入场：已确认的30分钟二买/三买。退出：已确认的30分钟一卖/二卖/三卖，或止损。不执行PRE、盘整背驰和中枢沿触及提示。每个信号只处理一次，跳过后不因环境改善补买；不加仓、不做空。</p><p>仓位：每只最多分配初始资金的10%，最多5只。新买单附带信号极值价下方3%的自动止损。跳空跌破止损则取消入场。买入成交K线内不推测触价；止损从该K线收盘后生效。</p><p>时序：排除尚未收盘的数据，另留15分钟数据稳定缓冲；来源超过45分钟则暂停新决策。首次完整快照只建基线，不补单。首次观察/确认时间来自服务器日志，极值时间不等于可交易时间。</p><p>撮合：决策后下一根常规时段5分钟K线的开盘价，加单边5bp滑点及费用。止损遇开盘跳空按开盘价模拟，盘中触及则在收盘识别、下根可成交开盘退出。缺失行情继续等待，不选择后来的有利价格补填。</p><p>卖出和止损不依赖市场环境转好。自动撮合基于已完成K线，记录会晚于模拟成交时点；它不是逐笔行情成交保证。日线方向来自原检测器，结构仍可能重绘。历史手动练习账户独立保留，不并入此账户。</p><p>当前收益用于观察这套明确规则的运行情况，不代表已经验证的实盘收益。</p></details>';
    root.innerHTML = html;
    root.querySelector('#strategy-refresh').addEventListener('click',load);
    root.querySelector('#strategy-clear')?.addEventListener('click',()=>{ selected=''; render(lastReport); });
  }

  async function load() {
    if (!visible() || busy) return;
    busy=true;
    const version=++generation;
    if (!lastReport) root.innerHTML=empty('正在读取服务器自动策略…');
    try {
      const response=await fetch('/api/strategy/us',{cache:'no-store'});
      if (!response.ok) throw new Error(response.status===503?'自动模拟调度尚未运行，请稍后刷新。':'暂时无法读取自动策略，保留最后一次显示的数据。');
      const report=await response.json();
      if (version===generation && visible()) render(report);
    } catch(error) {
      if (version===generation && visible()) {
        root.querySelector('.strategy-error')?.remove();
        const message=document.createElement('p');message.className='paper-error strategy-error';message.setAttribute('role','alert');message.textContent=error.message;
        root.prepend(message);
        if (lastReport && root.querySelector('#strategy-status')) root.querySelector('#strategy-status').textContent='连接中断 · 显示上次数据';
      }
    } finally {busy=false;if(version!==generation && visible())queueMicrotask(load);}
  }
  window.addEventListener('chan-view',event=>{if(event.detail?.view==='paper' || event.detail==='paper')queueMicrotask(load);});
  window.addEventListener('strategy-observe-symbol',event=>{selected=event.detail?.symbol || '';if(lastReport)render(lastReport);});
  window.addEventListener('chan-market',()=>{generation++;lastReport=null;if(document.body.dataset.market==='cn')root.innerHTML='';else load();});
  window.addEventListener('hashchange',load);
  document.addEventListener('visibilitychange',load);
  setInterval(load,30000);
  load();
}());
