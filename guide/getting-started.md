# Getting Started

Ante를 설치하고 첫 거래를 시작하기까지의 과정을 안내합니다.

> [!WARNING]
> Ante는 현재 베타 단계입니다. API와 설정 형식이 변경될 수 있습니다.

---

## 요구 사항

- Python 3.11 이상
- Linux 또는 macOS (Windows는 WSL2 사용)

---

## 📋 사전 준비

Ante를 설치하기 전에 아래 항목을 준비하면 초기 설정을 한 번에 마칠 수 있습니다.
필수 항목만 갖추면 바로 시작할 수 있고, 선택 항목은 나중에 설정해도 됩니다.

### 한국투자증권 계좌 및 Open API 키 (필수)

Ante는 한국투자증권(KIS) Open API를 통해 실제 매매를 수행합니다.

> 현재 KRX(국내주식)만 지원합니다. 해외주식 지원은 향후 계획에 포함되어 있습니다.

- 한국투자증권 계좌 개설
- [KIS Developers](https://apiportal.koreainvestment.com/intro)에서 APP KEY / APP SECRET 발급

> 건너뛰면 Test 증권사로 설정되어 실제 매매 없이 시스템을 체험할 수 있습니다.

### 텔레그램 봇 (선택)

거래 체결, 손절 알림, 시스템 경고 등을 실시간으로 수신할 수 있습니다.

- [BotFather](https://core.telegram.org/bots/tutorial)로 봇 생성 후 Bot Token 확보
- 알림을 받을 채팅방의 Chat ID 확인

### 공공데이터포털 API 키 (선택)

백테스팅용 KRX 시세·거래량 과거 데이터를 자동 수집하는 데 사용합니다.

- [공공데이터포털](https://www.data.go.kr/)에서 회원가입 후 Open API 인증키 발급

### DART Open API 키 (선택)

재무제표, 공시 정보 등 기업 펀더멘털 데이터를 수집하는 데 사용합니다.

- [OPEN DART](https://opendart.fss.or.kr/)에서 회원가입 후 인증키 발급

---

## 📦 설치

```bash
pip install ante
```

---

## ⚙️ 초기 설정

설치 후 `ante init`을 실행하면 대화형으로 초기 설정을 진행합니다.

```bash
ante init
```

### 1단계: Master 계정

시스템 관리자 계정을 생성합니다.

```
── 1. Master 계정 ──────────────────────────────
Member ID: owner
이름: 홈트레이더
패스워드: ••••••••
패스워드 확인: ••••••••
```

### 2단계: 계좌 등록

실제 거래에 사용할 증권사 계좌를 등록합니다.
건너뛰면 테스트 계좌가 자동 생성되며, 실제 매매 없이 시스템을 체험할 수 있습니다.

```
── [2/4] 계좌 설정 ─────────────────────────────
  등록하지 않으면 테스트 계좌가 자동으로 생성됩니다.
  나중에 `ante account create` 명령어로도 추가할 수 있습니다.
실제 거래 계좌를 등록하시겠습니까? [y/N]: y

  브로커를 선택하세요:
    1) kis-domestic (KRX / KRW)
  선택 [1]: 1
  계좌 ID [domestic]: domestic
  이름 [국내 주식]: 국내 주식
  app_key: PSxxxxxxxxxxx
  app_secret: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  account_no: 50123456-01
  -> 계좌 "domestic" 등록 예정 (KRX / KRW / kis-domestic)
```

각 계좌에는 **거래 모드(TradingMode)** 와 **모의투자 여부(is_paper)** 가 설정됩니다:

**TradingMode** — Ante 시스템 레벨의 거래 모드입니다:

| 모드 | 설명 |
|------|------|
| `VIRTUAL` | 가상거래 — 실제 주문이 나가지 않으며, 시스템 내부에서 체결을 시뮬레이션합니다. |
| `LIVE` | 실제거래 — 증권사 API를 통해 실제 주문이 발생합니다. |

**is_paper** — KIS 증권사 API 레벨의 모의투자 모드입니다:

| 값 | 설명 |
|----|------|
| `true` | KIS 모의투자 서버에 접속합니다. 실제 체결은 발생하지 않지만 증권사 API를 통해 주문이 처리됩니다. |
| `false` | KIS 실전투자 서버에 접속합니다. 실제 자금으로 매매가 이루어집니다. |

> `is_paper`는 KIS 브로커(`kis-domestic`)에서만 사용되며, `broker_config`에 설정합니다.
> Test 브로커에서는 이 설정이 무시됩니다.

**가능한 조합:**

| 브로커 | TradingMode | is_paper | 동작 | 용도 |
|--------|-------------|----------|------|------|
| `test` | `VIRTUAL` | — | Ante 내부 시뮬레이션 (증권사 API 미사용) | 시스템 체험, 개발/테스트 |
| `kis-domestic` | `VIRTUAL` | — | Ante 내부 시뮬레이션 (KIS API로 시세만 조회) | KIS 계좌 연동 확인 |
| `kis-domestic` | `LIVE` | `true` | KIS 모의투자 서버로 주문 전송 | 실전 전 검증 (추천) |
| `kis-domestic` | `LIVE` | `false` | KIS 실전투자 서버로 주문 전송 | **실제 매매** |

> [!WARNING]
> `LIVE` + `is_paper=false` 조합은 실제 자금으로 매매가 이루어집니다. 충분한 테스트 후 사용하세요.

나중에 `ante account create` 명령어로 계좌를 추가할 수 있습니다.

### 3단계: 텔레그램 알림 (선택)

거래 알림, 시스템 경고 등을 텔레그램으로 받을 수 있습니다.
건너뛰어도 시스템 운영에 지장은 없습니다.

나중에 `~/.config/ante/secrets.env`에서 설정할 수 있습니다:

```bash
# ~/.config/ante/secrets.env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=987654321
```

- **BOT_TOKEN**: [BotFather](https://core.telegram.org/bots/tutorial)에서 봇 생성 시 발급받은 토큰
- **CHAT_ID**: 알림을 받을 채팅방 ID (개인 DM 또는 그룹)

> Docker 등에서 `secrets.env` 대신 셸 환경변수로 전달할 수도 있습니다. 양쪽에 같은 키가 있으면 환경변수가 우선합니다.

### 4단계: 데이터 수집 API (선택)

백테스팅용 KRX 시세·재무 데이터를 자동 수집할 수 있습니다.
data.go.kr과 DART의 Open API Key가 필요합니다.
건너뛰어도 시스템 운영에 지장은 없습니다.

```bash
# 나중에 설정하는 경우
ante feed config set ANTE_DATAGOKR_API_KEY your_key_here
ante feed config set ANTE_DART_API_KEY your_key_here
```

#### 데이터 수집 상세 설정

데이터 수집의 스케줄, 수집 범위, 시간대 가드 등은 `~/.config/ante/data/.feed/config.toml`에서 변경할 수 있습니다.

> 현재 이 설정은 CLI로 변경할 수 없으며, TOML 파일을 직접 편집해야 합니다.

**수집 스케줄:**

```toml
[schedule]
daily_at = "16:00"              # 매일 자동 수집 시각 (KST, 장 종료 후)
backfill_at = "01:00"           # 과거 데이터 백필 시각 (KST, 새벽)
backfill_since = "2015-01-01"   # 백필 시작일 (이 날짜부터 과거 데이터 수집)
                                # KRX 전 종목 일봉 기준 약 10MB/년 (Parquet+Snappy 압축)
                                # 재무 데이터 포함 시 약 40~50MB/년
                                # 2015년부터 수집 시 약 400~500MB
```

**시간대 가드:**

데이터 수집은 기본적으로 **장 시간(09:00~15:30) 동안 일시 정지**됩니다.

```toml
[guard]
blocked_days = []                # 수집 차단 요일 (예: ["sat", "sun"])
blocked_hours = ["09:00-15:30"]  # 수집 차단 시간대 (KST)
pause_during_trading = true      # true: blocked_hours 적용
```

**수집 범위:**

기본적으로 KRX 전 종목의 일봉과 재무 데이터를 수집합니다.
특정 종목만 수집하려면 `symbols`를 리스트로 변경합니다.

```toml
[ohlcv.krx]
timeframes = ["1d"]              # 수집할 타임프레임
symbols = "all"                  # 전 종목 수집 (또는 ["005930", "000660"])

[fundamental.krx]
symbols = "all"                  # 전 종목 재무 데이터 수집
```

### 설정 완료

초기 설정이 끝나면 토큰과 Recovery Key가 출력됩니다.

```
── 완료 ────────────────────────────────────────

초기 설정 완료
  설정 디렉토리: ~/.config/ante/
  Member ID   : owner
  이모지      : 🦊
  계좌        : domestic (kis-domestic)

  토큰: ante_hk_8k2m9p4q...

   셸 프로필에 추가하면 매번 입력하지 않아도 됩니다:
   echo 'export ANTE_MEMBER_TOKEN=ante_hk_8k2m9p4q...' >> ~/.zshrc

   Recovery Key: ANTE-RK-7F3X-9K2M-P4QW-8J5N-R6TV-2Y1H
   이 키는 다시 표시되지 않습니다. 안전한 곳에 보관하세요.
```

**토큰**은 이후 모든 CLI 명령에 필요합니다. 셸 프로필에 등록하면 편리합니다:

```bash
echo 'export ANTE_MEMBER_TOKEN=ante_hk_8k2m9p4q...' >> ~/.zshrc
source ~/.zshrc
```

**Recovery Key**는 패스워드 분실 시 유일한 복구 수단입니다. 안전한 곳에 보관하세요.

---

## 🚀 시스템 시작

```bash
ante system start
```

시스템이 시작되면 AI 에이전트를 등록하여 전략 개발, 모니터링 등의 업무를 맡길 수 있습니다.

---

## ⚠️ 주의

이 시스템은 실제 자금을 다룹니다.
충분한 테스트(백테스트 / 모의투자) 후 사용하세요.

---

## 다음 단계

- 👉 [대시보드 사용하기](dashboard.md) — 웹 대시보드 접속, 주요 메뉴 안내
- 🤖 [에이전트 등록 및 활용](agent.md) — AI 에이전트 등록, scope 설정, 토큰 관리
- 🔐 [보안 주의사항](security.md) — 네트워크 보안, 에이전트 신뢰 모델, 민감 정보 관리
- 📖 [CLI Reference](cli.md) — 사용 가능한 모든 명령어 확인
- 📈 [Strategy Guide](strategy.md) — 나만의 투자 전략 작성하기
