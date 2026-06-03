"""Member 모듈 예외.

Refs #1805: ``MemberNotFoundError`` 를 신규 도입해 service 의 missing-member
경로가 ``ValueError`` 대신 typed exception 을 raise 한다. CLI 6 mutation
surface (set-emoji/suspend/reactivate/revoke/rotate-token, register 는 not-found
경로 부재) 가 envelope 코드 ``"MEMBER_NOT_FOUND"`` 를 stable 하게 surface 한다.
``ApprovalNotFoundError`` (#1798) 와 동형 패턴이다.

Refs #1814 (Group Q sweep): ``MemberStateConflictError`` 를 신규 도입해
``suspend``/``reactivate`` 표면의 state 위반 (이미 SUSPENDED 인 멤버
재정지, 이미 ACTIVE 인 멤버 재활성화) 을 ``PermissionError`` 대신 typed
exception 으로 raise 한다. CLI envelope 이 ``"MEMBER_STATE_CONFLICT"``
안정 코드를 surface 한다. ``ValueError`` 다중상속으로 #1805
``MemberNotFoundError`` 패턴을 따른다.

Refs #1806/#1807 (Group R sweep): ``MemberAlreadyExistsError`` 와
``MemberInvalidRecoveryCredentialError`` 를 신규 도입해 ``register``
duplicate 와 ``reset-password``/``regenerate-recovery-key`` recovery
credential validation 거부를 typed exception 으로 좁힌다. CLI envelope
이 각각 ``"MEMBER_ALREADY_EXISTS"`` / ``"MEMBER_INVALID_RECOVERY_CREDENTIAL"``
안정 코드를 surface 한다. ``ValueError`` 다중상속으로 #1805 패턴 1:1
미러 — 기존 ``except (ValueError, PermissionError)`` fallback 분기가
회귀 없이 동일하게 잡히도록 한다.

Refs #1915: ``MemberInvalidEmojiError`` 와 ``MemberMasterProtectedError`` 를
신규 도입해 emoji 형식 검증 거부 (``_validate_emoji_format``) 와 master
보호 위반 (``_assert_not_master``) 을 typed exception 으로 좁힌다. CLI
envelope 이 각각 ``"MEMBER_INVALID_EMOJI"`` / ``"MEMBER_MASTER_PROTECTED"``
안정 코드를 surface 한다. ``ValueError`` / ``PermissionError`` 다중상속
으로 #1805/#1807 패턴 1:1 미러 — 기존 ``except (ValueError,
PermissionError)`` generic fallback 분기 (CLI ``set-emoji`` /
``suspend`` / ``revoke``) 가 회귀 없이 동일하게 잡히도록 한다.
emoji 중복 (``_validate_emoji_unique``) 와 타입-역할 invariant
(``_assert_type_role``) 는 본 PR scope 외로 보존된다 — 이슈 #1915
본문은 ``MEMBER_INVALID_EMOJI`` (형식 거부) / ``MEMBER_MASTER_PROTECTED``
(master 보호) 두 표면만 명시한다.
"""


class MemberError(Exception):
    """Member 기본 예외."""


class PermissionDeniedError(MemberError):
    """권한 부족 — master만 수행 가능한 작업을 비-master가 시도.

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"PERMISSION_DENIED"`` 로 surface 하도록 한다 (#1843 member sweep).

    CLI direct path 의 ``except PermissionDeniedError:
    fmt.error(_MASTER_REQUIRED_MESSAGE, code="PERMISSION_DENIED")`` 명시
    typed except 는 보존된다 — master 검증 위반의 사용자 친화 한국어 문구
    (``_MASTER_REQUIRED_MESSAGE``) 가 envelope message 로 surface 되도록
    명시 메시지 override 가 필요하다. IPC envelope (server.py:322) 는
    ``getattr(e, "code", "EXECUTION_ERROR")`` 패스로 동일 ``PERMISSION_DENIED``
    코드를 surface 한다 (CLI/IPC 동등성, #1842 plan v2 #6 패턴).
    """

    code: str = "PERMISSION_DENIED"


class MemberNotFoundError(MemberError, ValueError):
    """멤버를 찾을 수 없음 (#1805).

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"MEMBER_NOT_FOUND"`` 로 surface 하도록 한다.

    ``MemberError`` 와 ``ValueError`` 의 다중상속으로 둔다 — ``_get_or_raise``
    가 본 서비스 전체에서 공유되는 헬퍼이므로, ``except ValueError`` 로
    missing-member 를 받아온 기존 caller (CLI ``update-scopes``/``reset-password``
    /``regenerate-recovery-key`` 등 5+ 표면, ``test_member.py:582``,
    ``test_cli_member_non_interactive.py`` mock 시나리오) 가 회귀 없이
    동일하게 잡히도록 한다. ``except MemberNotFoundError`` 를 먼저 둔
    caller (#1805 의 5 mutation surface) 는 typed 분기를 우선 매칭해 안정
    코드 envelope 을 surface 한다 (Python MRO 가 보장).
    """

    code: str = "MEMBER_NOT_FOUND"

    def __init__(self, member_id: str) -> None:
        self.member_id = member_id
        super().__init__(f"존재하지 않는 멤버: {member_id}")


class MemberStateConflictError(MemberError, ValueError):
    """멤버 state flow 위반 (#1814 Group Q sweep).

    ``suspend`` 메서드가 이미 SUSPENDED 인 멤버 (혹은 ACTIVE 가 아닌 상태)
    를 재정지하려 할 때, ``reactivate`` 메서드가 이미 ACTIVE 인 멤버 (혹은
    SUSPENDED 가 아닌 상태) 를 재활성화하려 할 때 raise 한다.

    ``MemberError`` 와 ``ValueError`` 다중상속으로 둔다 — #1805
    ``MemberNotFoundError`` 패턴 1:1 미러. 기존 caller (CLI ``suspend``
    /``reactivate`` 의 ``except (ValueError, PermissionError)`` generic
    fallback line 657/692, ``test_member_service.py:98`` 등) 가 회귀 없이
    동일하게 잡히도록 한다. ``except MemberStateConflictError`` 를 먼저 둔
    caller (#1814 의 2 mutation surface) 는 typed 분기를 우선 매칭해 안정
    코드 envelope 을 surface 한다 (Python MRO 보장).

    이전 (#1814 이전): ``_assert_status`` helper 가 ``PermissionError`` 를
    raise 했으나, state-conflict 는 권한 부족이 아닌 상태 흐름 위반이라
    의미가 모호했다. Group Q sweep 은 ``suspend``/``reactivate`` 의 state
    체크를 인라인 typed raise 로 좁히고, ``revoke`` (plan scope 외, 다중
    상태 허용) 는 기존 ``_assert_status`` helper 를 그대로 사용한다.

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"MEMBER_STATE_CONFLICT"`` 로 surface 하도록 한다.
    """

    code: str = "MEMBER_STATE_CONFLICT"

    def __init__(
        self,
        member_id: str,
        current_status: str,
        requested_action: str,
    ) -> None:
        self.member_id = member_id
        self.current_status = current_status
        self.requested_action = requested_action
        super().__init__(
            f"멤버 '{member_id}' 상태 '{current_status}' 에서 "
            f"'{requested_action}' 작업을 수행할 수 없습니다."
        )


class MemberAlreadyExistsError(MemberError, ValueError):
    """동일 ``member_id`` 멤버가 이미 등록됨 (#1807 Group R sweep).

    ``register`` 메서드가 이미 존재하는 ``member_id`` 를 받았을 때 raise
    한다. ``MemberError`` 와 ``ValueError`` 다중상속으로 둔다 — #1805
    ``MemberNotFoundError`` 패턴 1:1 미러. 기존 caller (CLI ``register``
    의 ``except (ValueError, PermissionError)`` generic fallback,
    ``test_member.py:206``, ``test_cli_member_non_interactive.py``
    mock 시나리오) 가 회귀 없이 동일하게 잡히도록 한다.
    ``except MemberAlreadyExistsError`` 를 먼저 둔 caller 는 typed 분기를
    우선 매칭해 안정 코드 envelope 을 surface 한다 (Python MRO 보장).

    bootstrap_master 의 ``master가 이미 존재합니다`` ValueError 는 ``ante
    init`` 별도 표면으로 본 PR scope 밖이다 (yagni — 이슈 #1807 본문은
    ``member register`` 표면만 명시).

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"MEMBER_ALREADY_EXISTS"`` 로 surface 하도록 한다.
    """

    code: str = "MEMBER_ALREADY_EXISTS"

    def __init__(self, member_id: str) -> None:
        self.member_id = member_id
        super().__init__(f"이미 존재하는 member_id: {member_id}")


class ReservedMemberIdError(MemberError, ValueError):
    """reserved ``system:`` prefix member_id 등록 거부 (#2295).

    ``register`` 가 ``member_id.startswith("system:")`` 등록 요청을 받았을 때
    raise 한다. ``system:`` 는 system audit sentinel 네임스페이스
    (``system:kill_switch`` / ``system:recovery``) 전용 reserved prefix 이며,
    사용자/agent member_id 가 이를 점유하면 audit 행위자 식별이 오염된다.

    ``MemberError`` 와 ``ValueError`` 다중상속으로 둔다 — #1807
    ``MemberAlreadyExistsError`` 패턴 1:1 미러. 기존 caller (CLI ``register``
    의 ``except (ValueError, PermissionError)`` generic fallback) 가 회귀
    없이 동일하게 잡히도록 한다. ``except ReservedMemberIdError`` 를 먼저 둔
    caller 는 typed 분기를 우선 매칭해 안정 코드 envelope 을 surface 한다
    (Python MRO 보장).

    duplicate (``MemberAlreadyExistsError`` / MEMBER_ALREADY_EXISTS) 와는
    별개 fault 로 분리한다 (Codex v2) — register 의 reserved-prefix guard 는
    existing-member 조회 *이전* 에 배치되어, legacy ``system:*`` 행이 있어도
    MEMBER_ALREADY_EXISTS 가 아닌 ``MEMBER_ID_RESERVED`` 코드가 surface 된다.
    permission fault (``PermissionDeniedError`` / PERMISSION_DENIED) 와도
    별개다 — reserved-prefix 는 권한 부족이 아니라 입력 네임스페이스 위반이다.

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"MEMBER_ID_RESERVED"`` 로 surface 하도록 한다.
    """

    code: str = "MEMBER_ID_RESERVED"

    def __init__(self, member_id: str) -> None:
        self.member_id = member_id
        super().__init__(f"예약된 member_id prefix 는 사용할 수 없습니다: {member_id}")


class MemberInvalidRecoveryCredentialError(MemberError, ValueError, PermissionError):
    """recovery credential validation 거부 (#1806 Group R sweep).

    ``reset_password`` 가 잘못된 recovery key 를 받았을 때, 또는
    ``regenerate_recovery_key`` 가 잘못된 현재 패스워드를 받았을 때 raise
    한다.

    ``MemberError`` + ``ValueError`` + ``PermissionError`` 다중상속이다 —
    ``ValueError`` 다중상속은 #1805 ``MemberNotFoundError`` 패턴 (typed
    code) 을 따른다. ``PermissionError`` 다중상속은 이전 (``PermissionError``
    raise) 동작을 보존해 ``except PermissionError`` 를 단언하는 기존
    test (``test_member.py::test_reset_password_wrong_key`` /
    ``test_regenerate_recovery_key`` / ``test_recovery_auth_notification.py``
    line 46) 와 ``except (ValueError, PermissionError)`` generic fallback
    (CLI ``reset-password`` / ``regenerate-recovery-key``) 양쪽이 회귀
    없이 동일하게 잡히도록 한다 — recovery credential 거부는 의미적으로
    `권한 부족` 카테고리에 속하므로 ``PermissionError`` 호환을 유지하는
    것이 의미 정렬상 안전하다.

    ``except MemberInvalidRecoveryCredentialError`` 를 먼저 둔 caller 는
    typed 분기를 우선 매칭해 안정 코드 envelope 을 surface 한다 (Python
    MRO 보장).

    MRO: ``MemberInvalidRecoveryCredentialError → MemberError → Exception``
    (왼쪽 분기), ``→ ValueError → Exception`` (가운데), ``→ PermissionError
    → OSError → Exception`` (오른쪽). C3 linearization 충돌 없음.

    ``change_password`` 의 ``현재 패스워드가 일치하지 않습니다``
    ``PermissionError`` 는 별도 표면으로 본 PR scope 밖이다 (이슈 #1806
    본문은 ``reset-password`` / ``regenerate-recovery-key`` 두 표면만 명시).

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"MEMBER_INVALID_RECOVERY_CREDENTIAL"`` 로 surface 하도록 한다.
    """

    code: str = "MEMBER_INVALID_RECOVERY_CREDENTIAL"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class MemberInvalidEmojiError(MemberError, ValueError):
    """emoji 형식 검증 거부 (#1915).

    ``MemberService._validate_emoji_format`` 이 단일 이모지가 아닌 입력을
    받았을 때 raise 한다. 빈 문자열은 허용되며, 그 외 입력은 ``emoji_pkg``
    (``_is_single_emoji``) 가 단일 이모지로 인식하는 문자열만 통과한다.

    ``MemberError`` 와 ``ValueError`` 다중상속으로 둔다 — #1807
    ``MemberAlreadyExistsError`` 패턴 1:1 미러. 기존 caller (CLI
    ``set-emoji`` 의 ``except ValueError`` generic fallback, ``test_member.py:
    602/606`` 의 ``pytest.raises(ValueError, match="단일 이모지만")`` 단언)
    가 회귀 없이 동일하게 잡히도록 한다. ``emit_cli_error`` registry-first
    lookup 이 본 typed exception 을 받아 안정 코드를 surface 한다 (Python
    MRO 보장).

    ``_validate_emoji_unique`` (emoji 중복 거부) 는 본 PR scope 외 — 이슈
    #1915 본문은 형식 거부 표면만 명시. ``register`` / ``bootstrap_master``
    가 호출하는 형식 검증도 동일 typed exception 으로 자동 정렬된다.

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"MEMBER_INVALID_EMOJI"`` 로 surface 하도록 한다.
    """

    code: str = "MEMBER_INVALID_EMOJI"


class MemberMasterProtectedError(MemberError, PermissionError):
    """master 보호 위반 (#1915).

    ``MemberService._assert_not_master`` 가 master role 멤버에 대한
    ``suspend`` / ``revoke`` 요청을 거부할 때 raise 한다. master 보호 동작
    자체는 그대로 유지되며, raise 타입만 typed exception 으로 좁힌다.

    ``MemberError`` 와 ``PermissionError`` 다중상속으로 둔다 — 기존 caller
    (CLI ``suspend`` / ``revoke`` 의 ``except (ValueError, PermissionError)``
    generic fallback, ``test_member_service_master_guard.py:239/245`` 의
    ``pytest.raises(PermissionError, match="master는 ...")`` 단언) 가 회귀
    없이 동일하게 잡히도록 한다. ``emit_cli_error`` registry-first lookup
    이 본 typed exception 을 받아 안정 코드를 surface 한다 (Python MRO 보장).

    ``_assert_type_role`` (타입-역할 invariant 거부) 는 본 PR scope 외 —
    이슈 #1915 본문은 master 보호 표면만 명시.

    ``PermissionDeniedError`` 와의 분리: ``PermissionDeniedError`` 는 비-master
    호출자의 master-only operation 시도 (``@require_master`` decorator) 를 의미
    하는 반면, 본 ``MemberMasterProtectedError`` 는 master 본인을 대상으로 한
    파괴적 operation (suspend / revoke) 거부를 의미한다. 두 fault 의 의미적
    분리를 envelope 안정 코드로도 분리한다 (``PERMISSION_DENIED`` vs
    ``MEMBER_MASTER_PROTECTED``).

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"MEMBER_MASTER_PROTECTED"`` 로 surface 하도록 한다.
    """

    code: str = "MEMBER_MASTER_PROTECTED"
