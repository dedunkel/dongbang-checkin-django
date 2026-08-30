"""
신청 참가자 확인용 공지 엑셀 다운로드.

기존 "공지용 명단"(announcement_export.py)은 라벨(예선 순서)이 배정된
확정 참가자만 담는 반면, 이건 라벨 배정 여부와 무관하게 그 장르에 신청한
사람 전원을 담아서, 참가자 본인이 자기 신청 내용이 맞게 접수됐는지
확인하는 용도다. 그래서 "순서" 컬럼이 없고, 아직 신청 처리가 덜 끝난
사람은 비고에 "미입금"/"학적 인증 필요"가 표시된다(문제없으면 빈칸).

이름/연락처 마스킹, 탭 구성, 제목 행 형식은 공지용 명단과 동일 —
event_excel_export.py의 공용 로직을 가져다 쓴다 (#30). 다만 "라벨 유무와
무관하게 전원을 담는다"는 이 내보내기만의 규칙이라, 그 부분(아래
all_participants_for_tab)만은 공용 모듈로 옮기지 않고 이 모듈 소유로 둔다 —
다른 내보내기가 쓰는 participants_for_tab(라벨 배정자만)과 이름이 헷갈리지
않도록 구분해서 부른다.
"""

from __future__ import annotations

from checkin.models import Event, Participant
from checkin.services.event_excel_export import build_file, mask_name, mask_phone, remarks_for

HEADERS = ["번호", "이름", "연락처", "소속대학", "학적", "비고"]


def all_participants_for_tab(event: Event, genre: str | None) -> list[Participant]:
    """라벨 유무와 무관하게 그 탭(장르 또는 관람)에 신청한 사람 전원을
    신청 순서(생성일시)로 정렬해 반환."""
    if genre is None:
        return list(Participant.objects.filter(event=event, entry_type="관람").order_by("created_at"))
    return list(
        Participant.objects.filter(event=event, entry_type="참가", genre=genre).order_by("created_at")
    )


def _row(i: int, p: Participant) -> list:
    return [
        i,
        mask_name(p.name),
        mask_phone(p.phone),
        p.school or "",
        p.academic_status or "",
        remarks_for(p),
    ]


def build_application_confirmation_file(event: Event) -> tuple[str, bytes]:
    """(파일명, xlsx 바이트) 튜플을 반환."""
    filename = f"DongbangBattle Vol.{event.volume} 참가·관람 신청 확인용 명단.xlsx"
    return build_file(event, HEADERS, _row, filename, tab_participants=all_participants_for_tab)
