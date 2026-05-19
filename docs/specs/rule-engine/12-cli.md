# Rule Engine 모듈 세부 설계 - CLI 인터페이스

> 인덱스: [README.md](README.md) | 호환 문서: [rule-engine.md](rule-engine.md)

# CLI 인터페이스

CLI 명령 시그니처와 실행 분류의 SSOT는
[cli/03-commands.md](../cli/03-commands.md#ante-rule--거래-룰-관리)다. 이 문서는
Rule Engine 관점의 조회 예시만 제공한다.

```bash
# 룰 목록 조회
ante rule list --account <account_id> [--scope global|strategy]

# 룰 상세 조회
ante rule info <rule_id> --account <account_id>
```

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
