// Real browser -> Gateway -> Redis -> GPU worker. No mocked inference or network.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const { chromium } = await import(process.env.PSWP_PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PSWP_PLAYWRIGHT_MODULE).href : 'playwright');
const base = process.env.TTOKTTI_DEMO_URL || 'http://localhost:8892';
const out = process.env.TTOKTTI_RESULTS;
if (!out) throw Error('Set TTOKTTI_RESULTS to a new result JSON path.');
const browser = await chromium.launch({headless:true,...(process.env.PSWP_CHROME?{executablePath:process.env.PSWP_CHROME}:{})});
const result={schema_version:1,kind:'real_browser_alternative_demo_not_mobile',base,
  started_at:new Date().toISOString(),conditions:[],errors:[]};
async function open(){
  const context=await browser.newContext({viewport:{width:1400,height:1000}});
  const page=await context.newPage();
  page.on('pageerror',e=>result.errors.push(e.message));
  await page.goto(base);
  await page.waitForFunction(()=>window.latencyDemo?.ready(),null,{timeout:120000});
  await page.locator('#preview').evaluate(image=>image.decode());
  return {context,page};
}
function stats(samples){
  const names=[...new Set(samples.flatMap(s=>Object.keys(s.metrics)))];
  return Object.fromEntries(names.map(key=>{
    const v=samples.map(s=>s.metrics[key]).filter(Number.isFinite).sort((a,b)=>a-b);
    if(!v.length)return [key,null];
    return [key,{n:v.length,p50:v[Math.ceil(v.length*.5)-1],p95:v[Math.ceil(v.length*.95)-1],max:v.at(-1)}];
  }));
}
async function save(){await fs.mkdir(path.dirname(out),{recursive:true});await fs.writeFile(out,JSON.stringify(result,null,2));}
try {
  const first=await open();
  result.metadata=await first.page.evaluate(()=>window.latencyDemo.report().metadata);
  result.warmup=await first.page.evaluate(()=>window.latencyDemo.measure({warmup:true}));
  console.log('WARMUP',JSON.stringify(result.warmup));
  await save();
  await first.context.close();
  for(const [clients,perClient] of [[1,10],[3,5]]){
    const pages=await Promise.all(Array.from({length:clients},()=>open()));
    const started=Date.now();
    const runs=await Promise.all(pages.map(async({page},client)=>{
      const samples=[];
      for(let i=0;i<perClient;i++){
        const sample=await page.evaluate(()=>window.latencyDemo.measure());
        assert.equal(sample.status,'ok');
        assert.ok(sample.analysis.text.length>0);
        assert.ok(sample.metrics.model_generate_ms>0);
        assert.ok(sample.metrics.worker_total_ms>=sample.metrics.model_generate_ms);
        sample.client=client;samples.push(sample);
        console.log('SAMPLE',clients,client,i,Math.round(sample.metrics.request_to_result_ms));
      }
      return samples;
    }));
    const samples=runs.flat();
    const condition={clients,per_client:perClient,load:'closed_loop_one_inflight_per_client',
      elapsed_ms:Date.now()-started,samples,stats:stats(samples)};
    result.conditions.push(condition);
    console.log('CONDITION',JSON.stringify({clients,stats:condition.stats}));
    if(process.env.PSWP_SCREENSHOT)await pages[0].page.screenshot({path:process.env.PSWP_SCREENSHOT,fullPage:true});
    await save();
    for(const {context} of pages)await context.close();
  }
  assert.deepEqual(result.errors,[]);
  result.completed_at=new Date().toISOString();result.passed=true;await save();
  console.log('DONE',out);
} catch(error) {
  result.failure=String(error);await save();throw error;
} finally{await browser.close();}
