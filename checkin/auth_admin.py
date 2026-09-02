"""계정 관리 → 계정 수정 화면 (design-handoff-account-edit/README.md 참고).

Django의 User/Group 모델을 그대로 쓰되, "권한" 3단계(스태프/운영진/슈퍼유저)를
하나의 라디오 선택으로 보여주고 저장 시 is_staff/is_superuser/groups 조합으로
변환하는 커스텀 폼을 UserAdmin에 꽂아 넣는다. 새 모델을 만들지 않는다.
"""

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import Group
from django.shortcuts import redirect
from django.urls import path
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from .admin_views import OPERATIONS_GROUP_NAME

User = get_user_model()

ROLE_STAFF, ROLE_OPS, ROLE_SUPER = "staff", "op", "super"

_ROLE_CHOICES = [
    (
        ROLE_STAFF,
        mark_safe(
            '<span class="role-name">스태프</span>'
            '<span class="role-desc">현장 QR 체크인 스캐너만 사용할 수 있어요. '
            "회차 · 참가자 관리 화면에는 들어갈 수 없어요.</span>"
        ),
    ),
    (
        ROLE_OPS,
        mark_safe(
            '<span class="role-name">운영진</span>'
            '<span class="role-desc">회차 · 참가자 관리 전체와 마스킹 없는 명단'
            "(QR 발송용 · 점수표 · CSV 백업 등) 다운로드까지 가능해요.</span>"
        ),
    ),
    (
        ROLE_SUPER,
        mark_safe(
            '<span class="role-name">슈퍼유저</span>'
            '<span class="role-desc">운영진 권한 전부 + 이 계정 관리 화면에서 '
            "다른 스태프 · 운영진 계정을 초대하고 권한을 바꿀 수 있어요.</span>"
        ),
    ),
]


def _role_of(user) -> str:
    if user.is_superuser:
        return ROLE_SUPER
    if user.pk and user.groups.filter(name=OPERATIONS_GROUP_NAME).exists():
        return ROLE_OPS
    return ROLE_STAFF


_ROLE_BADGE = {
    ROLE_STAFF: ("스태프", "neutral"),
    ROLE_OPS: ("운영진", "accent"),
    ROLE_SUPER: ("슈퍼유저", "super"),
}


class AccountEditForm(forms.ModelForm):
    role = forms.ChoiceField(choices=_ROLE_CHOICES, widget=forms.RadioSelect, label="권한")

    class Meta:
        model = User
        fields = ["first_name", "email", "is_active"]
        labels = {"first_name": "이름", "email": "이메일", "is_active": "계정 활성화"}
        help_texts = {
            # is_active=False는 "다음 로그인부터" 막는 게 아니라, 이미 로그인된
            # 기기도 다음 요청부터 즉시 차단한다(Django가 매 요청마다 is_active를
            # 다시 확인함) — 기기 분실·도난 시 이걸로 그 자리에서 접근을 끊을 수
            # 있다는 걸 운영진이 알아야 하는 부분이라 도움말에 명시한다.
            "is_active": (
                "끄면 로그인이 막히고, 이미 로그인돼 있던 기기(스캐너 등)도 바로 접근이 끊겨요 — "
                "기기를 분실했을 때 이걸로 즉시 차단할 수 있어요. 그동안의 처리 이력은 그대로 남습니다."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["role"].initial = _role_of(self.instance)

    def save(self, commit=True):
        user = super().save(commit=False)
        # 계정 관리 화면에 뜨는 대상은 전부 스태프 이상(체크인 스캐너 접근이
        # 최소 권한)이라, 세 역할 다 is_staff=True는 공통이고 슈퍼유저 플래그만
        # 여기서 정해진다. "운영진" 그룹 소속 여부는 AccountUserAdmin.save_related()에서
        # 처리한다 — Django admin은 이 save()를 항상 commit=False로 호출하고 그
        # 다음에 save_model()/save_related()를 따로 부르기 때문에, group.add/remove
        # 처럼 인스턴스 pk가 있어야 하는 M2M 작업을 여기 넣으면 admin 저장 경로에서
        # 절대 실행되지 않는다.
        user.is_staff = True
        user.is_superuser = self.cleaned_data["role"] == ROLE_SUPER
        if commit:
            user.save()
        return user


class AccountUserAdmin(UserAdmin):
    form = AccountEditForm
    fieldsets = (
        ("기본 정보", {"fields": ("first_name", "email")}),
        ("권한", {"fields": ("role",)}),
        ("상태", {"fields": ("is_active", "last_login")}),
    )
    readonly_fields = ("last_login",)

    def save_model(self, request, obj, form, change):
        # AccountEditForm.save()는 request를 모르는 상태로 role=="super"면 바로
        # is_superuser=True를 켠다. 지금은 계정 관리 화면 자체를 슈퍼유저만
        # 열 수 있어 문제가 없지만(accounts_dashboard의 접근 제한 참고), 나중에
        # 누군가 "운영진" 그룹에 auth.change_user 권한을 얹어주는 순간 운영진이
        # 자기 계정을 슈퍼유저로 셀프 승격시킬 수 있는 구멍이 된다 — 그 상황을
        # 대비해 여기서도 한 번 더, "슈퍼유저만 슈퍼유저를 만들 수 있다"를 강제한다.
        if form.cleaned_data.get("role") == ROLE_SUPER and not request.user.is_superuser:
            obj.is_superuser = False
            # save_related()가 그룹 배정을 결정할 때도 이 값을 다시 읽으므로,
            # 여기서 같이 낮춰줘야 "운영진으로 저장했습니다" 메시지와 실제
            # 저장 결과(그룹 배정)가 어긋나지 않는다.
            form.cleaned_data["role"] = ROLE_OPS
            messages.error(request, "슈퍼유저 권한은 슈퍼유저 계정만 부여할 수 있습니다 — 운영진으로 저장했습니다.")
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # "role" 필드는 AccountEditForm(수정 화면 전용)에만 있고, 계정 추가는
        # 여전히 UserAdmin 기본 add_form(username/password만)을 쓴다 — 여기서
        # 무조건 cleaned_data["role"]을 읽으면 계정 추가 시 KeyError로 500이
        # 났었다. 추가 화면에서는 그룹 배정을 건너뛰고, 슈퍼유저가 이어서
        # (Django가 추가 후 자동으로 이동시켜주는) 수정 화면에서 권한을
        # 마저 지정하게 한다.
        if "role" not in form.cleaned_data:
            return

        role = form.cleaned_data["role"]
        op_group, _ = Group.objects.get_or_create(name=OPERATIONS_GROUP_NAME)
        if role == ROLE_OPS:
            form.instance.groups.add(op_group)
        else:
            form.instance.groups.remove(op_group)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        user = self.get_object(request, object_id)
        if user is not None:
            label, css = _ROLE_BADGE[_role_of(user)]
            extra_context["dbbt_role_label"] = label
            extra_context["dbbt_role_badge_class"] = css
        return super().change_view(request, object_id, form_url, extra_context)

    def get_urls(self):
        return [
            path(
                "<int:user_id>/send-password-reset/",
                # require_POST를 메서드 정의에 @데코레이터로 바로 붙이면 클래스
                # 바디 시점에 언바운드 함수를 감싸버려서, 나중에 self.xxx로 바인딩된
                # 함수를 호출할 때 실제로는 require_POST가 감싼 wrapper(request, ...)
                # 시그니처에 self가 request 자리로 밀려 들어가 버린다 (AttributeError:
                # 'AccountUserAdmin' object has no attribute 'method'). self.send_password_reset로
                # 먼저 제대로 바인딩한 뒤에 여기서 require_POST를 씌워야 한다.
                self.admin_site.admin_view(require_POST(self.send_password_reset)),
                name="auth_user_send_password_reset",
            ),
        ] + super().get_urls()

    def send_password_reset(self, request, user_id):
        # admin_site.admin_view()는 "로그인한 스태프"인지만 확인한다 — 계정
        # 관리는 슈퍼유저 전용 기능(accounts_dashboard와 동일 기준)이라, 이
        # 체크가 없으면 최하위 권한인 스태프 계정도 다른 사람(슈퍼유저 포함)의
        # 비밀번호 재설정 메일을 마음대로 발송시킬 수 있었다.
        if not request.user.is_superuser:
            messages.error(request, "비밀번호 재설정 메일 발송은 슈퍼유저만 실행할 수 있습니다.")
            return redirect("admin:auth_user_change", user_id)

        user = self.get_object(request, str(user_id))
        if user is None or not user.email:
            messages.error(request, "이 계정에 이메일이 등록되어 있지 않아 재설정 메일을 보낼 수 없습니다.")
            return redirect("admin:auth_user_change", user_id)

        form = PasswordResetForm({"email": user.email})
        if form.is_valid():
            try:
                form.save(request=request, use_https=request.is_secure())
                messages.success(request, f"{user.email} 주소로 비밀번호 재설정 메일을 보냈습니다.")
            except Exception as exc:  # noqa: BLE001 — 메일 서버 미설정 등 어떤 이유로 실패해도 500 대신 안내만
                messages.error(request, f"메일 발송에 실패했습니다 (메일 서버 설정을 확인해주세요): {exc}")
        else:
            messages.error(request, "비밀번호 재설정 메일을 보낼 수 없습니다 — 이메일 형식을 확인해주세요.")
        return redirect("admin:auth_user_change", user_id)


# django.contrib.auth.admin이 먼저 등록해 둔 기본 UserAdmin을 우리 버전으로 교체.
# checkin 앱이 INSTALLED_APPS 맨 뒤에 있어 이 모듈은 항상 그 다음에 임포트되므로
# 기본 등록이 먼저 끝나 있는 상태에서 안전하게 unregister할 수 있다.
try:
    admin.site.unregister(User)
except NotRegistered:
    pass
admin.site.register(User, AccountUserAdmin)
