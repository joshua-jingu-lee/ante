# D-017: canonical symbol/timeframe vocabulary (2026-05-16)

> Ante 설계 결정 기록.
> 인덱스: [README.md](README.md)

**결정**: Ante 전역에서 OHLCV bar `timeframe`과 신규 입력 `symbol`이 의미하는
canonical vocabulary와 적용 범위를 **단일 계약(SSOT)으로 확정**한다. 계약 본문
(canonical timeframe set·고정 순서, KRX symbol shape, symbol/timeframe 축 구분
A~F, per-surface 허용/거부·에러 계약 매트릭스, legacy 호환 정책, 소비자 매핑)은
[docs/specs/core/core.md](../specs/core/core.md#canonical-symboltimeframe-vocabulary)
`## Canonical Symbol/Timeframe Vocabulary` 절에 둔다. 본 ADR은 결정·근거·소비자
영향만 기록하고 계약 디테일을 중복 기재하지 않는다.

핵심 (결정 요약 — 계약 본문은 core.md `## Canonical Symbol/Timeframe Vocabulary`):

- canonical OHLCV bar timeframe set `[1m, 5m, 15m, 1h, 1d]`(고정 순서·exact-literal·
  no-alias·no-normalization), KRX symbol shape(`^[0-9]{6}$`, **resolved exchange ==
  KRX인 신규 입력 경계 한정** — 비-KRX exchange symbol format은 본 SSOT 무제약·1.0
  비목표; exchange vocabulary 자체는 D-016 규율), symbol/timeframe 축
  구분(A OHLCV bar timeframe / B subminute 파티셔닝 / C `tick`·`fundamental`
  data_type / D write-ownership / E 신규 입력 vs legacy path 판별 / F fundamental
  cadence), per-surface 거부 계약·legacy 호환을 **단일 계약으로 확정**하고, 그 본문은
  D-017이 아니라
  [core.md `## Canonical Symbol/Timeframe Vocabulary`](../specs/core/core.md#canonical-symboltimeframe-vocabulary)
  절에 둔다. 본 ADR은 계약 디테일(값 집합·축 정의·거부 경계·표면별 계약)을 독립
  서술하지 않으며, 모든 디테일은 해당 절을 단일 참조점으로 가리킨다.
- 검증 범위의 결정: 검증은 **신규 입력 경계에만** 적용하고, 기존 영속 데이터의
  `read` 호환은 깨지 않는다(legacy 무손상 — 자동 삭제·마이그레이션 없음).
  legacy parquet path migration 판별(`store.py` `\d` 보존)은 신규 입력 strict
  검증과 별개 축이다(축 E). `read`가 어떻게 규율되는지의 계약 본문은 core.md의
  "Legacy out-of-vocabulary 호환 정책" 절이 SSOT다.

**근거**:

- symbol/timeframe vocabulary SSOT 후보(#1602)의 Plan Preflight가 `split-issue`로
  보류되며, 작업이 `#1612 docs-only 계약` / `#1613 코드 SSOT` / 표면별
  enforcement(#1603~#1611)로 분리됐다. 최신 스펙 확인 결과 OHLCV timeframe·KRX
  symbol vocabulary의 SSOT가 부재했고 normative 서술이 여러 스펙에 분산되어 있었다:
  - `docs/specs/web-api/05-resource-endpoints.md:77` — 인라인 `SSOT:
    ante.data.schemas.TIMEFRAMES` 선언.
  - `docs/specs/data-pipeline/03-design-decisions.md:66` — `TIMEFRAMES: list[str]`
    (소스: `src/ante/data/schemas.py`).
  - `docs/specs/data-pipeline/02-write-ownership.md` — write-ownership 표(축 D).
  - `docs/specs/data-feed/04-schema.md:37` — `10s/30s` subminute 파티셔닝(축 B).
  - `docs/specs/strategy/03-01-strategy-interface.md:19` — `timeframe` 기본값 서술
    `1m, 5m, 15m, 1h, 1d 등`.
- SSOT가 없으면 표면마다 invalid timeframe/symbol 누락을 사후에 반복 발견한다.
  계약을 먼저 스펙에 확정해야 enforcement·회귀 고정이 한 기준으로 수렴한다.
  exchange 선례(에픽 #1561 → D-016 docs-only 결정으로 core.md `## Canonical
  Exchange Vocabulary` + ADR + 영향 스펙 단일 참조 pointer, commit 2562168 →
  코드 SSOT #1576 → 표면별 enforcement)와 동일 순서를 따라 먼저 docs-only 계약을
  확정한다.
- 계약 본문 위치를 `docs/specs/core/core.md`로 정한 이유: OHLCV bar timeframe·KRX
  symbol은 특정 모듈 소유 개념이 아니라 data/web-api/cli/strategy/backtest가
  공유하는 식별 차원이며, core 모듈 개요가 "모든 모듈이 공유하는 기반 인프라"로
  정의되어 있다. D-017을 normative SSOT로 두면 ADR이 계약 본문을 머금게 되어 결정
  기록의 역할을 벗어나므로, ADR은 core.md 절을 링크하는 결정 기록으로 유지한다.
- timeframe을 **다축(A~F)으로 명문화한 이유**: 같은 `1m`/`1d`/`10s` 리터럴이라도
  OHLCV bar vocabulary(축 A)·subminute 파티셔닝(축 B)·write-ownership(축 D)·신규
  입력 vs legacy path(축 E)에 따라 규율 SSOT가 다르다. core.md 축 구분 절을 D-016
  "exchange vs market vs source vs broker_type" 동형으로 두어 값을 섞지 않는 경계를
  고정한다.
- live DataCollector ingress enforcement를 **#1614로 분리한 이유**: `collector.py`
  는 현재 `data_type='ohlcv'` append만 수행하며 vocabulary enforcement가 미구현인
  누락 소비자다. 본 docs-only 계약은 매트릭스에 #1614 참조(OHLCV `{1m,5m,15m,1h}`만,
  `1d`는 write-ownership상 DataFeed 소유라 제외, `tick`은 별도 data_type라 제외)로
  경계를 명시하고, ingress enforcement 자체는 #1614(Depends on #1613)에 위임한다.
- fundamental cadence(`quarterly`/`annual`)를 **본 계약에서 제외하고 후보 D로
  deferral한 이유**: `quarterly`/`annual`이 `dataset.timeframe` 필드에 overload되어
  있고(dashboard user-stories/mockups, fundamental parquet `quarterly.parquet`/
  `annual.parquet`), #1594 datasets API는 OHLCV vocabulary 외 값을 400 거부한다.
  이 cross-surface 불일치는 #1612가 만든 것이 아닌 기존 문제다. 본 canonical
  OHLCV-timeframe 계약은 `quarterly`/`annual`을 포함하지 않으며, 축 F를 "별개 축,
  필드 의미 정리는 후보 D" 까지만 명문화한다. 후보 D 이슈는 plan-preflight 계약상
  자동 생성하지 않고(사람 등록 surface) 경계만 명시·deferral한다.
- 기존 분산 SSOT를 core.md 단일 계약으로 수렴시킨 이유: 인라인 SSOT 표기·분산된
  normative 서술이 여러 스펙에 흩어져 있으면 drift가 누적된다. core.md 절을 단일
  참조점으로 두고 영향 스펙은 pointer-line으로 가리키게 하여 SSOT 위치를 단일화한다
  (값 집합 자체는 재작성하지 않음 — 위치 단일화·축 명문화만).

**소비자 영향 및 후속 이슈**:

| 소비자 / 작업 | 영향 | 후속 이슈 |
|---------------|------|-----------|
| 코드 레벨 SSOT(`ante.core.market_data_vocab` 신설, `TIMEFRAMES`/KRX regex 소비자 위임) | 표면별 상수·regex 산재를 단일 SSOT로 정렬 | #1613 |
| `DEFAULT_RETENTION` timeframe dict keys (보존 정책 dict 키) | 보존 정책 dict 키도 코드 SSOT 정렬 대상 (보존 기간 값은 retention 정책 고유) | #1613 |
| Backtest run CLI timeframe enforcement | non-canonical 신규 입력 → non-zero exit + 구조화 error payload | #1603 |
| Backtest programmatic API timeframe enforcement | non-canonical → 검증 에러 | #1604 |
| `data validate` CLI timeframe enforcement | non-canonical → non-zero exit + 구조화 error payload | #1605 |
| `feed inject` timeframe enforcement | non-canonical → 거부 | #1606 |
| Instrument import KRX symbol shape enforcement (primary — `cli/commands/instrument.py` import handler, 현재 exchange만 검증) | exchange=KRX 행 non-`^[0-9]{6}$` → non-zero exit + 구조화 error payload | #1611 |
| legacy parquet path migration KRX 판별 (축 E legacy — 신규 입력 검증과 별개 축) | `store.py` `_KRX_SYMBOL_PATTERN`/`migrate_parquet_paths` legacy 호환 무손상 보존 | **#1611 enforcement 대상 아님** (축 E legacy) |
| RuleEngine OrderRequestEvent KRX numeric preflight | `rule/engine.py` `_KRX_NUMERIC_SYMBOL_PATTERN` #1299 기존 동작 — 본 SSOT 도입으로 동작 불변 | **#1299** (불변, #1611 아님) |
| Data API `timeframe` filter (기구현 400) | vocabulary 외 timeframe 400 거부 기구현 | #1594 |
| Data API `symbol` filter 잔여 vocabulary 거부 (현재 200 empty 유지) | invalid `symbol`은 현재 200 empty (web-api/05 계약과 정합, **#1594 아님**) — exchange-aware symbol SSOT 후속 정렬 | **#1613 코드 SSOT 체인** |
| **Live DataCollector write·경로 생성** (OHLCV `{1m,5m,15m,1h}`만, `1d`·`tick` 제외) | 누락 소비자 ingress enforcement 추적 폐쇄 | **#1614** (Depends on #1613) |
| fundamental cadence `dataset.timeframe` overload reconciliation (축 F) | dashboard user-stories/mockups ↔ #1594 datasets API OHLCV-only 400 cross-surface 불일치 docs 정합화 | **후보 D** (deferral, 사람 등록) |

본 ADR과 영향 스펙(web-api/data-pipeline/data-feed/strategy)은 core.md
`## Canonical Symbol/Timeframe Vocabulary` 절을 단일 참조점으로 가리킨다. 영향
스펙의 normative 값 집합은 본 결정에서 재작성하지 않으며(값 `{1m,5m,15m,1h,1d}`·
보존 기간 수치·축 정의 불변), 코드 레벨 SSOT·표면별 enforcement·후보 D는 위
후속 이슈에서 수행한다(docs-only 결정).
