"""Authenticated, idempotent ingestion of bodycam VLM events."""
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.worksession.models import WorkSession, WorkSessionMember
from .models import RiskType, VideoLog
from .serializers import VideoSerializer

class BodycamEventSerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    worksession_id = serializers.IntegerField(min_value=1)
    description = serializers.CharField(max_length=4000)
    detected_at = serializers.DateTimeField()
    risk_type_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    video_path = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ingest_bodycam_event(request):
    serializer = BodycamEventSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    session = WorkSession.objects.filter(pk=data["worksession_id"]).first()
    if session is None:
        return Response({"detail": "Unknown work session"}, status=404)
    if not WorkSessionMember.objects.filter(worksession=session, user=request.user).exists():
        return Response({"detail": "Not a member of this work session"}, status=403)
    risk = None
    if data.get("risk_type_id") is not None:
        risk = RiskType.objects.filter(pk=data["risk_type_id"], camera_type="BODY").first()
        if risk is None:
            return Response({"detail": "A BODY risk type is required"}, status=400)
    with transaction.atomic():
        if risk is None:
            # A free-text VLM finding is not a reliable classifier for a specific hazard.
            risk, _ = RiskType.objects.get_or_create(
                code="BODY_VLM_HAZARD",
                defaults={"name": "바디캠 모델 위험 감지", "camera_type": "BODY",
                          "description": "분류되지 않은 바디캠 VLM 위험 설명"},
            )
            if risk.camera_type != "BODY":
                return Response({"detail": "Invalid generic risk configuration"}, status=409)
        expected = {
            "worksession_id": session.pk, "reported_by_id": request.user.pk,
            "risk_type_id": risk.pk, "description": data["description"],
            "detected_at": data["detected_at"], "original_video": data.get("video_path") or None,
            "source": "AUTO",
        }
        log, created = VideoLog.objects.get_or_create(event_id=data["event_id"], defaults=expected)
        if any(getattr(log, field) != value for field, value in expected.items()):
            return Response({"detail": "Event ID already used with different data"}, status=409)
    return Response({"ok": True, "created": created, "data": VideoSerializer(log).data},
                    status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
