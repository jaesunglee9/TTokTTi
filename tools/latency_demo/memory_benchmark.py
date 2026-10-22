"""Paired real-GPU memory experiment. Reuses production compression and Q&A prompts."""
import asyncio, base64, hashlib, io, json, sys, time
from pathlib import Path
from types import SimpleNamespace
import av
import torch
from PIL import Image
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.latency_demo.model_worker import Engine, FirstToken, StoppingCriteriaList
from core.inference import SafetyAnalyzer
DATA=Path('/tmp/ttoktti-runtime/memory-benchmark')
OUT=ROOT/'performance-results/memory-video-20261022.json'
QUESTION="In exactly two short sentences, summarize the earlier events in chronological order and describe what is happening now. Mention only events supported by the observations."
OBSERVE="Describe the visible characters, objects, and their actions in this animation frame in two short factual sentences. Do not infer events outside the image. Answer in English."
CHECKPOINTS={5,10,20,30}

class LocalTransport:
    """Runs actual Transformers inference; API-shaped wrapper reuses SafetyAnalyzer methods.
    Streaming requests are collected, so first-token timing is GPU timing, not delivery timing."""
    def __init__(self,engine):
        self.engine=engine
        self.last=None
        self.calls=[]
    @torch.inference_mode()
    def generate(self,messages,max_tokens=150,fixed=False):
        begin=time.perf_counter()
        converted=[]
        for message in messages:
            parts=[]
            for part in message['content']:
                if part['type']=='image_url':
                    img=Image.open(io.BytesIO(base64.b64decode(part['image_url']['url'].split(',',1)[-1]))).convert('RGB')
                    parts.append({'type':'image','image':img})
                else: parts.append(part)
            converted.append({'role':message['role'],'content':parts})
        inputs=self.engine.processor.apply_chat_template(converted,tokenize=True,add_generation_prompt=True,return_dict=True,return_tensors='pt').to('cuda')
        torch.cuda.synchronize()
        prepared=time.perf_counter()
        first=FirstToken(prepared)
        options={'max_new_tokens':max_tokens,'do_sample':False,'stopping_criteria':StoppingCriteriaList([first])}
        if fixed:options['min_new_tokens']=max_tokens
        generated=self.engine.model.generate(**inputs,**options)
        torch.cuda.synchronize()
        generated_at=time.perf_counter()
        ids=generated[0,inputs.input_ids.shape[1]:]
        text=self.engine.processor.decode(ids,skip_special_tokens=True).strip()
        assert text,'Empty real-model response'
        self.last={'text':text,'input_tokens':inputs.input_ids.shape[1],'output_tokens':len(ids),
            'token_limit_reached':len(ids)>=max_tokens,
            'prepare_ms':(prepared-begin)*1000,'generate_ms':(generated_at-prepared)*1000,
            'first_token_ms':first.first_ms,'total_ms':(time.perf_counter()-begin)*1000,
            'fixed_output_tokens':fixed}
        self.calls.append(self.last)
        return self.last
    async def create(self,**kwargs):
        result=self.generate(kwargs['messages'],kwargs['max_tokens'])
        if kwargs.get('stream'):
            async def chunks():
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=result['text']))])
            return chunks()
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=result['text']))])

def save(result):
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2))
def frames():
    # Actual decoded video, 30 observations spanning t=20..455 seconds.
    targets=[20+15*i for i in range(30)]
    selected=[]
    container=av.open(str(DATA/'source.mp4'))
    stream=container.streams.video[0]
    for index,target in enumerate(targets,1):
        container.seek(int(target/stream.time_base),stream=stream,backward=True)
        for frame in container.decode(stream):
            seconds=float(frame.pts*stream.time_base)
            if seconds>=target:
                img=frame.to_image();img.thumbnail((448,448))
                path=DATA/f'frame-{index:02d}.jpg';img.save(path,quality=80)
                selected.append({'index':index,'target_seconds':target,'actual_seconds':seconds,'path':str(path),
                    'base64':base64.b64encode(path.read_bytes()).decode()})
                break
    assert len(selected)==30
    container.close()
    return selected
def context(long_term,history):
    return f"Long-term memory context: {long_term} | Recent observations: "+(
        " | ".join(m['observation'] for m in history) if history else "No recent context available.")
async def main():
    selected=frames()
    engine=Engine()
    transport=LocalTransport(engine)
    analyzer=SafetyAnalyzer.__new__(SafetyAnalyzer)
    analyzer.client=SimpleNamespace(chat=SimpleNamespace(completions=transport))
    analyzer.model_name=engine.metadata['model']
    result={'schema_version':1,'kind':'real_video_memory_comparison','started_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
      'source':json.loads((DATA/'source.json').read_text()),'metadata':engine.metadata,
      'conditions':{'sample_times_seconds':[f['actual_seconds'] for f in selected],'compression_every_observations':5,
       'checkpoints':sorted(CHECKPOINTS),'repeats':3,'question':QUESTION,'greedy_both_conditions':True,
       'fixed_output_control_tokens':32,'transport':'in-process real GPU, no network/queue/browser timing',
       'original_methods':['SafetyAnalyzer.compress_memory','SafetyAnalyzer.answer_question'],
       'sampling_note':'One observation per 15 seconds; replaces production action-check cadence for a controlled experiment.'},
      'warmups':[],'observations':[],'compressions':[],'checkpoints':[],'passed':False}
    for contents in [[{'type':'text','text':'Summarize briefly: a rabbit sits in a field.'}],
                     analyzer._build_multi_frame_content(OBSERVE,[selected[0]['base64']])]:
        result['warmups'].append(transport.generate([{'role':'user','content':contents}],32))
    raw=[];short=[];long_term="No prior context."
    for f in selected:
        current=[x['base64'] for x in selected[max(0,f['index']-3):f['index']]]
        action=await analyzer.detect_action(current)
        action_metrics=dict(transport.last)
        description=transport.generate([{'role':'user','content':analyzer._build_multi_frame_content(OBSERVE,[f['base64']])}],64)
        entry={'timestamp':f"T+{f['actual_seconds']:.2f}s",'action':action,'observation':description['text']}
        raw.append(entry);short.append(entry)
        result['observations'].append({'index':f['index'],'timestamp_seconds':f['actual_seconds'],
            'frame_sha256':hashlib.sha256(Path(f['path']).read_bytes()).hexdigest(),
            'entry':entry,'action_metrics':action_metrics,'observation_metrics':dict(description)})
        if len(short)>=5:
            summary=await analyzer.compress_memory(short)
            assert summary!='Failed to compress memory.'
            metrics=dict(transport.last)
            long_term=summary if long_term=="No prior context." else long_term+" "+summary
            result['compressions'].append({'after_observations':len(raw),'source_entries':list(short),
                'summary':summary,'metrics':metrics,'long_term_memory':long_term})
            short=[]
        print(json.dumps({'event':'observation','n':len(raw),'compressions':len(result['compressions'])}),flush=True)
        save(result)
        if len(raw) not in CHECKPOINTS:continue
        contexts={'raw':context("No prior context.",raw),'compressed':context(long_term,short)}
        checkpoint={'observations':len(raw),'contexts':contexts,'natural_answers':[],'fixed_output_control':[]}
        result['checkpoints'].append(checkpoint)
        for repeat in range(3):
            order=['raw','compressed'] if repeat%2==0 else ['compressed','raw']
            for mode in order:
                begin=time.perf_counter()
                answer=''.join([chunk async for chunk in analyzer.answer_question(current,QUESTION,contexts[mode])])
                assert answer and answer==transport.last['text']
                checkpoint['natural_answers'].append({'mode':mode,'repeat':repeat,**dict(transport.last),
                    'method_total_ms':(time.perf_counter()-begin)*1000})
            # Same question/images and exactly 32 output tokens: isolates output-length confounding.
            for mode in reversed(order):
                prompt=(f"Recent Event History Timeline:\n{contexts[mode]}\n"
                    "You are an egocentric AI assistant analyzing the user's view in real time. "
                    f"User Question: {QUESTION}\n"
                    "Provide a clear, conversational answer directly addressing the user based on the timeline and chronological frames.")
                record=transport.generate([{'role':'user','content':analyzer._build_multi_frame_content(prompt,current)}],32,True)
                assert record['output_tokens']==32
                checkpoint['fixed_output_control'].append({'mode':mode,'repeat':repeat,**dict(record)})
            save(result)
        print(json.dumps({'event':'checkpoint_done','n':len(raw)}),flush=True)
    result['passed']=True
    result['completed_at']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    save(result)
    print('BENCHMARK COMPLETE '+str(OUT),flush=True)

if __name__=='__main__':asyncio.run(main())
