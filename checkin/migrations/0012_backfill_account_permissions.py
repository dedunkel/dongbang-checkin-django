from django.db import migrations

OPERATIONS_GROUP_NAME = "운영진"

NEW_EVENT_PERMS = ["view_event", "change_event", "add_event", "run_label_assign", "push_order_to_sheet"]
NEW_PARTICIPANT_PERMS = [
    "view_participant", "change_participant", "add_participant",
    "approve_verification", "mark_paid", "mark_refund", "swap_labels",
]


def backfill(apps, schema_editor):
    """계정 관리가 "스태프/운영진/슈퍼유저" 3단계 고정 역할에서 계정별
    개별 권한 체크박스로 바뀌면서, 그동안 암묵적으로 되던 접근이 배포 직후
    갑자기 끊기지 않도록 현재 상태를 새 권한 체계로 그대로 옮겨 담는다.
    """
    User = apps.get_model("auth", "User")
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    event_ct = ContentType.objects.filter(app_label="checkin", model="event").first()
    participant_ct = ContentType.objects.filter(app_label="checkin", model="participant").first()
    if event_ct is None or participant_ct is None:
        return

    use_scanner_perm = Permission.objects.filter(
        content_type=participant_ct, codename="use_scanner"
    ).first()
    if use_scanner_perm is not None:
        # 지금까지는 스태프 등급과 무관하게 로그인만 되면 누구나 체크인
        # 스캐너를 쓸 수 있었다 — 이 기준을 새 권한 체계에서도 그대로 잇는다.
        for user in User.objects.filter(is_staff=True, is_superuser=False):
            user.user_permissions.add(use_scanner_perm)

    op_group = Group.objects.filter(name=OPERATIONS_GROUP_NAME).first()
    if op_group is None:
        return

    # 그동안 "운영진" 그룹에 실제로 배정돼 있던 권한(관리자가 그룹 화면에서
    # 수동으로 체크해둔 것들, 예: export_sensitive_data)을 각 멤버 개인
    # 권한으로 그대로 복사해서 기존에 쓰던 기능이 끊기지 않게 한다.
    group_perms = list(op_group.permissions.all())

    new_codenames = NEW_EVENT_PERMS + NEW_PARTICIPANT_PERMS
    new_perms = list(
        Permission.objects.filter(
            content_type__in=[event_ct, participant_ct], codename__in=new_codenames
        )
    )

    for user in op_group.user_set.all():
        user.user_permissions.add(*group_perms)
        # 이번에 새로 도입하는 권한 게이트(학적검수 승인 · 입금 확인 · 환불 ·
        # 라벨 맞바꾸기 · 라벨/QR 발급 · 점수 시트 반영 등)는 이전엔 아예
        # 체크 자체가 없던 곳이라, 지금 운영진으로 쓰고 있는 사람들에게는
        # 자동으로 부여해서 배포 직후 갑자기 막히는 일이 없게 한다.
        user.user_permissions.add(*new_perms)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("checkin", "0011_alter_event_options_alter_participant_options"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
