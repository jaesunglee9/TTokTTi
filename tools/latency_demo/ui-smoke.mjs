import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.PSWP_PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.PSWP_CHROME});
try{
  const page=await browser.newPage({viewport:{width:1400,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://localhost:8892');
  await page.waitForFunction(()=>window.latencyDemo?.ready());
  await page.locator('#preview').evaluate(image=>image.decode());
  const image=await(await page.request.get('http://localhost:8892/demo/sample.jpg')).body();
  await page.locator('#file').setInputFiles({name:'sample.jpg',mimeType:'image/jpeg',buffer:image});
  await page.locator('#once').click();
  await page.waitForFunction(()=>window.latencyDemo.report().completed===1,null,{timeout:30000});
  assert.equal(await page.locator('#activity').textContent(),'분석 완료');
  assert.ok((await page.locator('#analysis').textContent()).length>10);
  const downloaded=page.waitForEvent('download');
  await page.locator('#export').click();
  const download=await downloaded;
  const stream=await download.createReadStream();
  const chunks=[];for await(const chunk of stream) chunks.push(chunk);
  const exported=JSON.parse(Buffer.concat(chunks).toString());
  assert.equal(exported.completed,1);assert.equal(exported.samples.length,1);
  await page.locator('#clear').click();
  assert.equal(await page.evaluate(()=>window.latencyDemo.report().completed),0);

  // Generate a short video fixture from the public sample; no webcam permission.
  const clip=await page.evaluate(async()=>{
    const image=document.getElementById('preview');await image.decode();
    const canvas=document.createElement('canvas');canvas.width=448;canvas.height=336;
    const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0,448,336);
    const stream=canvas.captureStream(10),chunks=[];
    const recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'});
    const finished=new Promise(resolve=>{recorder.onstop=resolve});
    recorder.ondataavailable=e=>chunks.push(e.data);
    recorder.start(100);
    for(let i=0;i<10;i++){
      ctx.drawImage(image,0,0,448,336);
      ctx.fillStyle=i%2?'#ffffff':'#000000';ctx.fillRect(0,0,2,2);
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    recorder.stop();await finished;stream.getTracks().forEach(t=>t.stop());
    return [...new Uint8Array(await new Blob(chunks,{type:'video/webm'}).arrayBuffer())];
  });
  await page.locator('#file').setInputFiles({name:'sample.webm',mimeType:'video/webm',buffer:Buffer.from(clip)});
  assert.ok(clip.length>1000,'Video fixture must contain encoded frames');
  await page.waitForFunction(()=>document.getElementById('video').readyState>=1);
  await page.locator('#video').evaluate(video=>video.play());
  await page.waitForFunction(()=>document.getElementById('video').readyState>=2);
  await page.locator('#video').evaluate(video=>video.pause());
  await page.locator('#once').click();
  await page.waitForFunction(()=>window.latencyDemo.report().completed===1,null,{timeout:30000});
  assert.equal(await page.locator('#activity').textContent(),'분석 완료');
  await page.screenshot({path:process.env.PSWP_SCREENSHOT,fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: image upload, real inference via button, JSON export, reset, video frame upload, no page errors');
}finally{await browser.close()}
