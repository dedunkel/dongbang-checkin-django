import csv

from django.contrib import admin, messages
from django.db import transaction
from django.db.models import CharField, Count, Q, Value
from django.db.models.functions import Cast, Concat, LPad
from django.http import HttpResponse
from django.urls import reverse
from django.utils.html import format_html
from django.utils.http import content_disposition_header

from .models import CheckinStatus, Event, Genre, Participant, PaymentStatus, VerificationStatus
from .services import sheet_sync
from .services.announcement_export import build_announcement_file
from .services.application_confirmation_export import build_application_confirmation_file
from .services.assign_labels import assign_labels_and_tokens
from .services.event_excel_export import find_duplicate_labels
from .services.score_sheet_export import build_score_sheet_file

# 계정 관리 → 계정 수정 화면(User/Group 기반 커스텀 UserAdmin)을 등록한다.
# Django의 admin 자동탐색은 각 앱의 admin.py만 임포트하므로, 별도 파일인
# auth_admin.py는 여기서 명시적으로 임포트해줘야 등록 코드가 실행된다.
from . import auth_admin  # noqa: F401,E402

admin.site.site_header = "DBBT STAFF"
admin.site.site_title = "DBBT STAFF"
admin.site.index_title = "운영진 대시보드"

# 폼/목록에 노출되는 라벨을 목업 문구에 맞추는 표시용 조정. verbose_name은
# 스키마에 영향을 주지 않는 메타데이터라 마이그레이션 없이 바꿔도 안전하다.
_EVENT_LABELS = {
    "volume": "회차 번호",
    "name": "회차 이름",
    "event_date": "행사 날짜",
    "location": "행사 장소",
    "is_active": "신규 신청 활성화",
    "sheet_sync_url": "점수 시트 연동 URL",
    "created_at": "생성일",
}
for _field, _label in _EVENT_LABELS.items():
    Event._meta.get_field(_field).verbose_name = _label

_PARTICIPANT_LABELS = {
    "event": "회차",
    "entry_type": "구분",
    "name": "이름",
    "phone": "연락처",
    "school": "소속대학",
    "academic_status": "학적",
    "genre": "참가 장르",
    "payer_name": "입금자명",
    "external_ref": "신청 연동 참조값 (external_ref)",
    "verification_status": "학적검수",
    "payment_status": "입금 상태",
    "label_group": "라벨 그룹",
    "label_number": "라벨 번호",
    "label_code": "라벨 코드",
    "qr_token": "QR 토큰",
    "qr_sent_at": "QR 발송 일시",
    "checkin_status": "체크인 상태",
    "checked_in_at": "체크인 시각",
    "id": "ID",
    "created_at": "신청 일시",
}
for _field, _label in _PARTICIPANT_LABELS.items():
    Participant._meta.get_field(_field).verbose_name = _label


# list_filter의 필터 pill 문구는 위 verbose_name(폼 라벨)보다 짧게 — 목업
# 툴바가 "검수: 전체"/"입금: 전체"처럼 축약된 이름을 쓰기 때문에 필드
# verbose_name과 별도로 title을 지정할 수 있는 커스텀 필터가 필요하다.
class _ChoiceFilter(admin.SimpleListFilter):
    field_name = None
    choices_source = None

    def lookups(self, request, model_admin):
        return self.choices_source

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(**{self.field_name: self.value()})
        return queryset


class GenreFilter(_ChoiceFilter):
    title = "장르"
    parameter_name = "genre"
    field_name = "genre"
    choices_source = Genre.choices


class VerificationFilter(_ChoiceFilter):
    title = "학적검수"
    parameter_name = "verification_status"
    field_name = "verification_status"
    choices_source = VerificationStatus.choices


class PaymentFilter(_ChoiceFilter):
    title = "입금"
    parameter_name = "payment_status"
    field_name = "payment_status"
    choices_source = PaymentStatus.choices


class CheckinFilter(_ChoiceFilter):
    title = "체크인"
    parameter_name = "checkin_status"
    field_name = "checkin_status"
    choices_source = CheckinStatus.choices


class ActiveFilter(admin.SimpleListFilter):
    title = "활성 여부"
    parameter_name = "is_active"

    def lookups(self, request, model_admin):
        return (("1", "활성"), ("0", "비활성"))

    def queryset(self, request, queryset):
        if self.value() == "1":
            return queryset.filter(is_active=True)
        if self.value() == "0":
            return queryset.filter(is_active=False)
        return queryset


@admin.action(description="라벨 / QR 발급")
def run_label_assign(modeladmin, request, queryset):
    for event in queryset:
        result = assign_labels_and_tokens(event)
        messages.success(
            request,
            f'"{event.name}": 라벨 신규 배정 {result["labeled"]}명 / QR 신규 발급 {result["issued"]}명',
        )


@admin.action(description="점수 시트 순서 반영")
def push_order_to_sheet(modeladmin, request, queryset):
    for event in queryset:
        result = sheet_sync.push_order_for_event(event)
        if result.get("ok"):
            messages.success(
                request,
                f'"{event.name}": 점수 시트 순서 반영 완료 '
                f'({result.get("matchedCount", 0)}/{result.get("totalCount", 0)}명 매칭)',
            )
        else:
            messages.error(request, f'"{event.name}": 점수 시트 반영 실패 — {result.get("message")}')


def _first_selected_event(request, queryset, action_label: str) -> Event | None:
    """내보내기 액션들이 전부 "회차 하나만" 대상으로 동작하는데, 관리자
    화면에서는 여러 개를 체크박스로 선택할 수 있다 — 그럴 때 첫 번째로
    선택한 회차만 쓰고, 나머지는 무시됐다는 걸 경고로 알려준다 (#30: 다섯
    액션에 거의 똑같이 반복되던 패턴을 하나로 모음).

    선택된 회차가 하나도 없으면(예: 페이지를 열어둔 사이 다른 사람이 그
    회차를 삭제한 경우) None을 반환한다 — 호출하는 쪽에서 반드시 None
    체크를 해야 한다. 원래는 이 경우를 확인하지 않아서 바로 다음 줄의
    event.name 등에서 AttributeError로 500이 났었다."""
    event = queryset.first()
    if event is None:
        messages.error(request, f"{action_label}: 선택한 회차를 찾을 수 없습니다 — 이미 삭제됐을 수 있습니다.")
        return None
    if queryset.count() > 1:
        messages.warning(
            request, f"{action_label}은 한 번에 회차 하나씩만 가능합니다. 첫 번째로 선택한 회차만 내려받습니다."
        )
    return event


def _xlsx_response(filename: str, content: bytes) -> HttpResponse:
    response = HttpResponse(
        content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response.headers["Content-Disposition"] = content_disposition_header(as_attachment=True, filename=filename)
    return response


@admin.action(description="선택 회차: 참가자 CSV 백업 다운로드 (마스킹 없음, 운영진 전용)")
def export_event_csv(modeladmin, request, queryset):
    # 이름/연락처를 마스킹 없이 그대로 내보내는 액션이라, export_score_sheet_excel(#28)과
    # 동일하게 checkin.export_sensitive_data 권한이 있는 사람(슈퍼유저 또는 "운영진"
    # 그룹)만 실행할 수 있게 제한한다. get_actions에서 권한 없는 사람에게는
    # 드롭다운에서 아예 안 보이게 숨기지만, 직접 폼을 조작해서 요청을 보내는
    # 경우까지 막으려고 여기서도 한 번 더 확인한다.
    if not request.user.has_perm("checkin.export_sensitive_data"):
        messages.error(request, "CSV 백업 다운로드는 운영진만 실행할 수 있습니다.")
        return

    event = _first_selected_event(request, queryset, "CSV 백업")
    if event is None:
        return

    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response.headers["Content-Disposition"] = content_disposition_header(
        as_attachment=True, filename=f"{event.name}_backup.csv"
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "이름", "연락처", "구분", "장르", "학교", "학적", "입금자명",
            "학적검수", "입금상태", "라벨코드", "체크인상태", "체크인시각", "신청시각",
        ]
    )
    for p in event.participants.all().order_by("created_at"):
        writer.writerow(
            [
                p.name, p.phone, p.entry_type, p.genre or "", p.school or "", p.academic_status or "",
                p.payer_name or "",
                p.verification_status, p.payment_status, p.label_code or "",
                p.checkin_status, p.checked_in_at or "", p.created_at,
            ]
        )
    return response


@admin.action(description="선택 회차: QR 발송용 명단 다운로드 (문자/카톡 대량발송 도구용)")
def export_qr_send_list(modeladmin, request, queryset):
    # 연락처 + 개인별 QR 링크를 그대로 담는 액션이라 CSV 백업/점수표와 동일하게
    # 운영진 전용으로 제한한다.
    if not request.user.has_perm("checkin.export_sensitive_data"):
        messages.error(request, "QR 발송용 명단 다운로드는 운영진만 실행할 수 있습니다.")
        return

    event = _first_selected_event(request, queryset, "QR 발송용 명단")
    if event is None:
        return

    participants = list(event.participants.filter(qr_token__isnull=False).order_by("entry_type", "genre", "created_at"))
    skipped = event.participants.filter(qr_token__isnull=True).count()
    if skipped:
        messages.warning(
            request,
            f'"{event.name}": 아직 QR이 발급되지 않은 참가자 {skipped}명은 명단에서 제외했습니다 '
            '(먼저 "선택 회차: 승인자 라벨/QR 발급 실행"을 실행해주세요).',
        )

    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response.headers["Content-Disposition"] = content_disposition_header(
        as_attachment=True, filename=f"{event.name}_QR발송명단.csv"
    )
    writer = csv.writer(response)
    writer.writerow(["이름", "연락처", "구분", "장르", "QR 링크", "안내 문구"])
    for p in participants:
        qr_url = request.build_absolute_uri(reverse("checkin:qr", args=[p.qr_token]))
        real_name = p.name.split("/")[0]
        message = f"[{event.name}] {real_name}님, 아래 링크에서 입장용 QR을 확인해주세요.\n{qr_url}"
        writer.writerow([real_name, p.phone, p.entry_type, p.genre or "", qr_url, message])
    return response


def _has_duplicate_labels(request, event) -> bool:
    """라벨 코드 중복이 있으면 관리자 화면에 에러로 알리고 True를 반환.
    (수동으로 label_group/label_number를 조정하다가 겹치는 경우 대비 —
    보통은 DB 제약이 막아주지만, 그걸로 못 잡는 경우까지 한 번 더 확인.)"""
    problems = find_duplicate_labels(event)
    if problems:
        messages.error(
            request,
            f'"{event.name}": 라벨 코드가 중복 배정된 참가자가 있어 다운로드를 중단했습니다 — ' + " / ".join(problems),
        )
    return bool(problems)


@admin.action(description="선택 회차: 공지용 명단 엑셀 다운로드 (이름/연락처 마스킹)")
def export_announcement_excel(modeladmin, request, queryset):
    event = _first_selected_event(request, queryset, "공지용 명단")
    if event is None:
        return
    if _has_duplicate_labels(request, event):
        return
    return _xlsx_response(*build_announcement_file(event))


@admin.action(description="선택 회차: 점수표 엑셀 다운로드 (마스킹 없음, 운영진 전용)")
def export_score_sheet_excel(modeladmin, request, queryset):
    # 이름/연락처를 마스킹 없이 그대로 내보내는 액션이라, checkin.export_sensitive_data
    # 권한이 있는 사람(슈퍼유저 또는 "운영진" 그룹)만 실행할 수 있게 제한한다 (#28).
    # get_actions에서 권한 없는 사람에게는 드롭다운에서 아예 안 보이게 숨기지만,
    # 직접 폼을 조작해서 요청을 보내는 경우까지 막으려고 여기서도 한 번 더 확인한다.
    if not request.user.has_perm("checkin.export_sensitive_data"):
        messages.error(request, "점수표 다운로드는 운영진만 실행할 수 있습니다.")
        return

    event = _first_selected_event(request, queryset, "점수표")
    if event is None:
        return
    if _has_duplicate_labels(request, event):
        return
    return _xlsx_response(*build_score_sheet_file(event))


@admin.action(description="선택 회차: 신청 참가자 확인용 공지 엑셀 다운로드 (라벨 배정 전에도 가능)")
def export_application_confirmation_excel(modeladmin, request, queryset):
    event = _first_selected_event(request, queryset, "신청 확인용 명단")
    if event is None:
        return
    return _xlsx_response(*build_application_confirmation_file(event))


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("name", "volume", "is_active_badge", "participant_count", "created_at")
    list_filter = (ActiveFilter,)
    ordering = ("-volume",)
    actions = [
        run_label_assign,
        push_order_to_sheet,
        export_event_csv,
        export_qr_send_list,
        export_application_confirmation_excel,
        export_announcement_excel,
        export_score_sheet_excel,
    ]

    @admin.display(description="활성 여부", ordering="is_active")
    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span class="dbbt-badge dbbt-badge-ok">활성</span>')
        return format_html('<span class="dbbt-badge dbbt-badge-neutral">비활성</span>')

    @admin.display(description="신청자 수")
    def participant_count(self, obj):
        return f'{obj.participants.count()}명'

    @admin.display(description="신청자 수")
    def participant_count_display(self, obj):
        return f'{obj.participants.count()}명' if obj and obj.pk else "—"

    def get_fieldsets(self, request, obj=None):
        base = ("기본 정보", {"fields": ("volume", "name", "event_date", "sheet_sync_url", "location", "is_active")})
        if obj is None:
            return (base,)
        return (
            base,
            ("현황", {"fields": ("participant_count_display", "created_at")}),
        )

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return ("participant_count_display", "created_at")

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.has_perm("checkin.export_sensitive_data"):
            actions.pop("export_score_sheet_excel", None)
            actions.pop("export_event_csv", None)
            actions.pop("export_qr_send_list", None)
        return actions

    def delete_queryset(self, request, queryset):
        for event in queryset:
            messages.info(
                request,
                f'"{event.name}" 데이터를 삭제했습니다 (참가자 {event.participants.count()}명 포함). '
                "삭제 전 CSV 백업을 받아두지 않았다면 복구할 수 없습니다.",
            )
        super().delete_queryset(request, queryset)


@admin.action(description="선택 참가자: 학적검수 승인 처리 (APPROVED)")
def approve_verification(modeladmin, request, queryset):
    updated = queryset.filter(entry_type="참가").update(verification_status="APPROVED")
    messages.success(request, f"{updated}명 학적검수 승인 처리했습니다.")


@admin.action(description="선택 참가자: 입금 확인 처리 (PAID)")
def mark_paid(modeladmin, request, queryset):
    updated = queryset.update(payment_status="PAID")
    messages.success(request, f"{updated}명 입금 확인 처리했습니다.")


@admin.action(description="선택 참가자: 입금 완료 → 환불 처리")
def mark_refund(modeladmin, request, queryset):
    # 입금 완료(PAID) 상태인 사람만 환불 대상으로 삼는다 — 대기/환불 상태인
    # 사람까지 같이 선택했더라도 실수로 잘못 바뀌지 않게.
    # 이미 라벨/QR이 발급된 사람이 나중에 환불되는 경우까지 대비해, 환불 시
    # 발급된 라벨·QR도 같이 회수한다(안 그러면 환불 후에도 기존 QR로 체크인이
    # 가능하게 남아있음). assign_labels_and_tokens()는 이미 payment_status가
    # PAID인 사람에게만 새로 발급하므로, 환불된 사람은 이후 재실행에서도
    # 다시 발급되지 않는다.
    updated = queryset.filter(payment_status="PAID").update(
        payment_status="REFUND",
        label_group=None, label_number=None, label_code=None,
        qr_token=None, qr_sent_at=None,
    )
    messages.success(request, f"{updated}명 환불 처리했습니다 (발급된 라벨/QR도 함께 회수했습니다).")


@admin.action(description="선택한 참가자 2명의 라벨(조/번호) 맞바꾸기")
def swap_labels(modeladmin, request, queryset):
    if queryset.count() != 2:
        messages.error(request, "라벨을 맞바꾸려면 참가자를 정확히 2명 선택해야 합니다.")
        return

    a, b = list(queryset)
    if a.event_id != b.event_id or a.genre != b.genre:
        messages.error(request, "같은 회차·같은 장르의 참가자끼리만 라벨을 맞바꿀 수 있습니다.")
        return
    if not a.label_code or not b.label_code:
        messages.error(request, "두 참가자 모두 라벨이 배정되어 있어야 맞바꿀 수 있습니다.")
        return

    a_group, a_number = a.label_group, a.label_number
    b_group, b_number = b.label_group, b.label_number

    # label_slot_unique 제약은 즉시 검사라, 둘을 그냥 순서대로 서로의 자리로
    # 옮기면 중간에 반드시 한 번은 자리가 겹쳐서 IntegrityError가 난다. A를
    # 먼저 완전히 비워서(=제약 검사 대상에서 제외) B가 그 빈자리로 옮긴 뒤,
    # A를 B가 떠나서 빈 자리로 옮기는 3단계로 나누면 매 순간 충돌이 없다.
    with transaction.atomic():
        a.label_group, a.label_number = None, None
        a.save()
        b.label_group, b.label_number = a_group, a_number
        b.save()
        a.label_group, a.label_number = b_group, b_number
        a.save()

    messages.success(request, f"{a.name}({a.label_code}) ↔ {b.name}({b.label_code}) 라벨을 맞바꿨습니다.")


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = (
        "name", "phone", "school", "academic_status", "event", "entry_type", "genre",
        "verification_status_badge", "payment_status_badge", "payer_name", "label_code_display",
        "checkin_status_badge",
    )
    list_filter = ("event", "entry_type", VerificationFilter, PaymentFilter, CheckinFilter, GenreFilter)
    search_fields = ("name", "phone", "school")
    actions = [approve_verification, mark_paid, swap_labels, mark_refund]
    # label_code는 save()에서 항상 label_group/label_number로부터 다시 계산되므로
    # (models.py 참고) 폼에서 직접 수정할 수 있게 두면 값이 저장돼도 무시되어
    # 혼란만 준다 — 목업(ParticipantDetailClean)도 이 필드를 읽기 전용으로 보여준다.
    readonly_fields = ("id", "qr_link_display", "created_at", "label_code")

    def changelist_view(self, request, extra_context=None):
        # ParticipantsClean 목업 상단의 통계 타일(총 신청/학적검수 대기/입금 대기/
        # 체크인 완료)이 보여줄 "기준 회차"를 정한다: 화면에 회차 필터가 걸려있으면
        # 그 회차를, 아니면 활성 회차를, 그것도 없으면(예: 아직 아무 회차도
        # 활성화한 적이 없는 상태) 가장 최근 회차를 쓴다 — 활성 회차가 없다고
        # 통계 타일 자체가 통째로 사라지면 화면이 목업과 달라 보이고 헷갈린다.
        extra_context = extra_context or {}
        target_event = None
        event_filter_value = request.GET.get("event__id__exact")
        if event_filter_value:
            target_event = Event.objects.filter(pk=event_filter_value).first()
        if target_event is None:
            target_event = Event.objects.filter(is_active=True).first()
        if target_event is None:
            target_event = Event.objects.order_by("-volume").first()

        if target_event is not None:
            participants = target_event.participants
            extra_context["dbbt_active_event"] = target_event
            # 4번 따로 .count()를 부르면 매번 새 쿼리가 나간다 — 하나의
            # aggregate()로 묶어서 이 화면을 열 때마다(페이지 이동/필터/검색
            # 시마다) 쿼리 4개 대신 1개만 나가게 한다.
            stats = participants.aggregate(
                total=Count("id"),
                pending_verification=Count("id", filter=Q(verification_status="PENDING")),
                pending_payment=Count("id", filter=Q(payment_status="PENDING")),
                checked_in=Count("id", filter=Q(checkin_status="CHECKED_IN")),
            )
            extra_context["dbbt_stat_total"] = stats["total"]
            extra_context["dbbt_stat_pending_verification"] = stats["pending_verification"]
            extra_context["dbbt_stat_pending_payment"] = stats["pending_payment"]
            extra_context["dbbt_stat_checked_in"] = stats["checked_in"]
        return super().changelist_view(request, extra_context=extra_context)

    _STATUS_BADGE_CLASS = {
        "APPROVED": "ok", "PAID": "ok", "CHECKED_IN": "ok",
        "PENDING": "warn",
        "REJECTED": "bad", "REFUND": "bad",
        "N_A": "neutral", "NOT_CHECKED_IN": "neutral",
    }

    def _status_badge(self, value, label):
        css = self._STATUS_BADGE_CLASS.get(value, "neutral")
        return format_html('<span class="dbbt-badge dbbt-badge-{}">{}</span>', css, label)

    @admin.display(description="학적검수", ordering="verification_status")
    def verification_status_badge(self, obj):
        return self._status_badge(obj.verification_status, obj.get_verification_status_display())

    @admin.display(description="입금", ordering="payment_status")
    def payment_status_badge(self, obj):
        return self._status_badge(obj.payment_status, obj.get_payment_status_display())

    @admin.display(description="체크인", ordering="checkin_status")
    def checkin_status_badge(self, obj):
        return self._status_badge(obj.checkin_status, obj.get_checkin_status_display())

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # label_code("A-10")를 그대로 정렬하면 문자열 비교라 "A-10"이 "A-2"보다
        # 앞에 와버림. label_number를 0으로 채운 문자열로 만들어 정렬 전용
        # 컬럼으로 붙여서, group+번호 순으로 정렬되게 한다.
        return qs.annotate(
            _label_sort=Concat(
                "label_group",
                LPad(Cast("label_number", CharField()), 2, Value("0")),
                output_field=CharField(),
            )
        )

    @admin.display(description="라벨 코드", ordering="_label_sort")
    def label_code_display(self, obj):
        return obj.label_code

    @admin.display(description="QR 링크")
    def qr_link_display(self, obj):
        if not obj.qr_token:
            return "-"
        # ModelAdmin의 readonly 필드 렌더 메서드는 request를 받지 못해서 절대
        # URL(도메인 포함)을 여기서 직접 만들 수 없다 — 상대 경로만 만들어두고,
        # 실제 도메인은 base_site.html의 스크립트가 location.origin으로 채운다
        # (그래야 로컬/스테이징/운영 어디서 봐도 지금 접속한 도메인 기준으로 나온다).
        path = reverse("checkin:qr", args=[obj.qr_token])
        return format_html(
            '<div class="dbbt-copy-row">'
            '<code class="dbbt-copy-text" data-copy-path="{}"></code>'
            '<button type="button" class="dbbt-copy-btn" title="링크 복사">'
            '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
            '<rect x="9" y="9" width="13" height="13" rx="2"/>'
            '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'
            "</svg>"
            "</button>"
            "</div>",
            path,
        )

    def get_fieldsets(self, request, obj=None):
        base = (
            ("기본 정보", {"fields": ("event", "entry_type", "name", "phone")}),
            ("신청 정보", {"fields": ("school", "academic_status", "genre", "payer_name", "external_ref")}),
            ("검수", {"fields": ("verification_status", "payment_status")}),
        )
        if obj is None:
            # 저장 전에는 라벨/QR/체크인 영역이 아직 존재하지 않는다 — 회차 관리의
            # "라벨 / QR 발급 실행"에서 일괄 배정되기 때문 (assign_labels_and_tokens).
            return base
        return base + (
            ("라벨", {"fields": ("label_group", "label_number", "label_code")}),
            ("QR / 체크인", {"fields": ("qr_link_display", "qr_sent_at", "checkin_status", "checked_in_at")}),
            ("기타", {"fields": ("id", "created_at")}),
        )
