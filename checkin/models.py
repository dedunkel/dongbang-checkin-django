import uuid

from django.db import models
from django.db.models import Q, UniqueConstraint


class Event(models.Model):
    """
    행사 회차. "동방배틀 vol.33" 처럼 매 회차마다 하나씩 만듭니다.
    is_active=True인 회차가 "현재" 신청을 받는 회차입니다 (동시에 하나만 활성).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    volume = models.PositiveIntegerField(unique=True, help_text="예: 33")
    name = models.CharField(max_length=200, help_text='예: "동방배틀 vol.33"')
    is_active = models.BooleanField(default=True, help_text="신규 신청을 받는 현재 회차인지")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-volume"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_active:
            # 활성 회차는 동시에 하나만 — 이 회차를 활성화하면 나머지는 자동으로 비활성화.
            Event.objects.exclude(pk=self.pk).filter(is_active=True).update(is_active=False)


class EntryType(models.TextChoices):
    PARTICIPANT = "참가", "참가"
    VIEWER = "관람", "관람"


class VerificationStatus(models.TextChoices):
    N_A = "N_A", "해당없음"
    PENDING = "PENDING", "검수 대기"
    APPROVED = "APPROVED", "승인"
    REJECTED = "REJECTED", "반려"


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", "대기"
    PAID = "PAID", "입금 완료"


class CheckinStatus(models.TextChoices):
    NOT_CHECKED_IN = "NOT_CHECKED_IN", "체크인 전"
    CHECKED_IN = "CHECKED_IN", "체크인 완료"


class Participant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="participants")

    # 신청 정보 (구글 폼 문항에 대응)
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=50)
    school = models.CharField(max_length=200, null=True, blank=True)
    academic_status = models.CharField(max_length=50, null=True, blank=True)
    genre = models.CharField(max_length=100, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    payer_name = models.CharField(
        max_length=200, null=True, blank=True, help_text="입금자명 (운영진이 입금 내역과 대조할 때 참고)"
    )
    entry_type = models.CharField(max_length=10, choices=EntryType.choices)

    # 구글 폼 응답을 가져올 때 중복 수집을 막기 위한 참조값 (시트 행 번호).
    # 같은 회차에서 같은 external_ref가 이미 있으면 새로 만들지 않고 건너뜁니다.
    external_ref = models.CharField(max_length=100, null=True, blank=True)

    verification_status = models.CharField(
        max_length=10, choices=VerificationStatus.choices, default=VerificationStatus.PENDING
    )
    payment_status = models.CharField(
        max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )

    # 라벨 코드 (참가자만 값이 채워짐)
    label_group = models.CharField(max_length=4, null=True, blank=True)
    label_number = models.PositiveSmallIntegerField(null=True, blank=True)
    label_code = models.CharField(max_length=10, null=True, blank=True)
    label_manual_override = models.BooleanField(default=False)

    # QR / 체크인
    qr_token = models.UUIDField(null=True, blank=True, unique=True)
    qr_sent_at = models.DateTimeField(null=True, blank=True)
    checkin_status = models.CharField(
        max_length=20, choices=CheckinStatus.choices, default=CheckinStatus.NOT_CHECKED_IN
    )
    checked_in_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # 같은 회차·장르 안에서 같은 조/번호가 중복 배정되지 않도록 DB 레벨에서도 막는다.
            UniqueConstraint(
                fields=["event", "genre", "label_group", "label_number"],
                condition=Q(label_code__isnull=False),
                name="label_slot_unique",
            ),
            # 구글 폼 응답을 여러 번 가져와도 같은 회차 안에서 같은 external_ref로
            # 중복 생성되지 않도록 막는다 (재시도/백필 멱등성).
            UniqueConstraint(
                fields=["event", "external_ref"],
                condition=Q(external_ref__isnull=False),
                name="participant_external_ref_unique",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.entry_type})"

    def save(self, *args, **kwargs):
        # 관리자 화면 등에서 체크인 상태를 "체크인 전"으로 되돌리면, 이전
        # 체크인 시각이 그대로 남아 헷갈리지 않도록 함께 지운다.
        if self.checkin_status == CheckinStatus.NOT_CHECKED_IN and self.checked_in_at is not None:
            self.checked_in_at = None
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and "checked_in_at" not in update_fields:
                kwargs["update_fields"] = list(update_fields) + ["checked_in_at"]
        super().save(*args, **kwargs)
