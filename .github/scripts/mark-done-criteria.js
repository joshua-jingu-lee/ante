// post-merge.yml의 `markIssueDone`이 연결 이슈 본문에 쓰는 완료 조건 파서다(#2524).
// 워크플로는 이 파일을 `GITHUB_WORKSPACE`에 체크아웃한 뒤 절대 경로로 불러온다.

// 체크박스 갱신을 `완료 조건` 절로 한정한다. 본문 전체를 치환하면
// 이슈 폼의 `위험 신호`처럼 완료 조건이 아닌 체크박스까지 「해당함」으로
// 바뀌어 감사 기록이 거짓이 된다. 불변식 넷:
//   1. `완료 조건` 헤딩 다음 줄부터 다음 헤딩 직전까지만 갱신한다.
//      헤딩 판정은 접두 앵커+경계다. `## 전제 조건` 같은 인접 헤딩은
//      켜지 않는다. 접미사는 **공백으로 띄운 뒤 낱말·숫자가 아닌 것**
//      으로 시작할 때만 켠다 — `## 완료 조건 (epic)`·`## 완료 조건 —
//      반영판`은 켜고, `## 완료 조건 매핑`(낱말)·`## 완료 조건 2차`
//      (숫자)·`## 완료 조건(epic)`(붙여 씀)은 켜지 않는다.
//   2. 코드 펜스 안은 헤딩도 체크박스도 아니다. 펜스는 여는 것과 같은
//      문자로 같은 길이 이상이고 뒤에 다른 글자가 없을 때만 닫히며,
//      여는 백틱 펜스의 info string에 백틱이 있으면 펜스가 아니다.
//   3. 헤딩은 `#`만 있는 빈 것도 헤딩이라 절을 닫는다(CommonMark).
//      체크박스는 `]` 뒤에 공백이나 행 끝이 와야 한다(GFM) — `- [ ]x`는
//      산문이라 건드리지 않는다.
//      헤딩·펜스·체크박스가 같은 관용도를 쓴다 — 선행 공백 3칸까지,
//      GFM 불릿 3종. 행 끝 CR은 판정에서만 무시하고 치환은 원문에
//      해서 CR을 보존한다.
//   4. 조용한 무동작은 성공과 구분되지 않으므로 셋을 warnings로
//      돌려준다 — 갱신할 `- [ ]` 항목이 있는데 절을 못 찾은 것,
//      펜스가 절이나 그 항목을 가릴 수 있게 열린 채 끝난 것, 절 안에
//      인식하지 못한 불릿·번호 형태의 미체크 항목이 남은 것. 헤딩 경고는 갱신할
//      항목이 없으면 내지 않고, 펜스 경고는 절을 못 찾았거나 절 안에서
//      펜스가 열렸을 때만 낸다 — 열린 펜스는 하나뿐이라 플래그를 여는
//      시점에 대입해 갱신한다. 접두 `[done-criteria:*]`와 이슈 번호는
//      호출부가 붙인다: 한 run이 여러 이슈를 처리하므로 번호가 없으면
//      어느 이슈인지 알 수 없고, 접두가 겹치면 로그 집계가 이중 계수한다.
function markDoneCriteriaChecked(body) {
  const lines = body.split("\n");
  let inDoneCriteria = false;
  let fenceMarker = null;
  let sawDoneCriteria = false;
  let sawUncheckedItem = false;
  let fenceOpenedInSection = false;
  let sawLooseItem = false;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].replace(/\r$/, "");

    const fence = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);

    if (fence && !(fence[1][0] === "`" && fence[2].includes("`"))) {
      if (!fenceMarker) {
        fenceMarker = fence[1];
        fenceOpenedInSection = inDoneCriteria;
      } else if (
        fence[1][0] === fenceMarker[0] &&
        fence[1].length >= fenceMarker.length &&
        fence[2].trim() === ""
      ) {
        fenceMarker = null;
      }
      continue;
    }

    if (fenceMarker) {
      continue;
    }

    const heading = line.match(/^ {0,3}#{1,6}(?:[ \t]+(.*))?$/);

    if (heading) {
      inDoneCriteria = /^완료 조건(?=$|\s)(?!\s*[\p{L}\p{N}])/u.test((heading[1] || "").trim());

      if (inDoneCriteria) {
        sawDoneCriteria = true;
      }
      continue;
    }

    const strict = /^ {0,3}[-*+] \[ \](?=\s|$)/.test(line);

    if (strict) {
      sawUncheckedItem = true;
    }

    if (inDoneCriteria) {
      if (strict) {
        lines[index] = lines[index].replace(
          /^( {0,3}[-*+]) \[ \](?=\s|$)/,
          "$1 [x]",
        );
      } else if (/^\s*(?:[-*+]|\d+[.)])\s+\[ \](?=\s|$)/.test(line)) {
        sawLooseItem = true;
      }
    }
  }

  const warnings = [];

  if (!sawDoneCriteria && sawUncheckedItem) {
    warnings.push({
      tag: "heading-not-found",
      detail:
        "본문에서 `완료 조건` 헤딩을 찾지 못해 체크리스트를 갱신하지 " +
        "않았습니다.",
    });
  }

  if (fenceMarker && (!sawDoneCriteria || fenceOpenedInSection)) {
    warnings.push({
      tag: "unterminated-fence",
      detail:
        "코드 펜스가 열린 채 본문이 끝나 `완료 조건` 절이나 그 항목이 " +
        "가려졌을 수 있습니다.",
    });
  }

  if (sawLooseItem) {
    warnings.push({
      tag: "item-not-matched",
      detail:
        "`완료 조건` 절에 이 구현이 인식하지 못하는 형태의 미체크 항목이 " +
        "있어 갱신에서 빠졌습니다(들여쓰기 4칸 이상·탭·번호 목록·불릿 뒤 " +
        "공백 2칸 이상).",
    });
  }

  return { body: lines.join("\n"), warnings };
}

// post-merge 코멘트의 `issue checklist` 줄이다. 첫 값은 본문을 고쳤는지만 말하고,
// 경고 태그는 괄호로 덧붙인다 — 경고는 갱신과 함께 날 수 있어 첫 값을 바꾸지 않는다.
// 경고가 없으면 태그를 싣기 전의 줄과 바이트로 같다.
function checklistLine(checkboxUpdated, warnings) {
  const base = `- issue checklist: ${checkboxUpdated ? "updated" : "unchanged"}`;
  if (warnings.length === 0) {
    return base;
  }
  const tags = warnings.map((warning) => warning.tag);
  return `${base} (${tags.join(", ")})`;
}

module.exports = { markDoneCriteriaChecked, checklistLine };
