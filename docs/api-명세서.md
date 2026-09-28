# 동방배틀 체크인 시스템 — API 명세서

Django REST Framework 없이 순수 Django 뷰(`checkin/views.py`)로 만든
내부용 JSON 엔드포인트 목록입니다. 화면 단위 기능 설명은
[기능명세서.md](./기능명세서.md)를 참고하세요.

- **인증**: "스태프 로그인 필요"는 Django 세션 로그인(`@staff_member_required`,
  `is_staff=True`)을 의미합니다. 별도 토큰/API 키 인증은 구글 폼 연동
  엔드포인트(`X-Import-Secret` 헤더) 한 곳에만 있습니다.
- **응답 포맷**: 전부 `application/json`. 별도 명시 없으면 HTTP 200 +
  아래 스키마.

## 체크인 스캐너용

### `POST /api/checkin/lookup/`

QR 텍스트를 조회만 하고 체크인 처리는 하지 않습니다(확인 화면에 정보만
띄우는 용도 — 실제 체크인 확정은 아래 `manual-checkin` 엔드포인트가 담당).

- **인증**: 스태프 로그인 필요
- **Request body**
  ```json
  { "text": "<QR로 스캔한 원문 텍스트 — 내부에서 UUID를 정규식으로 추출>" }
  ```
- **Response `200`**
  ```json
  // 찾은 경우
  { "status": "FOUND", "data": { /* ParticipantDTO, 아래 참고 */ }, "canApproveVerification": true }
  // 못 찾은 경우
  { "status": "NOT_FOUND", "message": "등록되지 않은 QR입니다." }
  ```

### `GET /api/participants/search/?q=<검색어>`

이름/전화번호로 활성 회차의 참가자를 검색합니다(QR을 못 보여주는 참가자용
수동 검색).

- **인증**: 스태프 로그인 필요
- **Query params**: `q` (이름 또는 연락처 부분 일치, 없으면 빈 결과)
- **Response `200`**
  ```json
  { "results": [ /* ParticipantDTO[], 최대 20건 */ ], "canApproveVerification": true }
  ```

### `POST /api/participants/<uuid:participant_id>/manual-checkin/`

해당 참가자를 체크인 확정 처리합니다(QR 스캔 확정, 수동 검색 확정 공용).
이미 체크인된 사람은 다시 처리하지 않습니다(최초 체크인 시각 보존).

- **인증**: 스태프 로그인 필요
- **Response `200`**
  ```json
  { "status": "success", "data": { /* ParticipantDTO */ } }
  ```
- **Response `400`**: 환불된 참가자, 또는 학적 검수가 필요한 참가자(`"code": "VERIFICATION_REQUIRED"`).
  화면에서 버튼을 숨겨도 서버가 같은 조건으로 막습니다.

`canApproveVerification`은 요청한 스태프에게 학적검수 승인 권한(`checkin.approve_verification`)이
있는지입니다. 화면이 "검수 완료" 버튼을 보여줄지, 권한 안내를 보여줄지 정하는 데 씁니다.

### `POST /api/participants/<uuid:participant_id>/approve-verification/`

체크인 화면의 "검수 완료" 버튼. 학적검수를 `APPROVED`로 바꿉니다. 이미 승인된 참가자에게
다시 불러도 성공합니다(멱등).

- **인증**: 스태프 로그인 + `checkin.approve_verification` 권한
- **Response `200`**: `{ "status": "success", "data": { /* ParticipantDTO */ } }`
- **Response `403`**: 승인 권한 없음
- **Response `400`**: 환불된 참가자이거나 관람 구분(검수 대상 아님)

### ParticipantDTO (위 엔드포인트 공통 응답 형태)

```json
{
  "id": "uuid",
  "name": "string",
  "phone": "string",
  "entryType": "참가 | 관람",
  "genre": "string | null",
  "school": "string | null",
  "labelCode": "string | null",
  "checkinStatus": "NOT_CHECKED_IN | CHECKED_IN",
  "verificationStatus": "PENDING | APPROVED | REJECTED | N_A",
  "needsVerification": "boolean — 참가 구분이면서 학적검수가 승인되지 않음(대기·반려)"
}
```

## 구글 폼 연동용

### `POST /api/import/google-form/`

`google-apps-script/Forwarder.gs`가 구글 폼 응답 시트의 신규 제출/백필을
전달하는 웹훅. 사람이 직접 호출하는 API가 아닙니다.

- **인증**: 헤더 `X-Import-Secret: <IMPORT_SECRET>` (`.env`의 값과 일치해야
  함). 세션 로그인 불필요(`csrf_exempt`) — 대신 이 시크릿으로 인증.
- **Request body**
  ```json
  {
    "rows": [
      {
        "externalRef": "string (필수, 시트 행 식별자 — 중복 수집 방지 키)",
        "name": "string (필수)",
        "phone": "string (필수)",
        "type": "참가 | 관람 (없으면 참가로 간주)",
        "school": "string (선택)",
        "academicStatus": "string (선택)",
        "genre": "string (`type`이 참가면 필수 — Genre 선택지 값과 정확히 일치해야 함, 관람이면 무시됨)",
        "payerName": "string (선택)"
      }
    ]
  }
  ```
  `rows`를 생략하거나 빈 배열로 보내면 실제 저장 없이 인증/활성 회차
  존재 여부만 확인하는 연결 테스트로 동작합니다.
- **Response `200`**
  ```json
  {
    "eventId": "uuid",
    "imported": 0,
    "skipped": 0,
    "errors": [{ "externalRef": "string", "message": "string" }]
  }
  ```
  `skipped`는 이미 존재하는 `externalRef`(멱등 처리), `errors`는
  `externalRef`/`name`/`phone` 누락, 참가 행인데 `genre`가 없거나
  `Genre` 선택지에 없는 값인 경우 등 개별 행 실패(해당 행만 건너뛰고 나머지는
  계속 처리됨).
- **Response `401`**: `X-Import-Secret` 불일치.
- **Response `400`**: 잘못된 JSON, 또는 활성 회차가 없음.
- **Response `500`**: 서버에 `IMPORT_SECRET`이 설정되어 있지 않음.

## 페이지형 엔드포인트 (참고용 — HTML 반환, API 아님)

| Method | Path | 인증 | 설명 |
| --- | --- | --- | --- |
| GET | `/` | 불필요 | 홈 |
| GET/POST | `/register/` | 불필요 | 예비 신청 폼 |
| GET | `/qr/<uuid:token>/` | 불필요 | 개인 QR 이미지 확인 |
| GET | `/checkin/scan/<uuid:token>/` | 불필요 | QR 스캔 시 뜨는 참가자 정보 확인(체크인 확정 아님) |
| POST | `/checkin/scan/<uuid:token>/approve/` | 스태프 + 학적검수 승인 권한 | 위 확인 화면에서 학적 검수 완료(폼 POST, 리다이렉트 응답) |
| POST | `/checkin/scan/<uuid:token>/confirm/` | 스태프 | 위 확인 화면에서 체크인 확정(폼 POST, 리다이렉트 응답). 검수가 필요한 참가자는 거절 |
| GET | `/checkin/` | 스태프 | 현장 체크인 스캐너 화면 |
| — | `/admin/...` | 운영진/슈퍼유저 | Django Admin 전체(회차/참가자 관리) |
| — | `/admin/accounts/` | 슈퍼유저 | 계정 관리 대시보드 |

## 이 문서에 대해

DRF/OpenAPI 스키마 없이 손으로 관리하는 문서입니다. 엔드포인트를
추가/변경할 때 이 파일도 함께 업데이트해야 최신 상태가 유지됩니다.
