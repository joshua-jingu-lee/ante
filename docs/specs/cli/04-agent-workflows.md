# CLI 모듈 세부 설계 - Agent 워크플로우 예시

> 인덱스: [README.md](README.md) | 호환 문서: [cli.md](cli.md)

# Agent 워크플로우 예시

`--format json`은 root 전역 옵션이므로 `ante` 바로 뒤에 둔다
(`strategy validate`, `data list`, `backtest run`, `report schema`,
`report submit`, `bot positions`, `strategy performance`는 서브커맨드 자체에
`--format`이 없어 leaf 위치 사용 시 `No such option: --format`으로 실패한다).
`trade list`처럼 서브커맨드가 `--format`을 직접 지원하는 명령은 trailing 형태도 유효하다.

```bash
# 1. 전략 개발 후 검증
ante --format json strategy validate strategies/my_strategy.py

# 2. 보유 데이터 확인
ante --format json data list

# 3. 백테스트 실행
ante --format json backtest run strategies/my_strategy.py \
    --start 2024-01-01 --end 2026-03-01 \
    --symbols 005930,000660

# 4. 리포트 스키마 확인 후 제출
ante --format json report schema
ante --format json report submit report_draft.json

# 5. (채택 후) 실전 성과 확인 — Agent 피드백 루프
ante trade list --bot bot_001 --from 2026-03-01 --to 2026-03-31 --format json
ante --format json bot positions bot_001
ante --format json strategy performance my_strategy
```

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
