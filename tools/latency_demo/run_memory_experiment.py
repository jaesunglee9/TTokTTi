import json,os,signal,subprocess,time
from pathlib import Path
ROOT=Path('/home/user0/projects/nice-check/TTokTTi')
runtime=Path('/tmp/ttoktti-runtime')
meta=json.loads((runtime/'demo-services.json').read_text())
pid=meta['worker_pid']
command=Path(f'/proc/{pid}/cmdline').read_bytes()
assert b'tools/latency_demo/model_worker.py' in command,command
os.kill(pid,signal.SIGTERM)
for _ in range(100):
 if not Path(f'/proc/{pid}').exists():break
 try:
  if Path(f'/proc/{pid}/stat').read_text().split()[2]=='Z':break
 except FileNotFoundError:break
 time.sleep(.1)
env=os.environ.copy();env['REDIS_URL']='redis://127.0.0.1:6391/0'
try:
 with (runtime/'memory-benchmark.log').open('w') as log:
  result=subprocess.run([str(runtime/'venv/bin/python'),'tools/latency_demo/memory_benchmark.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
 print('benchmark_exit',result.returncode,flush=True)
finally:
 with (runtime/'demo-worker.log').open('a') as log:
  proc=subprocess.Popen([str(runtime/'venv/bin/python'),'tools/latency_demo/model_worker.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 meta['worker_pid']=proc.pid
 (runtime/'demo-services.json').write_text(json.dumps(meta,indent=2))
 print('restored_worker_pid',proc.pid,flush=True)
