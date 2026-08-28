import csv

from django.contrib import admin, messages
from django.db.models import CharField, Value
from django.db.models.functions import Cast, Concat, LPad
from django.http import HttpResponse

from .models import Event, Participant
from .services.assign_labels import assign_labels_and_tokens


@admin.action(description="④ 선택 회차: 승인자 라벨/QR 발급 실행")
def run_label_assign(modeladmin, request, queryset):
    for event in queryset:
        result = assign_labels_and_tokens(event)
        messages.success(
            request,
            f'"{event.name}": 라벨 신규 배정 {result["labeled"]}명 / QR 신규 발급 {result["issued"]}명',
        )


@admin.action(description="선택 회차: 참가자 CSV 백업 다운로드")
def export_event_csv(modeladmin, request, queryset):
    event = queryset.first()
    if queryset.count() > 1:
        messages.warning(request, "CSV 백업은 한 번에 회차 하나씩만 가능합니다. 첫 번째로 선택한 회차만 내려받습니다.")

    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = f'attachment; filename="{event.name}_backup.csv"'
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


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("name", "volume", "is_active", "participant_count", "created_at")
    list_filter = ("is_active",)
    ordering = ("-volume",)
    actions = [run_label_assign, export_event_csv]

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


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = (
        "name", "event", "entry_type", "genre", "verification_status",
        "payment_status", "label_code_display", "checkin_status",
    )
    list_filter = ("event", "entry_type", "verification_status", "payment_status", "checkin_status", "genre")
    search_fields = ("name", "phone", "email")
    actions = [approve_verification, mark_paid]
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
