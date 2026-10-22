import type { TensorflowModel } from 'react-native-fast-tflite';
import type { Detection, SafetyEvent, Tracked } from './types';
import type { VisionConfig } from './config';
import type { Rule, RuleContext } from './rules/base';

import { TFLiteDetector } from './detection/tfliteDetector';
import { SimpleTracker } from './tracking/simpleTracker';
import { StateBuffer } from './state/stateBuffer';
import { TaskState } from './state/taskState';
import { PoseEstimator } from './pose/movenet';
import { estimatePersonHeightPx, estimateLadderHeightM } from './geometry/height';

import { HelmetNotWornRule, SafetyVestNotWornRule, SafetyShoesNotWornRule } from './rules/ppeRules';
import { InsufficientWorkerCountRule } from './rules/workerCount';
import { LadderInstabilityRule, LadderMovementWithPersonRule } from './rules/ladderRules';
import { HeightLadderViolationRule } from './rules/heightRule';
import { OuttriggerNotDeployedRule } from './rules/outtriggerRule';
import { ExcessiveBodyTiltRule, TopStepUsageRule } from './rules/postureRules';

/**
 * 메인 비전 파이프라인.
 * Python main.py의 while 루프를 processFrame() 단위 호출로 대체.
 */
export class VisionEngine {
  private detector: TFLiteDetector;
  private poseEstimator: PoseEstimator | null;
  private tracker: SimpleTracker;
  private state: StateBuffer;
  private taskState: TaskState;
  private rules: Rule[];
  private config: VisionConfig;
  private lastInferenceMs: number = 0;
  private lastLogTime: number = 0;

  constructor(
    yoloModel: TensorflowModel,
    movenetModel: TensorflowModel | null,
    config: VisionConfig,
  ) {
    this.config = config;
    this.detector = new TFLiteDetector(yoloModel, config.confidenceThreshold, 0.5, 640);
    this.poseEstimator = movenetModel ? new PoseEstimator(movenetModel) : null;
    this.tracker = new SimpleTracker(0.3);
    this.state = new StateBuffer();
    this.taskState = new TaskState('ladder', 2.0, false);
    this.taskState.start();

    this.rules = [
      // PPE
      new HelmetNotWornRule(config),
      new SafetyVestNotWornRule(config),
      new SafetyShoesNotWornRule(config),

      // Worker count
      new InsufficientWorkerCountRule(config),

      // Ladder
      new LadderInstabilityRule(config),
      new LadderMovementWithPersonRule(config),
      new HeightLadderViolationRule(config),

      // Equipment
      new OuttriggerNotDeployedRule(config),

      // Posture (pose 기반)
      new ExcessiveBodyTiltRule(config),
      new TopStepUsageRule(config),
    ];
  }

  /**
   * 1프레임 처리.
   *
   * @param yoloInput - 640x640x3 Float32Array (0~1 정규화)
   * @param frameWidth - 원본 프레임 너비 (PPE ROI 계산용)
   * @param frameHeight - 원본 프레임 높이
   * @param poseInputFn - person bbox → 192x192x3 crop Float32Array 반환 함수 (선택)
   * @returns { events, detections } - 안전 이벤트와 detection 결과
   */
  processFrame(
    yoloInput: Float32Array,
    frameWidth: number,
    frameHeight: number,
    poseInputFn?: (bbox: [number, number, number, number]) => Float32Array | null,
  ): { events: SafetyEvent[]; detections: Detection[] } {
    const started = performance.now();
    const t0 = Date.now();
    const now = t0 / 1000;
    const shouldLog = t0 - this.lastLogTime >= 1000; // 1초마다 로그

    // 1) Detection
    const detections: Detection[] = this.detector.detect(yoloInput);
    if (shouldLog && detections.length > 0) {
      console.log(
        `[Vision:Detection] ${detections.length}개 탐지:`,
        detections.map(d => `${d.label}(${(d.score * 100).toFixed(0)}%) [${d.bbox}]`).join(', '),
      );
    }

    // 2) Tracking
    const trackedInput: Tracked[] = detections.map(d => ({
      trackId: -1,
      label: d.label,
      bbox: d.bbox,
      score: d.score,
    }));
    const tracked = this.tracker.update(trackedInput);
    if (shouldLog && tracked.size > 0) {
      const trackLog = Array.from(tracked.values())
        .map(t => `#${t.trackId} ${t.label}`)
        .join(', ');
      console.log(`[Vision:Tracking] 활성 트랙 ${tracked.size}개: ${trackLog}`);
    }

    // 3) State update (PPE observer 포함)
    this.state.update(tracked, [frameHeight, frameWidth], now);
    if (shouldLog) {
      console.log(
        `[Vision:State] person=${this.state.site.personCount} ladder=${this.state.site.anyLadder} outtrigger=${this.state.site.anyOuttrigger}`,
      );
    }

    // 4) Pose estimation (선택)
    if (this.poseEstimator && poseInputFn) {
      for (const p of this.state.persons.values()) {
        if (p.bbox === null) continue;

        const cropData = poseInputFn(p.bbox);
        if (cropData === null) continue;

        const poseResult = this.poseEstimator.infer(cropData, p.bbox);
        if (poseResult) {
          p.keypoints = poseResult.keypoints;
          p.poseHist.push({
            tilt_deg: poseResult.bodyTiltDeg,
            torso_vector: poseResult.torsoVector,
          });

          // person height estimation (for ladder height calc)
          const heightPx = estimatePersonHeightPx(poseResult.keypoints);
          if (heightPx !== null) {
            p.heightPxHist.push(heightPx);
          }
        }
      }

      // 사다리 높이 추정 (가장 가까운 person의 height_px 사용)
      for (const l of this.state.ladders.values()) {
        if (l.bbox === null) continue;

        let bestHeightPx: number | null = null;
        for (const p of this.state.persons.values()) {
          const ph = p.heightPx;
          if (ph !== null) {
            if (bestHeightPx === null || ph > bestHeightPx) {
              bestHeightPx = ph;
            }
          }
        }

        const heightM = estimateLadderHeightM(l.bbox, bestHeightPx);
        if (heightM !== null) {
          l.heightMHist.push(heightM);
        }
      }
    }

    // 5) Rule evaluation
    const ctx: RuleContext = {
      timestamp: now,
      state: this.state,
      task: this.taskState,
    };

    const events: SafetyEvent[] = [];
    for (const rule of this.rules) {
      const ruleEvents = rule.evaluate(ctx);
      if (ruleEvents.length > 0) {
        for (const e of ruleEvents) {
          console.log(
            `[Vision:EVENT] ${e.severity.toUpperCase()} | ${e.label} | target=#${e.targetId ?? 'site'} | info=${JSON.stringify(e.info)}`,
          );
        }
      }
      events.push(...ruleEvents);
    }

    this.lastInferenceMs = Math.round(performance.now() - started);

    if (shouldLog) {
      console.log(`[Vision:Frame] ${this.lastInferenceMs}ms | 탐지=${detections.length} | 이벤트=${events.length}`);
      this.lastLogTime = t0;
    }

    return { events, detections };
  }

  getLastInferenceMs(): number {
    return this.lastInferenceMs;
  }

  updateTask(partial: Partial<TaskState>): void {
    if (partial.workMode !== undefined) this.taskState.workMode = partial.workMode;
    if (partial.expectedHeightM !== undefined) this.taskState.expectedHeightM = partial.expectedHeightM;
    if (partial.outtriggerRequired !== undefined) this.taskState.outtriggerRequired = partial.outtriggerRequired;
  }

  reset(): void {
    this.tracker.reset();
    this.state.reset();
  }
}
