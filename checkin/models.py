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
    event_date = models.DateField(null=True, blank=True, help_text="행사 당일 날짜 (선택)")
    location = models.CharField(max_length=200, null=True, blank=True, help_text="행사 장소 (선택, 예: 국민대학교)")
    is_active = models.BooleanField(default=True, help_text="신규 신청을 받는 현재 회차인지")
    # 이 회차의 점수 시트에 붙인 google-apps-script/SheetSync.gs를 웹 앱으로
    # 배포하면 나오는 URL(/exec로 끝남). 회차마다 새 시트를 만들어 새로 배포하기
    # 때문에 값이 자주 바뀌는데, 환경변수로 두면 매 행사마다 재배포가 필요해서
    # 회차별로 여기서 바로 수정할 수 있게 함(비워두면 이 기능만 꺼짐).
    sheet_sync_url = models.URLField(
        blank=True, null=True, help_text="이 회차 점수 시트에 배포한 SheetSync.gs 웹 앱 URL (선택)"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-volume"]
        verbose_name = "회차"
        verbose_name_plural = "회차"
        permissions = [
            (
                "export_sensitive_data",
                "마스킹 없는 민감 정보 엑셀 내보내기 가능 (점수표, CSV 백업)",
            ),
        ]

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


class Genre(models.TextChoices):
    """참가자 신청 장르. 값은 구글 폼 선택지 문구와 정확히 동일해야 한다 —
    SheetSync.gs의 GENRE_TAB_MAP, event_excel_export.py의 GENRE_TABS가
    이 값으로 참가자를 장르별 탭에 배정하기 때문에, 값이 조금이라도
    어긋나면 해당 참가자가 그 어떤 엑셀/시트에도 나타나지 않게 된다."""

    WAACKING = "Waacking", "왁킹"
    POPPING = "Popping", "팝핑"
    LOCKING = "Locking", "락킹"
    HOUSE = "House", "하우스"
    KRUMP = "Krump", "크럼프"
    HIPHOP = "Hiphop", "힙합"
    BREAKING = "Breaking", "브레이킹"


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
    genre = models.CharField(max_length=100, null=True, blank=True, choices=Genre.choices)
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
        verbose_name = "참가자"
        verbose_name_plural = "참가자"
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
        def _also_update(field: str) -> None:
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and field not in update_fields:
                kwargs["update_fields"] = list(update_fields) + [field]

        # label_code("A-3" 같은 표시용 문자열)는 label_group/label_number로부터
        # 항상 다시 계산한다 — 관리자 화면에서 셋을 각각 따로 수정할 수 있다 보니
        # (예: label_group만 지우고 label_code는 그대로 두는 식) 서로 안 맞는
        # 상태가 남으면 엑셀 내보내기 정렬에서 터지는 문제가 있었다. label_code를
        # 직접 고쳐도 이 값이 우선이라 반영되지 않는다 — 실제 값은 group/number다.
        new_label_code = (
            f"{self.label_group}-{self.label_number}"
            if self.label_group not in (None, "") and self.label_number is not None
            else None
        )
        if self.label_code != new_label_code:
            self.label_code = new_label_code
            _also_update("label_code")

        # 관리자 화면 등에서 체크인 상태를 "체크인 전"으로 되돌리면, 이전
        # 체크인 시각이 그대로 남아 헷갈리지 않도록 함께 지운다.
        if self.checkin_status == CheckinStatus.NOT_CHECKED_IN and self.checked_in_at is not None:
            self.checked_in_at = None
            _also_update("checked_in_at")

        super().save(*args, **kwargs)
