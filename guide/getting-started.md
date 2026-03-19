# Getting Started

Ante를 설치하고 첫 거래를 시작하기까지의 과정을 안내합니다.

## 요구 사항

- Python 3.11 이상
- (선택) Docker

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

### 2단계: 증권사 연동 (KIS)

한국투자증권 Open API 연동 정보를 입력합니다.
건너뛰면 Test 증권사로 설정되며, 실제 매매 없이 시스템을 체험할 수 있습니다.

나중에 `~/.config/ante/secrets.env`에서 변경할 수 있습니다.

```
── 2. 증권사 연동 (KIS) ────────────────────────
KIS 연동 정보를 입력하시겠습니까? [y/N]: y
APP KEY: PSxxxxxxxxxxx
APP SECRET: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
계좌번호 (예: 50123456-01): 50123456-01
모의투자 여부 [y/N]: n
```

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
✅ 초기 설정 완료
  설정 디렉토리: ~/.config/ante/
  Member ID   : owner
  이모지      : 🦊
  브로커      : KIS (실투자)

🔑 토큰: ante_hk_8k2m9p4q...

⚠️ Recovery Key: ANTE-RK-7F3X-9K2M-P4QW-8J5N-R6TV-2Y1H
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

## 다음 단계

- [CLI Reference](cli.md) — 사용 가능한 모든 명령어 확인
- [Strategy Guide](strategy.md) — 나만의 투자 전략 작성하기
- [Security](security.md) — 보안 설정 및 주의사항
