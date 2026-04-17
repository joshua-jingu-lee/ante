# Member 모듈 세부 설계 - 설계 결정

> 인덱스: [README.md](README.md) | 호환 문서: [member.md](member.md)

# 설계 결정

### Member 타입과 역할

| 타입 | 역할 | 설명 |
|------|------|------|
| `human` | `master` | 시스템 소유자 (대표). 최고 권한. 시스템에 1명만 존재 |
| `human` | `admin` | 관리자. 향후 파트너/운영자 추가 시 사용 (초기에는 미사용) |
| `agent` | `default` | AI 에이전트. 할당된 scope 내에서 활동 |

**불변식 (Invariant):**

1. `role="master"`는 `type="human"`인 멤버에게만 허용된다. 코드 레벨과 DB 레벨 이중 검증.
2. master는 시스템에 정확히 1명이다. 추가 생성·양도·삭제 불가.
3. master 역할로의 변경 API는 존재하지 않는다 (코드에 아예 없음).
4. `ante_hk_` 토큰은 `type="human"` 멤버에만 발급·매칭된다.
5. `ante_ak_` 토큰은 `type="agent"` 멤버에만 발급·매칭된다.

### 조직 (org)

멤버는 `org` 필드로 논리적 소속을 표현한다. 초기에는 단순 문자열로 관리하며, 별도 테이블은 두지 않는다.

```
org 예시:
├── default          → 기본 소속 (초기 멤버)
├── strategy-lab     → 전략 리서치 에이전트
├── risk             → 리스크 감시 에이전트
├── treasury         → 자금 관리 에이전트
└── operations       → 봇 운영 에이전트
```

향후 org별 권한 정책이 필요해지면 별도 `organizations` 테이블을 추가한다.

### 인증 체계

**타입별 인증 분리:**

human과 agent의 인증 경로를 물리적으로 분리하여, 한쪽의 인증 수단이 탈취되더라도 다른 쪽으로의 권한 상승을 차단한다.

```
접근 경로              인증 방식                   토큰 접두어
────────────────────────────────────────────────────────────
대시보드 (human)    → 패스워드 + 세션 쿠키          (세션 기반)
CLI (human)        → ANTE_MEMBER_TOKEN 환경변수    ante_hk_
CLI (agent)        → ANTE_MEMBER_TOKEN 환경변수    ante_ak_
Web API (agent)    → Authorization: Bearer 헤더    ante_ak_
```

**토큰 접두어에 의한 타입 강제:**

```python
def authenticate(token: str) -> Member:
    if token.startswith("ante_hk_"):
        member = lookup_by_token_hash(token)
        if member.type != "human":
            raise AuthError("human key로 agent 멤버 인증 불가")
    elif token.startswith("ante_ak_"):
        member = lookup_by_token_hash(token)
        if member.type != "agent":
            raise AuthError("agent key로 human 멤버 인증 불가")
    else:
        raise AuthError("유효하지 않은 토큰 형식")
    return member
```

agent가 서버 파일 시스템에 접근할 수 있더라도:
- DB에는 토큰 해시만 저장되므로 human 토큰 원문을 복원할 수 없다.
- 자신의 `ante_ak_` 토큰으로는 master 권한이 필요한 작업을 실행할 수 없다.

### 비밀번호 복구 — Recovery Key

human 멤버의 패스워드 분실 시 **외부 인프라(이메일, SMS) 없이** 자체 복구할 수 있는 메커니즘.

**생성 시점**: `ante member bootstrap` 실행 시 master 계정과 함께 1회 생성

```
$ ante member bootstrap --id owner --name "홈트레이더"
패스워드: ••••••••
패스워드 확인: ••••••••

✅ master 계정 생성 완료
  Member ID : owner
  이모지    : 🦊

🔑 토큰: ante_hk_8k2m9p4q...
   export ANTE_MEMBER_TOKEN=ante_hk_8k2m9p4q...

⚠️ Recovery Key: ANTE-RK-7F3X-9K2M-P4QW-8J5N-R6TV-2Y1H
   이 키는 패스워드 분실 시 유일한 복구 수단입니다.
   안전한 곳에 보관하세요. 이 키는 다시 표시되지 않습니다.
```

**설계:**

| 항목 | 설명 |
|------|------|
| 저장 | PBKDF2-SHA256 해시로 DB 저장. 원문은 시스템 내 어디에도 남기지 않음 |
| 용도 | `ante member reset-password --recovery-key ANTE-RK-...` |
| 재발급 | 현재 패스워드 입력 시에만 가능 (기존 키 폐기 + 신규 발급) |
| agent 방어 | 원문이 시스템에 없으므로 agent가 탈취 불가. `ante init`은 최초 1회만 실행 가능 |

**복구 흐름:**

```
1. 사용자가 서버 CLI에서 실행:
   $ ante member reset-password --recovery-key ANTE-RK-7F3X-...

2. 시스템이 recovery key 해시를 검증

3. 새 패스워드 입력 (대화형 프롬프트)

4. 패스워드 갱신 + 텔레그램 알림: "master 패스워드가 변경되었습니다"

5. 기존 모든 세션 무효화
```

**재발급 흐름:**

```
$ ante member regenerate-recovery-key
현재 패스워드: ********
⚠️  기존 복구 키가 폐기되었습니다.

새 복구 키:
  ANTE-RK-2M8P-Q5WN-K7JR-4F9X-L3HV-6Y0T

  안전한 곳에 보관하세요. 이 키는 다시 표시되지 않습니다.
```

### 권한 범위 (Scope)

agent 멤버에게는 토큰 발급 시 scope를 지정하여 접근 범위를 제한한다.
master(human)는 scope 제한 없이 모든 작업을 수행할 수 있다. scope는 오직 agent 멤버를 제한하기 위한 장치다.

**권한 수준 (3단계):**

| 수준 | 의미 | 예시 |
|------|------|------|
| `read` | 조회만 가능 | 목록 보기, 상세 보기, 상태 확인 |
| `write` | 데이터 생성/수정 | 전략 등록, 설정 변경, 결재 요청 |
| `admin` | 시스템 제어/위험 작업 | 봇 시그널키 발급, 룰 활성화/비활성화, 멤버 정지/폐기 |

**도메인별 scope 목록:**

| 도메인 | read | write | admin | run |
|--------|------|-------|-------|-----|
| `strategy` | 전략 조회 | 전략 등록/검증 | — | — |
| `data` | 데이터/종목 조회 | 데이터 주입, 종목 동기화 | — | — |
| `report` | 리포트 조회 | 리포트 제출 | — | — |
| `config` | 설정 조회 | 설정 변경 | — | — |
| `approval` | 결재 조회 | 결재 요청/의견 첨부/철회/재상신 | 결재 승인/거부 | — |
| `bot` | 봇 상태 조회 | — | 봇 생성/삭제, 시그널키 발급/갱신 | — |
| `trade` | 거래 내역 조회 | — | — | — |
| `treasury` | 자금 현황 조회 | — | 예산 설정/자금 투입 | — |
| `member` | 멤버 목록/상세 조회 | — | 멤버 등록/정지/폐기/토큰 관리 | — |
| `system` | 시스템 상태 조회 | — | 시스템 상태 변경 | — |
| `rule` | 룰 조회 | — | 룰 활성화/비활성화 | — |
| `broker` | 브로커 상태/잔고/대사 조회 | — | — | — |
| `audit` | 감사 로그 조회 | — | — | — |
| `notification` | 알림 이력 조회 | — | — | — |
| `backtest` | — | — | — | 백테스트 실행 |

> `signal` 도메인은 봇별 signal key(`sk_`) 인증으로 동작하며, member scope 체계 밖이다.

**scope 검증은 CLI 미들웨어에서 데코레이터로 수행:**

```python
@require_auth
@require_scope("strategy:write")
def strategy_submit(ctx, ...):
    ...
```

human 멤버는 `require_scope` 검증을 무조건 통과한다. agent 멤버만 등록된 scope 목록에 대해 검증된다.

**agent 등록 시 scope 조합 예시:**

```
# 전략 리서치 전용 agent — 전략 개발과 백테스트만 가능
scopes: strategy:read, strategy:write, data:read, backtest:run, report:write

# 모니터링 전용 agent — 모든 것을 볼 수 있지만 변경 불가
scopes: bot:read, trade:read, treasury:read, system:read, audit:read

# 운영 agent — 봇 관리와 결재까지 가능
scopes: bot:read, bot:admin, approval:read, approval:write, config:read
```

### 시스템 초기화 흐름

```
$ ante member bootstrap --id owner --name "홈트레이더"
  1. members 테이블 생성 (없으면)
  2. master 멤버 생성 (type=human, role=master, org=default)
  3. 패스워드 설정 (대화형 입력)
  4. Recovery Key 생성 + 화면 출력 (원문은 저장하지 않음)
  5. master 토큰(ante_hk_*) 발급 + 화면 출력
```

`bootstrap`은 최초 1회만 실행 가능하다. master가 이미 존재하면 거부한다.

### bootstrap 시 토큰 동시 발급

bootstrap 완료 시 master 토큰(`ante_hk_*`)을 함께 생성하여 출력한다.
이는 CLI 첫 사용 흐름에서 **순환 의존을 방지**하기 위한 설계다.

**배경**: `ante system start` 등 대부분의 명령은 `ANTE_MEMBER_TOKEN` 환경변수가 필요하다.
그러나 토큰을 발급받으려면 웹 대시보드 로그인이 필요하고, 웹 대시보드는 시스템 시작 이후에만 사용 가능하다.
bootstrap에서 토큰을 함께 발급하면 별도의 웹 로그인 없이 CLI만으로 전체 초기 설정을 완료할 수 있다.

**출력 예시**:

```
$ ante member bootstrap --id owner --name "홈트레이더"
패스워드: ••••••••
패스워드 확인: ••••••••

✅ master 계정 생성 완료
  Member ID : owner
  이모지    : 🦊

🔑 토큰: ante_hk_8k2m9p4q...
   이후 명령 실행 시 환경변수로 설정하세요:
   export ANTE_MEMBER_TOKEN=ante_hk_8k2m9p4q...

⚠️ Recovery Key: ANTE-RK-7F3X-9K2M-P4QW-8J5N-R6TV-2Y1H
   이 키는 패스워드 분실 시 유일한 복구 수단입니다.
   안전한 곳에 보관하세요. 이 키는 다시 표시되지 않습니다.
```

**보안 고려**:
- 토큰과 recovery key 모두 **1회만 표시**된다. 시스템 내에는 해시만 저장.
- 토큰 분실 시 `ante member rotate-token`으로 재발급 가능 (인증된 상태에서).
- 토큰 TTL은 기본 90일. 만료 시 웹 대시보드 로그인 또는 `rotate-token`으로 갱신.

### 이모지 시스템

각 멤버는 고유한 아바타 이모지를 가질 수 있다. 대시보드, CLI 출력 등에서 멤버를 시각적으로 빠르게 식별하는 용도로 사용한다.

**동물 이모지 풀 (ANIMAL_EMOJI_POOL):**

- 35종의 동물 이모지로 구성된 기본 풀을 제공한다.
- 멤버 등록 시 이모지를 지정하지 않으면 풀에서 미사용 이모지를 랜덤으로 자동 배정한다.
- 풀이 모두 소진된 경우 에러 없이 빈 문자열(`""`)로 설정한다.

**검증 규칙:**

- 단일 이모지(grapheme cluster)만 허용한다. 2개 이상의 이모지나 일반 텍스트는 거부한다.
- 멤버 간 이모지 중복은 불가하다. 단, 빈 문자열(`""`)은 중복을 허용한다.
- `update_emoji()` 메서드로 등록 이후에도 변경할 수 있다.
