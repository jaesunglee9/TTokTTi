# 영상 분석 지연 측정

똑띠는 모바일에서 사진 프레임을 주기적으로 캡처하고 로컬 분석 후 일부 프레임을
WebSocket → Gateway → Redis → Worker로 보낸다. 이 계측은 **프레임 처리/결과 수신 지연**이다.
센서 노출부터 디스플레이에 빛이 표시되기까지의 영상 지연(glass-to-glass)을 측정한 값은 아니다.
FPS는 처리 빈도이며 지연 시간과 별개다.

## 켜는 방법

### 모바일 / 바디캠

1. 수정된 Gateway와 Worker를 함께 배포/실행한다. 둘의 REDIS_URL은 같은 Redis를 가리켜야 한다.
2. 개발 빌드의 CameraScreen은 __DEV__일 때 측정을 켠다.
   SafetyStream을 직접 만들 때는 SessionConfig.measureLatency: true로 켤 수 있다.
   gatewayUrl에는 접근 가능한 ws:// 또는 wss:// 주소를 지정할 수 있다.
   미지정 시 기존 Tailscale 주소를 유지하므로 로컬 코드 수정만으로 원격 서버가 갱신되지는 않는다.
3. 촬영을 시작하고 React Native 로그에서 [LATENCY]를 찾는다.
   10초마다 최근 120개 유효 표본의 n/p50/p95/max를 ms 단위로 출력한다.
   카메라 로컬 통계는 CameraScreen 생명주기, 서버 왕복 통계는 SafetyStream 생명주기 기준이다.
4. worker 로그의 LATENCY JSON에는 해당 프레임의 서버 구간별 원시 값이 있다.
   frame_id로 클라이언트가 보낸 프레임과 완료 메시지를 연결한다.

이 프로젝트의 WSL에서는 8888을 Jupyter가 사용한다. Gateway를 로컬에서 별도로 켜려면
사용하지 않는 포트(예: 8891)를 확인하고 사용한다. 기존 서비스를 재시작할 필요는 없다.

```bash
# 필요한 프로젝트 의존성이 설치된 환경에서, 각각 다른 터미널
cd vision_bodycam
REDIS_URL=redis://localhost:6379 uvicorn gateway:app --host 0.0.0.0 --port 8891
REDIS_URL=redis://localhost:6379 python worker.py
```

Worker는 기존 vLLM/RAG 설정과 모델이 필요하다. 이 문서의 명령은 자동 실행하지 않는다.
휴대폰에서 localhost는 휴대폰 자신이므로 gatewayUrl은 PC에 접근 가능한 주소를 사용한다.

### Python 전체 현장 카메라

저장소 루트, 기존 카메라/모델 의존성이 준비된 환경에서:

```bash
TTOKTTI_LATENCY=1 python -m vision_fullcam.main
```

**[LATENCY]** 접두사로 10초마다 JSON이 출력되고 종료 때 마지막 통계를 출력한다.
기본값은 비활성화다. 프레임 읽기, 탐지, 추적/상태/규칙, 이벤트 저장, 화면 제출 구간을 구분한다.

## 지표의 정확한 범위

| 출처 / 지표 | 시작 → 끝 |
| --- | --- |
| camera_local / photo_request_ms | takePhoto 호출 직전 → 사진 반환 |
| camera_local / preprocess_ms | 사진 반환 → JPEG/리사이즈/텐서 전처리 완료 |
| camera_local / local_analysis_ms | 로컬 processFrame 호출 → 결과 반환; 추적·규칙도 포함 |
| camera_local / capture_request_to_local_result_ms | 촬영 요청 → 로컬 분석 결과 반환 |
| bodycam_client / capture_request_to_send_ms | 촬영 요청 → WebSocket send 호출 직전; 로컬 분석·base64·직렬화 포함 |
| bodycam_client / send_to_result_ms | send 호출 직전 → FRAME_RESULT 수신/파싱; 네트워크·큐·추론·반환 포함 |
| bodycam_client / capture_request_to_result_ms | 촬영 요청 → 서버 분석 완료 메시지 수신/파싱 |
| bodycam_worker / gateway_prepare_ms | Gateway receive_text 반환 → 이미지 최적화 완료 |
| bodycam_worker / queue_age_ms | enqueue 직전 Redis TIME → worker 진입 후 Redis TIME |
| bodycam_worker / context_ms | worker 메모리/문맥 준비; 주기적 행동 인식·RAG·메모리 압축 포함 |
| bodycam_worker / danger_check_ms | detect_danger 호출 → 완료; 모델 서비스 왕복 포함, GPU 커널 시간 아님 |
| bodycam_worker / worker_total_ms | worker 계측 시작 → 완료 메시지 생성; Django 보고 완료는 포함하지 않음 |
| fullcam_local / read_ms | VideoCapture.read 요청 → 프레임 반환 |
| fullcam_local / detector_ms | detector.detect 호출 → 반환 |
| fullcam_local / tracking_state_rules_ms | 탐지 완료 → 추적·그리기·상태·규칙 평가 완료 |
| fullcam_local / event_emit_ms | 규칙 평가 완료 → 이벤트 처리/저장/로그 완료 |
| fullcam_local / read_request_to_result_ms | 프레임 읽기 요청 → 규칙 평가 완료 |
| fullcam_local / read_request_to_display_submit_ms | 읽기 요청 → imshow 반환; show_window=true일 때만 |

휴대폰 안의 시간 차이는 performance.now(), Python 프로세스 내부는 time.perf_counter()를 사용한다.
기기 간 Date.now()/time.time() 값을 빼지 않는다. 큐 시간은 양쪽에서 같은 Redis TIME을 사용하므로
Gateway/Worker 호스트 간 시계 오차는 배제한다. Redis 자체의 시스템 시계 변경은 영향을 줄 수 있으며
음수 표본은 제외한다. 큐 값에는 Redis 왕복·직렬화·삽입·worker 진입 오버헤드도 포함된다.
서로 다른 구간의 p95를 더해서 전체 p95로 해석하면 안 된다.

## 누락과 표본 편향

- FRAME_RESULT는 opt-in 프레임에 한해 안전/위험 모두 보낸다. DANGER 알림은 기존대로 전달한다.
  완료 메시지는 알림 UI로 보내지 않는다. 구버전 클라이언트/측정 비활성 연결에는 추가 완료 메시지를 생성하지 않는다.
- sent/completed/failed/timedOut/abandoned/evicted/throttled/offline 및 pending을 함께 출력한다.
  결과가 120초 내에 없으면 timedOut, 연결 종료 시 미완료는 abandoned, 추적 항목 128개 초과 시 evicted다.
  타임아웃이 Redis 큐 삭제, 장애, 느린 추론 중 무엇 때문인지 이 카운터만으로 단정할 수 없다.
- 성공 지연 통계에는 성공 표본만 들어가므로 반드시 실패·미완료 수와 함께 비교한다.
  타임아웃 결과가 뒤늦게 오거나 중복 메시지가 와도 다시 집계하지 않는다.
- 서버 왕복 표본은 로컬 객체 필터를 통과해 실제 전송된 프레임이다. 모든 카메라 프레임의 통계가 아니다.
- 로컬 타이머가 이전 캡처 종료 전에 실행되면 busySkipped를 증가시킨다. 캡처 요청을 겹쳐서 쌓지 않는다.
- 최근 120개 rolling window이며 실행 전체 통계가 아니다. 중첩된 윈도우의 p95를 평균 내지 않는다.
- 계측 로그에는 영상/base64/모델 응답 내용을 추가하지 않는다. 기존 애플리케이션 로그 정책은 별개다.

## 아직 측정하지 않는 것

센서의 실제 촬영 시각, 카메라 내부 버퍼에 머문 시간, 실제 화면 표시/알림 표시,
위험 행동 시작부터 감지까지의 전체 시간은 포함하지 않는다.
현재 1fps 샘플링 대기와 규칙의 지속 시간 조건도 촬영 요청 이전 지연일 수 있다.
진짜 화면 지연이 필요하면 원본 타임코드와 표시 프레임을 연결하거나,
원본과 표시 화면을 동시에 외부 카메라로 촬영해 비교하는 별도 검증이 필요하다.

## 검증

GPU/카메라/실 Redis/DB에 접근하지 않는 격리 테스트:

```bash
# FastAPI, httpx, Pillow가 설치된 Python 환경
python -m unittest discover -s tests/latency -v

# TypeScript 설치 환경 (리포 루트에서)
npx tsc -p frontend/mobile/telemetry-tests/tsconfig.json --outDir /tmp/ttoktti-latency-tests
TTOKTTI_LATENCY_BUILD=/tmp/ttoktti-latency-tests node --test frontend/mobile/telemetry-tests/latency.test.cjs
```

검증 범위: Gateway↔Worker WebSocket 메시지 계약, 정상/위험/실패,
계측 시계 오류 시 분석 계속 진행, 내부 타임스탬프 클라이언트 위조 방지,
단조 시계 기반 계산, 퍼센타일/윈도우 제한, 중복·타임아웃·용량 제한·연결 해제,
의도적인 종료 후 재접속 방지.

이 테스트의 가짜 모델/Redis 시간은 실제 영상 성능 수치가 아니다.
모바일 전체 앱 빌드 및 실기기·실제 GPU 모델의 성능 검증은 별도로 해야 한다.
