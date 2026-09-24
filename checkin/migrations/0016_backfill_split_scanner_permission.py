from django.db import migrations

NEW_CODENAMES = ["scan_qr", "search_manual"]


def backfill(apps, schema_editor):
    """"체크인 스캐너 사용" 하나였던 권한을 "QR 스캔"/"수동 검색" 두 개로
    쪼갰다 — 기존에 use_scanner를 갖고 있던 계정은 두 기능을 다 쓰고
    있었으므로, 배포 직후 갑자기 스캐너 화면이 반쪽만 보이지 않도록
    두 권한을 모두 부여해 이전과 동일한 접근 범위를 유지한다. 이후
    슈퍼유저가 계정별로 필요하면 하나씩 꺼줄 수 있다."""
    User = apps.get_model("auth", "User")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    participant_ct = ContentType.objects.filter(app_label="checkin", model="participant").first()
    if participant_ct is None:
        return

    old_perm = Permission.objects.filter(content_type=participant_ct, codename="use_scanner").first()
    if old_perm is None:
        return

    new_perms = list(
        Permission.objects.filter(content_type=participant_ct, codename__in=NEW_CODENAMES)
    )
    if not new_perms:
        return

    users = User.objects.filter(user_permissions=old_perm) | User.objects.filter(
        groups__permissions=old_perm
    )
    for user in users.distinct():
        user.user_permissions.add(*new_perms)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("checkin", "0015_alter_participant_options"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
