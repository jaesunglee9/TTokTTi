const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');
const Module = require('node:module');
const build = process.env.TTOKTTI_LATENCY_BUILD;
if (!build) throw new Error('Set TTOKTTI_LATENCY_BUILD to the compiled test directory.');
const { LatencyWindow, FrameLatencyTracker } = require(path.join(build, 'telemetry/latency.js'));
test('nearest-rank percentiles use a bounded window and reject invalid durations', () => {
  const window = new LatencyWindow(20);
  for (let n=1;n<=25;n++) window.observe('ms',n);
  window.observe('ms',NaN); window.observe('ms',-1);
  assert.deepEqual(window.snapshot().ms,{n:20,p50:15,p95:24,max:25});
});
test('same-device monotonic elapsed time, duplicate rejection and missing capture timestamp', () => {
  let now=100;
  const tracker=new FrameLatencyTracker(()=>now);
  tracker.start('f1',20); now=400;
  tracker.complete('f1','ok',{queue_age_ms:50,danger_check_ms:100,gateway_prepare_ms:-9});
  const summary=tracker.snapshot();
  assert.equal(summary.metrics.send_to_result_ms.p50,300);
  assert.equal(summary.metrics.capture_request_to_result_ms.p50,380);
  assert.equal(summary.metrics.queue_age_ms.p50,50);
  assert.equal(summary.metrics.gateway_prepare_ms,undefined);
  assert.equal(tracker.complete('f1','ok',{}),false);
  tracker.start('f2'); now=500; tracker.complete('f2','ok',{});
  assert.equal(tracker.snapshot().metrics.capture_request_to_result_ms.n,1);
});
test('timeouts, errors, bounded pending capacity and disconnects are counted separately', () => {
  let now=0; const tracker=new FrameLatencyTracker(()=>now,100,2);
  tracker.start('f1'); tracker.start('f2'); tracker.start('f3');
  assert.equal(tracker.counts.evicted,1);
  tracker.complete('f2','error',{});
  assert.equal(tracker.counts.failed,1);
  now=101; tracker.expire();
  assert.equal(tracker.counts.timedOut,1);
  assert.equal(tracker.complete('f3','ok',{}),false);
  tracker.start('f4'); tracker.abandon();
  assert.equal(tracker.counts.abandoned,1);
  assert.equal(tracker.snapshot().pending,0);
  assert.deepEqual(tracker.snapshot().metrics,{});
});
test('websocket opt-in, frame correlation, safe completion, legacy alerts and intentional stop', () => {
  const originalLoad=Module._load;
  Module._load=function(name,...args) {
    if(name==='react-native') return {Alert:{alert(){throw Error('unexpected alert')}}};
    return originalLoad.call(this,name,...args);
  };
  const instances=[];
  class Socket {
    static OPEN=1;
    readyState=1; sent=[];
    constructor(){instances.push(this)}
    send(data){this.sent.push(JSON.parse(data))}
    close(){this.onclose?.({reason:'closed'})}
  }
  const previousWS=global.WebSocket;
  global.WebSocket=Socket;
  let stream;
  try {
    const SafetyStream=require(path.join(build,'api/stream.js')).default;
    const alerts=[];
    stream=new SafetyStream('test',{worksession_id:'1',video_path:'',measureLatency:true,accessToken:'fixture-jwt'},data=>alerts.push(data));
    stream.connect();
    const ws=instances[0]; ws.onopen();
    assert.equal(ws.sent[0].latency_metrics,true);
    assert.equal(ws.sent[0].access_token,'fixture-jwt');
    assert.equal(stream.sendFrame('fake-image',{captureRequestedAt:performance.now()}),true);
    const frame=ws.sent[1];
    assert.ok(frame.frame_id);
    assert.equal(frame.access_token,undefined);
    stream.updateAccessToken('renewed-jwt');
    assert.equal(ws.sent.at(-1).access_token,'renewed-jwt');
    ws.onmessage({data:JSON.stringify({type:'FRAME_RESULT',frame_id:frame.frame_id,status:'ok',timing:{worker_total_ms:1}})});
    assert.equal(stream.getLatencySummary().counts.completed,1);
    assert.equal(alerts.length,0);
    ws.onmessage({data:JSON.stringify({type:'DANGER',message:'test'})});
    assert.equal(alerts.length,1);
    ws.onmessage({data:JSON.stringify({type:'REPORT_RESULT',status:'error',message:'storage failed'})});
    assert.equal(alerts.length,2);
    assert.equal(stream.sendFrame('fake-image'),false);
    assert.equal(stream.getLatencySummary().counts.throttled,1);
    stream.disconnect(); stream.connect();
    assert.equal(instances.length,1);
  } finally {
    stream?.disconnect(); Module._load=originalLoad; global.WebSocket=previousWS;
  }
});
