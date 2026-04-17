# Member 모듈 세부 설계 - 미결 사항

> 인덱스: [README.md](README.md) | 호환 문서: [member.md](member.md)

# 미결 사항

### bootstrap 시 토큰 동시 발급

- [ ] `MemberService.bootstrap_master()` 반환 타입을 `tuple[Member, str]` → `tuple[Member, str, str]`로 변경 (token, recovery_key)
- [ ] bootstrap 내부에서 `TokenManager`를 호출하여 `ante_hk_*` 토큰 생성 + 해시 저장
- [ ] CLI `ante member bootstrap` 출력에 토큰 및 `export ANTE_MEMBER_TOKEN=...` 안내 추가
- [ ] 기존 테스트(`test_bootstrap_master`) 반환값 검증 수정
- [ ] `guide/cli.md` (자동 생성) — bootstrap 커맨드의 help 텍스트에 토큰 발급 안내 반영
