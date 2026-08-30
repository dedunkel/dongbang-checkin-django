import io
import uuid

from openpyxl import load_workbook

from django.test import TestCase

from checkin.models import Event, Participant
from checkin.services.announcement_export import build_announcement_file
from checkin.services.application_confirmation_export import build_application_confirmation_file
from checkin.services.event_excel_export import find_duplicate_labels, mask_name, mask_phone, remarks_for
from checkin.services.label_assign import GROUP_SIZE, FixedEntry, FreshEntry, assign_genre
from checkin.services.score_sheet_export import build_score_sheet_file


def mulberry32(seed: int):
    """TypeScript 버전 테스트와 같은 계열의 시드 고정 PRNG (파이썬으로 이식, 자체 검증용)."""
    state = {"t": seed}

    def rng() -> float:
        state["t"] = (state["t"] + 0x6D2B79F5) & 0xFFFFFFFF
        t = state["t"]
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t = (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    return rng


class AssignGenreTests(TestCase):
    """
    lib/labelAssign.ts (Next.js 버전) / Code.gs (Apps Script 버전)와 동일한 시나리오로
    검증합니다 — 세 구현이 전부 같은 규칙을 지키는지 교차 확인하는 목적도 있습니다.
    """

    def test_25_names_with_3_duplicates_across_seeds(self):
        names = [f"사람{i}" for i in range(22)] + ["홍길동", "홍길동", "홍길동"]
        fresh = [FreshEntry(id=f"p{i}", name=n) for i, n in enumerate(names)]

        for seed in range(20):
            result = assign_genre([], fresh, mulberry32(seed))
            self.assertEqual(len(result), len(fresh))

            by_group: dict[str, list[str]] = {}
            for p in fresh:
                by_group.setdefault(result[p.id].group, []).append(p.name)

            for g, names_in_group in by_group.items():
                self.assertLessEqual(len(names_in_group), GROUP_SIZE)
                self.assertLessEqual(names_in_group.count("홍길동"), 1)

                nums = [result[p.id].number for p in fresh if result[p.id].group == g]
                self.assertEqual(len(set(nums)), len(nums))

    def test_fresh_duplicate_of_existing_fixed_entry_avoids_that_group(self):
        existing = [
            FixedEntry(id="e1", name="김철수", group="A", number=1),
            FixedEntry(id="e2", name="이영희", group="A", number=2),
        ]
        fresh = [
            FreshEntry(id="n1", name="김철수"),
            FreshEntry(id="n2", name="박민수"),
            FreshEntry(id="n3", name="최수정"),
        ]
        for seed in range(20):
            result = assign_genre(existing, fresh, mulberry32(seed))
            self.assertNotEqual(result["n1"].group, "A")

    def test_11_people_split_into_2_groups(self):
        fresh = [FreshEntry(id=f"p{i}", name=f"이름{i}") for i in range(11)]
        result = assign_genre([], fresh, mulberry32(1))
        groups_used = {slot.group for slot in result.values()}
        self.assertEqual(len(groups_used), 2)

    def test_100_person_stress_no_duplicate_names_in_any_group(self):
        pool = ["김민준", "이서연", "박도윤", "최지우", "정하은", "강서준", "조수아", "윤예준", "장하윤", "임시우"]
        pool_rng = mulberry32(999)
        fresh = [FreshEntry(id=f"p{i}", name=pool[int(pool_rng() * len(pool))]) for i in range(100)]

        result = assign_genre([], fresh, mulberry32(12345))
        by_group: dict[str, list[str]] = {}
        for p in fresh:
            by_group.setdefault(result[p.id].group, []).append(p.name)

        for names_in_group in by_group.values():
            counts: dict[str, int] = {}
            for n in names_in_group:
                counts[n] = counts.get(n, 0) + 1
            for c in counts.values():
                self.assertLessEqual(c, 1)

        self.assertEqual(len(result), 100)


class ExportMaskingHelperTests(TestCase):
    """마스킹/비고 헬퍼는 세 내보내기 전부가 공유하는 로직이라(#30), 순수 함수
    수준에서 따로 검증해둔다."""

    def test_mask_name_with_dancer_name(self):
        self.assertEqual(mask_name("김철수/비보이스파크"), "김*수/비보이스파크")

    def test_mask_name_without_separator(self):
        self.assertEqual(mask_name("김철수"), "김*수")

    def test_mask_name_dancer_same_as_real(self):
        self.assertEqual(mask_name("김철수/김철수"), "김*수/김*수")

    def test_mask_phone_standard_11_digits(self):
        self.assertEqual(mask_phone("010-1234-5678"), "010-****-5678")

    def test_mask_phone_non_standard_left_as_is(self):
        self.assertEqual(mask_phone("02-123-4567"), "02-123-4567")

    def test_remarks_for_flags_unpaid_and_unverified(self):
        p = Participant(entry_type="참가", payment_status="PENDING", verification_status="PENDING")
        self.assertEqual(remarks_for(p), "미입금/학적 인증 필요")

    def test_remarks_for_empty_when_all_clear(self):
        p = Participant(entry_type="참가", payment_status="PAID", verification_status="APPROVED")
        self.assertEqual(remarks_for(p), "")

    def test_remarks_for_viewer_ignores_verification(self):
        # 관람은 학적검수 대상이 아니라, 미승인 상태여도 비고에 안 뜬다.
        p = Participant(entry_type="관람", payment_status="PENDING", verification_status="PENDING")
        self.assertEqual(remarks_for(p), "미입금")


class EventExcelExportTests(TestCase):
    """엑셀 내보내기 3종을 공용 모듈(event_excel_export.py)로 합친 리팩터링(#30)이
    기존 동작(탭 구성/마스킹/라벨 유무 필터링)을 그대로 유지하는지 확인."""

    def setUp(self):
        self.event = Event.objects.create(volume=99, name="테스트 회차")
        # 라벨이 배정된 확정 참가자 — 공지용/점수표 탭에 나와야 한다.
        self.labeled = Participant.objects.create(
            id=uuid.uuid4(), event=self.event, entry_type="참가", genre="Breaking",
            name="김철수/비보이스파크", phone="010-1234-5678", school="국민대학교",
            academic_status="재학", label_group="A", label_number=1, label_code="A-1",
            payment_status="PAID", verification_status="APPROVED", checkin_status="CHECKED_IN",
        )
        # 라벨이 아직 없는 신청자 — 신청 확인용 명단에는 나오되, 공지용/점수표에는 빠져야 한다.
        self.unlabeled = Participant.objects.create(
            id=uuid.uuid4(), event=self.event, entry_type="참가", genre="Breaking",
            name="박준혁", phone="010-2222-3333", payment_status="PENDING",
        )
        self.viewer = Participant.objects.create(
            id=uuid.uuid4(), event=self.event, entry_type="관람",
            name="최유진", phone="010-4444-5555", payment_status="PAID",
        )

    def _sheet_rows(self, wb, sheet_title):
        ws = wb[sheet_title]
        # 1행 제목, 2행 헤더, 3행부터 데이터.
        return [[c.value for c in row] for row in ws.iter_rows(min_row=3)]

    def test_announcement_excel_masks_and_excludes_unlabeled(self):
        filename, content = build_announcement_file(self.event)
        self.assertTrue(filename.endswith(".xlsx"))
        wb = load_workbook(filename=io.BytesIO(content))

        self.assertIn("브레이킹", wb.sheetnames)
        self.assertIn("관람", wb.sheetnames)

        rows = self._sheet_rows(wb, "브레이킹")
        self.assertEqual(len(rows), 1, "라벨 없는 참가자는 공지용 명단 탭에서 빠져야 함")
        self.assertEqual(rows[0][1], "김*수/비보이스파크")  # 이름 마스킹
        self.assertEqual(rows[0][2], "010-****-5678")  # 연락처 마스킹
        self.assertEqual(rows[0][5], "A-1")  # 순서(라벨 코드)

        viewer_rows = self._sheet_rows(wb, "관람")
        self.assertEqual(len(viewer_rows), 1)
        self.assertEqual(viewer_rows[0][1], "최*진")

    def test_score_sheet_excel_no_masking_and_marks_paid_checked_in(self):
        filename, content = build_score_sheet_file(self.event)
        wb = load_workbook(filename=io.BytesIO(content))
        rows = self._sheet_rows(wb, "브레이킹")
        self.assertEqual(len(rows), 1, "라벨 없는 참가자는 점수표 탭에서 빠져야 함")
        self.assertEqual(rows[0][1], "김철수/비보이스파크")  # 마스킹 없음
        self.assertEqual(rows[0][2], "010-1234-5678")
        self.assertEqual(rows[0][6], "O")  # 입금 여부
        self.assertEqual(rows[0][7], "O")  # 도착 여부

    def test_application_confirmation_includes_unlabeled_participants(self):
        filename, content = build_application_confirmation_file(self.event)
        wb = load_workbook(filename=io.BytesIO(content))
        rows = self._sheet_rows(wb, "브레이킹")
        names = {row[1] for row in rows}
        self.assertEqual(len(rows), 2, "라벨 유무와 무관하게 신청자 전원이 나와야 함")
        self.assertIn("김*수/비보이스파크", names)
        self.assertIn("박*혁", names)  # 라벨 없는 신청자도 포함, 마스킹은 그대로 적용
        # "순서" 컬럼이 없는 게 이 내보내기의 특징 — 헤더 개수로 확인.
        self.assertEqual(len(rows[0]), 6)

    def test_find_duplicate_labels_empty_when_no_conflict(self):
        self.assertEqual(find_duplicate_labels(self.event), [])
