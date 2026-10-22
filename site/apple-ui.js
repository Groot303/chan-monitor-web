/* Apple Design §1–11：即时响应、可中断弹簧、速度投射、1:1跟手与边界阻尼。
 * 不引入动画依赖；每个面板只更新自身transform，不给整棵DOM更新CSS变量。
 */
(function () {
  'use strict';
  var states = new WeakMap(), reduced = matchMedia('(prefers-reduced-motion:reduce)');
  function instant() { return reduced.matches || document.documentElement.dataset.input === 'keyboard'; }
  function get(el) {
    var state = states.get(el);
    if (!state) { state = {el:el,axis:'y',value:0,velocity:0,target:0,frame:0,opened:false,done:null,kind:'sheet',drag:null}; states.set(el,state); }
    return state;
  }
  function paint(s) {
    var center = s.kind === 'filter' && !matchMedia('(max-width:760px)').matches ? 'translateX(-50%) ' : '';
    s.el.style.transform = center + (s.axis === 'x' ? 'translateX(' : 'translateY(') + s.value.toFixed(3) + 'px)';
  }
  function stop(s) { if (s.frame) cancelAnimationFrame(s.frame); s.frame=0; s.done=null; }
  function settle(s,target,done) {
    stop(s); s.target=target; s.done=done || null;
    if (instant()) {
      s.value=target; s.velocity=0; paint(s);
      var finish=s.done; s.done=null; if (finish) finish(); return;
    }
    var previous=performance.now();
    function tick(time) {
      var dt=Math.min(Math.max((time-previous)/1000,0),0.05); previous=time;
      // 临界阻尼解析解：从当前屏幕位置和速度继续，不重启预设关键帧。
      var omega=28, displacement=s.value-s.target, c=s.velocity+omega*displacement, decay=Math.exp(-omega*dt);
      s.value=s.target+(displacement+c*dt)*decay;
      s.velocity=(s.velocity-omega*c*dt)*decay;
      paint(s);
      if (Math.abs(s.value-s.target)<0.2 && Math.abs(s.velocity)<3) {
        s.value=s.target; s.velocity=0; s.frame=0; paint(s);
        var finish=s.done; s.done=null; if (finish) finish();
      } else s.frame=requestAnimationFrame(tick);
    }
    s.frame=requestAnimationFrame(tick);
  }
  function exitDistance(s) {
    return s.axis==='x' ? innerWidth+20 : Math.min(s.el.getBoundingClientRect().height+30,innerHeight+30);
  }
  window.AppleMotion={
    enter:function(el,kind){
      var s=get(el), first=!s.opened; s.kind=kind;
      s.axis=kind==='detail' && matchMedia('(max-width:760px)').matches ? 'x' : 'y';
      if(first){s.value=instant()?0:(s.axis==='x'?innerWidth:36);s.velocity=0;}
      s.opened=true;paint(s);settle(s,0);
    },
    close:function(el,done){
      var s=get(el); if(!s.opened){if(done)done();return;}
      settle(s,exitDistance(s),function(){s.opened=false;s.el.style.transform='';if(done)done();});
    },
    reset:function(el){var s=get(el);stop(s);s.value=0;s.velocity=0;s.opened=false;s.drag=null;el.style.transform='';}
  };
  function emit(name){window.dispatchEvent(new CustomEvent(name));}
  function attach(el,handle,eventName,allowed){
    if(!el||!handle)return;
    handle.addEventListener('pointerdown',function(e){
      if(e.button!==0 || !e.isPrimary || (allowed&&!allowed()) || e.target.closest('button,a,input,select'))return;
      var s=get(el);if(!s.opened || s.drag)return;
      stop(s);
      var point=s.axis==='x'?e.clientX:e.clientY;
      s.drag={id:e.pointerId,start:point,offset:s.value,origin:s.value,samples:[{p:point,t:e.timeStamp}],moved:false};
      handle.setPointerCapture(e.pointerId);
    });
    handle.addEventListener('pointermove',function(e){
      var s=get(el),d=s.drag;if(!d||d.id!==e.pointerId)return;
      var point=s.axis==='x'?e.clientX:e.clientY, delta=point-d.start;
      if(Math.abs(delta)>6)d.moved=true;
      var next=d.offset+delta;
      // 负向越界不断增加阻力，避免突然撞上硬边。
      s.value=next<0 ? (next*200*.55)/(200+.55*Math.abs(next)) : next;
      d.samples.push({p:point,t:e.timeStamp});
      while(d.samples.length>2 && d.samples[0].t<e.timeStamp-90)d.samples.shift();
      paint(s);
    });
    function release(e,cancelled){
      var s=get(el),d=s.drag;if(!d||d.id!==e.pointerId)return;
      s.drag=null;
      if(handle.hasPointerCapture(e.pointerId))handle.releasePointerCapture(e.pointerId);
      if(!d.moved||cancelled){s.velocity=0;settle(s,0);return;}
      var last=d.samples[d.samples.length-1], first=d.samples[0], age=e.timeStamp-last.t;
      s.velocity=age>90?0:(last.p-first.p)/Math.max(last.t-first.t,1)*1000;
      // Apple的指数衰减投射，且快速反向手势能够撤回原来的关闭意图。
      var projection=s.value+(s.velocity/1000)*.998/(1-.998);
      var threshold=Math.min(140,exitDistance(s)*.35);
      if(s.velocity>=-30 && projection>threshold)emit(eventName);else settle(s,0);
    }
    handle.addEventListener('pointerup',function(e){release(e,false);});
    handle.addEventListener('pointercancel',function(e){release(e,true);});
    handle.addEventListener('lostpointercapture',function(e){if(get(el).drag)release(e,true);});
  }
  var filter=document.getElementById('filters'), settings=document.getElementById('settings-sheet'), detail=document.getElementById('drawer');
  attach(filter,filter.querySelector('.filter-grabber'),'apple-dismiss-filter',function(){return matchMedia('(max-width:760px)').matches;});
  attach(settings,settings.querySelector('.sheet-handle'),'apple-dismiss-settings');
  attach(detail,detail.querySelector('.drawer-head'),'apple-dismiss-detail',function(){return matchMedia('(max-width:760px)').matches;});
  // 桌面保留带图标的文字导航，与手机相同的五个目的地。
  document.querySelectorAll('.tabs-top .tab').forEach(function(tab){
    var icon=document.querySelector('.tabs-bottom [data-view="'+tab.dataset.view+'"] svg');
    if(icon)tab.prepend(icon.cloneNode(true));
  });
})();
