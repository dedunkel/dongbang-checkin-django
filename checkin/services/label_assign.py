"""
라벨 코드(참가 순서) 배정 알고리즘.

이전에 만들어드린 Apps Script 버전(appsscript/Code.gs의 assignGenre_)과
TypeScript/Next.js 버전(lib/labelAssign.ts)에서 검증한 것과 완전히 동일한
로직을 파이썬으로 그대로 옮긴 것입니다. (동명이인 11명 경계, 100명 스트레스
테스트 등으로 이미 검증됐던 로직이라 바꾸지 않았습니다.)

규칙:
- 참가자에게만 배정 (관람객은 이 함수를 호출하지 않음)
- 조 하나에 최대 GROUP_SIZE(기본 10)명
- 랜덤 배정
- 같은 이름을 가진 사람은 같은 조에 들어가지 않도록 재배정
- 기존에 이미 배정된(고정된) 사람은 건드리지 않고, 새로 들어오는 사람만 배정
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

GROUP_SIZE = 10
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass(frozen=True)
class FixedEntry:
    id: str
    name: str
    group: str
    number: int


@dataclass(frozen=True)
class FreshEntry:
    id: str
    name: str


@dataclass(frozen=True)
class LabelSlot:
    group: str
    number: int


def _letter_at(i: int) -> str:
    if i < 26:
        return LETTERS[i]
    return LETTERS[i // 26 - 1] + LETTERS[i % 26]


def _shuffle(items: list, rng: Callable[[], float]) -> list:
    a = list(items)
    for i in range(len(a) - 1, 0, -1):
        j = int(rng() * (i + 1))
        a[i], a[j] = a[j], a[i]
    return a


class _GroupState:
    __slots__ = ("used", "names")

    def __init__(self):
        self.used: set[int] = set()
        self.names: dict[str, int] = {}


def assign_genre(
    existing: list[FixedEntry],
    fresh: list[FreshEntry],
    rng: Callable[[], float] | None = None,
) -> dict[str, LabelSlot]:
    """
    existing: 이미 배정되어 고정된 사람들 (수동 변경분 포함)
    fresh:    이번에 새로 배정할 사람들
    rng:      테스트에서 결과를 고정하고 싶을 때 시드 있는 난수 함수를 넣을 수 있음
    """
    rng = rng or random.random
    groups: dict[str, _GroupState] = {}

    def ensure_group(g: str) -> _GroupState:
        gr = groups.get(g)
        if gr is None:
            gr = _GroupState()
            groups[g] = gr
        return gr

    for p in existing:
        gr = ensure_group(p.group)
        gr.used.add(p.number)
        gr.names[p.name] = gr.names.get(p.name, 0) + 1

    def next_new_letter() -> str:
        idx = 0
        while _letter_at(idx) in groups:
            idx += 1
        return _letter_at(idx)

    def open_slot(prefer_groups: list[str]) -> LabelSlot:
        for g in prefer_groups:
            gr = ensure_group(g)
            for n in range(1, GROUP_SIZE + 1):
                if n not in gr.used:
                    return LabelSlot(group=g, number=n)
        g = next_new_letter()
        ensure_group(g)
        return LabelSlot(group=g, number=1)

    existing_group_letters = sorted(groups.keys())
    shuffled = _shuffle(fresh, rng)
    result: dict[str, LabelSlot] = {}

    for p in shuffled:
        prefer = existing_group_letters if existing_group_letters else [next_new_letter()]
        slot = open_slot(prefer)
        gr = ensure_group(slot.group)
        gr.used.add(slot.number)
        gr.names[p.name] = gr.names.get(p.name, 0) + 1
        result[p.id] = slot
        if slot.group not in existing_group_letters:
            existing_group_letters.append(slot.group)
            existing_group_letters.sort()

    # 동명이인 충돌 해결 — 새로 배정된 사람만 이동 대상으로 삼는다.
    changed = True
    iterations = 0
    while changed and iterations < 50:
        changed = False
        iterations += 1
        for g in list(groups.keys()):
            gr = groups[g]
            dup_names = [n for n, c in gr.names.items() if c > 1]
            if not dup_names:
                continue
            for dup_name in dup_names:
                movable = next(
                    (p for p in shuffled if p.name == dup_name and result[p.id].group == g), None
                )
                if movable is None:
                    continue
                cur = result[movable.id]
                cur_group = groups[cur.group]
                cur_group.used.discard(cur.number)
                cnt = cur_group.names.get(dup_name, 0) - 1
                if cnt <= 0:
                    cur_group.names.pop(dup_name, None)
                else:
                    cur_group.names[dup_name] = cnt

                candidate_groups = sorted(
                    gg for gg in groups.keys() if gg != g and dup_name not in groups[gg].names
                )
                slot = open_slot(candidate_groups) if candidate_groups else open_slot([])
                slot_group = ensure_group(slot.group)
                slot_group.used.add(slot.number)
                slot_group.names[dup_name] = slot_group.names.get(dup_name, 0) + 1
                result[movable.id] = slot
                changed = True
                break

    return result
