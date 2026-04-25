# Trade 모듈 세부 설계 - CLI 사용

> 인덱스: [README.md](README.md) | 호환 문서: [trade.md](trade.md)

# CLI 사용

CLI 명령 시그니처와 실행 분류의 SSOT는
[cli/03-commands.md](../cli/03-commands.md#ante-trade--거래-이력)다. 이 문서는 Trade
관점의 조회 예시만 제공한다.

```bash
# 봇별 거래 내역 조회
ante trade list --bot bot_001 --limit 20 --format json

# 특정 기간 거래 조회
ante trade list --from 2026-03-01 --to 2026-03-12 --format json

# 거래 상세 조회
ante trade info <trade_id> --format json
```
