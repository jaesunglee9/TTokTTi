const assert=require('node:assert/strict');
const test=require('node:test');
const Module=require('node:module');
const path=require('node:path');
test('REST and stream token renewal share one request and rotate stored tokens',async()=>{
 const build=process.env.TTOKTTI_LATENCY_BUILD;
 const stored=new Map([['refresh_token','old-refresh']]);
 let calls=0,fail=false;
 const storage={getItem:async key=>stored.get(key)??null,setItem:async(k,v)=>{stored.set(k,v)},multiRemove:async keys=>keys.forEach(k=>stored.delete(k))};
 const axios={create:()=>({interceptors:{request:{use(){}},response:{use(){}}}}),
 post:async()=>{calls++;await new Promise(r=>setImmediate(r));if(fail)throw Error('refresh failed');return {data:{access:'new-access',refresh:'new-refresh'}}}};
 const original=Module._load;
 Module._load=function(name,...args){if(name==='axios')return {__esModule:true,default:axios};if(name==='@react-native-async-storage/async-storage')return {__esModule:true,default:storage};return original.call(this,name,...args)};
 try{
  const {refreshAccessToken}=require(path.join(build,'api/client.js'));
  const first=refreshAccessToken(),second=refreshAccessToken();
  assert.equal(first,second);assert.deepEqual(await Promise.all([first,second]),['new-access','new-access']);
  assert.equal(calls,1);assert.equal(stored.get('refresh_token'),'new-refresh');
  fail=true;await assert.rejects(refreshAccessToken(),/refresh failed/);
  fail=false;assert.equal(await refreshAccessToken(),'new-access');assert.equal(calls,3);
 }finally{Module._load=original}
});
