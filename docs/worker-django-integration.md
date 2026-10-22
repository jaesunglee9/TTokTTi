# Worker → Django 위험 기록 저장 계약

검증일: 2026-10-22. 기존 `/api/incidents/` 저장 요청의 URL·인증·필수 데이터 불일치를 수정했다.

## 현재 동작

```text
모바일 로그인 JWT (연결 시 갱신, 이후 4분마다 갱신)
  → WebSocket CONFIG(access_token, worksession_id, 선택 risk_type_id/video_path)
  → Gateway: 토큰은 세션 메타데이터에 보관, 작업에는 세션 정보만 복사
  → Worker 위험 판정 → 앱 DANGER 알림
  → POST /api/detect/bodycam/events/ (Authorization: Bearer 사용자 JWT)
  → Django: JWT + 작업 세션 참여 여부 확인
  → VideoLog 저장 (사건 ID 중복 방지)
  → REPORT_RESULT: saved 또는 error
  → 별도 보고서 생성 요청 시 저장된 설명·감지 시각·위험 통계 반영
```

영상 분석·위험 알림과 DB 저장은 별도다. 프레임 분석의 FRAME_RESULT=ok는 저장 성공을 보장하지 않는다. REPORT_RESULT=saved와 videolog_id가 저장 확인이다. 저장 실패는 앱에 별도 경고로 표시한다.

## 요청·응답

기본 Worker 설정:

```bash
DJANGO_API_URL=http://localhost:8000/api/detect/bodycam/events/
```

Docker 등에서 Worker와 Django가 다른 호스트라면 Worker가 실제 접근할 수 있는 Django 주소로 설정한다. 기존 DJANGO_API_KEY/X-Internal-Key 방식은 이 경로에서 사용하지 않는다. JWT 서명키나 refresh token을 Worker에 공유할 필요는 없다.

요청 예시(가상 데이터):

```json
{
  "event_id": "4f328acb-219c-4a61-b037-e2cafdc1e914",
  "worksession_id": 17,
  "description": "DANGER: 안전모 미착용 의심",
  "detected_at": "2026-10-22T10:00:00Z",
  "video_path": null
}
```

- JWT의 사용자로 작업 세션 참여 여부를 확인한다. client_id 문자열을 사용자 인증 근거로 사용하지 않는다.
- event_id는 Worker가 생성하며 재시도마다 같은 값을 보낸다.
- description과 detected_at을 실제 DB에 저장한다.
- risk_type_id를 주면 BODY 유형이어야 한다. 없으면 BODY_VLM_HAZARD라는 일반 유형을 사용한다. 자유 서술문에서 특정 사고 유형을 추측해 지정하지 않는다.
- video_path가 없으면 original_video=NULL로 저장한다. 실제 업로드된 증거 영상이 있다는 뜻으로 가짜 경로를 만들지 않는다.
- 신규 저장은 201, 동일 사건 재전송은 200이다. 같은 ID로 내용·사용자·세션 등이 달라지면 409다.
- 미인증은 401, 해당 작업 참여자가 아니면 403, 잘못된 유형/입력은 400, 없는 세션은 404다.
- 기존 JWT 바디캠 저장 API `/api/detect/bodycam/`는 유지한다.

Worker는 200/201 응답의 ok와 DB id를 검사한다. HTTP 429/5xx 및 네트워크 오류는 최대 3회 시도하며, 그 외 4xx는 재시도하지 않는다. 일시 장애 재시도 간격은 0.2초, 0.4초다. 정상 종료 때 진행 중인 저장 작업을 기다린다.

재시도는 프로세스 메모리 안에서만 유지된다. 강제 종료나 장기 장애에도 전달을 보장하는 영속 outbox는 구현하지 않았다. DB 저장 뒤 알림 연결이 끊기면 앱이 저장 성공 통지를 받지 못할 수도 있다.

## 모바일 연결

실제 AuthContext.userId와 작업 세션으로 연결마다 고유 client_id를 만든다. 기존 고정 `AuthContext_user_id` 문자열을 제거했다. 로그인 refresh token으로 연결 시작 시 access token을 받고 4분 간격으로 갱신한다. REST와 카메라가 동시에 갱신하면 같은 갱신 요청을 공유한다.

토큰은 CONFIG로만 보내며 프레임 payload에 반복해 넣지 않는다. Gateway의 Redis 세션 메타데이터에 access token이 저장되므로 운영에서는 WSS, 보호된 Redis 접근, 만료·비밀정보 관리가 필요하다. 현재 Gateway가 모든 GPU 요청을 JWT로 선검증하도록 바뀐 것은 아니다. DB 저장 API가 JWT와 세션 권한을 검증한다.

Gateway는 프레임을 큐에 넣을 때 작업 세션·위험 유형·영상 경로를 복사한다. 이후 CONFIG 갱신이 이미 큐에 있는 프레임의 세션을 바꾸지 않는다. Worker는 저장 시점의 최신 access token을 사용한다.

## DB와 보고서

마이그레이션 `detect.0003_bodycam_event_ingestion`은 VideoLog에 다음을 추가한다.

- event_id: nullable unique UUID. 기존 로그와 호환.
- description: 위험 설명.
- detected_at: 실제 감지 시각.
- reported_by: JWT 사용자 FK.

보고서 입력 패키지의 사건·하이라이트 증거에 description을 포함하고, 감지 시각이 있으면 created_at 대신 감지 시각으로 정렬·집계한다. 기존 로그는 created_at을 사용한다. 보고서 생성은 여전히 별도 `POST /api/report/generate`이며 위험 이벤트마다 자동 생성하지 않는다.

## 배포·실행 적용

```bash
# 운영과 같은 Django 설정/환경변수에서 먼저 스키마 반영
cd backend
python manage.py migrate
```

그 후 새 Django, Gateway, Worker 및 모바일 빌드를 적용한다. 원격 git push만으로 실행 중인 서버나 앱이 자동 갱신됐다고 가정하면 안 된다. 기존 OPENAI_API_KEY와 원본 영상 모델 환경은 별도로 필요하다. 이 작업은 운영 DB에 마이그레이션하거나 원격 배포를 실행하지 않았다.

## 검증 결과

- Python 계측·판정·HTTP 저장 계약 10개 통과.
- 실제 Django 모델·뷰·JWT·세션 권한·임시 SQLite 검증 8개 통과.
- TypeScript strict 컴파일 및 계측/연결/토큰 갱신 테스트 5개 통과.
- 실제 프로젝트 마이그레이션을 새 SQLite DB에 적용했고, detect 모델에 누락된 마이그레이션이 없음을 확인했다.
- 실제 Worker 저장 함수의 HTTP 요청을 실제 Django 뷰에 연결했다. DB 저장 후 응답을 잃는 상황을 재현했을 때 재시도는 같은 event_id로 수행되고 DB는 1건이었다. 이후 실제 보고서 집계·저장에 그 사건이 포함됐다.
- HTTP 전송은 테스트 transport, DB는 임시 SQLite, 위험 판정과 보고서 LLM은 대체했다. 이 검증은 원본 모델·Android·실 네트워크·운영 MySQL까지 포함한 현장 종단 간 실측이 아니다.

재현:

```bash
python -m unittest discover -s tests/latency -v
python tests/report_pipeline/run.py
npx tsc -p frontend/mobile/telemetry-tests/tsconfig.json --outDir /tmp/ttoktti-latency-tests
TTOKTTI_LATENCY_BUILD=/tmp/ttoktti-latency-tests node --test frontend/mobile/telemetry-tests/*.test.cjs
```

보고서 테스트는 기본적으로 기존 측정 산출물을 덮어쓰지 않는다. 가상 보고서 예시를 새로 저장하려는 경우에만 `TTOKTTI_WRITE_REPORT_FIXTURE=1`을 설정한다.
