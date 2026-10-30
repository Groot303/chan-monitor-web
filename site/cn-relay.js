/* 题材接力：只读实际分钟证据，未完成窗口不预填结果，缺失不当作零。 */
(function(){
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const clock=v=>v?new Date(v).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'—';
  const signed=v=>v==null?'—':(v>0?'+':'')+v;
  let host=null,day='',snapshotKey='',query='',payload=null,selection='',minutes=15,error='',busy=false,serial=0,lastRead=0;
  const alive=()=>host?.isConnected && document.body.dataset.market==='cn';
  const names={pending:'观察中',complete:'已完成',incomplete:'快照不足',session_break:'跨休市不可比'};
  function proofs(group){
    const labels={gained:'净增封板名单',lost:'净减封板名单',new_seen:'窗口新见封板',resealed:'观察到回封',opened:'观察到开板',pool_exits:'观察到离池'};
    return '<details class="cn-relay-proof"><summary>查看涉及标的与采样时间</summary>'+Object.entries(labels).map(([key,label])=>'<p><b>'+label+'</b><br>'+((group[key]||[]).map(s=>esc(s.name)+' '+esc(s.code)+(s.observed_at?' · '+esc(clock(s.observed_at)):'')).join('<br>')||'本窗口未记录')+'</p>').join('')+'<p><b>固定归因样本</b><br>'+(group.members||[]).map(s=>esc(s.name)+' '+esc(s.code)).join('、')+'</p></details>';
  }
  function render(){
    if(!alive())return;
    let html='<section class="cn-panel"><h2>题材接力观察</h2><p class="cn-subtitle">某题材集中开板后，哪些其他题材的封板样本增加？这里只观察先后变化，不证明资金从一个题材流向另一个。</p>';
    if(error)html+='<div class="cn-status" data-state="stale" role="status">'+esc(error)+(payload?' 下方保留上次分析，尚未核对最新快照。':' 未用示例或零值补充结果。')+' <button class="btn" type="button" data-relay-retry>重新读取</button></div>';
    if(!payload){host.innerHTML=html+'<div class="cn-empty">'+(error?'接力数据暂不可用。':'正在读取实际分钟快照…')+'</div></section>';return;}
    html+='<p class="cn-subtitle">交易日 '+esc(payload.trade_date)+' · 最近交易时段采样 '+esc(clock(payload.latest_observed_at))+'（北京时间）</p>';
    const events=payload.events||[];
    if(!events.length){
      host.innerHTML=html+'<div class="cn-empty">'+esc(payload.message||'暂无可核验观察事件。')+'</div><p class="cn-subtitle">触发规则：3分钟内，同一主要题材至少2只不同股票由封板变为开板；同一题材30分钟内不重复触发。单次历史计算、首次抓取的炸板股不算触发。</p></section>';return;
    }
    if(!events.some(e=>e.id===selection))selection=events[0].id;
    const e=events.find(e=>e.id===selection),w=e.windows.find(w=>w.minutes===minutes);
    html+='<label class="cn-ladder-select">观察起点<select id="cn-relay-event" aria-label="选择接力观察事件">'+events.map(item=>'<option value="'+esc(item.id)+'"'+(item.id===selection?' selected':'')+'>'+esc(clock(item.observed_at))+' · '+esc(item.theme.name)+' · '+item.opened.length+'只开板</option>').join('')+'</select></label>';
    html+='<div class="cn-height" role="group" aria-label="接力观察窗口">'+[5,15,30].map(n=>'<button type="button" data-relay-window="'+n+'" aria-pressed="'+(n===minutes)+'">'+n+'分钟</button>').join('')+'</div>';
    html+='<div class="cn-relay-anchor"><span class="cn-eyebrow">实际快照中观察到</span><h3>'+esc(e.theme.name)+' · 集中开板</h3><p>'+esc(clock(e.observed_at))+' · '+e.opened.map(s=>esc(s.name)+' '+esc(s.code)).join('、')+'</p><small>实际发生在两次采样之间，不以来源首封时间倒填。</small></div>';
    html+='<div class="cn-relay-timeline"><span>此前'+minutes+'分钟</span><b>起点 '+esc(clock(e.observed_at))+'</b><span>后续'+minutes+'分钟</span></div>';
    html+='<p class="cn-subtitle" data-relay-status>'+esc(names[w.status]||w.status)+' · 目标 '+esc(clock(w.target_at))+(w.end_at?' · 结束采样 '+esc(clock(w.end_at)):'')+'</p>';
    if(w.status!=='complete'){
      host.innerHTML=html+'<div class="cn-empty">'+esc(w.reason)+'</div></section>';return;
    }
    html+='<div class="cn-relay-coverage"><b>观察池整体封板净变化 '+esc(signed(w.pool_net_delta))+'只</b><p>以下仅比较已核验、固定题材归属的样本。'+(w.partial?'有'+w.unknown_stocks+'只归因未知或名称异常，未参与题材比较，不能视为零变化。':'本对比区间内的样本归因均可核验。')+(w.fixed_theme_changes?' '+w.fixed_theme_changes+'只归因曾变化，保持本区间首次归属，不将改题材计为新增封板。':'')+'</p><p>'+ (w.before_status==='complete'?'前窗采样 '+esc(clock(w.baseline_at))+' → 起点；后窗至 '+esc(clock(w.end_at))+'。':'此前同长窗口快照不足，只展示后续变化，不计算加速值。')+'</p></div>';
    const filtered=w.rows.filter(g=>!g.trigger && (!query || [g.name,...(g.members||[]).flatMap(s=>[s.name,s.code])].join(' ').toLowerCase().includes(query.toLowerCase())));
    const maximum=Math.max(1,...filtered.map(g=>Math.abs(g.net_delta)));
    html+='<h3 class="cn-relay-results-title">其他题材 · 已匹配净封板变化</h3>';
    html+=filtered.length?filtered.map(g=>'<article class="cn-relay-row"><div class="cn-relay-row-head"><h4>'+esc(g.name)+'</h4><strong class="'+(g.net_delta>=0?'cn-up':'cn-down')+'">'+esc(signed(g.net_delta))+'只</strong></div><div class="cn-relay-bar" aria-hidden="true"><i class="'+(g.net_delta>=0?'cn-up':'cn-down')+'" style="width:'+Math.round(Math.abs(g.net_delta)/maximum*100)+'%"></i></div><p>样本封板 '+g.start_count+' → '+g.end_count+'只 · 前窗 '+esc(signed(g.before_delta))+'只 · 前后差 '+esc(signed(g.acceleration))+'只</p><p>新见封板 '+g.new_seen.length+'只 · 回封 '+g.resealed.length+'只 · 开板 '+g.opened.length+'只</p>'+proofs(g)+'</article>').join(''):'<div class="cn-empty">当前条件下暂无其他题材的已核验样本。</div>';
    html+='<p class="cn-subtitle">净变化＝结束采样封板数－起点封板数；前后差＝后窗净变化－前窗净变化。新见不等于首次涨停；开板、回封按不同股票分别去重，不能简单相加替代净变化。分钟采样会遗漏期间开合，未接入成交额增速、全板块上涨占比或实际资金转移。</p></section>';
    host.innerHTML=html;
  }
  async function load(force=false){
    if(!alive()||busy||(!force&&payload&&Date.now()-lastRead<25000))return;
    busy=true;lastRead=Date.now();const token=++serial,requestedDay=day;
    try{
      const response=await fetch('/api/cn/relay?date='+encodeURIComponent(requestedDay),{cache:'no-store'});
      if(!response.ok)throw new Error('接力快照读取失败。');
      const result=await response.json();if(result.schema!=='cn-theme-relay-v1'||result.trade_date!==requestedDay)throw new Error('接力数据格式或交易日不匹配。');
      if(token===serial&&alive()){payload=result;error='';render();}
    }catch(ex){if(token===serial&&alive()){error=ex.message;render();}}
    finally{if(token===serial)busy=false;}
  }
  window.CNRelay={
    mount(element,options){
      const changed=day!==options.date,updated=snapshotKey!==options.key;
      host=element;query=options.query||'';snapshotKey=options.key;
      if(changed){serial++;busy=false;payload=null;selection='';error='';lastRead=0;day=options.date;}
      render();load(changed||updated);
    },
    deactivate(){serial++;busy=false;host=null;}
  };
  document.addEventListener('click',e=>{
    if(!alive())return;
    const option=e.target.closest('[data-relay-window]');if(option){minutes=Number(option.dataset.relayWindow);render();return;}
    if(e.target.closest('[data-relay-retry]')||e.target.closest('#cn-refresh'))load(true);
  });
  document.addEventListener('change',e=>{if(alive()&&e.target.id==='cn-relay-event'){selection=e.target.value;render();document.getElementById('cn-relay-event')?.focus();}});
  window.addEventListener('chan-market',e=>{if(e.detail?.market!=='cn')window.CNRelay.deactivate();});
})();
