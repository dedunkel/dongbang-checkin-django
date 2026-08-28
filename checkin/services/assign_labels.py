"""
승인(verification_status=APPROVED, 참가자만) + 입금 확인(payment_status=PAID)된
사람들 중 아직 라벨/토큰이 없는 사람에게 라벨 코드와 QR 토큰을 발급합니다.
이미 처리된 사람은 건드리지 않으므로 몇 번을 다시 실행해도 안전합니다.
(Next.js 버전의 app/api/labels/assign/route.ts, Apps Script 버전의
assignAndIssue_와 동일한 정책)
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from django.db import transaction

from checkin.models import Event, Participant
from checkin.services.label_assign import FixedEntry, FreshEntry, assign_genre


def assign_labels_and_tokens(event: Event) -> dict:
    all_participants = list(Participant.objects.filter(event=event))

    # --- 1. 장르별 라벨 배정 ---
    by_genre: dict[str, dict] = defaultdict(lambda: {"existing": [], "fresh": []})
    for p in all_participants:
        if p.entry_type != "참가":
            continue
        genre = p.genre or "미지정"
        bucket = by_genre[genre]
        if p.label_code:
            bucket["existing"].append(
                FixedEntry(id=str(p.id), name=p.name, group=p.label_group, number=p.label_number)
            )
        elif p.verification_status == "APPROVED" and p.payment_status == "PAID":
            bucket["fresh"].append(FreshEntry(id=str(p.id), name=p.name))

    label_updates: dict[str, dict] = {}
    for bucket in by_genre.values():
        if not bucket["fresh"]:
            continue
        assigned = assign_genre(bucket["existing"], bucket["fresh"])
        for pid, slot in assigned.items():
            label_updates[pid] = {"group": slot.group, "number": slot.number, "code": f"{slot.group}-{slot.number}"}

    # --- 2. QR 토큰 발급 (참가/관람 공통) ---
    token_updates: dict[str, uuid.UUID] = {}
    for p in all_participants:
        if p.qr_token:
            continue
        eligible = p.payment_status == "PAID" and (p.entry_type == "관람" or p.verification_status == "APPROVED")
        if not eligible:
            continue
        token_updates[str(p.id)] = uuid.uuid4()

    # --- 3. DB 반영 ---
    ids = set(label_updates.keys()) | set(token_updates.keys())
    if ids:
        by_id = {str(p.id): p for p in all_participants}
        with transaction.atomic():
            to_update = []
            for pid in ids:
                p = by_id[pid]
                label = label_updates.get(pid)
                token = token_updates.get(pid)
                if label:
                    p.label_group = label["group"]
                    p.label_number = label["number"]
                    p.label_code = label["code"]
                if token:
                    p.qr_token = token
                to_update.append(p)
            Participant.objects.bulk_update(
                to_update, ["label_group", "label_number", "label_code", "qr_token"]
            )

    return {"labeled": len(label_updates), "issued": len(token_updates)}
