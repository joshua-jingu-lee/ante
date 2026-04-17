# Bot 모듈 세부 설계 - CLI 사용법

> 인덱스: [README.md](README.md) | 호환 문서: [bot.md](bot.md)

# CLI 사용법

```bash
# 봇 생성 — --account로 소속 계좌 지정 (active 계좌가 하나뿐이면 생략 가능)
ante bot create --strategy momentum_breakout_v1.0.0 --account domestic --interval 60
ante bot create --strategy agent_relay_v1.0.0 --account us-stock
# → bot_id: bot_002, signal_key: sk_a1b2c3d4 (외부 시그널 수신 가능)

# 봇 시작
ante bot start bot_001

# 봇 목록 조회
ante bot list
ante bot list --account domestic         # 계좌별 필터
ante bot list --format json

# 봇 상태 조회
ante bot status bot_001

# 봇 중지
ante bot stop bot_001

# 봇 삭제
ante bot remove bot_001

# 시그널 키 관리
ante bot signal-key bot_002              # 키 조회
ante bot signal-key bot_002 --rotate     # 키 재발급

# 외부 시그널 채널 연결 (양방향 JSON Lines 파이프)
ante signal connect --key sk_a1b2c3d4
```

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
