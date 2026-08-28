/**
 * Django → 인포/공연장 점수 시트 실시간 반영용 스크립트
 * ---------------------------------------------------
 * Forwarder.gs(구글 폼 응답 시트 → Django, 신청 정보 가져오기)와는 반대 방향입니다.
 * 이건 Django가 이 스크립트를 호출해서, 인포·공연장에서 다 같이 보는 점수 시트
 * (장르별 탭으로 나뉜, 구글 폼 응답 시트와는 다른 별도 파일)에 값을 자동으로
 * 채워 넣는 역할만 합니다. 두 가지 경우에 호출됩니다.
 *   1) 체크인 확정 시 → 해당 탭의 "도착 여부"에 표시
 *   2) 관리자 페이지에서 "라벨 순서를 점수 시트에 반영" 버튼을 눌렀을 때
 *      → 참가자 전원의 라벨 코드를 해당 탭의 "순서"에 한 번에 반영
 *
 * 설치 방법
 * 1) 이 점수 시트 파일을 엽니다 (구글 폼 응답 시트 아님).
 * 2) 확장 프로그램 > Apps Script.
 * 3) 기본 Code.gs 내용을 지우고 이 파일 내용을 통째로 붙여넣습니다.
 * 4) 아래 CONFIG의 SECRET을 아무 랜덤 문자열로 채우고, Django 쪽 .env의
 *    SHEET_SYNC_SECRET에도 반드시 같은 값을 넣습니다.
 * 5) GENRE_TAB_MAP과 COLS가 실제 탭 이름·컬럼 헤더와 다르면 여기를 맞춥니다.
 * 6) 오른쪽 위 "배포" > "새 배포" > 유형: 웹 앱
 *    - 실행 계정: 나
 *    - 액세스 권한: 전체 허용 (Django 서버가 외부에서 호출해야 하므로)
 *    배포하면 웹 앱 URL이 나오는데, 이 값을 Django 쪽 .env의 SHEET_SYNC_URL에
 *    넣습니다 (끝에 /exec 포함).
 * 7) 스크립트나 시트 구조를 바꾼 뒤에는 "배포 관리"에서 새 버전으로 다시
 *    배포해야 반영됩니다 (URL은 그대로 유지됨).
 *
 * 참고: 이 방향(Django → 시트)은 값을 채워 넣기만 하는 단방향입니다. 시트에서
 * "도착 여부"나 "순서"를 수동으로 고쳐도 Django에는 반영되지 않습니다 — 두
 * 곳이 서로 다른 값을 덮어쓰는 충돌을 피하기 위해 일부러 그렇게 설계했습니다.
 */

const CONFIG = {
  // Django .env의 SHEET_SYNC_SECRET과 동일한 값.
  SECRET: 'REPLACE_WITH_SAME_SECRET_AS_ENV',

  // Django Participant.genre 값(구글 폼 선택지와 동일) → 이 시트의 탭 이름.
  // 관람객은 genre가 없으므로 entryType으로 따로 판단합니다 (아래 resolveSheetName_ 참고).
  GENRE_TAB_MAP: {
    Popping: '팝핑',
    House: '하우스',
    Krump: '크럼프',
    Waacking: '왁킹',
    Locking: '락킹',
    Hiphop: '힙합',
    Breaking: '브레이킹',
  },
  VIEWER_TAB: '관람',

  // 각 탭 공통 헤더 이름 — 실제 헤더와 다르면 여기를 맞춰주세요.
  COLS: {
    name: '이름',
    phone: '연락처',
    arrival: '도착 여부',
    order: '순서',
  },

  // "도착 여부" 컬럼에 채워 넣을 표시.
  ARRIVAL_MARK: 'O',
};

function doPost(e) {
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return jsonResponse_({ ok: false, message: '잘못된 JSON입니다.' });
  }

  if (body.secret !== CONFIG.SECRET) {
    return jsonResponse_({ ok: false, message: '인증 실패 (secret 불일치)' });
  }

  if (body.action === 'order') {
    return handleOrderPush_(body.entries || []);
  }
  return handleArrival_(body);
}

/** 체크인 확정 1건 처리 — 해당 탭의 "도착 여부"에 표시. */
function handleArrival_(body) {
  const sheetName = resolveSheetName_(body.entryType, body.genre);
  if (!sheetName) {
    return jsonResponse_({ ok: false, message: '장르에 대응하는 탭을 찾지 못했습니다: ' + body.genre });
  }
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
  if (!sheet) {
    return jsonResponse_({ ok: false, message: '시트에 "' + sheetName + '" 탭이 없습니다.' });
  }
  const matched = writeToColumn_(sheet, body.name, body.phone, CONFIG.COLS.arrival, CONFIG.ARRIVAL_MARK);
  return jsonResponse_({
    ok: true,
    matched: matched,
    sheet: sheetName,
    message: matched ? '도착 표시 완료' : '이름/연락처가 일치하는 행을 찾지 못했습니다.',
  });
}

/** 관리자 페이지 "라벨 순서를 점수 시트에 반영" 버튼 — 여러 명을 한 번에 처리. */
function handleOrderPush_(entries) {
  const results = entries.map(function (entry) {
    const sheetName = resolveSheetName_(entry.entryType, entry.genre);
    const sheet = sheetName ? SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName) : null;
    const matched = sheet
      ? writeToColumn_(sheet, entry.name, entry.phone, CONFIG.COLS.order, entry.labelCode)
      : false;
    return { name: entry.name, phone: entry.phone, sheet: sheetName, matched: matched };
  });
  const matchedCount = results.filter(function (r) { return r.matched; }).length;
  return jsonResponse_({
    ok: true,
    matchedCount: matchedCount,
    totalCount: results.length,
    results: results,
  });
}

function resolveSheetName_(entryType, genre) {
  if (entryType === '관람' || !genre) return CONFIG.VIEWER_TAB;
  return CONFIG.GENRE_TAB_MAP[genre] || null;
}

function normalizePhone_(v) {
  return String(v || '').replace(/[^0-9]/g, '');
}

/**
 * 이름+연락처가 일치하는 행을 찾아 지정한 컬럼(colHeaderName)에 value를 씀.
 * 찾으면 true, 못 찾으면 false.
 */
function writeToColumn_(sheet, name, phone, colHeaderName, value) {
  const lastRow = sheet.getLastRow();
  const lastCol = sheet.getLastColumn();
  if (lastRow < 2) return false;

  const header = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  const nameCol = header.indexOf(CONFIG.COLS.name);
  const phoneCol = header.indexOf(CONFIG.COLS.phone);
  const targetCol = header.indexOf(colHeaderName);
  if (nameCol === -1 || phoneCol === -1 || targetCol === -1) return false;

  const values = sheet.getRange(2, 1, lastRow - 1, lastCol).getValues();
  const targetPhone = normalizePhone_(phone);
  const targetName = String(name || '').trim();

  for (let i = 0; i < values.length; i++) {
    const rowPhone = normalizePhone_(values[i][phoneCol]);
    if (rowPhone && rowPhone === targetPhone) {
      // 이름은 "본명/댄서네임" 형식이라 완전 일치가 아니라 포함 여부로 느슨하게 확인.
      const rowName = String(values[i][nameCol] || '').trim();
      if (!rowName || rowName.includes(targetName) || targetName.includes(rowName)) {
        sheet.getRange(i + 2, targetCol + 1).setValue(value);
        return true;
      }
    }
  }
  return false;
}

function jsonResponse_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

/** 배포 후 웹 앱이 살아있는지 확인용. 브라우저로 웹 앱 URL을 직접 열면 이게 호출됨. */
function doGet() {
  return jsonResponse_({ ok: true, message: 'SheetSync 웹 앱이 정상적으로 떠 있습니다. POST로 호출해주세요.' });
}
