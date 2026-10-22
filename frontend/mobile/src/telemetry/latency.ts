/** Durations use one monotonic clock; never subtract device and server dates. */
export type Summary = { n: number; p50: number; p95: number; max: number };
export class LatencyWindow {
  private values = new Map<string, number[]>();
  constructor(private readonly size = 120) {}
  observe(name: string, ms: number) {
    if (!Number.isFinite(ms) || ms < 0) return;
    const values = this.values.get(name) ?? [];
    values.push(ms);
    if (values.length > this.size) values.shift();
    this.values.set(name, values);
  }
  snapshot(): Record<string, Summary> {
    return Object.fromEntries([...this.values].map(([name, values]) => {
      const sorted = [...values].sort((a, b) => a - b);
      const percentile = (p: number) => sorted[Math.max(0, Math.ceil(p * sorted.length) - 1)];
      return [name, { n: sorted.length, p50: percentile(0.5), p95: percentile(0.95), max: sorted[sorted.length - 1] }];
    }));
  }
}
export type FrameStart = { captureRequestedAt: number };
export class FrameLatencyTracker {
  readonly metrics = new LatencyWindow();
  readonly counts = { sent: 0, completed: 0, failed: 0, timedOut: 0, abandoned: 0, evicted: 0, throttled: 0, offline: 0 };
  private pending = new Map<string, { capture?: number; sent: number }>();
  constructor(private readonly now = () => performance.now(), private readonly timeoutMs = 120_000, private readonly capacity = 128) {}
  start(id: string, capture?: number) {
    this.expire();
    if (this.pending.size >= this.capacity) {
      this.pending.delete(this.pending.keys().next().value!);
      this.counts.evicted++;
    }
    const sent = this.now();
    this.pending.set(id, { capture, sent });
    if (capture !== undefined) this.metrics.observe('capture_request_to_send_ms', sent - capture);
    this.counts.sent++;
  }
  complete(id: unknown, status: unknown, timing: unknown) {
    this.expire();
    if (typeof id !== 'string' || (status !== 'ok' && status !== 'error')) return false;
    const frame = this.pending.get(id);
    if (!frame) return false; // Duplicate, late, or another connection's result.
    this.pending.delete(id);
    if (status === 'error') { this.counts.failed++; return true; }
    const end = this.now();
    this.counts.completed++;
    this.metrics.observe('send_to_result_ms', end - frame.sent);
    if (frame.capture !== undefined) this.metrics.observe('capture_request_to_result_ms', end - frame.capture);
    if (timing && typeof timing === 'object') {
      for (const key of ['gateway_prepare_ms', 'queue_age_ms', 'context_ms', 'danger_check_ms', 'worker_total_ms']) {
        const value = (timing as Record<string, unknown>)[key];
        if (typeof value === 'number') this.metrics.observe(key, value);
      }
    }
    return true;
  }
  expire() {
    const now = this.now();
    for (const [id, frame] of this.pending) if (now - frame.sent >= this.timeoutMs) {
      this.pending.delete(id); this.counts.timedOut++;
    }
  }
  abandon() { this.counts.abandoned += this.pending.size; this.pending.clear(); }
  snapshot() {
    this.expire();
    return { source: 'bodycam_client', window: 120, counts: { ...this.counts }, pending: this.pending.size, metrics: this.metrics.snapshot() };
  }
}
