# Config 모듈 세부 설계 - 미결 사항

> 인덱스: [README.md](README.md) | 호환 문서: [config.md](config.md)

# 미결 사항

- [ ] 알림 무음 시간대(quiet_hours) 설정 연결 ([#532](https://github.com/joshua-jingu-lee/ante/issues/532)) — `NotificationService`에 `quiet_start`/`quiet_end` 파라미터가 구현되어 있으나, `notification.quiet_hours` 동적 설정 키를 실제로 읽어서 `main.py` 초기화 시 주입하는 경로가 없음. 초기화 시 주입 + `ConfigChangedEvent` 구독으로 런타임 반영 필요
