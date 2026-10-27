/* 手动模拟盘只调用独立 paper API；资金、时间和成交账本由服务器维护。 */
(function () {
  'use strict';
  const root=document.getElementById('paper-app');
  const read=k=>{try{return localStorage.getItem(k);}catch{return null;}};
  const market='us';
  let intent=null,state=null,version=0;
  const $=id=>document.getElementById(id),esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number=x=>x==null?'—':Number(x).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
  const pct=x=>x==null?'—':(x>0?'+':'')+Number(x).toFixed(Math.abs(x)>0&&Math.abs(x)<.01?4:2)+'%';
  const percent=x=>x==null?'—':Number(x).toFixed(Math.abs(x)>0&&Math.abs(x)<.01?4:2)+'%';
  const date=x=>x?new Date(x).toLocaleString('zh-CN',{timeZone:'America/New_York',hour12:false}):'—';
  const key=()=>`chan.paper.${market}.v1`, credential=()=>read(key());
  const error=e=>{const box=$('paper-error');if(box)box.textContent=e.message||String(e);};
  async function api(path,body){
    const response=await fetch('/api/paper/'+path,{method:body===undefined?'GET':'POST',cache:'no-store',
      headers:{'Content-Type':'application/json',...(credential()?{Authorization:'Bearer '+credential()}:{})},body:body===undefined?undefined:JSON.stringify(body)});
    let data;try{data=await response.json();}catch{throw new Error('模拟服务响应异常，请稍后刷新');}
    if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'模拟服务暂不可用');
    return data;
  }
  const models=`<details class="paper-model paper-panel"><summary>成交规则与统计口径</summary><p>美股美元练习账户，只练习整股做多。手动练习不代表通过策略筛选。提交后，按严格晚于服务器收单时间的后续已完成5分钟K线开盘价，加买卖各5基点不利滑点模拟成交。信号历史价格不会作为成交价格。成交可能延迟到下一次打开或刷新时记录。</p><p>假设费用：美股每股0.005美元，最低1美元。以上是固定练习模型，不代表你的券商真实费率。美股使用简化资金可用模型，未模拟结算/PDT；未处理分红和拆股，遇公司行动需停止解读收益。平坦K线保守等待。指数不能买卖。</p><p>计划止损只作复盘记录，不自动触发。待成交单7天到期；无法核验的缺失行情不补造成交。收益含模型费用；回撤只根据已采样净值，未覆盖根内波动。胜率按卖出笔数统计，减仓也算一笔，不能作为策略有效性证明。</p><p>账户凭据只保存在此浏览器，清除网站数据可能失去访问权；账户和记录保存在服务器。没有修改历史订单、删除成交或回填旧订单的入口。请定期导出记录。</p></details>`;
  function shell(content){root.innerHTML=`<div class="paper-top"><div><div class="paper-eyebrow">美股 · USD · 美东时间</div><p class="muted small">手动练习 · 与真实持仓独立</p></div><button class="btn ghost" id="paper-refresh" type="button">刷新</button></div><p id="paper-error" class="paper-error" role="alert"></p>${content}${models}`;$('paper-refresh').onclick=()=>load();}
  async function load(){
    const epoch=++version,selected=market;
    if(!credential()){
      shell(`<section class="paper-panel"><h2>开始记录你的决策</h2><p class="muted">用独立模拟资金练习入场、减仓和平仓，查看成本后的收益。</p><form id="paper-create" class="paper-form"><label class="wide">初始模拟资金<input name="initial" type="number" min="1000" max="10000000" step="1" value="100000" required></label><button class="btn primary wide" type="submit">创建美元练习账户</button></form><p class="paper-note">创建后初始资金固定；不会自动执行策略。</p></section>`);
      $('paper-create').onsubmit=async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{localStorage.setItem('chan.paper.storage-test','ok');localStorage.removeItem('chan.paper.storage-test');const data=await api('accounts',{market:selected,initial:Number(new FormData(e.target).get('initial'))});localStorage.setItem(`chan.paper.${selected}.v1`,data.token);if(market===selected)await load();}catch(err){error(err);}finally{button.disabled=false;}};
      return;
    }
    try{
      const result=await api('account');
      if(epoch!==version||selected!==market)return;
      state=result;render();
      const response=await fetch('/api/signals',{cache:'no-store'});
      if(!response.ok)throw new Error('标的列表暂不可用');
      const snapshot=await response.json();if(epoch!==version)return;
      const symbols=Object.keys(snapshot.symbols||{}).filter(s=>/^[A-Z][A-Z0-9.\-]{0,14}$/.test(s));
      orderForm(symbols);
    }catch(err){if(epoch!==version)return;shell('<section class="paper-panel"><h2>练习账户暂不可用</h2><p class="muted">请保留当前浏览器数据，稍后刷新重试。</p></section>');error(err);}
  }
  function curve(points){
    if(points.length<2)return '<p class="paper-empty">新行情到来后开始积累收益曲线。</p>';
    const low=Math.min(...points.map(p=>p.value)),high=Math.max(...points.map(p=>p.value)),span=high-low||1;
    const coords=points.map((p,i)=>`${10+i/(points.length-1)*300},${120-(p.value-low)/span*100}`).join(' ');
    return `<svg class="paper-curve" viewBox="0 0 320 150" role="img" aria-label="模拟账户已采样资产曲线"><line x1="10" y1="125" x2="310" y2="125"/><polyline points="${coords}" fill="none" stroke="currentColor" stroke-width="2.5"/><text x="10" y="145">${esc(date(points[0].time).split(' ')[0])}</text><text x="310" y="145" text-anchor="end">${esc(date(points.at(-1).time).split(' ')[0])}</text></svg>`;
  }
  function render(){
    const s=state,labels={pending:'待成交',filled:'已成交',canceled:'已撤销',rejected:'未成交'};
    const metrics=[['可用现金',number(s.available_cash)],['已付模型费用',number(s.fees)],['采样最大回撤',percent(s.max_drawdown_pct)],['卖出笔数',s.closed_exits],['卖出胜率',percent(s.win_rate_pct)],['平均盈利/亏损',s.payoff_ratio==null?'—':number(s.payoff_ratio)]];
    const positions=s.positions.map(p=>`<div class="paper-row"><div><strong>${esc(p.symbol)}</strong><small>${p.qty} 股 · 含买入费用成本 ${number(p.basis/p.qty)}</small><small>行情 ${esc(date(p.quote?.time))}${p.quote?.fresh?'':' · 待更新'}</small></div><div class="paper-right"><strong>${number(p.value)}</strong><small>浮动盈亏 ${number(p.unrealized_pnl)}</small><button type="button" class="btn ghost" data-sell="${esc(p.symbol)}" data-qty="${p.qty}">模拟卖出</button></div></div>`).join('');
    const orders=s.orders.slice(0,30).map(o=>`<div class="paper-row"><div><strong>${esc(o.symbol)} · ${o.side==='buy'?'买入':'卖出'} ${o.qty} 股</strong><small>${esc(date(o.submitted))} · ${esc(labels[o.status]||o.status)}</small><small>${esc(o.message)}</small><small>理由：${esc(o.reason)}${o.plan_stop?' · 计划止损 '+number(o.plan_stop):''}</small></div>${o.status==='pending'?`<button type="button" class="btn ghost" data-cancel="${esc(o.id)}">撤单</button>`:''}</div>`).join('');
    const fills=s.fills.slice().reverse().slice(0,30).map(f=>`<div class="paper-row"><div><strong>${esc(f.symbol)} · ${f.side==='buy'?'买入':'卖出'} ${f.qty} 股</strong><small>${esc(date(f.market_bar.open_time))}</small><small>记录于 ${esc(date(f.recorded_at))}</small></div><div class="paper-right"><strong>${number(f.price)}</strong><small>费用 ${number(f.fee)}</small>${f.side==='sell'?`<small>已实现 ${number(f.realized_pnl)}</small>`:''}</div></div>`).join('');
    const b=s.benchmark_comparison;
    shell(`<section class="paper-panel"><div class="paper-eyebrow">模拟总资产 · ${esc(s.currency)}</div><div class="paper-balance">${number(s.equity)}</div><div class="paper-return">累计收益 ${pct(s.return_pct)}${s.valuation_status==='unknown'?' · 行情不足，当前净值待核验':''}</div><div class="paper-metrics">${metrics.map(([k,v])=>`<div><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('')}</div></section><section class="paper-panel"><h2>资产变化</h2>${curve(s.curve)}<p class="paper-note">${b?`同区间账户 ${pct(b.account_return_pct)} · 纳指 ${pct(b.benchmark_return_pct)}<br>对比始于 ${esc(date(b.since))}，截至 ${esc(date(b.as_of))}`:'基准数据尚不足；积累同步行情后再比较。'}</p></section><section class="paper-panel" id="paper-order-section"><h2>新的练习单</h2><div id="paper-order-form"><p class="muted">读取可练习标的…</p></div></section><section class="paper-panel"><h2>模拟持仓</h2>${positions||'<p class="paper-empty">还没有模拟持仓。</p>'}</section><section class="paper-panel"><h2>练习订单</h2>${orders||'<p class="paper-empty">提交第一笔练习单后，理由和状态会记录在这里。</p>'}</section><section class="paper-panel"><h2>成交与复盘</h2>${fills||'<p class="paper-empty">尚未产生模拟成交。</p>'}<button class="btn ghost" id="paper-export" type="button">导出全部练习记录</button></section>`);
    root.querySelectorAll('[data-cancel]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{await api(`orders/${button.dataset.cancel}/cancel`,{});await load();}catch(err){error(err);button.disabled=false;}});
    root.querySelectorAll('[data-sell]').forEach(button=>button.onclick=()=>{const form=$('paper-ticket');if(!form)return;form.elements.symbol.value=button.dataset.sell;form.elements.side.value='sell';form.elements.qty.value=button.dataset.qty;form.elements.stop.value='';form.dispatchEvent(new Event('input',{bubbles:true}));$('paper-order-section').scrollIntoView({behavior:'smooth'});form.elements.reason.focus();});
    $('paper-export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(state,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=`paper-${market}-${new Date().toISOString().slice(0,10)}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  }
  function orderForm(symbols){
    const selected=intent?.market===market?intent.symbol:null;intent=null;
    $('paper-order-form').innerHTML=`${selected&&!symbols.includes(selected)?'<p class="paper-note">该标的是指数或缺少支持的股票行情，无法模拟买卖。</p>':''}<form class="paper-form" id="paper-ticket"><label>标的<select name="symbol" required>${symbols.map(s=>`<option ${s===selected?'selected':''}>${esc(s)}</option>`).join('')}</select></label><label>方向<select name="side"><option value="buy">模拟买入</option><option value="sell">模拟卖出</option></select></label><label>数量（股）<input name="qty" type="number" required min="1" step="1" value="10"></label><label>计划止损（可选，仅记录）<input name="stop" type="number" min="0.01" step="0.01" inputmode="decimal"></label><label class="wide">这笔练习的理由<textarea name="reason" required maxlength="500" rows="2" placeholder="例如：日线方向向上，观察30分钟回踩"></textarea></label><button class="btn primary wide" type="submit" ${symbols.length?'':'disabled'}>预览模拟订单</button><div class="paper-preview" id="paper-preview"></div></form>`;
    const form=$('paper-ticket');let prepared=null;
    form.oninput=()=>{prepared=null;$('paper-preview').innerHTML='';form.elements.stop.disabled=form.elements.side.value==='sell';if(form.elements.stop.disabled)form.elements.stop.value='';};
    if(selected&&symbols.includes(selected))form.elements.qty.focus();
    form.onsubmit=async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{
      const fields=new FormData(form),side=fields.get('side'),stop=fields.get('stop');
      const payload={symbol:fields.get('symbol'),side,qty:Number(fields.get('qty')),reason:fields.get('reason'),plan_stop:stop?Number(stop):null,request_key:crypto.randomUUID()};
      const p=await api('preview',payload);prepared=payload;
      $('paper-preview').innerHTML=`参考价 ${number(p.reference_price)} · ${esc(date(p.quote_time))}<br>参考金额 ${number(p.estimated_notional)} · 估算费用 ${number(p.estimated_fee)}<br>${side==='buy'?'预留 '+number(p.reserve)+'（含5%跳空缓冲）<br>':''}实际模拟成交价取提交后的后续行情，可能跳空或无法成交。${esc(p.constraint_note||'')}<br><button class="btn primary" type="button" id="paper-confirm">确认提交模拟单</button>`;
      $('paper-confirm').onclick=async event=>{event.target.disabled=true;try{if(!prepared)throw new Error('请重新预览');await api('orders',prepared);await load();}catch(err){error(err);event.target.disabled=false;}};
    }catch(err){error(err);}finally{button.disabled=false;}};
  }
  window.addEventListener('paper-order-intent',e=>{if(e.detail.market==='us')intent=e.detail;});
  window.addEventListener('chan-view',e=>{if(e.detail.view==='paper')load();});
  window.addEventListener('chan-market',e=>{if(e.detail.market!=='us'){++version;intent=null;}});
  if(document.body.dataset.view==='paper')load();
})();
