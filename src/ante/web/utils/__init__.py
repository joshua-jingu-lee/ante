"""``ante.web.utils`` — Web API 라우트 공용 유틸리티.

라우트 핸들러에서 반복되는 입력 검증/정규화 로직을 모아두는 모듈.
서비스 레이어로 새 추상화를 끌어올리지 않고, 라우트 진입점 직전에
얇은 헬퍼로 끼워 넣는 contract-drift 방지용 SSOT.

본 모듈은 의도적으로 ``ante.web.*`` 외부 의존성을 갖지 않는다.
서비스 레이어 검증 강화는 별도 이슈로 분리한다.
"""

from ante.web.utils.account_params import reject_invalid_account_id
from ante.web.utils.date_params import (
    validate_iso_date_only,
    validate_iso_date_param_for_sql_datetime,
)

__all__ = [
    "reject_invalid_account_id",
    "validate_iso_date_only",
    "validate_iso_date_param_for_sql_datetime",
]
