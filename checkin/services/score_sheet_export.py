"""
인포/공연장에서 쓰는 점수표 엑셀 다운로드.

공지용 명단(announcement_export.py)과 달리 이건 스태프 내부용이라 이름/
연락처를 마스킹하지 않는다. 입금 여부·도착 여부는 현재 DB 상태를 그대로
반영해서 미리 채워 넣고, 점수는 당연히 비워둔다(행사 당일 채워 넣는 용도).
장르별 탭 구성은 공지용 명단과 동일 — event_excel_export.py의 공용 로직을
그대로 가져다 쓴다 (#30).
"""

from __future__ import annotations

from checkin.models import Event
from checkin.services.event_excel_export import build_file

HEADERS = ["번호", "이름", "연락처", "소속대학", "학적", "순서", "입금 여부", "도착 여부", "점수"]

CHECK_MARK = "O"


def _row(i: int, p) -> list:
    return [
        i,
        p.name,
        p.phone,
        p.school or "",
        p.academic_status or "",
        p.label_code or "",
        CHECK_MARK if p.payment_status == "PAID" else "",
        CHECK_MARK if p.checkin_status == "CHECKED_IN" else "",
        "",
    ]


def build_score_sheet_file(event: Event) -> tuple[str, bytes]:
    """(파일명, xlsx 바이트) 튜플을 반환."""
    filename = f"DongbangBattle Vol.{event.volume} 점수표.xlsx"
    return build_file(event, HEADERS, _row, filename)
