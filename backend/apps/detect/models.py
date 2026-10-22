from django.db import models
from django.conf import settings

class RiskType(models.Model):

    class CameraType(models.TextChoices):
        BODY = "BODY", "Body Cam"
        FULL = "FULL", "Full Cam"

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, null=True, blank=True)

    camera_type = models.CharField(
        max_length=10,
        choices=CameraType.choices
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "risk_type"
        ordering = ["id"]

    def __str__(self):
        return self.name
    
class VideoLog(models.Model): # 알림 로그의 의미 (웹에서 관리자에게 보여지는 로그)

    event_id = models.UUIDField(null=True, blank=True, unique=True)
    description = models.TextField(blank=True, default="")
    detected_at = models.DateTimeField(null=True, blank=True, db_index=True)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="bodycam_events",
    )

    class SourceChoices(models.TextChoices):
        AUTO = "AUTO", "Auto Detection" # 모델에 의한 자동 위험 감지 로그
        MANUAL = "MANUAL", "Manual Report" # 사용자가 수동으로 요청한 로그

    class StatusChoices(models.TextChoices): # manual 의 경우에만 상태 필드 필요함
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    source = models.CharField(
        max_length=10,
        choices=SourceChoices.choices
    )

    status = models.CharField(
        max_length=10,
        choices=StatusChoices.choices,
        null=True,
        blank=True
    )

    worksession = models.ForeignKey(
        "worksession.WorkSession",
        on_delete=models.CASCADE,
        related_name="video_logs"
    )

    risk_type = models.ForeignKey( # AUTO인 경우에만
        RiskType,
        on_delete=models.CASCADE,
        related_name="video_logs",
        null=True,
        blank=True
    )

    compliance = models.ForeignKey(
        "check.Compliance",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="logs"
    )

    original_video = models.CharField(max_length=255, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "videolog"
        ordering = ["-created_at"]

    def __str__(self):
        return f"VideoLog({self.id})"

class VideoLogRead(models.Model):

    videolog = models.ForeignKey(
        VideoLog,
        on_delete=models.CASCADE,
        related_name="read_status"
    )

    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="video_reads"
    )

    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "videolog_read"
        unique_together = ("videolog", "manager")

    def __str__(self):
        return f"Read({self.manager_id}, {self.videolog_id})"