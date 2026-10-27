/* 真实自动策略/SQLite端到端：浏览器只读，测试行情推进由独立测试接口完成。 */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict');
const path=require('node:path');
(async()=>{
  const port=18479,base=`http://127.0.0.1:${port}`;
  const server=spawn('python',['-m','uvicorn','tests.paper_fixture_server:app','--host','127.0.0.1','--port',String(port),'--log-level','error'],{cwd:path.resolve(__dirname,'..'),stdio:['ignore','ignore','pipe']});
  let logs='';server.stderr.on('data',x=>{logs+=x.toString()});
  let browser;
  try{
    let ready=false;
    for(let i=0;i<60;i++){try{if((await fetch(base+'/api/signals')).ok){ready=true;break}}catch{}await new Promise(r=>setTimeout(r,100));}
    assert.ok(ready,'fixture server failed: '+logs);
    browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
    const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
    const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base);await page.locator('.signal-note').first().waitFor();
    await page.locator('#quick-search').fill('NVDA');await page.locator('.signal-note').first().click();
    const writes=[],manual=[];
    page.on('request',r=>{if(r.url().includes('/api/') && r.method()!=='GET')writes.push(r.url());if(r.url().includes('/api/paper/'))manual.push(r.url());});
    await page.locator('#dr-paper').click();await page.locator('#strategy-refresh').waitFor();
    assert.match(await page.locator('#paper-app').innerText(),/这里只查看，不需要手动买卖/);
    assert.equal(await page.locator('[data-strategy-version="v2"]').getAttribute('aria-pressed'),'true');
    assert.match(await page.locator('#paper-app').innerText(),/单笔0.5%、组合2%/);
    assert.equal(await page.locator('#paper-app form,#paper-app input').count(),0,'observer has no trading controls');
    const initial=await (await fetch(base+'/api/strategy/us')).json();assert.equal(initial.account.orders.length,0);
    assert.equal((await (await fetch(base+'/test/signal',{method:'POST'})).json()).orders,1,'server submitted automatically');
    await page.locator('#strategy-refresh').click();
    await page.waitForFunction(()=>document.querySelector('#paper-app').textContent.includes('自动买入'));
    await fetch(base+'/test/advance',{method:'POST'});
    await page.locator('#strategy-refresh').click();
    await page.waitForFunction(()=>document.querySelector('#paper-app').textContent.includes('100.05'));
    await page.reload();await page.locator('#strategy-refresh').waitFor();
    assert.match(await page.locator('#paper-app').innerText(),/100\.05/);
    const stopped=await fetch(base+'/test/stop-advance',{method:'POST'});
    assert.equal((await stopped.json()).automatic_stops_filled,1,'server stop exits without browser/account refresh');
    await page.locator('#strategy-refresh').click();
    await page.waitForFunction(()=>document.getElementById('paper-app').textContent.includes('自动止损'));
    const account=(await (await fetch(base+'/api/strategy/us')).json()).account;
    assert.equal(account.positions.length,0);assert.equal(account.fills.length,2);
    await page.locator('[data-strategy-version="v1"]').click();
    await page.waitForFunction(()=>document.querySelector('#paper-app [data-strategy-version="v1"]')?.getAttribute('aria-pressed')==='true');
    assert.match(await page.locator('#paper-app').innerText(),/us-daily-30m-v1/);
    await page.locator('[data-strategy-version="v2"]').click();
    await page.waitForFunction(()=>document.querySelector('#paper-app [data-strategy-version="v2"]')?.getAttribute('aria-pressed')==='true');
    assert.match(await page.locator('#paper-app').innerText(),/按买点复盘/);
    assert.match(await page.locator('#paper-app').innerText(),/完整交易胜率/);
    // 两个市场分别建设：A股保留原页面，不展示/创建美股练习入口。
    await page.locator('[data-market="cn"]').click();
    await page.waitForFunction(()=>document.getElementById('data-status').textContent.includes('东方财富'));
    assert.equal(await page.locator('.tab[data-view="paper"]:visible').count(),0);
    await page.evaluate(()=>{location.hash='paper';});
    await page.waitForFunction(()=>location.hash==='#signals');
    await page.locator('.signal-note').first().click();
    assert.equal(await page.locator('#dr-paper').count(),0);
    await page.keyboard.press('Escape');
    await page.locator('#drawer').waitFor({state:'hidden'});
    await page.locator('[data-market="us"]').click();
    await page.waitForFunction(()=>document.body.dataset.market==='us');
    await page.locator('.tabs-bottom [data-view="paper"]').click();
    await page.locator('#strategy-refresh').waitFor();
    assert.match(await page.locator('#paper-app').innerText(),/自动止损/);
    assert.equal(await page.locator('#paper-app form,#paper-app input').count(),0);
    assert.deepEqual(writes,[],'observer must never submit mutation requests');
    assert.deepEqual(manual,[],'observer must never access legacy manual accounts');
    for(const theme of ['light','dark']){
      await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
      for(const width of [320,390,768,1440]){
        await page.setViewportSize({width,height:844});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${theme} ${width} overflow`);
        assert.equal(await page.locator('#paper-app .paper-right').evaluateAll(nodes=>nodes.some(n=>n.scrollWidth>n.clientWidth+1)),false,`${theme} ${width} clipped record text`);
      }
    }
    await page.setViewportSize({width:390,height:844});
    if(process.env.SCREENSHOT_DIR){const fs=require('fs');fs.mkdirSync(process.env.SCREENSHOT_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'paper-mobile.png'),fullPage:true});}
    assert.deepEqual(errors,[]);
    console.log('PASS: read-only strategy observer, server signal entry, fill, background stop, reload, CN isolation, no writes or manual credentials, both themes and mobile widths.');
  }finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1});
