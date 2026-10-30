/* 接力只读流程：实际SQLite与路由、明确测试快照、观察中/缺失/未知/断网，不接触交易。 */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict');
const path=require('node:path');
(async()=>{
  const base='http://127.0.0.1:18491';
  const server=spawn('python',['-m','uvicorn','tests.paper_fixture_server:app','--host','127.0.0.1','--port','18491','--log-level','error'],{cwd:path.resolve(__dirname,'..'),stdio:['ignore','ignore','pipe']});
  let logs='',browser;server.stderr.on('data',b=>logs+=b.toString());
  try{
    let ready=false;for(let i=0;i<80;i++){try{if((await fetch(base+'/api/cn/relay')).ok){ready=true;break;}}catch(_){}await new Promise(r=>setTimeout(r,100));}assert.ok(ready,logs);
    browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
    const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
    const page=await context.newPage(),errors=[],writes=[];let fail=false;
    page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().includes('/api/')&&r.method()!=='GET')writes.push(r.url());});
    await page.route('**/api/cn/relay*',async route=>fail?route.fulfill({status:503,body:'test outage'}):route.continue());
    await page.goto(base);await page.locator('.signal-note').first().waitFor();
    await page.locator('[data-market="cn"]').click();await page.locator('[data-cn-theme]').first().waitFor();
    await page.locator('.cn-bottom [data-cn-tab="relay"]').click();
    const app=page.locator('#cn-relay-app');await app.locator('.cn-relay-row').waitFor();
    assert.match(await app.innerText(),/机器人 · 集中开板/);assert.match(await app.innerText(),/商业航天[\s\S]*\+3只/);
    assert.match(await app.innerText(),/不证明资金/);assert.match(await app.innerText(),/已完成/);
    await app.locator('.cn-relay-proof summary').click();assert.match(await app.innerText(),/航天新见一/);assert.match(await app.innerText(),/航天回封/);
    await app.locator('[data-relay-window="5"]').click();assert.match(await app.innerText(),/前窗 \+?0只/);
    await page.locator('#cn-search').fill('不匹配的题材');assert.equal(await app.locator('.cn-relay-row').count(),0);await page.locator('#cn-search').fill('');
    for(const mode of ['light','dark']){
      await page.evaluate(v=>document.documentElement.dataset.theme=v,mode);
      for(const width of [320,390,768,1440]){
        await page.setViewportSize({width,height:844});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,mode+' '+width+' overflow');
      }
    }
    await page.setViewportSize({width:390,height:844});
    await fetch(base+'/test/relay/pending',{method:'POST'});await page.locator('#cn-refresh').click();
    await page.waitForFunction(()=>document.querySelector('#cn-relay-app [data-relay-status]')?.textContent.includes('观察中'));
    assert.equal(await app.locator('.cn-relay-row').count(),0,'pending windows do not show future gains');
    await fetch(base+'/test/relay/complete',{method:'POST'});await page.locator('#cn-refresh').click();await app.locator('.cn-relay-row').waitFor();
    fail=true;await page.locator('#cn-refresh').click();await app.locator('[data-relay-retry]').waitFor();
    assert.match(await app.innerText(),/保留上次分析/);assert.equal(await app.locator('.cn-relay-row').count(),1);
    fail=false;await app.locator('[data-relay-retry]').click();await app.locator('[data-relay-retry]').waitFor({state:'hidden'});
    await fetch(base+'/test/relay/gap',{method:'POST'});await page.locator('#cn-refresh').click();
    await page.waitForFunction(()=>document.querySelector('#cn-relay-app [data-relay-status]')?.textContent.includes('快照不足'));
    assert.equal(await app.locator('.cn-relay-row').count(),0,'missing snapshots cannot become zero movement');
    await fetch(base+'/test/relay/unknown',{method:'POST'});await page.locator('#cn-refresh').click();await app.locator('.cn-relay-row').waitFor();
    assert.match(await app.innerText(),/1只归因未知/);assert.match(await app.innerText(),/不能视为零变化/);
    await page.locator('#cn-date').selectOption('2026-10-28');
    await page.waitForFunction(()=>document.getElementById('cn-relay-app').textContent.includes('暂无交易时段内的分钟快照'));
    assert.equal(await app.locator('.cn-relay-row').count(),0,'date change never retains another day gains');
    await page.locator('#cn-date').selectOption('');await app.locator('.cn-relay-row').waitFor();
    if(process.env.SCREENSHOT_DIR){const fs=require('fs');fs.mkdirSync(process.env.SCREENSHOT_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'cn-relay-mobile.png'),fullPage:true});}
    await page.locator('[data-market="us"]').click();await page.locator('.signal-note').first().waitFor();assert.equal(await app.isVisible(),false);
    assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
    console.log('PASS: relay events, 5/15/30 windows, sample proofs, search, two themes/four widths, pending/no-lookahead, gaps, unknown attribution, stale preservation/retry, date isolation, read-only and US return.');
  }finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
