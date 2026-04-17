# Treasury 모듈 세부 설계 - CLI 인터페이스

> 인덱스: [README.md](README.md) | 호환 문서: [treasury.md](treasury.md)

# CLI 인터페이스

자금 관리용 CLI 명령:

```bash
# 자금 현황 조회
ante treasury status
ante treasury bot <bot_id>

# 자금 할당/회수
ante treasury allocate <bot_id> <amount>
ante treasury deallocate <bot_id> <amount>
```

> **참고**: 포지션 조회(`ante trade positions`)와 P&L 조회(`ante trade performance`)는 Trade 모듈 CLI에서 제공한다.

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
