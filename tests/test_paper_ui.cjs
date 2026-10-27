/* 使用真实 paper API/SQLite 与明确的测试行情，浏览器流程不连接实盘。 */
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
    browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
    const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
    const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base);await page.locator('.signal-note').first().waitFor();
    await page.locator('#quick-search').fill('NVDA');await page.locator('.signal-note').first().click();
    await page.locator('#dr-paper').click();await page.locator('#paper-create').waitFor();
    await page.locator('#paper-create button').click();await page.locator('#paper-ticket').waitFor();
    assert.equal(await page.locator('#paper-ticket [name=symbol]').inputValue(),'NVDA');
    await page.locator('#paper-ticket [name=qty]').fill('10');
    await page.locator('#paper-ticket [name=reason]').fill('手动回踩练习 <script>bad</script>');
    await page.locator('#paper-ticket button[type=submit]').click();await page.locator('#paper-confirm').waitFor();
    assert.match(await page.locator('#paper-preview').innerText(),/实际模拟成交价取提交后的后续行情/);
    await page.locator('#paper-confirm').click();
    await page.waitForFunction(()=>document.querySelector('#paper-app').textContent.includes('待成交'));
    assert.match(await page.locator('#paper-app').innerText(),/还没有模拟持仓/);
    await fetch(base+'/test/advance',{method:'POST'});
    await page.locator('#paper-refresh').click();
    await page.waitForFunction(()=>document.querySelector('#paper-app').textContent.includes('已成交'));
    assert.match(await page.locator('#paper-app').innerText(),/100\.05/);
    assert.equal(await page.locator('[data-sell=NVDA]').count(),1);
    await page.reload();await page.locator('#paper-ticket').waitFor();
    assert.equal(await page.locator('[data-sell=NVDA]').count(),1,'account survives reload');
    await page.locator('[data-sell=NVDA]').click();
    assert.equal(await page.locator('#paper-ticket [name=side]').inputValue(),'sell');
    await page.locator('#paper-ticket [name=qty]').fill('5');await page.locator('#paper-ticket [name=reason]').fill('分批减仓');
    await page.locator('#paper-ticket button[type=submit]').click();await page.locator('#paper-confirm').click();
    await page.locator('[data-cancel]').first().waitFor();await page.locator('[data-cancel]').first().click();
    await page.waitForFunction(()=>document.querySelector('#paper-app').textContent.includes('已撤销'));
    const download=page.waitForEvent('download');await page.locator('#paper-export').click();assert.match((await download).suggestedFilename(),/paper-us/);
    for(const theme of ['light','dark']){
      await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
      for(const width of [320,390,768,1440]){
        await page.setViewportSize({width,height:844});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${theme} ${width} overflow`);
      }
    }
    await page.setViewportSize({width:390,height:844});
    if(process.env.SCREENSHOT_DIR){const fs=require('fs');fs.mkdirSync(process.env.SCREENSHOT_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'paper-mobile.png'),fullPage:true});}
    assert.deepEqual(errors,[]);
    console.log('PASS: real paper API/SQLite create, detail entry, preview, pending, future fill, reload, reduce, cancel, export, both themes and mobile widths.');
  }finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1});
