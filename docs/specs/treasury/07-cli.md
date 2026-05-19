# Treasury 모듈 세부 설계 - CLI 인터페이스

> 인덱스: [README.md](README.md) | 호환 문서: [treasury.md](treasury.md)

# CLI 인터페이스

CLI 명령 시그니처와 실행 분류의 SSOT는
[cli/03-commands.md](../cli/03-commands.md#ante-treasury--자금-관리)다. 이 문서는
Treasury 관점의 사용 예시만 제공한다.

```bash
# 자금 현황 조회
ante treasury status --account <account_id>

# 자금 할당/회수
ante treasury allocate <bot_id> <amount> --account domestic
ante treasury deallocate <bot_id> <amount> --account domestic
```

> **참고**: 포지션 조회는 `ante bot positions <bot_id>` 또는 거래/포트폴리오 조회 API에서 다룬다.

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
