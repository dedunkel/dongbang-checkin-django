"""
URL configuration for config project.

/admin/ — Django 기본 관리자 페이지. 이 프로젝트에서는 별도로 "운영진 대시보드"를
새로 만들지 않고, 이 admin 화면을 그대로 운영진 대시보드로 씁니다
(checkin/admin.py 참고 — 회차 관리, 검수, 라벨/QR 발급, CSV 백업 액션이 여기 있습니다).
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("checkin.urls")),
]
