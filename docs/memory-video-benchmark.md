# 실제 영상에서 단기·장기 기억 압축 비교

측정 시작: 2026-10-22T10:33:43Z. 종료: 2026-10-22T10:36:58Z.

[실험 화면](http://localhost:8892/memory) · [원시 결과 JSON](../performance-results/memory-video-20261022.json) · [벤치마크 코드](../tools/latency_demo/memory_benchmark.py).

## 결과

30개 관찰 시점에서 입력 토큰은 **63.6% 감소**했다. 자연 답변의 전체 추론 시간 변화는 **+20.1% 절감**, 출력 길이를 32토큰으로 고정한 조건은 **+10.2% 절감**이었다. 음수 절감률은 지연 증가를 의미한다.

다음 값은 조건별 3회 중앙값이며, 각 칸은 **누적 / 압축**이다. 시간은 ms이다.

| 관찰 수 | 입력 토큰 | 자연 답변 출력 토큰 | 자연 답변 전체 ms | 32토큰 고정 전체 ms | 고정 조건 첫 토큰 ms |
|---|---:|---:|---:|---:|---:|
| 5 | 521.0 / 358.0 | 90.0 / 48.0 | 3,539.6 / 1,872.1 | 1,329.8 / 1,328.0 | 125.0 / 103.4 |
| 10 | 734.0 / 394.0 | 116.0 / 70.0 | 4,767.9 / 2,873.4 | 1,341.5 / 1,318.0 | 144.3 / 111.0 |
| 20 | 1,181.0 / 481.0 | 110.0 / 79.0 | 4,344.6 / 3,125.6 | 1,355.9 / 1,276.7 | 196.3 / 113.1 |
| 30 | 1,614.0 / 588.0 | 100.0 / 85.0 | 4,126.4 / 3,295.7 | 1,446.4 / 1,298.6 | 254.9 / 123.9 |

요약 6회 자체에 **11.25초**가 들었다. 두 방식이 공유하는 행동·관찰 생성 비용은 **60.10초**였다.

각 체크포인트에 질문을 한 번씩 한다고 놓고 반복 중앙값으로 계산하면:

| 비용 | 누적 | 압축 |
|---|---:|---:|
| 공통 행동·관찰 생성 | 60.10초 | 60.10초 |
| 질문 4회 | 16.78초 | 11.17초 |
| 주기적 기억 요약 6회 | 0초 | 11.25초 |
| 합계 | 76.88초 | 82.51초 |

위 합계는 비용을 비교하기 위한 계산이며 실제 벤치마크 전체 실행 시간과 다르다. 실제 실행은 두 조건·반복 측정·고정 출력 통제·워밍업을 모두 수행한다. 영상 디코딩과 모델 로딩 시간도 위 비용 합계에 포함하지 않는다.

## 실험 방법

- 영상: [Big Buck Bunny](https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4.zip), (c) 2008 Blender Foundation / www.bigbuckbunny.org, [CC BY 3.0](https://peach.blender.org/about/).
- 원본 SHA256: `f78f39603e6774907f2faafabf26a667f4a6fc31769ec304a8a8f7c62d280508`, 파일 크기 64,657,027 bytes.
- 실제 MP4를 PyAV 19.0.2로 디코딩했다. 320×180 프레임을 영상 시각 20~455초에서 15초 간격으로 30장 추출했다.
- 각 관찰 시점에 원래 `detect_action()`으로 최근 표본 프레임 최대 3개의 행동을 얻고, 별도 프레임 설명 프롬프트로 관찰 문장을 생성했다. 두 조건은 이 **동일한 기록**을 공유한다. 관찰을 조건마다 다시 생성하지 않았다.
- 누적 조건: 모든 관찰 문장을 단기 기억에 유지한다.
- 압축 조건: 단기 기억 5개마다 원래 `SafetyAnalyzer.compress_memory()`를 호출하고, 생성된 요약을 장기 기억 문자열 뒤에 붙인 뒤 단기 기억을 비운다. 현재 Worker의 동작을 그대로 재현했다. 장기 기억 전체를 다시 압축하거나 길이를 제한하는 개선은 적용하지 않았다.
- 5·10·20·30개 시점에 원래 `answer_question()`의 프롬프트와 동일한 최근 이미지 3개로 질문했다. 각 조건 3회, 실행 순서를 번갈아 측정했다.
- 질문: “In exactly two short sentences, summarize the earlier events in chronological order and describe what is happening now. Mention only events supported by the observations.”
- 별도로 같은 질문·입력에서 `min_new_tokens=max_new_tokens=32`인 통제 조건을 측정했다. 답변 길이 차이가 지연 차이로 오인되는 것을 줄이기 위한 조건이며 잘린 문장을 품질 평가에 사용하지 않는다.
- 모델은 이전 실험과 같은 Qwen3-VL-2B-Instruct, revision `89644892e4d85e24eaac8bacfd4f463576704203`, FP16/SDPA, RTX 2070 SUPER이다.
- 기존 SafetyAnalyzer의 OpenAI 형태 호출을 실제 로컬 Transformers 추론에 연결하는 어댑터를 사용했다. 가짜 모델 응답이나 인위적인 추론 지연은 없다. API 전송 경로를 재현한 실험은 아니다.
- 두 조건 모두 greedy decoding을 사용했다. 원본 함수의 temperature=0.1/0.4 대신 샘플링을 꺼서 무작위 출력 차이를 줄였다. 원본 압축의 max_tokens=60과 답변의 max_tokens=150은 유지했다.
- 워밍업 두 건과 모델 로딩은 비교 통계에서 제외했다. GPU 동기화 완료까지 실제 시간을 쟀다.

## 해석 시 주의할 점

1. **입력 축소와 전체 응답 속도는 같은 지표가 아니다.** 첫 토큰 이전의 입력 처리와 이후 토큰 생성은 구분해야 한다. 원시 결과에는 입력 준비, 생성 전체, 첫 토큰, 출력 토큰 수를 각각 저장했다.
2. 요약은 무료가 아니다. 현재 구현처럼 위험 판정 앞에서 동기적으로 요약하면 그 요청에는 요약 비용이 추가된다. 위 비용 합계는 질문 4회라는 이 실험의 빈도에만 해당한다.
3. **요약 2/6건이 60토큰 상한에 도달했다.** 상한 도달은 완전한 요약을 보장하지 않는다. 입력 감소가 의미 보존을 입증하지 않으며, 일부 기록이 누락되거나 출력이 잘렸는지는 원문과 함께 확인해야 한다.
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

### 관찰 5개

누적 입력:

```text
Long-term memory context: No prior context. | Recent observations: A cartoon bird with grey feathers, a yellow beak, and orange feet is perched on a tree branch. The bird is opening its beak wide as if singing or calling out. | A large, dark, furry creature is curled up inside a cozy, grassy den with rocks. The creature is resting, and the den is surrounded by vibrant green grass and smooth stones. | A large, grey, furry creature with a long snout and small ears is sitting on a grassy hill, holding onto a rock with its front paws. The creature is looking up at the sky, which is a soft, pale color. | A large, white, cartoonish character with a round body and a small head is standing on a grassy hill. The character is facing the viewer and appears to be in a relaxed, standing pose. | A large, white, fluffy rabbit stands in a grassy field, looking up at a small pink butterfly that is flying above it. The rabbit has its arms slightly raised and is standing still, while a small red butterfly is visible on the grass to the left.
```

압축 입력:

```text
Long-term memory context: The worker observes a series of animated and real creatures in a natural setting: a cartoon bird singing on a tree, a furry creature resting in a den, another creature on a hill, a white character standing, and finally a rabbit with a butterfly above it, all within a grassy, natural environment | Recent observations: No recent context available.
```

### 관찰 10개

누적 입력:

```text
Long-term memory context: No prior context. | Recent observations: A cartoon bird with grey feathers, a yellow beak, and orange feet is perched on a tree branch. The bird is opening its beak wide as if singing or calling out. | A large, dark, furry creature is curled up inside a cozy, grassy den with rocks. The creature is resting, and the den is surrounded by vibrant green grass and smooth stones. | A large, grey, furry creature with a long snout and small ears is sitting on a grassy hill, holding onto a rock with its front paws. The creature is looking up at the sky, which is a soft, pale color. | A large, white, cartoonish character with a round body and a small head is standing on a grassy hill. The character is facing the viewer and appears to be in a relaxed, standing pose. | A large, white, fluffy rabbit stands in a grassy field, looking up at a small pink butterfly that is flying above it. The rabbit has its arms slightly raised and is standing still, while a small red butterfly is visible on the grass to the left. | A large, white, fluffy rabbit stands in a grassy field, holding a red carrot in its right hand and eating it with its left paw. The rabbit is positioned in the foreground, with a backdrop of green trees, a blue sky, and distant mountains. | A large, white rabbit with long ears stands in a grassy field, looking up with a surprised expression. A purple butterfly flies in the air to the left of the rabbit. | A small, brown squirrel with large, round eyes peeks out from behind a large, gray rock. The squirrel is looking directly at the viewer with a curious expression. | A large, white rabbit with a worried expression stands in the foreground, looking up at a small brown squirrel perched on a tree trunk. A purple butterfly is flying in the air to the left of the rabbit. | A squirrel with a bushy tail is perched on a large tree trunk, looking down at the ground. A small, dark-furred mouse is sitting on the grass nearby, looking up at the squirrel.
```

압축 입력:

```text
Long-term memory context: The worker observes a series of animated and real creatures in a natural setting: a cartoon bird singing on a tree, a furry creature resting in a den, another creature on a hill, a white character standing, and finally a rabbit with a butterfly above it, all within a grassy, natural environment The worker observes a white rabbit harvesting flowers, eating a carrot, and later encounters a squirrel and butterfly in a grassy field, before climbing a tree to observe a mouse below. | Recent observations: No recent context available.
```

### 관찰 20개

누적 입력:

```text
Long-term memory context: No prior context. | Recent observations: A cartoon bird with grey feathers, a yellow beak, and orange feet is perched on a tree branch. The bird is opening its beak wide as if singing or calling out. | A large, dark, furry creature is curled up inside a cozy, grassy den with rocks. The creature is resting, and the den is surrounded by vibrant green grass and smooth stones. | A large, grey, furry creature with a long snout and small ears is sitting on a grassy hill, holding onto a rock with its front paws. The creature is looking up at the sky, which is a soft, pale color. | A large, white, cartoonish character with a round body and a small head is standing on a grassy hill. The character is facing the viewer and appears to be in a relaxed, standing pose. | A large, white, fluffy rabbit stands in a grassy field, looking up at a small pink butterfly that is flying above it. The rabbit has its arms slightly raised and is standing still, while a small red butterfly is visible on the grass to the left. | A large, white, fluffy rabbit stands in a grassy field, holding a red carrot in its right hand and eating it with its left paw. The rabbit is positioned in the foreground, with a backdrop of green trees, a blue sky, and distant mountains. | A large, white rabbit with long ears stands in a grassy field, looking up with a surprised expression. A purple butterfly flies in the air to the left of the rabbit. | A small, brown squirrel with large, round eyes peeks out from behind a large, gray rock. The squirrel is looking directly at the viewer with a curious expression. | A large, white rabbit with a worried expression stands in the foreground, looking up at a small brown squirrel perched on a tree trunk. A purple butterfly is flying in the air to the left of the rabbit. | A squirrel with a bushy tail is perched on a large tree trunk, looking down at the ground. A small, dark-furred mouse is sitting on the grass nearby, looking up at the squirrel. | A white rabbit with long ears is shown from the back, standing in a grassy field. The rabbit is facing away from the viewer, with a bright, sunny sky and distant hills in the background. | A red, fox-like character with a long tail is peeking out from behind a large tree trunk. A gray, mouse-like character is sitting on the grass, looking up at the fox. | A small, dark-furred animal with a red nose is lying on the grass near a large tree trunk. A brown, furry creature with a large head is standing in the foreground, facing the animal. | A brown squirrel with large, expressive eyes is looking up at a large tree. A small, dark-colored animal with a round face is peeking out from behind the tree trunk. | A small, dark-furred squirrel is sitting on the grass near a large tree trunk, holding a red object in its paws. A red fox with a bushy tail is standing on the grass, looking at the squirrel. A brown squirrel is on the grass to the right, looking at the fox. | A large, grey, cartoon rabbit with a round body and a prominent snout stands in a lush, green forest. The rabbit is holding a small red object in its right paw and is looking slightly to its left. | A white, furry creature with a long snout and a small tail is standing in a forest, holding a large, thick tree trunk with both front paws. The creature is looking up at the tree trunk, which is leaning against a tree. | A large, white, round rabbit with long ears stands in a forest, holding a green plant in its front paws. The rabbit is looking forward with a calm expression. | A small, gray, furry creature with a long snout is peeking out from behind a large tree trunk in a grassy field. The creature is looking towards the left side of the frame, where a single, green tree stands in the distance. | A small, red, bird-like creature with a long tail is flying over a vibrant green field. In the background, a large, green, leafy tree stands tall among other trees.
```

압축 입력:

```text
Long-term memory context: The worker observes a series of animated and real creatures in a natural setting: a cartoon bird singing on a tree, a furry creature resting in a den, another creature on a hill, a white character standing, and finally a rabbit with a butterfly above it, all within a grassy, natural environment The worker observes a white rabbit harvesting flowers, eating a carrot, and later encounters a squirrel and butterfly in a grassy field, before climbing a tree to observe a mouse below. The worker repeatedly digs in a grassy field, observing a white rabbit, a red fox, and various squirrels, while climbing a tree and interacting with them in a sunny, natural setting. The worker repeatedly digs and lifts logs in a lush forest, observing various animals including a cartoon rabbit, a white furry creature, a large white rabbit, and a small gray creature, while a red bird-like creature flies over a green field. | Recent observations: No recent context available.
```

### 관찰 30개

누적 입력:

```text
Long-term memory context: No prior context. | Recent observations: A cartoon bird with grey feathers, a yellow beak, and orange feet is perched on a tree branch. The bird is opening its beak wide as if singing or calling out. | A large, dark, furry creature is curled up inside a cozy, grassy den with rocks. The creature is resting, and the den is surrounded by vibrant green grass and smooth stones. | A large, grey, furry creature with a long snout and small ears is sitting on a grassy hill, holding onto a rock with its front paws. The creature is looking up at the sky, which is a soft, pale color. | A large, white, cartoonish character with a round body and a small head is standing on a grassy hill. The character is facing the viewer and appears to be in a relaxed, standing pose. | A large, white, fluffy rabbit stands in a grassy field, looking up at a small pink butterfly that is flying above it. The rabbit has its arms slightly raised and is standing still, while a small red butterfly is visible on the grass to the left. | A large, white, fluffy rabbit stands in a grassy field, holding a red carrot in its right hand and eating it with its left paw. The rabbit is positioned in the foreground, with a backdrop of green trees, a blue sky, and distant mountains. | A large, white rabbit with long ears stands in a grassy field, looking up with a surprised expression. A purple butterfly flies in the air to the left of the rabbit. | A small, brown squirrel with large, round eyes peeks out from behind a large, gray rock. The squirrel is looking directly at the viewer with a curious expression. | A large, white rabbit with a worried expression stands in the foreground, looking up at a small brown squirrel perched on a tree trunk. A purple butterfly is flying in the air to the left of the rabbit. | A squirrel with a bushy tail is perched on a large tree trunk, looking down at the ground. A small, dark-furred mouse is sitting on the grass nearby, looking up at the squirrel. | A white rabbit with long ears is shown from the back, standing in a grassy field. The rabbit is facing away from the viewer, with a bright, sunny sky and distant hills in the background. | A red, fox-like character with a long tail is peeking out from behind a large tree trunk. A gray, mouse-like character is sitting on the grass, looking up at the fox. | A small, dark-furred animal with a red nose is lying on the grass near a large tree trunk. A brown, furry creature with a large head is standing in the foreground, facing the animal. | A brown squirrel with large, expressive eyes is looking up at a large tree. A small, dark-colored animal with a round face is peeking out from behind the tree trunk. | A small, dark-furred squirrel is sitting on the grass near a large tree trunk, holding a red object in its paws. A red fox with a bushy tail is standing on the grass, looking at the squirrel. A brown squirrel is on the grass to the right, looking at the fox. | A large, grey, cartoon rabbit with a round body and a prominent snout stands in a lush, green forest. The rabbit is holding a small red object in its right paw and is looking slightly to its left. | A white, furry creature with a long snout and a small tail is standing in a forest, holding a large, thick tree trunk with both front paws. The creature is looking up at the tree trunk, which is leaning against a tree. | A large, white, round rabbit with long ears stands in a forest, holding a green plant in its front paws. The rabbit is looking forward with a calm expression. | A small, gray, furry creature with a long snout is peeking out from behind a large tree trunk in a grassy field. The creature is looking towards the left side of the frame, where a single, green tree stands in the distance. | A small, red, bird-like creature with a long tail is flying over a vibrant green field. In the background, a large, green, leafy tree stands tall among other trees. | A large, green-skinned character with a prominent nose is holding a long, thin stick. The character is using the stick to carefully wrap a bundle of green leaves around a thick, brown tree branch. | A cartoon rabbit with large, wide eyes and a prominent white tooth is shown in a close-up. The rabbit's ears are perked up, and it appears to be looking directly at the viewer. | A small, gray, furry creature with large ears sits on a dirt path in a lush, green forest. The creature is holding a small, brown object in its paws and appears to be looking down at it. | A large, white, furry creature with a stern expression stands in a forest, looking down at a small, dark gray mouse on the ground. The creature has its arms outstretched and is holding a small, dark object in its right hand. | A small, brown squirrel with large, round eyes stands on a patch of dirt near a large tree trunk. The squirrel is holding a small, round object in its paws and looks directly at the viewer. | A cartoon squirrel with large, wide eyes and a furrowed brow is perched on a rock. It is looking down with a worried expression, its tail curled around its body. | A cartoon squirrel with a large, expressive eye is flying through the air with its arms outstretched. The squirrel is wearing a red bandana and has a bushy tail. | A cartoon squirrel with a brown and white coat is flying through the air with its arms outstretched. The squirrel has a long tail and is positioned against a bright blue sky with white clouds and a green tree visible in the background. | A cartoon squirrel with large, wide eyes is flying through the air. It has a bushy tail and is positioned above a green, leafy tree. | A small, brown squirrel with a large, round eye is perched on a thin branch, looking up at a large, white, furry creature. The creature, which has a long, pointed ear and a calm expression, is holding the branch with its front paws.
```

압축 입력:

```text
Long-term memory context: The worker observes a series of animated and real creatures in a natural setting: a cartoon bird singing on a tree, a furry creature resting in a den, another creature on a hill, a white character standing, and finally a rabbit with a butterfly above it, all within a grassy, natural environment The worker observes a white rabbit harvesting flowers, eating a carrot, and later encounters a squirrel and butterfly in a grassy field, before climbing a tree to observe a mouse below. The worker repeatedly digs in a grassy field, observing a white rabbit, a red fox, and various squirrels, while climbing a tree and interacting with them in a sunny, natural setting. The worker repeatedly digs and lifts logs in a lush forest, observing various animals including a cartoon rabbit, a white furry creature, a large white rabbit, and a small gray creature, while a red bird-like creature flies over a green field. The worker observes a series of interactions in a lush forest: a green-skinned character wraps leaves around a tree, a rabbit looks at the viewer, a gray creature ties a rope, a white furry creature observes a mouse, and a squirrel holds a round object while looking directly at the viewer. The worker observes a cartoon squirrel initially perched on a rock, then flying through the air with a red bandana and bushy tail, eventually perched on a branch above a tree, while a large, calm creature holds the branch. | Recent observations: No recent context available.
```
