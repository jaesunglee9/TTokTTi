# apps/reports/services.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from collections import Counter
from datetime import timedelta

from django.utils import timezone
from django.db.models import Prefetch

# ✅ WorkSession 계열: apps/worksession/models.py
from apps.worksession.models import Worksite, WorkSession, WorkSessionMember

# ✅ Check(준수/전후사진): apps/check/models.py
from apps.check.models import Compliance, Photo

# ✅ Detect(위험 유형/로그): apps/detect/models.py
from apps.detect.models import VideoLog, RiskType

# ✅ RiskAssessment 계열: apps/risk/models.py
from apps.risk.models import (
    RiskAssessment,
    RiskAssessmentImage,
    RiskReport,
    WorkerRecommendation,
)

from django.contrib.auth import get_user_model
User = get_user_model()


@dataclass
class Highlight:
    start: timezone.datetime
    end: timezone.datetime
    count: int
    top_types: List[Dict[str, Any]]
    evidence_samples: List[Dict[str, Any]]


def _dt(v):
    return v.isoformat() if v else None


def compute_risk_stats_and_highlights(
    videologs: List[VideoLog],
    window_sec: int = 60,
    threshold: int = 3,
    merge_gap_sec: int = 30,
    max_evidence_per_highlight: int = 3,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    - stats: 유형별/카메라별/조치(승인/반려/대기) 집계
    - highlights: 위험 로그가 특정 구간에 몰린 곳(시간창) 탐지
    """
    # 1) 위험 이벤트만 (risk_type 있는 것만)
    risk_events = [v for v in videologs if v.risk_type_id is not None]
    risk_events.sort(key=lambda x: x.detected_at or x.created_at)

    by_type = Counter()
    by_camera = Counter()
    manual_actions = Counter()

    for v in risk_events:
        rt = v.risk_type
        if rt:
            by_type[rt.name] += 1
            by_camera[rt.camera_type] += 1

        if v.source == "MANUAL":
            manual_actions[str(v.status or "PENDING")] += 1

    stats = {
        "total": len(risk_events),
        "by_type": [{"risk_type_name": k, "count": int(c)} for k, c in by_type.most_common()],
        "by_camera": {k: int(v) for k, v in by_camera.items()},
        "manual_actions": {
            "PENDING": int(manual_actions.get("PENDING", 0)),
            "APPROVED": int(manual_actions.get("APPROVED", 0)),
            "REJECTED": int(manual_actions.get("REJECTED", 0)),
        },
    }

    if not risk_events:
        return stats, []

    times = [v.detected_at or v.created_at for v in risk_events]
    n = len(times)
    i = 0
    j = 0
    w = timedelta(seconds=window_sec)

    candidates: List[Tuple[timezone.datetime, timezone.datetime, int, List[VideoLog]]] = []

    while i < n:
        while j < n and times[j] <= times[i] + w:
            j += 1
        cnt = j - i
        if cnt >= threshold:
            start = times[i]
            end = times[j - 1]
            evs = risk_events[i:j]
            candidates.append((start, end, cnt, evs))
        i += 1

    if not candidates:
        return stats, []

    # 병합
    candidates.sort(key=lambda x: x[0])
    merged: List[Tuple[timezone.datetime, timezone.datetime, List[VideoLog]]] = []

    cur_s, cur_e, _, cur_evs = candidates[0]
    for s, e, _, evs in candidates[1:]:
        if s <= cur_e + timedelta(seconds=merge_gap_sec):
            cur_e = max(cur_e, e)
            cur_evs.extend(evs)
        else:
            merged.append((cur_s, cur_e, cur_evs))
            cur_s, cur_e, cur_evs = s, e, evs
    merged.append((cur_s, cur_e, cur_evs))

    out: List[Dict[str, Any]] = []
    for s, e, evs in merged:
        # 중복 제거(병합 때문에)
        uniq = {v.id: v for v in evs}
        evs2 = sorted(uniq.values(), key=lambda x: x.detected_at or x.created_at)

        c_type = Counter()
        for v in evs2:
            if v.risk_type:
                c_type[v.risk_type.name] += 1

        top_types = [{"risk_type_name": k, "count": int(v)} for k, v in c_type.most_common(3)]

        evidence_samples = []
        for v in evs2[:max_evidence_per_highlight]:
            rt = v.risk_type
            evidence_samples.append({
                "videolog_id": v.id,
                "time": _dt(v.detected_at or v.created_at),
                "description": v.description,
                "risk_type_name": rt.name if rt else None,
                "camera_type": rt.camera_type if rt else None,
                "evidence_video": v.original_video,
                "source": v.source,
                "status": str(v.status) if v.status else None,
            })

        out.append({
            "start": _dt(s),
            "end": _dt(e),
            "count": len(evs2),
            "top_types": top_types,
            "evidence_samples": evidence_samples,
            "reason": "위험 로그 집중 구간",
        })

    return stats, out


def build_input_package(worksession_id: int) -> Dict[str, Any]:
    """
    worksession 기반 입력 패키지 생성 + (선택) assessment 섹션
    """
    ws = (
        WorkSession.objects
        .select_related("worksite")
        .prefetch_related(
            Prefetch("members", queryset=WorkSessionMember.objects.select_related("user")),
        )
        .get(id=worksession_id)
    )

    session_label = str(ws)  # Session({id}) - {status}

    # ✅ Photo / Compliance는 FK 필드명이 worksession
    photos = list(Photo.objects.filter(worksession_id=worksession_id).order_by("created_at"))
    before = [p for p in photos if p.status == "BEFORE"]
    after = [p for p in photos if p.status == "AFTER"]

    comp = list(Compliance.objects.filter(worksession_id=worksession_id).order_by("created_at"))

    # ✅ VideoLog도 FK 필드명이 worksession
    videologs = list(
        VideoLog.objects.filter(worksession_id=worksession_id)
        .select_related("risk_type")
        .order_by("created_at")
    )

    # participants
    heads, related, workers = [], [], []
    for m in ws.members.all():
        u = m.user
        item = {
            "user_id": u.id,
            "username": getattr(u, "username", None),
            "name": getattr(u, "name", None),
            "phone": getattr(u, "phone", None),
            "photo": getattr(u, "photo", None),
            "sex": getattr(u, "sex", None),
            "is_manager": getattr(u, "is_manager", None),
        }
        if m.role == "HEAD":
            heads.append(item)
        elif m.role == "RELATED":
            related.append(item)
        else:
            workers.append(item)

    # compliance stats
    def _comp_bucket(cat: str):
        rows = [r for r in comp if r.category == cat]
        complied = sum(1 for r in rows if r.is_complied is True)
        notc = sum(1 for r in rows if r.is_complied is False)
        unknown = sum(1 for r in rows if r.is_complied is None)
        return {"total": len(rows), "complied": complied, "not_complied": notc, "unknown": unknown}

    compliance_stats = {
        "helmet": _comp_bucket("HELMET"),
        "vest": _comp_bucket("VEST"),
        "shoes": _comp_bucket("SHOES"),
    }

    # risk stats + highlights
    risk_stats, highlights = compute_risk_stats_and_highlights(videologs)

    # events sample
    events_sample: List[Dict[str, Any]] = []
    for v in videologs[:200]:
        rt = v.risk_type
        events_sample.append({
            "videolog_id": v.id,
            "time": _dt(v.detected_at or v.created_at),
            "description": v.description,
            "source": v.source,
            "status": str(v.status) if v.status else None,
            "risk_type": {
                "id": rt.id if rt else None,
                "code": rt.code if rt else None,
                "name": rt.name if rt else None,
                "camera_type": rt.camera_type if rt else None,
                "description": rt.description if rt else None,
            },
            "evidence_video": v.original_video,
        })

    pkg: Dict[str, Any] = {
        "worksession": {
            "id": ws.id,
            "session_label": session_label,
            "status": ws.status,
            "starts_at": _dt(ws.starts_at),
            "ends_at": _dt(ws.ends_at),
            "worksite": {
                "id": ws.worksite.id,
                "name": ws.worksite.name,
                "address": ws.worksite.address,
            },
            "videos": {
                "fullcam_video": ws.fullcam_video,
                "bodycam_video": ws.bodycam_video,
                "meta": {
                    "fullcam_duration_sec": None,
                    "bodycam_duration_sec": None,
                }
            }
        },
        "participants": {
            "head_managers": heads,
            "related": related,
            "workers": workers,
        },
        "photos": {
            "before": [
                {"photo_id": p.id, "employee_id": p.employee_id, "image_path": p.image_path, "created_at": _dt(p.created_at)}
                for p in before
            ],
            "after": [
                {"photo_id": p.id, "employee_id": p.employee_id, "image_path": p.image_path, "created_at": _dt(p.created_at)}
                for p in after
            ],
        },
        "compliance": {
            "stats": compliance_stats,
            "records_sample": [
                {
                    "compliance_id": r.id,
                    "employee_id": r.employee_id,
                    "category": r.category,
                    "is_complied": r.is_complied,
                    "original_image": r.original_image,
                    "detected_image": r.detected_image,
                    "created_at": _dt(r.created_at),
                }
                for r in comp[:100]
            ],
        },
        "risk_logs": {
            "stats": risk_stats,
            "highlights": highlights,
            "events_sample": events_sample,
        },
    }

    return pkg