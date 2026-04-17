# CLI 모듈 세부 설계 - Agent 워크플로우 예시

> 인덱스: [README.md](README.md) | 호환 문서: [cli.md](cli.md)

# Agent 워크플로우 예시

```bash
# 1. 전략 개발 후 검증
ante strategy validate strategies/my_strategy.py --format json

# 2. 보유 데이터 확인
ante data list --format json

# 3. 백테스트 실행
ante backtest run strategies/my_strategy.py \
    --start 2024-01-01 --end 2026-03-01 \
    --symbols 005930,000660 --format json

# 4. 리포트 스키마 확인 후 제출
ante report schema --format json
ante report submit report_draft.json --format json

# 5. (채택 후) 실전 성과 확인 — Agent 피드백 루프
ante trade list --bot bot_001 --days 30 --format json
ante bot positions bot_001 --format json
ante strategy performance my_strategy --format json
```

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
