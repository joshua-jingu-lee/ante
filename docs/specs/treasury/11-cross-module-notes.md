# Treasury 모듈 세부 설계 - 타 모듈 설계 시 참고

> 인덱스: [README.md](README.md) | 호환 문서: [treasury.md](treasury.md)

# 타 모듈 설계 시 참고

- **Trade 스펙**: 포지션은 Trade 모듈이 단일 소유자. Treasury는 포지션을 추적하지 않음
- **Rule Engine 스펙**: 미실현 손익 기반 리스크 모니터링은 Rule Engine의 영역. Trade 모듈에서 포지션 조회하여 판단
- **Web API 스펙**: 자금 현황 API (`GET /treasury/status`, `GET /treasury/bots/{id}`), 스냅샷 API (`GET /treasury/snapshots`, `/snapshots/latest`, `/snapshots/{date}`)
- **CLI 스펙**: `ante treasury status/allocate/deallocate`, `ante treasury snapshot`
