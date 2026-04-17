# Trade 모듈 세부 설계 - CLI 사용

> 인덱스: [README.md](README.md) | 호환 문서: [trade.md](trade.md)

# CLI 사용

```bash
# 봇별 거래 내역 조회
ante trade list --bot bot_001 --limit 20 --format json

# 전략별 성과 조회
ante trade performance --strategy momentum_breakout_v1.0.0 --format json

# 특정 기간 거래 조회
ante trade list --from 2026-03-01 --to 2026-03-12 --format json

# 봇 요약
ante trade summary --bot bot_001 --format json
```
