/* 独立A股连板研究台：只读快照，关注清单只存本地，不提供交易或买卖点。 */
(function(){
  'use strict';
  const root=document.getElementById('cn-research-app');if(!root)return;
  const dialog=document.getElementById('cn-stock-dialog'),body=document.getElementById('cn-stock-body');
  const tabs={themes:'题材',ladder:'连板梯队',broken:'炸板观察',previous:'昨日表现',watch:'我的关注'};
  const esc=value=>String(value==null?'':value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt=(value,d=0)=>value==null || !Number.isFinite(Number(value))?'—':Number(value).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d});
  const pct=value=>value==null?'—':(value>0?'+':'')+fmt(value,2)+'%';
  const money=value=>value==null?'—':value>=1e8?fmt(value/1e8,2)+'亿':value>=1e4?fmt(value/1e4,0)+'万':fmt(value,0);
  const time=value=>value?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'尚未采集';
  const empty=text=>'<div class="cn-empty">'+esc(text)+'</div>';
  const panel=(title,html)=>'<section class="cn-panel"><h2>'+esc(title)+'</h2>'+html+'</section>';
  let data=null,tab='themes',query='',date='',height=0,theme=null,busy=false,serial=0,focusBefore=null,overflowBefore='';
  let watch=[];try{watch=JSON.parse(localStorage.getItem('cn.research.watch.v1')||'[]').filter(c=>/^\d{6}$/.test(c));}catch(_){}
  const active=()=>document.body.dataset.market==='cn';
  function pool(key){return data?.pools?.[key] || [];}
  function matches(stock){return !query || [stock.code,stock.name,stock.industry,stock.theme?.name,...(stock.concepts || [])].join(' ').toLowerCase().includes(query.toLowerCase());}
  function stock(code){return ['up','broken','previous','down'].flatMap(pool).find(s=>s.code===code) || {code,name:'未在当前观察池',state:'unknown',theme:null};}
  function watchButton(code){return '<button type="button" class="cn-star" data-cn-watch="'+esc(code)+'" aria-label="'+(watch.includes(code)?'取消关注':'关注')+' '+esc(code)+'" aria-pressed="'+watch.includes(code)+'">'+(watch.includes(code)?'★':'☆')+'</button>';}
  function row(s){
    let label=s.boards?s.boards+'板':s.state==='broken'?'已开板':s.state==='previous'?'昨'+fmt(s.yesterday_boards)+'板':s.state==='down'?'跌停':s.state==='ambiguous'?'待核验':'';
    return '<div class="cn-row"><button type="button" class="cn-stock-main" data-cn-stock="'+esc(s.code)+'"><strong>'+esc(s.name)+'<span class="cn-badge">'+esc(label)+'</span></strong><small>'+esc(s.code)+' · '+esc(s.theme?.name || '题材待核验')+'</small><small>'+
      esc(s.state==='previous'?(s.currently_sealed===true?'仍在涨停池 · 当前'+fmt(s.current_boards)+'板':s.currently_sealed===false?'当前未在涨停池':'今日状态待核验'):'首封 '+(s.first_seal || '—')+' · 开板 '+fmt(s.open_count)+'次')+'</small></button><div class="cn-stock-quote '+(s.change_pct>=0?'cn-up':'cn-down')+'">'+esc(pct(s.change_pct))+'<small>¥'+esc(fmt(s.price,2))+'</small><small>'+(s.seal_amount!=null?'封单 '+esc(money(s.seal_amount)):s.state==='broken'?'现价低于封板状态':'')+'</small></div>'+watchButton(s.code)+'</div>';
  }
  function list(rows,message='当前条件下没有已采集的标的。'){const selected=rows.filter(matches);return selected.length?'<div class="cn-list">'+selected.map(row).join('')+'</div>':empty(message);}
  function shell(){
    root.innerHTML='<header class="cn-head"><div><div class="cn-eyebrow">A股 · 专注连板研究</div><h1>连板研究</h1><p class="cn-muted" id="cn-date-note">正在读取交易日…</p></div><button class="btn cn-refresh" type="button" id="cn-refresh">刷新</button></header><div class="cn-status" id="cn-status" role="status">正在读取连板研究快照…</div><div class="cn-metrics" id="cn-metrics"></div>'+
      '<div class="cn-controls"><input id="cn-search" type="search" placeholder="搜索名称、代码或题材" aria-label="搜索连板研究标的"><select id="cn-date" aria-label="选择已采集交易日"><option value="">最近交易日</option></select></div><nav class="cn-tabs" aria-label="连板研究栏目">'+Object.entries(tabs).map(([key,label])=>'<button type="button" data-cn-tab="'+key+'">'+label+'</button>').join('')+'</nav><div id="cn-content"></div><div id="cn-method"></div>';
    document.getElementById('cn-search').value=query;
    document.getElementById('cn-search').addEventListener('input',e=>{query=e.target.value;renderContent();});
    document.getElementById('cn-date').addEventListener('change',e=>{date=e.target.value;theme=null;serial++;load();});
    document.getElementById('cn-refresh').addEventListener('click',load);
  }
  function render(){
    if(!document.getElementById('cn-content'))shell();
    const state=data.status,labels={current:'盘中快照',closed:'休市 · 最近快照',partial:'部分字段待核验',stale:'数据过期 · 保留旧快照',historical:'历史采集快照',unavailable:'等待行情'};
    const status=document.getElementById('cn-status');status.dataset.state=state;
    status.textContent=(labels[state] || state)+' · '+(data.error || data.collection_error || '采集时间 '+time(data.observed_at))+'。来源延迟尚未验证。';
    document.getElementById('cn-date-note').textContent='数据交易日 '+(data.trade_date || '待核验')+' · 北京时间';
    const summary=data.summary || {};
    document.getElementById('cn-metrics').innerHTML=[['已观察高度',summary.observed_height,'板'],['当前涨停',summary.sealed_count,''],['当前炸板',summary.broken_count,''],['当前跌停',summary.down_count,'']].map(([name,value,unit])=>'<div><span>'+name+'</span><strong>'+esc(fmt(value))+esc(value==null?'':unit)+'</strong></div>').join('');
    const selector=document.getElementById('cn-date');selector.innerHTML='<option value="">最近交易日</option>'+(data.available_dates || []).map(d=>'<option value="'+esc(d)+'">'+esc(d)+' 采集记录</option>').join('');
    if(date && !(data.available_dates || []).includes(date))selector.insertAdjacentHTML('beforeend','<option value="'+esc(date)+'">'+esc(date)+'</option>');selector.value=date;
    document.getElementById('data-status').textContent='A股连板研究 · '+(labels[state] || state)+' · '+(data.trade_date || '日期待核验');
    document.getElementById('meta-short').textContent=data.trade_date || '连板研究';
    document.getElementById('foot-meta').textContent='研究快照接收时间：'+time(data.observed_at)+'（北京时间）。行业、概念和当日涨停归因分别记录。';
    renderContent();renderMethod();
  }
  function renderContent(){
    const target=document.getElementById('cn-content');if(!target)return;
    document.querySelectorAll('[data-cn-tab]').forEach(button=>{if(button.dataset.cnTab===tab)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
    if(!data || data.status==='unavailable'){target.innerHTML=empty(data?.error || '等待服务器首次采集，不使用旧策略或示例行情填充。');return;}
    let html='';
    if(tab==='themes' && theme){
      const group=data.themes.find(t=>t.id===theme);
      html='<button class="btn cn-back" type="button" id="cn-theme-back">‹ 全部题材</button>'+panel(group?.name || '题材',
        '<p class="cn-subtitle">当日供应商涨停归因；股票其他概念与行业在详情中分别显示。</p>'+list([...pool('up'),...pool('broken')].filter(s=>(s.theme?.id || 'unclassified')===theme)));
    } else if(tab==='themes'){
      const groups=(data.themes || []).filter(g=>!query || g.name.toLowerCase().includes(query.toLowerCase()) || g.stocks.some(c=>matches(stock(c))));
      html=panel('按题材看涨停表现','<p class="cn-subtitle">今日封板归因覆盖 '+fmt(data.summary?.attributed_sealed)+' / '+fmt(data.summary?.attribution_total)+' 只。未核验题材单列，不用行业代替。</p>'+(groups.length?groups.map(g=>'<button class="cn-theme" type="button" data-cn-theme="'+esc(g.id)+'"><div class="cn-theme-head"><strong>'+esc(g.name)+'</strong><span class="cn-theme-count">'+fmt(g.sealed_count)+' 涨停 · '+fmt(g.broken_count)+' 炸板 ›</span></div><small>板内已观察最高 '+fmt(g.highest_boards)+'板 · '+esc(g.stocks.slice(0,4).map(c=>stock(c).name).join('、'))+'</small></button>').join(''):empty('暂无可核验题材归因。')));
    } else if(tab==='ladder'){
      html=panel('连板梯队','<div class="cn-height" role="group" aria-label="筛选连板高度">'+[[0,'全部'],[1,'首板'],[2,'二板'],[3,'三板'],[4,'四板'],[5,'五板+']].map(([key,name])=>'<button type="button" data-cn-height="'+key+'" aria-pressed="'+(key===height)+'">'+name+'</button>').join('')+'</div>'+list(pool('up').filter(s=>!height || (height===5?s.boards>=5:s.boards===height)).sort((a,b)=>b.boards-a.boards || (a.first_seal || '').localeCompare(b.first_seal || ''))));
    } else if(tab==='broken'){
      html=panel('炸板观察','<p class="cn-subtitle">快照开板占比 '+fmt(data.summary?.snapshot_open_ratio_pct,1)+'%：当前炸板池 ÷ 当前涨停与炸板池。仅在两池完整且采样一致时计算，不等同于全日炸板率。</p>'+list(pool('broken').slice().sort((a,b)=>(b.open_count || 0)-(a.open_count || 0))));
      const events=(data.events || []).filter(e=>e.kind==='observed_open' || e.kind==='observed_reseal').slice(0,15);
      html+=panel('网站观察到的开合',events.length?events.map(e=>'<div class="cn-log">'+esc(e.name)+' · '+(e.kind==='observed_open'?'观察到开板':'观察到回封')+'<br>'+esc(time(e.observed_at))+'<br>两次采样间的状态变化，实际发生时刻未知。</div>').join(''):empty('暂无已记录的开板/回封变化；不会由首封时间补造网站观察记录。'));
    } else if(tab==='previous'){
      html=panel('昨日涨停，今日表现','<p class="cn-subtitle">盘中晋级为观察值。未在当前涨停池不等于已经确认收盘断板。</p>'+(data.progression || []).map(p=>'<div class="cn-progression"><div>昨日 '+p.from_boards+'板 → 今日 '+(p.from_boards+1)+'板<small>'+p.candidates+' 只候选 · 当前仍封板 '+fmt(p.currently_advanced)+' 只</small></div><strong>'+fmt(p.rate_pct,1)+'%</strong></div>').join('')+list(pool('previous').slice().sort((a,b)=>(b.change_pct || 0)-(a.change_pct || 0))));
    } else if(tab==='watch'){
      html=panel('我的关注','<p class="cn-subtitle">关注清单仅保存在这台设备。未出现在来源观察池的股票不补造行情。</p>'+list(watch.map(stock),'点击标的旁的星号，加入你的研究清单。'));
    }
    target.innerHTML=html;
  }
  function renderMethod(){
    const open=document.getElementById('cn-source-details')?.open;
    const names={up:'东财涨停池',broken:'东财炸板池',previous:'东财昨日涨停表现',down:'东财跌停池'};
    document.getElementById('cn-method').innerHTML='<details class="cn-panel cn-method" id="cn-source-details"'+(open?' open':'')+'><summary>数据来源与统计口径</summary><p>数据仅用于连板研究，无自动交易。采样每分钟一次，页面约30秒读取一次；采集时间不是交易所行情时间，无法承诺逐笔完整性。</p><p>'+esc(data.coverage_note || '等待来源统计范围说明。')+'</p>'+
      Object.entries(data.sources || {}).map(([key,s])=>'<div class="cn-source-row">'+esc(names[key] || '开盘啦 '+key.slice(-1)+'板题材归因')+' · '+esc(({ok:'已取得',partial:'列表未完整',empty:'无当日可核验归因',error:'暂不可用'})[s.status] || s.status)+'<br>接收：'+esc(time(s.observed_at))+(s.error?'<br>'+esc(s.error):'')+'</div>').join('')+'<p>来源的首封、末封与炸板次数是供应商字段。网站首次观察与开合事件来自实际采样日志，不能据此证明撤单细节、涨停排队或可成交性。</p><p>分钟采样及原始响应保留7天，每日最后快照保留60天；日期选择只展示实际已采集记录。</p></details>';
  }
  function detail(code,opener){
    const s=stock(code);focusBefore=opener;overflowBefore=document.body.style.overflow;
    body.innerHTML='<div class="cn-eyebrow">'+esc(s.code)+' · '+esc(data.trade_date)+'</div><h2 id="cn-stock-title">'+esc(s.name)+'</h2>'+watchButton(s.code)+'<dl class="cn-facts">'+
      [['最新价','¥'+fmt(s.price,2)],['涨跌幅',pct(s.change_pct)],['连板高度',s.boards?fmt(s.boards)+'板':'—'],['封板资金',money(s.seal_amount)],['来源首封',s.first_seal || '—'],['来源末封',s.last_seal || '—'],['来源炸板次数',fmt(s.open_count)],['成交额',money(s.amount)]].map(([k,v])=>'<div><dt>'+k+'</dt><dd>'+esc(v)+'</dd></div>').join('')+'</dl>'+
      '<section class="cn-detail-section"><h3>当日涨停归因</h3><p>'+esc(s.theme?.name || '暂无本交易日可核验归因')+'<br>来源：'+esc(s.theme?'开盘啦供应商归因，非事实认定':'待核验')+'</p></section><section class="cn-detail-section"><h3>行业 / 其他概念</h3><p>行业：'+esc(s.industry || '—')+'<br>概念：'+esc((s.concepts || []).join('、') || '—')+'</p></section><section class="cn-detail-section"><h3>时间与状态证据</h3><p>网站首次观察：'+esc(time(s.first_observed_at))+'<br>本快照接收：'+esc(time(data.observed_at))+'<br>来源事件：'+esc(time(s.source_event_time))+'<br>来源事件不等于网站首次发现；本页不判定可成交性。'+(s.state==='unknown'?'<br>此标的未在当前观察池，暂无可核验行情。':'')+'</p></section>';
    document.body.style.overflow='hidden';dialog.showModal();document.getElementById('cn-stock-close').focus();
  }
  document.getElementById('cn-stock-close').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{document.body.style.overflow=overflowBefore;const target=focusBefore?.isConnected?focusBefore:root.querySelector('[data-cn-stock="'+focusBefore?.dataset.cnStock+'"]');target?.focus();});
  document.addEventListener('click',event=>{
    if(!active())return;
    const nav=event.target.closest('[data-cn-tab]');if(nav){tab=nav.dataset.cnTab;theme=null;renderContent();window.scrollTo({top:0,behavior:'instant'});return;}
    const star=event.target.closest('[data-cn-watch]');if(star){const code=star.dataset.cnWatch;watch=watch.includes(code)?watch.filter(c=>c!==code):watch.concat(code);try{localStorage.setItem('cn.research.watch.v1',JSON.stringify(watch));}catch(_){}renderContent();if(dialog.open){const button=body.querySelector('[data-cn-watch]');button.setAttribute('aria-pressed',watch.includes(code));button.setAttribute('aria-label',(watch.includes(code)?'取消关注':'关注')+' '+code);button.textContent=watch.includes(code)?'★':'☆';}return;}
    const stockButton=event.target.closest('[data-cn-stock]');if(stockButton){detail(stockButton.dataset.cnStock,stockButton);return;}
    const group=event.target.closest('[data-cn-theme]');if(group){theme=group.dataset.cnTheme;renderContent();return;}
    const filter=event.target.closest('[data-cn-height]');if(filter){height=Number(filter.dataset.cnHeight);renderContent();return;}
    if(event.target.closest('#cn-theme-back')){theme=null;renderContent();}
  });
  async function load(){
    if(!active() || document.hidden || busy)return;
    busy=true;const version=++serial,requestedDate=date;
    if(!document.getElementById('cn-content'))shell();
    try{
      const response=await fetch('/api/cn/research'+(requestedDate?'?date='+encodeURIComponent(requestedDate):''),{cache:'no-store'});
      if(!response.ok)throw new Error('研究数据暂时无法读取，请刷新重试。');
      const snapshot=await response.json();if(snapshot.schema!=='cn-limitup-research-v1')throw new Error('研究数据格式暂不可用。');
      if(version===serial && requestedDate===date && active()){data=snapshot;render();}
    }catch(error){if(version===serial && active()){const status=document.getElementById('cn-status');status.dataset.state='stale';status.textContent=error.message+(data?' 下方保留上次快照：'+time(data.observed_at):' 暂无行情，不使用示例填充。');}}
    finally{busy=false;if((version!==serial || requestedDate!==date) && active())queueMicrotask(load);}
  }
  window.addEventListener('chan-market',()=>{serial++;document.querySelector('.cn-bottom').hidden=!active();if(!active()){if(dialog.open)dialog.close();}else queueMicrotask(load);});
  window.addEventListener('chan-view',e=>{if(e.detail?.view==='research')queueMicrotask(load);});
  document.addEventListener('visibilitychange',load);setInterval(load,30000);
  document.querySelector('.cn-bottom').hidden=!active();if(active())load();
}());
