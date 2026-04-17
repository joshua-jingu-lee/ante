# Bot 모듈 세부 설계 - 알림 이벤트 정의 (Notification Events)

> 인덱스: [README.md](README.md) | 호환 문서: [bot.md](bot.md)

# 알림 이벤트 정의 (Notification Events)

Bot 모듈이 발행하는 `NotificationEvent` 목록. `bot/manager.py`에서 직접 발행한다 (category: `"bot"`).

### 봇 시작

**트리거**: 봇 정상 가동 완료 시
**데이터 수집**: bot_id, 전략명, 전략 버전

```
ℹ️ 봇 시작
봇 bot-001이 가동되었습니다.
전략: momentum_breakout v1.0.0
```

### 봇 중지

**트리거**: 봇 정상 중지 시 (수동 또는 시스템 종료)
**데이터 수집**: bot_id

```
ℹ️ 봇 중지
봇 bot-001이 중지되었습니다.
```

### 봇 에러

**트리거**: 봇 실행 중 예외 발생 시
**데이터 수집**: bot_id, 에러 메시지

```
❌ 봇 bot-001에서 에러가 발생
Connection timeout after 30s
봇은 자동 재시작을 시도합니다.
```

### 재시작 한도 소진

**트리거**: 자동 재시작 최대 횟수 도달 시
**데이터 수집**: bot_id, 재시작 시도 횟수, 마지막 에러 메시지

```
❌ 봇 bot-001이 3회 재시작에 모두 실패했습니다
마지막 에러: Broker API 연결 실패
봇이 중지 상태입니다. 원인 확인 후 수동 재시작하세요.
```
