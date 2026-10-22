import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.PSWP_PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.PSWP_CHROME});
try{
 const page=await browser.newPage({viewport:{width:1400,height:1000}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://localhost:8892/memory');
 await page.waitForFunction(()=>document.querySelectorAll('#rows tr').length===4);
 assert.match(await page.locator('#status').textContent(),/측정 완료/);
 assert.match(await page.locator('#finding').textContent(),/63.6%/);
 await page.locator('#checkpoint').selectOption('5');
 assert.match(await page.locator('#raw').textContent(),/Recent observations:/);
 await page.locator('#checkpoint').selectOption('30');
 await page.waitForFunction(()=>document.querySelector('video').readyState>=1);
 await page.locator('#seek').click();
 await page.waitForFunction(()=>Math.abs(document.querySelector('video').currentTime-455)<1);
 const video=await page.request.get('http://localhost:8892/demo/memory-video.mp4',{headers:{Range:'bytes=0-1023'}});
 assert.equal(video.status(),206);
 assert.equal((await video.body()).length,1024);
 const json=await(await page.request.get('http://localhost:8892/demo/memory-results.json')).json();
 assert.equal(json.passed,true);assert.equal(json.observations.length,30);assert.equal(json.compressions.length,6);
 for(const c of json.checkpoints){
  assert.equal(c.natural_answers.length,6);assert.equal(c.fixed_output_control.length,6);
  for(const s of c.fixed_output_control)assert.equal(s.output_tokens,32);
 }
 const health=await(await page.request.get('http://localhost:8892/demo/status')).json();
 assert.equal(health.ready,true,'Demo worker must be restored');
 await page.screenshot({path:process.env.PSWP_SCREENSHOT,fullPage:true});
 assert.deepEqual(errors,[]);
 console.log('PASS: completed report, four paired checkpoints, video seeking/range, actual 32-token control, demo worker restored');
}finally{await browser.close()}
