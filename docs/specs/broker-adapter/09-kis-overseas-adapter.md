# Broker Adapter 모듈 세부 설계 - KISOverseasAdapter — 해외주식 전용 (1.1 범위)

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# KISOverseasAdapter — 해외주식 전용 (1.1 범위)

> **1.1 범위**: 이 문서에서는 확장 포인트만 정의한다. 구현체는 1.1에서 작성한다.

KISBaseAdapter를 상속하여 해외주식 전용 로직을 구현할 예정이다.

### 국내/해외 분리 요약

| 항목 | KISDomesticAdapter | KISOverseasAdapter |
|------|-------------------|-------------------|
| API 경로 | `/uapi/domestic-stock/v1/` | `/uapi/overseas-stock/v1/` |
| TR ID 매핑 | `TTTC0802U` (매수) 등 | `TTTT1002U` (매수) 등, **거래소별** |
| 주문 파라미터 | `ORD_DVSN`, `PDNO` (6자리) | `OVRS_EXCG_CD`, `TR_CRCY_CD`, 티커 |
| 잔고 조회 | 원화 단일 | 통화별 분리 (`wcrc_frcr_dvsn_cd`) |
| 시세 조회 | `fid_cond_mrkt_div_code: "J"` | `EXCD: "NAS"` 등 |
| 심볼 정규화 | 6자리 숫자 (`005930`) | 영문 티커 (`AAPL`) |
| 호가 단위 | 가격대별 (100/500/1000원) | $0.01 고정 |
| 모의투자 TR | `T` → `V` 접두사 | `T` → `V` 접두사 (동일 규칙) |
