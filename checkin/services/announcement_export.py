"""
공지용(참가/관람 신청 명단 및 예선 순서) 엑셀 다운로드.

지금까지 공지에 쓰던 구글 시트와 같은 양식(장르별 탭, "동방배틀 Vol.N
{장르} 참가자 명단" 제목 행)으로 만들되, 개인정보 보호를 위해 이름/연락처는
일부를 *로 가려서 내보냅니다. 실제 구글 시트 링크가 필요하면, 다운로드된
엑셀 파일을 구글 드라이브에 업로드해서 그대로 구글 시트로 열면 됩니다
(별도 API 연동 없이도 동일한 결과를 얻을 수 있어 이렇게 구현했습니다).
"""

from __future__ import annotations

import io
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from checkin.models import Event, Participant

# 장르별 탭 순서 — 기존 공지 시트와 동일 (관람은 마지막, genre=None으로 구분).
GENRE_TABS = [
    ("Waacking", "왁킹"),
    ("Popping", "팝핑"),
    ("Locking", "락킹"),
    ("House", "하우스"),
    ("Krump", "크럼프"),
    ("Hiphop", "힙합"),
    ("Breaking", "브레이킹"),
    (None, "관람"),
]

HEADERS = ["번호", "이름", "연락처", "소속대학", "학적", "순서", "비고"]

_PHONE_DIGITS_RE = re.compile(r"\D")


def _mask_middle(s: str) -> str:
    s = s.strip()
    if len(s) <= 1:
        return s
    if len(s) == 2:
        return s[0] + "*"
    return s[0] + "*" * (len(s) - 2) + s[-1]


def mask_name(raw_name: str) -> str:
    """'본명/댄서네임' 형식이면 본명 부분만 가운데를 마스킹하고 댄서네임은
    그대로 둔다. 구분자가 없으면(=댄서네임을 따로 안 적어 이름과 같은
    경우) 전체를 이름과 동일하게 마스킹한다."""
    real, _, dancer = raw_name.partition("/")
    masked_real = _mask_middle(real)
    return f"{masked_real}/{dancer}" if dancer else masked_real


def mask_phone(raw_phone: str) -> str:
    """010-****-1234 형식으로 통일. 11자리 숫자가 아니면 원본을 그대로 반환."""
    digits = _PHONE_DIGITS_RE.sub("", raw_phone or "")
    if len(digits) != 11:
        return raw_phone
    return f"{digits[:3]}-****-{digits[7:]}"


def _write_sheet(wb: Workbook, event: Event, sheet_title: str, participants: list[Participant]) -> None:
    ws = wb.create_sheet(title=sheet_title)
    title_text = (
        f"동방배틀 Vol.{event.volume} 관람자 명단"
        if sheet_title == "관람"
        else f"동방배틀 Vol.{event.volume} {sheet_title} 참가자 명단"
    )

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(HEADERS))
    title_cell = ws.cell(row=1, column=1, value=title_text)
    title_cell.font = Font(bold=True, size=13)
    title_cell.alignment = Alignment(horizontal="center")

    for col, header in enumerate(HEADERS, start=1):
        cell = ws.cell(row=2, column=col, value=header)
        cell.font = Font(bold=True)

    for i, p in enumerate(participants, start=1):
        ws.append(
            [
                i,
                mask_name(p.name),
                mask_phone(p.phone),
                p.school or "",
                p.academic_status or "",
                p.label_code or "",
                "",
            ]
        )

    for col in range(1, len(HEADERS) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 16


def build_announcement_workbook(event: Event) -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)  # 기본으로 생기는 빈 시트 제거

    for genre, tab_name in GENRE_TABS:
        if genre is None:
            participants = list(
                Participant.objects.filter(event=event, entry_type="관람").order_by("created_at")
            )
        else:
            participants = sorted(
                Participant.objects.filter(event=event, entry_type="참가", genre=genre, label_code__isnull=False),
                key=lambda p: (p.label_group, p.label_number),
            )
        _write_sheet(wb, event, tab_name, participants)

    return wb


def build_announcement_file(event: Event) -> tuple[str, bytes]:
    """(파일명, xlsx 바이트) 튜플을 반환."""
    wb = build_announcement_workbook(event)
    buf = io.BytesIO()
    wb.save(buf)
    filename = f"DongbangBattle Vol.{event.volume} 참가·관람 신청 명단 및 예선 순서.xlsx"
    return filename, buf.getvalue()
