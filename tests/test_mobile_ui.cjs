/* 手机改版的用户流程回归。需要安装 Playwright 和 Chromium。
 * CHROMIUM_PATH=/usr/bin/chromium node tests/test_mobile_ui.cjs
 * 所有接口均使用明确的测试数据，不访问或更改真实持仓。
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const repo = path.resolve(__dirname, '..');
const site = path.join(repo, 'site');
const generated = '2026-10-17T03:00:00+00:00';
// 测试数据：验证名称/代码搜索和新增A股详情，不访问真实持仓。
const cnSnapshot = JSON.parse(fs.readFileSync(path.join(site,'data/signals_cn.json'),'utf8'));
const addedCN = [['万向钱潮','000559'],['三花智控','002050'],['三孚股份','603938'],['诺德股份','600110']];
for (const [symbol,code] of addedCN) {
  cnSnapshot.symbols[symbol] = {code,levels:{daily:{last_close:10,bars:100,state:{direction:'up',pivot_pos:'above'}}}};
  cnSnapshot.signals.push({symbol,code,level:'daily',type:'3B',time:'2026-10-21',price:10,score:6,recent:true,confirmed:true,bars_ago:0,resonance:'strong'});
}

const macro = { generated, source: 'UI test fixture', indicators: {vix:{name:'VIX',value:19.99,unit:'',kind:'index',status:'ok',asof:'2026-10-16',change:1,change_pct:1,change_label:'+1%',read:'测试指标',range:[18,22],series:[['2026-10-15',19],['2026-10-16',19.99]]}}, regime:{}, failures:{} };
const positions = {generated, positions:[{symbol:'NVDA',currency:'USD',qty:10,cost:200,mark:225.92,unrealized:259.2,value:2259.2,asset:'STK'}]};
(async () => {
  const browser = await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',args:['--no-sandbox'],headless:true});
  try {
    const context = await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
    let failSignals = false, slowNvda = false;
    await context.route('http://chan.test/**', async route => {
      const name = decodeURIComponent(new URL(route.request().url()).pathname);
      if (name === '/api/signals' && failSignals) return route.fulfill({status:503,body:'unavailable'});
      if (name === '/api/positions') return route.fulfill({json:positions});
      if (name === '/api/macro') return route.fulfill({json:macro});
      let file = name === '/' ? 'index.html' : name.slice(1);
      if (name === '/api/signals') file = 'data/signals.json';
      else if (name === '/api/signals_cn') return route.fulfill({json:cnSnapshot});
      else if (name.startsWith('/api/charts')) file = 'data/' + name.slice('/api/'.length);
      if (slowNvda && name === '/api/charts/NVDA.json') await new Promise(resolve=>setTimeout(resolve,150));
      if (name.startsWith('/api/charts_cn/') && addedCN.some(([symbol])=>name.endsWith('/'+symbol+'.json'))) file='data/charts/NVDA.json';
      const resolved = path.resolve(site,file);
      if (!resolved.startsWith(site + path.sep) || !fs.existsSync(resolved)) return route.fulfill({status:404,body:'not found'});
      return route.fulfill({path:resolved});
    });
    const page = await context.newPage();
    const errors = [], privateRequests = [];
    page.on('request',r=>{if(/\/(?:api\/(?:positions|holdings)|data\/positions_ibkr\.json)(?:[?]|$)/.test(r.url()))privateRequests.push(r.url());});
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('http://chan.test/');
    await page.locator('.signal-note').first().waitFor();
    assert.match(await page.locator('#data-status').innerText(), /Alpaca/);
    // 手机首屏服务真实内容：第一条信号必须在屏幕上方60%内出现。
    const firstSignal = await page.locator('.signal-note').first().boundingBox();
    assert.ok(firstSignal.y < 844 * 0.6, 'signal list pushed below the first screen');
    await page.locator('#btn-filters').click();
    await page.locator('#filter-backdrop').waitFor({state:'visible'});
    assert.equal(await page.locator('#f-q').evaluate(el=>getComputedStyle(el).fontSize),'16px','prevent iOS input zoom');
    assert.equal(await page.locator('#filters').getAttribute('aria-modal'),'true');
    await page.locator('#f-q').fill('NVDA');
    assert.equal(await page.locator('.note-symbol').evaluateAll(es=>es.every(e=>e.textContent==='NVDA')),true);
    // 验证键盘焦点留在面板内，关闭后回到入口。
    await page.locator('#filter-apply').focus();
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(()=>document.activeElement.id),'filter-close');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#filter-backdrop').isVisible(),false);
    assert.equal(await page.evaluate(()=>document.activeElement.id),'btn-filters');
    assert.equal(await page.evaluate(()=>document.body.style.overflow),'');
    // / 快捷键同样打开底部面板，而不是只显示隐藏控件。
    await page.keyboard.press('/');
    assert.equal(await page.locator('#filter-backdrop').isVisible(),true);
    await page.locator('#filter-apply').click();
    await page.locator('.signal-note').first().click();
    await page.locator('#ichart-root canvas').first().waitFor();
    assert.equal(await page.locator('#drawer').isVisible(),true);
    assert.equal(await page.locator('.research-details').getAttribute('open'),null);
    await page.keyboard.press('Escape');
    await page.locator('#drawer').waitFor({state:'hidden'});
    await page.locator('#btn-theme').click();
    assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
    await page.locator('#btn-settings').click();
    await page.locator('#settings-close').focus();
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(()=>document.activeElement.id),'glossary-hints-toggle');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#settings-sheet').isVisible(),false);
    // 持仓入口已移除，旧深链接也无法打开持仓。
    assert.equal(await page.locator('.tab[data-view="holdings"]').count(),0);
    await page.evaluate(()=>{location.hash='holdings';});
    await page.waitForFunction(()=>location.hash==='#signals');
    assert.equal(await page.locator('#view-holdings').isVisible(),false);
    await page.goto('http://chan.test/#holdings');
    await page.waitForFunction(()=>location.hash==='#signals');
    assert.equal(await page.locator('#view-holdings').isVisible(),false);
    await page.locator('.tabs-bottom [data-view="macro"]').click();
    await page.locator('#macro-body .msec').first().waitFor();
    assert.match(await page.locator('#data-status').innerText(),/2026-10-17/);
    assert.match(await page.locator('#macro-body').innerText(),/VIX/);
    const term = page.locator('#macro-body [data-indicator]').first();
    await term.click();
    await page.locator('.gl-sheet, .gl-pop').waitFor({state:'visible'});
    await page.keyboard.press('Escape');
    for (const view of ['symbols','about','signals']) {
      await page.locator('.tabs-bottom [data-view="'+view+'"]').click();
      assert.equal(await page.locator('#view-'+view).isVisible(),true);
    }
    await page.locator('#btn-filters').click();
    await page.locator('#f-reset').click();
    await page.locator('#filter-apply').click();
    await page.locator('[data-market="cn"]').click();
    await page.waitForFunction(()=>document.getElementById('data-status').textContent.includes('东方财富'));
    for (const [symbol,code] of addedCN) {
      await page.locator('#btn-filters').click();
      await page.locator('#f-q').fill(code);
      await page.locator('#filter-apply').click();
      assert.equal(await page.locator('.signal-note').count(),1);
      assert.match(await page.locator('.note-symbol').innerText(),new RegExp(symbol));
      assert.equal(await page.locator('.note-symbol .symbol-code').innerText(),code);
      await page.locator('.signal-note').click();
      await page.locator('#ichart-root canvas').first().waitFor();
      assert.match(await page.locator('#dr-title').innerText(),new RegExp(code));
      await page.keyboard.press('Escape');
      await page.locator('#drawer').waitFor({state:'hidden'});
    }
    await page.locator('[data-market="us"]').click();
    await page.waitForFunction(()=>document.getElementById('data-status').textContent.includes('Alpaca'));
    // 手机到桌面时不能遗留遮罩或滚动锁。
    await page.locator('#btn-filters').click();
    await page.setViewportSize({width:1440,height:1000});
    assert.equal(await page.locator('#filter-backdrop').isVisible(),false);
    assert.equal(await page.evaluate(()=>document.body.style.overflow),'');
    for (const width of [320,375,390,430,768,900,1024,1440]) {
      await page.setViewportSize({width,height:844});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`overflow at ${width}`);
    }
    // 接口失败不可被内置过期数据掩盖，重试必须恢复正常结果。
    failSignals = true;
    await page.reload();
    await page.locator('#retry').waitFor();
    assert.match(await page.locator('#data-status').innerText(),/暂不可用/);
    assert.equal(await page.locator('.signal-note').count(),0);
    failSignals = false;
    await page.locator('#retry').click();
    await page.locator('.signal-note').first().waitFor();
    // 两次图表请求逆序返回时，只有最新标的能够挂载。
    slowNvda = true;
    const race = await page.evaluate(async()=>{
      const host = document.createElement('div'); host.style.width='600px'; document.body.appendChild(host);
      const first = ChanInteractive.mount(host,'NVDA');
      const second = ChanInteractive.mount(host,'AAPL');
      const results = await Promise.all([first,second]);
      const label = host.querySelector('.ichart-host').getAttribute('aria-label');
      ChanInteractive.destroy(); host.remove(); return {results,label};
    });
    assert.deepEqual(race.results,[false,true]);
    assert.match(race.label,/AAPL/);
    assert.deepEqual(errors,[]);
    assert.deepEqual(privateRequests,[],'disabled holdings must not fetch private data');
    console.log('PASS: mobile filters/focus/Escape/shortcut, charts, themes, settings, hidden holdings/deep link, macro glossary, navigation, markets, responsive widths, failure/retry.');
    if (process.env.SCREENSHOT_DIR) {
      fs.mkdirSync(process.env.SCREENSHOT_DIR,{recursive:true});
      await page.setViewportSize({width:390,height:844});
      await page.locator('#btn-theme').click();
      await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'mobile-list.png'),style:'#toast{visibility:hidden}'});
      await page.evaluate(()=>scrollTo({top:0,behavior:'instant'}));
      await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'mobile.png'),style:'#toast{visibility:hidden}'});
      await page.locator('#btn-filters').click();
      await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'filters.png')});
      await page.locator('#filter-apply').click();
      await page.setViewportSize({width:1440,height:1000});
      await page.evaluate(()=>scrollTo({top:0,behavior:'instant'}));
      await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'desktop.png'),style:'#toast{visibility:hidden}'});
      await page.setViewportSize({width:390,height:844});
      for (const theme of ['dark','light']) {
        if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('#btn-theme').click();
        for (const view of ['signals','symbols','macro','about']) {
          await page.locator('.tabs-bottom [data-view="'+view+'"]').click();
          await page.evaluate(()=>scrollTo({top:0,behavior:'instant'}));
          assert.equal(await page.locator('h1:visible').count(),1);
          assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
          await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,theme+'-'+view+'.png'),style:'#toast{visibility:hidden}'});
        }
      }
    }
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
