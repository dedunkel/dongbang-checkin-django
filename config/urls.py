"""
URL configuration for config project.

/admin/ — Django 기본 관리자 페이지. 이 프로젝트에서는 별도로 "운영진 대시보드"를
새로 만들지 않고, 이 admin 화면을 그대로 운영진 대시보드로 씁니다
(checkin/admin.py 참고 — 회차 관리, 검수, 라벨/QR 발급, CSV 백업 액션이 여기 있습니다).

/admin/accounts/ — 계정 관리 화면(checkin/admin_views.py). User/Group 모델
기반이라 ModelAdmin으로 등록하지 않고 별도 뷰로 만들었으므로, admin.site.urls가
"admin/"로 시작하는 나머지 경로를 전부 가로채기 전에 먼저 매칭되도록
admin.site.urls보다 앞에 둬야 한다.

비밀번호 재설정 4종 URL — 계정 수정 화면의 "비밀번호 재설정 이메일 보내기"
(checkin/auth_admin.py의 PasswordResetForm.save())가 이메일 본문에서
{% url 'password_reset_confirm' %}을 참조하는데, 이 URL 이름이 프로젝트에
없으면 이메일 렌더링 자체가 NoReverseMatch로 실패한다. 김에 admin 로그인
화면의 "Forgotten your login credentials?" 링크(admin_password_reset)도
같이 살아나게 연결한다.
"""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from checkin.admin_views import accounts_dashboard

urlpatterns = [
    path("admin/accounts/", accounts_dashboard, name="accounts_dashboard"),
    path(
        "admin/password_reset/",
        auth_views.PasswordResetView.as_view(email_template_name="registration/password_reset_email.html"),
        name="admin_password_reset",
    ),
    path("admin/password_reset/done/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("reset/done/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("admin/", admin.site.urls),
    path("", include("checkin.urls")),
]
