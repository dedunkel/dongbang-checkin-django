from __future__ import annotations


def split_display_name(raw_name: str) -> tuple[str, str]:
    """'이름 / 댄서명' 형식에서 구분자 앞뒤 공백만 제거하고 (본명, 댄서명)으로
    나눈다. 이름 자체에 포함된 공백(예: "나나미 헤이지")은 원형 그대로 둔다.
    구분자가 없으면 댄서명은 빈 문자열."""
    real, sep, dancer = raw_name.partition("/")
    return real.strip(), (dancer.strip() if sep else "")
