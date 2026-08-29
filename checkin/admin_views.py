from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils import timezone

OPERATIONS_GROUP_NAME = "운영진"


def _account_row(user):
    if user.is_superuser:
        tier, tier_label = "super", "슈퍼유저"
    elif user.groups.filter(name=OPERATIONS_GROUP_NAME).exists():
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
