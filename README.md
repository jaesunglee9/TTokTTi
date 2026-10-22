# TTokTTi
** README will be updated soon

![4팀_수정](https://github.com/user-attachments/assets/500f32d5-aacc-4f0e-b477-37287aabf0ba)

## Manual Video
https://drive.google.com/file/d/1zjroz1Cni2MDa6PSe0AQ4Y9y739frgUG/view?usp=sharing

## Now working (`2/21` 12:50)
- images: `riskpulse_db`, `riskpulse_redis`, `riskpulse_be`, `riskpulse_fe_web`
```bash
cd RiskPulse # at project root, 
docker compose up -d
```
- After running docker compose up, check Docker Desktop
- Make sure the backend container is running
- In some cases, the backend and fe-web container does not start automatically
→ If so, start it manually using the Run button in Docker Desktop
```bash
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser
# then, enter your information for temporal login
```
- You can enter web by `http://localhost:3000/`
- If you ran container detached, view logs with
```bash
docker logs -f riskpulse-backend # same for other images
```

## Full Reset (Including DB Volume)
- This will remove all data, including the database volume. Use this when you’ve changed .env or need a full clean slate.
```bash
docker compose down -v
docker compose up --build
```

## Start App (Android Studio)
1. Open `/frontend/mobile/android` project at Android Studio
2. fix `local.properties` with your Android SDK path
3. (First Time Only) Install Dependencies and Generate Keystore
```bash
# at /frontend/mobile
npm install
cd android/app
keytool -genkeypair \
  -alias androiddebugkey \
  -keyalg RSA \
  -keysize 2048 \
  -validity 10000 \
  -keystore debug.keystore \
  -storepass android \
  -keypass android \
  -dname "CN=Android Debug,O=Android,C=US"
```
4. (Terminal 1) Run Metro Server
```bash
# at frontend/mobile/android
npm start
```
5. Add Android Device
- Start an Android Emulator from Android Studio or Connect a physical Android device with USB debugging enabled
6. (Terminal 2) Build and Run the App
```bash
# at frontend/mobile/android
npm run android
```
---


## DB seeding
currently code is seeded at backend/apps/users/management/seed_db.py

```bash
docker compose down -v 
docker compose up -d --build
docker exec -it riskpulse_be python manage.py makemigrations
```

```bash
# Password is 'rootpassword' as defined in your docker-compose.yml
docker exec -it riskpulse_db mysql -u root -p
```
id:admin
pw:adminpassword

## todos
TODO 1 : nvidia-container-toolkit installed on your Linux host for this to work. (worker)

## 영상 분석 지연 측정

모바일 개발 빌드와 바디캠 Gateway/Worker에 프레임 추적 및 구간별 지연 측정을 추가했다.
최근 120개 표본의 p50/p95/max와 실패·미완료 수를 로그로 확인할 수 있다.
Python 전체 현장 카메라는 TTOKTTI_LATENCY=1로 활성화한다.
측정 범위, 실행 방법, 한계 및 테스트는 [영상 지연 측정 문서](docs/video-latency.md)를 참고한다.

## PC 브라우저 대체 데모

원본 모바일 환경 없이 공개 2B 모델을 실제 GPU에서 실행하는 데모를 추가했다.
실행 중인 PC에서는 http://localhost:8892 에 접속한다.
1개·3개 클라이언트의 실제 측정 결과와 재실행 방법은 [브라우저 지연 실측 보고서](docs/browser-latency-demo.md)를 참고한다.
이 결과는 원래 모바일 앱·8B 모델의 성능이나 위험 탐지 정확도를 나타내지 않는다.

실제 영상의 단기·장기 기억 비교는 [기억 압축 실측 보고서](docs/memory-video-benchmark.md)와 [실험 화면](http://localhost:8892/memory)에서 확인할 수 있다.

## 테스트 파이프라인과 위험 리포트

[테스트·위험 리포트 검증 보고서](docs/test-pipeline-report.md)에 현재 처리 흐름, 실제 측정 결과, 격리 DB 테스트와 미완료 연결을 정리했다.
위험 알림과 종합 보고서 생성은 별도 단계이며, Worker의 기본 저장 요청과 Django API 계약에는 아직 불일치가 있다.
