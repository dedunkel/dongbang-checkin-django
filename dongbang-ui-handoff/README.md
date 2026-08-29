# 동방배틀 vol.33 체크인 시스템 — UI 리디자인 핸드오프

레포: https://github.com/dedunkel/dongbang-checkin-django (Django)

이 폴더는 "클린" 방향으로 확정한 UI 목업을 실제 Django 코드에 반영하기 위한
자료입니다. `screens/` 안의 각 `.html` 파일은 완성된 마크업 + 인라인 CSS라서,
Django 템플릿 문법(`{{ }}`, `{% %}`)으로 바꿔 끼우는 정도로 거의 그대로 옮길 수
있습니다. 이름/전화번호/학교 등 화면에 보이는 값은 전부 예시 데이터입니다.

## 적용 방법 (Claude Code에게)

1. `tokens.css`의 디자인 토큰(라이트/다크 oklch 값, 폰트)을 프로젝트의 공통
   스타일(`checkin/templates/checkin/base.html`의 `<style>` 등)에 반영해주세요.
   지금 `base.html`은 다크 전용 고정 팔레트(`#0a0a0a` 등)라서, 토큰 기반으로
   바꾸면서 라이트/다크를 다 지원하게 만들지, 다크 하나로 유지할지는 팀에서
   정해주세요 — 목업은 라이트/다크 두 벌 다 있으니 둘 다 가능합니다.
2. `assets/logo.png`를 정적 파일로 추가하고, 아래 표에 있는 화면들에 작게
   넣어주세요 (참가자용 화면은 헤더 근처, 스태프 화면은 상단바 왼쪽).
3. 아래 "화면 매핑" 표를 따라 각 목업 파일을 대응하는 실제 템플릿/뷰/관리자
   화면에 반영해주세요. "상태" 열이 있는 화면들(신청완료, QR 없음, 이미
   체크인 등)은 전부 지금 코드의 `{% if %}` 분기와 1:1로 대응합니다 — 새 로직이
   필요한 게 아니라 각 분기의 마크업만 바꾸면 됩니다.
4. 회차 관리/참가자 관리/계정 관리/상세/추가/로그인 화면은 지금은 전부
   Django 기본 `/admin/`입니다 (`config/urls.py` 주석 참고). 이번 리디자인의
   핵심 요청이 "이 admin 화면을 새로 만드는 것"이었으므로, `django.contrib.admin`
   자체를 걷어내고 새 뷰/템플릿으로 만들지, 아니면 admin의 템플릿만
   오버라이드(`templates/admin/...`)해서 스타일만 새 걸로 입힐지 판단이
   필요합니다 — 후자가 작업량이 훨씬 적고, 지금 있는 액션(라벨 발급, 점수
   시트 반영, CSV/엑셀 다운로드 등)을 그대로 재사용할 수 있어 추천합니다.
5. 표에 없는 파일은 없습니다 — `screens/` 폴더의 47개 파일이 곧 전체 화면
   목록입니다.

## 화면 매핑

### 참가자용 (모바일, 로그인 불필요)

| 목업 파일 | 실제 코드 | 비고 |
|---|---|---|
| `Main.html` / `MainCleanDark.html` | `checkin/templates/checkin/home.html` (`views.home`) | |
| `RegisterClean.html` / `Dark` | `checkin/templates/checkin/register.html` (`views.register_view`, 기본 상태) | 이름 필드 라벨 "이름 / 댄서명", 장르는 영문 표기(`Genre.choices`의 영문 값) |
| `RegisterSuccessClean.html` / `Dark` | 같은 템플릿, `success` 분기 | |
| `RegisterEmptyClean.html` / `Dark` | 같은 템플릿, `no_active_event` 분기 | |
| `QrClean.html` / `Dark` | `checkin/templates/checkin/qr.html` (`views.qr_view`, 기본 상태) | |
| `QrNotFoundClean.html` / `Dark` | 같은 템플릿, `not_found` 분기 | |
| `QrCheckedInClean.html` / `Dark` | 같은 템플릿, `participant.checkin_status == CHECKED_IN` 분기 | |
| `ScanClean.html` / `Dark` | `checkin/templates/checkin/scan.html` (`views.scan_view`/`scan_confirm`, 미체크인 상태) | |
| `ScanNotFoundClean.html` / `Dark` | 같은 템플릿, `not_found` 분기 | |
| `ScanCheckedInClean.html` / `Dark` | 같은 템플릿, 체크인 완료 상태 | |
| `StaffLoginClean.html` / `Dark` | Django 기본 admin 로그인 (`admin:login`) | 지금은 커스텀 템플릿이 없음 — `registration/login.html` 오버라이드 필요 |

### 스태프 — 현장 체크인 스캐너 (로그인 필요)

| 목업 파일 | 실제 코드 | 비고 |
|---|---|---|
| `CheckinClean.html` / `Dark` | `checkin/templates/checkin/checkin.html` (`views.checkin_view`) 기본 상태 + 하단 수동 검색 (`participant_search_api`) | |
| `CheckinFoundClean.html` / `Dark` | `qr_lookup_api` FOUND, 체크인 확정 전 | |
| `CheckinAlreadyClean.html` / `Dark` | 이미 체크인된 참가자를 스캔한 경우 | |
| `CheckinNotFoundClean.html` / `Dark` | `qr_lookup_api` NOT_FOUND | |
| `CheckinCameraOffClean.html` / `Dark` | 카메라 권한 거부/미지원 시 폴백 | |

### 스태프 — 운영진 대시보드 (지금은 Django 기본 `/admin/`, 이번에 새로 디자인)

| 목업 파일 | 실제 코드 | 비고 |
|---|---|---|
| `EventsClean.html` / `Dark` | `EventAdmin` changelist (`checkin/admin.py`) | 액션 ④⑤ = `run_label_assign`, `push_order_to_sheet`; 내보내기 5종 = `export_application_confirmation_excel`, `export_announcement_excel`, `export_qr_send_list`(운영진 전용, 신규), `export_score_sheet_excel`(운영진 전용), `export_event_csv`(운영진 전용) — "운영진 전용"은 `has_perm("checkin.export_sensitive_data")` 기준이며 슈퍼유저는 항상 통과 |
| `EventDetailClean.html` / `Dark` | `EventAdmin` change form | 필드: `volume`, `name`, `is_active`, `sheet_sync_url`. 하단 삭제 경고 문구는 `EventAdmin.delete_queryset`의 메시지와 동일하게 맞춤 |
| `EventAddClean.html` / `Dark` | `EventAdmin` add form | |
| `ParticipantsClean.html` / `Dark` | `ParticipantAdmin` changelist | 컬럼은 `list_display` 그대로 + 입금자명 추가. 필터는 `list_filter` 그대로. 액션 = `approve_verification`, `mark_paid`, `swap_labels` |
| `ParticipantDetailClean.html` / `Dark` | `ParticipantAdmin` change form | `fieldsets` 그대로: 기본정보 / 신청정보 / 검수 / 라벨 / QR·체크인 / 기타. `readonly_fields = (id, qr_token, created_at)` |
| `ParticipantAddClean.html` / `Dark` | `ParticipantAdmin` add form | 저장 전이라 라벨·QR·체크인 영역은 비활성 표시 (실제로는 라벨은 회차 관리의 "라벨/QR 발급 실행"에서 일괄 배정됨 — `assign_labels_and_tokens`) |
| `AccountsClean.html` / `Dark` | **신규** — Django `User`/`Group` 모델 기반 스태프 계정 관리, 3단계 권한 | 지금은 이 화면 자체가 없음. 권한은 3단계: **스태프**(`is_staff=True`만, 그룹 없음 — 체크인 스캐너만 접근 가능, Event/Participant 관리자 화면은 Django 권한 시스템이 자동 차단), **운영진**("운영진" `Group`에 소속 — `checkin.export_sensitive_data` 커스텀 권한(`Event.Meta.permissions`) + Event/Participant view·change 권한 보유, 마스킹 없는 내보내기 전부 가능), **슈퍼유저**(`is_superuser=True` — 모든 `has_perm` 자동 통과 + 계정/권한 관리). 코드 수정 없이 `/admin`에서 그룹 배정만으로 운영진 계정을 늘리고 줄일 수 있음 |
| `ParticipantsTablet.html` | 반응형 참고용 (실제 화면 아님) | 태블릿 폭(834px)에서 표가 가로 스크롤 + 이름 열 고정되는 패턴 예시. 회차/계정 관리 표에도 동일 패턴 적용 권장 |

## 참고 사항

- 장르 값은 `Genre.choices`(`Waacking/왁킹`, `Popping/팝핑`, `Locking/락킹`,
  `House/하우스`, `Krump/크럼프`, `Hiphop/힙합`, `Breaking/브레이킹`) 그대로이며,
  참가자용 화면에는 영문 값만 노출합니다.
- 참가자용 화면(신청/QR/체크인)은 `base.html`이 이미 `main { max-width: 640px;
  margin: 0 auto; width: 100%; }` 구조라 아이패드·노트북에서도 카드가 가운데
  정렬될 뿐 깨지지 않습니다 — 이 부분은 손댈 필요 없습니다.
- 스태프 대시보드(회차/참가자/계정 관리)는 데스크톱 전제의 넓은 표라
  좁은 화면에서는 `ParticipantsTablet.html`의 가로 스크롤 패턴을 적용해주세요.
- **QR 발송용 명단 다운로드**(`export_qr_send_list`, 신규): 이름/연락처/구분/장르/
  개인별 QR 링크/발송 안내 문구를 담은 CSV를 내려받는 액션입니다. 문자·카톡
  대량발송 도구에 그대로 업로드하는 용도라, 목록 화면(`EventsClean.html`)과
  상세 화면(`EventDetailClean.html`)의 "내보내기" 영역에 다른 명단 다운로드
  버튼들과 나란히 배치했습니다. QR이 아직 발급 안 된 참가자는 명단에서
  자동 제외되고 몇 명 제외됐는지 경고로 안내됩니다 — 별도 확인 UI를
  새로 만들 필요는 없고, 지금 있는 메시지 배너(상단 `{% if messages %}`)로
  충분합니다.
- 권한 표기가 3단계(스태프/운영진/슈퍼유저)로 바뀌면서, 예전에 "슈퍼유저
  전용"으로 표기했던 점수표·CSV 백업 내보내기 버튼도 이제 "운영진"으로
  라벨이 바뀌었습니다 — 실제로는 슈퍼유저도 항상 통과하지만, 버튼에 뜨는
  문구는 실제로 필요한 최소 권한(운영진)을 기준으로 맞췄습니다.
