import io
import uuid

from openpyxl import load_workbook

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.test import TestCase

from checkin.admin_views import OPERATIONS_GROUP_NAME
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


class AdminSecurityRegressionTests(TestCase):
    """코드 리뷰(2026-08-30, PR #61)에서 발견된 실제 버그들에 대한 회귀 테스트.
    전부 실제로 재현/수정을 확인한 것들이라, 나중에 누가 관련 코드를 다시
    건드릴 때 조용히 되돌아가지 않도록 여기 고정해둔다."""

    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser("root", "root@example.com", "pass12345")
        self.ops_user = User.objects.create_user("ops1", email="ops1@example.com", password="x", is_staff=True)
        Group.objects.get_or_create(name=OPERATIONS_GROUP_NAME)[0].user_set.add(self.ops_user)
        self.staff_user = User.objects.create_user("staff1", email="staff1@example.com", password="x", is_staff=True)
        self.target = User.objects.create_user("kim", email="kim@example.com", password="x", is_staff=True)

    def test_add_user_flow_does_not_crash(self):
        # AccountUserAdmin.save_related()가 add_form(role 필드 없음)에서도
        # cleaned_data["role"]을 무조건 읽어서 "+ 계정 초대"가 KeyError로
        # 500이 났었다.
        self.client.login(username="root", password="pass12345")
        resp = self.client.post("/admin/auth/user/add/", {
            "username": "newstaff", "password1": "Xk8f2m9qLp!", "password2": "Xk8f2m9qLp!",
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        User = get_user_model()
        self.assertTrue(User.objects.filter(username="newstaff").exists())

    def test_password_reset_requires_superuser(self):
        # send_password_reset이 admin_view()(=로그인한 스태프)만 확인해서,
        # 최하위 권한 스태프도 아무 계정에나 재설정 메일을 발송시킬 수 있었다.
        self.client.login(username="staff1", password="x")
        resp = self.client.post(f"/admin/auth/user/{self.target.pk}/send-password-reset/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_works_for_superuser(self):
        self.client.login(username="root", password="pass12345")
        resp = self.client.post(f"/admin/auth/user/{self.target.pk}/send-password-reset/", follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_ops_user_cannot_self_promote_to_superuser(self):
        # auth.change_user 권한이 "운영진" 그룹에 부여되는 미래 상황을 가정 —
        # 그래도 role=super는 저장 시점에 서버에서 막혀야 한다.
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        User = get_user_model()
        ct = ContentType.objects.get_for_model(User)
        perm = Permission.objects.get(content_type=ct, codename="change_user")
        self.ops_user.user_permissions.add(perm)

        self.client.login(username="ops1", password="x")
        resp = self.client.post(f"/admin/auth/user/{self.ops_user.pk}/change/", {
            "first_name": "", "email": "ops1@example.com", "role": "super", "is_active": "on",
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.ops_user.refresh_from_db()
        self.assertFalse(self.ops_user.is_superuser)
        self.assertTrue(self.ops_user.groups.filter(name=OPERATIONS_GROUP_NAME).exists())

    def test_viewer_registration_leaves_genre_blank(self):
        # RegisterForm.genre에 빈 선택지가 없어서, 관람 신청자가 장르를 안
        # 건드려도 브라우저가 첫 옵션(Waacking)을 자동 제출해버렸다.
        Event.objects.create(volume=1, name="테스트", is_active=True)
        resp = self.client.post("/register/", {
            "entry_type": "관람", "name": "박관람", "phone": "010-0000-0000",
            "school": "국민대", "academic_status": "재학",
        })
        self.assertEqual(resp.status_code, 200)
        p = Participant.objects.get(name="박관람")
        self.assertIn(p.genre, (None, ""))

    def test_export_action_with_deleted_event_does_not_crash(self):
        # _first_selected_event가 queryset이 비어도(회차가 그 사이 삭제된
        # 경우) None 체크 없이 event.name 등을 바로 써서 500이 났었다.
        self.client.login(username="root", password="pass12345")
        event = Event.objects.create(volume=2, name="삭제될 회차")
        pk = event.pk
        event.delete()
        resp = self.client.post("/admin/checkin/event/", {
            "action": "export_announcement_excel", "_selected_action": [str(pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)

    def test_delete_selected_action_visible(self):
        # actions.html이 event/participant 액션 바를 통째로 하드코딩된
        # 버튼 몇 개로 바꾸면서, 장고 기본 "삭제" 액션이 화면에서 사라졌었다.
        self.client.login(username="root", password="pass12345")
        Event.objects.create(volume=3, name="목록에 보일 회차")
        html = self.client.get("/admin/checkin/event/").content.decode("utf-8")
        self.assertIn('value="delete_selected"', html)


class MarkRefundActionTests(TestCase):
    """환불 처리 액션 — 입금 완료(PAID) 상태만 환불 대상이 되고, 이미 발급된
    라벨/QR도 함께 회수되는지 (환불 후에도 옛 QR로 체크인 가능한 상태로
    남으면 안 됨)."""

    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser("root", "root@example.com", "pass12345")
        self.event = Event.objects.create(volume=1, name="테스트 회차", is_active=True)
        self.client.login(username="root", password="pass12345")

    def _post_refund(self, participant_ids):
        return self.client.post("/admin/checkin/participant/", {
            "action": "mark_refund", "_selected_action": [str(pid) for pid in participant_ids],
        }, follow=True)

    def test_refund_revokes_existing_label_and_qr(self):
        p = Participant.objects.create(
            id=uuid.uuid4(), event=self.event, entry_type="참가", name="김환불", phone="010-0000-0001",
            genre="Breaking", verification_status="APPROVED", payment_status="PAID",
            label_group="A", label_number=1, label_code="A-1", qr_token=uuid.uuid4(),
        )
        self._post_refund([p.pk])
        p.refresh_from_db()
        self.assertEqual(p.payment_status, "REFUND")
        self.assertIsNone(p.label_group)
        self.assertIsNone(p.label_number)
        self.assertIsNone(p.label_code)
        self.assertIsNone(p.qr_token)

    def test_refund_ignores_non_paid_participants(self):
        # 대기 상태인 사람까지 실수로 같이 선택해도 잘못 바뀌면 안 된다.
        p = Participant.objects.create(
            id=uuid.uuid4(), event=self.event, entry_type="참가", name="이대기", phone="010-0000-0002",
            genre="Breaking", verification_status="PENDING", payment_status="PENDING",
        )
        self._post_refund([p.pk])
        p.refresh_from_db()
        self.assertEqual(p.payment_status, "PENDING")

    def test_refunded_participant_not_reissued_label_or_qr(self):
        # assign_labels_and_tokens()를 다시 돌려도 환불된 사람은 여전히
        # payment_status != PAID이므로 새 라벨/QR을 받지 않아야 한다.
        from checkin.services.assign_labels import assign_labels_and_tokens

        p = Participant.objects.create(
            id=uuid.uuid4(), event=self.event, entry_type="참가", name="박환불", phone="010-0000-0003",
            genre="Breaking", verification_status="APPROVED", payment_status="PAID",
            label_group="A", label_number=1, label_code="A-1", qr_token=uuid.uuid4(),
        )
        self._post_refund([p.pk])
        assign_labels_and_tokens(self.event)
        p.refresh_from_db()
        self.assertIsNone(p.label_code)
        self.assertIsNone(p.qr_token)
