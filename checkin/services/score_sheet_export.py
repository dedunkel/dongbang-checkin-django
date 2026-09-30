"""
인포/공연장에서 쓰는 점수표 엑셀 다운로드.

공지용 명단(announcement_export.py)과 달리 이건 스태프 내부용이라 이름/
연락처를 마스킹하지 않는다. 입금 여부·도착 여부는 현재 DB 상태를 그대로
반영해서 미리 채워 넣고, 점수는 당연히 비워둔다(행사 당일 채워 넣는 용도).
장르별 탭 구성은 공지용 명단과 동일 — event_excel_export.py의 공용 로직을
그대로 가져다 쓴다 (#30).

학적검수 미통과자도 입금만 되면 라벨/QR이 나가게 되면서(assign_labels.py),
그런 참가자가 이 점수표에도 섞여 들어온다 — 공지용 명단과 동일하게 비고에
"학적 인증 필요"를 표시하고, 이름 셀만 파란색으로 칠해 눈에 띄게 한다.

동명이인도 현장에서 사람을 헷갈리기 쉬운 포인트라, 장르 탭을 통틀어 실명이
겹치는 참가자는 이름 셀 배경을 노란색(#FFD94D)으로 칠한다. 학적 인증 필요
(파란 글자색)와 동시에 해당될 수도 있어서 겹치지 않게 서로 다른 속성(배경 vs
글자색)을 쓴다 — 두 조건 다 해당되면 노란 배경 위에 파란 글자가 같이 보인다.
"""

from __future__ import annotations

from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from checkin.models import Event, Participant
from checkin.services.event_excel_export import build_file, find_duplicate_real_names, remarks_for
from checkin.services.name_utils import split_display_name

HEADERS = ["번호", "이름", "연락처", "소속대학", "학적", "순서", "입금 여부", "도착 여부", "점수", "비고"]

CHECK_MARK = "O"
_NAME_COLUMN = 2
_UNVERIFIED_NAME_COLOR = "FF3B82F6"
_DUPLICATE_NAME_FILL = "FFFFD94D"


def _row(i: int, p: Participant) -> list:
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
        remarks_for(p),
    ]


def _make_row_styler(duplicate_names: set[str]) -> callable:
    def _style_row(ws: Worksheet, row: int, p: Participant) -> None:
        cell = ws.cell(row=row, column=_NAME_COLUMN)
        real, _ = split_display_name(p.name)
        if real in duplicate_names:
            cell.fill = PatternFill(fill_type="solid", fgColor=_DUPLICATE_NAME_FILL)
        if p.entry_type == "참가" and p.verification_status != "APPROVED":
            cell.font = Font(color=_UNVERIFIED_NAME_COLOR)

    return _style_row


def build_score_sheet_file(event: Event) -> tuple[str, bytes]:
    """(파일명, xlsx 바이트) 튜플을 반환."""
    filename = f"DongbangBattle Vol.{event.volume} 점수표.xlsx"
    duplicate_names = find_duplicate_real_names(event)
    return build_file(event, HEADERS, _row, filename, row_styler=_make_row_styler(duplicate_names))
