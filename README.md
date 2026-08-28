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
3. `google-apps-script/Forwarder.gs` 내용을 통째로 붙여넣고, 맨 위 `CONFIG`의
   `SERVER_URL`(배포 도메인 + `/api/import/google-form/`, 끝 슬래시 포함),
   `IMPORT_SECRET`(1번과 동일한 값), `FORM_COLS`(실제 시트 헤더 이름)를 맞춥니다.
4. 저장 → 트리거(시계 아이콘) 추가 → 함수 `onFormSubmit`, 이벤트 유형
   "양식 제출 시"로 등록 → 권한 승인.
5. 시트를 새로고침하면 "동방배틀 연동" 메뉴가 생깁니다. 트리거를 달기 전에
   이미 쌓여있던 응답이 있다면 "기존 응답 전체 백필"을 눌러서 옮겨줍니다.
   (같은 응답을 여러 번 백필해도 시트 행 번호 기준으로 중복 없이 건너뜁니다.)

전달되는 값은 폼의 "입금확인" 체크 여부와 무관하게 항상 검수 대기(PENDING)로
들어옵니다 — 실제 확인은 운영진이 관리자 페이지에서 합니다.

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
4. `/admin/` > **Events** 목록에서 해당 회차를 체크 → 액션 드롭다운에서
   "④ 선택 회차: 승인자 라벨/QR 발급 실행" 실행. 승인+입금완료된 참가자에게
   라벨 코드, 전원(참가+관람)에게 QR 토큰이 발급됩니다. 몇 번을 다시 실행해도
   이미 처리된 사람은 건드리지 않아 안전합니다.
5. 참가자에게 `/qr/{token}/` 링크를 문자/카카오톡으로 보내줍니다 (자동 발송은
   이번 버전도 구현하지 않았습니다 — 참가자 이메일/연락처는 `/admin/`에서
   CSV로 내려받아 발송 도구에 넣어 쓰시면 됩니다).
6. **행사 당일**: 스태프가 본인 계정으로 로그인한 상태에서 아이패드/아이폰
   브라우저로 `/checkin/` 접속 → 카메라 자동 실행 → QR 스캔 시 라벨 코드/이름/
   장르가 크게 표시. 같은 QR 재스캔 시 "이미 체크인됨" 표시. QR을 못 보여주는
   사람은 같은 페이지의 "이름/전화번호로 수동 검색"으로 찾아서 수동 체크인.
7. **행사 종료 후**: `/admin/` > **Events**에서 해당 회차를 체크 → "참가자
   CSV 백업 다운로드" 액션으로 데이터를 저장해두고, 기본 제공되는 삭제
   액션으로 그 회차를 삭제하면 참가자 데이터도 함께 정리됩니다(연쇄 삭제).
   다음 회차는 다시 "Add event"로 새로 시작하면 됩니다.

## 배포 (실제 서비스로 만들기)

1. **DB**: [Supabase](https://supabase.com) 또는 [Neon](https://neon.tech)에서
   무료 Postgres 프로젝트 생성 → connection string을 `.env`의 `DATABASE_URL`에.
2. **배포**: Django는 Railway, Render, Fly.io, PythonAnywhere 등에서 쉽게
   돌릴 수 있습니다 (Vercel은 Django 같은 상시 구동 서버엔 잘 안 맞습니다 —
   Next.js 버전과 배포처가 다른 이유입니다). 배포 시 `DJANGO_DEBUG=0`,
   `DJANGO_SECRET_KEY`를 랜덤 값으로, `DJANGO_ALLOWED_HOSTS`에 실제 도메인을
   설정하고 `python manage.py collectstatic`을 실행해주세요. WSGI 서버는
   `gunicorn config.wsgi`를 권장합니다.
3. 배포된 도메인이 `/admin/`, `/checkin/`, `/register/` 링크가 되고, QR
   링크(`.../qr/{token}/`)도 이 도메인 기준으로 자동 생성됩니다.

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
│   ├── label_assign.py     # 라벨 배정 알고리즘 (TS 버전과 동일 로직)
│   └── assign_labels.py    # 회차 단위 일괄 라벨/QR 발급
├── templates/checkin/       # register, checkin(스캐너), qr, home
└── tests.py                  # 라벨 배정 알고리즘 단위 테스트
google-apps-script/
└── Forwarder.gs   # 기존 구글 폼 응답 시트에 붙이는 전달용 스크립트
requirements.txt
.env.example
```

## 다음에 붙이면 좋은 것들 (일부러 이번 범위에서 뺀 것)

- 학적증명서 OCR 자동 대조
- 문자/카카오 알림톡 자동 발송 (지금은 명단만 뽑아서 수동 발송)
- 스태프 계정별 권한 세분화 (지금은 슈퍼유저/스태프 여부로만 구분 — 인원이
  늘면 Django의 그룹/권한 기능으로 "체크인만 가능", "검수만 가능" 같은
  역할을 나눌 수 있습니다)
