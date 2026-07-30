# Broker Adapter 모듈 세부 설계 - CLI 인터페이스

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# CLI 인터페이스

CLI 명령 시그니처와 실행 분류의 SSOT는
[cli/03-commands.md](../cli/03-commands.md#ante-broker--증권사-연동)다. 이 문서는
Broker Adapter 관점의 런타임 경계만 설명한다.

증권사 live 상태를 읽는 CLI 명령은 서버가 시작 시 생성한 BrokerAdapter를 통해
실행하는 런타임 IPC 커맨드다. CLI가 별도 adapter를 직접 생성하면 credentials 복호화,
연결 세션, rate limit, circuit breaker, audit 경로가 서버와 분리된다.

```bash
# 연결 상태 확인
ante broker status --account <account_id>

# 잔고 조회
ante broker balance --account <account_id>

# 포지션 조회
ante broker positions --account <account_id>

# 주문/체결 이력 조회 (read-only)
ante broker order-history --account <account_id> [--from <YYYY-MM-DD>] [--to <YYYY-MM-DD>]

# 포지션 대사
ante broker reconcile --account <account_id> [--fix]
```

`order-history`는 `BrokerAdapter.get_order_history()`를 노출하는 read-only 표면이다
(#2412). 반환 row는 어댑터가 정규화한 8키(`order_id`/`symbol`/`side`/`quantity`/
`filled_quantity`/`price`/`status`/`timestamp`)이며 증권사 원시 응답 필드는 어댑터
경계를 넘지 않는다. `--from`/`--to`는 공개 표면 어휘인 ISO `YYYY-MM-DD`로 받고,
어댑터가 요구하는 압축 `YYYYMMDD`로의 변환은 어댑터 호출 직전 **모든 경로**(런타임
IPC 핸들러 / 서버 정지 시 직접 연결 폴백)가 공유하는 단일 헬퍼
(`ante.core.time.iso_to_kis_date`)가 담당한다. 정규화 키의 표현력 한계와 KIS 3개월
경계 교차 구간의 bounded known-limitation은
[cli/03-commands.md](../cli/03-commands.md#broker-order-history--주문체결-이력-조회-read-only)에
열거되어 있으며, 이 명령은 그것을 노출만 하고 해소하지 않는다.

historical/public market data 조회는 `data` 또는 `feed` 계열 커맨드가 담당한다.

일반 운영 CLI는 `broker order`를 제공하지 않는다. 주문은 Bot/Strategy → RuleEngine
→ BrokerAdapter 경로로만 들어가야 하며, 수동 주문 테스트가 필요하면 별도
maintenance/test 스펙에서 승인·감사·실계좌 보호 조건을 정의한다. 실시간 가격
스트리밍 CLI도 오픈 범위가 아니다.
