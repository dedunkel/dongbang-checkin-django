# 동방배틀 체크인 시스템 (Django/파이썬 버전)

앞서 드린 Next.js/TypeScript 버전과 기능은 동일하고, 파이썬(Django)으로 만든
버전입니다. 신청 접수는 이미 쓰고 계신 구글 폼을 그대로 쓰고, 그 뒤 검수 →
라벨/QR 발급 → 현장 체크인은 이 서버가 맡습니다.

## Next.js 버전과 다른 점 (왜 다른지)

- **운영진 대시보드가 따로 없고, Django 기본 관리자 페이지(`/admin/`)를 그대로
  씁니다.** Django에는 모델(회차, 참가자)만 등록하면 목록·검색·필터·수정 화면이
  자동으로 생기는 관리자 페이지가 내장돼 있어서, 굳이 같은 기능을 직접 만들
  이유가 없었습니다. "회차 만들기"는 이벤트 추가, "검수/입금 처리"는 참가자
  목록에서 상태 필드 클릭, "라벨/QR 발급"과 "CSV 백업"은 회차 목록의 액션
  버튼으로 되어 있습니다. 아래 "운영 흐름"에 화면 위치를 정리해뒀습니다.
- **`/checkin`, `/admin`에 진짜 로그인이 걸려 있습니다.** Next.js 버전
  README에는 "관리자 인증이 없다"는 걸 배포 전 보완할 점으로 적어드렸었는데,
  Django는 로그인 시스템이 기본 내장이라 이번 버전은 처음부터 스태프 계정으로
  로그인해야 체크인 스캐너와 관리자 페이지에 들어갈 수 있게 만들었습니다
  (`python manage.py createsuperuser`로 계정을 만듭니다).
- 나머지(라벨 코드 랜덤 배정+동명이인 분리 알고리즘, QR 발급/스캔, 구글 폼 연동,
  회차별 데이터 분리)는 로직 그대로 파이썬으로 옮긴 것입니다.
- 학적증명서 OCR 자동 대조는 이번에도 범위 밖입니다 (이전과 동일한 결정).
- 참가자는 장르를 하나만 선택합니다(`Participant.genre`가 단일 값 필드). 한
  사람이 여러 장르에 동시 신청하는 것은 의도적으로 지원하지 않는 제약입니다 —
  장르별 조 배정(`checkin/services/assign_labels.py`)과 라벨 코드가 "신청자당
  장르 하나"를 전제로 설계돼 있습니다.

## 기술 스택

- **Django 5** (Python 3.11+)
- **PostgreSQL** (`psycopg` 드라이버) — `DATABASE_URL`을 비워두면 로컬
  SQLite로 자동 전환되어 설치 없이 바로 켜볼 수도 있습니다.
- QR 생성: `qrcode` 라이브러리 (서버에서 PNG 생성) / QR 스캔: `jsQR`
  (체크인 페이지에서 카메라 프레임을 읽는 용도, CDN으로 불러옴)
- 테스트: Django 기본 테스트러너(`manage.py test`, 라벨 배정 알고리즘 단위
  테스트) + 실제 로컬 Postgres에 대고 돌린 통합 테스트로 전체 흐름(구글 폼
  가져오기 → 중복 방지 → 검수 → 라벨/QR 발급 → 체크인 → 중복 체크인 방지 →
  검색 → CSV 백업, 그리고 로그인 없이는 `/checkin`에 못 들어가는지)까지 확인.

## 로컬에서 실행하기

### 1. 준비물

- Python 3.11 이상
- PostgreSQL (로컬 설치 또는 Supabase/Neon 같은 무료 클라우드 Postgres) —
  없어도 SQLite로 우선 켜볼 수 있습니다.

### 2. 설치

```bash
python -m venv venv
source venv/bin/activate   # Windows는 venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env
# .env 안의 DATABASE_URL을 본인 Postgres 접속 정보로 수정 (또는 그 줄을 지우면 SQLite 사용)
```

### 3. DB 테이블 생성 + 스태프 계정 만들기

```bash
python manage.py migrate
python manage.py createsuperuser   # 운영진 로그인 계정 (관리자 페이지 + 체크인 스캐너 접속용)
```

### 4. 개발 서버 실행

```bash
python manage.py runserver
```

<http://localhost:8000> 접속. `/admin/`에서 방금 만든 계정으로 로그인하세요.

### 5. 테스트

```bash
python manage.py test checkin   # 라벨 배정 알고리즘 단위 테스트
python manage.py check          # 설정/모델 오류 체크
```

## 구글 폼 연동 (신청 접수)

Next.js 버전과 방식은 동일하고, 붙이는 스크립트만 이 버전(`google-apps-script/
Forwarder.gs`)을 씁니다.

1. 서버 쪽: `.env`에 `IMPORT_SECRET`을 아무 랜덤 문자열로 채워둡니다.
2. 구글 폼 응답 시트를 열고 확장 프로그램 > Apps Script.
3. `google-apps-script/Forwarder.gs.example`을 `google-apps-script/Forwarder.gs`로
   복사한 뒤(`.gs`는 `.env`처럼 `.gitignore`에 있어 커밋되지 않습니다 — 실제
   시크릿이 CONFIG에 그대로 들어가기 때문입니다) 그 내용을 통째로 Apps Script에
   붙여넣고, 맨 위 `CONFIG`의 `SERVER_URL`(배포 도메인 +
   `/api/import/google-form/`, 끝 슬래시 포함), `IMPORT_SECRET`(1번과 동일한 값),
   `FORM_COLS`(실제 시트 헤더 이름)를 맞춥니다.
4. 저장 → 트리거(시계 아이콘) 추가 → 함수 `onFormSubmit`, 이벤트 유형
   "양식 제출 시"로 등록 → 권한 승인.
5. 시트를 새로고침하면 "동방배틀 연동" 메뉴가 생깁니다. 트리거를 달기 전에
   이미 쌓여있던 응답이 있다면 "기존 응답 전체 백필"을 눌러서 옮겨줍니다.
   (같은 응답을 여러 번 백필해도 응답 제출 시각(타임스탬프) 기준으로
   중복 없이 건너뜁니다 — 응답 시트에서 행을 지워 다른 행들이 밀려도
   영향 없습니다.)

전달되는 값은 폼의 "입금확인" 체크 여부와 무관하게 항상 검수 대기(PENDING)로
들어옵니다 — 실제 확인은 운영진이 관리자 페이지에서 합니다.

## 체크인 → 점수 시트 실시간 반영 (선택)

인포·공연장에서 다 같이 보는 "도착 여부" 점수 시트(구글 폼 응답 시트와는
별도 파일, 장르별 탭으로 구성)가 있다면, 체크인될 때마다 그 시트에도 자동으로
도착 표시가 남도록 연동할 수 있습니다. 방향은 구글 폼 연동과 반대입니다
(Django → 시트).

1. 서버 쪽: `.env`에 `SHEET_SYNC_SECRET`을 아무 랜덤 문자열로 채워둡니다
   (배포 환경 전체에서 공유하는 값이라 한 번만 설정하면 됩니다).
2. 그 점수 시트 파일을 열고 확장 프로그램 > Apps Script.
3. `google-apps-script/SheetSync.gs.example`을 `google-apps-script/SheetSync.gs`로
   복사한 뒤(마찬가지로 `.gs`는 `.gitignore`에 있어 커밋되지 않습니다) 그
   내용을 통째로 붙여넣고, `CONFIG`의 `SECRET`(1번과 동일한 값),
   `GENRE_TAB_MAP`(장르별 탭 이름), `COLS`(실제 헤더 이름)를 맞춥니다.
4. 배포 > 새 배포 > 유형: 웹 앱, 실행 계정: 나, 액세스 권한: 전체 허용 →
   배포하면 나오는 URL(`/exec`로 끝남)을 확인합니다.
5. `/admin/` > **Events**에서 그 회차를 열어 `Sheet sync url` 필드에 4번
   URL을 붙여넣고 저장합니다. **회차마다 새 시트를 새로 배포하게 되므로,
   이 URL은 환경변수가 아니라 회차별 필드입니다** — 매 행사 때마다 `.env`를
   고치거나 재배포할 필요 없이 여기서만 바꾸면 됩니다. 비워두면 그 회차는
   이 기능 없이 체크인만 동작합니다.
6. 참가자 이름+연락처로 그 탭에서 행을 찾아 값을 쓰는 방식이라, 시트의
   이름·연락처 값이 실제 참가자 정보와 일치해야 합니다. 일치하는 행을 못
   찾아도 체크인 자체는 정상 처리되고, 시트 반영만 조용히 실패합니다
   (서버 로그에서 확인 가능).

점수 시트 파일 자체가 아직 없다면, `/admin/` > **Events**에서 "선택 회차:
점수표 엑셀 다운로드 (마스킹 없음, 스태프 내부용)" 액션으로 현재 참가자
데이터 그대로(이름·연락처 마스킹 없음, 입금 여부·도착 여부는 현재 DB
상태로 미리 채워짐) 장르별 탭이 나뉜 엑셀을 받아서, 구글 드라이브에
업로드하면 그대로 점수 시트로 쓸 수 있습니다. 공지용 명단과 달리 이건
스태프 내부용이라 마스킹하지 않습니다.

같은 연동으로 두 가지가 자동/수동으로 반영됩니다.

- **도착 여부** — 체크인이 확정되는 즉시 자동 반영 (실시간).
- **순서**(라벨 코드, 예: `A-1`) — 자동 반영 아님. `/admin/` > **Events**에서
  회차를 체크 → "⑤ 선택 회차: 라벨 순서를 점수 시트에 반영" 액션을 눌러야
  반영됩니다. 라벨을 랜덤 배정(④)한 뒤 필요하면 참가자 상세 화면에서
  `label_group`/`label_number`를 수동으로 조정하고(`label_code`는 이
  둘로부터 자동 계산되므로 직접 안 건드려도 됩니다), 다 끝난 뒤 이
  액션을 눌러 확정된 순서를 한 번에 시트로 보내는 흐름입니다.
  두 사람의 라벨을 서로 바꾸고 싶으면(예: A-1 ↔ A-2), 각자 편집 화면에서
  따로 고치면 중간에 자리가 겹쳐서 저장이 안 됩니다 — `/admin/` >
  **Participants**에서 그 두 명만 체크 → "선택한 참가자 2명의 라벨(조/번호)
  맞바꾸기" 액션을 쓰면 한 번에 안전하게 바뀝니다.

## 운영 흐름

1. `/admin/` 로그인 → **Events**(회차) > **Add event**로 새 회차 생성 (예:
   volume=33, "동방배틀 vol.33", "Is active" 체크). 활성 회차는 항상 하나뿐이며,
   새 회차를 활성화하면 이전 회차는 자동으로 비활성화됩니다. 구글 폼 응답과
   예비 신청 폼(`/register/`) 신청 모두 이 활성 회차에 붙습니다.
2. 참가자/관람객이 구글 폼으로 신청 → Forwarder.gs가 자동으로 서버에 전달.
3. `/admin/` > **Participants**(참가자) 목록에서 학적 검수·입금 확인이 필요한
   사람들을 체크박스로 선택 → 상단 액션 드롭다운에서 "학적검수 승인 처리
   (APPROVED)" / "입금 확인 처리 (PAID)" 실행. (검색창, 회차/구분/장르 등
   필터도 기본 제공됩니다.)
3-1. 라벨을 발급하기 전이라도, 참가자들이 자기 신청 내용이 맞게 접수됐는지
   확인할 수 있게 공지하고 싶다면 **Events**에서 "선택 회차: 신청 참가자
   확인용 공지 엑셀 다운로드" 액션을 씁니다. 공지용 명단과 마찬가지로
   이름/연락처를 마스킹하고 장르별 탭으로 나누지만, 순서 컬럼 없이 그
   장르에 신청한 사람 전원이 나오고, 아직 학적 미승인이거나 입금 전인
   사람은 비고에 "미입금"/"학적 인증 필요"가 표시됩니다(둘 다 해당하면
   "미입금/학적 인증 필요"). 라벨을 이미 발급한 뒤에도 계속 쓸 수 있습니다.
4. `/admin/` > **Events** 목록에서 해당 회차를 체크 → 액션 드롭다운에서
   "④ 선택 회차: 승인자 라벨/QR 발급 실행" 실행. 승인+입금완료된 참가자에게
   라벨 코드, 전원(참가+관람)에게 QR 토큰이 발급됩니다. 몇 번을 다시 실행해도
   이미 처리된 사람은 건드리지 않아 안전합니다. 점수 시트 연동을 켜뒀다면,
   필요시 순서를 수동 조정한 뒤 "⑤ 선택 회차: 라벨 순서를 점수 시트에 반영"
   액션으로 확정된 순서를 시트에 반영합니다.
4-1. 공지용으로 참가/관람 명단과 예선 순서를 공유해야 한다면, 같은 자리의
   "선택 회차: 공지용 명단 엑셀 다운로드" 액션으로 장르별 탭이 나뉜 엑셀
   파일을 받을 수 있습니다. 이름 가운데(본명 부분만, 댄서네임은 그대로),
   연락처 가운데 4자리는 `*`로 가려서 나갑니다. 구글 시트 링크로 공유하고
   싶으면 이 파일을 구글 드라이브에 업로드해서 열면 그대로 구글 시트가
   됩니다.
5. 참가자에게 `/qr/{token}/` 링크를 문자/카카오톡으로 보내줍니다 (자동 발송은
   이번 버전도 구현하지 않았습니다 — 참가자 연락처는 `/admin/`에서 CSV로
   내려받아 발송 도구에 넣어 쓰시면 됩니다. 이메일은 신청 폼에 문항이 없어서
   항상 비어있습니다).
6. **행사 당일**: 스태프가 본인 계정으로 로그인한 상태에서 아이패드/아이폰
   브라우저로 `/checkin/` 접속 → 카메라 자동 실행 → QR 스캔 시 라벨 코드/이름/
   장르가 크게 표시. 같은 QR 재스캔 시 "이미 체크인됨" 표시. QR을 못 보여주는
   사람은 같은 페이지의 "이름/전화번호로 수동 검색"으로 찾아서 수동 체크인.
7. **행사 종료 후**: `/admin/` > **Events**에서 해당 회차를 체크 → "참가자
   CSV 백업 다운로드" 액션으로 데이터를 저장해두고, 기본 제공되는 삭제
   액션으로 그 회차를 삭제하면 참가자 데이터도 함께 정리됩니다(연쇄 삭제).
   다음 회차는 다시 "Add event"로 새로 시작하면 됩니다.

## 배포 (실제 서비스로 만들기)

1. **DB**: [Supabase](https://supabase.com), [Neon](https://neon.tech), 또는 Render
   자체 Postgres에서 무료 Postgres 프로젝트 생성 → connection string을 배포
   환경변수 `DATABASE_URL`에 (sslmode가 붙은 URL도 그대로 지원합니다).
2. **배포**: Django는 Railway, Render, Fly.io, PythonAnywhere 등에서 쉽게
   돌릴 수 있습니다 (Vercel은 Django 같은 상시 구동 서버엔 잘 안 맞습니다 —
   Next.js 버전과 배포처가 다른 이유입니다).

   **Render 기준 설정값:**
   - Build Command: `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
   - Start Command: `gunicorn config.wsgi`
   - 환경변수:
     - `DJANGO_DEBUG=0`
     - `DJANGO_SECRET_KEY` — 랜덤 값 (`python -c "import secrets; print(secrets.token_urlsafe(50))"`으로 생성)
     - `DJANGO_ALLOWED_HOSTS` — 예: `your-app.onrender.com`
     - `DJANGO_CSRF_TRUSTED_ORIGINS` — 스킴 포함, 예: `https://your-app.onrender.com`
       (없으면 /admin 로그인 등 POST 요청이 CSRF 오류로 막힘)
     - `DATABASE_URL`, `IMPORT_SECRET`, (쓴다면) `SHEET_SYNC_URL`/`SHEET_SYNC_SECRET`

   정적 파일은 [whitenoise](https://whitenoise.readthedocs.io/)가 앱 프로세스
   안에서 직접 서빙하므로 별도 CDN/nginx 설정 없이 `collectstatic`만 해주면
   됩니다.
3. 배포된 도메인이 `/admin/`, `/checkin/`, `/register/` 링크가 되고, QR
   링크(`.../qr/{token}/`)도 이 도메인 기준으로 자동 생성됩니다.
4. `google-apps-script/Forwarder.gs`의 `CONFIG.SERVER_URL`을 배포 도메인 +
   `/api/import/google-form/`로 바꿔야 실제 구글 폼 응답 시트와 연동됩니다
   (Apps Script는 구글 서버에서 실행돼서 `localhost`는 호출할 수 없습니다).

## 프로젝트 구조

```
config/
├── settings.py        # DB/앱/보안 설정 (.env 읽어옴)
└── urls.py             # /admin/ + checkin 앱 라우팅
checkin/
├── models.py            # Event, Participant 모델 (제약조건 포함)
├── admin.py             # /admin/ 커스터마이즈 — 이게 사실상 "운영진 대시보드"
├── forms.py             # 예비 신청 폼(RegisterForm)
├── views.py             # 신청/체크인/QR/구글폼 import 뷰
├── urls.py
├── services/
│   ├── label_assign.py         # 라벨 배정 알고리즘 (TS 버전과 동일 로직)
│   ├── assign_labels.py        # 회차 단위 일괄 라벨/QR 발급
│   ├── sheet_sync.py           # 체크인 시 점수 시트 "도착 여부" 실시간 반영
│   ├── event_excel_export.py   # 엑셀 내보내기 3종이 공유하는 탭 구성/마스킹/워크북 조립 공용 로직
│   ├── announcement_export.py  # 공지용 참가/관람 명단 엑셀 (확정자, 마스킹 있음)
│   ├── application_confirmation_export.py  # 신청 확인용 공지 엑셀 (전원, 마스킹 있음)
│   └── score_sheet_export.py   # 스태프용 점수표 엑셀 (마스킹 없음)
├── templates/checkin/       # register, checkin(스캐너), qr, home
└── tests.py                  # 라벨 배정 알고리즘 단위 테스트
google-apps-script/
├── Forwarder.gs.example   # 기존 구글 폼 응답 시트에 붙이는 전달용 스크립트 (실제 시크릿 채운 Forwarder.gs는 .gitignore 대상)
└── SheetSync.gs.example   # 점수 시트에 붙이는, 체크인 도착 표시 반영용 스크립트 (SheetSync.gs도 마찬가지)
requirements.txt
.env.example
```

## 다음에 붙이면 좋은 것들 (일부러 이번 범위에서 뺀 것)

- 학적증명서 OCR 자동 대조
- 문자/카카오 알림톡 자동 발송 (지금은 명단만 뽑아서 수동 발송)
- 스태프 계정별 권한 세분화 (지금은 슈퍼유저/스태프 여부로만 구분 — 인원이
  늘면 Django의 그룹/권한 기능으로 "체크인만 가능", "검수만 가능" 같은
  역할을 나눌 수 있습니다)
