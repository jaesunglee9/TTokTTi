# vision_fullcam/main.py
import time
import cv2

from vision_fullcam.latency import PipelineLatency
from vision_fullcam.config import Config
from vision_fullcam.stream.reader import FrameReader

# detector
from vision_fullcam.detection.yolo_detector import YoloDetector
from vision_fullcam.detection.fake_detector import FakeDetector
from vision_fullcam.detection.composite_detector import CompositeDetector

# tracking / state
from vision_fullcam.tracking.simple_tracker import SimpleTracker, Tracked
from vision_fullcam.state.state_buffer import StateBuffer
from vision_fullcam.state.task_state import TaskState
from vision_fullcam.state.ppe_observer import PPEObserver

# rules
from vision_fullcam.rules.base import RuleContext
from vision_fullcam.rules.ppe_rules import (
    HelmetNotWornRule,
    SafetyVestNotWornRule,
)
from vision_fullcam.rules.worker_count import InsufficientWorkerCountRule
from vision_fullcam.rules.ladder_rules import (
    LadderInstabilityRule,
    LadderMovementWithPersonRule,
)
from vision_fullcam.rules.height_rule import HeightLadderViolationRule
from vision_fullcam.rules.outtrigger_not_deployed import OuttriggerNotDeployedRule
from vision_fullcam.rules.posture_rules import (
    ExcessiveBodyTiltRule,
    TopStepUsageRule,
)
from vision_fullcam.rules.vehicle_rules import VehicleProximityRule

# events
from vision_fullcam.events.clip_buffer import ClipBuffer
from vision_fullcam.events.emitter import EventEmitter

from vision_fullcam.ui.draw import draw_tracked, draw_events

def build_detector(cfg: Config):
    if getattr(cfg, "use_fake_detector", False):
        return FakeDetector(fps=cfg.fps_monitor)

    # ✅ 1) best.pt (PPE / ladder / person)
    best_map = {
        0: "glove",
        1: "helmet",
        2: "ladder",
        3: "outtrigger",
        4: "person",
        5: "safety_vest",
    }
    det_best = YoloDetector(
        model_path="vision_fullcam/best.pt",
        cls_map=best_map,
        conf=0.35,
        imgsz=416,
    )

    # ✅ 2) COCO YOLO (vehicle 전용)
    coco_vehicle_map = {
        2: "vehicle",  # car
        3: "vehicle",  # motorcycle
        5: "vehicle",  # bus
        7: "vehicle",  # truck
    }
    det_vehicle = YoloDetector(
        model_path="yolov8n.pt",
        cls_map=coco_vehicle_map,
        conf=0.25,
        imgsz=416,
    )

    # ✅ 3) 합쳐서 반환
    return CompositeDetector([det_best, det_vehicle])

def _handle_keys(detector, task: TaskState, key: int):
    """
    FakeDetector 테스트 모드 키 입력 처리
    - 창(영상 창) 클릭해서 포커스 준 뒤 키를 눌러야 먹음.
    """
    if key in (-1, 255):
        return

    if key == 27:  # ESC
        raise KeyboardInterrupt

    # FakeDetector만 모드 전환 지원
    if not isinstance(detector, FakeDetector):
        return

    # 0~8: 모드 전환
    mapping = {
        ord("0"): ("normal",             "normal"),
        ord("1"): ("no_helmet",          "no_helmet (2s -> helmet_not_worn)"),
        ord("2"): ("no_vest",            "no_vest   (2s -> safety_vest_not_worn)"),
        ord("3"): ("one_person",         "one_person(5s -> insufficient_worker_count)"),
        ord("4"): ("ladder_move",        "ladder_move(-> ladder_movement_with_person)"),
        ord("5"): ("tilted_ladder",      "tilted_ladder(1s -> ladder_tilt)"),
        ord("6"): ("outtrigger_missing", "outtrigger_missing(2.5s -> outtrigger_not_deployed, task required=True)"),
        ord("7"): ("outtrigger_deployed","outtrigger_deployed(정상 상태)"),
        ord("8"): ("vehicle_proximity",  "vehicle_proximity(0.6s -> vehicle_proximity)"),
    }

    if key in mapping:
        mode, desc = mapping[key]
        detector.set_mode(mode)
        print(f"[MODE] {desc}")
        return

    # (옵션) outtrigger_required 토글: t 키
    if key == ord("t"):
        task.outtrigger_required = not bool(getattr(task, "outtrigger_required", False))
        print(f"[TASK] outtrigger_required={task.outtrigger_required}")
        return

    # (옵션) expected_height 토글: h 키 (height 룰 테스트용)
    if key == ord("h"):
        # 낮음(2.0) <-> 높음(4.0) 토글
        cur = float(getattr(task, "expected_height_m", 0.0) or 0.0)
        task.expected_height_m = 4.0 if cur < 3.5 else 2.0
        print(f"[TASK] expected_height_m={task.expected_height_m}")
        return


def main():
    cfg = Config()
    latency = PipelineLatency()

    # ========================
    # 입력 / 추론 파이프라인
    # ========================
    reader = FrameReader(getattr(cfg, "camera_index", 0))
    detector = build_detector(cfg)
    tracker = SimpleTracker(iou_thr=getattr(cfg, "tracker_iou_thr", 0.3))

    state = StateBuffer()
    ppe_observer = PPEObserver()

    # ========================
    # 작업(Task) 상태 (앱 입력)
    # ========================
    task = TaskState(
        work_mode=getattr(cfg, "work_mode", "ladder"),
        expected_height_m=float(getattr(cfg, "expected_height_m", 2.0) or 0.0),
        outtrigger_required=bool(getattr(cfg, "outtrigger_required", False)),
    )
    task.start()

    # ========================
    # 이벤트 시스템
    # ========================
    clip_buffer = ClipBuffer(
        fps=cfg.fps_monitor,
        keep_sec=cfg.clip_pre_sec + cfg.clip_post_sec,
    )
    emitter = EventEmitter(
        out_dir=getattr(cfg, "output_dir", "runs"),
        clip_buffer=clip_buffer,
    )

    # ========================
    # 룰 등록 (공용)
    # ========================
    rules = [
        # ladder / height
        HeightLadderViolationRule(cfg),
        LadderMovementWithPersonRule(cfg),
        LadderInstabilityRule(cfg),
        OuttriggerNotDeployedRule(cfg),

        # PPE
        HelmetNotWornRule(cfg),
        SafetyVestNotWornRule(cfg),

        # people
        InsufficientWorkerCountRule(cfg),

        # posture (pose 붙이면 활성)
        ExcessiveBodyTiltRule(cfg),
        TopStepUsageRule(cfg),
        # vehicle
        VehicleProximityRule(cfg),
    ]

    if isinstance(detector, FakeDetector):
        print("=== FakeDetector Test Keys ===")
        print("0: normal")
        print("1: no_helmet (2s -> helmet_not_worn)")
        print("2: no_vest   (2s -> safety_vest_not_worn)")
        print("3: one_person(5s -> insufficient_worker_count)")
        print("4: ladder_move (-> ladder_movement_with_person)")
        print("5: tilted_ladder (1s -> ladder_tilt)")
        print("6: outtrigger_missing (2.5s -> outtrigger_not_deployed, task required=True)")
        print("7: outtrigger_deployed (정상 상태)")
        print("8: vehicle_proximity (0.6s -> vehicle_proximity)")
        print("t: toggle outtrigger_required")
        print("h: toggle expected_height_m (2.0 <-> 4.0)")
        print("ESC: quit")

    # ========================
    # 메인 루프
    # ========================
    dt_target = 1.0 / max(1, cfg.fps_monitor)

    try:
        while True:
            t0 = time.perf_counter()
            frame = reader.read()
            if frame is None:
                break

            read_done = time.perf_counter()
            clip_buffer.push(frame)

            # 1) detection
            detection_started = time.perf_counter()
            detections = detector.detect(frame)
            detection_done = time.perf_counter()

            # 2) tracking
            tracked_input = [
                Tracked(track_id=-1, label=d.label, bbox=d.bbox, score=d.score)
                for d in detections
            ]
            tracked = tracker.update(tracked_input)

            draw_tracked(frame, tracked)

            # 3) state update
            now = time.time()
            state.update(tracked,frame, now)

            # 4) PPE / ladder observer (state 채움)
            ppe_observer.update(
                persons=state.persons,
                tracked=tracked,
                frame_shape=frame.shape[:2],
            )

            # 5) rule context
            ctx = RuleContext(timestamp=now, frame=frame, state=state, task=task)

            # 6) rule evaluation
            events = []
            for rule in rules:
                if rule.is_active(ctx):
                    events.extend(rule.evaluate(ctx))
            
            if events:
                draw_events(frame, events)

            rules_done = time.perf_counter()
            # 7) emit
            if events:
                emitter.emit(events, frame)
                for e in events:
                    print(
                        f"[EVENT] {e.label} "
                        f"sev={e.severity} "
                        f"target={e.target_id} "
                        f"info={e.info}"
                    )

            emit_done = time.perf_counter()
            # 8) monitor + key handling (키는 여기서 딱 1번만 읽음)
            if getattr(cfg, "show_window", True):
                cv2.imshow("vision_fullcam", frame)

            display_submitted = time.perf_counter()
            metrics = {
                "read_ms": (read_done - t0) * 1000,
                "detector_ms": (detection_done - detection_started) * 1000,
                "tracking_state_rules_ms": (rules_done - detection_done) * 1000,
                "event_emit_ms": (emit_done - rules_done) * 1000,
                "read_request_to_result_ms": (rules_done - t0) * 1000,
            }
            if getattr(cfg, "show_window", True):
                metrics["read_request_to_display_submit_ms"] = (display_submitted - t0) * 1000
            latency.record(metrics)

            key = cv2.waitKey(1) & 0xFF
            _handle_keys(detector, task, key)

            # fps sync
            dt = time.perf_counter() - t0
            if dt < dt_target:
                time.sleep(dt_target - dt)

    except KeyboardInterrupt:
        pass
    finally:
        latency.flush()
        reader.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()