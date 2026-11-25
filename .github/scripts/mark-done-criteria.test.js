// post-merge.yml이 불러 쓰는 완료 조건 파서의 행동 명제다(#2524).
// 명제 이름은 #2509 회귀 락 L4의 태그를 그대로 쓴다. 경고 문자열은
// 호출부(markIssueDone)와 같은 접두로 만든다 — 번호는 판정에 쓰지 않으므로 뺀다.
"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const { markDoneCriteriaChecked } = require("./mark-done-criteria.js");

const warnings = [];

function check(body) {
  const result = markDoneCriteriaChecked(body);
  for (const warning of result.warnings) {
    warnings.push(`[done-criteria:${warning.tag}] ${warning.detail}`);
  }
  return result.body;
}

function lines(body) {
  return check(body).split("\n");
}

function tagOf(message) {
  return (message.match(/^\[done-criteria:[a-z-]+\]/) || [])[0];
}

test("RETSHAPE", () => {
  const result = markDoneCriteriaChecked("## 완료 조건\n- [ ] a");
  assert.equal(typeof result, "object");
  assert.equal(typeof result.body, "string");
  assert.ok(Array.isArray(result.warnings));
});

test("BEHAVIOR", () => {
  const body = [
    "## 배경", "본문", "",
    "### 위험 신호", "- [ ] cache / invalidate", "- [ ] mutable config", "",
    "## 완료 조건", "- [ ] 구현", "- [ ] 테스트", "",
    "## 비목표", "- [ ] 건드리지 않음",
  ].join("\n");
  const out = lines(body);
  const risk = out.filter((l) => l.includes("cache") || l.includes("mutable"));
  const done = out.slice(out.indexOf("## 완료 조건") + 1, out.indexOf("## 비목표"));
  const nongoal = out.filter((l) => l.includes("건드리지 않음"));
  assert.ok(risk.every((l) => l.startsWith("- [ ]")));
  assert.ok(done.filter((l) => l.trim()).every((l) => l.startsWith("- [x]")));
  assert.ok(nongoal.every((l) => l.startsWith("- [ ]")));
});

test("NOHEADING", () => {
  assert.equal(check("## 배경\n- [ ] a"), "## 배경\n- [ ] a");
});

test("FORMLEVEL", () => {
  const out = lines("### 완료 조건\n- [ ] x\n### 다음\n- [ ] y");
  assert.equal(out[1], "- [x] x");
  assert.equal(out[3], "- [ ] y");
});

test("TRAILING", () => {
  assert.equal(lines("## 완료 조건 — 반영판\n- [ ] z")[1], "- [x] z");
});

test("BARE", () => {
  assert.equal(check("- [ ] a\n- [ ] b"), "- [ ] a\n- [ ] b");
});

test("ANCHOR", () => {
  const out = lines("## 전제 조건\n- [ ] p\n## 완료 조건\n- [ ] q");
  assert.equal(out[1], "- [ ] p");
  assert.equal(out[3], "- [x] q");
});

test("PUNCT", () => {
  const out = lines(["## 완료 조건 : 반영판", "- [ ] a", "## 완료 조건이 아닌 것", "- [ ] b"].join("\n"));
  assert.equal(out[1], "- [x] a");
  assert.equal(out[3], "- [ ] b");
});

test("UNIBOUND", () => {
  const out = lines(["## 완료 조건書", "- [ ] a", "## 완료 조건", "- [ ] b"].join("\n"));
  assert.equal(out[1], "- [ ] a");
  assert.equal(out[3], "- [x] b");
});

test("CRLF", () => {
  const out = check(["### 위험 신호", "- [ ] cache", "## 완료 조건", "- [ ] c"].join("\r\n"));
  assert.ok(out.includes("- [x] c"));
  assert.ok(out.includes("- [ ] cache"));
});

test("FENCE", () => {
  const out = lines(["## 배경", "```markdown", "## 완료 조건", "- [ ] 예시", "```", "## 완료 조건", "- [ ] 진짜"].join("\n"));
  assert.equal(out[3], "- [ ] 예시");
  assert.equal(out[6], "- [x] 진짜");
});

test("FENCECMT", () => {
  const out = lines(["## 완료 조건", "- [ ] A", "```bash", "# 주석", "```", "- [ ] B"].join("\n"));
  assert.equal(out[1], "- [x] A");
  assert.equal(out[5], "- [x] B");
});

test("NESTED", () => {
  const out = lines(["### 배경", "````markdown", "```", "### 완료 조건", "- [ ] 예시", "```", "````", "### 완료 조건", "- [ ] 진짜"].join("\n"));
  assert.equal(out[4], "- [ ] 예시");
  assert.equal(out[8], "- [x] 진짜");
});

test("MIXED", () => {
  const out = lines(["```", "## 완료 조건", "- [ ] x", "~~~", "- [ ] y", "```", "## 완료 조건", "- [ ] z"].join("\n"));
  assert.equal(out[2], "- [ ] x");
  assert.equal(out[4], "- [ ] y");
  assert.equal(out[7], "- [x] z");
});

test("FENCEIN", () => {
  const out = lines(["## 완료 조건", "- [ ] 진짜", "```markdown", "- [ ] 예시", "```", "- [ ] 진짜2"].join("\n"));
  assert.equal(out[1], "- [x] 진짜");
  assert.equal(out[3], "- [ ] 예시");
  assert.equal(out[5], "- [x] 진짜2");
});

test("UNCLOSED", () => {
  const out = lines(["## 완료 조건", "- [ ] a", "```bash", "- [ ] 코드블록"].join("\n"));
  assert.equal(out[1], "- [x] a");
  assert.equal(out[3], "- [ ] 코드블록");
});

test("CLOSERINFO", () => {
  const out = lines(["## 완료 조건", "```text", "- [ ] 안", "```js", "- [ ] 밖"].join("\n"));
  assert.equal(out[2], "- [ ] 안");
  assert.equal(out[4], "- [ ] 밖");
});

test("INDENT3", () => {
  const out = lines(["   ## 완료 조건", "- [ ] a", "   ## 비목표", "- [ ] b"].join("\n"));
  assert.equal(out[1], "- [x] a");
  assert.equal(out[3], "- [ ] b");
});

test("BULLETS", () => {
  const out = lines(["## 완료 조건", "- [ ] a", "  - [ ] b", "* [ ] c", "+ [ ] d"].join("\n"));
  assert.equal(out[1], "- [x] a");
  assert.equal(out[2], "  - [x] b");
  assert.equal(out[3], "* [x] c");
  assert.equal(out[4], "+ [x] d");
});

test("OPENERINFO", () => {
  const out = lines(["### 기술 노트", "``` ``` 두 개", "## 완료 조건", "- [ ] a"].join("\n"));
  assert.equal(out[3], "- [x] a");
});

test("WARN", () => {
  warnings.length = 0;
  check("## 배경\n- [ ] a");
  const w1 = warnings.length;
  warnings.length = 0;
  check("## 배경\n```bash\n## 완료 조건\n- [ ] a");
  const w2 = warnings.length;
  warnings.length = 0;
  check("## 완료 조건\n- [ ] a");
  assert.equal(w1, 1);
  assert.equal(w2, 1);
  assert.equal(warnings.length, 0);
});

test("WARNTAG", () => {
  warnings.length = 0;
  check("## 배경\n- [ ] a");
  const t1 = tagOf(warnings[0]);
  warnings.length = 0;
  check("## 배경\n```bash\n## 완료 조건\n- [ ] a");
  const t2 = tagOf(warnings[0]);
  assert.ok(t1);
  assert.ok(t2);
  assert.notEqual(t1, t2);
});

test("MISDIAG", () => {
  warnings.length = 0;
  check("## 배경\n```bash\necho hi\n## 완료 조건\n- [ ] a");
  assert.ok(warnings.map(tagOf).includes("[done-criteria:unterminated-fence]"));
});

test("NOISE", () => {
  warnings.length = 0;
  check("## 배경\n본문만 있고 체크박스가 없다");
  const q1 = warnings.length;
  warnings.length = 0;
  check("## 배경\n- [x] 이미 완료");
  assert.equal(q1, 0);
  assert.equal(warnings.length, 0);
});

test("FENCEWARN", () => {
  warnings.length = 0;
  check("## 완료 조건\n- [ ] a\n## 로그\n```\n붙여넣은 로그");
  assert.equal(warnings.length, 0);
});

test("FENCEINSEC", () => {
  warnings.length = 0;
  check("## 완료 조건\n```\n- [ ] a\n- [ ] b");
  assert.ok(warnings.some((w) => w.startsWith("[done-criteria:unterminated-fence]")));
});

test("FENCERESET", () => {
  warnings.length = 0;
  const out = check("## 완료 조건\n- [ ] a\n```\ncode\n```\n## 로그\n```\n로그");
  assert.ok(out.includes("- [x] a"));
  assert.equal(warnings.length, 0);
});

test("BAREHEAD", () => {
  const out = check("## 완료 조건\n- [ ] a\n##\n- [ ] out");
  assert.ok(out.includes("- [x] a"));
  assert.ok(out.includes("- [ ] out"));
});

test("GFMSPACE", () => {
  const out = check("## 완료 조건\n- [ ]x 산문\n- [ ] 항목");
  assert.ok(out.includes("- [ ]x 산문"));
  assert.ok(out.includes("- [x] 항목"));
});

test("GFMOBS", () => {
  warnings.length = 0;
  check("## 배경\n- [ ]x 산문");
  assert.equal(warnings.length, 0);
});

test("GFMLOOSE", () => {
  warnings.length = 0;
  check("## 완료 조건\n- [ ]x 산문\n- [ ] 항목");
  assert.equal(warnings.length, 0);
});

test("HEADSUFFIX", () => {
  assert.ok(check("## 완료 조건 매핑\n- [ ] x").includes("- [ ] x"));
  assert.ok(check("## 완료 조건 (epic)\n- [ ] y").includes("- [x] y"));
  assert.ok(check("## 완료 조건(epic)\n- [ ] z").includes("- [ ] z"));
  assert.ok(check("## 완료 조건 — 반영판\n- [ ] w").includes("- [x] w"));
});

test("NOHTMLSTATE", () => {
  const out = check("## 완료 조건\n- [ ] A <!-- 근거:\n  상세\n-->\n- [ ] B");
  assert.ok(out.includes("- [x] A <!-- 근거:"));
  assert.ok(out.includes("- [x] B"));
});

test("LOOSE", () => {
  warnings.length = 0;
  const out = check("## 완료 조건\n- [ ] a\n    - [ ] child");
  assert.ok(out.includes("- [x] a"));
  assert.ok(out.includes("    - [ ] child"));
  assert.ok(warnings.some((w) => w.startsWith("[done-criteria:item-not-matched]")));
});

// 아래 넷은 #2509가 실측 노출 0으로 선언한 파서 공백이다. 이 파일은 동작을
// 넓히지 않는다 — 기대 동작을 todo로 적어 두고 후속 이슈가 켠다.
test("SETEXT: setext 헤딩이 절을 닫는다", { todo: true }, () => {
  assert.equal(lines("## 완료 조건\n- [ ] a\n\n다음\n---\n- [ ] b")[5], "- [ ] b");
});

test("HTMLCOMMENT: HTML 주석 안의 헤딩이 절을 켜지 않는다", { todo: true }, () => {
  assert.equal(lines("<!--\n## 완료 조건\n-->\n- [ ] a")[3], "- [ ] a");
});

test("SUBHEADING: 완료 조건 아래 하위 헤딩의 항목도 갱신한다", { todo: true }, () => {
  assert.equal(lines("## 완료 조건\n### 코드\n- [ ] a")[2], "- [x] a");
});

test("INDENT4: 4칸 들여쓴 중첩 항목도 갱신한다", { todo: true }, () => {
  assert.equal(lines("## 완료 조건\n- [ ] a\n    - [ ] child")[2], "    - [x] child");
});
