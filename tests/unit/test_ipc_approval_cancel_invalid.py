"""IPC 핸들러 ``_handle_approval_cancel_invalid`` 검증 (#1472).

검증 대상:
- 정상 처리 시 ``svc.approval.cancel_invalid_type_request`` 가 ``resolved_by=actor``
  로 호출된다.
- ``svc.audit_logger`` 가 주입된 경우 ``audit_logger.log`` 가 정확한
  ``(member_id=actor, action="approval.cancel_invalid",
  resource=f"approval:{id}", detail=<request.type>)`` 인자로 호출된다.
- ``svc.audit_logger=None`` 인 경우에도 핸들러는 예외 없이 성공한다 (audit
  호출은 skip 된다).
- ``approval.cancel_invalid`` 가 ``CommandRegistry`` 에 ``is_mutating=True`` 로
  등록되어 있다.
- ``svc.approval.cancel_invalid_type_request`` 가 ``ValueError`` 를 raise 하면
  핸들러도 그대로 raise 한다 (audit 호출은 일어나지 않는다).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.ipc.registry import (
    CommandRegistry,
    _handle_approval_cancel_invalid,
    register_all_handlers,
)


def _make_svc(
    *,
    cancel_return: object | None = None,
    cancel_side_effect: Exception | None = None,
    with_audit_logger: bool = True,
) -> tuple[SimpleNamespace, AsyncMock, AsyncMock | None]:
    """ServiceRegistry-shaped stub + (approval, audit_logger) mock 반환."""
    approval = MagicMock()
    approval.cancel_invalid_type_request = AsyncMock(
        return_value=cancel_return,
        side_effect=cancel_side_effect,
    )

    audit_logger: AsyncMock | None
    if with_audit_logger:
        audit_logger = MagicMock()
        audit_logger.log = AsyncMock()
    else:
        audit_logger = None

    svc = SimpleNamespace(approval=approval, audit_logger=audit_logger)
    return (
        svc,
        approval.cancel_invalid_type_request,
        (audit_logger.log if audit_logger is not None else None),
    )


class TestHandleApprovalCancelInvalid:
    """IPC 핸들러 정상 경로."""

    async def test_calls_service_with_actor_as_resolved_by(self) -> None:
        """approval_id 와 actor 가 서비스로 정확히 전달된다."""
        request_obj = SimpleNamespace(
            id="inv-1",
            status="cancelled",
            type="oracle_invalid_type",
        )
        svc, cancel_mock, _audit_log = _make_svc(cancel_return=request_obj)

        result = await _handle_approval_cancel_invalid(
            svc, {"approval_id": "inv-1"}, "admin-master"
        )

        cancel_mock.assert_awaited_once_with("inv-1", resolved_by="admin-master")
        assert result == {
            "id": "inv-1",
            "status": "cancelled",
            "type": "oracle_invalid_type",
        }

    async def test_audit_logger_called_with_correct_args(self) -> None:
        """AuditLogger.log 가 member_id=actor, action, resource, detail 인자로 호출."""
        request_obj = SimpleNamespace(
            id="inv-2",
            status="cancelled",
            type="legacy_type_x",
        )
        svc, _cancel_mock, audit_log = _make_svc(cancel_return=request_obj)
        assert audit_log is not None

        await _handle_approval_cancel_invalid(
            svc, {"approval_id": "inv-2"}, "admin-master"
        )

        audit_log.assert_awaited_once_with(
            member_id="admin-master",
            action="approval.cancel_invalid",
            resource="approval:inv-2",
            detail="legacy_type_x",
        )

    async def test_handler_succeeds_when_audit_logger_is_none(self) -> None:
        """audit_logger=None 환경에서도 핸들러는 정상 성공."""
        request_obj = SimpleNamespace(
            id="inv-3",
            status="cancelled",
            type="oracle_invalid_type",
        )
        svc, cancel_mock, _ = _make_svc(
            cancel_return=request_obj, with_audit_logger=False
        )

        result = await _handle_approval_cancel_invalid(
            svc, {"approval_id": "inv-3"}, "admin-master"
        )

        cancel_mock.assert_awaited_once()
        assert result["id"] == "inv-3"
        assert result["status"] == "cancelled"

    async def test_handler_succeeds_when_audit_logger_attribute_missing(
        self,
    ) -> None:
        """audit_logger 속성 자체가 없어도 (legacy ServiceRegistry) skip 안전."""
        request_obj = SimpleNamespace(
            id="inv-4",
            status="cancelled",
            type="oracle_invalid_type",
        )
        approval = MagicMock()
        approval.cancel_invalid_type_request = AsyncMock(return_value=request_obj)
        # audit_logger 속성을 의도적으로 부재 시킨다.
        svc = SimpleNamespace(approval=approval)

        result = await _handle_approval_cancel_invalid(
            svc, {"approval_id": "inv-4"}, "admin-master"
        )

        assert result["id"] == "inv-4"


class TestHandleApprovalCancelInvalidErrorPropagation:
    """서비스 거부 시 audit 호출 없이 그대로 raise."""

    async def test_service_value_error_propagates(self) -> None:
        """ApprovalService.cancel_invalid_type_request 의 ValueError 는 그대로 전파."""
        svc, _cancel_mock, audit_log = _make_svc(
            cancel_side_effect=ValueError("not an invalid-type request")
        )

        with pytest.raises(ValueError, match="not an invalid-type request"):
            await _handle_approval_cancel_invalid(
                svc, {"approval_id": "valid-1"}, "admin-master"
            )

        # 거부된 경우 audit 호출 없음
        assert audit_log is not None
        audit_log.assert_not_awaited()


class TestRegistryRegistration:
    """CommandRegistry 등록 invariant."""

    def test_command_registered_as_mutating(self) -> None:
        """approval.cancel_invalid 는 is_mutating=True 로 등록되어야 한다."""
        registry = CommandRegistry()
        register_all_handlers(registry)

        spec = registry.get("approval.cancel_invalid")
        assert spec is not None
        assert spec.is_mutating is True
        assert spec.handler is _handle_approval_cancel_invalid
