# Account 모듈 세부 설계 - Scope Out (1.0에서 제외)

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# Scope Out (1.0에서 제외)

- **KISOverseasAdapter 구현 및 "us-stock" Account**: 1.1 범위. 프리셋 `kis-overseas`는 정의만 해두고, 실제 어댑터 구현 및 US 데이터 파이프라인은 1.1에서 지원.
- **계좌 간 자금 이체**: 원화→달러 환전 등은 증권사 앱에서 수행. Ante는 sync로 반영만.
- **계좌별 알림 채널 분리**: 1.0에서는 모든 알림이 동일 텔레그램 채널로 발송.
- **계좌 간 합산 리스크 룰**: 전 계좌 합산 MDD 등 cross-account 안전장치. 필요 시 시스템 레벨 룰로 추가.
- **결제일(settlement_days) 추적**: 브로커 API가 매수가능금액을 결제일 반영하여 제공. 필요 시 추후 추가.
