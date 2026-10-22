# 브라우저 대체 데모와 영상 분석 지연 실측

측정일: 2026-10-22 19:13–19:14 KST. 원본 결과: [browser-demo-20261022.json](../performance-results/browser-demo-20261022.json).

현재 PC에서 [http://localhost:8892](http://localhost:8892)를 열면 사용할 수 있다. WSL과 데모 프로세스가 실행 중이어야 한다. 예제 이미지로 **한 번 분석** 또는 **10회 반복 측정**을 누르고, **결과 JSON 저장**으로 원시 표본을 내려받는다. 개인 이미지·영상도 선택할 수 있다. 영상은 재생 후 원하는 위치에서 멈추고 분석하면 해당 프레임을 보낸다. 웹캠은 사용 버튼을 눌러 권한을 허용한 경우에만 열린다.

## 무엇을 실제로 연결했나

```text
Windows Chrome
  → JPEG 프레임 + frame_id / WebSocket
  → 기존 vision_bodycam Gateway (WSL, 데모 포트 8892)
  → 전용 Redis (127.0.0.1:6391)
  → 데모 Worker 1개 / 실제 GPU 모델 추론
  → Redis Pub/Sub → Gateway → 브라우저 결과 및 구간별 통계
```

모의 응답이나 인위적인 sleep으로 추론 시간을 만들지 않았다. 공개 [Qwen/Qwen3-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct)를 실제 GPU에서 실행했다. 기존 모바일 앱의 계측은 유지하며, 원본 모델·휴대폰이 없는 상황에서 브라우저와 별도 Worker를 추가했다.

- GPU: NVIDIA GeForce RTX 2070 SUPER, 8 GB.
- 모델 revision: `89644892e4d85e24eaac8bacfd4f463576704203`.
- FP16, SDPA, greedy decoding, 최대 생성 토큰 64.
- Python 3.12.14, PyTorch 2.14.0+cu130, Transformers 4.57.6.
- 프레임의 긴 변 최대 448px, 브라우저 JPEG quality 0.8.
- 샘플: 공식 모델 예제의 [여성과 개가 있는 해변 사진](https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen-VL/assets/demo.jpeg).
- 원본 이미지 SHA256: `9eeaa87013b4e800930e8a411b58ff9e2fd5383906b1a022f4a712720af34cc2`.
- 한국어 응답을 프롬프트로 요청했지만 이번 표본의 실제 출력은 영어였다. UI와 JSON에는 원문을 그대로 보존했다.

## 측정 조건과 결과

실제 Chrome headless에서 서로 분리된 브라우저 컨텍스트를 사용했다. 1개 클라이언트는 10회, 3개 클라이언트는 각각 5회씩 총 15회 요청했다. 각 클라이언트는 이전 응답을 받은 다음에 요청하는 closed-loop 방식으로, 동시에 미완료 요청을 하나만 유지한다. 워밍업 1회는 별도 기록하고 아래 통계에서 제외했다. 측정 25회는 모두 성공했고 브라우저 JavaScript 오류는 없었다.

단위는 ms이며 각 칸은 **p50 / p95**이다.

| 구간 | 1개 클라이언트, n=10 | 3개 클라이언트, n=15 |
|---|---:|---:|
| 요청 시작 → 결과 수신 | 2037.3 / 2506.4 | 5775.2 / 6072.5 |
| 브라우저 이미지 준비 | 3.1 / 18.8 | 3.8 / 50.7 |
| 전송 → 결과 수신 | 2034.2 / 2503.3 | 5771.7 / 6021.8 |
| Gateway 이미지 처리 | 0.427 / 0.691 | 0.452 / 0.955 |
| Redis 큐 대기 포함 | 0.791 / 1.208 | 3748.436 / 4232.596 |
| 모델 입력 준비·GPU 전송 | 10.245 / 21.452 | 14.966 / 22.389 |
| 모델 생성 전체 | 2012.687 / 2479.036 | 2010.648 / 2162.371 |
| ↳ 첫 토큰까지 | 73.120 / 85.597 | 73.860 / 95.058 |
| ↳ 첫 토큰 이후 생성 | 1940.663 / 2398.370 | 1936.788 / 2086.002 |
| Worker 전체 | 2030.478 / 2500.218 | 2027.064 / 2184.157 |
| 결과 수신 → 화면 갱신 기회 | 7.6 / 16.0 | 8.0 / 12.0 |
| 요청 시작 → 화면 갱신 기회 | 2040.0 / 2512.2 | 5776.7 / 6082.4 |

모델 로딩은 **42.10초**, 로딩 이후 첫 요청은 **7.83초**였다. 첫 요청의 모델 생성은 7.37초, 그중 첫 토큰까지 5.23초였다. 서비스 시작 시간과 워밍업 이후 응답 시간을 구분해야 한다.

p50/p95는 nearest-rank 방식이다. 표본이 적어 두 조건 모두 p95가 최댓값과 같으며, 안정적인 운영 SLO를 추정하기 위한 실험은 아니다. 각 행의 백분위수는 서로 다른 요청에서 나올 수 있으므로 행끼리 더하거나 빼서 전체 지연을 계산하면 안 된다.

## 어디에서 오래 걸렸나

단일 클라이언트에서는 모델 생성이 약 2.01초로 가장 컸다. 요청별 생성 시간 / 전체 시간을 계산한 비율의 중앙값은 **99.0%**였다. 첫 토큰은 약 73ms 만에 나왔지만, 나머지 토큰을 순차 생성하는 데 약 1.94초가 들었다. 현재 프로토콜은 답변을 완성한 뒤 전송하므로 첫 토큰 시간이 사용자에게 보이는 응답 시간은 아니다.

3개 클라이언트에서는 Worker가 요청을 한 번에 하나씩 처리하면서 큐 대기 중앙값이 **3.75초**까지 늘었다. 요청별 큐 대기 / 전체 시간 비율의 중앙값은 **64.4%**였다. 모델 생성 자체는 계속 약 2초였다. 이번 조건의 동시 요청 지연은 주로 직렬 처리 대기에서 발생했다.

이 결과를 바탕으로 검토할 개선은 출력 길이 축소, 토큰 스트리밍, GPU 메모리 한도 안에서의 추론 배칭, 영상의 오래된 프레임을 버리고 최신 프레임을 우선하는 정책이다. 이번 작업에서는 측정과 원인 확인까지만 수행했으며, 이 개선을 적용했거나 효과를 검증했다고 주장하지 않는다.

## 계측의 의미와 한계

- 브라우저 내부 구간은 `performance.now()`, Python 내부는 `time.perf_counter()`를 사용한다. 서로 다른 호스트의 로컬 시각을 직접 빼지 않는다.
- 큐 지연은 동일 Redis의 TIME을 Gateway와 Worker가 읽어 계산한다. enqueue 직전부터 dequeue 후 측정까지이므로 Redis 명령 왕복·스케줄링 일부를 포함한다.
- GPU 생성 구간은 CUDA synchronize로 완료를 기다린 뒤 측정한다. 첫 토큰 계측에도 동기화가 있어 계측 비용이 포함된다.
- 화면 값은 DOM 갱신 이후 두 번의 requestAnimationFrame 기회까지다. 디스플레이에 실제로 빛이 나온 시점이나 카메라 센서 노출 시점을 측정하지 않는다. 숨겨진 탭 등에서 갱신 기회를 관측하지 못하면 값을 기록하지 않는다.
- 이미지·영상 파일 디코딩 중 요청하면 준비 시간에 포함될 수 있다. 영상은 현재 프레임이며 영상 재생 지연, 영상 전체 처리량 또는 물리적인 camera-to-display latency가 아니다.
- localhost를 통한 Windows↔WSL 환경이다. 휴대폰·Wi-Fi·모바일 네트워크 지연을 대표하지 않는다.
- 원래 앱의 YOLO 전처리, 원래 Qwen3-VL-8B AWQ/vLLM, 최근 3프레임, 행동 분석·RAG·기억 경로는 이번 데모에서 실행하지 않았다.
- 산업 현장 데이터셋으로 위험 탐지 정확도를 평가하지 않았다. 이 데모 Worker는 Django에 위험 사건이나 리포트를 생성하지 않는다.
- 같은 사진의 짧은 실험이다. 장시간 부하, 더 많은 사용자, 열린 도착률, 메모리 포화, 큐 초과 드롭은 검증하지 않았다. 출력 길이도 43–53 토큰으로 달랐다.
- UI는 성공한 최근 120개 비워밍업 표본의 통계를 표시한다. 실패와 원시 표본은 JSON에 별도로 기록한다. 첫 성공 추론 및 벤치마크가 지정한 워밍업은 통계에서 제외한다.
- 다운로드 JSON에는 모델이 생성한 텍스트가 들어간다. 서버 성능 JSONL에는 이미지와 생성 텍스트를 쓰지 않는다.

## 코드 위치

| 파일 | 역할 |
|---|---|
| [server.py](../tools/latency_demo/server.py) | 기존 Gateway에 UI·모델 상태·예제 이미지 경로 추가 |
| [model_worker.py](../tools/latency_demo/model_worker.py) | 실제 모델, 첫 토큰·생성·입력 준비 시간, Redis 응답 |
| [app.js](../tools/latency_demo/app.js) | 프레임 전송, 응답 연결, 브라우저 구간 측정, 통계·JSON |
| [benchmark.mjs](../tools/latency_demo/benchmark.mjs) | 실제 Chrome 1개/3개 클라이언트 부하 측정 |
| [ui-smoke.mjs](../tools/latency_demo/ui-smoke.mjs) | 이미지·영상 업로드, 실제 분석, JSON 내용·초기화 검증 |
| [video-latency.md](video-latency.md) | 기존 모바일·서버 계측의 상세 설명 |

## 현재 WSL 환경에서 다시 실행

현재는 Redis 6391과 데모 8892가 실행 중이다. 이미 동작 중이면 아래 명령으로 중복 실행하지 않는다. 프로세스 자동 시작 서비스는 설치하지 않았으며 WSL 종료 시 데모도 종료될 수 있다. 런타임과 예제 이미지가 `/tmp`에 있어 삭제될 경우 다시 준비해야 한다.

다음은 이번에 준비한 런타임이 남아 있을 때 각 WSL 터미널에서 실행하는 명령이다.

터미널 1 — 전용 Redis:

```bash
LD_LIBRARY_PATH=/tmp/ttoktti-runtime/redis/usr/lib/x86_64-linux-gnu \
  /tmp/ttoktti-runtime/redis/usr/bin/redis-server \
  --bind 127.0.0.1 --port 6391 --save '' --appendonly no
```

터미널 2 — 모델 Worker:

```bash
cd /home/user0/projects/nice-check/TTokTTi
REDIS_URL=redis://127.0.0.1:6391/0 \
  /tmp/ttoktti-runtime/venv/bin/python tools/latency_demo/model_worker.py
```

터미널 3 — Gateway 및 화면:

```bash
cd /home/user0/projects/nice-check/TTokTTi
REDIS_URL=redis://127.0.0.1:6391/0 \
  /tmp/ttoktti-runtime/venv/bin/python -m uvicorn tools.latency_demo.server:app \
  --host 127.0.0.1 --port 8892
```

모델 준비 후 [데모](http://localhost:8892)를 새로고침한다. 예제 이미지가 없으면 직접 이미지를 선택하거나 다음 명령으로 다시 준비한다.

```bash
mkdir -p /tmp/ttoktti-runtime
curl -L --fail 'https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen-VL/assets/demo.jpeg' \
  -o /tmp/ttoktti-runtime/sample.jpg
```

다른 환경에서는 별도 Python 3.12 가상환경에 CUDA 지원 PyTorch와 torchvision을 준비한 뒤 [requirements.txt](../tools/latency_demo/requirements.txt)를 설치하고, Redis를 위 전용 포트로 띄운다. 기존 Jupyter 환경은 변경하지 않았다. 이번 가상환경은 기존 PyTorch 패키지 경로를 읽기만 하도록 연결했기 때문에 그 경로가 사라지면 독립 설치가 필요하다. Hugging Face 첫 실행은 모델 다운로드와 약 4GB 이상의 모델 캐시 저장 공간이 필요하다.

벤치마크 스크립트는 Node.js에서 실행하며, `PSWP_PLAYWRIGHT_MODULE`에 Playwright 모듈의 절대 경로, `PSWP_CHROME`에 Chrome 실행 파일의 절대 경로, `TTOKTTI_RESULTS`에 결과 JSON 경로를 지정한다. `PSWP_SCREENSHOT`은 화면 캡처 경로다. 실제 사용 예와 기본값은 스크립트 상단을 참고한다. 이번 결과를 덮어쓰지 않도록 새 출력 경로를 사용한다.

## 검증

실제 모델 벤치마크 25회 + 워밍업 1회 성공. UI 검증에서는 파일로 올린 이미지와 생성한 WebM 영상의 현재 프레임을 각각 실제 추론했고, JSON 다운로드 내용과 통계 초기화를 확인했다. 기존 Python 지연 계측 테스트 8개도 통과했다. Android 실기기 실행 검증은 수행하지 못했다.
