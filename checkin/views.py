import json
import re
import uuid

import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import IntegrityError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .forms import RegisterForm
from .models import Event, Participant
from .services import sheet_sync

UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def home(request):
    active_event = Event.objects.filter(is_active=True).first()
    return render(request, "checkin/home.html", {"event": active_event})


# --------------------------------------------------------------------------
# 신청 폼 (구글 폼을 안 쓸 경우를 위한 예비 경로)
# --------------------------------------------------------------------------
def register_view(request):
    active_event = Event.objects.filter(is_active=True).first()
    if not active_event:
        return render(request, "checkin/register.html", {"no_active_event": True})

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            participant = form.save(commit=False)
            participant.event = active_event
            if participant.entry_type != "참가":
                participant.genre = None
            participant.verification_status = "N_A" if participant.entry_type == "관람" else "PENDING"
            participant.payment_status = "PENDING"
            participant.save()
            return render(request, "checkin/register.html", {"success": True, "event": active_event})
    else:
        form = RegisterForm()

    return render(request, "checkin/register.html", {"form": form, "event": active_event})


# --------------------------------------------------------------------------
# 개인 QR 확인 페이지
# --------------------------------------------------------------------------
def qr_view(request, token):
    participant = Participant.objects.filter(qr_token=token).first()
    if not participant:
        return render(request, "checkin/qr.html", {"not_found": True})

    protocol = "http" if "localhost" in request.get_host() or "127.0.0.1" in request.get_host() else "https"
    # QR에는 /checkin/scan/<token>/ 링크를 그대로 넣습니다. 우리 앱의 카메라 스캐너뿐
    # 아니라, 스태프가 각자 쓰는 아무 QR 인식 앱으로 찍어도 이 주소가 바로 열립니다
    # (checkin:scan 뷰 참고 — 참가자 정보를 보여주는 "팝업" 역할).
    payload = f"{protocol}://{request.get_host()}{reverse('checkin:scan', args=[participant.qr_token])}"

    img = qrcode.make(payload, box_size=8, border=2)
    import base64
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    return render(
        request,
        "checkin/qr.html",
        {"participant": participant, "qr_data_url": qr_data_url},
    )


# --------------------------------------------------------------------------
# 아무 QR 인식 앱으로 스캔해도 열리는 공개 확인 페이지 ("팝업" 역할).
# 정보는 로그인 없이 누구나 볼 수 있지만, 실제 체크인 확정(scan_confirm)은
# 스태프 로그인이 있어야만 가능합니다 — 참가자 본인이나 제3자가 QR을 먼저
# 열어봐도 그것만으로 체크인되지 않도록 하기 위한 설계입니다.
# --------------------------------------------------------------------------
def scan_view(request, token):
    participant = Participant.objects.filter(qr_token=token).first()
    if not participant:
        return render(request, "checkin/scan.html", {"not_found": True})
    return render(request, "checkin/scan.html", {"participant": participant})


@require_POST
def scan_confirm(request, token):
    if not (request.user.is_authenticated and request.user.is_staff):
        # @staff_member_required가 기본으로 하는 것처럼 로그인 화면으로 보내되,
        # next는 이 POST 액션 자체가 아니라 GET인 scan_view로 잡는다 — POST
        # 액션으로 next를 잡으면 로그인 후 리다이렉트가 GET으로 재요청되면서
        # require_POST에 막혀 405가 나기 때문. 그 대신 로그인 후에는 확인
        # 화면으로 돌아가서 "체크인 확정" 버튼을 다시 눌러야 한다.
        login_url = f"{reverse('admin:login')}?next={reverse('checkin:scan', args=[token])}"
        return redirect(login_url)

    participant = get_object_or_404(Participant, qr_token=token)
    if participant.checkin_status != "CHECKED_IN":
        _mark_checked_in(participant)
        messages.success(request, f"{participant.name}님 체크인을 확정했습니다.")
    else:
        messages.info(request, f"{participant.name}님은 이미 체크인되어 있습니다.")
    return redirect("checkin:scan", token=token)


def _mark_checked_in(participant: Participant) -> None:
    participant.checkin_status = "CHECKED_IN"
    participant.checked_in_at = timezone.now()
    participant.save(update_fields=["checkin_status", "checked_in_at"])
    sheet_sync.push_arrival(participant)


# --------------------------------------------------------------------------
# 현장 체크인 스캐너 (스태프 로그인 필요 — Django 인증 그대로 사용)
# --------------------------------------------------------------------------
@staff_member_required
def checkin_view(request):
    active_event = Event.objects.filter(is_active=True).first()
    return render(request, "checkin/checkin.html", {"event": active_event})


def _extract_token(text: str) -> str | None:
    m = UUID_RE.search(text or "")
    return m.group(0) if m else None


@staff_member_required
@require_POST
def qr_lookup_api(request):
    """QR을 조회만 하고 체크인 처리는 하지 않음 — 스태프가 화면에서 참가자 정보를
    확인하고 "체크인 확정" 버튼을 눌러야 manual_checkin_api가 실제로 체크인시킴.
    """
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        body = {}
    token = _extract_token(str(body.get("text", "")))

    participant = None
    if token:
        try:
            participant = Participant.objects.filter(qr_token=uuid.UUID(token)).first()
        except ValueError:
            participant = None

    if not participant:
        return JsonResponse({"status": "NOT_FOUND", "message": "등록되지 않은 QR입니다."})

    return JsonResponse({"status": "FOUND", "data": _participant_dto(participant)})


@staff_member_required
@require_GET
def participant_search_api(request):
    q = request.GET.get("q", "").strip()
    active_event = Event.objects.filter(is_active=True).first()
    if not q or not active_event:
        return JsonResponse({"results": []})
    rows = Participant.objects.filter(event=active_event).filter(
        Q(name__icontains=q) | Q(phone__icontains=q)
    )[:20]
    return JsonResponse({"results": [_participant_dto(p) for p in rows]})


@staff_member_required
@require_POST
def manual_checkin_api(request, participant_id):
    participant = get_object_or_404(Participant, pk=participant_id)
    # scan_confirm과 마찬가지로 이미 체크인된 사람은 다시 마킹하지 않는다 —
    # 안 그러면 최초 도착 시각이 나중에 눌린 시각으로 덮어써진다 (#19).
    if participant.checkin_status != "CHECKED_IN":
        _mark_checked_in(participant)
    return JsonResponse({"status": "success", "data": _participant_dto(participant)})


def _participant_dto(p: Participant) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "phone": p.phone,
        "entryType": p.entry_type,
        "genre": p.genre,
        "school": p.school,
        "labelCode": p.label_code,
        "checkinStatus": p.checkin_status,
    }


# --------------------------------------------------------------------------
# 기존 구글 폼 연동 — Forwarder.gs가 새 응답/백필을 이 endpoint로 보냅니다.
# --------------------------------------------------------------------------
@csrf_exempt
@require_POST
def google_form_import(request):
    secret = request.headers.get("X-Import-Secret")
    if not settings.IMPORT_SECRET:
        return JsonResponse(
            {"error": "서버에 IMPORT_SECRET이 설정되어 있지 않습니다. .env를 확인해주세요."}, status=500
        )
    if secret != settings.IMPORT_SECRET:
        return JsonResponse({"error": "인증 실패 (X-Import-Secret 불일치)"}, status=401)

    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "잘못된 JSON입니다."}, status=400)

    rows = body.get("rows") or []

    active_event = Event.objects.filter(is_active=True).first()
    if not active_event:
        return JsonResponse({"error": "활성 회차가 없습니다. /admin에서 회차를 먼저 만들어주세요."}, status=400)

    if not rows:
        # 연결 테스트: 실제 저장 없이 인증/활성회차 확인만.
        return JsonResponse(
            {"ok": True, "eventId": str(active_event.id), "imported": 0, "skipped": 0, "errors": []}
        )

    imported = 0
    skipped = 0
    errors = []

    for row in rows:
        external_ref = str(row.get("externalRef") or "").strip()
        if not external_ref:
            errors.append({"externalRef": row.get("externalRef"), "message": "externalRef 없음"})
            continue

        if Participant.objects.filter(event=active_event, external_ref=external_ref).exists():
            skipped += 1
            continue

        name = (row.get("name") or "").strip()
        phone = (row.get("phone") or "").strip()
        if not name or not phone:
            errors.append({"externalRef": external_ref, "message": "이름 또는 연락처 누락"})
            continue

        entry_type = "관람" if "관람" in (row.get("type") or "참가") else "참가"
        school = (row.get("school") or "").strip() or None
        academic_status = (row.get("academicStatus") or "").strip() or None
        genre = (row.get("genre") or "").strip() or None
        if entry_type != "참가":
            genre = None

        try:
            Participant.objects.create(
                event=active_event,
                external_ref=external_ref,
                entry_type=entry_type,
                name=name,
                phone=phone,
                school=school,
                academic_status=academic_status,
                genre=genre,
                payer_name=(row.get("payerName") or "").strip() or None,
                # 폼의 "입금확인" 체크 여부와 무관하게 항상 PENDING에서 시작합니다.
                # 실제 확인은 운영진이 /admin에서 합니다 (예전 Apps Script 버전과 동일한 정책).
                verification_status="N_A" if entry_type == "관람" else "PENDING",
                payment_status="PENDING",
                checkin_status="NOT_CHECKED_IN",
            )
        except IntegrityError:
            # 위의 .exists() 체크와 여기 create() 사이에 동시 요청이 끼어들어
            # 같은 external_ref로 먼저 저장된 경우 — 원래 의도(멱등하게 건너뛰기)
            # 그대로 skipped로 처리한다 (#20).
            skipped += 1
            continue
        imported += 1

    return JsonResponse(
        {"eventId": str(active_event.id), "imported": imported, "skipped": skipped, "errors": errors}
    )
