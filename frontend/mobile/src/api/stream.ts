// src/api/stream.ts
import { Alert } from 'react-native';
import { FrameLatencyTracker, type FrameStart } from '../telemetry/latency';

export type StreamMessageType = 'DANGER' | 'ANSWER' | 'ANSWER_CHUNK' | 'ANSWER_DONE' | 'FRAME_RESULT' | 'REPORT_RESULT';
export interface StreamResponse {
  type: StreamMessageType;
  message: string;
  details?: string;
  timestamp?: string;
  frame_id?: string;
  status?: 'ok' | 'error' | 'saved';
  event_id?: string;
  videolog_id?: number;
  timing?: Record<string, number>;
}
export interface SessionConfig {
  worksession_id: string;
  video_path: string;
  accessToken?: string;
  riskTypeId?: number;
  /** Diagnostic frames receive a completion even when no danger is detected. */
  measureLatency?: boolean;
  gatewayUrl?: string;
}

class SafetyStream {
  private ws: WebSocket | null = null;
  private url: string;
  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 5;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private metricsTimer: ReturnType<typeof setInterval> | null = null;
  private stopped = false;
  private lastFrameTime = -Infinity;
  private readonly FRAME_INTERVAL_MS = 1000;
  private readonly latency = new FrameLatencyTracker();
  private readonly tracePrefix = Math.random().toString(36).slice(2);
  private sequence = 0;

  constructor(clientId: string, private config: SessionConfig, private onMessageCallback: (data: StreamResponse) => void) {
    const gateway = config.gatewayUrl ?? 'wss://laptop-gpu.tail413c80.ts.net';
    this.url = `${gateway.replace(/\/$/, '')}/ws/stream/${encodeURIComponent(clientId)}`;
  }

  public connect() {
    if (this.stopped || this.ws) return;
    const socket = new WebSocket(this.url);
    this.ws = socket;
    socket.onopen = () => {
      if (this.ws !== socket || this.stopped) return;
      console.log('✅ Connected to Safety Gateway');
      this.reconnectAttempts = 0;
      socket.send(JSON.stringify({
        type: 'CONFIG', worksession_id: this.config.worksession_id,
        video_path: this.config.video_path, access_token: this.config.accessToken,
        risk_type_id: this.config.riskTypeId, latency_metrics: this.config.measureLatency === true,
      }));
      if (this.config.measureLatency && !this.metricsTimer) {
        this.metricsTimer = setInterval(() => {
          const summary = this.latency.snapshot();
          if (summary.counts.sent) console.log('[LATENCY]', JSON.stringify(summary));
        }, 10_000);
      }
    };
    socket.onmessage = e => {
      if (this.ws !== socket || this.stopped) return;
      try {
        const data: StreamResponse = JSON.parse(e.data);
        if (data.type === 'FRAME_RESULT') {
          if (this.config.measureLatency) this.latency.complete(data.frame_id, data.status === 'ok' ? 'ok' : 'error', data.timing);
          return; // Measurement acknowledgments are not safety alerts.
        }
        this.onMessageCallback(data);
      } catch (err) {
        console.error('❌ Failed to parse stream message:', err);
      }
    };
    socket.onclose = e => {
      if (this.ws !== socket) return;
      this.ws = null;
      this.latency.abandon();
      console.log('🔌 Connection closed:', e.reason);
      if (!this.stopped) this.handleReconnect();
    };
    socket.onerror = e => console.error('⚠️ WebSocket Error:', e);
  }

  private handleReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      this.reconnectTimer = setTimeout(() => { this.reconnectTimer = null; this.connect(); }, 3000);
    } else {
      Alert.alert('연결 오류', '서버와의 연결이 끊겼습니다. 네트워크를 확인해주세요.');
    }
  }

  public updateAccessToken(accessToken: string) {
    this.config.accessToken = accessToken;
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'CONFIG',
        worksession_id: this.config.worksession_id, video_path: this.config.video_path,
        access_token: accessToken, risk_type_id: this.config.riskTypeId,
        latency_metrics: this.config.measureLatency === true }));
    }
  }

  public sendFrame(base64Image: string, capture?: FrameStart): boolean {
    const now = performance.now();
    if (this.ws?.readyState !== WebSocket.OPEN) {
      if (this.config.measureLatency) this.latency.counts.offline++;
      return false;
    }
    if (now - this.lastFrameTime < this.FRAME_INTERVAL_MS) {
      if (this.config.measureLatency) this.latency.counts.throttled++;
      return false;
    }
    this.lastFrameTime = now;
    const id = this.config.measureLatency ? `${this.tracePrefix}-${++this.sequence}` : undefined;
    const payload = JSON.stringify({ type: 'FRAME', image: base64Image, timestamp: Date.now(), frame_id: id });
    // Serialization is included in capture-to-send, but not send-to-result.
    if (id) this.latency.start(id, capture?.captureRequestedAt);
    try {
      this.ws.send(payload);
      return true;
    } catch (error) {
      if (id) this.latency.complete(id, 'error', {});
      console.warn('Frame send failed:', error);
      return false;
    }
  }

  public sendQuestion(text: string, timestamp: string) {
    if (this.ws?.readyState === WebSocket.OPEN)
      this.ws.send(JSON.stringify({ type: 'QUESTION', text, timestamp }));
  }

  public getLatencySummary() { return this.latency.snapshot(); }

  public disconnect() {
    if (this.stopped) return;
    this.stopped = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.metricsTimer) clearInterval(this.metricsTimer);
    this.reconnectTimer = null;
    this.metricsTimer = null;
    this.latency.abandon();
    if (this.config.measureLatency && this.latency.counts.sent)
      console.log('[LATENCY]', JSON.stringify(this.latency.snapshot()));
    const socket = this.ws;
    this.ws = null; // Ignore the close callback; deliberate stop must never reconnect.
    socket?.close();
  }
}
export default SafetyStream;
