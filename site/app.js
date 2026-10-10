(function(){
const LV={weekly:"周线",daily:"日线","30m":"30分钟"};
const TY={"1B":"一买","2B":"二买","3B":"三买","1S":"一卖","2S":"二卖","3S":"三卖"};
const BK={base:"基础分",divergence:"背驰",resonance:"共振",confirmed:"确认",freshness:"新鲜度",quality:"中枢质量"};
const $=id=>document.getElementById(id);
let D=null;
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
fetch("data/signals.json?"+Date.now()).then(r=>r.json()).then(d=>{
  D=d;
  const t=new Date(d.generated);
  $("meta").textContent="数据更新时间: "+t.toLocaleString("zh-CN",{hour12:false})+" (本地时间) | UTC "+d.generated.slice(0,16).replace("T"," ");
  Object.keys(d.symbols).sort().forEach(s=>{const o=document.createElement("option");o.value=o.textContent=s;$("f-sym").appendChild(o)});
  ["f-sym","f-lv","f-type","f-conf","f-recent","f-sort"].forEach(i=>$(i).addEventListener("change",render));
  render();
}).catch(e=>{$("meta").textContent="数据加载失败: "+e});
function render(){
  const f={s:$("f-sym").value,l:$("f-lv").value,t:$("f-type").value,c:$("f-conf").value,r:$("f-recent").value,o:$("f-sort").value};
  let a=D.signals.filter(g=>(!f.s||g.symbol===f.s)&&(!f.l||g.level===f.l)&&(!f.t||g.type===f.t)&&(f.c===""||String(+g.confirmed)===f.c)&&(!f.r||g.recent));
  a.sort((x,y)=>f.o==="asc"?x.score-y.score:y.score-x.score);
  const tb=document.querySelector("#tbl tbody");tb.innerHTML="";
  $("empty").hidden=a.length>0;
  a.forEach(g=>{
    const tr=document.createElement("tr");tr.className="sig";
    const buy=g.type.endsWith("B");
    tr.innerHTML=`<td class="score"><span class="bar" style="width:${g.score*6}px"></span>${g.score.toFixed(1)}</td><td>${esc(g.symbol)}</td><td>${LV[g.level]||g.level}</td><td class="${buy?"buy":"sell"}">${TY[g.type]||esc(g.type)}</td><td>${esc(g.time)}</td><td>${g.price.toFixed(2)}</td><td class="${g.confirmed?"":"un"}">${g.confirmed?"已确认":"未确认"}</td>`;
    tr.addEventListener("click",()=>toggle(tr,g));
    tb.appendChild(tr);
  });
}
function toggle(tr,g){
  const nx=tr.nextSibling;
  if(nx&&nx.classList&&nx.classList.contains("bd")){nx.remove();return}
  const b=g.score_breakdown||{};
  const items=Object.keys(BK).map(k=>`<div>${BK[k]}: <b>${b[k]>0?"+":""}${(b[k]||0).toFixed(2)}</b></div>`).join("");
  const extra=[`原始合计 ${(b.raw_total??0).toFixed(2)}${b.capped?"(已封顶10)":""}`,`距今 ${g.bars_ago} 根K线`,g.resonance?`多级别共振: ${esc(g.resonance)}`:"",g.repaint_warning?esc(g.repaint_warning):""].filter(Boolean).join(" | ");
  const d=document.createElement("tr");d.className="bd";
  d.innerHTML=`<td colspan="7"><div class="bk">${items}</div><div>${extra}</div></td>`;
  tr.after(d);
  showDetail(g.symbol);
}
function showDetail(sym){
  const s=D.symbols[sym];$("detail").hidden=false;$("d-title").textContent=sym+" K线图(周/日/30分钟)";
  $("d-info").textContent=Object.entries(s.levels).map(([l,x])=>`${LV[l]||l}: 收盘 ${x.last_close.toFixed(2)} (${x.last}), 方向 ${x.state.direction}`).join(" | ");
  if(s.image){$("d-img").src=s.image;$("d-img").hidden=false}else $("d-img").hidden=true;
}
})();
