from django import forms

from .models import EntryType, Participant


class RegisterForm(forms.ModelForm):
    """구글 폼을 쓰지 않을 경우를 위한 예비 신청 폼."""

    class Meta:
        model = Participant
        fields = ["entry_type", "name", "phone", "school", "academic_status", "genre", "email"]
        widgets = {
            "entry_type": forms.RadioSelect,
        }
        labels = {
            "entry_type": "참가 / 관람",
            "name": "참가자명 / 관람자명",
            "phone": "연락처",
            "school": "소속대학",
            "academic_status": "학적 (재학/휴학)",
            "genre": "참가 장르",
            "email": "이메일 주소",
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("entry_type") == EntryType.PARTICIPANT and not cleaned.get("genre"):
            self.add_error("genre", "참가자는 장르를 선택해야 합니다.")
        return cleaned
