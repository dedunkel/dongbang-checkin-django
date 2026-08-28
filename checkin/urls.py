from django.urls import path

from . import views

app_name = "checkin"

urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.register_view, name="register"),
    path("checkin/", views.checkin_view, name="checkin"),
    path("qr/<uuid:token>/", views.qr_view, name="qr"),
    path("checkin/scan/<uuid:token>/", views.scan_view, name="scan"),
    path("checkin/scan/<uuid:token>/confirm/", views.scan_confirm, name="scan_confirm"),
    path("api/checkin/", views.checkin_api, name="checkin_api"),
    path("api/participants/search/", views.participant_search_api, name="participant_search_api"),
    path(
        "api/participants/<uuid:participant_id>/manual-checkin/",
        views.manual_checkin_api,
        name="manual_checkin_api",
    ),
    path("api/import/google-form/", views.google_form_import, name="google_form_import"),
]
