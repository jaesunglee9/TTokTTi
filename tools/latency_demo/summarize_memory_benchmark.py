"""Build the measurement report directly from recorded samples."""
import json,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
r=json.loads((ROOT/'performance-results/memory-video-20261022.json').read_text())
assert r['passed']
def med(c,kind,mode,key):
 return statistics.median(x[key] for x in c[kind] if x['mode']==mode)
rows=[];details=[]
for c in r['checkpoints']:
 n=c['observations'];kind='natural_answers';fixed='fixed_output_control'
 row=[n]
 for k,metric in [(kind,'input_tokens'),(kind,'output_tokens'),(kind,'total_ms'),(fixed,'total_ms'),(fixed,'first_token_ms')]:
  row.append(' / '.join(f"{med(c,k,m,metric):,.1f}" for m in ['raw','compressed']))
 rows.append('| '+' | '.join(map(str,row))+' |')
 details.append(f"### 관찰 {n}개\n\n누적 입력:\n\n```text\n{c['contexts']['raw']}\n```\n\n압축 입력:\n\n```text\n{c['contexts']['compressed']}\n```\n")
final=r['checkpoints'][-1]
compress=sum(c['metrics']['total_ms'] for c in r['compressions'])
observe=sum(o['action_metrics']['total_ms']+o['observation_metrics']['total_ms'] for o in r['observations'])
raw=sum(med(c,'natural_answers','raw','total_ms') for c in r['checkpoints'])
cmp=sum(med(c,'natural_answers','compressed','total_ms') for c in r['checkpoints'])
input_saved=100*(1-med(final,'natural_answers','compressed','input_tokens')/med(final,'natural_answers','raw','input_tokens'))
fixed_saved=100*(1-med(final,'fixed_output_control','compressed','total_ms')/med(final,'fixed_output_control','raw','total_ms'))
natural_saved=100*(1-med(final,'natural_answers','compressed','total_ms')/med(final,'natural_answers','raw','total_ms'))
truncated=sum(c['metrics']['token_limit_reached'] for c in r['compressions'])
source=r['source']
text=f"""# 실제 영상에서 단기·장기 기억 압축 비교

측정 시작: {r['started_at']}. 종료: {r['completed_at']}.

[실험 화면](http://localhost:8892/memory) · [원시 결과 JSON](../performance-results/memory-video-20261022.json) · [벤치마크 코드](../tools/latency_demo/memory_benchmark.py).

## 결과

30개 관찰 시점에서 입력 토큰은 **{input_saved:.1f}% 감소**했다. 자연 답변의 전체 추론 시간 변화는 **{natural_saved:+.1f}% 절감**, 출력 길이를 32토큰으로 고정한 조건은 **{fixed_saved:+.1f}% 절감**이었다. 음수 절감률은 지연 증가를 의미한다.

다음 값은 조건별 3회 중앙값이며, 각 칸은 **누적 / 압축**이다. 시간은 ms이다.

| 관찰 수 | 입력 토큰 | 자연 답변 출력 토큰 | 자연 답변 전체 ms | 32토큰 고정 전체 ms | 고정 조건 첫 토큰 ms |
|---|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

요약 6회 자체에 **{compress/1000:.2f}초**가 들었다. 두 방식이 공유하는 행동·관찰 생성 비용은 **{observe/1000:.2f}초**였다.

각 체크포인트에 질문을 한 번씩 한다고 놓고 반복 중앙값으로 계산하면:

| 비용 | 누적 | 압축 |
|---|---:|---:|
| 공통 행동·관찰 생성 | {observe/1000:.2f}초 | {observe/1000:.2f}초 |
| 질문 4회 | {raw/1000:.2f}초 | {cmp/1000:.2f}초 |
| 주기적 기억 요약 6회 | 0초 | {compress/1000:.2f}초 |
| 합계 | {(observe+raw)/1000:.2f}초 | {(observe+cmp+compress)/1000:.2f}초 |

위 합계는 비용을 비교하기 위한 계산이며 실제 벤치마크 전체 실행 시간과 다르다. 실제 실행은 두 조건·반복 측정·고정 출력 통제·워밍업을 모두 수행한다. 영상 디코딩과 모델 로딩 시간도 위 비용 합계에 포함하지 않는다.

## 실험 방법

- 영상: [{source['title']}]({source['url']}), {source['attribution']}, [CC BY 3.0]({source['license_source']}).
- 원본 SHA256: `{source['sha256']}`, 파일 크기 {source['bytes']:,} bytes.
- 실제 MP4를 PyAV 19.0.2로 디코딩했다. 320×180 프레임을 영상 시각 20~455초에서 15초 간격으로 30장 추출했다.
- 각 관찰 시점에 원래 `detect_action()`으로 최근 표본 프레임 최대 3개의 행동을 얻고, 별도 프레임 설명 프롬프트로 관찰 문장을 생성했다. 두 조건은 이 **동일한 기록**을 공유한다. 관찰을 조건마다 다시 생성하지 않았다.
- 누적 조건: 모든 관찰 문장을 단기 기억에 유지한다.
- 압축 조건: 단기 기억 5개마다 원래 `SafetyAnalyzer.compress_memory()`를 호출하고, 생성된 요약을 장기 기억 문자열 뒤에 붙인 뒤 단기 기억을 비운다. 현재 Worker의 동작을 그대로 재현했다. 장기 기억 전체를 다시 압축하거나 길이를 제한하는 개선은 적용하지 않았다.
- 5·10·20·30개 시점에 원래 `answer_question()`의 프롬프트와 동일한 최근 이미지 3개로 질문했다. 각 조건 3회, 실행 순서를 번갈아 측정했다.
- 질문: “{r['conditions']['question']}”
- 별도로 같은 질문·입력에서 `min_new_tokens=max_new_tokens=32`인 통제 조건을 측정했다. 답변 길이 차이가 지연 차이로 오인되는 것을 줄이기 위한 조건이며 잘린 문장을 품질 평가에 사용하지 않는다.
- 모델은 이전 실험과 같은 Qwen3-VL-2B-Instruct, revision `{r['metadata']['revision']}`, FP16/SDPA, RTX 2070 SUPER이다.
- 기존 SafetyAnalyzer의 OpenAI 형태 호출을 실제 로컬 Transformers 추론에 연결하는 어댑터를 사용했다. 가짜 모델 응답이나 인위적인 추론 지연은 없다. API 전송 경로를 재현한 실험은 아니다.
- 두 조건 모두 greedy decoding을 사용했다. 원본 함수의 temperature=0.1/0.4 대신 샘플링을 꺼서 무작위 출력 차이를 줄였다. 원본 압축의 max_tokens=60과 답변의 max_tokens=150은 유지했다.
- 워밍업 두 건과 모델 로딩은 비교 통계에서 제외했다. GPU 동기화 완료까지 실제 시간을 쟀다.

## 해석 시 주의할 점

1. **입력 축소와 전체 응답 속도는 같은 지표가 아니다.** 첫 토큰 이전의 입력 처리와 이후 토큰 생성은 구분해야 한다. 원시 결과에는 입력 준비, 생성 전체, 첫 토큰, 출력 토큰 수를 각각 저장했다.
2. 요약은 무료가 아니다. 현재 구현처럼 위험 판정 앞에서 동기적으로 요약하면 그 요청에는 요약 비용이 추가된다. 위 비용 합계는 질문 4회라는 이 실험의 빈도에만 해당한다.
3. **요약 {truncated}/6건이 60토큰 상한에 도달했다.** 상한 도달은 완전한 요약을 보장하지 않는다. 입력 감소가 의미 보존을 입증하지 않으며, 일부 기록이 누락되거나 출력이 잘렸는지는 원문과 함께 확인해야 한다.
4. 자연 답변 조건은 출력 길이가 서로 다를 수 있다. 32토큰 고정 결과와 함께 해석해야 한다. 반복 3회이므로 작은 시간 차이는 확정적인 개선으로 일반화하지 않는다.
5. 원본 Worker는 처리 프레임 20개마다 행동 기록을 갱신한다. 이번에는 영상 15초마다 한 관찰을 만드는 통제 실험으로 대체했다. 실제 카메라의 모든 프레임 처리나 wall-clock 실시간 재생이 아니다. 최근 3프레임도 최대 30초에 걸친 표본이다.
6. 산업 안전 영상이 아닌 애니메이션이다. 기억 흐름과 지연 비용을 확인했으며 위험 탐지 정확도나 사실 보존율은 측정하지 않았다. 행동·관찰 텍스트 자체에도 모델 오류가 있을 수 있다.
7. 원래 8B 모델·vLLM, YOLO, RAG, Redis 큐, 네트워크, 브라우저 표시 시간은 이 비교에서 제외했다. `first_token_ms`는 모델 생성 시작 기준이며 첫 토큰의 클라이언트 도착 시간이 아니다.
8. 원래 질문 스트리밍 함수를 재사용하되 로컬 어댑터는 완성된 출력을 수집해서 돌려준다. 따라서 실제 스트리밍 체감 지연에 관한 결론을 내리지 않는다.

## 재현

현재 WSL의 전용 가상환경에서 `av==19.0.2`가 추가로 필요하다. 영상 준비와 실험 실행:

```bash
cd /home/user0/projects/nice-check/TTokTTi
/tmp/ttoktti-runtime/venv/bin/python tools/latency_demo/prepare_memory_video.py
/tmp/ttoktti-runtime/venv/bin/python tools/latency_demo/run_memory_experiment.py
/tmp/ttoktti-runtime/venv/bin/python tools/latency_demo/summarize_memory_benchmark.py
```

실행 관리 스크립트는 `demo-services.json`의 PID가 데모 Worker인지 검사한 뒤 해당 Worker만 잠시 종료한다. 벤치마크 종료 후 성공 여부와 관계없이 데모 Worker를 다시 시작한다. 다른 GPU 작업은 종료하지 않는다. 결과 경로는 현재 날짜 파일로 고정되어 있으므로 재측정 결과를 보존하려면 실행 전 벤치마크의 `OUT` 경로와 보고서 입력 경로를 새 파일로 바꾼다.

영상·추출 프레임은 `/tmp/ttoktti-runtime/memory-benchmark`에 저장한다. 원시 JSON에는 각 관찰과 요약, 질문 입력·출력, 구간별 실제 측정값, 프레임 해시가 포함된다.

## 시점별 기억 원문

{chr(10).join(details)}
"""
(ROOT/'docs/memory-video-benchmark.md').write_text(text.rstrip()+'\n')
print(json.dumps({'input_saved_percent':input_saved,'natural_saved_percent':natural_saved,'fixed_saved_percent':fixed_saved,
 'compression_total_ms':compress,'observation_total_ms':observe,'raw_questions_ms':raw,'compressed_questions_ms':cmp,'summaries_at_cap':truncated},indent=2))
