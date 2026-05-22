# Getting Started

Ante를 설치하고 첫 거래를 시작하기까지의 과정을 안내합니다.

> [!WARNING]
> Ante는 현재 베타 단계입니다. API와 설정 형식이 변경될 수 있습니다.

---

## 요구 사항

- Python 3.13 (3.13.x)
- Python 3.13 free-threaded 빌드 및 JIT는 공식 지원 범위 밖
- Linux 또는 macOS (Windows는 WSL2 사용)

저장소 루트의 `.python-version`이 `3.13`을 가리키므로 pyenv/asdf/uv 같은 버전 매니저가 자동으로 같은 인터프리터를 선택합니다. venv는 Python 3.13으로 직접 만듭니다:

```bash
python3.13 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

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

설치 후 `ante init`을 실행하면 **비대화형**으로 파일 골격과 master 계정을 한 번에 생성합니다.
프롬프트 입력 없이, 플래그로 필요한 값을 지정합니다. AI 에이전트가 동일 커맨드를 호출할 수 있도록 설계되었습니다.

```bash
ante init
# 또는 master 정체성을 지정
ante init --member-id owner --name "홈트레이더"
```

### 플래그

| 플래그 | 기본값 | 설명 |
|--------|--------|------|
| `--member-id` | `owner` | master 멤버 ID |
| `--name` | `Owner` | master 표시 이름 |
| `--dir` | `~/.config/ante/` | 설정 디렉토리 경로 |

### 생성되는 것

`ante init` 한 번으로 다음 **6가지 산출물**이 생성됩니다.

- **파일 3개**: `~/.config/ante/system.toml`, `~/.config/ante/secrets.env` (권한 0600), `~/.config/ante/db/ante.db`
- **DB 레코드 2개**: master 계정 1개, default 테스트 계좌(`broker_type="test"`) 1개
- **민감값 3개(1회만 표시)**: 자동 생성된 패스워드, master 토큰(`ante_hk_*`), Recovery Key(`ANTE-RK-*`)

테스트 계좌만으로 시스템 전체를 가상으로 체험할 수 있습니다. 실거래는 아래 "선택 설정"에서 별도로 추가합니다.

### 완료 화면

```
── 완료 ────────────────────────────────────────
  설정 디렉토리: ~/.config/ante/
  Member ID   : owner
  이모지      : 🦊
  테스트 계좌 : test (TEST)

  패스워드     : gX7mKq2nPvR8sT4uWxYzA3bF
  토큰         : ante_hk_8k2m9p4q...
  Recovery Key : ANTE-RK-7F3X-9K2M-P4QW-8J5N-R6TV-2Y1H

  위 3개 값은 이 화면에만 표시됩니다. 안전한 곳에 보관하세요.

  셸에 토큰 등록:
   export ANTE_MEMBER_TOKEN=ante_hk_8k2m9p4q...

  이제 시스템을 시작할 수 있습니다:
   ante system start
```

**패스워드 / 토큰 / Recovery Key** 3개는 DB에 해시로만 저장되며 **1회만** 화면에 표시됩니다. 반드시 안전한 곳에 복사해 두세요.

- **토큰**은 이후 모든 CLI 명령에 필요합니다.
- **패스워드**는 human 인증 복구 명령에 사용됩니다.
- **Recovery Key**는 패스워드 분실 시 유일한 복구 수단입니다.

### 재실행 (멱등성)

`ante init`은 **위 3개 파일이 모두 존재하면** 실행을 거부합니다:

```
Error: init이 이미 완료된 상태입니다: /Users/foo/.config/ante/
  재설치를 원하면 디렉토리를 삭제한 뒤 다시 실행하세요.
```

모두 밀고 다시 시작하려면 설정 디렉토리를 삭제한 뒤 재실행합니다:

```bash
rm -rf ~/.config/ante/
ante init
```

> `ante init`은 `--force` 같은 재초기화 플래그를 제공하지 않습니다. 실수로 master 계정과 DB가 덮어써지는 것을 막기 위한 의도적인 제약입니다.

### JSON 출력 (AI 에이전트용)

스크립트/에이전트가 호출할 때는 JSON 포맷으로 값을 바로 파싱할 수 있습니다.

```bash
ante --format json init --member-id operator --name "Operator"
```

출력 JSON에는 `member_id`, `role`, `emoji`, `token`, `recovery_key`, `password`, `config_dir`, `test_account` 필드가 포함됩니다.

---

## 🧩 선택 설정 (필요 시)

`ante init`은 파일 골격 + master + 테스트 계좌 딱 여기까지만 만듭니다.
아래 기능은 **별도 명령**으로 추가합니다. 한 번에 다 하지 않아도, 필요한 시점에 하나씩 추가할 수 있습니다.

### 실거래 증권사 계좌 (KIS) 추가

`ante account create`는 비대화형 cold-path 명령입니다. 브로커 종류·계좌 ID·거래 모드(`virtual`/`live`)는 옵션으로 지정하고, 인증정보(`app_key`, `app_secret` 등)는 환경변수(권장) 또는 파일 채널로만 전달합니다. KIS의 `is_paper`(모의투자 여부)는 `--broker-config` free-form 채널로 넘깁니다.

```bash
export ANTE_KIS_APP_KEY="..."        # 사전 등록
export ANTE_KIS_APP_SECRET="..."
export ANTE_KIS_ACCOUNT_NO="..."     # 8자리 계좌번호 + 2자리 상품코드

ante account create \
  --broker-type kis-domestic \
  --account-id domestic \
  --name "국내주식" \
  --trading-mode virtual \
  --credential-env app_key=ANTE_KIS_APP_KEY \
  --credential-env app_secret=ANTE_KIS_APP_SECRET \
  --credential-env account_no=ANTE_KIS_ACCOUNT_NO \
  --broker-config is_paper=true
```

`kis-domestic` preset은 `app_key`, `app_secret`, `account_no` 세 키를 모두 필수로 요구합니다. 하나라도 누락되면 `ACCOUNT_MISSING_REQUIRED_CREDENTIAL` 에러로 실패합니다.

인증정보는 이후 `ante account set-credentials <ACCOUNT_ID>`로 동일한 `--credential-env` / `--credential-file` 채널을 통해 갱신할 수 있습니다. 도메인 specialize 옵션(`--app-key-env` 등)은 제공되지 않으며, generic credential 계약만 사용합니다.

**TradingMode**(Ante 시스템 레벨의 거래 모드)와 **is_paper**(KIS API 레벨의 모의투자 여부) 조합:

| 브로커 | TradingMode | is_paper | 동작 | 용도 |
|--------|-------------|----------|------|------|
| `test` | `VIRTUAL` | — | Ante 내부 시뮬레이션 | 시스템 체험 |
| `kis-domestic` | `VIRTUAL` | — | Ante 내부 시뮬레이션 (KIS 시세만) | 연동 확인 |
| `kis-domestic` | `LIVE` | `true` | KIS 모의투자 서버 | 실전 전 검증 |
| `kis-domestic` | `LIVE` | `false` | KIS 실전투자 서버 | **실제 매매** |

> [!WARNING]
> `LIVE` + `is_paper=false` 조합은 실제 자금으로 매매됩니다. 충분한 테스트 후 사용하세요.

### 텔레그램 알림

`~/.config/ante/secrets.env`를 직접 편집합니다:

```bash
# ~/.config/ante/secrets.env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=987654321
```

- **BOT_TOKEN**: [BotFather](https://core.telegram.org/bots/tutorial)에서 봇 생성 시 발급받은 토큰
- **CHAT_ID**: 알림을 받을 채팅방 ID (개인 DM 또는 그룹)

> Docker 환경에서는 `secrets.env` 대신 셸 환경변수로 전달할 수도 있습니다. 양쪽에 같은 키가 있으면 환경변수가 우선합니다.

### DataFeed API 키 (백테스팅 데이터 수집)

백테스팅용 KRX 시세·재무 데이터를 자동 수집하려면 `data.go.kr`과 `DART`의 Open API 키가 필요합니다.

```bash
ante feed config set ANTE_DATAGOKR_API_KEY your_key_here
ante feed config set ANTE_DART_API_KEY your_key_here
```

수집 스케줄·시간대 가드·수집 범위 등 상세 설정은 `~/.config/ante/data/.feed/config.toml`에서 변경합니다. (해당 파일 편집은 CLI 지원 예정.)

**수집 스케줄:**

```toml
[schedule]
daily_at = "16:00"              # 매일 자동 수집 시각 (KST, 장 종료 후)
backfill_at = "01:00"           # 과거 데이터 백필 시각 (KST, 새벽)
backfill_since = "2015-01-01"   # 백필 시작일
                                # KRX 전 종목 일봉 기준 약 10MB/년 (Parquet+Snappy)
                                # 재무 데이터 포함 시 약 40~50MB/년
```

**시간대 가드** (기본: 장 시간 09:00~15:30 동안 수집 일시 정지):

```toml
[guard]
blocked_days = []
blocked_hours = ["09:00-15:30"]
pause_during_trading = true
```

**수집 범위** (기본: KRX 전 종목):

```toml
[ohlcv.krx]
timeframes = ["1d"]
symbols = "all"                 # 또는 ["005930", "000660"]

[fundamental.krx]
symbols = "all"
```

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

- 🤖 [에이전트 등록 및 활용](agent.md) — AI 에이전트 등록, scope 설정, 토큰 관리
- 🔐 [보안 주의사항](security.md) — 네트워크 보안, 에이전트 신뢰 모델, 민감 정보 관리
- 📖 [CLI Reference](cli.md) — 사용 가능한 모든 명령어 확인
- 📈 [Strategy Guide](strategy.md) — 나만의 투자 전략 작성하기
