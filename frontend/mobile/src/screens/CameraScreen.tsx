/* 현장 촬영 화면 */
import React, { useState, useRef, useCallback, useEffect } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  StatusBar,
  Modal,
  Alert,
  Vibration,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  Camera,
  useCameraDevice,
  useCameraFormat,
  useCameraPermission,
  useMicrophonePermission,
} from 'react-native-vision-camera';
import BaseCamera from '../components/BaseCamera';
import RNFS from 'react-native-fs';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { RouteProp } from '@react-navigation/native';
import type { RootStackParamList } from '../../App';
import TopHeader from '../components/TopHeader';

import { useWorkSession } from '../context/WorkSessionContext';
import SafetyStream, { StreamResponse } from '../api/stream';

import { useVisionEngine } from '../vision/hooks/useVisionEngine';
import { preprocessImageForYOLO } from '../vision/utils/imagePreprocess';

import { PorcupineManager } from '@picovoice/porcupine-react-native';
import Voice, { SpeechResultsEvent } from '@react-native-voice/voice';
import Tts from 'react-native-tts';

type Props = {
  navigation: NativeStackNavigationProp<RootStackParamList, 'Camera'>;
  route: RouteProp<RootStackParamList, 'Camera'>;
};

type AssistantState = 'idle' | 'listening_for_wakeword' | 'listening_for_question' | 'speaking';



/* ──────── Configuration ──────── */

const STREAM_CONFIG = {
  WIDTH: 448,
  HEIGHT: 448,
  INTERVAL_MS: 1000,
};

const SEVERITY_COLORS: Record<string, string> = {
  high: '#FF3B30',
  medium: '#FF9500',
  low: '#FFCC00',
};

const SEVERITY_LABELS: Record<string, string> = {
  helmet_not_worn: '안전모 미착용',
  safety_vest_not_worn: '안전조끼 미착용',
  insufficient_worker_count: '작업자 부족',
  ladder_instability: '사다리 불안정',
  ladder_movement_with_person: '사다리 이동 위험',
  height_ladder_violation: '사다리 높이 초과',
  outtrigger_not_deployed: '아웃트리거 미설치',
  excessive_body_tilt: '과도한 몸 기울기',
  top_step_usage: '최상단 발판 사용',
};

/* ──────── Main Component ──────── */

export default function CameraScreen({ route }: Props) {
  const insets = useSafeAreaInsets();
  const { mode } = route.params;
  const isFullCam = mode === 'all';
  const isTestCam = mode === 'test';
  const isWorkerCam = mode === 'worker';
  
  // Local lightweight YOLO is now always loaded to support event-based streaming
  const useVision = true;

  const { workSessionId } = useWorkSession();

  // 스트리밍 설정 기반 포맷 선택
  const device = useCameraDevice('back');
  const streamFormat = useCameraFormat(device, [
    { videoResolution: { width: STREAM_CONFIG.WIDTH, height: STREAM_CONFIG.HEIGHT } },
  ]);

  // State
  const [isCameraActive, setIsCameraActive] = useState(false);
  const isCameraActiveRef = useRef(false);
  const isCameraReadyRef = useRef(false);
  const [isRecording, setIsRecording] = useState(false);
  const [alertVisible, setAlertVisible] = useState(false);
  const [alertMessage, setAlertMessage] = useState('');
  const [alertSeverity, setAlertSeverity] = useState<string>('medium');
  const [detections, setDetections] = useState<any[]>([]);
  const [previewSize, setPreviewSize] = useState({ width: 0, height: 0 });

  // Voice Assistant
  const [assistantState, setAssistantState] = useState<AssistantState>('idle');

  // Vision Engine (mode=all 전용)
  const vision = useVisionEngine();
  const [visionStatus, setVisionStatus] = useState<string>('');

  // Refs
  const cameraRef = useRef<Camera>(null);
  const streamRef = useRef<SafetyStream | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const porcupineManagerRef = useRef<PorcupineManager | null>(null);

  // Permissions:
  const {hasPermission, requestPermission} = useCameraPermission();
  const {hasPermission: hasMicPermission, requestPermission: requestMicPermission} = useMicrophonePermission();

  useEffect(() => {
    if (!hasPermission) requestPermission();
    if (!hasMicPermission) requestMicPermission();
  }, [hasPermission, requestPermission, hasMicPermission, requestMicPermission]);

  // Wake Word Callbacks
  const startWakeWord = async () => {
    try {
      if (porcupineManagerRef.current) {
        setAssistantState('listening_for_wakeword');
        await porcupineManagerRef.current.start();
      }
    } catch (e) {
      console.error("Wake word start error:", e);
    }
  };

  const stopWakeWord = async () => {
    try {
      if (porcupineManagerRef.current) {
        await porcupineManagerRef.current.stop();
      }
    } catch (e) {
      console.error("Wake word stop error:", e);
    }
  };

  const wakeWordCallback = async (keywordIndex: number) => {
    if (keywordIndex === 0) {
      // Wake word detected! Stop Porcupine and start listening to user's question
      await stopWakeWord();
      setAssistantState('listening_for_question');
      try {
        await Voice.start('ko-KR');
      } catch (e) {
        console.error("Voice start error:", e);
        startWakeWord();
      }
    }
  };

  // Voice Assistant Setup
  useEffect(() => {
    const initVoiceAssistant = async () => {
      // 1. Init TTS
      Tts.setDefaultLanguage('ko-KR');
      Tts.setDefaultRate(0.5); // Adjust rate as needed
      
      // Prevent TTS audio clash with camera/voice recordings on iOS
      Tts.setDefaultCategory('ios.audio.category.PLAY_AND_RECORD', {
        defaultToSpeaker: true,
        duckOthers: true, // Lowers background audio when speaking
        interruptSpokenAudioAndMixWithOthers: true,
      });

      Tts.addEventListener('tts-finish', () => {
        // Resume wake word listener after speaking finishes
        startWakeWord();
      });

      // 2. Init STT (Voice)
      Voice.onSpeechResults = (e: SpeechResultsEvent) => {
        const text = e.value?.[0] || '';
        if (text && streamRef.current) {
          const timestamp = new Date().toISOString();
          streamRef.current.sendQuestion(text, timestamp);
        }
        // Fallback: Restart wake word (will be overridden if an ANSWER triggers TTS quickly)
        startWakeWord(); 
      };

      Voice.onSpeechError = (e: any) => {
        console.error('Voice Error:', e);
        startWakeWord();
      };

      // 3. Init Porcupine
      try {
        porcupineManagerRef.current = await PorcupineManager.fromKeywordPaths(
          'YOUR_PICOVOICE_ACCESS_KEY', // TODO: Insert your actual Access Key here
          ['path/to/ttoktti.ppn'],     // TODO: Insert local path/require to the generated .ppn file
          wakeWordCallback
        );
        await startWakeWord();
      } catch (error) {
        console.error('Porcupine Initialization Error:', error);
      }
    };

    initVoiceAssistant();

    return () => {
      // Cleanup Voice Assistant engines
      Tts.stop();
      Voice.destroy().then(Voice.removeAllListeners);
      porcupineManagerRef.current?.delete();
    };
  }, []);

  // mode=worker: Event-Based WebSocket Streaming Connect
  useEffect(() => {
    const currentSessionId = workSessionId ? String(workSessionId) : "";
    if (!isWorkerCam || !isCameraActive) return;
    const userId = 'AuthContext_user_id';

    streamRef.current = new SafetyStream(
      userId, 
      { 
        worksession_id: currentSessionId, 
        video_path: ""  
      },
      (data: StreamResponse) => {
      if (data.type === 'DANGER') {
        setAlertMessage(data.message || '위험이 감지되었습니다!');
        setAlertSeverity('high');
        setAlertVisible(true);
      } else if (data.type === 'ANSWER') {
        Alert.alert('AI Assistant', data.message);
        setAssistantState('speaking');
        stopWakeWord().then(() => {
          Tts.speak(data.message);
        });
      }
    });

    streamRef.current.connect();

    return () => {
      streamRef.current?.disconnect();
    };
  }, [isWorkerCam, isCameraActive, workSessionId]);

  // ref 동기화
  useEffect(() => {
    isCameraActiveRef.current = isCameraActive;
  }, [isCameraActive]);

  // mode=all/test: 온디바이스 VisionEngine
  useEffect(() => {
    if (!useVision || !isCameraActive) {
      isCameraReadyRef.current = false;
      return;
    }
    if (!vision.isReady) {
      setVisionStatus(vision.loading ? '모델 로딩 중...' : vision.error || '');
      return;
    }

    setVisionStatus(`온디바이스 탐지 (${vision.targetFps}fps)`);

    const captureInterval = setInterval(async () => {
      if (!cameraRef.current || !vision.isReady) return;
      if (!isCameraActiveRef.current || !isCameraReadyRef.current) return;

      try {
        const photo = await cameraRef.current.takePhoto({
          flash: 'off',
          enableShutterSound: false,
        });

        // 실제 이미지 전처리: JPEG → 640x640 RGB Float32Array
        const inputData = await preprocessImageForYOLO(`file://${photo.path}`, 640);

        const { events, detections: frameDetections } = vision.processFrame(inputData, 640, 640);

        // 모드별 detection 필터
        const filtered = isTestCam
          ? frameDetections // test: 전체 표시
          : frameDetections.filter(
              d => d.label === 'person' || d.label === 'helmet' || d.label === 'safety_vest',
            );
        setDetections(filtered);

        // [EVENT-BASED STREAMING]
        // 로컬 YOLO(경량화된 모델)에서 유의미한 객체가 감지되었을 때만 비디오를 서버로 전송합니다.
        // 불필요한 네트워크 트래픽 및 Tailscale 라우팅 지연을 감소시킵니다.
        if (isWorkerCam && filtered.length > 0 && streamRef.current) {
          const base64 = await RNFS.readFile(photo.path, 'base64');
          streamRef.current.sendFrame(base64);
          console.log('[CameraScreen] 유의미한 객체 인식됨 -> 프레임 스트리밍 전송완료');
        }

        // 모드별 이벤트 처리
        if (isTestCam && events.length > 0) {
          // test 모드: 모든 이벤트 처리 (가장 높은 severity 우선)
          const sorted = [...events].sort((a, b) => {
            const order: Record<string, number> = { high: 0, medium: 1, low: 2 };
            return (order[a.severity] ?? 2) - (order[b.severity] ?? 2);
          });
          const top = sorted[0];
          const messages = events.map(e => SEVERITY_LABELS[e.label] || e.label);
          setAlertMessage(messages.join(', '));
          setAlertSeverity(top.severity);
          setAlertVisible(true);
          if (top.severity === 'high') {
            Vibration.vibrate(1000);
          } else {
            Vibration.vibrate(500);
          }
        } else if (isFullCam) {
          // all 모드: PPE만
          const helmetEvent = events.find(e => e.label === 'helmet_not_worn');
          const vestEvent = events.find(e => e.label === 'safety_vest_not_worn');
          if (helmetEvent || vestEvent) {
            const messages: string[] = [];
            if (helmetEvent) messages.push('안전모 미착용');
            if (vestEvent) messages.push('안전조끼 미착용');
            setAlertMessage(messages.join(', '));
            setAlertSeverity('medium');
            setAlertVisible(true);
            Vibration.vibrate(500);
          }
        }
      } catch (err) {
        console.error('[CameraScreen] 프레임 처리 실패:', err);
      }
    }, 1000); // 1fps

    return () => clearInterval(captureInterval);
  }, [useVision, isCameraActive, vision.isReady, vision.targetFps, vision.processFrame]);

  // 비전 이벤트 처리 → 알림 표시 (실험용으로 비활성화)
  // const handleVisionEvents = useCallback((events: SafetyEvent[]) => {
  //   if (events.length === 0) return;

  //   // 가장 높은 severity 이벤트 선택
  //   const sorted = [...events].sort((a, b) => {
  //     const order = { high: 0, medium: 1, low: 2 };
  //     return (order[a.severity] ?? 2) - (order[b.severity] ?? 2);
  //   });

  //   const top = sorted[0];
  //   const label = SEVERITY_LABELS[top.label] || top.label;
  //   setAlertMessage(label);
  //   setAlertSeverity(top.severity);
  //   setAlertVisible(true);

  //   if (top.severity === 'high') {
  //     Vibration.vibrate(500);
  //   }
  // }, []);

  const headerTitle = isTestCam ? '종합 테스트' : isFullCam ? '전체 촬영' : '작업자 환경 촬영';

  const handleToggleRecording = useCallback(async () => {
    if (!cameraRef.current) return;

    if (isRecording) {
      await cameraRef.current.stopRecording();
      setIsRecording(false);
    } else {
      setIsRecording(true);
      cameraRef.current.startRecording({
        onRecordingFinished: video => {
          console.log('Recording finished:', video.path);
        },
        onRecordingError: error => {
          console.error('Recording error:', error);
          setIsRecording(false);
        },
      });
    }
  }, [isRecording]);

  return (
    <View style={styles.container}>
      <StatusBar barStyle="dark-content" backgroundColor="#FFFFFF" />

      <TopHeader title={headerTitle} />

      {/* Vision Status Banner (mode=all/test) */}
      {useVision && visionStatus !== '' && (
        <View style={styles.statusBanner}>
          <Text style={styles.statusText}>{visionStatus}</Text>
          {vision.lastInferenceMs > 0 && (
            <Text style={styles.statusFps}>
              {vision.targetFps}fps / {vision.lastInferenceMs}ms
            </Text>
          )}
        </View>
      )}

      {/* Camera Preview Area */}
      <View
        style={styles.cameraPreview}
        onLayout={(e) => {
          const { width, height } = e.nativeEvent.layout;
          setPreviewSize({ width, height });
        }}>
        <BaseCamera
          ref={cameraRef}
          isActive={isCameraActive}
          video={true}
          audio={!useVision}
          format={streamFormat || undefined}
          isRecording={isRecording}
          onCapture={useVision ? undefined : handleToggleRecording}
          onInitialized={() => {
            console.log('[CameraScreen] 카메라 초기화 완료');
            isCameraReadyRef.current = true;
          }}
        />

        {/* Bounding Box Overlay */}
        {useVision && detections.length > 0 && previewSize.width > 0 && (
          <View style={StyleSheet.absoluteFill} pointerEvents="none">
            {detections.map((det, idx) => {
              const [x1, y1, x2, y2] = det.bbox;
              const scaleX = previewSize.width / 640;
              const scaleY = previewSize.height / 640;
              const left = x1 * scaleX;
              const top = y1 * scaleY;
              const width = (x2 - x1) * scaleX;
              const height = (y2 - y1) * scaleY;

              const boxColor =
                det.label === 'person' ? '#00FF00' :
                  det.label === 'helmet' ? '#00BFFF' :
                    det.label === 'safety_vest' ? '#FF9500' :
                      det.label === 'ladder' ? '#FF3B30' :
                        det.label === 'outtrigger' ? '#AF52DE' :
                          '#FFCC00'; // 기타

              return (
                <View
                  key={`${idx}-${det.label}`}
                  style={{
                    position: 'absolute',
                    left,
                    top,
                    width,
                    height,
                    borderWidth: 2,
                    borderColor: boxColor,
                    backgroundColor: 'transparent',
                  }}>
                  <View
                    style={{
                      backgroundColor: boxColor,
                      paddingHorizontal: 4,
                      paddingVertical: 2,
                    }}>
                    <Text style={{ color: '#000', fontSize: 10, fontWeight: 'bold' }}>
                      {det.label} {(det.score * 100).toFixed(0)}%
                    </Text>
                  </View>
                </View>
              );
            })}
          </View>
        )}
      </View>

      {/* Bottom Control Section */}
      <View
        style={[
          styles.bottomSection,
          { paddingBottom: insets.bottom + 16 },
        ]}>
        <TouchableOpacity
          style={[
            styles.cameraButton,
            isCameraActive && styles.cameraButtonActive,
          ]}
          onPress={() => setIsCameraActive(!isCameraActive)}>
          <Text style={styles.cameraButtonText}>
            {isCameraActive ? '촬영 중지' : '촬영 시작'}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Alert Modal */}
      <Modal
        visible={alertVisible}
        transparent
        animationType="fade"
        onRequestClose={() => setAlertVisible(false)}>
        <View style={styles.modalOverlay}>
          <View style={styles.dialog}>
            <View style={styles.dialogContent}>
              <Text
                style={[
                  styles.dialogTitle,
                  { color: SEVERITY_COLORS[alertSeverity] || '#FF3B30' },
                ]}>
                {alertSeverity === 'high'
                  ? '⚠️ 위험 감지!'
                  : alertSeverity === 'medium'
                    ? '⚠️ 주의'
                    : '📋 알림'}
              </Text>
              <Text style={styles.dialogDescription}>{alertMessage}</Text>
            </View>
            <View style={styles.dialogActions}>
              <TouchableOpacity
                style={styles.dialogButtonFilled}
                onPress={() => setAlertVisible(false)}>
                <Text style={styles.dialogButtonFilledText}>확인</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

/* ──────── Main Styles ──────── */

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F8F9FE',
  },

  /* Status Banner */
  statusBanner: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginHorizontal: 15,
    marginTop: 8,
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: '#F0F4FF',
    borderRadius: 8,
  },
  statusText: {
    fontSize: 12,
    color: '#FFB800',
    fontWeight: '600',
  },
  statusFps: {
    fontSize: 11,
    color: '#8E8E93',
  },

  /* Camera Preview */
  cameraPreview: {
    flex: 1,
    marginTop: 16,
    marginHorizontal: 15,
  },
  bottomSection: {
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 16,
    backgroundColor: '#FFFFFF',
  },
  cameraButton: {
    width: '100%',
    height: 56,
    borderRadius: 12,
    backgroundColor: '#FFB800',
    justifyContent: 'center',
    alignItems: 'center',
  },
  cameraButtonActive: {
    backgroundColor: '#FF3B30',
  },
  cameraButtonText: {
    fontSize: 16,
    fontWeight: '700',
    color: '#FFFFFF',
  },

  // Modal Styles
  modalOverlay: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: 'rgba(0, 0, 0, 0.5)' },
  dialog: { width: 300, backgroundColor: '#FFFFFF', borderRadius: 16, padding: 20, gap: 20 },
  dialogContent: { gap: 10, alignItems: 'center' },
  dialogTitle: { fontSize: 18, fontWeight: '800', color: '#FF3B30' },
  dialogDescription: { fontSize: 14, color: '#1F2024', textAlign: 'center' },
  dialogActions: { flexDirection: 'row', justifyContent: 'center' },
  dialogButtonFilled: { width: '100%', height: 44, borderRadius: 12, backgroundColor: '#FFB800', justifyContent: 'center', alignItems: 'center' },
  dialogButtonFilledText: { color: '#FFFFFF', fontWeight: '600' },
});
