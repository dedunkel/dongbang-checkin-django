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
            "is_active": "끄면 로그인만 막혀요 — 그동안의 처리 이력은 그대로 남습니다.",
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

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
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
