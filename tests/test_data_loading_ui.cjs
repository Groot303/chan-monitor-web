/* 只读请求故障回归：请求头/响应体卡住、迟到响应、超时解锁、重试与网络恢复。 */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
async function helperChecks(){
  const source=fs.readFileSync(path.resolve(__dirname,'../site/app.js'),'utf8').split('/* 缠论信号看板')[0];
  function helper(fetch){const scope={window:{},AbortController,Promise,setTimeout,clearTimeout,fetch};vm.runInNewContext(source,scope);return scope.window.ChanData;}
  let signal;
  const stuck=helper((url,options)=>{signal=options.signal;return new Promise(()=>{});});
  await assert.rejects(stuck.getJSON('/test',{timeoutMs:25}),e=>e.name==='TimeoutError');assert.equal(signal.aborted,true,'cancel pending socket when possible');
  const body=helper(()=>Promise.resolve({ok:true,json:()=>new Promise(()=>{})}));
  await assert.rejects(body.getJSON('/body',{timeoutMs:25}),e=>e.name==='TimeoutError','deadline includes JSON body');
  let release,delivered=false;
  const late=helper(()=>new Promise(resolve=>{release=resolve;}));
  await late.getJSON('/late',{timeoutMs:25}).then(()=>{delivered=true;},()=>{});
  release({ok:true,json:()=>Promise.resolve({old:true})});await new Promise(r=>setTimeout(r,5));assert.equal(delivered,false,'late response cannot succeed after deadline');
  let goodSignal;
  const good=helper((url,options)=>{goodSignal=options.signal;assert.equal(options.cache,'no-store');assert.equal(options.method,undefined);return Promise.resolve({ok:true,json:()=>Promise.resolve({ok:true})});});
  assert.equal((await good.getJSON('/fresh',{timeoutMs:25})).ok,true);
  await new Promise(r=>setTimeout(r,35));assert.equal(goodSignal.aborted,false,'successful reads clear the deadline');
  const bad=helper(()=>Promise.resolve({ok:false,status:503}));
  await assert.rejects(bad.getJSON('/http',{httpError:s=>'status '+s}),/status 503/);
}
(async()=>{
  await helperChecks();
  const base='http://127.0.0.1:18493';
  const server=spawn('python',['-m','uvicorn','tests.paper_fixture_server:app','--host','127.0.0.1','--port','18493','--log-level','error'],{cwd:path.resolve(__dirname,'..'),stdio:['ignore','ignore','pipe']});
  let logs='',browser;server.stderr.on('data',b=>logs+=b.toString());
  try{
    let ready=false;for(let i=0;i<80;i++){try{if((await fetch(base+'/api/signals')).ok){ready=true;break;}}catch(_){}await new Promise(r=>setTimeout(r,100));}assert.ok(ready,logs);
    browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
    const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
    const page=await context.newPage(),errors=[],writes=[],held=[];let blocked='/api/signals';
    page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().includes('/api/')&&r.method()!=='GET')writes.push(r.url());});
    await page.route('**/api/**',async route=>{
      if(new URL(route.request().url()).pathname===blocked)await new Promise(resolve=>held.push(resolve));
      try{await route.continue();}catch(_){} // 超时后旧连接可能已经被浏览器取消。
    });
    const unblock=()=>{blocked='';held.splice(0).forEach(resolve=>resolve());};
    const request=path=>page.waitForRequest(r=>new URL(r.url()).pathname===path);
    await page.clock.install();
    let started=request('/api/signals');await page.goto(base,{waitUntil:'domcontentloaded'});await started;
    await page.clock.runFor(15010);await page.locator('#retry').waitFor();assert.match(await page.locator('#sig-results').innerText(),/请求超时/);
    assert.equal(await page.locator('#sig-results .skeleton').count(),0);
    unblock();await page.locator('#retry').click();await page.locator('.signal-note').first().waitFor();
    started=request('/api/signals');await page.evaluate(()=>dispatchEvent(new Event('online')));await started;await page.locator('.signal-note').first().waitFor();
    started=request('/api/signals');await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));await started;await page.locator('.signal-note').first().waitFor();
    blocked='/api/cn/research';started=request(blocked);await page.locator('[data-market="cn"]').click();await started;
    await page.clock.runFor(15010);await page.waitForFunction(()=>document.getElementById('cn-status')?.textContent.includes('请求超时'));
    unblock();await page.locator('#cn-refresh').click();await page.locator('[data-cn-theme]').first().waitFor();
    const themes=await page.locator('[data-cn-theme]').count();
    blocked='/api/cn/research';started=request(blocked);await page.locator('#cn-refresh').click();await started;await page.clock.runFor(15010);
    await page.waitForFunction(()=>document.getElementById('cn-status').textContent.includes('请求超时'));
    assert.equal(await page.locator('[data-cn-theme]').count(),themes,'CN last snapshot survives timeout with stale label');
    unblock();await page.evaluate(()=>dispatchEvent(new Event('online')));
    await page.waitForFunction(()=>!document.getElementById('cn-status').textContent.includes('请求超时'));
    await page.locator('[data-market="us"]').click();await page.locator('.signal-note').first().waitFor();
    blocked='/api/strategy/us';started=request(blocked);await page.locator('.tabs-bottom [data-view="paper"]').click();await started;await page.clock.runFor(15010);
    await page.locator('#strategy-retry').waitFor();assert.match(await page.locator('#paper-app').innerText(),/请求超时/);
    assert.doesNotMatch(await page.locator('#paper-app').innerText(),/正在读取服务器/);
    unblock();await page.locator('#strategy-retry').click();await page.locator('#strategy-refresh').waitFor();
    const balance=await page.locator('.paper-balance').innerText();
    blocked='/api/strategy/us';started=request(blocked);await page.locator('#strategy-refresh').click();await started;await page.clock.runFor(15010);
    await page.waitForFunction(()=>document.getElementById('strategy-status')?.textContent.includes('连接中断'));
    assert.equal(await page.locator('.paper-balance').innerText(),balance,'strategy retains last report and labels stale');
    unblock();await page.locator('#strategy-refresh').click();await page.waitForFunction(()=>!document.querySelector('.strategy-error'));
    blocked='/api/macro';started=request(blocked);await page.locator('.tabs-bottom [data-view="macro"]').click();await started;await page.clock.runFor(15010);
    await page.locator('#macro-retry').waitFor();assert.match(await page.locator('#macro-body').innerText(),/请求超时/);
    unblock();await page.locator('#macro-retry').click();await page.locator('#macro-retry').waitFor({state:'hidden'});
    await page.locator('[data-market="cn"]').click();await page.locator('[data-cn-theme]').first().waitFor();
    await page.locator('.cn-bottom [data-cn-tab="relay"]').click();await page.locator('.cn-relay-row').waitFor();
    blocked='/api/cn/relay';started=request(blocked);await page.locator('#cn-refresh').click();await started;
    // 主研究快照同时刷新；等它完成，避免把非故障请求也快进到超时。
    await page.waitForTimeout(100);
    await page.clock.runFor(15010);await page.locator('[data-relay-retry]').waitFor();
    assert.match(await page.locator('#cn-relay-app').innerText(),/请求超时[\s\S]*保留上次分析/);
    assert.equal(await page.locator('.cn-relay-row').count(),1);
    unblock();await page.locator('[data-relay-retry]').click();await page.locator('[data-relay-retry]').waitFor({state:'hidden'});
    assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
    console.log('PASS: bounded header/body reads, late response rejection, US/CN/strategy/macro/relay hung requests, retry/unlock, stale preservation, online recovery and no browser API writes.');
  }finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
