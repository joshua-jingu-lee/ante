# Web API 모듈 세부 설계 - Cursor 페이지네이션

> 인덱스: [README.md](README.md) | 호환 문서: [web-api.md](web-api.md)

# Cursor 기반 페이지네이션

> 소스: [`src/ante/web/pagination.py`](../../../src/ante/web/pagination.py)

대량 데이터 목록 API에 cursor 기반 페이지네이션을 적용한다.

| 함수 | 설명 |
|------|------|
| `encode_cursor(value)` | 커서 값을 base64 URL-safe 인코딩 |
| `decode_cursor(cursor)` | 인코딩된 커서를 디코딩 |
| `paginate(items, cursor_field, limit, cursor)` | 아이템 목록에서 커서 이후 limit건 추출. `{"items": [...], "next_cursor": ... \| None}` 반환 |

적용 엔드포인트: `/api/bots`, `/api/trades`, `/api/notifications`, `/api/reports`
