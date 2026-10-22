import { useState, useRef, useCallback, useEffect } from 'react';
import type { SafetyEvent } from '../types';
import { VisionEngine } from '../engine';
import { DEFAULT_CONFIG } from '../config';
import { useModelLoader } from './useModelLoader';
import { EventEmitter } from '../events/eventEmitter';

export interface VisionEngineState {
  loading: boolean;
  error: string | null;
  events: SafetyEvent[];
  targetFps: number;
  lastInferenceMs: number;
}

/**
 * VisionEngine 생명주기 관리 훅.
 * 모델 로딩 → 엔진 초기화 → 프레임 처리 → 동적 FPS 조절.
 */
export function useVisionEngine() {
  const { yoloModel, movenetModel, loading: modelLoading, error: modelError } = useModelLoader();
  const engineRef = useRef<VisionEngine | null>(null);
  const emitterRef = useRef(new EventEmitter());
  const lastProcessedRef = useRef<number>(0);

  const [state, setState] = useState<VisionEngineState>({
    loading: true,
    error: null,
    events: [],
    targetFps: DEFAULT_CONFIG.fpsMonitor,
    lastInferenceMs: 0,
  });

  // 엔진 초기화
  useEffect(() => {
    if (modelLoading) return;

    if (modelError || !yoloModel) {
      setState(prev => ({ ...prev, loading: false, error: modelError || '모델 로딩 실패' }));
      return;
    }

    engineRef.current = new VisionEngine(yoloModel, movenetModel, DEFAULT_CONFIG);
    setState(prev => ({ ...prev, loading: false, error: null }));

    return () => {
      engineRef.current?.reset();
      engineRef.current = null;
    };
  }, [yoloModel, movenetModel, modelLoading, modelError]);

  // 동적 FPS 조절
  const adjustFps = useCallback((inferenceMs: number) => {
    let newFps: number;
    if (inferenceMs < 120) newFps = 7;
    else if (inferenceMs < 180) newFps = 5;
    else newFps = 3;

    setState(prev => {
      if (prev.targetFps !== newFps) {
        return { ...prev, targetFps: newFps, lastInferenceMs: inferenceMs };
      }
      return { ...prev, lastInferenceMs: inferenceMs };
    });
  }, []);

  // 프레임 처리
  const processFrame = useCallback(
    (
      yoloInput: Float32Array,
      frameWidth: number,
      frameHeight: number,
      poseInputFn?: (bbox: [number, number, number, number]) => Float32Array | null,
    ): { events: SafetyEvent[]; detections: any[]; processed: boolean } => {
      if (!engineRef.current) return { events: [], detections: [], processed: false };

      // FPS 스킵
      const now = Date.now();
      const interval = 1000 / state.targetFps;
      if (now - lastProcessedRef.current < interval) return { events: [], detections: [], processed: false };
      lastProcessedRef.current = now;

      const { events, detections } = engineRef.current.processFrame(
        yoloInput,
        frameWidth,
        frameHeight,
        poseInputFn,
      );

      const inferenceMs = engineRef.current.getLastInferenceMs();
      adjustFps(inferenceMs);

      if (events.length > 0) {
        setState(prev => ({ ...prev, events }));
        // 비동기 로컬 저장
        emitterRef.current.emit(events).catch(console.error);
      }

      return { events, detections, processed: true };
    },
    [state.targetFps, adjustFps],
  );

  const updateTask = useCallback(
    (partial: { workMode?: string; expectedHeightM?: number; outtriggerRequired?: boolean }) => {
      engineRef.current?.updateTask(partial);
    },
    [],
  );

  return {
    ...state,
    processFrame,
    updateTask,
    isReady: !state.loading && !state.error && engineRef.current !== null,
  };
}
