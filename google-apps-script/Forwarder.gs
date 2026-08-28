/**
 * 동방배틀 구글 폼 → 웹 서비스 전달용 스크립트
 * ---------------------------------------------
 * 이건 예전에 드렸던 appsscript/Code.gs(자체 체크인 시스템 전체를 구현한 버전)와는
 * 다른, 훨씬 가벼운 스크립트입니다. 지금 쓰고 계신 "기존 구글 폼"은 그대로 두고,
 * 그 폼이 쌓는 응답 시트에 이 스크립트만 붙여서 새 응답이 들어올 때마다 우리
 * 웹 서비스(Django + PostgreSQL 버전)로 전달(forward)하는 역할만 합니다.
 * (Next.js 버전용 Forwarder.gs와 기능은 동일하고, 호출 주소만 다릅니다.)
 *
 * 설치 방법
 * 1) 폼 응답이 쌓이는 구글 시트를 엽니다.
 * 2) 확장 프로그램 > Apps Script.
 * 3) 기본 Code.gs 내용을 지우고 이 파일 내용을 통째로 붙여넣습니다.
 * 4) 아래 CONFIG의 SERVER_URL, IMPORT_SECRET, 시트 헤더 이름들을 실제 값으로 맞춥니다.
 *    - IMPORT_SECRET은 웹 서비스 .env의 IMPORT_SECRET과 반드시 같아야 합니다.
 *    - 비밀번호를 코드에 그대로 두기 싫다면, 아래처럼 스크립트 속성에 저장해도 됩니다:
 *      프로젝트 설정 > 스크립트 속성 > IMPORT_SECRET 추가 후,
 *      CONFIG.IMPORT_SECRET 줄을 PropertiesService.getScriptProperties().getProperty('IMPORT_SECRET')로 바꾸면 됩니다.
 * 5) 저장 후, 왼쪽 시계 아이콘(트리거) > 트리거 추가:
 *    - 실행할 함수: onFormSubmit
 *    - 이벤트 소스: 스프레드시트에서
 *    - 이벤트 유형: 양식 제출 시
 *    저장하면 권한 승인 화면이 뜨는데, 본인 계정으로 승인하면 됩니다.
 * 6) 시트 메뉴에 "동방배틀 연동" 메뉴가 생깁니다. 처음 붙이는 거라면
 *    "기존 응답 전체 백필"을 한 번 눌러서, 트리거 달기 전에 쌓여있던 응답들도
 *    옮겨줍니다. (몇 번을 다시 눌러도 이미 옮긴 행은 건너뛰므로 안전합니다.)
 *
 * 참고: 신청자가 업로드하는 학적증명서 OCR 자동 대조는 이번에도 범위 밖입니다
 * (전에 협의된 대로, 나중에 확장 예정).
 */

const CONFIG = {
  // Django 서버의 import endpoint 주소 (끝에 슬래시 포함, Django 기본 설정 기준).
  // 로컬 테스트: "http://localhost:8000/api/import/google-form/" (단, Apps Script는
  //   구글 서버에서 실행되므로 로컬호스트를 호출할 수 없습니다 — 실제 배포 후 도메인으로 바꾸세요)
  // 배포 후 예시: "https://your-domain.com/api/import/google-form/"
  SERVER_URL: 'https://YOUR-DOMAIN/api/import/google-form/',

  // 웹 서비스 .env의 IMPORT_SECRET과 동일한 값
  IMPORT_SECRET: 'REPLACE_WITH_SAME_SECRET_AS_ENV',

  // 원본 구글 폼 문항(시트 헤더) 이름 — 실제 헤더와 다르면 여기를 맞춰주세요.
  FORM_COLS: {
    type: '참가 / 관람',
    name: '참가자명 / 관람자명',
    phone: '연락처',
    school: '소속대학',
    academicStatus: '학적',
    genre: '참가 장르',
    payerName: '입금자명',
    email: '이메일 주소',
  },
};

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('동방배틀 연동')
    .addItem('기존 응답 전체 백필', 'menuBackfillAll')
    .addItem('연결 테스트', 'menuTestConnection')
    .addToUi();
}

/** 폼 제출 트리거: 새 응답 1건만 전달 */
function onFormSubmit(e) {
  const sheet = e.range.getSheet();
  const row = e.range.getRow();
  const header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const payloadRow = buildRow_(sheet, header, row);
  sendRows_([payloadRow]);
}

/** 메뉴: 시트에 이미 쌓여있던 응답 전체를 한 번에 백필 */
function menuBackfillAll() {
  const sheet = SpreadsheetApp.getActiveSheet();
  const lastRow = sheet.getLastRow();
  const lastCol = sheet.getLastColumn();
  if (lastRow < 2) {
    SpreadsheetApp.getUi().alert('응답이 없습니다.');
    return;
  }
  const header = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  const rows = [];
  for (let r = 2; r <= lastRow; r++) {
    rows.push(buildRow_(sheet, header, r));
  }
  const result = sendRows_(rows);
  SpreadsheetApp.getUi().alert(
    '백필 완료\n신규 반영: ' + result.imported + '명\n이미 있어서 건너뜀: ' + result.skipped + '명\n' +
    (result.errors && result.errors.length ? '오류 ' + result.errors.length + '건 (자세한 건 실행 로그 참고)' : '오류 없음')
  );
  if (result.errors && result.errors.length) {
    Logger.log(JSON.stringify(result.errors, null, 2));
  }
}

function menuTestConnection() {
  try {
    const res = sendRows_([]);
    SpreadsheetApp.getUi().alert('서버 응답: ' + JSON.stringify(res));
  } catch (err) {
    SpreadsheetApp.getUi().alert('연결 실패: ' + err);
  }
}

/** 시트 한 행 -> 서버가 기대하는 row 객체로 변환. externalRef는 시트 행 번호를 그대로 씀. */
function buildRow_(sheet, header, rowNum) {
  const values = sheet.getRange(rowNum, 1, 1, header.length).getValues()[0];
  const map = {};
  header.forEach((h, i) => { map[h] = values[i]; });
  const fc = CONFIG.FORM_COLS;
  return {
    externalRef: String(rowNum),
    type: String(map[fc.type] || ''),
    name: String(map[fc.name] || ''),
    phone: String(map[fc.phone] || ''),
    school: String(map[fc.school] || ''),
    academicStatus: String(map[fc.academicStatus] || ''),
    genre: String(map[fc.genre] || ''),
    payerName: String(map[fc.payerName] || ''),
    email: String(map[fc.email] || ''),
  };
}

function sendRows_(rows) {
  const res = UrlFetchApp.fetch(CONFIG.SERVER_URL, {
    method: 'post',
    contentType: 'application/json',
    headers: { 'x-import-secret': CONFIG.IMPORT_SECRET },
    payload: JSON.stringify({ rows: rows }),
    muteHttpExceptions: true,
  });
  const code = res.getResponseCode();
  const body = res.getContentText();
  if (code >= 300) {
    throw new Error('서버 오류 (' + code + '): ' + body);
  }
  return JSON.parse(body);
}
