import csv

from django.contrib import admin, messages
from django.db import transaction
from django.db.models import CharField, Value
from django.db.models.functions import Cast, Concat, LPad
from django.http import HttpResponse
from django.utils.http import content_disposition_header

from .models import Event, Participant
from .services import sheet_sync
from .services.announcement_export import build_announcement_file, find_duplicate_labels
from .services.application_confirmation_export import build_application_confirmation_file
from .services.assign_labels import assign_labels_and_tokens
from .services.score_sheet_export import build_score_sheet_file


@admin.action(description="④ 선택 회차: 승인자 라벨/QR 발급 실행")
def run_label_assign(modeladmin, request, queryset):
    for event in queryset:
        result = assign_labels_and_tokens(event)
        messages.success(
            request,
            f'"{event.name}": 라벨 신규 배정 {result["labeled"]}명 / QR 신규 발급 {result["issued"]}명',
        )


@admin.action(description="⑤ 선택 회차: 라벨 순서를 점수 시트에 반영")
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


@admin.action(description="선택 회차: 참가자 CSV 백업 다운로드")
def export_event_csv(modeladmin, request, queryset):
    event = queryset.first()
    if queryset.count() > 1:
        messages.warning(request, "CSV 백업은 한 번에 회차 하나씩만 가능합니다. 첫 번째로 선택한 회차만 내려받습니다.")

    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response.headers["Content-Disposition"] = content_disposition_header(
        as_attachment=True, filename=f"{event.name}_backup.csv"
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "이름", "연락처", "구분", "장르", "학교", "학적", "이메일", "입금자명",
            "학적검수", "입금상태", "라벨코드", "체크인상태", "체크인시각", "신청시각",
        ]
    )
    for p in event.participants.all().order_by("created_at"):
        writer.writerow(
            [
                p.name, p.phone, p.entry_type, p.genre or "", p.school or "", p.academic_status or "",
                p.email or "", p.payer_name or "",
                p.verification_status, p.payment_status, p.label_code or "",
                p.checkin_status, p.checked_in_at or "", p.created_at,
            ]
        )
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
    event = queryset.first()
    if queryset.count() > 1:
        messages.warning(request, "공지용 명단은 한 번에 회차 하나씩만 가능합니다. 첫 번째로 선택한 회차만 내려받습니다.")
    if _has_duplicate_labels(request, event):
        return

    filename, content = build_announcement_file(event)
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response.headers["Content-Disposition"] = content_disposition_header(
        as_attachment=True, filename=filename
    )
    return response


@admin.action(description="선택 회차: 점수표 엑셀 다운로드 (마스킹 없음, 스태프 내부용)")
def export_score_sheet_excel(modeladmin, request, queryset):
    event = queryset.first()
    if queryset.count() > 1:
        messages.warning(request, "점수표는 한 번에 회차 하나씩만 가능합니다. 첫 번째로 선택한 회차만 내려받습니다.")
    if _has_duplicate_labels(request, event):
        return

    filename, content = build_score_sheet_file(event)
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response.headers["Content-Disposition"] = content_disposition_header(
        as_attachment=True, filename=filename
    )
    return response


@admin.action(description="선택 회차: 신청 참가자 확인용 공지 엑셀 다운로드 (라벨 배정 전에도 가능)")
def export_application_confirmation_excel(modeladmin, request, queryset):
    event = queryset.first()
    if queryset.count() > 1:
        messages.warning(request, "신청 확인용 명단은 한 번에 회차 하나씩만 가능합니다. 첫 번째로 선택한 회차만 내려받습니다.")

    filename, content = build_application_confirmation_file(event)
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response.headers["Content-Disposition"] = content_disposition_header(
        as_attachment=True, filename=filename
    )
    return response


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("name", "volume", "is_active", "participant_count", "created_at")
    list_filter = ("is_active",)
    ordering = ("-volume",)
    actions = [
        run_label_assign,
        push_order_to_sheet,
        export_event_csv,
        export_application_confirmation_excel,
        export_announcement_excel,
        export_score_sheet_excel,
    ]

    @admin.display(description="신청자 수")
    def participant_count(self, obj):
        return obj.participants.count()

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
        "verification_status", "payment_status", "label_code_display", "checkin_status",
    )
    list_filter = ("event", "entry_type", "verification_status", "payment_status", "checkin_status", "genre")
    search_fields = ("name", "phone", "email", "school")
    actions = [approve_verification, mark_paid, swap_labels]
    readonly_fields = ("id", "qr_token", "created_at")

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

    @admin.display(description="Label code", ordering="_label_sort")
    def label_code_display(self, obj):
        return obj.label_code

    fieldsets = (
        (None, {"fields": ("event", "entry_type", "name", "phone", "email")}),
        ("신청 정보", {"fields": ("school", "academic_status", "genre", "payer_name", "external_ref")}),
        ("검수", {"fields": ("verification_status", "payment_status")}),
        (
            "라벨",
            {"fields": ("label_group", "label_number", "label_code", "label_manual_override")},
        ),
        ("QR / 체크인", {"fields": ("qr_token", "qr_sent_at", "checkin_status", "checked_in_at")}),
        ("기타", {"fields": ("id", "created_at")}),
    )
