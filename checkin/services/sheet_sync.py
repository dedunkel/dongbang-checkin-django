"""
체크인 시 인포/공연장 점수 시트("도착 여부" 컬럼)에 실시간으로 반영하기 위한
연동. google-apps-script/SheetSync.gs를 그 시트(구글 폼 응답 시트와는 다른,
별도 파일)에 붙이고 웹 앱으로 배포해서 나온 URL을 SHEET_SYNC_URL로 씁니다.

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
# 프록시 자동 감지(특히 Windows의 시스템 프록시 조회)가 첫 요청에서 몇 초씩
# 걸리는 경우가 있어, 명시적으로 끄고 직접 연결하도록 한다.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def push_arrival(participant: Participant) -> None:
    if not settings.SHEET_SYNC_URL:
        return

    payload = json.dumps(
        {
            "secret": settings.SHEET_SYNC_SECRET,
            "entryType": participant.entry_type,
            "genre": participant.genre,
            "name": participant.name,
            "phone": participant.phone,
        }
    ).encode()

    thread = threading.Thread(target=_send, args=(payload,), daemon=True)
    thread.start()


def _send(payload: bytes) -> None:
    req = urllib.request.Request(
        settings.SHEET_SYNC_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _opener.open(req, timeout=_TIMEOUT_SECONDS) as res:
            res.read()
    except OSError as e:
        logger.warning("점수 시트 도착 표시 반영 실패: %s", e)
