/* 实际SQLite/只读API的连板研究流程。行情为明确测试夹具，不接入实盘。 */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict');
const path=require('node:path');
(async()=>{
  const base='http://127.0.0.1:18489';
  const server=spawn('python',['-m','uvicorn','tests.paper_fixture_server:app','--host','127.0.0.1','--port','18489','--log-level','error'],{cwd:path.resolve(__dirname,'..'),stdio:['ignore','ignore','pipe']});
  let logs='',browser;server.stderr.on('data',b=>logs+=b.toString());
  try{
    let ready=false;for(let i=0;i<80;i++){try{if((await fetch(base+'/api/cn/research')).ok){ready=true;break;}}catch(_){}await new Promise(r=>setTimeout(r,100));}
    assert.ok(ready,logs);
    browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
    const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
    const page=await context.newPage(),errors=[],legacy=[],writes=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(/signals_cn|charts_cn|img_cn/.test(r.url()))legacy.push(r.url());if(r.url().includes('/api/')&&r.method()!=='GET')writes.push(r.url());});
    await page.goto(base);await page.locator('.signal-note').first().waitFor();
    await page.locator('[data-market="cn"]').click();await page.locator('[data-cn-theme]').first().waitFor();
    assert.match(await page.locator('#cn-date-note').innerText(),/2026-10-29/);
    assert.equal(await page.locator('#view-signals').isVisible(),false);
    assert.equal(await page.locator('.tabs-bottom').isVisible(),false);
    assert.equal(await page.locator('.cn-bottom').isVisible(),true);
    await page.locator('[data-cn-theme]').first().click();
    await page.locator('[data-cn-stock="000559"]').click();
    await page.locator('#cn-stock-dialog').waitFor({state:'visible'});
    assert.match(await page.locator('#cn-stock-body').innerText(),/机器人/);
    assert.match(await page.locator('#cn-stock-body').innerText(),/汽车零部件/);
    assert.match(await page.locator('#cn-stock-body').innerText(),/网站首次观察/);
    assert.match(await page.locator('#cn-stock-body').innerText(),/09:30:01/);
    await page.locator('#cn-stock-body [data-cn-watch]').click();
    await page.keyboard.press('Escape');await page.locator('#cn-stock-dialog').waitFor({state:'hidden'});
    await page.waitForFunction(()=>document.body.style.overflow==='');
    assert.equal(await page.evaluate(()=>document.activeElement.dataset.cnStock),'000559','focus returns after underlying watch rows rerender');
    await page.locator('.cn-bottom [data-cn-tab="watch"]').click();
    assert.match(await page.locator('#cn-content').innerText(),/000559/);
    await page.reload();await page.locator('[data-cn-theme]').first().waitFor();
    await page.locator('.cn-bottom [data-cn-tab="watch"]').click();
    assert.equal(await page.locator('#cn-content [data-cn-stock]').count(),1,'watchlist survives reload');
    await page.locator('.cn-bottom [data-cn-tab="ladder"]').click();
    await page.locator('[data-cn-height="3"]').click();
    assert.equal(await page.locator('#cn-content [data-cn-stock]').count(),1);
    assert.match(await page.locator('#cn-content').innerText(),/002050/);
    await page.locator('#cn-search').fill('000559');
    assert.equal(await page.locator('#cn-content [data-cn-stock]').count(),0);
    await page.locator('[data-cn-height="0"]').click();assert.equal(await page.locator('#cn-content [data-cn-stock]').count(),1);
    await page.locator('#cn-search').fill('');
    await page.locator('.cn-bottom [data-cn-tab="previous"]').click();
    assert.match(await page.locator('#cn-content').innerText(),/昨日 1板/);
    assert.match(await page.locator('#cn-content').innerText(),/50.0%/);
    await page.locator('#cn-date').selectOption('2026-10-28');
    await page.waitForFunction(()=>document.getElementById('cn-status').textContent.includes('历史采集快照'));
    assert.match(await page.locator('#cn-date-note').innerText(),/2026-10-28/);
    await page.locator('#cn-date').selectOption('');
    await page.waitForFunction(()=>document.getElementById('cn-date-note').textContent.includes('2026-10-29'));
    await fetch(base+'/test/cn-open',{method:'POST'});await page.locator('#cn-refresh').click();
    await page.locator('.cn-bottom [data-cn-tab="broken"]').click();
    await page.waitForFunction(()=>document.getElementById('cn-content').textContent.includes('观察到开板'));
    await fetch(base+'/test/cn-reseal',{method:'POST'});await page.locator('#cn-refresh').click();
    await page.waitForFunction(()=>document.getElementById('cn-content').textContent.includes('观察到回封'));
    for(const theme of ['light','dark']){
      await page.evaluate(value=>document.documentElement.dataset.theme=value,theme);
      for(const width of [320,390,768,1440]){
        await page.setViewportSize({width,height:844});
        for(const tab of ['themes','ladder','broken','previous','watch']){
          await page.locator((width>760?'.cn-tabs':'.cn-bottom')+' [data-cn-tab="'+tab+'"]').click();
          assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${theme} ${width} ${tab} overflow`);
          assert.equal(await page.locator('h1:visible').count(),1);
        }
      }
    }
    await page.setViewportSize({width:390,height:844});
    await fetch(base+'/test/cn-offline',{method:'POST'});await page.locator('#cn-refresh').click();
    await page.waitForFunction(()=>document.getElementById('cn-status').textContent.includes('数据过期'));
    await page.locator('.cn-bottom [data-cn-tab="themes"]').click();assert.equal(await page.locator('[data-cn-theme]').count(),1,'last snapshot stays explicitly stale');
    if(process.env.SCREENSHOT_DIR){const fs=require('fs');fs.mkdirSync(process.env.SCREENSHOT_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'cn-research-mobile.png'),fullPage:true});}
    await page.locator('[data-market="us"]').click();await page.locator('.signal-note').first().waitFor();
    assert.equal(await page.locator('#view-research').isVisible(),false);
    assert.equal(await page.locator('.cn-bottom').isVisible(),false);
    assert.match(await page.locator('#data-status').innerText(),/Alpaca/);
    assert.deepEqual(legacy,[],'CN research never fetches retired signals or charts');assert.deepEqual(writes,[],'browser is read-only');assert.deepEqual(errors,[]);
    console.log('PASS: CN themes, ladder, industry/attribution details, watch persistence, history, observed open/reseal, stale-data preservation, two themes, responsive widths, no legacy CN or trading requests, US return.');
  }finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
