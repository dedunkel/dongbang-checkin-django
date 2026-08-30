"""
공지용(참가/관람 신청 명단 및 예선 순서) 엑셀 다운로드.

지금까지 공지에 쓰던 구글 시트와 같은 양식(장르별 탭, "동방배틀 Vol.N
{장르} 참가자 명단" 제목 행)으로 만들되, 개인정보 보호를 위해 이름/연락처는
일부를 *로 가려서 내보냅니다. 실제 구글 시트 링크가 필요하면, 다운로드된
엑셀 파일을 구글 드라이브에 업로드해서 그대로 구글 시트로 열면 됩니다
(별도 API 연동 없이도 동일한 결과를 얻을 수 있어 이렇게 구현했습니다).

탭 구성/제목 행/워크북 조립 등 공통 로직은 event_excel_export.py를 그대로
가져다 쓴다 (#30) — 이 모듈에는 이 내보내기 고유의 헤더/행 값만 남긴다.
"""

from __future__ import annotations

from checkin.models import Event
from checkin.services.event_excel_export import build_file, mask_name, mask_phone, remarks_for

HEADERS = ["번호", "이름", "연락처", "소속대학", "학적", "순서", "비고"]


def _row(i: int, p) -> list:
    return [
        i,
        mask_name(p.name),
        mask_phone(p.phone),
        p.school or "",
        p.academic_status or "",
        p.label_code or "",
        remarks_for(p),
    ]


def build_announcement_file(event: Event) -> tuple[str, bytes]:
    """(파일명, xlsx 바이트) 튜플을 반환."""
    filename = f"DongbangBattle Vol.{event.volume} 참가·관람 신청 명단 및 예선 순서.xlsx"
    return build_file(event, HEADERS, _row, filename)
