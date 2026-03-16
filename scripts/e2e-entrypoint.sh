#!/bin/bash
# E2E 테스트 환경 엔트리포인트
# 1. 시드 데이터 주입
# 2. Ante 서버 시작
set -e

echo "[e2e] 시드 데이터 주입 시작..."
python -c "
import asyncio
from tests.fixtures.seed.seeder import inject_seed_data
result = asyncio.run(inject_seed_data('db/ante.db', 'data/'))
print(f'[e2e] 시드 데이터 주입 완료: {result}')
"

echo "[e2e] Ante 서버 시작..."
exec python -m ante.main
