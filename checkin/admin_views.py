from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils import timezone
from django_otp import devices_for_user
from django_otp.plugins.otp_totp.models import TOTPDevice

from .otp import totp_qr_data_url

OPERATIONS_GROUP_NAME = "운영진"


def _account_row(user):
    if user.is_superuser:
        tier, tier_label = "super", "슈퍼유저"
    # .filter()/.exists()는 related manager의 prefetch_related 캐시를 안 쓰고
    # 매번 새 쿼리를 날린다 — accounts_dashboard가 groups를 prefetch해줘도
    # 여기서 .filter()를 쓰면 그 캐시를 무시하고 계정 수만큼 쿼리가 나가서
    # (N+1) prefetch가 무용지물이 된다. 이미 메모리에 올라온 user.groups.all()을
    # 순회하면 캐시를 그대로 쓴다.
    elif any(g.name == OPERATIONS_GROUP_NAME for g in user.groups.all()):
        tier, tier_label = "op", "운영진"
    else:
        tier, tier_label = "staff", "스태프"

    if not user.is_active:
        status, status_label = "inactive", "비활성"
    elif user.last_login is None:
        status, status_label = "invited", "초대됨"
    else:
        status, status_label = "active", "활성"

    return {
        "user": user,
        "tier": tier,
        "tier_label": tier_label,
        "status": status,
        "status_label": status_label,
    }


# 계정 관리 화면은 슈퍼유저 전용 — 스태프/운영진 계정을 만들고 권한(그룹)을
# 배정하는 화면이라, 운영진에게까지 열어두면 스스로 슈퍼유저 계정을 만들 수
# 있게 되어버린다 (staff_member_required는 is_staff만 확인하므로 그 위에
# is_superuser도 한 번 더 확인한다).
@staff_member_required
def accounts_dashboard(request):
    if not request.user.is_superuser:
        raise PermissionDenied("계정 관리는 슈퍼유저만 접근할 수 있습니다.")

    User = get_user_model()
    users = User.objects.filter(is_staff=True).prefetch_related("groups").order_by("-is_superuser", "-date_joined")
    rows = sorted(
        (_account_row(u) for u in users),
        key=lambda row: {"super": 0, "op": 1, "staff": 2}[row["tier"]],
    )

    return render(
        request,
        "admin/accounts_dashboard.html",
        {
            **{"title": "계정 관리", "admin_tab": "accounts", "site_header": "DBBT STAFF"},
            "rows": rows,
            "now": timezone.now(),
        },
    )


# 본인 계정의 2단계 인증(TOTP)을 스스로 켜고 끄는 화면 (SEC-03). 계정 관리
# (다른 사람 계정을 다루는 화면, 슈퍼유저 전용)와는 별개로, 로그인한 사람
# 누구나(스태프 포함) 자기 계정에 대해서만 쓸 수 있다 — 켜고 끄는 것 자체가
# 이미 로그인된 상태에서만 가능해서, 스스로 껐다 켰다 하는 걸 막을 이유가
# 없다(공격자가 이미 그 계정에 로그인해 있다면 2단계 인증 여부와 무관하게
# 이미 뚫린 상태).
@staff_member_required
def otp_setup(request):
    user = request.user
    confirmed_devices = list(devices_for_user(user, confirmed=True))

    if confirmed_devices:
        if request.method == "POST" and request.POST.get("action") == "disable":
            for device in confirmed_devices:
                device.delete()
            messages.success(request, "2단계 인증을 껐습니다. 다음 로그인부터는 비밀번호만으로 접속됩니다.")
            return redirect("otp_setup")
        return render(request, "admin/otp_setup.html", {"title": "2단계 인증", "enabled": True})

    # 아직 미확인 상태인 기기가 있으면(직전 시도에서 코드를 틀렸거나 중간에
    # 이탈) 새로 안 만들고 그대로 재사용한다 — 매번 새로 만들면 키가 바뀌어서
    # 이미 인증 앱에 등록해둔 QR/코드가 무효가 되어버린다.
    device = TOTPDevice.objects.filter(user=user, confirmed=False).order_by("-id").first()
    if device is None:
        device = TOTPDevice.objects.create(user=user, confirmed=False, name="기본")

    if request.method == "POST":
        if request.POST.get("action") == "reset":
            device.delete()
            return redirect("otp_setup")

        token = (request.POST.get("token") or "").strip()
        if device.verify_token(token):
            device.confirmed = True
            device.save(update_fields=["confirmed"])
            messages.success(request, "2단계 인증을 설정했습니다. 다음 로그인부터 인증 코드를 입력해야 합니다.")
            return redirect("otp_setup")
        messages.error(request, "인증 코드가 올바르지 않습니다. 인증 앱에 뜬 숫자를 다시 확인해주세요.")

    return render(
        request,
        "admin/otp_setup.html",
        {
            "title": "2단계 인증",
            "enabled": False,
            "qr_data_url": totp_qr_data_url(device),
            "manual_key": device.key,
        },
    )
