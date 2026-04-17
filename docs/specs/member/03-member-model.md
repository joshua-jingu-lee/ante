# Member 모듈 세부 설계 - Member 모델

> 인덱스: [README.md](README.md) | 호환 문서: [member.md](member.md)

# Member 모델

```python
@dataclass
class Member:
    member_id: str              # 고유 식별자 (예: "owner", "strategy-dev-01")
    type: str                   # "human" | "agent"
    role: str                   # "master" | "admin" | "default"
    org: str                    # 소속 조직 (예: "default", "strategy-lab")
    name: str                   # 표시 이름 (예: "대표", "전략 리서치 1호")
    emoji: str = ""             # 아바타 이모지 (단일 이모지, 멤버 간 고유)
    status: str                 # "active" | "suspended" | "revoked"
    scopes: list[str]           # 권한 범위 (예: ["strategy:write", "report:write"])
    token_hash: str = ""        # 토큰 해시 (SHA-256)
    password_hash: str = ""     # 패스워드 해시 (human만, PBKDF2-SHA256)
    recovery_key_hash: str = "" # 복구 키 해시 (human만, PBKDF2-SHA256)
    created_at: str = ""        # 생성 시각
    created_by: str = ""        # 생성자 member_id
    last_active_at: str = ""    # 마지막 활동 시각
    suspended_at: str = ""      # 정지 시각
    revoked_at: str = ""        # 폐기 시각
    token_expires_at: str = ""  # 토큰 만료 시각 (기본 90일 TTL)
```

### 토큰 만료 관리

토큰 인증 시 만료 상태를 3단계로 판별한다:

| 상태 | 조건 | 동작 |
|------|------|------|
| 정상 | 만료까지 7일 초과 | 정상 인증 |
| `expiring_soon` | 만료까지 7일 이내 | 인증 성공 + 경고 로그 |
| `expired` | 만료 시각 경과 | 인증 거부 (`PermissionError`) |

만료된 토큰은 `ante member rotate-token`으로 갱신해야 한다.

### Member 상태 흐름

```
active ──→ suspended ──→ active (재활성화)
  │              │
  │              └──→ revoked (영구 폐기)
  │
  └──→ revoked (즉시 폐기)
```

- `suspended`: 일시 정지. 토큰이 유효하지만 인증 시 거부. 재활성화 가능.
- `revoked`: 영구 폐기. 토큰 해시 삭제. 복원 불가. 감사 이력은 보존.

**상태 전이 제약:**
- `suspend`: `active` 상태에서만 가능
- `reactivate`: `suspended` 상태에서만 가능
- `revoke`: `active` 또는 `suspended` 상태에서만 가능. 이미 `revoked`된 멤버에 대한 재폐기는 거부
