# 스테이징 환경 구축 설계

> 상태: **Draft (사용자 리뷰 대기)**
> 작성일: 2026-04-17
> 범위: 스테이징 호스팅, 배포, 로그 포맷, 감시 에이전트
> 관련 스펙: [docs/specs/config/03-design-decisions.md](../../specs/config/03-design-decisions.md), [docs/specs/broker-adapter/07-kis-base-adapter.md](../../specs/broker-adapter/07-kis-base-adapter.md), [docs/specs/account/04-account-service.md](../../specs/account/04-account-service.md)

## 1. 배경과 문제

현재 환경은 두 가지다.

- **Production**: 홈서버에서 24h 구동, 실계좌 매매
- **QA**: `docker-compose.qa.yml` + `Dockerfile.qa`, TestBrokerAdapter 기반, Gherkin TC 자동 실행용 (CI 포함)

그 사이에 **실제 외부 API와 붙은 채 장시간 운용 시 어떻게 행동하는지** 관찰할 수 있는 공간이 비어 있다. 특히 다음 두 시나리오를 다룰 수 없다.

- KIS WebSocket 스트림을 하루/며칠 켜놓았을 때의 재접속·누수·끊김 거동
- KIS 모의투자 계좌에 실제 주문을 넣었을 때의 응답·수수료·체결 흐름

QA는 결정론적 무상태 테스트용이라 이 관찰을 담을 수 없고, Production에서 검증하는 것은 위험하다. 이 공백을 메우는 **제3의 상시 환경**이 필요하다.

## 2. 목적과 비목적

### 2.1 목적
- 실제 KIS 모의투자 API에 24h 연결된 상태로 Ante 풀 스택이 돌아가는 상시 환경을 제공한다.
- 장시간 운용 중 발생한 에러/이상 징후를 **자동으로 GitHub Issue로 승격**한다.
- 업그레이드 시점을 사용자가 통제할 수 있다 (의도치 않은 재시작으로 관찰이 끊기지 않는다).

### 2.2 비목적
- 실시간 알림(Telegram 즉시 알림 등)은 범위 밖이다. 감시는 주기적(시간 단위)이다.
- 부하/성능 벤치마크 환경은 아니다. 단일 인스턴스 관찰용이다.
- 릴리즈 파이프라인 게이트(RC 승격·자동 프로모션)는 범위 밖이다. 필요 시 후속 반복에서 다룬다.

## 3. 아키텍처 개요

### 3.1 3계층 환경 배치

| 환경 | 호스트 | 가동 | 브로커 | 실행 빈도 |
|---|---|---|---|---|
| Production | 홈서버 | 24/7 | 실계좌 | 상시 |
| **Staging** | **맥미니** | **24/7** | **KIS 모의투자** | **상시** |
| QA | CI 러너 / 임시 | on-demand | TestBrokerAdapter | TC 실행 시 |

### 3.2 Docker 자산 재사용

| 파일 | Production | Staging | QA |
|---|:---:|:---:|:---:|
| `Dockerfile` | ✅ | ✅ (재사용) | — |
| `Dockerfile.qa` | — | — | ✅ |
| `docker-compose.yml` | ✅ | — | — |
| `docker-compose.qa.yml` | — | — | ✅ |
| `docker-compose.staging.yml` | — | ✅ (신규) | — |

Staging은 Production과 동일한 풀 이미지(프론트엔드 포함)를 사용한다. 이미지 빌드·배포 파이프라인은 기존 [.github/workflows/publish.yml](../../.github/workflows/publish.yml)을 재사용한다 (main 푸시 시 GHCR에 push).

### 3.3 배포 흐름 (수동)

```
main 머지 → GHCR publish (자동)
             ↓
맥미니에서 사용자가 원할 때:
  docker compose -f docker-compose.staging.yml pull
  docker compose -f docker-compose.staging.yml up -d
```

배포를 수동으로 유지하는 이유: 장시간 스트림 관찰 중 원치 않는 재시작이 관찰을 끊지 않도록 사용자가 업그레이드 시점을 통제한다.

## 4. 환경 구성 (Config·Secrets)

### 4.1 스펙 준수 원칙

[docs/specs/config/03-design-decisions.md](../../specs/config/03-design-decisions.md)의 설정 계층 구조를 그대로 따른다. 새 환경변수 스키마를 만들지 않는다.

- 정적 설정 → `config/system.toml`
- 비밀값 → `config/secrets.env`
- 동적 설정 → SQLite `dynamic_config`
- 계좌 정보 → Account 모델 (`is_paper`, `trading_mode` 등)

### 4.2 맥미니 로컬 파일 배치

맥미니에는 리포를 한 번 clone 해두고 그 워킹 디렉토리에서 compose를 실행한다. 별도 경로 복제 없이 git 업데이트만 주기적으로 수행한다.

```
~/Projects/ante/                    # git clone한 리포
├── docker-compose.staging.yml      # 리포에 포함
├── config/
│   ├── system.toml                 # 스테이징 값 (gitignored)
│   └── secrets.env                 # KIS_PAPER01_* 등 (gitignored)
└── logs/                           # JSONL 볼륨 마운트 지점 (gitignored)
```

`config/system.toml`, `config/secrets.env`는 기존 [.gitignore](../../../.gitignore) 규칙에 포함되어 있다. `logs/`는 본 설계 구현 시 `.gitignore`에 추가한다 (§10 스펙 보강 항목).

### 4.3 핵심 차이점만 요약

| 설정 | Production | Staging |
|---|---|---|
| `system.log_level` | INFO | INFO (동일) |
| `web.port` | 3982 | 3982 (맥미니 단독 사용이므로 동일) |
| KIS 크리덴셜 | `KIS_DEFAULT_*` (실계좌) | `KIS_PAPER01_*` (모의투자) |
| Account 초기 세팅 | `trading_mode=LIVE`, `is_paper=False` | `trading_mode=LIVE`, `is_paper=True` |
| Telegram | 운영 봇 | 스테이징 전용 봇 (또는 생략 — §9 참조) |
| 환경변수 `ANTE_ENV` | `production` | `staging` |

### 4.4 `ANTE_ENV` 환경변수 신규 도입

로그 `env` 필드(§6) 및 감시 에이전트가 환경 식별에 사용한다. 기본값은 `production`으로 기존 동작과 호환.

## 5. 볼륨과 데이터 보존

| 볼륨 | 경로 | 보존 |
|---|---|---|
| `ante_staging_db` | `/app/db` | 영속 (수동 리셋) |
| `ante_staging_data` | `/app/data` | 영속 |
| `ante_staging_logs` | `/app/logs` | 30일 순환 (§6.4) |

QA 컴포즈의 `ante_ante-data:ro` 같은 프로덕션 볼륨 참조 마운트는 사용하지 않는다 (물리적 격리).

## 6. 구조화 JSONL 로그

> 본 섹션은 스테이징 환경 기준의 요약이다. 로그 시스템의 공식 스펙은 [docs/specs/logging/](../../specs/logging/)가 SSOT이며, 필드 스키마·fingerprint 규칙·핸들러 구성·회전 정책은 거기서 관리한다. 본 섹션은 그 요약 인용이다.

### 6.1 도입 범위

**전역 도입**을 권장한다 (Production/QA/Staging 모두). 이중 핸들러 구조:

- **콘솔 stdout**: 컬러 평문 (기존 포맷 유지, 개발자 경험 보존)
- **파일 `logs/ante-YYYY-MM-DD.jsonl`**: JSONL

단, 본 문서의 1차 구현 범위는 **JSONL 파일 핸들러를 환경변수 `ANTE_LOG_JSONL=1`이 켜질 때만 활성화**한다. Staging에서 먼저 켜고 실전 운영에서 문제없음이 확인되면 Production에서도 켠다.

### 6.2 필수 필드

| 필드 | 타입 | 예 |
|---|---|---|
| `ts` | ISO 8601 UTC | `"2026-04-17T20:15:32.145Z"` |
| `level` | string | `"ERROR"` |
| `logger` | string | `"ante.broker.kis.adapter"` |
| `msg` | string | `"주문 전송 실패"` |
| `env` | string | `"staging"` |

### 6.3 선택 컨텍스트 필드 (`extra`로 주입)

`account_id`, `bot_id`, `strategy_id`, `order_id`, `symbol`, `request_id`, `extra`(자유 객체)

### 6.4 Exception 필드

```json
{
  "exc": {
    "type": "ConnectionError",
    "message": "WebSocket closed unexpectedly",
    "traceback": "Traceback (most recent call last):\n  ...",
    "fingerprint": "ConnectionError@ante.broker.kis.stream:handle_reconnect"
  }
}
```

**Fingerprint 규칙**: `{exception class}@{스택 상 최근 프레임 중 ante.*로 시작하는 것의 module:function}`.
- 스택에 `ante.*` 프레임이 없으면 `{exception class}@{logger 이름}`으로 폴백.
- 라인번호는 포함하지 않는다 (리팩터링 저항).

### 6.5 회전·보관

- 회전: `TimedRotatingFileHandler(when="midnight", utc=False)` — Asia/Seoul 자정 기준
- 보관: 30일, 3일 이후 파일은 gzip 압축
- 디렉토리: 컨테이너 `/app/logs` (볼륨 마운트)

### 6.6 구현 위치

신규 모듈 `src/ante/log/json_formatter.py`(신설)에 `JsonFormatter`를 두고, [src/ante/main.py](../../src/ante/main.py)의 `_init_core`에서 `ANTE_LOG_JSONL` 환경변수에 따라 핸들러를 추가한다.

> 모듈명을 `ante.log`로 둔다. 표준 라이브러리 `logging`과 이름 충돌을 피하고, 신규 로깅 관련 자산(JsonFormatter, 회전 정책, 컨텍스트 필드 래퍼 등)을 한 곳에 모은다.

## 7. 감시 에이전트 (Staging Watcher)

### 7.1 실행 모델

**Claude Code 에이전트 루틴** — 맥미니의 `launchd`가 6시간마다 Claude Code CLI를 호출한다. 상주 Python 데몬은 사용하지 않는다.

### 7.2 커맨드 정의

신규 파일 [.agent/commands/staging-watch.md](../../.agent/commands/staging-watch.md).

**책임**:
1. 맥미니의 `~/ante-staging/logs/ante-*.jsonl` 중 지난 감시 이후 엔트리를 읽는다 (마지막 감시 시각은 `~/.ante-staging-watcher/last-run.txt`에 보관).
2. `level ∈ {ERROR, CRITICAL}`인 엔트리를 `exc.fingerprint`(없으면 `{logger}:{msg[0:80]}`)로 그룹핑한다.
3. 각 그룹에 대해 GitHub 이슈 검색:
   - `label:source:watcher label:env:staging in:title "<fingerprint>" state:open`
   - **존재 O**: 코멘트로 추가 (발생 횟수, 최초/최종 타임스탬프, 샘플 3건)
   - **존재 X**: 새 이슈 생성, 라벨 `needs-triage`, `env:staging`, `source:watcher`, `type:bug`
4. 감시 결과를 stdout에 요약 리포트.

### 7.3 이슈 템플릿

```markdown
# [staging-watch] <exception.type>: <요약 메시지>

<!-- fingerprint: ConnectionError@ante.broker.kis.stream:handle_reconnect -->

## 요약
- 최초 발생: 2026-04-17T20:15:32Z
- 최근 발생: 2026-04-17T23:02:11Z
- 발생 횟수: 42 (6h 윈도우)
- 환경: staging

## 스택 트레이스 (샘플)
```
<최근 엔트리 traceback>
```

## 컨텍스트 필드 (다양성 있는 경우 최대 3건)
- account_id=paper01, order_id=ord-123
- account_id=paper01, order_id=ord-148
...

## 관련 스펙
- 추정: docs/specs/broker-adapter/...

## 처리 방법
`needs-triage` 라벨을 제거하면 autopilot 대상이 됩니다.
```

### 7.4 자동 처리 게이트

- 감시 에이전트는 **`needs-triage` 라벨을 반드시 붙인다**.
- [.agent/commands/autopilot.md](../../.agent/commands/autopilot.md) 및 `implement-issue`는 이슈 선별 시 `-label:needs-triage` 필터를 적용한다 (관련 커맨드 보강 필요 — §11 참조).
- 사용자/오케스트레이터가 판단 후 `needs-triage`를 제거하면 autopilot이 처리한다.

### 7.5 스케줄

macOS `launchd` plist를 `deploy/staging/com.ante.staging-watcher.plist`로 제공:

```xml
<key>StartCalendarInterval</key>
<array>
  <dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>0</integer></dict>
  <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
  <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
  <dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
</array>
```

하루 4회(6시간 간격). 실행 명령은 `cd <repo> && claude -p "/staging-watch"`.

### 7.6 관찰 범위

감시 에이전트는 **오직 JSONL 로그만 읽는다**. Docker 컨테이너에 접근하거나 DB를 직접 쿼리하지 않는다. 관심사 분리를 유지하여 에이전트 권한을 최소화한다.

## 8. 네트워크 노출

- 기본: 맥미니의 LAN(또는 Tailscale 네트워크) 내에서만 접근 가능하다.
- 포트: 3982 (Production과 동일하나 물리적으로 다른 호스트).
- 공인 인터넷 노출은 범위 밖이다.

## 9. Telegram 정책

사용자 요구사항(실시간 알림 불필요)에 따라 **스테이징은 Telegram을 발송하지 않는다**. `secrets.env`에서 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`를 공란으로 두고, [docs/specs/notification/notification.md](../../specs/notification/notification.md)가 정의하는 "토큰 없으면 알림 비활성화" 동작에 의존한다 (구현 확인 필요 — §11).

필요가 생기면 별도 반복에서 전용 봇/채널을 추가할 수 있다.

## 10. 스펙 보강 항목

본 설계 확정 시 다음 스펙 문서에 반영이 필요하다.

| 스펙 | 보강 내용 |
|---|---|
| [docs/specs/logging/](../../specs/logging/) | 신설 분할 스펙. 로그 3종 관계, JSONL 스키마, fingerprint 규칙, 핸들러·회전 정책, 컨텍스트 필드 주입 패턴, 구현 위치를 주제별 문서로 관리한다. 본 문서 §6은 이 스펙의 요약 인용. |
| [docs/specs/config/03-design-decisions.md](../../specs/config/03-design-decisions.md) | `ANTE_ENV`, `ANTE_LOG_JSONL` 환경변수 정의 추가 |
| [docs/runbooks/](../../runbooks/) | `07-staging-operations.md` 신설 (배포·관찰·리셋 절차) |
| [docs/decisions/](../../decisions/) | D-015 "스테이징은 맥미니 상시 구동·수동 배포" 등록 |
| [.gitignore](../../../.gitignore) | `logs/` 추가 (JSONL 파일이 리포 루트에 생성됨) |

### 10.1 로그 스펙 위치 (확정)

독립 모듈 스펙 `docs/specs/logging/`로 관리한다. 근거: 로깅은 이벤트 로그·감사 로그와 나란히 서는 독립 인프라이며, 향후 Watcher 계약·로그 인입 API 등으로 확장 여지가 크다. 분할 형식은 [docs/specs/account/](../../specs/account/)의 다중 파일 패턴을 따른다 (`README.md` 인덱스 + `<module>.md` 호환 문서 + `0N-<topic>.md` 주제별 문서).

## 11. 오픈 이슈 (1차 구현 시 확인)

- [ ] autopilot/implement-issue가 `-label:needs-triage` 필터를 지원하는지 확인. 미지원 시 커맨드 md 보강.
- [ ] Notification 모듈이 `TELEGRAM_BOT_TOKEN` 공란 시 silent 동작을 실제로 지원하는지 확인. 미지원 시 가드 추가.
- [ ] macOS `launchd`에서 `claude` CLI 호출 시 PATH/인증 전달 방식 검증 (기존 shell 세션 환경과 차이 확인 필요).
- [ ] GitHub 이슈 검색 API의 타이틀 내 fingerprint 매칭 정확도 확인. 불충분 시 이슈 body HTML 코멘트 마커(`<!-- fingerprint: ... -->`) 스캔으로 폴백.

## 12. 구현 순서 제안

상세 구현 계획은 본 문서 승인 후 `writing-plans` 스킬로 별도 작성한다. 대략의 마일스톤:

1. **JSONL 로거 기반 구축** — `JsonFormatter`, `_init_core` 통합, `ANTE_LOG_JSONL` 게이트, 단위 테스트
2. **`docker-compose.staging.yml` + config 템플릿** — 볼륨, 환경변수, 이미지 참조
3. **맥미니 부트스트랩 절차** — config 배치, 이미지 pull, up, 초기 Account 등록 (KIS_PAPER01)
4. **`.agent/commands/staging-watch.md`** — 감시 에이전트 커맨드
5. **`launchd` plist** — 스케줄 등록
6. **스펙 보강** — §10 항목 반영

---

## 리뷰 체크포인트

이 문서가 확정되면 다음 단계로:
1. `writing-plans` 스킬로 구현 계획 작성
2. 계획 승인 후 실제 구현

리뷰 시 특히 확인 부탁드리는 지점:
- **§6.1**: JSONL 전역 도입 + `ANTE_LOG_JSONL` 게이트 전략이 맞는지
- **§7.5**: 6시간 주기(하루 4회)가 적절한지 — 더 자주/드물게가 나은지
- **§9**: Telegram 완전 생략이 맞는지
- **§11**: 오픈 이슈 중 사전에 결정할 사항이 있는지
