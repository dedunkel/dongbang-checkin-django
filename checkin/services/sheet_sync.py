"""
체크인 시 인포/공연장 점수 시트("도착 여부" 컬럼)에 실시간으로 반영하기 위한
연동. google-apps-script/SheetSync.gs를 그 시트(구글 폼 응답 시트와는 다른,
별도 파일)에 붙이고 웹 앱으로 배포해서 나온 URL을 그 회차(Event)의
sheet_sync_url 필드에 넣어 씁니다. 회차마다 새 시트를 만들어 새로 배포하는
구조라 환경변수가 아니라 /admin에서 회차별로 바로 수정할 수 있게 함 —
비밀키(SHEET_SYNC_SECRET)만 배포 환경 전체에서 공유합니다.

체크인은 이미 저장된 뒤이므로, 이 연동이 실패해도(시트 접근 문제, 네트워크
문제 등) 현장 체크인 자체를 막으면 안 됩니다. 그래서 별도 스레드로 던져두고
실패는 로그만 남깁니다 — 스태프가 QR을 계속 스캔하는 흐름을 이 요청 때문에
기다리게 하지 않기 위함입니다.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.request

from django.conf import settings

from checkin.models import Participant

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10
# 순서 일괄 반영은 여러 명을 한 번에 처리하느라 더 오래 걸릴 수 있어 넉넉하게.
_BULK_TIMEOUT_SECONDS = 60
# 프록시 자동 감지(특히 Windows의 시스템 프록시 조회)가 첫 요청에서 몇 초씩
# 걸리는 경우가 있어, 명시적으로 끄고 직접 연결하도록 한다.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def push_arrival(participant: Participant) -> None:
    """체크인 확정 시 호출 — 실시간성이 중요하고 실패해도 체크인을 막으면 안
    되므로, 백그라운드 스레드로 던지고 실패는 로그만 남긴다(fire-and-forget)."""
    sheet_sync_url = participant.event.sheet_sync_url
    if not sheet_sync_url:
        return

    payload = {
        "secret": settings.SHEET_SYNC_SECRET,
        "entryType": participant.entry_type,
        "genre": participant.genre,
        "name": participant.name,
        "phone": participant.phone,
    }
    thread = threading.Thread(
        target=_post_ignore_errors, args=(sheet_sync_url, payload, _TIMEOUT_SECONDS), daemon=True
    )
    thread.start()


def push_order_for_event(event) -> dict:
    """스태프가 명시적으로 누르는 버튼(Events 액션)에서 호출 — 체크인과 달리
    한 번에 여러 명을 보내고, 결과(몇 명 매칭됐는지)를 그대로 돌려줘서
    관리자 화면에 성공/실패 메시지로 보여준다."""
    if not event.sheet_sync_url:
        return {"ok": False, "message": "이 회차에 점수 시트 URL(sheet_sync_url)이 설정되어 있지 않습니다."}

    entries = [
        {
            "entryType": p.entry_type,
            "genre": p.genre,
            "name": p.name,
            "phone": p.phone,
            "labelCode": p.label_code,
        }
        for p in Participant.objects.filter(event=event, entry_type="참가", label_code__isnull=False)
    ]
    if not entries:
        return {"ok": True, "matchedCount": 0, "totalCount": 0, "message": "라벨이 배정된 참가자가 없습니다."}

    payload = {"secret": settings.SHEET_SYNC_SECRET, "action": "order", "entries": entries}
    try:
        body = _post(event.sheet_sync_url, payload, timeout=_BULK_TIMEOUT_SECONDS)
        return json.loads(body)
    except OSError as e:
        logger.warning("점수 시트 순서 반영 실패: %s", e)
        return {"ok": False, "message": str(e)}


def _post(url: str, payload: dict, timeout: int) -> bytes:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _opener.open(req, timeout=timeout) as res:
        return res.read()


def _post_ignore_errors(url: str, payload: dict, timeout: int) -> None:
    try:
        _post(url, payload, timeout)
    except OSError as e:
        logger.warning("점수 시트 도착 표시 반영 실패: %s", e)
