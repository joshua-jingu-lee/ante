# D-016: canonical exchange vocabulary (2026-05-15)

> Ante 설계 결정 기록.
> 인덱스: [README.md](README.md)

**결정**: Ante 전역에서 `exchange`가 의미하는 canonical vocabulary와 적용 범위를
**단일 계약(SSOT)으로 확정**한다. 계약 본문(canonical set, wildcard 정책,
canonical-known vs 1.0 account-supported 구분, exchange vs market/source/broker_type
경계, per-surface 허용/거부·에러 계약 매트릭스, legacy 호환 정책, 소비자 매핑)은
[docs/specs/core/core.md](../specs/core/core.md#canonical-exchange-vocabulary)
`## Canonical Exchange Vocabulary` 절에 둔다. 본 ADR은 결정·근거·소비자 영향만
기록하고 계약 디테일을 중복 기재하지 않는다.

핵심 (결정 요약 — 계약 본문은 core.md `## Canonical Exchange Vocabulary`):

- canonical set·`StrategyMeta.exchange` 전용 wildcard·exchange vs market/source/
  broker_type 경계·canonical-known vs 1.0 account preset 구분·per-surface 거부
  계약·legacy 호환을 **단일 계약으로 확정**하고, 그 본문은 D-016이 아니라
  [core.md `## Canonical Exchange Vocabulary`](../specs/core/core.md#canonical-exchange-vocabulary)
  절에 둔다. 본 ADR은 계약 디테일(거부 경계·표면별 계약·필드명)을 독립 서술하지
  않으며, 모든 디테일은 해당 절을 단일 참조점으로 가리킨다.
- 검증 범위의 결정: 검증은 **신규 입력·경로 식별 경계에만** 적용하고, 기존
  영속 데이터의 `read` 호환은 깨지 않는다(legacy 무손상 — 에픽 #1561 비목표).
  `read`가 어떻게 규율되는지의 계약 본문은 core.md의 "Legacy out-of-vocabulary
  호환 정책" 절이 SSOT다(`read`에 신규 입력 검증 미적용).

**근거**:

- 에픽 #1561은 `instrument` CLI가 `ORACLE_INVALID_EXCHANGE`(invalid exchange 입력)을
  성공 처리한 A7 oracle 리포트에서 시작했다. 최신 스펙 확인 결과 instrument /
  account / data / strategy 간 `exchange` 허용값의 SSOT가 부재했다:
  - Instrument: `exchange: str = "KRX"`, 허용 vocabulary 미정의
    (`docs/specs/instrument/instrument.md:32-34`).
  - Strategy: `{KRX, NYSE, NASDAQ, AMEX, TEST, *}`
    (`src/ante/strategy/validator.py:9` `VALID_EXCHANGES`).
  - Account: `{KRX, NYSE, NASDAQ, TEST}` (`docs/specs/account/03-data-model.md:34`),
    1.0 preset은 `KRX`,`TEST`만 (`docs/specs/account/03-data-model.md`의
    `BROKER_PRESETS` `test`/`kis-domestic` 항목).
  - DataStore: `{KRX, NYSE, NASDAQ, AMEX, TEST}`를 path migration 판별에 사용
    (`src/ante/data/store.py:26` `_KNOWN_EXCHANGES`).
- SSOT가 없으면 oracle A7 host probe가 표면마다 invalid exchange 누락을 사후에
  반복 발견한다(D-015의 인증 누락 회귀와 같은 구조의 문제). 계약을 먼저 스펙에
  확정해야 enforcement·회귀 고정이 한 기준으로 수렴한다.
- 계약 본문 위치를 `docs/specs/core/core.md`로 정한 이유: `exchange`는 특정 모듈
  소유 개념이 아니라 instrument/account/data/strategy/backtest가 공유하는 식별
  차원이며, core 모듈 개요가 "모든 모듈이 공유하는 기반 인프라"로 정의되어 있다.
  D-016을 normative SSOT로 두면 ADR이 계약 본문을 머금게 되어 결정 기록의 역할을
  벗어나므로, ADR은 core.md 절을 링크하는 결정 기록으로 유지한다.
- wildcard `*`를 `StrategyMeta.exchange`에만 허용하는 이유: `*`는 거래소 식별자가
  아니라 "시장 무관 범용 전략"이라는 전략 메타 의미값이다. account/instrument/data
  경계에서 `*`는 실제 데이터·계좌·경로를 식별할 수 없으므로 거부가 자명하다.
- legacy 무손상 호환을 택한 이유: 기존 DB/Parquet 마이그레이션 실행은 에픽 #1561
  비목표다. 검증을 신규 입력 경계로 한정하면 계약 도입이 기존 데이터 읽기 호환성을
  깨지 않고 점진 적용된다.

**소비자 영향 및 후속 이슈**:

| 소비자 / 작업 | 영향 | 후속 이슈 |
|---------------|------|-----------|
| 코드 레벨 SSOT(canonical 상수 단일화) | 표면별 상수 산재를 단일 SSOT로 정렬 | #1576 |
| Instrument CLI `list`/`sync`/`import` | non-canonical 신규 입력 → non-zero exit + 구조화 error payload (주 신규 입력 표면) | #1577 |
| account/data/backtest/strategy 경계면 정렬 + backtest `--exchange` 옵션 신설 | 표면별 거부 계약 정렬, backtest override는 현재 spec-vs-impl gap | #1578 |
| 회귀 테스트 고정 | 표면별 거부 동작 회귀 방지 | #1579 |
| 에픽 | 결정 사항 링크 | #1561 |

본 ADR과 영향 스펙(instrument/strategy/account/data-pipeline/data-feed/cli)은
core.md `## Canonical Exchange Vocabulary` 절을 단일 참조점으로 가리킨다. 영향
스펙의 normative 값 집합은 본 결정에서 재작성하지 않으며, 표면별 enforcement·정렬은
위 후속 이슈에서 수행한다(docs-only 결정).
