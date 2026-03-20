# Getting Started

Ante를 설치하고 첫 거래를 시작하기까지의 과정을 안내합니다.

## 요구 사항

- Python 3.11 이상
- (선택) Docker

## 사전 준비

Ante를 설치하기 전에 아래 계정과 API 키를 준비하면 초기 설정을 한 번에 마칠 수 있습니다.
필수 항목만 갖추면 시작할 수 있고, 선택 항목은 나중에 설정해도 됩니다.

### 한국투자증권 계좌 및 Open API 키 (필수)

Ante는 한국투자증권(KIS) Open API를 통해 실제 매매를 수행합니다. 계좌와 API 키가 있어야 실투자가 가능합니다.

- 한국투자증권 계좌 개설
- [KIS Developers](https://apiportal.koreainvestment.com/intro)에서 APP KEY / APP SECRET 발급

> 건너뛰면 Test 증권사로 설정되어 실제 매매 없이 시스템을 체험할 수 있습니다.

### 텔레그램 봇 (선택)

거래 체결, 손절 알림, 시스템 경고 등을 텔레그램으로 실시간 수신할 수 있습니다.

- [BotFather](https://core.telegram.org/bots/tutorial)로 봇 생성 후 Bot Token 확보
- 알림을 받을 채팅방의 Chat ID 확인

### 공공데이터포털 API 키 (선택)

KRX 시세·거래량 등 백테스팅용 과거 데이터를 자동 수집하는 데 사용합니다.

- [공공데이터포털](https://www.data.go.kr/)에서 회원가입 후 Open API 인증키 발급

### DART Open API 키 (선택)

재무제표, 공시 정보 등 기업 펀더멘털 데이터를 수집하는 데 사용합니다.

- [OPEN DART](https://opendart.fss.or.kr/)에서 회원가입 후 인증키 발급

## 설치

### pip

```bash
pip install ante
```

### Docker

```bash
docker pull ghcr.io/joshua-jingu-lee/ante:latest
```

## 초기 설정

설치 후 `ante init`을 실행하면 대화형으로 초기 설정을 진행합니다.

```bash
ante init
```

### 1단계: Master 계정

시스템 관리자 계정을 생성합니다. Member ID, 이름, 패스워드를 입력합니다.

```
── 1. Master 계정 ──────────────────────────────
Member ID: owner
이름: 홈트레이더
패스워드: ••••••••
패스워드 확인: ••••••••
```

### 2단계: 계좌 등록

실제 거래에 사용할 증권사 계좌를 등록합니다. 건너뛰면 테스트 계좌가 자동으로 생성되며, 실제 매매 없이 시스템을 체험할 수 있습니다.

나중에 `ante account create` 명령어로 계좌를 추가할 수 있습니다.

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

각 계좌에는 **거래 모드(TradingMode)** 가 설정됩니다:

| 모드 | 설명 |
|------|------|
| `VIRTUAL` | 가상거래 — 실제 주문이 나가지 않으며, 시스템 내부에서 체결을 시뮬레이션합니다. |
| `LIVE` | 실제거래 — 증권사 API를 통해 실제 주문이 발생합니다. |

등록 후에는 `ante account list`로 계좌 목록을 확인할 수 있습니다.

### 3단계: 텔레그램 알림 (선택)

거래 알림, 시스템 경고 등을 텔레그램으로 받을 수 있습니다.
건너뛰어도 시스템 운영에 지장은 없습니다.

나중에 `~/.config/ante/secrets.env`에서 설정할 수 있습니다.

### 4단계: 데이터 수집 API (선택)

설정하면 백테스팅용 KRX 시세·재무 데이터를 자동 수집할 수 있습니다.
data.go.kr과 DART의 Open API Key가 필요합니다.
건너뛰어도 시스템 운영에 지장은 없습니다.

나중에 `ante feed config set` 명령어로 설정할 수 있습니다.

```bash
# 나중에 설정하는 경우
ante feed config set ANTE_DATAGOKR_API_KEY your_key_here
ante feed config set ANTE_DART_API_KEY your_key_here
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

## 시스템 시작

```bash
ante system start
```

시스템이 시작되면 AI 에이전트를 등록하여 전략 개발, 모니터링 등의 업무를 맡길 수 있습니다.

## 다음 단계

- [대시보드 사용하기](dashboard.md) — 웹 대시보드 접속, 주요 메뉴 안내
- [에이전트 등록 및 활용](agent.md) — AI 에이전트 등록, scope 설정, 토큰 관리
- [보안 주의사항](security.md) — 네트워크 보안, 에이전트 신뢰 모델, 민감 정보 관리
- [CLI Reference](cli.md) — 사용 가능한 모든 명령어 확인
- [Strategy Guide](strategy.md) — 나만의 투자 전략 작성하기
