/* Apple Design真实浏览器回归：跟手、速度、取消、中断、返回与无障碍偏好。 */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const site=path.resolve(__dirname,'../site');
(async()=>{
  const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
  try{
    const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'no-preference'});
    await context.route('http://apple.test/**',async route=>{
      let name=decodeURIComponent(new URL(route.request().url()).pathname);
      if(name==='/api/positions')return route.fulfill({json:{generated:'2026-10-22T03:00:00Z',positions:[{symbol:'NVDA',currency:'USD',qty:10,cost:200,mark:225.92,value:2259.2,unrealized:259.2,asset:'STK'}]}});
      if(name==='/api/macro')return route.fulfill({json:{generated:'2026-10-22T03:00:00Z',indicators:{vix:{name:'VIX',value:19.99,kind:'index',status:'ok',asof:'2026-10-21',change:1,change_pct:1,change_label:'+1%',read:'测试指标',range:[18,22],series:[['2026-10-20',19],['2026-10-21',19.99]]}},regime:{},failures:{}}});
      if(name==='/api/signals')name='/data/signals.json';
      if(name==='/api/signals_cn')name='/data/signals_cn.json';
      if(name.startsWith('/api/charts'))name='/data/'+name.slice(5);
      const file=path.resolve(site,name==='/'?'index.html':name.slice(1));
      if(!file.startsWith(site+path.sep)||!fs.existsSync(file))return route.fulfill({status:404,body:'not found'});
      return route.fulfill({path:file});
    });
    const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://apple.test/');await page.locator('.signal-note').first().waitFor();
    // 搜索和两个筛选入口共享同一状态，不会互相覆盖。
    await page.locator('#quick-search').fill('NVDA');
    assert.ok(await page.locator('.signal-note').count()>0);
    assert.equal(await page.locator('.note-symbol').evaluateAll(es=>es.every(e=>e.textContent==='NVDA')),true);
    await page.locator('#btn-filters').click();
    assert.equal(await page.locator('#f-q').inputValue(),'NVDA');
    const offset=async sel=>page.locator(sel).evaluate(el=>{const m=new DOMMatrix(getComputedStyle(el).transform);return {x:m.m41,y:m.m42};});
    const rest=async(sel,axis='y')=>page.waitForFunction(({sel,axis})=>{const m=new DOMMatrix(getComputedStyle(document.querySelector(sel)).transform);return Math.abs(axis==='x'?m.m41:m.m42)<.25;},{sel,axis});
    await rest('#filters');
    let box=await page.locator('.filter-grabber').boundingBox(),x=box.x+box.width/2,y=box.y+box.height/2;
    await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x,y+55,{steps:5});
    const dragged=(await offset('#filters')).y; assert.ok(Math.abs(dragged-55)<2,'panel must track finger 1:1, actual '+dragged);
    await page.mouse.move(x,y+6,{steps:6});await page.mouse.up();await rest('#filters');
    assert.equal(await page.locator('#filter-backdrop').isVisible(),true,'reverse gesture cancels dismissal');
    // 关闭动画中途重开，必须从当前画面位置延续，而不是跳回初始值。
    await page.evaluate(()=>closeSignalFilters(false));
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    // 在同一帧比较，避免自动化的两次往返之间动画已自然前进。
    const interruption=await page.evaluate(()=>{
      const panel=document.getElementById('filters');
      const before=new DOMMatrix(getComputedStyle(panel).transform).m42;
      openSignalFilters(false);
      return {before,after:new DOMMatrix(getComputedStyle(panel).transform).m42};
    });
    assert.ok(interruption.before>0);
    assert.ok(Math.abs(interruption.after-interruption.before)<.1,'reopen jumped away from current position');
    await rest('#filters');
    box=await page.locator('.filter-grabber').boundingBox();x=box.x+box.width/2;y=box.y+box.height/2;
    await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x,y+185,{steps:5});await page.mouse.up();
    await page.locator('#filter-backdrop').waitFor({state:'hidden'});
    assert.equal(await page.evaluate(()=>document.body.style.overflow),'');
    assert.equal(await page.evaluate(()=>document.activeElement.id),'btn-filters');
    await page.locator('#quick-search').fill('');
    await page.locator('#scope-confirmed').click();
    assert.equal(await page.locator('#scope-confirmed').getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator('.note-unconfirmed').count(),0);
    await page.locator('#scope-all').click();
    await page.locator('.signal-note').first().click();await rest('#drawer','x');
    if(process.env.SCREENSHOT_DIR){fs.mkdirSync(process.env.SCREENSHOT_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'detail-light.png')});}
    await page.locator('#dr-back').click();await page.locator('#drawer').waitFor({state:'hidden'});
    assert.equal(await page.evaluate(()=>document.activeElement.classList.contains('signal-note')),true);
    await page.locator('.signal-note').first().click();await rest('#drawer','x');
    box=await page.locator('#dr-title').boundingBox();x=box.x+12;y=box.y+12;
    await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+165,y,{steps:6});
    assert.ok((await offset('#drawer')).x>150,'detail must follow the horizontal back gesture');
    await page.mouse.up();await page.locator('#drawer').waitFor({state:'hidden'});
    await page.locator('#btn-settings').click();await rest('#settings-sheet');
    assert.equal(await page.evaluate(()=>document.body.style.overflow),'hidden');
    box=await page.locator('.sheet-handle').boundingBox();x=box.x+box.width/2;y=box.y+box.height/2;
    await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x,y+160,{steps:5});await page.mouse.up();
    await page.locator('#settings-sheet').waitFor({state:'hidden'});
    assert.equal(await page.evaluate(()=>document.body.style.overflow),'');
    await page.locator('.tabs-bottom [data-view="holdings"]').click();
    assert.equal(await page.locator('.portfolio-value').innerText(),'$2,259.20');
    assert.match(await page.locator('.portfolio-pnl').innerText(),/\+\$259\.20/);
    // 不同业务内容、两种主题及窄桌面都不能挤出页面宽度。
    for(const theme of ['light','dark']){
      await page.evaluate(t=>{document.documentElement.dataset.theme=t;},theme);
      for(const width of [320,390,768,1000,1024,1440]){
        await page.setViewportSize({width,height:844});
        for(const view of ['signals','symbols','holdings','macro','about']){
          await page.locator((width>1000?'.tabs-top':'.tabs-bottom')+' [data-view="'+view+'"]').click();
          assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${theme} ${view} overflow at ${width}`);
        }
      }
    }
    await page.setViewportSize({width:390,height:844});
    await page.locator('.tabs-bottom [data-view="signals"]').click();
    await page.emulateMedia({reducedMotion:'reduce'});await page.locator('#btn-filters').click();
    assert.equal((await offset('#filters')).y,0);
    await page.keyboard.press('Escape');assert.equal(await page.locator('#filter-backdrop').isVisible(),false);
    assert.deepEqual(errors,[]);
    console.log('PASS: Apple spring tracking/reversal/reopen/flick, shared search, detail back, settings scroll lock, all five views in both themes at six widths, reduced motion.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
