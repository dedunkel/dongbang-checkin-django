"""계정 관리 → 계정 수정/추가 화면.

Django의 User 모델을 그대로 쓰되, "권한"을 스태프/운영진/슈퍼유저 3단계
고정 역할 대신 계정마다 개별 체크박스로 켜고 끌 수 있게 한다. 체크박스
하나하나는 checkin 앱의 Permission(내장 view/change 포함)에 대응하고,
저장 시 user.user_permissions로 직접 반영한다 — 공유 그룹을 거치지 않아
계정마다 완전히 독립적으로 조합할 수 있다.
"""

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import PasswordResetForm, UserCreationForm
from django.contrib.auth.models import Permission
from django.shortcuts import redirect
from django.urls import path
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

User = get_user_model()


def _cap(name: str, desc: str):
    return mark_safe(f'<span class="perm-name">{name}</span><span class="perm-desc">{desc}</span>')


# 카테고리별 권한 체크박스 정의. codename은 checkin 앱 Permission의
# codename과 1:1 대응한다(실제로 부여되는 codename 목록은 아래
# _PERM_BUNDLES 참고 — "관리" 계열은 add_* 권한도 같이 묶어 부여한다).
# 순서가 화면에 보이는 순서.
CAP_CHECKIN = [
    ("use_scanner", _cap("체크인 스캐너 사용", "현장에서 QR 스캔 · 이름/전화 수동 검색으로 체크인을 확정해요.")),
]

CAP_EVENT = [
    ("view_event", _cap("회차 목록 열람", "회차 목록과 상세 정보를 볼 수 있어요.")),
    ("change_event", _cap("회차 정보 관리", "회차를 추가 · 수정하고 활성 회차를 전환해요.")),
    ("run_label_assign", _cap("라벨 · QR 발급 실행", "참가자에게 조/번호 라벨과 개인 QR을 배정해요.")),
    ("push_order_to_sheet", _cap("점수 시트 순서 반영", "연동된 점수 시트에 참가자 순서를 반영해요.")),
]

CAP_PARTICIPANT = [
    ("view_participant", _cap("참가자 명단 열람", "참가자 목록과 상세 정보를 볼 수 있어요.")),
    ("change_participant", _cap("참가자 정보 수정", "참가자 정보를 직접 편집해요.")),
    ("approve_verification", _cap("학적검수 승인", "학적 확인 대기 중인 참가자를 승인 처리해요.")),
    ("mark_paid", _cap("입금 확인 처리", "입금이 확인된 참가자를 입금 완료 상태로 바꿔요.")),
    ("mark_refund", _cap("환불 처리", "참가자를 환불 처리하고 라벨 · QR을 회수해요.")),
    ("swap_labels", _cap("라벨 맞바꾸기", "참가자 두 명의 조/번호 라벨을 서로 바꿔요.")),
]

CAP_EXPORT = [
    ("export_csv_backup", _cap("CSV 백업 다운로드", "참가자 전체 정보를 마스킹 없이 CSV로 내려받아요.")),
    ("export_qr_send_list", _cap("QR 발송용 명단 다운로드", "문자/카톡 대량발송용 이름 · 연락처 · QR 링크를 내려받아요.")),
    ("export_score_sheet", _cap("점수표 다운로드", "심사용 점수표를 마스킹 없이 엑셀로 내려받아요.")),
    ("export_announcement", _cap("공지용 명단 다운로드", "이름/연락처를 마스킹한 공지용 명단을 내려받아요.")),
    ("export_application_confirmation", _cap("신청 확인용 명단 다운로드", "라벨 배정 전에도 받을 수 있는 전체 신청자 확인용 명단이에요.")),
]

_ALL_CAP_GROUPS = [
    ("perm_checkin", CAP_CHECKIN),
    ("perm_event", CAP_EVENT),
    ("perm_participant", CAP_PARTICIPANT),
    ("perm_export", CAP_EXPORT),
]

# 체크박스 하나가 저장 시 실제로 부여하는 Django permission codename 목록.
# "관리" 계열 체크박스는 열람(view)뿐 아니라 신규 추가(add)까지 같이
# 묶어서 부여한다 — 화면에 "추가"용 체크박스를 따로 두면 실사용자 입장에서
# 구분할 실익이 없다.
_PERM_BUNDLES = {
    "use_scanner": ["use_scanner"],
    "view_event": ["view_event"],
    "change_event": ["change_event", "add_event"],
    "run_label_assign": ["run_label_assign"],
    "push_order_to_sheet": ["push_order_to_sheet"],
    "view_participant": ["view_participant"],
    "change_participant": ["change_participant", "add_participant"],
    "approve_verification": ["approve_verification"],
    "mark_paid": ["mark_paid"],
    "mark_refund": ["mark_refund"],
    "swap_labels": ["swap_labels"],
    "export_csv_backup": ["export_csv_backup"],
    "export_qr_send_list": ["export_qr_send_list"],
    "export_score_sheet": ["export_score_sheet"],
    "export_announcement": ["export_announcement"],
    "export_application_confirmation": ["export_application_confirmation"],
}

TIER_LABEL = {"staff": "스태프", "op": "운영진", "super": "슈퍼유저"}


def _capability_field(choices):
    return forms.MultipleChoiceField(
        choices=choices, widget=forms.CheckboxSelectMultiple, required=False, label=""
    )


def _codenames_for(user) -> set[str]:
    """이 계정에 실제로 부여돼 있는 checkin 권한 codename 집합. 슈퍼유저
    여부와는 무관하게 DB에 저장된 값만 본다(체크박스는 슈퍼유저 토글과
    별개로 그 자체 값을 그대로 보여줘야 함) — content_type을
    select_related로 함께 가져와야 하는 호출부는 accounts_dashboard의
    Prefetch를 참고."""
    if not user.pk:
        return set()
    return {
        p.codename
        for p in user.user_permissions.all()  # prefetch 캐시를 쓰려면 filter()가 아니라 all() 순회
        if p.content_type.app_label == "checkin"
    }


def _tier_of(user) -> str:
    """계정 목록에서 한눈에 보여줄 요약 등급. 실제 접근 범위는 이제 계정마다
    완전히 개별적이라 정확한 3단계 분류는 더는 의미가 없지만, 목록에서
    "이 사람은 스캐너만 쓰는지 / 그 이상도 하는지"를 훑어보는 용도로는
    여전히 쓸모 있어 남겨둔다."""
    if user.is_superuser:
        return "super"
    if _codenames_for(user) - {"use_scanner"}:
        return "op"
    return "staff"


def _permissions_for_codenames(codenames) -> list:
    target_codenames = set()
    for _field_name, choices in _ALL_CAP_GROUPS:
        for codename, _label in choices:
            if codename in codenames:
                target_codenames.update(_PERM_BUNDLES[codename])
    if not target_codenames:
        return []
    return list(Permission.objects.filter(content_type__app_label="checkin", codename__in=target_codenames))


class _CapabilityFormMixin:
    """계정 수정 폼과 추가 폼이 공유하는 "슈퍼유저 여부 + 카테고리별 권한
    체크박스" 저장/초기화 로직. 필드 자체는 각 폼에서 선언한다 — Django
    ModelForm을 상속하는 믹스인은 메타클래스 순서 문제가 잘 나서(공식
    문서도 권장하지 않음), 필드 선언은 중복을 감수하고 각 폼에 직접 두고
    로직만 공유한다."""

    def _init_capability_initial(self):
        if self.instance.pk:
            self.fields["is_superuser"].initial = self.instance.is_superuser
            current = _codenames_for(self.instance)
            for field_name, choices in _ALL_CAP_GROUPS:
                self.fields[field_name].initial = [c for c, _label in choices if c in current]

    def selected_codenames(self) -> set[str]:
        selected = set()
        for field_name, _choices in _ALL_CAP_GROUPS:
            selected.update(self.cleaned_data.get(field_name) or [])
        return selected


class AccountEditForm(_CapabilityFormMixin, forms.ModelForm):
    is_superuser = forms.BooleanField(
        required=False,
        label="슈퍼유저",
        help_text=(
            "계정 관리 화면 접근을 포함해 모든 권한을 자동으로 가져요. "
            "아래 개별 권한 체크와 무관하게 항상 전체 접근이 허용돼요."
        ),
    )
    perm_checkin = _capability_field(CAP_CHECKIN)
    perm_event = _capability_field(CAP_EVENT)
    perm_participant = _capability_field(CAP_PARTICIPANT)
    perm_export = _capability_field(CAP_EXPORT)

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
        self._init_capability_initial()

    def save(self, commit=True):
        user = super().save(commit=False)
        # 계정 관리 화면에 뜨는 대상은 전부 스태프 이상(체크인 스캐너 접근이
        # 최소 권한)이라 is_staff=True는 항상 고정이고, 슈퍼유저 플래그만
        # 여기서 정해진다. 개별 권한(user_permissions)은
        # AccountUserAdmin.save_related()에서 처리한다 — Django admin은 이
        # save()를 항상 commit=False로 호출하고 그 다음에
        # save_model()/save_related()를 따로 부르기 때문에, user_permissions
        # 처럼 인스턴스 pk가 있어야 하는 M2M 작업을 여기 넣으면 admin 저장
        # 경로에서 절대 실행되지 않는다.
        user.is_staff = True
        user.is_superuser = self.cleaned_data.get("is_superuser", False)
        if commit:
            user.save()
        return user


class AccountCreateForm(_CapabilityFormMixin, UserCreationForm):
    is_superuser = forms.BooleanField(
        required=False,
        label="슈퍼유저",
        help_text=(
            "계정 관리 화면 접근을 포함해 모든 권한을 자동으로 가져요. "
            "아래 개별 권한 체크와 무관하게 항상 전체 접근이 허용돼요."
        ),
    )
    perm_checkin = _capability_field(CAP_CHECKIN)
    perm_event = _capability_field(CAP_EVENT)
    perm_participant = _capability_field(CAP_PARTICIPANT)
    perm_export = _capability_field(CAP_EXPORT)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "email")
        labels = {"username": "아이디", "first_name": "이름", "email": "이메일"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_capability_initial()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = True
        user.is_superuser = self.cleaned_data.get("is_superuser", False)
        if commit:
            user.save()
        return user


class AccountUserAdmin(UserAdmin):
    form = AccountEditForm
    add_form = AccountCreateForm
    fieldsets = (
        ("기본 정보", {"fields": ("first_name", "email")}),
        ("권한", {"fields": ("is_superuser",)}),
        ("체크인", {"fields": ("perm_checkin",)}),
        ("회차 관리", {"fields": ("perm_event",)}),
        ("참가자 관리", {"fields": ("perm_participant",)}),
        ("다운로드", {"fields": ("perm_export",)}),
        ("상태", {"fields": ("is_active", "last_login")}),
    )
    add_fieldsets = (
        ("계정 정보", {"fields": ("username", "password1", "password2", "first_name", "email")}),
        ("권한", {"fields": ("is_superuser",)}),
        ("체크인", {"fields": ("perm_checkin",)}),
        ("회차 관리", {"fields": ("perm_event",)}),
        ("참가자 관리", {"fields": ("perm_participant",)}),
        ("다운로드", {"fields": ("perm_export",)}),
    )
    readonly_fields = ("last_login",)

    def save_model(self, request, obj, form, change):
        # AccountEditForm/AccountCreateForm.save()는 request를 모르는 상태로
        # is_superuser 체크박스 값을 그대로 반영한다. 지금은 계정 관리 화면
        # 자체를 슈퍼유저만 열 수 있어 문제가 없지만(accounts_dashboard의
        # 접근 제한 참고), 나중에 누군가 운영진 계정에 auth.change_user
        # 권한을 얹어주는 순간 스스로를 슈퍼유저로 셀프 승격시킬 수 있는
        # 구멍이 된다 — 그 상황을 대비해 여기서도 한 번 더, "슈퍼유저만
        # 슈퍼유저를 만들 수 있다"를 강제한다.
        if form.cleaned_data.get("is_superuser") and not request.user.is_superuser:
            obj.is_superuser = False
            # save_related()가 권한 배정을 결정할 때도 이 값을 다시 읽지는
            # 않지만(개별 권한 체크박스와 슈퍼유저는 이제 독립적인 필드),
            # 메시지가 실제 저장 결과와 어긋나지 않도록 함께 낮춰둔다.
            form.cleaned_data["is_superuser"] = False
            messages.error(request, "슈퍼유저 권한은 슈퍼유저 계정만 부여할 수 있습니다 — 나머지 권한만 저장했습니다.")
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if not hasattr(form, "selected_codenames"):
            return
        # 계정 수정 폼과 추가 폼 둘 다 selected_codenames()를 갖고 있어서
        # (예전 role 필드는 추가 폼엔 아예 없어서 분기해야 했지만, 지금은
        # 두 폼이 같은 인터페이스라 분기 없이 하나로 처리된다), 매번 선택된
        # 체크박스 집합으로 checkin 권한을 통째로 교체한다 — 이번에 체크
        # 해제한 권한은 정확히 그만큼 빠져야 하므로 add()가 아니라 set()을
        # 쓴다. 단, user_permissions.set()은 전체 M2M을 통째로 바꿔버려서
        # checkin 권한이 아닌 다른 권한(예: 미래에 누군가 얹어둔
        # auth.change_user — save_model의 셀프 승격 방지 로직이 상정하는
        # 상황)까지 같이 날아간다. checkin 권한만 바꾸고 나머지는 그대로
        # 남기기 위해 두 집합을 합쳐서 넣는다.
        codenames = form.selected_codenames()
        new_checkin_perms = _permissions_for_codenames(codenames)
        other_perms = list(form.instance.user_permissions.exclude(content_type__app_label="checkin"))
        form.instance.user_permissions.set(other_perms + new_checkin_perms)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        user = self.get_object(request, object_id)
        if user is not None:
            tier = _tier_of(user)
            extra_context["dbbt_role_label"] = TIER_LABEL[tier]
            extra_context["dbbt_role_badge_class"] = tier
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
