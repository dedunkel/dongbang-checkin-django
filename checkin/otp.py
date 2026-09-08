"""2단계 인증(TOTP) — SEC-03.

로그인 폼에 인증 앱(Google Authenticator 등) 6자리 코드 입력을 추가하되,
계정이 아직 등록을 안 했으면 예전처럼 비밀번호만으로 통과시킨다. 그래서
"슈퍼유저부터 먼저, 나머지는 나중에"처럼 계정별로 순차 적용할 수 있고,
행사 직전에 전체 스태프가 한꺼번에 로그인 못 하게 되는 사고가 없다.

기기 등록/해제는 checkin/admin_views.py의 otp_setup 뷰(계정 관리와 별개로
본인 계정 자기 스스로 설정하는 화면, /admin/2fa/)가 담당한다.
"""

from __future__ import annotations

import base64
import io

import qrcode
from django import forms
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django_otp import devices_for_user


class AdminOTPAuthenticationForm(AdminAuthenticationForm):
    """AdminAuthenticationForm(아이디/비밀번호 + is_staff 확인) + OTP 코드.

    비밀번호까지 맞았는데 그 계정에 확인된(confirmed) TOTP 기기가 있으면
    코드가 맞아야 로그인이 끝난다. 기기가 아예 없는 계정(아직 2단계 인증을
    설정 안 함)은 이 단계를 그냥 건너뛴다.
    """

    otp_token = forms.CharField(
        required=False,
        label="2단계 인증 코드",
        widget=forms.TextInput(
            attrs={"autocomplete": "one-time-code", "inputmode": "numeric", "autofocus": False}
        ),
    )

    def clean(self):
        cleaned = super().clean()
        user = self.get_user()
        if user is None:
            return cleaned

        devices = list(devices_for_user(user, confirmed=True))
        if not devices:
            return cleaned

        token = (cleaned.get("otp_token") or "").strip()
        if not token:
            raise forms.ValidationError("2단계 인증 코드를 입력해주세요.", code="otp_token_required")

        for device in devices:
            if device.verify_token(token):
                # django_otp가 user_logged_in 시그널에서 이 속성을 보고 세션에
                # 인증 상태를 반영한다 — django_otp.login()을 직접 안 불러도 된다.
                user.otp_device = device
                return cleaned

        raise forms.ValidationError("2단계 인증 코드가 올바르지 않습니다.", code="otp_token_invalid")


admin.site.login_form = AdminOTPAuthenticationForm


def totp_qr_data_url(device) -> str:
    """TOTPDevice의 프로비저닝 URL을 QR 코드 PNG(데이터 URL)로 렌더링."""
    img = qrcode.make(device.config_url, box_size=6, border=1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
