from django import forms

from .models import EntryType, Genre, Participant


class RegisterForm(forms.ModelForm):
    """구글 폼을 쓰지 않을 경우를 위한 예비 신청 폼."""

    # Genre.choices의 두 번째 값(왁킹/팝핑 등 한글 표기)은 SheetSync.gs·엑셀
    # 내보내기가 장르별 탭을 찾는 데 쓰는 내부 라벨일 뿐이라, 참가자에게 보여주는
    # 화면에는 노출하지 않는다 (dongbang-ui-handoff/README.md 참고 사항) — 값과
    # 화면 표시 문구를 둘 다 영문 값으로 맞춰서 select 옵션에 한글이 안 뜨게 한다.
    genre = forms.ChoiceField(
        required=False, label="참가 장르", choices=[(g.value, g.value) for g in Genre]
    )

    class Meta:
        model = Participant
        fields = ["entry_type", "name", "phone", "school", "academic_status", "genre"]
        widgets = {
            "entry_type": forms.RadioSelect,
        }
        labels = {
            "entry_type": "참가 / 관람",
            "name": "이름 / 댄서명",
            "phone": "연락처",
            "school": "소속대학",
            "academic_status": "학적 (재학/휴학)",
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("entry_type") == EntryType.PARTICIPANT and not cleaned.get("genre"):
            self.add_error("genre", "참가자는 장르를 선택해야 합니다.")
        return cleaned
