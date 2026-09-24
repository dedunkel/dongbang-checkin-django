from .auth_admin import TIER_LABEL, _tier_of
from .models import Suggestion


def suggestion_notifications(request):
    """상단바 알림 벨에 들어갈 데이터. base_site.html이 모든 관리자 화면에서
    확장되므로 이 컨텍스트 프로세서는 전역(비-admin 공개 페이지 포함)에서
    호출된다 — 슈퍼유저가 아니면 즉시 빈 dict를 반환해 쿼리를 안 날린다."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.is_superuser:
        return {}

    suggestions = list(Suggestion.objects.select_related("author").order_by("-created_at")[:20])
    rows = []
    unread_count = 0
    for s in suggestions:
        if not s.is_read:
            unread_count += 1
        if s.author_id:
            author_name = s.author.get_full_name() or s.author.get_username()
            role_label = TIER_LABEL[_tier_of(s.author)]
        else:
            author_name = "(삭제된 계정)"
            role_label = ""
        rows.append(
            {
                "obj": s,
                "author_name": author_name,
                "role_label": role_label,
                "preview": s.content[:50],
            }
        )

    return {
        "dbbt_suggestions": rows,
        "dbbt_suggestions_unread_count": unread_count,
    }
