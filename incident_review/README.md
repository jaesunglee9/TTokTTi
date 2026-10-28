# incident_review — 하이라이트 재검토와 근거 있는 사고 보고서 (v2 실험)

현재 파이프라인은 실시간 소형 VLM이 낸 `DANGER: 한 문장`을 그대로 기록하고, 보고서 LLM은 **영상을 보지 않고** 그 문장과 통계만으로 글을 쓴다. 법령 근거 필드는 없다.

v2는 단계를 나눈다.

| 단계 | 담당 | 출력 |
|---|---|---|
| 1. 실시간 탐지 | 소형 VLM (기존) | `DANGER/SAFE` 한 문장 |
| 2. 재검토 | 큰 멀티모달 모델 (`verifier.py`) | 규칙별 `VIOLATED / NOT_VIOLATED / UNCERTAIN` + 근거 프레임 |
| 3. 사실 확정 | 서버 (`verifier.validate`) | 없는 규칙, 없는 프레임, 근거 없는 위반을 거부 |
| 4. 보고서 | 텍스트 LLM (`report_v2.py`) | 문장과 조치만. 위반 목록과 조문은 서버가 카탈로그에서 붙임 |

- 조문은 VLM이 고르지 않는다. `rule_catalog.json`(사람 검수, `verified=false`인 항목은 law.go.kr 확인 전)이 rule_id → 조문을 정한다.
- `backends.py`의 Claude Code, Codex CLI 어댑터는 **오프라인 실험용**이다. 운영은 같은 `complete()`를 유료 API로 구현한다.

## 평가 재현

데이터: [Construction Site Safety](https://universe.roboflow.com/roboflow-universe-projects/construction-site-safety) (CC BY 4.0, Hugging Face `keremberke/construction-safety-object-detection`) 398장 중 PPE 라벨이 있는 194장.

```bash
python incident_review/eval/build_labels.py --data ~/data/ttokti-eval
python incident_review/eval/run_baseline.py --data ~/data/ttokti-eval          # 1단계 재현 (GPU)
python incident_review/eval/run_review.py   --data ~/data/ttokti-eval --backend claude
python incident_review/eval/score.py        --data ~/data/ttokti-eval
```

지표 (모두 1단계 알람이 울린 사고에 대해, 이미지 단위 bootstrap 95% 구간 포함)
- **오탐 감소율**: 1단계가 위반이라고 한 (이미지, 규칙) 중 라벨상 정상인 것을 재검토가 몇 % 걸렀나
- **진짜 위반 유지율**: 1단계가 맞힌 위반을 재검토가 지우지 않고 남긴 비율
- **보고서 사실 오류율**: 보고서가 위반이라고 쓴 항목 중 라벨상 정상인 비율 (legacy vs v2)
- **안전모 조문 근거 정확도**: 실제 안전모 위반 사고 중 보고서가 안전보건규칙 제32조를 맞게 단 비율

## 한계
- 정지 이미지 1장을 하이라이트 구간 하나로 취급한다(실제 바디캠 연속 영상 아님).
- 운영 1단계는 Qwen3-VL-8B AWQ(vLLM)이다. 평가 GPU(8GB, Turing)에서는 같은 프롬프트로 더 작은 Qwen3-VL을 썼다. 모델 id는 결과 행마다 기록된다.
- 공개 데이터 라벨은 여러 프로젝트를 합친 것이라 빠진 주석이 있을 수 있다. 라벨이 없는 규칙은 채점하지 않는다.
- 같은 모델 계열(Claude)이 재검토와 보고서를 모두 맡는다. 교차 확인은 `--backend codex`로 돌릴 수 있다.
