# CLI JSON 출력 마이그레이션

`--format json` 출력을 스크립트나 에이전트로 읽고 있다면, 이 문서에서 고쳐야 할 경로를 찾으세요.

> [!NOTE]
> 이 문서는 명령이 직접 만든 JSON 성공 출력을 내던 CLI 명령을 공통 성공 봉투로 옮긴 뒤 처음 나오는 릴리스에 맞춘 스냅샷입니다. 옮긴 대상은 `feed`·`init`·`update`와 `signal connect`를 뺀 계약 명령입니다(`system start`는 전부터 봉투를 직접 냅니다). 이 문서는 그 전환과 그에 딸린 실패 출력의 변경만 다루며, 그 뒤의 변경은 담지 않습니다. 명령과 옵션의 현재 목록은 [CLI 레퍼런스](cli.md)에 있습니다.

## 요약

명령 67개의 JSON 성공 출력이 공통 봉투로 바뀌었습니다. 봉투의 모양은 `{"status": "ok", "message": …, "data": …}`입니다. 전에는 이 명령들이 자기 객체나 배열을 최상위에 그대로 냈습니다. 이제는 그 객체가 키 하나 바뀌지 않고 `data` 아래에 들어가고, 배열은 `data`의 키 하나 아래에 들어갑니다. 이로써 `feed`·`init`·`update`(각자의 JSON을 직접 냅니다)와 `signal connect`(성공 봉투가 없는 스트림)를 뺀 명령의 성공 출력을 같은 방법으로 읽을 수 있습니다.

다음은 바뀌지 않았습니다.

- text 출력. 예외는 [실패 출력](#실패-출력의-변경)에 적은 것뿐입니다.
- 종료 코드. 예외는 [text 출력의 예외 하나](#text-출력의-예외-하나)뿐입니다.

```text
# 전
{"bots": [...]}

# 뒤
{"status": "ok", "message": "", "data": {"bots": [...]}}
```

옮겨진 명령의 봉투 `message`는 빈 문자열(`""`)입니다. 옛 payload 안에 있던 `message` 키는 `.data.message`에 남습니다(아래 표).

---

## ⚠️ 오류 없이 다른 값을 주는 자리

옛 출력이 최상위에 `status`·`message`·`data` 키를 갖고 있던 명령이 있습니다. 봉투도 같은 이름의 키를 최상위에 둡니다. 그래서 옛 경로를 그대로 읽는 스크립트는 실패하지 않고, 봉투의 값을 옛 값으로 알고 계속 돕니다. 다른 자리는 키가 사라지므로 스크립트가 바로 실패합니다. 이 표부터 확인하세요.

### 최상위 `.status`가 도메인 상태였던 명령

이제 최상위 `.status`는 늘 `"ok"`입니다. 옛 값은 `.data.status`에 있습니다.

| 명령 | 옛 `.status` 값의 예 | 고칠 경로 |
|------|----------------------|-----------|
| `account info` | `"active"` (계좌 상태) | `.status` → `.data.status` |
| `member info` | `"active"` (멤버 상태) | `.status` → `.data.status` |
| `member update-scopes` | `"active"` (멤버 상태) | `.status` → `.data.status` |
| `approval info` | `"pending"` (결재 상태) | `.status` → `.data.status` |
| `bot info` | `"stopped"` (봇 상태) | `.status` → `.data.status` |
| `strategy info` | `"registered"` (전략 상태) | `.status` → `.data.status` |
| `strategy set-status` | `"adopted"` (바꾼 전략 상태) | `.status` → `.data.status` |
| `trade info` | `"filled"` (거래 상태) | `.status` → `.data.status` |
| `report view` | `"submitted"` (리포트 상태) | `.status` → `.data.status` |
| `config set` | `"success"` (설정 반영 결과) | `.status` → `.data.status` |

### 최상위 `.message`에 안내 문장을 싣던 명령

이제 최상위 `.message`는 봉투의 것이고 `""`입니다. 옛 문장은 `.data.message`에 있습니다.

| 명령 | 언제 | 옛 `.message` 값의 예 |
|------|------|------------------------|
| `account list` | 빈 결과 | `"등록된 계좌가 없습니다."` |
| `account credentials` | 인증 정보 없음 | `"등록된 인증 정보가 없습니다."` |
| `account set-credentials` | 인증 정보가 필요 없는 브로커 | `"브로커 '…'에는 인증 정보가 필요하지 않습니다."` |
| `member list` | 빈 결과 | `"등록된 멤버가 없습니다."` |
| `bot list` | 빈 결과 | `"등록된 봇이 없습니다."` |
| `bot positions` | 빈 결과 | `"보유 포지션 없음"` |
| `broker positions` | 빈 결과 | `"보유 종목 없음"` |
| `strategy list` | 빈 결과 | `"등록된 전략 없음"` |
| `backtest history` | 빈 결과 | `"'<전략>' 백테스트 이력이 없습니다."` |
| `data validate` | 검증할 데이터 없음 | `"검증할 데이터가 없습니다."` |
| `trade list` | 빈 결과 | `"거래 내역 없음"` |
| `audit list` | 빈 결과 | `"감사 로그가 없습니다."` |
| `report performance` | 빈 결과 | `"집계 데이터가 없습니다."` |
| `rule list` | 빈 결과 | `"등록된 룰이 없습니다."` |
| `instrument sync` | 늘 | `"동기화 완료: 신규 N건, 갱신 N건, 상폐 N건"` |

### 최상위 `.data`가 배열이던 명령

| 명령 | 고칠 경로 |
|------|-----------|
| `treasury portfolio history` | `.data` → `.data.data` (`start_date`·`end_date`는 `.data.start_date`·`.data.end_date`) |

---

## 🔑 비밀값의 위치

비밀값이 stdout에 나가는 스트림과 횟수(한 번)는 그대로입니다. JSON 안의 자리만 바뀌었습니다.

| 명령 | 전 | 뒤 |
|------|----|----|
| `member register` | `.token` | `.data.token` |
| `member rotate-token` | `.token` | `.data.token` |
| `member regenerate-recovery-key` | `.recovery_key` | `.data.recovery_key` |
| `bot signal-key` (조회) | `.signal_key` | `.data.signal_key` |
| `bot signal-key --rotate` | `.data.signal_key` | 그대로 (전부터 봉투였다) |

```bash
# 전
ante member register --id agent-2 --type agent --name "새 에이전트" --format json | jq -r '.token'
# 뒤
ante member register --id agent-2 --type agent --name "새 에이전트" --format json | jq -r '.data.token'
```

---

## 📋 배열을 그대로 내던 명령

배열은 `data`의 키 하나 아래에 들어갑니다. 그 키는 명령마다 정해져 있습니다.

| 명령 | 뒤의 경로 |
|------|-----------|
| `approval list` | `.data.approvals` |
| `approval audit-types` | `.data.approvals` |
| `instrument list` | `.data.instruments` |
| `instrument search` | `.data.instruments` |
| `report list` | `.data.reports` |
| `treasury snapshot` (`--from`/`--to`) | `.data.snapshots` |

빈 결과의 모양이 다른 명령이 둘 있습니다. 이 명령들은 빈 결과일 때 전부터 배열이 아니라 객체를 냈고, 그 객체가 키 그대로 `data`에 들어갑니다.

- `instrument list`의 빈 결과: `.data.instruments`(빈 배열)와 `.data.count`.
- `instrument search`의 빈 결과: `.data.results`(빈 배열)와 `.data.count`. 행이 있을 때(`.data.instruments`)와 키가 다릅니다.

`treasury snapshot`은 옵션에 따라 모양이 다릅니다. `--from`/`--to`는 배열이라 `.data.snapshots` 아래에 들어갑니다. 날짜 하나를 조회하면(`--date` 또는 생략 시 가장 최근 스냅샷) 전부터 객체를 냈고, 그 객체가 `.data` 아래에 키 그대로 들어갑니다.

```bash
# 전
ante approval list --format json | jq '.[] | .id'
# 뒤
ante approval list --format json | jq '.data.approvals[] | .id'
```

---

## 📦 명령군별 전 → 뒤

일반 규칙은 하나입니다. 옛 객체는 키 하나 바뀌지 않고 `.data` 아래에 들어가며, 옛 객체 안의 `message` 키도 `.data` 안에 남습니다. 배열은 `.data.<키>` 아래에 들어갑니다(키는 위 표). 「전」 칸의 `/`는 분기(빈 결과, 서버 가동 여부 등)마다 다른 모양을 나눕니다.

```bash
# 전
ante bot list --format json | jq '.bots[]'
# 뒤
ante bot list --format json | jq '.data.bots[]'

# 전
ante config set system.log_level DEBUG --format json | jq -r '.value'
# 뒤
ante config set system.log_level DEBUG --format json | jq -r '.data.value'
```

### account 4개

| 명령 | 전 (최상위 키) | 뒤 | 주의 |
|------|----------------|-----|------|
| `account list` | {`accounts`} / {`message`·`accounts`} | `.data` 아래 같은 키 | 빈 결과일 때 `.message` → `.data.message` |
| `account info` | {`account_id`·`name`·`exchange`·`currency`·`broker_type`·`trading_mode` 외 7개} | `.data` 아래 같은 키 | `.status` → `.data.status` |
| `account credentials` | {`account_id`·`credentials`} / {`message`·`credentials`} | `.data` 아래 같은 키 | 인증 정보가 없을 때 `.message` → `.data.message` |
| `account set-credentials` | {`message`} | `.data` 아래 같은 키 | 인증 정보가 필요 없는 브로커일 때만 바뀜(`.message` → `.data.message`). 재설정 성공은 전부터 봉투 |

### member 7개

| 명령 | 전 (최상위 키) | 뒤 | 주의 |
|------|----------------|-----|------|
| `member list` | {`message`·`members`} / {`members`} | `.data` 아래 같은 키 | 빈 결과일 때 `.message` → `.data.message` |
| `member info` | {`member_id`·`type`·`role`·`org`·`name`·`emoji` 외 5개} | `.data` 아래 같은 키 | `.status` → `.data.status` |
| `member list-invalid-roles` | {`recommended_action`·`valid_roles`·`actionable_count`·`legacy_revoked_count`·`actionable`·`legacy_revoked`} | `.data` 아래 같은 키 |  |
| `member register` | {`member_id`·`type`·`role`·`org`·`name`·`token`} | `.data` 아래 같은 키 | 비밀값 `.token` → `.data.token` |
| `member update-scopes` | {`member_id`·`scopes`·`status`} | `.data` 아래 같은 키 | `.status` → `.data.status` |
| `member rotate-token` | {`member_id`·`token`} | `.data` 아래 같은 키 | 비밀값 `.token` → `.data.token` |
| `member regenerate-recovery-key` | {`recovery_key`} | `.data` 아래 같은 키 | 비밀값 `.recovery_key` → `.data.recovery_key` |

### approval 3개

| 명령 | 전 (최상위 키) | 뒤 | 주의 |
|------|----------------|-----|------|
| `approval list` | 배열 | `data.approvals` |  |
| `approval info` | {`id`·`type`·`status`·`requester`·`title`·`body` 외 9개} | `.data` 아래 같은 키 | `.status` → `.data.status` |
| `approval audit-types` | 배열 | `data.approvals` |  |

### bot 9개

| 명령 | 전 (최상위 키) | 뒤 | 주의 |
|------|----------------|-----|------|
| `bot list` | {`message`·`bots`} / {`bots`} | `.data` 아래 같은 키 | 빈 결과일 때 `.message` → `.data.message` |
| `bot info` | {`bot_id`·`name`·`strategy_id`·`account_id`·`status`·`interval_seconds` 외 1개} / {`bot_id`·`name`·`strategy_id`·`status`} | `.data` 아래 같은 키 | `.status` → `.data.status` |
| `bot signal-key` | {`bot_id`·`signal_key`} | `.data` 아래 같은 키 | 비밀값 `.signal_key` → `.data.signal_key`. `--rotate`는 전부터 봉투 |
| `bot positions` | {`message`·`positions`} / {`positions`} | `.data` 아래 같은 키 | 빈 결과일 때 `.message` → `.data.message` |
| `bot update` | {`bot_id`·`updates`·`bot`} | `.data` 아래 같은 키 |  |
| `bot logs` | {`bot_id`·`logs`·`total`} | `.data` 아래 같은 키 |  |
| `bot start` | {`bot`} | `.data` 아래 같은 키 |  |
| `bot stop` | {`bot`} | `.data` 아래 같은 키 |  |
| `bot status` | {`bot`} | `.data` 아래 같은 키 |  |

### treasury 7개

| 명령 | 전 (최상위 키) | 뒤 | 주의 |
|------|----------------|-----|------|
| `treasury status` | {`currency`·`account_balance`·`purchasable_amount`·`total_evaluation`·`purchase_amount`·`eval_amount` 외 15개} | `.data` 아래 같은 키 |  |
| `treasury transactions` | {`items`·`total`} | `.data` 아래 같은 키 |  |
| `treasury budgets` | {`budgets`} | `.data` 아래 같은 키 |  |
| `treasury set-balance` | {`account_id`·`total_balance`·`updated_at`} | `.data` 아래 같은 키 |  |
| `treasury snapshot` | {`account_id`·`snapshot_date`·`total_asset`·`ante_eval_amount`·`ante_purchase_amount`·`unallocated` 외 8개} / 배열 | `.data` 아래 같은 키 / `data.snapshots` | `--from`/`--to`는 배열 → `data.snapshots`. 날짜 하나는 객체 |
| `treasury portfolio value` | {`total_value`·`daily_pnl`·`daily_return`·`unrealized_pnl`·`accounts`·`updated_at`} | `.data` 아래 같은 키 |  |
| `treasury portfolio history` | {`data`·`start_date`·`end_date`} | `.data` 아래 같은 키 | `.data` → `.data.data` |

### strategy 6개

| 명령 | 전 (최상위 키) | 뒤 | 주의 |
|------|----------------|-----|------|
| `strategy submit` | {`submitted`·`strategy_id`·`name`·`version`·`description`·`author_name` 외 4개} | `.data` 아래 같은 키 |  |
| `strategy list` | {`message`·`strategies`} / {`strategies`} | `.data` 아래 같은 키 | 빈 결과일 때 `.message` → `.data.message` |
| `strategy info` | {`strategy_id`·`name`·`version`·`status`·`description`·`author_name` 외 4개} / {`strategy_id`·`name`·`version`·`status`·`description`·`author_name` 외 9개} / {`strategy_id`·`name`·`version`·`status`·`description`·`author_name` 외 8개} | `.data` 아래 같은 키 | `.status` → `.data.status` |
| `strategy performance` | {`strategy_name`·`strategy_id`·`metrics`} | `.data` 아래 같은 키 |  |
| `strategy set-status` | {`strategy_id`·`status`} / {`strategy_id`·`status`·`name`·`version`} | `.data` 아래 같은 키 | `.status` → `.data.status` |
| `strategy summary` | {`strategy_id`·`period`·`items`} | `.data` 아래 같은 키 |  |

### broker 5개

| 명령 | 전 (최상위 키) | 뒤 | 주의 |
|------|----------------|-----|------|
| `broker status` | {`connected`·`healthy`·`exchange`} / {`connected`·`healthy`·`error`} | `.data` 아래 같은 키 |  |
| `broker balance` | {`cash`·`total_assets`·`purchase_amount`·`eval_amount`·`total_profit_loss`·`substitute_amount` 외 2개} | `.data` 아래 같은 키 |  |
| `broker positions` | {`message`·`positions`} / {`positions`} | `.data` 아래 같은 키 | 빈 결과일 때 `.message` → `.data.message` |
| `broker order-history` | {`orders`} | `.data` 아래 같은 키 |  |
| `broker reconcile` | {`total_symbols`·`discrepancies`·`match`·`fix_applied`·`corrections`} | `.data` 아래 같은 키 |  |

### data 6개

| 명령 | 전 (최상위 키) | 뒤 | 주의 |
|------|----------------|-----|------|
| `data list` | {`datasets`·`count`} | `.data` 아래 같은 키 |  |
| `data info` | {`dataset`·`preview`} | `.data` 아래 같은 키 |  |
| `data delete` | {`dataset_id`·`symbol`·`timeframe`·`data_type`·`path`·`deleted`} | `.data` 아래 같은 키 |  |
| `data schema` | {`timestamp`·`symbol`·`open`·`high`·`low`·`close` 외 3개} | `.data` 아래 같은 키 |  |
| `data storage` | {`total_bytes`·`total_mb`·`by_timeframe`} | `.data` 아래 같은 키 |  |
| `data validate` | {`message`·`results`} / {`results`·`summary`} | `.data` 아래 같은 키 | 검증할 데이터가 없을 때 `.message` → `.data.message` |

### instrument 4개

| 명령 | 전 (최상위 키) | 뒤 | 주의 |
|------|----------------|-----|------|
| `instrument list` | {`instruments`·`count`} / 배열 | `.data` 아래 같은 키 / `data.instruments` | 행이 있으면 배열 → `data.instruments`(`count` 없음). 빈 결과는 객체였다 |
| `instrument sync` | {`sync_result`·`message`} | `.data` 아래 같은 키 | `.message` → `.data.message` |
| `instrument search` | {`results`·`count`} / 배열 | `.data` 아래 같은 키 / `data.instruments` | 행이 있으면 배열 → `data.instruments`. 빈 결과는 `data.results`·`data.count` |
| `instrument import` | {`dry_run`·`total`·`preview`} | `.data` 아래 같은 키 | `--dry-run`만 바뀜. 실제 import는 전부터 봉투 |

### trade 2개

| 명령 | 전 (최상위 키) | 뒤 | 주의 |
|------|----------------|-----|------|
| `trade list` | {`message`·`trades`} / {`trades`} | `.data` 아래 같은 키 | 빈 결과일 때 `.message` → `.data.message` |
| `trade info` | {`trade_id`·`bot_id`·`strategy_id`·`symbol`·`side`·`quantity` 외 7개} | `.data` 아래 같은 키 | `.status` → `.data.status` |

### backtest 2개

| 명령 | 전 (최상위 키) | 뒤 | 주의 |
|------|----------------|-----|------|
| `backtest run` | {`strategy`·`period`·`initial_balance`·`final_balance`·`total_return_pct`·`total_trades` 외 9개} | `.data` 아래 같은 키 |  |
| `backtest history` | {`message`·`runs`} / {`strategy_name`·`runs`} | `.data` 아래 같은 키 | 빈 결과일 때 `.message` → `.data.message` |

### report 4개

| 명령 | 전 (최상위 키) | 뒤 | 주의 |
|------|----------------|-----|------|
| `report schema` | {`required_fields`·`optional_fields`·`format`·`example`} | `.data` 아래 같은 키 |  |
| `report list` | 배열 | `data.reports` |  |
| `report performance` | {`message`·`summaries`} / {`period`·`summaries`} | `.data` 아래 같은 키 | 빈 결과일 때 `.message` → `.data.message` |
| `report view` | {`report_id`·`strategy`·`status`·`submitted_at`·`submitted_by`·`backtest_period` 외 10개} | `.data` 아래 같은 키 | `.status` → `.data.status` |

### system 1개

| 명령 | 전 (최상위 키) | 뒤 | 주의 |
|------|----------------|-----|------|
| `system status` | {`trading_state`·`bot_count`} | `.data` 아래 같은 키 |  |

### config 3개

| 명령 | 전 (최상위 키) | 뒤 | 주의 |
|------|----------------|-----|------|
| `config get` | {`key`·`value`·`source`} / {`configs`} | `.data` 아래 같은 키 |  |
| `config set` | {`status`·`key`·`value`} | `.data` 아래 같은 키 | `.status` → `.data.status` |
| `config history` | {`key`·`history`} | `.data` 아래 같은 키 |  |

### rule 3개

| 명령 | 전 (최상위 키) | 뒤 | 주의 |
|------|----------------|-----|------|
| `rule list` | {`message`·`rules`} / {`rules`} | `.data` 아래 같은 키 | 빈 결과일 때 `.message` → `.data.message` |
| `rule info` | {`rule_id`·`name`·`scope`·`enabled`·`priority`·`description`} | `.data` 아래 같은 키 |  |
| `rule update` | {`account_id`·`rule_type`·`rule`} / {`account_id`·`rule_type`} | `.data` 아래 같은 키 |  |

### audit 1개

| 명령 | 전 (최상위 키) | 뒤 | 주의 |
|------|----------------|-----|------|
| `audit list` | {`message`·`logs`} / {`logs`} | `.data` 아래 같은 키 | 빈 결과일 때 `.message` → `.data.message` |

---

## ❌ 실패 출력의 변경

JSON 모드의 실패는 다음 모양의 에러 봉투로 stdout에 한 줄로 나갑니다. text 모드의 실패는 stderr에 `Error: <code>: <message>` 줄을 냅니다. 다음 자리에서는 그 줄의 앞이나 뒤로 줄이 더 나갑니다.

- `strategy validate`·`strategy submit`의 검증 실패(text): 첫 줄 뒤에 오류마다 `  - <오류>` 줄이 이어지고, `validate`는 경고마다 `  [warn] <경고>` 줄도 이어집니다.
- `update`의 마이그레이션 실패(text): 에러 줄 앞에 마이그레이션 실패·롤백 안내 줄이 먼저 나갑니다(stderr. 롤백이 끝났다는 안내는 stdout).
- `init`이 master를 만든 뒤 테스트 계좌 생성에 실패할 때(JSON): 에러 봉투 앞에 복구용 한 줄 JSON이 stderr로 먼저 나갑니다.

```json
{"status": "error", "code": "<STABLE_ERROR_CODE>", "message": "<사람이 읽는 메시지>", "details": {"stage": "load"}}
```

`details`는 선택 키라서 상세가 있는 실패에만 있습니다. 에러 봉투의 JSON은 비 ASCII 문자를 `\uXXXX`로 이스케이프합니다. JSON 파서로 읽으면 원래 문자열이 나옵니다.

### `strategy validate`·`strategy submit`

| 자리 | 전 | 뒤 |
|------|----|----|
| `validate` 실패 (text) | `Error: Validation failed: <파일>` | `Error: STRATEGY_VALIDATION_FAILED: Validation failed: <파일>` |
| `validate` 실패 (JSON) | 여러 줄. `{"status": "error", "code", "message", "data": {"valid": false, "errors": [...], "warnings": [...]}}` | 한 줄. `{"status": "error", "code", "message", "details": {"errors": [...], "warnings": [...]}}` |
| `submit` 검증 실패 (text) | `Error: Validation failed: <파일>` | `Error: STRATEGY_VALIDATION_ERROR: Validation failed: <파일>` |
| `submit` 검증 실패 (JSON) | `{"submitted": false, "stage": "validate", "code", "errors": [...]}` | `{"status": "error", "code", "message", "details": {"stage": "validate", "errors": [...]}}` |
| `submit` 로드 실패 (JSON) | `{"submitted": false, "stage": "load", "code": "STRATEGY_LOAD_ERROR", "error": "<원인>"}` | `{"status": "error", "code": "STRATEGY_LOAD_ERROR", "message": "Load test failed: <원인>", "details": {"stage": "load"}}` |
| `submit` meta 실패 (JSON) | `{"submitted": false, "stage": "meta_validation", "code": "STRATEGY_VALIDATION_ERROR", "error": "<한국어 문장>"}` | `{"status": "error", "code": "STRATEGY_VALIDATION_ERROR", "message": "Invalid meta shape: expected StrategyMeta, got <타입>", "details": {"stage": "meta_validation"}}` |
| `submit` 등록 실패 (JSON) | `{"submitted": false, "stage": "register", "code": <예외의 code, 기본 "STRATEGY_ERROR">, "error": "<원인>"}` | `{"status": "error", "code": <예외의 code, 기본 "STRATEGY_ERROR">, "message": "<원인>", "details": {"stage": "register"}}` |

`submit`의 실패 출력에서 바뀐 것은 다음과 같습니다.

- `submitted: false`가 사라지고 `status: "error"`가 그 자리를 맡습니다.
- `stage`는 `.details.stage`로, `errors`는 `.details.errors`로 옮겨졌습니다.
- `error`는 `.message`가 됩니다. 로드 실패와 meta 실패의 `.message`는 text 출력의 문장과 같습니다.

### `signal connect`

연결 실패의 text 출력(stderr)에 `Error: <code>: ` 접두가 붙습니다. JSON 모드에서 연결 실패 다섯 자리(소켓 없음·연결 거부·시간 초과·응답 끊김·데몬 거부)는 전부터 에러 봉투를 냈고 그대로입니다. 종료 코드(1)도 그대로입니다.

| 실패 | 전 (text) | 뒤 (text) |
|------|-----------|-----------|
| 소켓 없음·연결 거부·응답 끊김 | `<서버 미기동 안내>` | `Error: IPC_SERVER_NOT_RUNNING: <서버 미기동 안내>` |
| 시간 초과 | `서버 응답 시간 초과` | `Error: IPC_TIMEOUT: 서버 응답 시간 초과` |
| 데몬이 거부 | `Invalid signal key` 등 | `Error: INVALID_SIGNAL_KEY: Invalid signal key` 등 |

### text 출력의 예외 하나

`strategy info`는 전략의 파라미터가 사전이 아닐 때 전에는 표의 앞부분을 stdout에 낸 뒤 `Error: EXECUTION_ERROR: …`를 내고 종료 코드 1로 끝났습니다. 이제는 성공하고(종료 코드 0) 그 값을 `파라미터` 줄 한 줄로 냅니다.

---

## ✅ 바뀌지 않은 것

- **text 출력** — 위 실패 출력의 접두와 예외 하나를 빼고 그대로입니다.
- **종료 코드** — 위 text 출력의 예외 하나를 빼고 이 문서의 명령 모두 그대로입니다.
- **전부터 봉투였던 명령의 JSON** — 다음 명령은 전부터 `{"status": "ok", "message", "data"}`를 냈고 그대로입니다.
  - `account activate`·`create`·`delete`·`repair-timezone`·`suspend`
  - `approval approve`·`cancel`·`cancel-invalid`·`reject`·`reopen`·`request`·`review`
  - `bot create`·`remove`
  - `member reactivate`·`reset-password`·`revoke`·`set-emoji`·`suspend`
  - `report submit`
  - `strategy validate`(성공)
  - `system clear-halt`·`halt`·`stop`
  - `treasury allocate`·`deallocate`
  - 위 표에서 「전부터 봉투」로 적은 분기
- **`feed`·`init`·`update`** — 이 문서의 봉투 전환 대상이 아니며, 각자의 JSON을 직접 냅니다.
- **`system start`** — 자식 프로세스를 띄우기 전에 봉투를 한 번 직접 냅니다. JSON 모드에서는 자식의 출력을 stderr로 보냅니다. 자식의 종료 코드로 끝나고, Ctrl+C에서는 종료 코드 0으로 끝납니다. 모두 그대로입니다.
- **`signal connect`의 스트림** — stdin·stdout 위의 JSON Lines 스트림은 그대로입니다. 성공 봉투는 내지 않고, 연결 실패는 위와 같이 에러 봉투를 냅니다.
