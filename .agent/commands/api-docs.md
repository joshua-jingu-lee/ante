백엔드 OpenAPI 스키마를 조회하여 API 계약 정보를 제공한다.

## 인자

$ARGUMENTS — 검색할 키워드 (예: approval, audit, bot, trade 등). 생략 시 전체 엔드포인트 목록을 출력한다.

## 절차

1. **스키마 조회**: 백엔드 소스에서 OpenAPI 정보를 추출한다.
   ```bash
   # 라우터 파일에서 엔드포인트 정의 검색
   rg -n '@router\.(get|post|put|patch|delete)' src/ante/web/routes/
   ```

2. **키워드 필터링**: 인자가 있으면 해당 키워드가 포함된 엔드포인트만 필터링한다.

3. **상세 정보 수집**: 매칭된 엔드포인트에 대해 다음을 확인한다:
   - 경로, HTTP 메서드
   - 요청 파라미터 (Query, Path, Body)
   - `response_model` (응답 스키마)
   - 해당 Pydantic 모델 정의 (`src/ante/web/schemas.py`)

4. **스키마 모델 조회**: 응답/요청에 사용된 Pydantic 모델의 필드 구조를 확인한다.
   ```bash
   # schemas.py에서 해당 모델 클래스 검색
   rg -n -A 20 'class {모델명}' src/ante/web/schemas.py
   ```

5. **결과 출력**: 엔드포인트별로 다음 형식으로 정리한다:
   ```
   GET /api/approval/
     Query: status (optional), limit (default: 50)
     Response: ApprovalListResponse
       - items: list[ApprovalDetail]
       - total: int
   ```
