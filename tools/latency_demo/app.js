const $ = id => document.getElementById(id);
const labels = {
  request_to_result_ms:'요청 → 결과 수신', client_prepare_ms:'브라우저 이미지 준비',
  send_to_result_ms:'전송 → 결과 수신', gateway_prepare_ms:'Gateway 이미지 처리',
  queue_age_ms:'Redis 큐 대기 포함', image_decode_ms:'서버 이미지 디코딩',
  model_prepare_ms:'모델 입력 준비·GPU 전송', model_generate_ms:'모델 생성 전체',
  first_token_ms:'↳ 첫 토큰까지 (생성의 일부)', model_decode_tail_ms:'↳ 나머지 토큰 생성',
  worker_total_ms:'Worker 전체', receive_to_raf_ms:'결과 수신 → 화면 갱신 기회',
  request_to_raf_ms:'요청 → 화면 갱신 기회'
};
const state={ready:false,connected:false,busy:false,stop:false,repeat:false,samples:[],failures:[],metadata:null};
const pending=new Map();
const preview=$('preview'), video=$('video');
let source=preview, objectURL=null, cameraStream=null;
const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/stream/demo-${crypto.randomUUID()}`);
function buttons(){
  for(const id of ['once','repeat']) $(id).disabled=!state.ready||!state.connected||state.busy||state.repeat;
  for(const id of ['file','sample','camera','clear']) $(id).disabled=state.busy||state.repeat;
  $('stop').disabled=!state.repeat;
}
ws.onopen=()=>{
  ws.send(JSON.stringify({type:'CONFIG',latency_metrics:true,worksession_id:'browser-demo',video_path:''}));
  state.connected=true; $('connection').textContent='Gateway 연결됨'; buttons();
};
ws.onclose=()=>{
  state.connected=false;$('connection').textContent='연결 끊김 · 새로고침 필요';
  for(const job of pending.values()) job.fail('연결이 종료되었습니다.');
  buttons();
};
ws.onerror=()=>{$('connection').textContent='연결 오류';};
async function refreshStatus(){
  try{
    const data=await(await fetch('/demo/status')).json();
    state.ready=data.ready;state.metadata=data;
    $('model').textContent=data.ready?`${data.model} · ${data.device} · FP16`:data.reason;
    if(data.ready&&!state.samples.length&&!state.busy) $('activity').textContent='준비되었습니다. 이미지로 분석을 시작하세요.';
  }catch{state.ready=false;$('model').textContent='서버 상태 확인 실패';}
  buttons();
}
refreshStatus();setInterval(refreshStatus,3000);
function afterPaintOpportunity(){
  return new Promise(resolve=>{
    if(document.visibilityState!=='visible') return resolve(false);
    let done=false;
    const timer=setTimeout(()=>{done=true;resolve(false)},1000);
    requestAnimationFrame(()=>requestAnimationFrame(()=>{
      if(!done){done=true;clearTimeout(timer);resolve(true);}
    }));
  });
}
ws.onmessage=async event=>{
  const data=JSON.parse(event.data);
  if(data.type!=='FRAME_RESULT') return;
  const job=pending.get(data.frame_id);
  if(!job) return;
  if(data.status!=='ok') {job.fail(data.error||'분석 실패');return;}
  const received=performance.now();
  clearTimeout(job.timer);pending.delete(data.frame_id);
  const metrics={...data.timing,client_prepare_ms:job.sent-job.start,
    send_to_result_ms:received-job.sent,request_to_result_ms:received-job.start};
  $('analysis').textContent=data.analysis.text;
  $('lastTotal').textContent=metrics.request_to_result_ms.toFixed(1);
  const warmup=job.warmup||data.analysis.model_call===1;
  $('lastMeta').textContent=`${warmup?'워밍업 · 통계 제외':'측정 완료'} · ${data.analysis.output_tokens} tokens${data.analysis.token_limit_reached?' · 출력 길이 제한 도달':''}`;
  const sample={frame_id:data.frame_id,status:'ok',warmup,metrics,
    analysis:data.analysis,visibility:document.visibilityState,utc:new Date().toISOString()};
  const painted=await afterPaintOpportunity();
  if(painted){
    const end=performance.now();
    metrics.receive_to_raf_ms=end-received;metrics.request_to_raf_ms=end-job.start;
  }
  sample.raf_observed=painted;
  state.samples.push(sample);
  $('activity').textContent='분석 완료';
  state.busy=false;render();buttons();job.resolve(sample);
};
function percentile(values,p){return values[Math.max(0,Math.ceil(values.length*p)-1)];}
function summary(){
  const samples=state.samples.filter(s=>!s.warmup).slice(-120);
  const metrics={};
  for(const key of Object.keys(labels)){
    const values=samples.map(s=>s.metrics[key]).filter(v=>Number.isFinite(v)&&v>=0).sort((a,b)=>a-b);
    if(values.length) metrics[key]={n:values.length,p50:percentile(values,.5),p95:percentile(values,.95),max:values.at(-1)};
  }
  return {metadata:state.metadata,window:120,completed:state.samples.length,failures:state.failures.length,pending:pending.size,metrics};
}
function render(){
  const stats=summary();
  $('counts').textContent=`완료 ${stats.completed} (워밍업 ${state.samples.filter(s=>s.warmup).length}) · 실패 ${stats.failures} · 대기 ${stats.pending}`;
  $('metrics').replaceChildren();
  for(const [key,label] of Object.entries(labels)){
    const row=document.createElement('tr'),m=stats.metrics[key];
    for(const value of [label,m?.n??'—',m?.p50?.toFixed(1)??'—',m?.p95?.toFixed(1)??'—',m?.max?.toFixed(1)??'—']){
      const cell=document.createElement('td');cell.textContent=value;row.append(cell);
    }$('metrics').append(row);
  }
  $('bars').replaceChildren();
  const last=state.samples.at(-1);
  if(last) for(const key of ['queue_age_ms','model_prepare_ms','model_generate_ms']){
    const value=last.metrics[key]??0;
    const label=document.createElement('div');label.className='muted';label.textContent=`${labels[key]} · ${value.toFixed(1)} ms`;
    const bar=document.createElement('div');bar.className='bar';
    const fill=document.createElement('i');fill.style.width=`${Math.min(100,value/last.metrics.request_to_result_ms*100)}%`;
    bar.append(fill);label.append(bar);$('bars').append(label);
  }
}
async function measure({warmup=false}={}){
  if(state.busy||!state.ready||!state.connected) throw Error('모델·연결 준비 상태를 확인하세요.');
  state.busy=true;buttons();
  const start=performance.now();
  try{
    if(source===preview) await preview.decode();
    if(source===video&&video.readyState<2) throw Error('영상을 먼저 재생하고 프레임이 표시된 뒤 분석하세요.');
    const width=source===video?video.videoWidth:preview.naturalWidth;
    const height=source===video?video.videoHeight:preview.naturalHeight;
    if(!width||!height) throw Error('영상 또는 이미지가 준비되지 않았습니다.');
    const scale=Math.min(1,448/Math.max(width,height));
    const canvas=document.createElement('canvas');canvas.width=Math.round(width*scale);canvas.height=Math.round(height*scale);
    canvas.getContext('2d').drawImage(source,0,0,canvas.width,canvas.height);
    const image=canvas.toDataURL('image/jpeg',.8),id=crypto.randomUUID();
    const payload=JSON.stringify({type:'FRAME',frame_id:id,image,timestamp:Date.now()});
    return await new Promise((resolve,reject)=>{
      const fail=message=>{
        const job=pending.get(id);if(!job)return;
        clearTimeout(job.timer);pending.delete(id);
        state.failures.push({frame_id:id,error:message,elapsed_ms:performance.now()-start});
        state.busy=false;$('activity').textContent=message;render();buttons();reject(Error(message));
      };
      pending.set(id,{start,sent:performance.now(),warmup,resolve,fail,timer:setTimeout(()=>fail('120초 안에 결과가 오지 않았습니다.'),120000)});
      try{ws.send(payload);$('activity').textContent='이미지를 분석하고 있습니다…';}
      catch{fail('프레임을 보내지 못했습니다.');}
    });
  }catch(error){state.busy=false;buttons();throw error;}
}
async function repeat(count=10){
  if(state.repeat) return;
  state.repeat=true;state.stop=false;buttons();
  try{for(let i=0;i<count&&!state.stop;i++){await measure();$('activity').textContent=`${i+1}/${count} 완료`;}}
  catch(error){$('activity').textContent=error.message;}
  finally{state.repeat=false;buttons();}
}
function releaseSource(){
  cameraStream?.getTracks().forEach(track=>track.stop());cameraStream=null;
  video.pause();video.srcObject=null;video.removeAttribute('src');
  if(objectURL){URL.revokeObjectURL(objectURL);objectURL=null;}
}
async function sample(){
  releaseSource();source=preview;preview.style.display='block';video.style.display='none';
  preview.src='/demo/sample.jpg';await preview.decode();
}
$('file').onchange=async event=>{
  const file=event.target.files[0];if(!file)return;
  releaseSource();objectURL=URL.createObjectURL(file);
  if(file.type.startsWith('video/')){source=video;video.src=objectURL;video.style.display='block';preview.style.display='none';}
  else{source=preview;preview.src=objectURL;preview.style.display='block';video.style.display='none';}
};
$('sample').onclick=()=>sample().catch(e=>$('activity').textContent=e.message);
$('camera').onclick=async()=>{
  try{releaseSource();cameraStream=await navigator.mediaDevices.getUserMedia({video:true,audio:false});
    video.srcObject=cameraStream;source=video;video.style.display='block';preview.style.display='none';await video.play();}
  catch(error){$('activity').textContent='카메라를 열지 못했습니다: '+error.message;}
};
$('once').onclick=()=>measure().then(()=>$('activity').textContent='분석 완료').catch(e=>$('activity').textContent=e.message);
$('repeat').onclick=()=>repeat();
$('stop').onclick=()=>{state.stop=true;$('activity').textContent='진행 중인 분석이 끝나면 멈춥니다.';};
$('clear').onclick=()=>{state.samples=[];state.failures=[];render();};
function report(){return {schema_version:1,benchmark_kind:'browser_alternative_not_native_app',...summary(),samples:state.samples,errors:state.failures};}
$('export').onclick=()=>{
  const url=URL.createObjectURL(new Blob([JSON.stringify(report(),null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='ttoktti-latency.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
window.addEventListener('beforeunload',()=>{releaseSource();ws.close();});
window.latencyDemo={measure,repeat,report,ready:()=>state.ready&&state.connected,loadSample:sample};
sample().catch(()=>$('activity').textContent='예제를 불러오지 못했습니다. 이미지를 선택해주세요.');
render();
