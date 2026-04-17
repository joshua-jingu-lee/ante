# 에이전트 등록 및 활용

Ante에서 **에이전트(Agent)** 는 사용자를 대신해 시장을 조사하고, 투자 전략을 만들고, 매매를 모니터링하는 AI 직원입니다.
사용자가 직접 사용하는 master 계정(`ante_hk_` 토큰)과 달리, 에이전트에게는 전용 계정(`ante_ak_` 토큰)을 발급하여 **필요한 권한만** 부여합니다.

| 구분 | Master (사용자) | Agent (AI) |
|------|----------------|------------|
| 토큰 접두어 | `ante_hk_` | `ante_ak_` |
| 권한 | 모든 작업 가능 | 등록 시 부여한 scope만 사용 |
| 용도 | 시스템 관리, 최종 결정 | 전략 개발, 데이터 분석, 모니터링 등 |

에이전트를 별도 계정으로 분리하면 다음과 같은 이점이 있습니다:

- **최소 권한** — 전략 리서치 에이전트가 시스템 설정을 변경하는 등의 사고를 방지합니다.
- **독립 관리** — 에이전트별로 토큰을 재발급하거나 정지할 수 있어, 문제가 생긴 에이전트만 즉시 차단할 수 있습니다.
- **활동 추적** — 감사 로그에 어떤 에이전트가 어떤 작업을 수행했는지 기록됩니다.

## 에이전트 등록

시스템을 시작한 뒤, 에이전트 계정을 등록합니다.

```bash
ante member register \
  --id strategy-dev-01 \
  --type agent \
  --name "전략 리서치 1호" \
  --scopes "strategy:write,data:read,backtest:run,report:write"
```

등록이 완료되면 `ante_ak_` 접두어의 토큰이 발급됩니다. 이 토큰은 **1회만 표시**되므로 즉시 저장하세요.

```
✅ 멤버 등록 완료
  Member ID: strategy-dev-01
  토큰: ante_ak_8k2m9p4q...
  이 토큰은 다시 표시되지 않습니다.
```

에이전트는 이 토큰을 환경변수나 API Bearer 헤더로 사용하여 Ante에 접근합니다.

```bash
# AI 에이전트 환경에 토큰 설정
export ANTE_MEMBER_TOKEN=ante_ak_8k2m9p4q...
```

## 활용 예시

역할에 따라 scope를 다르게 부여하여, 목적에 맞는 여러 에이전트를 운용할 수 있습니다.

**전략 리서치 에이전트** — 시장 데이터를 분석하고 전략을 개발·백테스트합니다.

```bash
ante member register \
  --id researcher-01 --type agent --name "리서처 1호" \
  --scopes "strategy:read,strategy:write,data:read,backtest:run,report:write"
```

**모니터링 에이전트** — 봇 상태와 거래 내역을 감시하고, 이상 징후를 보고합니다.

```bash
ante member register \
  --id monitor-01 --type agent --name "모니터 1호" \
  --scopes "bot:read,trade:read,treasury:read,system:read,audit:read"
```

**운영 에이전트** — 봇 생성·관리와 결재 처리 등 운영 업무를 수행합니다.

```bash
ante member register \
  --id ops-01 --type agent --name "운영 1호" \
  --scopes "bot:read,bot:admin,approval:read,approval:write,config:read"
```

## Scope 전체 목록

Scope는 `도메인:권한` 형식입니다. 에이전트 등록 시 필요한 scope만 쉼표로 구분하여 부여합니다.

| 도메인 | read | write | admin | run |
|--------|------|-------|-------|-----|
| `strategy` | 전략 조회 | 전략 등록·검증 | | |
| `data` | 데이터·종목 조회 | 데이터 주입, 종목 동기화 | | |
| `report` | 리포트 조회 | 리포트 제출 | | |
| `config` | 설정 조회 | 설정 변경 | | |
| `approval` | 결재 조회 | 결재 요청·의견·철회 | 결재 승인·거부 | |
| `bot` | 봇 상태 조회 | | 봇 생성·삭제, 시그널키 발급 | |
| `trade` | 거래 내역 조회 | | | |
| `treasury` | 자금 현황 조회 | | 예산 설정·자금 투입 | |
| `member` | 멤버 목록·상세 조회 | | 멤버 등록·정지·폐기·토큰 관리 | |
| `system` | 시스템 상태 조회 | | 시스템 상태 변경 | |
| `rule` | 룰 조회 | | 룰 활성화·비활성화 | |
| `broker` | 브로커 상태·잔고·대사 조회 | | | |
| `audit` | 감사 로그 조회 | | | |
| `notification` | 알림 이력 조회 | | | |
| `backtest` | | | | 백테스트 실행 |

> Master 계정(human)은 scope 제한 없이 모든 작업을 수행할 수 있습니다. Scope는 에이전트 권한 제어 전용입니다.

## 토큰 관리

| 상황 | 명령어 |
|------|--------|
| 토큰 재발급 (기존 즉시 무효화) | `ante member rotate-token <MEMBER_ID>` |
| 에이전트 일시 정지 | `ante member suspend <MEMBER_ID>` |
| 에이전트 재활성화 | `ante member reactivate <MEMBER_ID>` |
| 에이전트 영구 폐기 | `ante member revoke <MEMBER_ID>` |

토큰은 기본 90일 후 만료됩니다. 만료 7일 전부터 경고가 표시되며, `rotate-token`으로 재발급할 수 있습니다.
