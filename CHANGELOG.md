# CHANGELOG

<!-- version list -->

## v0.12.0 (2026-07-28)

### Bug Fixes

- **broker**: #2384 KIS 매수가능액을 inquire-psbl-order로 노출 — get_buyable 신설 + purchasable_amount SSOT 정렬
  ([#2389](https://github.com/joshua-jingu-lee/ante/pull/2389),
  [`d66a90a`](https://github.com/joshua-jingu-lee/ante/commit/d66a90a1491237aaaffe7961af41b5f24e228293))

- **broker**: #2399 per-app_key cooldown at source — EGW00133 토큰 재타격 근본 차단
  ([#2403](https://github.com/joshua-jingu-lee/ante/pull/2403),
  [`ae6d8b3`](https://github.com/joshua-jingu-lee/ante/commit/ae6d8b37dd9f43d630b1ba52f0910c68c7cadd93))

- **broker**: #2399 startup get_broker EGW00133 bounded retry 재배치 — connect 가 get_broker 내부에 있어
  wrapper 미도달 회귀 수정 ([#2403](https://github.com/joshua-jingu-lee/ante/pull/2403),
  [`ae6d8b3`](https://github.com/joshua-jingu-lee/ante/commit/ae6d8b37dd9f43d630b1ba52f0910c68c7cadd93))

- **broker**: #2399 토큰 캐시 키 config fingerprint — secret/환경 전환 재검증
  ([#2403](https://github.com/joshua-jingu-lee/ante/pull/2403),
  [`ae6d8b3`](https://github.com/joshua-jingu-lee/ante/commit/ae6d8b37dd9f43d630b1ba52f0910c68c7cadd93))

- **broker**: #2399 후속 broker-backed startup init 에서 broker not_ready 계좌 skip — EGW00133 토큰 1/min
  재타격 방지 ([#2403](https://github.com/joshua-jingu-lee/ante/pull/2403),
  [`ae6d8b3`](https://github.com/joshua-jingu-lee/ante/commit/ae6d8b37dd9f43d630b1ba52f0910c68c7cadd93))

- **core**: #2397 리뷰 attempt-2 반영 — treasury 전계좌 self-healing + 면제별 회복 + burst backoff
  ([#2401](https://github.com/joshua-jingu-lee/ante/pull/2401),
  [`7f38e85`](https://github.com/joshua-jingu-lee/ante/commit/7f38e853696c9ba77f555c329b0c3da6e55301a0))

- **core**: #2397 리뷰 attempt-3 반영 — self-healing 스케줄러 재등록 churn 방지
  ([#2401](https://github.com/joshua-jingu-lee/ante/pull/2401),
  [`7f38e85`](https://github.com/joshua-jingu-lee/ante/commit/7f38e853696c9ba77f555c329b0c3da6e55301a0))

- **core**: #2397 리뷰 attempt-4 반영 — broker 회복 시 Treasury sync stale broker 교체
  ([#2401](https://github.com/joshua-jingu-lee/ante/pull/2401),
  [`7f38e85`](https://github.com/joshua-jingu-lee/ante/commit/7f38e853696c9ba77f555c329b0c3da6e55301a0))

- **core**: #2397 리뷰 반영 — self-healing 비-broker readiness 재시도 + reconcile.enabled 존중 + 면제
  fail-closed ([#2401](https://github.com/joshua-jingu-lee/ante/pull/2401),
  [`7f38e85`](https://github.com/joshua-jingu-lee/ante/commit/7f38e853696c9ba77f555c329b0c3da6e55301a0))

- **core**: #2397 메타리뷰 반영 — self-healing 루프 예외 격리 + broker_ready mark 지연
  ([#2401](https://github.com/joshua-jingu-lee/ante/pull/2401),
  [`7f38e85`](https://github.com/joshua-jingu-lee/ante/commit/7f38e853696c9ba77f555c329b0c3da6e55301a0))

- **core**: #2398 active-order gate Codex attempt2 P2 2건 — 메타 기반 non-LIVE silent skip + reason
  fail-closed ([#2402](https://github.com/joshua-jingu-lee/ante/pull/2402),
  [`f2d02b8`](https://github.com/joshua-jingu-lee/ante/commit/f2d02b84cf2eff52534124823a823762ff5c46b5))

- **core**: #2398 active-order gate Codex attempt3 P1 — SUSPENDED kill-switch 우회 차단(status 스냅샷
  fallback 제거) ([#2402](https://github.com/joshua-jingu-lee/ante/pull/2402),
  [`f2d02b8`](https://github.com/joshua-jingu-lee/ante/commit/f2d02b84cf2eff52534124823a823762ff5c46b5))

- **core**: #2398 active-order gate Codex attempt4 P1×2 + 메타 감사 — place_order 직전 단일 재확인 + SUSPENDED
  in-flight backstop ([#2402](https://github.com/joshua-jingu-lee/ante/pull/2402),
  [`f2d02b8`](https://github.com/joshua-jingu-lee/ante/commit/f2d02b84cf2eff52534124823a823762ff5c46b5))

- **core**: #2398 active-order gate Codex attempt5 P2 — virtual SUSPENDED in-flight backstop 대칭
  ([#2402](https://github.com/joshua-jingu-lee/ante/pull/2402),
  [`f2d02b8`](https://github.com/joshua-jingu-lee/ante/commit/f2d02b84cf2eff52534124823a823762ff5c46b5))

- **core**: #2398 virtual-routing 메타 실패 P2 2건 — deterministic 마커 skip
  ([#2402](https://github.com/joshua-jingu-lee/ante/pull/2402),
  [`f2d02b8`](https://github.com/joshua-jingu-lee/ante/commit/f2d02b84cf2eff52534124823a823762ff5c46b5))

- **data**: #2413 0바이트 복구 경로 3건 국소 수정(mode/경고순서/docstring)
  ([#2443](https://github.com/joshua-jingu-lee/ante/pull/2443),
  [`9217bfb`](https://github.com/joshua-jingu-lee/ante/commit/9217bfb05b10df1faa62996f846e351d276ead8a))

- **data**: #2413 code-review 반영 — corruption 판정 좁힘·self-heal write 가드·권한 복원
  ([#2443](https://github.com/joshua-jingu-lee/ante/pull/2443),
  [`9217bfb`](https://github.com/joshua-jingu-lee/ante/commit/9217bfb05b10df1faa62996f846e351d276ead8a))

- **data**: #2413 parquet 파티션 원자 write + 0바이트 파티션 자동복구
  ([#2443](https://github.com/joshua-jingu-lee/ante/pull/2443),
  [`9217bfb`](https://github.com/joshua-jingu-lee/ante/commit/9217bfb05b10df1faa62996f846e351d276ead8a))

- **data**: #2413 parquet 파티션 원자 write + 손상 파티션 self-heal
  ([#2443](https://github.com/joshua-jingu-lee/ante/pull/2443),
  [`9217bfb`](https://github.com/joshua-jingu-lee/ante/commit/9217bfb05b10df1faa62996f846e351d276ead8a))

- **data**: #2413 self-heal 범위를 0바이트-only 자동복구로 축소(단순화)
  ([#2443](https://github.com/joshua-jingu-lee/ante/pull/2443),
  [`9217bfb`](https://github.com/joshua-jingu-lee/ante/commit/9217bfb05b10df1faa62996f846e351d276ead8a))

- **data**: #2413 재리뷰 반영 — self-heal 클래스 불변식 source-level 강제
  ([#2443](https://github.com/joshua-jingu-lee/ante/pull/2443),
  [`9217bfb`](https://github.com/joshua-jingu-lee/ante/commit/9217bfb05b10df1faa62996f846e351d276ead8a))

- **gateway**: #2391 리뷰 반영 — modify broker 조회 try 포함 + quantity finite 검증
  ([#2394](https://github.com/joshua-jingu-lee/ante/pull/2394),
  [`c69e9a6`](https://github.com/joshua-jingu-lee/ante/commit/c69e9a6edf204ea2c6d3e294a9738c1b100a3dad))

- **gateway**: #2391 리뷰 반영(2) — modify 수량/가격 검증 OverflowError·로깅 안전화
  ([#2394](https://github.com/joshua-jingu-lee/ante/pull/2394),
  [`c69e9a6`](https://github.com/joshua-jingu-lee/ante/commit/c69e9a6edf204ea2c6d3e294a9738c1b100a3dad))

- **gateway**: #2391 리뷰 반영(3) — modify 봇 소유권 + 비지정가 fail-closed
  ([#2394](https://github.com/joshua-jingu-lee/ante/pull/2394),
  [`c69e9a6`](https://github.com/joshua-jingu-lee/ante/commit/c69e9a6edf204ea2c6d3e294a9738c1b100a3dad))

- **gateway**: #2405 fallback poll은 세션 멤버십 미마킹 — is_exchange_tick source chokepoint (attempt5 P2)
  ([#2411](https://github.com/joshua-jingu-lee/ante/pull/2411),
  [`68fd30e`](https://github.com/joshua-jingu-lee/ante/commit/68fd30e33b2933b77f92f77ca66465d90ab63ce8))

- **gateway**: #2405 per-order entered_session + market-wide 마킹 (attempt3 P1+P2)
  ([#2411](https://github.com/joshua-jingu-lee/ante/pull/2411),
  [`68fd30e`](https://github.com/joshua-jingu-lee/ante/commit/68fd30e33b2933b77f92f77ca66465d90ab63ce8))

- **gateway**: #2405 register raise + manager-level 세션활동 플래그 (attempt2 P2×2 + 메타 감사)
  ([#2411](https://github.com/joshua-jingu-lee/ante/pull/2411),
  [`68fd30e`](https://github.com/joshua-jingu-lee/ante/commit/68fd30e33b2933b77f92f77ca66465d90ab63ce8))

- **gateway**: #2405 shutdown 순서 — manager.stop()을 IPC gate 뒤로 (attempt4 P2)
  ([#2411](https://github.com/joshua-jingu-lee/ante/pull/2411),
  [`68fd30e`](https://github.com/joshua-jingu-lee/ante/commit/68fd30e33b2933b77f92f77ca66465d90ab63ce8))

- **gateway**: #2405 stop 주문 세션 만료(A2) 자동 배선
  ([#2411](https://github.com/joshua-jingu-lee/ante/pull/2411),
  [`68fd30e`](https://github.com/joshua-jingu-lee/ante/commit/68fd30e33b2933b77f92f77ca66465d90ab63ce8))

- **gateway**: #2405 stop 주문 세션만료 자동 배선(A2) + manager_stopped 복구
  ([#2411](https://github.com/joshua-jingu-lee/ante/pull/2411),
  [`68fd30e`](https://github.com/joshua-jingu-lee/ante/commit/68fd30e33b2933b77f92f77ca66465d90ab63ce8))

- **gateway**: #2405 거래일 확인 세션 늦은 등록 마킹 + expire shield (attempt6 P2-A/P2-B)
  ([#2411](https://github.com/joshua-jingu-lee/ante/pull/2411),
  [`68fd30e`](https://github.com/joshua-jingu-lee/ante/commit/68fd30e33b2933b77f92f77ca66465d90ab63ce8))

- **gateway**: #2405 틱 기반 entered_session 마킹 + register stopped 가드
  ([#2411](https://github.com/joshua-jingu-lee/ante/pull/2411),
  [`68fd30e`](https://github.com/joshua-jingu-lee/ante/commit/68fd30e33b2933b77f92f77ca66465d90ab63ce8))

- **notification**: #2385 KIS 실운용·/stop 종목명 병기 누락 수정 — _sync_instruments 전 계좌 동기화 +
  TelegramCommandReceiver format_label ([#2386](https://github.com/joshua-jingu-lee/ante/pull/2386),
  [`25953d4`](https://github.com/joshua-jingu-lee/ante/commit/25953d40ef31fee7e3f229c0369b0e9b67029a92))

- **process**: #2418 리뷰 반영 rev3 — read-only 리뷰어 쓰기 주체 분리 전수 sweep + autopilot 게이트 배선 + epic 한계 정직화
  ([#2421](https://github.com/joshua-jingu-lee/ante/pull/2421),
  [`7dc27e3`](https://github.com/joshua-jingu-lee/ante/commit/7dc27e32da3d11d0d63fca23230775425d285487))

- **process**: #2418 리뷰 반영 rev4 — @issue-reviewer 게이트 트리거를 confirmed 기준으로 정책과 동일화
  ([#2421](https://github.com/joshua-jingu-lee/ante/pull/2421),
  [`7dc27e3`](https://github.com/joshua-jingu-lee/ante/commit/7dc27e32da3d11d0d63fca23230775425d285487))

- **process**: #2418 리뷰 반영 — @issue-reviewer read-only 통일 (검증·쓰기 주체 분리)
  ([#2421](https://github.com/joshua-jingu-lee/ante/pull/2421),
  [`7dc27e3`](https://github.com/joshua-jingu-lee/ante/commit/7dc27e32da3d11d0d63fca23230775425d285487))

- **process**: #2418 리뷰 반영 — Gate A 빌트인 /code-review 명확화 + base 스코핑 표현 제거 (epic 한정 규칙)
  ([#2421](https://github.com/joshua-jingu-lee/ante/pull/2421),
  [`7dc27e3`](https://github.com/joshua-jingu-lee/ante/commit/7dc27e32da3d11d0d63fca23230775425d285487))

- **release**: #2416 prepare/dry-run 경로 의도치 않은 태그 push 차단
  ([#2419](https://github.com/joshua-jingu-lee/ante/pull/2419),
  [`44834a5`](https://github.com/joshua-jingu-lee/ante/commit/44834a5109966b8af4383059f35537fca8797215))

- **release**: #2416 리뷰 반영 rev4 — dry-run 계약 정합·유령 항목 제거·grep 정밀화
  ([#2419](https://github.com/joshua-jingu-lee/ante/pull/2419),
  [`44834a5`](https://github.com/joshua-jingu-lee/ante/commit/44834a5109966b8af4383059f35537fca8797215))

- **release**: #2416 리뷰 반영 rev5 — 가드 exit code 수정 + 중단 조건 단계 한정
  ([#2419](https://github.com/joshua-jingu-lee/ante/pull/2419),
  [`44834a5`](https://github.com/joshua-jingu-lee/ante/commit/44834a5109966b8af4383059f35537fca8797215))

- **release**: #2416 리뷰 반영 rev6 — stale release PR 복구를 폐기 후 재실행으로 교체
  ([#2419](https://github.com/joshua-jingu-lee/ante/pull/2419),
  [`44834a5`](https://github.com/joshua-jingu-lee/ante/commit/44834a5109966b8af4383059f35537fca8797215))

- **release**: #2416 리뷰 반영 rev7 — stale 복구 명령을 통일 정리 규칙과 동일화
  ([#2419](https://github.com/joshua-jingu-lee/ante/pull/2419),
  [`44834a5`](https://github.com/joshua-jingu-lee/ante/commit/44834a5109966b8af4383059f35537fca8797215))

- **release**: #2416 리뷰 반영 — prepare 순서 재구성 + main 전용 가드
  ([#2419](https://github.com/joshua-jingu-lee/ante/pull/2419),
  [`44834a5`](https://github.com/joshua-jingu-lee/ante/commit/44834a5109966b8af4383059f35537fca8797215))

- **release**: #2416 메타 리뷰 반영 — prepare 라이프사이클 재구조화 + step-level 가드
  ([#2419](https://github.com/joshua-jingu-lee/ante/pull/2419),
  [`44834a5`](https://github.com/joshua-jingu-lee/ante/commit/44834a5109966b8af4383059f35537fca8797215))

- **strategy**: #2404 지표 파라미터 키 docs↔런타임 정합 + legacy-key 가드
  ([#2408](https://github.com/joshua-jingu-lee/ante/pull/2408),
  [`63ccb7a`](https://github.com/joshua-jingu-lee/ante/commit/63ccb7afda0f6ccc9b308e761b05db11245b34ce))

- **trade**: #2407 DB 손상 predicate로 escalation/backoff 좁힘 — transient/내부버그 오분류 차단
  ([#2410](https://github.com/joshua-jingu-lee/ante/pull/2410),
  [`f860434`](https://github.com/joshua-jingu-lee/ante/commit/f8604342cc331e5c981a21c9997e5deb4d392222))

- **trade**: #2407 FillOutboxPublisher DB 손상 escalation/backoff (국소)
  ([#2410](https://github.com/joshua-jingu-lee/ante/pull/2410),
  [`f860434`](https://github.com/joshua-jingu-lee/ante/commit/f8604342cc331e5c981a21c9997e5deb4d392222))

- **trade**: #2407 FillOutboxPublisher._loop DB 손상 escalation/backoff
  ([#2410](https://github.com/joshua-jingu-lee/ante/pull/2410),
  [`f860434`](https://github.com/joshua-jingu-lee/ante/commit/f8604342cc331e5c981a21c9997e5deb4d392222))

### Chores

- #2418 미참조 AI 리뷰 게이트 잔재 스크립트 4종 삭제 + 생성물 갱신
  ([#2421](https://github.com/joshua-jingu-lee/ante/pull/2421),
  [`7dc27e3`](https://github.com/joshua-jingu-lee/ante/commit/7dc27e32da3d11d0d63fca23230775425d285487))

- **deps**: Bump actions/checkout from 5 to 7
  ([#2439](https://github.com/joshua-jingu-lee/ante/pull/2439),
  [`c9e271b`](https://github.com/joshua-jingu-lee/ante/commit/c9e271b1d184fe0590bee50c0d515f54c301dafb))

- **deps**: Bump actions/github-script from 8 to 9
  ([#2432](https://github.com/joshua-jingu-lee/ante/pull/2432),
  [`1b6f4b3`](https://github.com/joshua-jingu-lee/ante/commit/1b6f4b3babfe5f6db150c28bcc5b295702e18b55))

- **deps**: Bump actions/setup-python from 6 to 7
  ([#2446](https://github.com/joshua-jingu-lee/ante/pull/2446),
  [`027904b`](https://github.com/joshua-jingu-lee/ante/commit/027904bd10a09acb5aa60135a584521fb748db45))

- **deps**: Bump docker/build-push-action from 6.19.2 to 7.3.0
  ([#2433](https://github.com/joshua-jingu-lee/ante/pull/2433),
  [`0cc6193`](https://github.com/joshua-jingu-lee/ante/commit/0cc61938f859da814b4320bbb6f51a87e1a8166a))

- **deps**: Bump docker/login-action from 3.7.0 to 4.4.0
  ([#2431](https://github.com/joshua-jingu-lee/ante/pull/2431),
  [`d30e310`](https://github.com/joshua-jingu-lee/ante/commit/d30e310cb27443fda38bd9f5669fa5847f047167))

- **deps**: Bump docker/setup-buildx-action from 3.12.0 to 4.2.0
  ([#2434](https://github.com/joshua-jingu-lee/ante/pull/2434),
  [`5f47c9b`](https://github.com/joshua-jingu-lee/ante/commit/5f47c9b07e1bf1fa12e9e402cb37d9537f88069f))

- **deps**: Bump pypa/gh-action-pypi-publish from 1.14.0 to 1.14.1
  ([#2447](https://github.com/joshua-jingu-lee/ante/pull/2447),
  [`3073c5b`](https://github.com/joshua-jingu-lee/ante/commit/3073c5b3389ebd7bc0467e097d29bc1759f5f7f9))

- **deps**: Bump softprops/action-gh-release from 2.6.2 to 3.0.1
  ([#2435](https://github.com/joshua-jingu-lee/ante/pull/2435),
  [`54a774d`](https://github.com/joshua-jingu-lee/ante/commit/54a774d7c564eb89af903091fff6e402707721bd))

- **deps**: Bump softprops/action-gh-release from 3.0.1 to 3.0.2
  ([#2442](https://github.com/joshua-jingu-lee/ante/pull/2442),
  [`8dfad6c`](https://github.com/joshua-jingu-lee/ante/commit/8dfad6c72c5673c227c5cbc939eecadc3b784680))

### Continuous Integration

- #2428 리뷰 반영 — publish concurrency 제거(무음 취소 함정)·main push CI 활성 조건 정직화
  ([#2429](https://github.com/joshua-jingu-lee/ante/pull/2429),
  [`976e26b`](https://github.com/joshua-jingu-lee/ante/commit/976e26b60fbdee59e34e2d1efb8f70526dfab57c))

- #2428 워크플로우 위생 — 서드파티 SHA 핀·최소권한·concurrency·버전업 + main push CI
  ([#2429](https://github.com/joshua-jingu-lee/ante/pull/2429),
  [`976e26b`](https://github.com/joshua-jingu-lee/ante/commit/976e26b60fbdee59e34e2d1efb8f70526dfab57c))

- #2428 워크플로우 위생 — 서드파티 SHA 핀·최소권한·버전업 + main push CI
  ([#2429](https://github.com/joshua-jingu-lee/ante/pull/2429),
  [`976e26b`](https://github.com/joshua-jingu-lee/ante/commit/976e26b60fbdee59e34e2d1efb8f70526dfab57c))

- #2437 post-merge 폴링 해체 — pull_request:closed 이벤트 + PAT auto-merge
  ([#2441](https://github.com/joshua-jingu-lee/ante/pull/2441),
  [`e9e9c59`](https://github.com/joshua-jingu-lee/ante/commit/e9e9c59724f1ab5833f0fbd432d88b913715b987))

- #2437 post-merge 폴링 해체 — pull_request:closed 이벤트 + PAT auto-merge(fail-closed)
  ([#2441](https://github.com/joshua-jingu-lee/ante/pull/2441),
  [`e9e9c59`](https://github.com/joshua-jingu-lee/ante/commit/e9e9c59724f1ab5833f0fbd432d88b913715b987))

- #2437 리뷰 반영 rev3 — 시크릿 누락 방향별 진단 정확화 + docs/temp stale pr_number 참조 정정
  ([#2441](https://github.com/joshua-jingu-lee/ante/pull/2441),
  [`e9e9c59`](https://github.com/joshua-jingu-lee/ante/commit/e9e9c59724f1ab5833f0fbd432d88b913715b987))

- #2437 리뷰 반영 — Dependabot secrets 병행 등록 안내 + 수동 복구 멱등 서술 정직화
  ([#2441](https://github.com/joshua-jingu-lee/ante/pull/2441),
  [`e9e9c59`](https://github.com/joshua-jingu-lee/ante/commit/e9e9c59724f1ab5833f0fbd432d88b913715b987))

- **publish**: #2430 :latest semver 가드 — 과거 라인 핫픽스 시 latest 역행 차단
  ([#2438](https://github.com/joshua-jingu-lee/ante/pull/2438),
  [`54a0376`](https://github.com/joshua-jingu-lee/ante/commit/54a0376a2ea2bcfcffe67b2f8ebcb68cf3041e5b))

- **publish**: #2430 리뷰 반영 — HIGHEST 파이프라인 grep 무매치 흡수 (pipefail 즉사 수정)
  ([#2438](https://github.com/joshua-jingu-lee/ante/pull/2438),
  [`54a0376`](https://github.com/joshua-jingu-lee/ante/commit/54a0376a2ea2bcfcffe67b2f8ebcb68cf3041e5b))

- **publish**: #2436 PyPI Trusted Publishing(OIDC) 전환 — 장수명 토큰 제거
  ([#2440](https://github.com/joshua-jingu-lee/ante/pull/2440),
  [`8918b38`](https://github.com/joshua-jingu-lee/ante/commit/8918b38b0ba42c9640ce2ddf524f7c812898bf66))

### Documentation

- #2406 README 주의 섹션에 KIS 실전 REST 계약 모의 한정 고지
  ([#2409](https://github.com/joshua-jingu-lee/ante/pull/2409),
  [`a48a355`](https://github.com/joshua-jingu-lee/ante/commit/a48a3554534815ff5415c41be5b08c5870bda057))

- 03-design-decisions.md self-heal 계약을 corruption 좁힘·일시적 오류
  ([#2443](https://github.com/joshua-jingu-lee/ante/pull/2443),
  [`9217bfb`](https://github.com/joshua-jingu-lee/ante/commit/9217bfb05b10df1faa62996f846e351d276ead8a))

- 03-design-decisions.md self-heal 서술을 0바이트-only 축소설계로 갱신
  ([#2443](https://github.com/joshua-jingu-lee/ante/pull/2443),
  [`9217bfb`](https://github.com/joshua-jingu-lee/ante/commit/9217bfb05b10df1faa62996f846e351d276ead8a))

- 03-design-decisions.md에 3개 클래스 불변식·마커 판정·권한/tmp·orphan
  ([#2443](https://github.com/joshua-jingu-lee/ante/pull/2443),
  [`9217bfb`](https://github.com/joshua-jingu-lee/ante/commit/9217bfb05b10df1faa62996f846e351d276ead8a))

- **broker-adapter**: #2387 purchasable_amount KIS 주문가능액 스펙 확정 — inquire-psbl-order get_buyable 계약
  (#2384 선행) ([#2388](https://github.com/joshua-jingu-lee/ante/pull/2388),
  [`2eae297`](https://github.com/joshua-jingu-lee/ante/commit/2eae297af61ec0835a9e3a6d2930fff796cde7c1))

- **ci**: #2428 리뷰 반영 rev3 — GITHUB_TOKEN 예외 단서·concurrency 근거·취소 방향 정밀화
  ([#2429](https://github.com/joshua-jingu-lee/ante/pull/2429),
  [`976e26b`](https://github.com/joshua-jingu-lee/ante/commit/976e26b60fbdee59e34e2d1efb8f70526dfab57c))

- **core**: #2396 readiness gate 스펙 확정 — runtime readiness + active-order gate + KIS token
  single-flight ([#2400](https://github.com/joshua-jingu-lee/ante/pull/2400),
  [`2173606`](https://github.com/joshua-jingu-lee/ante/commit/217360634a936e6c74f74e8a746404197dc5bf92))

- **core**: #2396 readiness gate 스펙 확정 — runtime readiness + active-order gate + KIS token
  single-flight (구현 #2397/#2398/#2399) ([#2400](https://github.com/joshua-jingu-lee/ante/pull/2400),
  [`2173606`](https://github.com/joshua-jingu-lee/ante/commit/217360634a936e6c74f74e8a746404197dc5bf92))

- **core**: #2396 리뷰 반영 — virtual trading_mode deterministic skip + virtual 시장가 0원 체결 금지
  ([#2400](https://github.com/joshua-jingu-lee/ante/pull/2400),
  [`2173606`](https://github.com/joshua-jingu-lee/ante/commit/217360634a936e6c74f74e8a746404197dc5bf92))

- **core**: #2396 리뷰 반영(2) — SUSPENDED kill-switch 계층1 차단 + virtual 가격실패 OrderFailedEvent + virtual
  no-op registry mark ([#2400](https://github.com/joshua-jingu-lee/ante/pull/2400),
  [`2173606`](https://github.com/joshua-jingu-lee/ante/commit/217360634a936e6c74f74e8a746404197dc5bf92))

- **core**: #2396 리뷰 반영(3) — virtual stop StopOrderManager 보존 + EGW00133 generic transient 분리 + 전역
  not_ready 면제 우선 ([#2400](https://github.com/joshua-jingu-lee/ante/pull/2400),
  [`2173606`](https://github.com/joshua-jingu-lee/ante/commit/217360634a936e6c74f74e8a746404197dc5bf92))

- **decisions**: D-019 리뷰 게이트 재설계 — Codex 의존 제거 ADR
  ([#2415](https://github.com/joshua-jingu-lee/ante/pull/2415),
  [`df7423f`](https://github.com/joshua-jingu-lee/ante/commit/df7423f488feb8c3ecdeafc2b03cede694392343))

- **drift**: #2422 리뷰 반영 — BotErrorEvent 예제 account_id 접근을 실제 계약(bot.config.account_id)으로 수정
  ([#2424](https://github.com/joshua-jingu-lee/ante/pull/2424),
  [`7c1ec32`](https://github.com/joshua-jingu-lee/ante/commit/7c1ec32d2f1f9dd96832037a7b97f8ccfa188739))

- **drift**: #2422 스킬 3종·런북 코드/구조 드리프트 정리
  ([#2424](https://github.com/joshua-jingu-lee/ante/pull/2424),
  [`7c1ec32`](https://github.com/joshua-jingu-lee/ante/commit/7c1ec32d2f1f9dd96832037a7b97f8ccfa188739))

- **process**: #2418 D-019 이행 — 리뷰 게이트 재배선 및 Codex 참조 제거
  ([#2421](https://github.com/joshua-jingu-lee/ante/pull/2421),
  [`7dc27e3`](https://github.com/joshua-jingu-lee/ante/commit/7dc27e32da3d11d0d63fca23230775425d285487))

- **process**: #2418 리뷰 게이트 재배선 — Codex→네이티브(@plan-reviewer, /code-review) + @issue-reviewer 신설
  ([#2421](https://github.com/joshua-jingu-lee/ante/pull/2421),
  [`7dc27e3`](https://github.com/joshua-jingu-lee/ante/commit/7dc27e32da3d11d0d63fca23230775425d285487))

- **release**: #2417 1.0.0 메이저 선언 절차 정의 — major_on_zero 정합
  ([#2420](https://github.com/joshua-jingu-lee/ante/pull/2420),
  [`ff40dba`](https://github.com/joshua-jingu-lee/ante/commit/ff40dba1eab64f8c1973053b1807a93796dd57e5))

- **release**: #2417 리뷰 반영 rev2 — publish 경로 declare_major 전파 + 범프 분류 정합 + 게이트 예외
  ([#2420](https://github.com/joshua-jingu-lee/ante/pull/2420),
  [`ff40dba`](https://github.com/joshua-jingu-lee/ante/commit/ff40dba1eab64f8c1973053b1807a93796dd57e5))

- **release**: #2417 리뷰 반영 rev3 — 중단 조건에 declare-major forced-level 예외 반영
  ([#2420](https://github.com/joshua-jingu-lee/ante/pull/2420),
  [`ff40dba`](https://github.com/joshua-jingu-lee/ante/commit/ff40dba1eab64f8c1973053b1807a93796dd57e5))

- **release**: #2426 리뷰 반영 rev3 — 태그 충돌 안전망 배선·불변식 정합·:latest 사후 복구
  ([#2427](https://github.com/joshua-jingu-lee/ante/pull/2427),
  [`f0dc909`](https://github.com/joshua-jingu-lee/ante/commit/f0dc909ec9a8b43fca542278159c15cda51e957d))

- **release**: #2426 리뷰 반영 rev4 — 태그 충돌 해소를 에스컬레이션으로 재서술 (미배선 forced-minor 제거)
  ([#2427](https://github.com/joshua-jingu-lee/ante/pull/2427),
  [`f0dc909`](https://github.com/joshua-jingu-lee/ante/commit/f0dc909ec9a8b43fca542278159c15cda51e957d))

- **release**: #2426 리뷰 반영 rev5 — 확장 이슈 범위를 prepare 계약+CI 양측으로 완결
  ([#2427](https://github.com/joshua-jingu-lee/ante/pull/2427),
  [`f0dc909`](https://github.com/joshua-jingu-lee/ante/commit/f0dc909ec9a8b43fca542278159c15cda51e957d))

- **release**: #2426 리뷰 반영 — 핫픽스 버전 불변식·검증 게이트·:latest 조건화·네이밍 화해 잔여
  ([#2427](https://github.com/joshua-jingu-lee/ante/pull/2427),
  [`f0dc909`](https://github.com/joshua-jingu-lee/ante/commit/f0dc909ec9a8b43fca542278159c15cda51e957d))

- **release**: #2426 브랜치 전략 성문화 — 핫픽스 lazy-branch·keystone·운영 태그 결합
  ([#2427](https://github.com/joshua-jingu-lee/ante/pull/2427),
  [`f0dc909`](https://github.com/joshua-jingu-lee/ante/commit/f0dc909ec9a8b43fca542278159c15cda51e957d))

- **release**: #2436 리뷰 반영 rev3 — §8 폴백 라벨 정합 + rerun 창 경과 시 수동 twine 최후 수단
  ([#2440](https://github.com/joshua-jingu-lee/ante/pull/2440),
  [`8918b38`](https://github.com/joshua-jingu-lee/ante/commit/8918b38b0ba42c9640ce2ddf524f7c812898bf66))

- **release**: #2436 리뷰 반영 rev4 — 수동 twine 자격증명 출처 정정(시크릿 write-only)·수동 GHCR :latest 처분 명시
  ([#2440](https://github.com/joshua-jingu-lee/ante/pull/2440),
  [`8918b38`](https://github.com/joshua-jingu-lee/ante/commit/8918b38b0ba42c9640ce2ddf524f7c812898bf66))

- **release**: #2436 리뷰 반영 rev5 — rev4 부분 정정 잔재 해소 (리드인·§8 표의 시크릿 출처 서술)
  ([#2440](https://github.com/joshua-jingu-lee/ante/pull/2440),
  [`8918b38`](https://github.com/joshua-jingu-lee/ante/commit/8918b38b0ba42c9640ce2ddf524f7c812898bf66))

- **release**: #2436 리뷰 반영 — OIDC 실패 복구를 rerun 기반으로 재작성 (태그 시점 워크플로우 제약)
  ([#2440](https://github.com/joshua-jingu-lee/ante/pull/2440),
  [`8918b38`](https://github.com/joshua-jingu-lee/ante/commit/8918b38b0ba42c9640ce2ddf524f7c812898bf66))

- **runbooks**: #2423 일회성 정리 런북 07·08 archive 이동
  ([#2425](https://github.com/joshua-jingu-lee/ante/pull/2425),
  [`7150d22`](https://github.com/joshua-jingu-lee/ante/commit/7150d22a37ccee8461ec890777d6c52b41de2cd6))

- **strategy**: #2390 modify_order를 broker-level 미구현(deferred)로 SSOT 정렬 — guide·설계스펙·KIS 표 (#2391
  follow-up) ([#2392](https://github.com/joshua-jingu-lee/ante/pull/2392),
  [`c3e1b94`](https://github.com/joshua-jingu-lee/ante/commit/c3e1b94ecbe5dda5d920d06307b859b459d4d6b7))

- **strategy**: #2390 리뷰 반영 — modify RuleEngine 선처리·reason 필드 정확화
  ([#2392](https://github.com/joshua-jingu-lee/ante/pull/2392),
  [`c3e1b94`](https://github.com/joshua-jingu-lee/ante/commit/c3e1b94ecbe5dda5d920d06307b859b459d4d6b7))

- **strategy**: #2390 리뷰 반영(2) — modify 룰 선처리 정확화 전파 + eventbus 구독자 보강
  ([#2392](https://github.com/joshua-jingu-lee/ante/pull/2392),
  [`c3e1b94`](https://github.com/joshua-jingu-lee/ante/commit/c3e1b94ecbe5dda5d920d06307b859b459d4d6b7))

### Features

- **broker**: #2391 KIS 주문 정정 v1(price-only) — modify_order/order-rvsecncl 정정 + un-defer
  ([#2394](https://github.com/joshua-jingu-lee/ante/pull/2394),
  [`c69e9a6`](https://github.com/joshua-jingu-lee/ante/commit/c69e9a6edf204ea2c6d3e294a9738c1b100a3dad))

- **broker**: #2399 KIS 토큰 single-flight + shared cache + EGW00133 per-app_key cooldown
  ([#2403](https://github.com/joshua-jingu-lee/ante/pull/2403),
  [`ae6d8b3`](https://github.com/joshua-jingu-lee/ante/commit/ae6d8b37dd9f43d630b1ba52f0910c68c7cadd93))

- **broker**: #2399 KIS 토큰 single-flight + shared cache + EGW00133 단일 cadence backoff
  ([#2403](https://github.com/joshua-jingu-lee/ante/pull/2403),
  [`ae6d8b3`](https://github.com/joshua-jingu-lee/ante/commit/ae6d8b37dd9f43d630b1ba52f0910c68c7cadd93))

- **core**: #2397 RuntimeReadinessRegistry — per-account readiness + self-healing (observe-only)
  ([#2401](https://github.com/joshua-jingu-lee/ante/pull/2401),
  [`7f38e85`](https://github.com/joshua-jingu-lee/ante/commit/7f38e853696c9ba77f555c329b0c3da6e55301a0))

- **core**: #2397 RuntimeReadinessRegistry — per-account readiness + self-healing (observe-only,
  #2396) ([#2401](https://github.com/joshua-jingu-lee/ante/pull/2401),
  [`7f38e85`](https://github.com/joshua-jingu-lee/ante/commit/7f38e853696c9ba77f555c329b0c3da6e55301a0))

- **core**: #2398 active-order readiness gate — 3계층 defense-in-depth + in-flight kill-switch
  backstop ([#2402](https://github.com/joshua-jingu-lee/ante/pull/2402),
  [`f2d02b8`](https://github.com/joshua-jingu-lee/ante/commit/f2d02b84cf2eff52534124823a823762ff5c46b5))

- **core**: #2398 active-order readiness gate — 3계층 defense-in-depth(G1–G9)
  ([#2402](https://github.com/joshua-jingu-lee/ante/pull/2402),
  [`f2d02b8`](https://github.com/joshua-jingu-lee/ante/commit/f2d02b84cf2eff52534124823a823762ff5c46b5))

### Refactoring

- **docs**: #2418 리뷰 게이트 문서 중복 축약 (재배선 선행)
  ([#2421](https://github.com/joshua-jingu-lee/ante/pull/2421),
  [`7dc27e3`](https://github.com/joshua-jingu-lee/ante/commit/7dc27e32da3d11d0d63fca23230775425d285487))

### Testing

- **gateway**: #2405 _init_gateway stub에 _stop_session_expiry_loop 중립화 — full suite hang 해소
  ([#2411](https://github.com/joshua-jingu-lee/ante/pull/2411),
  [`68fd30e`](https://github.com/joshua-jingu-lee/ante/commit/68fd30e33b2933b77f92f77ca66465d90ab63ce8))


## v0.11.0 (2026-06-13)

### Bug Fixes

- **account**: #2372 _reconnect_broker를 per-account lock으로 직렬화 — in-flight connect와 설정 변경 race 제거
  ([#2376](https://github.com/joshua-jingu-lee/ante/pull/2376),
  [`13f9854`](https://github.com/joshua-jingu-lee/ante/commit/13f985488102114844b03b68b65c240da82318ce))

- **account**: #2372 get_broker connect-성공-후-캐시 + per-account lock + connect 멱등 — 미연결 adapter 캐시 잔존
  제거 ([#2376](https://github.com/joshua-jingu-lee/ante/pull/2376),
  [`13f9854`](https://github.com/joshua-jingu-lee/ante/commit/13f985488102114844b03b68b65c240da82318ce))

- **account**: #2372 get_broker connect-성공-후-캐시 + per-account lock — 미연결 adapter 캐시 잔존 제거
  ([#2376](https://github.com/joshua-jingu-lee/ante/pull/2376),
  [`13f9854`](https://github.com/joshua-jingu-lee/ante/commit/13f985488102114844b03b68b65c240da82318ce))

- **account**: #2372 get_cached_broker를 lock-drain 조회로 — shutdown이 in-flight connect를 놓치는 세션 잔존 제거
  ([#2376](https://github.com/joshua-jingu-lee/ante/pull/2376),
  [`13f9854`](https://github.com/joshua-jingu-lee/ante/commit/13f985488102114844b03b68b65c240da82318ce))

- **broker**: #2324 KIS 빈 msg1 시 get_error_message 폴백으로 비공백 에러메시지 보장
  ([#2332](https://github.com/joshua-jingu-lee/ante/pull/2332),
  [`5a32012`](https://github.com/joshua-jingu-lee/ante/commit/5a32012398363cc704f825f29e928081b198c5ee))

- **broker**: #2342 KIS order-cash TR ID를 공식 현행(0011/0012)으로 갱신
  ([#2343](https://github.com/joshua-jingu-lee/ante/pull/2343),
  [`02934a9`](https://github.com/joshua-jingu-lee/ante/commit/02934a9276e4bd08fdcb898910b5fe6f1f5b81d7))

- **broker**: #2344 KIS order-cash body에 EXCG_ID_DVSN_CD 추가 (공식 현행 계약 정합)
  ([#2355](https://github.com/joshua-jingu-lee/ante/pull/2355),
  [`5b39d50`](https://github.com/joshua-jingu-lee/ante/commit/5b39d50dc4b1e7911f1b70d9da2a47f87f77ef4f))

- **broker**: #2345 KIS order-rvsecncl 취소 body에 KRX_FWDG_ORD_ORGNO 추가 (order-cash 응답 캡처·date-scoped
  캐시) ([#2348](https://github.com/joshua-jingu-lee/ante/pull/2348),
  [`c02eb07`](https://github.com/joshua-jingu-lee/ante/commit/c02eb07df23460f466263d43a3cd2117e4dcb511))

- **broker**: #2350 late-ccld TimeoutError 차단기 회계 제외 + fill 폴 steady-state cooldown
  ([#2358](https://github.com/joshua-jingu-lee/ante/pull/2358),
  [`f4de3a8`](https://github.com/joshua-jingu-lee/ante/commit/f4de3a8dafecaa5298164dabed230556308501df))

- **broker**: #2350 비-transient 예외 시 cooldown 카운터 리셋 (Codex R1 P2)
  ([#2358](https://github.com/joshua-jingu-lee/ante/pull/2358),
  [`f4de3a8`](https://github.com/joshua-jingu-lee/ante/commit/f4de3a8dafecaa5298164dabed230556308501df))

- **broker**: #2361 40910000 모의 주문불가 계좌 PERMANENT 분류 (#1951 미러)
  ([#2362](https://github.com/joshua-jingu-lee/ante/pull/2362),
  [`660dad8`](https://github.com/joshua-jingu-lee/ante/commit/660dad83a31b2d5ea8585956915c082dbac6bb21))

- **broker**: #2368 KIS connect 인증 실패 시 aiohttp session 정리 — unclosed 경고 제거
  ([#2369](https://github.com/joshua-jingu-lee/ante/pull/2369),
  [`196e05e`](https://github.com/joshua-jingu-lee/ante/commit/196e05e45652c23284110c410683b3bad6bd7c63))

- **cli**: #2338 signal connect relay EOF 비대칭 teardown (pump_in EOF 시 pump_out drain)
  ([#2341](https://github.com/joshua-jingu-lee/ante/pull/2341),
  [`c28637d`](https://github.com/joshua-jingu-lee/ante/commit/c28637d072c65e3220da3d1760ef5066dc9a0132))

- **cli**: #2367 trade list --to 날짜를 end-of-day 포함 경계로 — 당일 거래 조회 빈 결과 수정
  ([#2370](https://github.com/joshua-jingu-lee/ante/pull/2370),
  [`0b59bcf`](https://github.com/joshua-jingu-lee/ante/commit/0b59bcf3ed1ff308aa1fbc62215aef4bbb86788a))

- **cli**: #2373 broker status 폴백에 adapter.disconnect 추가 — sibling 대칭 session 정리
  ([#2375](https://github.com/joshua-jingu-lee/ante/pull/2375),
  [`d993035`](https://github.com/joshua-jingu-lee/ante/commit/d993035ba0ee4c19c8ec5fe62b75de2d35f610ec))

- **core**: #2365 Database writer 직렬화 + 트랜잭션 owner 추적 — 태스크 간 중첩 트랜잭션 race 제거
  ([#2366](https://github.com/joshua-jingu-lee/ante/pull/2366),
  [`84b4dd8`](https://github.com/joshua-jingu-lee/ante/commit/84b4dd8cd549dd0010fa8cc156156130e37cdb30))

- **instrument**: #2377 format_label Markdown 이스케이프 + exchange 폴백 known-limitation 고정 (Codex P2 반영)
  ([#2382](https://github.com/joshua-jingu-lee/ante/pull/2382),
  [`c20c8ef`](https://github.com/joshua-jingu-lee/ante/commit/c20c8ef09dd90768339cd409e28add276993fb07))

- **notification**: #2378 텔레그램 /balance TreasuryManager 주입 — 전 계좌 자금 현황 요약
  ([#2380](https://github.com/joshua-jingu-lee/ante/pull/2380),
  [`a1f567b`](https://github.com/joshua-jingu-lee/ante/commit/a1f567b4f7dbf2e3a2c72144069aa672e5f97b11))

- **spec**: #2342 08 order-cash TR ID 표에서 (paper)/(live) terminology lint 잔재 제거
  ([#2343](https://github.com/joshua-jingu-lee/ante/pull/2343),
  [`02934a9`](https://github.com/joshua-jingu-lee/ante/commit/02934a9276e4bd08fdcb898910b5fe6f1f5b81d7))

- **strategy**: #2323 IndicatorCalculator.compute None 결과 가드로 TypeError 차단
  ([#2331](https://github.com/joshua-jingu-lee/ante/pull/2331),
  [`3b72f37`](https://github.com/joshua-jingu-lee/ante/commit/3b72f37c942a2ab9de40e7c5e71a2492316d8af5))

- **trade**: #2351 reconciler sell-side self-check 대칭 확장 — self 매도 외부 오라벨링/force-write 방지
  ([#2359](https://github.com/joshua-jingu-lee/ante/pull/2359),
  [`feed6e3`](https://github.com/joshua-jingu-lee/ante/commit/feed6e332178cb7148238bea9a21e2b42508a72d))

- **trade**: #2352 단일봇 미귀속 보유(carryover) 외부매수 force-write 제거 — capacity==0 detect-only
  ([#2356](https://github.com/joshua-jingu-lee/ante/pull/2356),
  [`f3ca94a`](https://github.com/joshua-jingu-lee/ante/commit/f3ca94a444582934e4893ef24e06e5a6f8d57ac7))

- **trade**: #2371 trades.timestamp 단일 isoformat invariant — save_adjustment 정규화 + v005 마이그레이션
  ([#2374](https://github.com/joshua-jingu-lee/ante/pull/2374),
  [`85bbdbd`](https://github.com/joshua-jingu-lee/ante/commit/85bbdbd15c57b3591b6bcdec519c973f2f0d011c))

### Chores

- .gitignore에 uv.lock 등록 — 로컬 uv 실행 산출물 미추적 처리
  ([`b07e900`](https://github.com/joshua-jingu-lee/ante/commit/b07e9002c9622c04fd1bbbbe920805b5a0dd6ad3))

- **broker**: #2346 KIS 취소 tr_id 신세대 0013U + EXCG_ID_DVSN_CD (라이브 A/B both_ok)
  ([#2363](https://github.com/joshua-jingu-lee/ante/pull/2363),
  [`abf09d1`](https://github.com/joshua-jingu-lee/ante/commit/abf09d16283f8fe5a1789d6886efc541ee321551))

- **broker**: #2349 KIS inquire-daily-ccld tr_id 신세대 4코드(0081R/9215R) 분기 + EXCG_ID_DVSN_CD
  ([#2357](https://github.com/joshua-jingu-lee/ante/pull/2357),
  [`4ec5c3f`](https://github.com/joshua-jingu-lee/ante/commit/4ec5c3f4969384633a8b8e224a0f8a76cdfaef72))

### Documentation

- **generated**: Project-structure.md 전체 재생성 — #2350 신규 테스트 반영 + pre-existing drift 정리
  ([#2358](https://github.com/joshua-jingu-lee/ante/pull/2358),
  [`f4de3a8`](https://github.com/joshua-jingu-lee/ante/commit/f4de3a8dafecaa5298164dabed230556308501df))

- **spec**: #2334 signal connect daemon-위임 스트리밍 아키텍처 스펙 반영
  ([#2335](https://github.com/joshua-jingu-lee/ante/pull/2335),
  [`a9f3e4d`](https://github.com/joshua-jingu-lee/ante/commit/a9f3e4d89346565a4b525612d776a352f75a625c))

- **specs**: #2353 fill-recovery §11 측정 결과 반영 — 다중주문 ODNO 식별 확인·partial known-limitation 확정
  ([#2364](https://github.com/joshua-jingu-lee/ante/pull/2364),
  [`d82e022`](https://github.com/joshua-jingu-lee/ante/commit/d82e0229aced5337583017b0fa4f4e10aad5d8cd))

- **specs**: #2353 fill-recovery 측정 결과 반영 — 다중주문 ODNO 식별 확인·partial known-limitation 확정·모의/실전 사실
  매트릭스 정합 ([#2364](https://github.com/joshua-jingu-lee/ante/pull/2364),
  [`d82e022`](https://github.com/joshua-jingu-lee/ante/commit/d82e0229aced5337583017b0fa4f4e10aad5d8cd))

- **specs**: #2353 §11.7 실전 의존을 TTTC0081R 기준으로 분리 표기 (Codex R2 P2)
  ([#2364](https://github.com/joshua-jingu-lee/ante/pull/2364),
  [`d82e022`](https://github.com/joshua-jingu-lee/ante/commit/d82e0229aced5337583017b0fa4f4e10aad5d8cd))

- **specs**: #2353 §2.1 신 tr_id 효과 확인을 모의 한정으로 명시 (Codex R4 P2)
  ([#2364](https://github.com/joshua-jingu-lee/ante/pull/2364),
  [`d82e022`](https://github.com/joshua-jingu-lee/ante/commit/d82e0229aced5337583017b0fa4f4e10aad5d8cd))

- **specs**: #2353 §9 잔존 실전 의존 표기 정합 (활성 gate 포함, Codex R1 P2)
  ([#2364](https://github.com/joshua-jingu-lee/ante/pull/2364),
  [`d82e022`](https://github.com/joshua-jingu-lee/ante/commit/d82e0229aced5337583017b0fa4f4e10aad5d8cd))

- **specs**: #2353 모의/실전 검증 상태 전수 sweep — V코드 검증완료·T코드 미검증 단일 어휘 (Codex R3 P2)
  ([#2364](https://github.com/joshua-jingu-lee/ante/pull/2364),
  [`d82e022`](https://github.com/joshua-jingu-lee/ante/commit/d82e0229aced5337583017b0fa4f4e10aad5d8cd))

- **specs**: #2353 사실 매트릭스 정합 — fallback 기본활성 근거 승격(공식 지연 가능성)·모의/실전 단일 어휘 교차 미러 (메타 리뷰)
  ([#2364](https://github.com/joshua-jingu-lee/ante/pull/2364),
  [`d82e022`](https://github.com/joshua-jingu-lee/ante/commit/d82e0229aced5337583017b0fa4f4e10aad5d8cd))

### Features

- **cli**: #2338 signal connect thin IPC relay + test migration (#2333 해소)
  ([#2341](https://github.com/joshua-jingu-lee/ante/pull/2341),
  [`c28637d`](https://github.com/joshua-jingu-lee/ante/commit/c28637d072c65e3220da3d1760ef5066dc9a0132))

- **ipc**: #2336 signal.connect transport+ingress 골격 (4-게이트 핸들러·connection-upgrade·typed exceptions)
  ([#2339](https://github.com/joshua-jingu-lee/ante/pull/2339),
  [`373bb43`](https://github.com/joshua-jingu-lee/ante/commit/373bb431ff921d4499935d936951dc2742f2b7f2))

- **ipc**: #2337 signal.connect outbound+registry+lifecycle (SignalChannelRegistry·bounded
  queue·teardown·single-connect) ([#2340](https://github.com/joshua-jingu-lee/ante/pull/2340),
  [`77cb4f1`](https://github.com/joshua-jingu-lee/ante/commit/77cb4f1702aaa50e32b34a62eb4718b14c3a97df))

- **notification**: #2377 텔레그램 알림 종목코드 전 지점 종목명 병기 — InstrumentService.format_label SSOT
  ([#2382](https://github.com/joshua-jingu-lee/ante/pull/2382),
  [`c20c8ef`](https://github.com/joshua-jingu-lee/ante/commit/c20c8ef09dd90768339cd409e28add276993fb07))

- **notification**: #2379 텔레그램 결재 인라인 버튼 전용화 — /approve·/reject 텍스트 명령 스펙아웃
  ([#2381](https://github.com/joshua-jingu-lee/ante/pull/2381),
  [`b5bb993`](https://github.com/joshua-jingu-lee/ante/commit/b5bb99347d5e7d398e6cbcda807396fe86b473d1))


## v0.10.1 (2026-06-05)

### Bug Fixes

- **account**: #2131 suspend(CRITICAL)/activate(INFO) 킬스위치 NotificationEvent 직접 발행
  ([#2262](https://github.com/joshua-jingu-lee/ante/pull/2262),
  [`791bf94`](https://github.com/joshua-jingu-lee/ante/commit/791bf945d0e7282b86870429da0c8cce42cf1d44))

- **backtest**: #1987 미청산 포지션을 현재가로 평가(mark-to-market), final valuation lookahead 차단
  ([#2169](https://github.com/joshua-jingu-lee/ante/pull/2169),
  [`b3f3238`](https://github.com/joshua-jingu-lee/ante/commit/b3f32380b841c1e84bce0c746664b765d0db78de))

- **backtest**: #1989 초과 매도 시 체결 수량으로 수수료/슬리피지/거래 기록
  ([#2170](https://github.com/joshua-jingu-lee/ante/pull/2170),
  [`8106682`](https://github.com/joshua-jingu-lee/ante/commit/810668252bae4630a99d4de4086000fec6cf6059))

- **backtest**: #1990 거래 PnL 추정에 매수 수수료를 원가에 포함 — 손실 거래 오분류 수정
  ([#2227](https://github.com/joshua-jingu-lee/ante/pull/2227),
  [`209eff1`](https://github.com/joshua-jingu-lee/ante/commit/209eff1b85c3bc73f88635e00f5baaa0503e4348))

- **backtest**: #1991 invalid Signal(side/quantity) 검증 추가 (#2066 포함)
  ([#2171](https://github.com/joshua-jingu-lee/ante/pull/2171),
  [`b81c488`](https://github.com/joshua-jingu-lee/ante/commit/b81c4882540b1b063b715b1ce3ba7d1287e84c8a))

- **backtest**: #1994 order_type 트리거/리밋 게이트 — 미충족 limit/stop 즉시 시장가 체결 차단
  ([#2228](https://github.com/joshua-jingu-lee/ante/pull/2228),
  [`493aa63`](https://github.com/joshua-jingu-lee/ante/commit/493aa637947f3c0bf35373f30b77869b1ae49344))

- **backtest**: #1994 order_type 트리거/리밋 게이트 — 미충족 limit/stop 즉시 시장가 체결 차단(체결가 limit cap)
  ([#2228](https://github.com/joshua-jingu-lee/ante/pull/2228),
  [`493aa63`](https://github.com/joshua-jingu-lee/ante/commit/493aa637947f3c0bf35373f30b77869b1ae49344))

- **backtest**: #1998 run()이 결과 artifact 저장 + result_path 전파 (자동 리포트 초안 경로 복구)
  ([#2293](https://github.com/joshua-jingu-lee/ante/pull/2293),
  [`7459dc8`](https://github.com/joshua-jingu-lee/ante/commit/7459dc82ef2de719a53d247fe33540cb430e15ff))

- **backtest**: #2000 run()이 validated.data_paths를 실제 데이터 로딩에 사용
  ([#2218](https://github.com/joshua-jingu-lee/ante/pull/2218),
  [`6089b56`](https://github.com/joshua-jingu-lee/ante/commit/6089b568a6fcb939c09dc8ce7b4a00f0d3af6d7d))

- **backtest**: #2012 비-1d 체결가/지표 조회를 설정 timeframe으로 — provider run-timeframe 인지
  ([#2224](https://github.com/joshua-jingu-lee/ante/pull/2224),
  [`9a2df3f`](https://github.com/joshua-jingu-lee/ante/commit/9a2df3f87a5a16f420f83a544fa0f7ffa064aef0))

- **backtest**: #2013 비-1d 성과지표(annual_return/Sharpe)를 일별 리샘플 기준으로 — bar→일수 왜곡 수정
  ([#2225](https://github.com/joshua-jingu-lee/ante/pull/2225),
  [`26be0ea`](https://github.com/joshua-jingu-lee/ante/commit/26be0eae13263d71e932a7debeaf28fed8e4a415))

- **backtest**: #2034 #2035 #2036 _validate_config가 exchange/date/numeric을 검증
  ([#2204](https://github.com/joshua-jingu-lee/ante/pull/2204),
  [`437691b`](https://github.com/joshua-jingu-lee/ante/commit/437691b6420ac7d2b4ec7250b6e08ecd24d72bdd))

- **backtest**: #2039 backtest run이 StrategyLoader.load 전 StrategyValidator로 검증 — 금지 코드 import 실행 차단
  ([#2236](https://github.com/joshua-jingu-lee/ante/pull/2236),
  [`6a8875a`](https://github.com/joshua-jingu-lee/ante/commit/6a8875a672399f5547ce4362b3ad9aa5af37e467))

- **backtest**: #2053 factory_drift allowlist의 backtest.py Database anchor 라인 갱신(214→229)
  ([#2203](https://github.com/joshua-jingu-lee/ante/pull/2203),
  [`b3b3c6a`](https://github.com/joshua-jingu-lee/ante/commit/b3b3c6a82db7f06ba6b4b9a08da0ca4bde6cf81d))

- **backtest**: #2060 --symbols/--timeframe 생략 시 StrategyMeta로 fallback
  ([#2255](https://github.com/joshua-jingu-lee/ante/pull/2255),
  [`97c868f`](https://github.com/joshua-jingu-lee/ante/commit/97c868f49fc6cb28896b8f4d0d172a8a722a7645))

- **backtest**: #2060 --symbols/--timeframe 생략 시 StrategyMeta로 fallback (Closes #2096)
  ([#2255](https://github.com/joshua-jingu-lee/ante/pull/2255),
  [`97c868f`](https://github.com/joshua-jingu-lee/ante/commit/97c868f49fc6cb28896b8f4d0d172a8a722a7645))

- **backtest**: #2061 첫 데이터 행(row 0)을 처리하도록 커서 초기값 -1 + timestamp 가드
  ([#2177](https://github.com/joshua-jingu-lee/ante/pull/2177),
  [`6a7fc19`](https://github.com/joshua-jingu-lee/ante/commit/6a7fc190c855aae98ebd5d76abd6e338995006a4))

- **backtest**: #2065 run_subprocess 결과를 sentinel marker로 stdout noise와 분리
  ([#2216](https://github.com/joshua-jingu-lee/ante/pull/2216),
  [`eedc928`](https://github.com/joshua-jingu-lee/ante/commit/eedc9285a4e399c7e384479c952b652085e7fb7f))

- **backtest**: #2071 무거래 zero-OHLC 행 backtest-load flat-bar 정규화 (저장 raw 보존)
  ([#2306](https://github.com/joshua-jingu-lee/ante/pull/2306),
  [`757039c`](https://github.com/joshua-jingu-lee/ante/commit/757039cc2a48dad16682e51dbcd7655a22d51d5b))

- **backtest**: #2072 config.symbols universe 밖 Signal.symbol 거래 거부(가격조회 전 조기 skip)
  ([#2231](https://github.com/joshua-jingu-lee/ante/pull/2231),
  [`b5ab9d1`](https://github.com/joshua-jingu-lee/ante/commit/b5ab9d188edaf01af219e91c16257aa2990a21f3))

- **backtest**: #2073 BacktestExecutor on_fill 콜백+follow-up 체결 처리
  ([#2219](https://github.com/joshua-jingu-lee/ante/pull/2219),
  [`b139e20`](https://github.com/joshua-jingu-lee/ante/commit/b139e20b8d96f78b27db86b2aa02322d8305d372))

- **backtest**: #2073 BacktestExecutor가 체결 후 on_fill 호출 및 follow-up 주문 체결
  ([#2219](https://github.com/joshua-jingu-lee/ante/pull/2219),
  [`b139e20`](https://github.com/joshua-jingu-lee/ante/commit/b139e20b8d96f78b27db86b2aa02322d8305d372))

- **backtest**: #2073 cap을 on_fill follow-up에만 적용(on_step 신호 무제한·deque BFS) — 리뷰 회귀 수정
  ([#2219](https://github.com/joshua-jingu-lee/ante/pull/2219),
  [`b139e20`](https://github.com/joshua-jingu-lee/ante/commit/b139e20b8d96f78b27db86b2aa02322d8305d372))

- **backtest**: #2073 on_fill follow-up cap을 루프 상단 선검사로 정확히 강제(off-by-one 수정)
  ([#2219](https://github.com/joshua-jingu-lee/ante/pull/2219),
  [`b139e20`](https://github.com/joshua-jingu-lee/ante/commit/b139e20b8d96f78b27db86b2aa02322d8305d372))

- **backtest**: #2074 get_positions에 current_price/unrealized_pnl 추가 (PortfolioView 스키마 parity)
  ([#2175](https://github.com/joshua-jingu-lee/ante/pull/2175),
  [`c30db26`](https://github.com/joshua-jingu-lee/ante/commit/c30db2608e0497de87f84a57bb8d29ee0794d8ea))

- **backtest**: #2075 BacktestStrategyContext.get_trade_history 추가 (라이브 parity)
  ([#2173](https://github.com/joshua-jingu-lee/ante/pull/2173),
  [`92b4b7a`](https://github.com/joshua-jingu-lee/ante/commit/92b4b7a91729ba256f6dc254630b925ee912a9ef))

- **backtest**: #2083 strategy file-access 공용 helper 추출 +
  BacktestStrategyContext.load_file/load_text
  ([#2174](https://github.com/joshua-jingu-lee/ante/pull/2174),
  [`13f78bc`](https://github.com/joshua-jingu-lee/ante/commit/13f78bcac5156da95f68d9bdcd9650b7e092059b))

- **backtest**: #2098 멀티심볼 백테스트 timestamp 통합 timeline + 체결 current-bar gate (Closes #1992)
  ([#2220](https://github.com/joshua-jingu-lee/ante/pull/2220),
  [`93a0441`](https://github.com/joshua-jingu-lee/ante/commit/93a044160ff54869ae005593d76b09aa8df27b3c))

- **backtest**: #2125 무거래 백테스트도 계산 가능한 성과지표 반환
  ([#2176](https://github.com/joshua-jingu-lee/ante/pull/2176),
  [`6b2cb0d`](https://github.com/joshua-jingu-lee/ante/commit/6b2cb0d8bb480380badfec430426d35961bb08d5))

- **bot**: #2111 rotate JSON 출력을 standard envelope로 복원 (IPC 라우팅 유지, 출력 계약 보존)
  ([#2280](https://github.com/joshua-jingu-lee/ante/pull/2280),
  [`0474bd8`](https://github.com/joshua-jingu-lee/ante/commit/0474bd8a66ca71f833cd7954cd2841641530595c))

- **bot**: #2111 signal-key --rotate를 bot.signal_key.rotate IPC로 라우팅 (cold-path DB mutation 제거)
  ([#2280](https://github.com/joshua-jingu-lee/ante/pull/2280),
  [`0474bd8`](https://github.com/joshua-jingu-lee/ante/commit/0474bd8a66ca71f833cd7954cd2841641530595c))

- **bot**: #2111 signal-key --rotate를 bot.signal_key.rotate IPC로 라우팅 + cold-path DB mutation 제거
  ([#2280](https://github.com/joshua-jingu-lee/ante/pull/2280),
  [`0474bd8`](https://github.com/joshua-jingu-lee/ante/commit/0474bd8a66ca71f833cd7954cd2841641530595c))

- **bot**: #2112 bot list/info/positions/signal-key(read)를 runtime IPC + snapshot fallback로 라우팅
  ([#2286](https://github.com/joshua-jingu-lee/ante/pull/2286),
  [`1273d58`](https://github.com/joshua-jingu-lee/ante/commit/1273d58e63e7e74165d3b3d762bcae050253f736))

- **bot**: #2129 bots.strategy_id↔config_json 일관 갱신 + update_bot 전략 검증
  ([#2275](https://github.com/joshua-jingu-lee/ante/pull/2275),
  [`d70748b`](https://github.com/joshua-jingu-lee/ante/commit/d70748b064ac2800983628c9575df59e94dc255c))

- **bot**: #2129 bots.strategy_id↔config_json 일관 갱신 + update_bot 전략 검증 (Closes #2130)
  ([#2275](https://github.com/joshua-jingu-lee/ante/pull/2275),
  [`d70748b`](https://github.com/joshua-jingu-lee/ante/commit/d70748b064ac2800983628c9575df59e94dc255c))

- **bot**: #2129 update_bot 전략 검증에 effective account_id 사용 (account+strategy 동시 변경 대응, 브랜치 리뷰)
  ([#2275](https://github.com/joshua-jingu-lee/ante/pull/2275),
  [`d70748b`](https://github.com/joshua-jingu-lee/ante/commit/d70748b064ac2800983628c9575df59e94dc255c))

- **bot**: #2137 bot status/positions 조회를 봇 계좌로 스코핑
  ([#2168](https://github.com/joshua-jingu-lee/ante/pull/2168),
  [`44c3bc9`](https://github.com/joshua-jingu-lee/ante/commit/44c3bc97c4edb5847f6de0ef9a71dab0b5b88130))

- **bot**: #2137 error_drift allowlist line 번호 갱신(bot.py 940/976/1010)
  ([#2168](https://github.com/joshua-jingu-lee/ante/pull/2168),
  [`44c3bc9`](https://github.com/joshua-jingu-lee/ante/commit/44c3bc97c4edb5847f6de0ef9a71dab0b5b88130))

- **bot**: #2138 _liquidate_positions를 봇 계좌로 스코핑 + fail-closed 방어
  ([#2162](https://github.com/joshua-jingu-lee/ante/pull/2162),
  [`6bce03b`](https://github.com/joshua-jingu-lee/ante/commit/6bce03b93af25a4c0633c6712a000be9653a9c99))

- **bot**: #2139 Live 전략 컨텍스트 portfolio/trade history를 봇 계좌로 스코핑
  ([#2165](https://github.com/joshua-jingu-lee/ante/pull/2165),
  [`a399117`](https://github.com/joshua-jingu-lee/ante/commit/a3991175e0446486de0e7d50474f225218940cce))

- **bot**: #2143 BOT_SCHEMA account_id DEFAULT 'test' 제거(스펙 정렬)
  ([#2190](https://github.com/joshua-jingu-lee/ante/pull/2190),
  [`67b750f`](https://github.com/joshua-jingu-lee/ante/commit/67b750fa24e7e4c89aac389cb80474bc80bb4fee))

- **bot**: #2143 BOT_SCHEMA account_id DEFAULT 'test' 제거(스펙 정렬) + db-schema 재생성
  ([#2190](https://github.com/joshua-jingu-lee/ante/pull/2190),
  [`67b750f`](https://github.com/joshua-jingu-lee/ante/commit/67b750fa24e7e4c89aac389cb80474bc80bb4fee))

- **bot**: #2274 _save_bot_config UPSERT가 account_id 컬럼도 갱신 (config_json↔컬럼 drift 제거, #2130 동형)
  ([#2284](https://github.com/joshua-jingu-lee/ante/pull/2284),
  [`614acd7`](https://github.com/joshua-jingu-lee/ante/commit/614acd7e889cee6b9df2dc437809af12c0ae3628))

- **bot**: #2282 account_id를 update_bot 불변 필드로 제약
  ([#2312](https://github.com/joshua-jingu-lee/ante/pull/2312),
  [`23ba32c`](https://github.com/joshua-jingu-lee/ante/commit/23ba32ca5bf0bdf3a14817fa09c515f63db216d8))

- **broker**: #2004 FillReconcileScheduler가 get_order_history timestamp를 KST YYYYMMDD로 정규화 (ISO 체결이력
  복구) ([#2266](https://github.com/joshua-jingu-lee/ante/pull/2266),
  [`130bf17`](https://github.com/joshua-jingu-lee/ante/commit/130bf17dfeafc1006956194bd7035d690ba68ccd))

- **broker**: #2126 KIS 조회 메서드 CTX_AREA/tr_cont pagination 처리 (잔고·미체결·체결이력 전 페이지 수집)
  ([#2261](https://github.com/joshua-jingu-lee/ante/pull/2261),
  [`9486a91`](https://github.com/joshua-jingu-lee/ante/commit/9486a91c1b71560002efe2753c1583f36a4d549c))

- **broker**: #2318 fallback 유일성 판정·late-ccld alert 도달성 교정 (Codex 리뷰 반영)
  ([#2321](https://github.com/joshua-jingu-lee/ante/pull/2321),
  [`3a6b83f`](https://github.com/joshua-jingu-lee/ante/commit/3a6b83fb0bbc0489a317e622a1ae1acd3681b2eb))

- **broker**: #2318 KIS 모의 당일 position-derived bounded fallback 구현
  ([#2321](https://github.com/joshua-jingu-lee/ante/pull/2321),
  [`3a6b83f`](https://github.com/joshua-jingu-lee/ante/commit/3a6b83fb0bbc0489a317e622a1ae1acd3681b2eb))

- **broker**: #2318 late-ccld verify를 (odno, item_date) date-scope로 교정 (Codex 리뷰 반영)
  ([#2321](https://github.com/joshua-jingu-lee/ante/pull/2321),
  [`3a6b83f`](https://github.com/joshua-jingu-lee/ante/commit/3a6b83fb0bbc0489a317e622a1ae1acd3681b2eb))

- **cli**: #1965 init 상대 db.path(relocatable) + auth connect 실패 시 aiosqlite 정리
  ([#1967](https://github.com/joshua-jingu-lee/ante/pull/1967),
  [`81e8574`](https://github.com/joshua-jingu-lee/ante/commit/81e8574883ca063da463d4e2ca162cbcd57db795))

- **cli**: #1974 backtest history offline read-only — initialize() 제거 + no such table 정규화
  ([#1976](https://github.com/joshua-jingu-lee/ante/pull/1976),
  [`d31ce22`](https://github.com/joshua-jingu-lee/ante/commit/d31ce22fdd710e17b9a01bbbde139fe6ea2de708))

- **cli**: #1984 data list를 read-only DB artifact 조회로 확대 (load_readonly 캐시 워밍, backtest history 미러)
  ([#2297](https://github.com/joshua-jingu-lee/ante/pull/2297),
  [`a2a44a9`](https://github.com/joshua-jingu-lee/ante/commit/a2a44a934b48f26a3612577a4cf20c6e3892771b))

- **cli**: #1985 report view DB 에러를 REPORT_ERROR envelope으로 처리(report list 동형)
  ([#2246](https://github.com/joshua-jingu-lee/ante/pull/2246),
  [`7edb767`](https://github.com/joshua-jingu-lee/ante/commit/7edb76771521891ba501b4271c3c3df4e99fde1d))

- **cli**: #1986 data list 빈 페이지 count가 total을 유지
  ([#2205](https://github.com/joshua-jingu-lee/ante/pull/2205),
  [`74ea807`](https://github.com/joshua-jingu-lee/ante/commit/74ea80703aeb54ed5778d3b704fb0c51ccf19e58))

- **cli**: #1995 backtest run이 명시 종목 전체 무데이터면 BACKTEST_DATA_NOT_FOUND로 실패
  ([#2207](https://github.com/joshua-jingu-lee/ante/pull/2207),
  [`a83390d`](https://github.com/joshua-jingu-lee/ante/commit/a83390daf3fae9407faa96ea17aaaed60a6dac41))

- **cli**: #2001 backtest run CLI를 D-004 subprocess 격리 경로로 전환
  ([#2302](https://github.com/joshua-jingu-lee/ante/pull/2302),
  [`0baa3c7`](https://github.com/joshua-jingu-lee/ante/commit/0baa3c78355640c0063eb7faaf17f4fdec1fdcb0))

- **cli**: #2024 OutputFormatter가 non-finite float를 null로 정규화해 strict JSON 출력
  ([#2202](https://github.com/joshua-jingu-lee/ante/pull/2202),
  [`f330266`](https://github.com/joshua-jingu-lee/ante/commit/f3302668096e05c6f376d848d67c5638e6590de9))

- **cli**: #2053 backtest run이 strict YYYY-MM-DD만 허용
  ([#2203](https://github.com/joshua-jingu-lee/ante/pull/2203),
  [`b3b3c6a`](https://github.com/joshua-jingu-lee/ante/commit/b3b3c6a82db7f06ba6b4b9a08da0ca4bde6cf81d))

- **cli**: #2108 data validate --fix에 data:write scope 조건부 검증 + data scope 문서 정렬
  ([#2221](https://github.com/joshua-jingu-lee/ante/pull/2221),
  [`3b7d98c`](https://github.com/joshua-jingu-lee/ante/commit/3b7d98c0e88b60944e1c9ba00e7550ebd3d90562))

- **cli**: #2108 data validate --fix에 data:write scope 조건부 검증 + data scope 문서 정렬 (Closes #1996,
  #2154) ([#2221](https://github.com/joshua-jingu-lee/ante/pull/2221),
  [`3b7d98c`](https://github.com/joshua-jingu-lee/ante/commit/3b7d98c0e88b60944e1c9ba00e7550ebd3d90562))

- **cli**: #2108 validate --fix 권한 체크를 입력검증·경로 resolution 이전 최상단으로 이동 (fail-fast)
  ([#2221](https://github.com/joshua-jingu-lee/ante/pull/2221),
  [`3b7d98c`](https://github.com/joshua-jingu-lee/ante/commit/3b7d98c0e88b60944e1c9ba00e7550ebd3d90562))

- **cli**: #2114 report list/view를 read-only DB artifact 조회로 확대 (offline-factory read_only sweep)
  ([#2298](https://github.com/joshua-jingu-lee/ante/pull/2298),
  [`f6e0cd9`](https://github.com/joshua-jingu-lee/ante/commit/f6e0cd9297100240409f97ba545a290020007f06))

- **cli**: #2114 report list/view를 read-only DB artifact 조회로 확대 (offline-factory 적용범위 sweep)
  ([#2298](https://github.com/joshua-jingu-lee/ante/pull/2298),
  [`f6e0cd9`](https://github.com/joshua-jingu-lee/ante/commit/f6e0cd9297100240409f97ba545a290020007f06))

- **cli**: #2135 strategy performance를 record.strategy_id로 필터
  ([#2178](https://github.com/joshua-jingu-lee/ante/pull/2178),
  [`8e6dcf8`](https://github.com/joshua-jingu-lee/ante/commit/8e6dcf8e9c0ba11ffbde578362b7730697e7c99a))

- **cli**: #2144 strategy summary를 trades.strategy_id로 전략 전체 집계 (첫 봇만→모든 트레이드)
  ([#2299](https://github.com/joshua-jingu-lee/ante/pull/2299),
  [`6073b69`](https://github.com/joshua-jingu-lee/ante/commit/6073b693f694bdd9d971d58d5ce8ee6f8887a849))

- **config**: #2132 notification.min_level enum 검증 추가 (CONFIG_VALIDATION_ERROR)
  ([#2179](https://github.com/joshua-jingu-lee/ante/pull/2179),
  [`00a4373`](https://github.com/joshua-jingu-lee/ante/commit/00a43739d8f4b330fb40a6096002d58953855651))

- **config**: #2133 DynamicConfigService.set UPSERT가 기존 키 category 갱신
  ([#2188](https://github.com/joshua-jingu-lee/ante/pull/2188),
  [`3cf0f2a`](https://github.com/joshua-jingu-lee/ante/commit/3cf0f2a799e0012041e010979512a3a97f3895cc))

- **core**: #1970 Database.connect partial-failure 시 worker thread 결정적 join (flaky test 해소)
  ([#1971](https://github.com/joshua-jingu-lee/ante/pull/1971),
  [`48ae63f`](https://github.com/joshua-jingu-lee/ante/commit/48ae63f46afa19915968dfbdc9b4287d5d589586))

- **core**: #1974 Database read-only 연결 모드(mode=ro+immutable fallback) — backtest history 실제
  read-only mount 지원 ([#1979](https://github.com/joshua-jingu-lee/ante/pull/1979),
  [`3c93086`](https://github.com/joshua-jingu-lee/ante/commit/3c93086d157d11ae47f154121c97e856c553e241))

- **core**: #2114 Database docstring의 read_only 적용범위를 data list/report 포함 sweep 정렬
  ([#2298](https://github.com/joshua-jingu-lee/ante/pull/2298),
  [`f6e0cd9`](https://github.com/joshua-jingu-lee/ante/commit/f6e0cd9297100240409f97ba545a290020007f06))

- **core**: #2141 bot_delete approval 검증을 봇 계좌로 스코핑
  ([#2172](https://github.com/joshua-jingu-lee/ante/pull/2172),
  [`2bf340f`](https://github.com/joshua-jingu-lee/ante/commit/2bf340f64ef87cc1f50ce7d115e3ab281801fde8))

- **data**: #1982 data info가 fundamental row_count를 실제 계산, data list는 row_count/file_size를 null로
  ([#2209](https://github.com/joshua-jingu-lee/ante/pull/2209),
  [`9a88d11`](https://github.com/joshua-jingu-lee/ante/commit/9a88d11ea9afa71850ad43319b78c94f7d722eee))

- **data**: #1983 data list가 fundamental+timeframe 모순 조합을 거부
  ([#2208](https://github.com/joshua-jingu-lee/ante/pull/2208),
  [`5006726`](https://github.com/joshua-jingu-lee/ante/commit/500672677188a1c2e32e30011263823e0286a3c9))

- **data**: #2010 DART available_date(rcept_no 접수일) 저장 — point-in-time producer
  ([#2281](https://github.com/joshua-jingu-lee/ante/pull/2281),
  [`fb9c4b7`](https://github.com/joshua-jingu-lee/ante/commit/fb9c4b74f80914f31d3cea9e20dc3b4ca117c876))

- **data**: #2011 DART CFS/OFS 선택에 bsns_year 포함 (연도별 OFS 폴백 보존)
  ([#2276](https://github.com/joshua-jingu-lee/ante/pull/2276),
  [`f1fb1e1`](https://github.com/joshua-jingu-lee/ante/commit/f1fb1e12fe8d6e7f2bee16cd99ab9060a7e43624))

- **data**: #2014 get_date_range가 파일 stem 대신 실제 row 날짜 반환
  ([#2211](https://github.com/joshua-jingu-lee/ante/pull/2211),
  [`dd0de7a`](https://github.com/joshua-jingu-lee/ante/commit/dd0de7a26f441b8e9ae4048c37766dda67824591))

- **data**: #2081 ParquetStore.read date-only end를 whole-day inclusive로 (intraday 당일 장중 포함)
  ([#2265](https://github.com/joshua-jingu-lee/ante/pull/2265),
  [`b5270c9`](https://github.com/joshua-jingu-lee/ante/commit/b5270c9c98c6fa5fd5dd97c4b9526023999911b8))

- **data**: #2095 ParquetStore.read strict 옵션 + backtest load 손상 파티션 fail-closed(BacktestDataError)
  ([#2232](https://github.com/joshua-jingu-lee/ante/pull/2232),
  [`0cfe4b1`](https://github.com/joshua-jingu-lee/ante/commit/0cfe4b1457f23c3701932b9604d2b1165fb5a19e))

- **data**: #2100 RetentionPolicy가 실제 월말 기준으로 age 계산
  ([#2193](https://github.com/joshua-jingu-lee/ante/pull/2193),
  [`8a4c7e0`](https://github.com/joshua-jingu-lee/ante/commit/8a4c7e06228cfc3e38cdd737bffb4ba6c01d6dc4))

- **data**: #2105 DataNormalizer가 tz-aware timestamp를 UTC로 변환
  ([#2200](https://github.com/joshua-jingu-lee/ante/pull/2200),
  [`5a89637`](https://github.com/joshua-jingu-lee/ante/commit/5a8963735cf3181a8065bea33e53557a90e5b191))

- **data**: #2107 ParquetStore가 null partition key를 ValueError로 거부
  ([#2198](https://github.com/joshua-jingu-lee/ante/pull/2198),
  [`3f04a17`](https://github.com/joshua-jingu-lee/ante/commit/3f04a17a93ae5319b52737edde997b6ffb798f7a))

- **data**: #2115 ParquetStore가 ohlcv 10s/30s를 일별 파티션으로 (신규 dir만, legacy 월별은 #2267)
  ([#2268](https://github.com/joshua-jingu-lee/ante/pull/2268),
  [`b1f091b`](https://github.com/joshua-jingu-lee/ante/commit/b1f091b7dc7bbab29532fc6db099333e78b0e7f1))

- **eventbus**: #2058 PositionMismatchEvent/ReconcileEvent account-scoped 승격 (account_id + marker +
  알림 계좌 표시) ([#2184](https://github.com/joshua-jingu-lee/ante/pull/2184),
  [`99df529`](https://github.com/joshua-jingu-lee/ante/commit/99df52985e78b570193c40afe5eac9d65e1f797a))

- **eventbus**: #2145 BotStopEvent에 account_id 필드+marker 추가 및 RuleEngine 전파
  ([#2182](https://github.com/joshua-jingu-lee/ante/pull/2182),
  [`217b132`](https://github.com/joshua-jingu-lee/ante/commit/217b1328e3b6d09ef24ced340a5e4d4d6ff7fbda))

- **eventbus**: #2146 ExternalSignalEvent account_id 필드+marker 추가 및 SignalChannel 전파
  ([#2163](https://github.com/joshua-jingu-lee/ante/pull/2163),
  [`0f49dd9`](https://github.com/joshua-jingu-lee/ante/commit/0f49dd9d8acf13ad90fb6a1b0b00ff31efb0f13c))

- **eventbus**: #2146 ExternalSignalEvent에 account_id 필드+marker 추가 및 SignalChannel 전파
  ([#2163](https://github.com/joshua-jingu-lee/ante/pull/2163),
  [`0f49dd9`](https://github.com/joshua-jingu-lee/ante/commit/0f49dd9d8acf13ad90fb6a1b0b00ff31efb0f13c))

- **eventbus**: #2147 멤버 보안 이벤트 3종 추가 및 MemberService 발행
  ([#2185](https://github.com/joshua-jingu-lee/ante/pull/2185),
  [`c386e50`](https://github.com/joshua-jingu-lee/ante/commit/c386e50b78f8813a33be6cd2881a6762383c94bc))

- **eventbus**: #2155 BotStepCompletedEvent에 signal_count/duration_ms 추가 및 발행
  ([#2183](https://github.com/joshua-jingu-lee/ante/pull/2183),
  [`6a6f842`](https://github.com/joshua-jingu-lee/ante/commit/6a6f842c4179f93e2585855b9ee3d80dd8c4d110))

- **feed**: #1964 fundamental 다중소스 merge 데이터손실 방지 + report.warnings + DART checkpoint clamp
  ([#1966](https://github.com/joshua-jingu-lee/ante/pull/1966),
  [`68bd10f`](https://github.com/joshua-jingu-lee/ante/commit/68bd10fab37ffc9d7d46c6bcac684a1265d949a1))

- **feed**: #1968 파생지표 cadence-aware as-of join (다중소스 fundamental null 해소)
  ([#1969](https://github.com/joshua-jingu-lee/ante/pull/1969),
  [`e2baf03`](https://github.com/joshua-jingu-lee/ante/commit/e2baf03131d8c565185b6bc0afc55f933124057d))

- **feed**: #1972 backfill 가드 분리 — blocked_days skip / blocked_hours 대기(+취소·관측성)
  ([#1973](https://github.com/joshua-jingu-lee/ante/pull/1973),
  [`dcfc108`](https://github.com/joshua-jingu-lee/ante/commit/dcfc108985285277dc74ec633135e05edb448d10))

- **feed**: #1972 stop_event wake-up이 거래시간 window 동시 해제와 race해도 즉시 중단 (Codex 브랜치 리뷰 반영)
  ([#1973](https://github.com/joshua-jingu-lee/ante/pull/1973),
  [`dcfc108`](https://github.com/joshua-jingu-lee/ante/commit/dcfc108985285277dc74ec633135e05edb448d10))

- **feed**: #1993 Codex review 후속 — data.go.kr stored_ok 유도 + DART store-merge checkpoint 게이트
  ([#2301](https://github.com/joshua-jingu-lee/ante/pull/2301),
  [`77f1a40`](https://github.com/joshua-jingu-lee/ante/commit/77f1a403a19d8007e1a87acd774b787324225300))

- **feed**: #1993 rows_written을 net-new 저장 delta로 (checkpoint/DART QuarterStatus 신호 분리)
  ([#2301](https://github.com/joshua-jingu-lee/ante/pull/2301),
  [`77f1a40`](https://github.com/joshua-jingu-lee/ante/commit/77f1a403a19d8007e1a87acd774b787324225300))

- **feed**: #1993 rows_written을 net-new 저장 delta로 — checkpoint·DART store-merge 가드 분리
  ([#2301](https://github.com/joshua-jingu-lee/ante/pull/2301),
  [`77f1a40`](https://github.com/joshua-jingu-lee/ante/commit/77f1a403a19d8007e1a87acd774b787324225300))

- **feed**: #2002 daily_runner가 store_merge 경고를 CollectionResult.warnings로 drain (backfill 패턴 미러)
  ([#2234](https://github.com/joshua-jingu-lee/ante/pull/2234),
  [`131a74e`](https://github.com/joshua-jingu-lee/ante/commit/131a74e663ee6c4ceb6712b904ef8003824f6716))

- **feed**: #2003 scheduler 날짜 생성 헬퍼를 KST 기준으로 (date.today→datetime.now(tz=KST))
  ([#2233](https://github.com/joshua-jingu-lee/ante/pull/2233),
  [`7025432`](https://github.com/joshua-jingu-lee/ante/commit/7025432c3aae750086bfe91e58fdc6533e895820))

- **feed**: #2007 feed lock 원자적 획득(O_CREAT|O_EXCL) + PermissionError=alive 차단 (Closes #2057, #2006)
  ([#2235](https://github.com/joshua-jingu-lee/ante/pull/2235),
  [`18046e5`](https://github.com/joshua-jingu-lee/ante/commit/18046e53a878f0829aa6db0f874bf3826e8fc990))

- **feed**: #2015 data.go.kr checkpoint를 written>0에만 전진 + 미공개일 backfill cap (데이터 누락 해소)
  ([#2259](https://github.com/joshua-jingu-lee/ante/pull/2259),
  [`e9f3e33`](https://github.com/joshua-jingu-lee/ante/commit/e9f3e334d8a80a7cfaffaf459c78e1034b9a5415))

- **feed**: #2019 RateLimiter 날짜 self-reset + #2048 token refill 시간 전진 (2x TPS 차단)
  ([#2229](https://github.com/joshua-jingu-lee/ante/pull/2229),
  [`1b0e225`](https://github.com/joshua-jingu-lee/ante/commit/1b0e2258d476eec242d06873583056fe215cc29e))

- **feed**: #2020 data.go.kr 수집 시 .feed/instruments.parquet 갱신
  ([#2269](https://github.com/joshua-jingu-lee/ante/pull/2269),
  [`a7e9ec9`](https://github.com/joshua-jingu-lee/ante/commit/a7e9ec95000f9eb041cbefa885345823146e127a))

- **feed**: #2020 data.go.kr 수집 시 .feed/instruments.parquet 갱신 (srtnCd/itmsNm/mrktCtg upsert)
  ([#2269](https://github.com/joshua-jingu-lee/ante/pull/2269),
  [`a7e9ec9`](https://github.com/joshua-jingu-lee/ante/commit/a7e9ec95000f9eb041cbefa885345823146e127a))

- **feed**: #2020 itmsNm/mrktCtg 컬럼 전무 시 instruments.parquet 미생성 (브랜치 리뷰 반영)
  ([#2269](https://github.com/joshua-jingu-lee/ante/pull/2269),
  [`a7e9ec9`](https://github.com/joshua-jingu-lee/ante/commit/a7e9ec95000f9eb041cbefa885345823146e127a))

- **feed**: #2021 DARTCollector가 존재하는 corp_code 캐시를 재사용
  ([#2206](https://github.com/joshua-jingu-lee/ante/pull/2206),
  [`1d0191d`](https://github.com/joshua-jingu-lee/ante/commit/1d0191d8c4d8aff7c1127e496e72931193edfbb7))

- **feed**: #2026 HTTP 4xx 비재시도 + #2027 UNKNOWN(99/900) 1회 재시도 — DataFeed source retry 정책 (Closes
  #2027) ([#2240](https://github.com/joshua-jingu-lee/ante/pull/2240),
  [`284a3fa`](https://github.com/joshua-jingu-lee/ante/commit/284a3fa7fcfbce8c2f303157e88f6994c7eabea4))

- **feed**: #2028 DART 빈 분기를 SKIP_EMPTY로 checkpoint 미전진 (미공시 분기 완료 오인 해소)
  ([#2260](https://github.com/joshua-jingu-lee/ante/pull/2260),
  [`d785bc5`](https://github.com/joshua-jingu-lee/ante/commit/d785bc58bfe3b9cea881b3a96a3181f7ba0c1578))

- **feed**: #2029 feed start에서 nice_value 적용 (os.setpriority, best-effort)
  ([#2258](https://github.com/joshua-jingu-lee/ante/pull/2258),
  [`91a83aa`](https://github.com/joshua-jingu-lee/ante/commit/91a83aaa11e761f3f200f8c3f26efba678d97fa0))

- **feed**: #2030 scheduler daily_at/backfill_at/blocked_hours HH:MM 형식 검증 + loop 순서 backfill 우선
  (Closes #2070, #2031) ([#2237](https://github.com/joshua-jingu-lee/ante/pull/2237),
  [`046a0ef`](https://github.com/joshua-jingu-lee/ante/commit/046a0efebd1b99019eff5d8563478520b116feea))

- **feed**: #2037 guard 타입 검증 + #2038 log_level 적용 — feed 커맨드 공통 config helper (Closes #2038)
  ([#2245](https://github.com/joshua-jingu-lee/ante/pull/2245),
  [`1edba76`](https://github.com/joshua-jingu-lee/ante/commit/1edba766e2a56f3ecce9e78c17f4bd896c9da0d4))

- **feed**: #2046 feed config check API 키 네트워크 유효성 검증(valid/invalid/unknown 3-state)
  ([#2287](https://github.com/joshua-jingu-lee/ante/pull/2287),
  [`3c50689`](https://github.com/joshua-jingu-lee/ante/commit/3c506899857d999f2fbc3cd3e316c658c1baea95))

- **feed**: #2047 list_reports를 started_at(datetime) 기준 정렬 — 같은 날짜 daily/backfill 순서 정정
  ([#2257](https://github.com/joshua-jingu-lee/ante/pull/2257),
  [`a951f62`](https://github.com/joshua-jingu-lee/ante/commit/a951f629cf8cc1fc97cc4c7447fc7422aa892269))

- **feed**: #2051 config set 값 개행 거부(키 주입 차단) + #2050 inject 출력을 실제 store 경로로 (Closes #2050)
  ([#2242](https://github.com/joshua-jingu-lee/ante/pull/2242),
  [`eb81872`](https://github.com/joshua-jingu-lee/ante/commit/eb81872c50f6bf68a5948a772951dcc1300ec492))

- **feed**: #2054 DART 분기 실패 시 checkpoint 미전진 (monotonic-safe 재시도)
  ([#2180](https://github.com/joshua-jingu-lee/ante/pull/2180),
  [`082d442`](https://github.com/joshua-jingu-lee/ante/commit/082d442864216ab3c746b3085f2611fd94afbf5c))

- **feed**: #2055 DataGoKrCollector raw 필드 schema 검증 정정 + 실패 레코드 skip·surface (Closes #2008)
  ([#2223](https://github.com/joshua-jingu-lee/ante/pull/2223),
  [`4a95392`](https://github.com/joshua-jingu-lee/ante/commit/4a953929d396e02c4ecda069722180e620f2760d))

- **feed**: #2055 DataGoKrCollector raw 필드 schema 검증 정정 + 실패 레코드 skip·게이트
  ([#2223](https://github.com/joshua-jingu-lee/ante/pull/2223),
  [`4a95392`](https://github.com/joshua-jingu-lee/ante/commit/4a953929d396e02c4ecda069722180e620f2760d))

- **feed**: #2055 validate_all 실패(passed=False) survivor 저장 차단 — schema-skip 계약 방어적 강화
  ([#2223](https://github.com/joshua-jingu-lee/ante/pull/2223),
  [`4a95392`](https://github.com/joshua-jingu-lee/ante/commit/4a953929d396e02c4ecda069722180e620f2760d))

- **feed**: #2067 fundamental as-of join을 공시 접수일(available_date) 기준으로 — lookahead 제거
  ([#2283](https://github.com/joshua-jingu-lee/ante/pull/2283),
  [`430c50a`](https://github.com/joshua-jingu-lee/ante/commit/430c50a848a5d81fe69ae8b7dff052306b890dc0))

- **feed**: #2068 feed run --format json에 CollectionResult failures/warnings 포함
  ([#2256](https://github.com/joshua-jingu-lee/ante/pull/2256),
  [`97517a6`](https://github.com/joshua-jingu-lee/ante/commit/97517a6e2e36d924d318ab7e4cef70690d5c45e8))

- **feed**: #2069 data.go.kr 부분 수집(빈 페이지+totalCount 미달)을 DataGoKrError로 fail-loud
  ([#2194](https://github.com/joshua-jingu-lee/ante/pull/2194),
  [`0c44ad5`](https://github.com/joshua-jingu-lee/ante/commit/0c44ad5a0b551e42f429ac5e55c754b968d3a586))

- **feed**: #2078 data.go.kr backfill 실패 시 checkpoint 미전진 (#2054 동형 halt)
  ([#2181](https://github.com/joshua-jingu-lee/ante/pull/2181),
  [`5cd769f`](https://github.com/joshua-jingu-lee/ante/commit/5cd769f558c51fc88319618fec42d825f3a20bcd))

- **feed**: #2079 DARTCollector가 빈 corp_code_map을 structured warning으로 표면화
  ([#2199](https://github.com/joshua-jingu-lee/ante/pull/2199),
  [`e9585d8`](https://github.com/joshua-jingu-lee/ante/commit/e9585d84264af0fee0d7033fda049337b9d6fca4))

- **feed**: #2080 DataGoKrCollector가 비KRX srtnCd를 drop+warning 처리
  ([#2195](https://github.com/joshua-jingu-lee/ante/pull/2195),
  [`bd783d8`](https://github.com/joshua-jingu-lee/ante/commit/bd783d8e6ddae2d112f8b6ac6183f65d5be66040))

- **feed**: #2087 validate_schema가 모든 레코드의 필수 필드/타입 검사
  ([#2191](https://github.com/joshua-jingu-lee/ante/pull/2191),
  [`7217621`](https://github.com/joshua-jingu-lee/ante/commit/7217621ffbccdbe10a91364b3eed9a31479f3a63))

- **feed**: #2089 validate_business가 NaN/inf 값을 warning으로 관측
  ([#2192](https://github.com/joshua-jingu-lee/ante/pull/2192),
  [`8af7dca`](https://github.com/joshua-jingu-lee/ante/commit/8af7dcafc3db2979cafcc4b25db7d50c07c92a68))

- **feed**: #2099 validate_business가 tz-aware timestamp 시계열 역전 감지 (_try_parse_date fromisoformat
  fallback + mixed-tz 방어) ([#2239](https://github.com/joshua-jingu-lee/ante/pull/2239),
  [`11e0528`](https://github.com/joshua-jingu-lee/ante/commit/11e0528a86bacd35c854fea6a9a7793682822216))

- **feed**: #2101 DART daily 모드는 최신 분기 1개만 수집 (backfill_since 전 분기 순회 차단)
  ([#2279](https://github.com/joshua-jingu-lee/ante/pull/2279),
  [`c2c997b`](https://github.com/joshua-jingu-lee/ante/commit/c2c997b18b4b18288527b244b3eed92b331a14bc))

- **feed**: #2102 validate_business가 정규화 temporal key로 중복 timestamp 감지
  ([#2197](https://github.com/joshua-jingu-lee/ante/pull/2197),
  [`559c534`](https://github.com/joshua-jingu-lee/ante/commit/559c534db8382f239116204a2a4b57bf3c6c39e2))

- **feed**: #2103 validate가 null required field(error)와 unparseable timestamp(warning) 검출
  ([#2201](https://github.com/joshua-jingu-lee/ante/pull/2201),
  [`167f64c`](https://github.com/joshua-jingu-lee/ante/commit/167f64ce329bf2ef336fdd25db82309638c7f0a9))

- **feed**: #2104 check_api_keys가 빈 API 키를 미설정으로 판정
  ([#2196](https://github.com/joshua-jingu-lee/ante/pull/2196),
  [`a586fc8`](https://github.com/joshua-jingu-lee/ante/commit/a586fc8184901d181162ab02f4fbe3c5ad91f62f))

- **feed**: #2106 RateLimiter daily_count를 request attempt 기준으로 — 실패/재시도 시도 반영
  ([#2230](https://github.com/joshua-jingu-lee/ante/pull/2230),
  [`c82fc50`](https://github.com/joshua-jingu-lee/ante/commit/c82fc50cbfd9b8810ba4a059cde7f98bbf8c2664))

- **feed**: #2117 summary에 failures_total 추가 — 비-심볼(날짜/소스) 실패 표면화
  ([#2285](https://github.com/joshua-jingu-lee/ante/pull/2285),
  [`0da8301`](https://github.com/joshua-jingu-lee/ante/commit/0da83015ce45f82098be59726abc4d672e400d88))

- **feed**: #2123 report 파일명에 시각 포함 (같은 날 rerun 이력 보존, 동일초 suffix)
  ([#2300](https://github.com/joshua-jingu-lee/ante/pull/2300),
  [`54ad6b6`](https://github.com/joshua-jingu-lee/ante/commit/54ad6b664d49b2e7df65d6daa1cc01b119dc90ed))

- **feed**: #2222 data.go.kr business 검증을 정규화 후 OHLCV에 적용
  ([#2311](https://github.com/joshua-jingu-lee/ante/pull/2311),
  [`2180695`](https://github.com/joshua-jingu-lee/ante/commit/21806959e92aac33199537d22d4b1184c536679a))

- **gateway**: #2044 주문 취소 완료/실패 이벤트에 symbol/side 채움 (OrderTracker record, cross-account 가드)
  ([#2288](https://github.com/joshua-jingu-lee/ante/pull/2288),
  [`7312e1c`](https://github.com/joshua-jingu-lee/ante/commit/7312e1cd86595ae0015e1e213aee5a458518caa6))

- **gateway**: #2124 StopOrderManager.get_orders_for_account 추가(스펙 parity)
  ([#2189](https://github.com/joshua-jingu-lee/ante/pull/2189),
  [`6207abb`](https://github.com/joshua-jingu-lee/ante/commit/6207abb6ba11e41ffb5b94911f30c0a846d683b7))

- **gateway**: #2134 cancel_order가 OrderTracker로 broker_order_id 변환 (fail-closed + account scoping)
  ([#2263](https://github.com/joshua-jingu-lee/ante/pull/2263),
  [`557391b`](https://github.com/joshua-jingu-lee/ante/commit/557391b82cd4feece73493ebdbbce300bae668c7))

- **gateway**: #2142 취소 broker False 반환 시 OrderCancelFailedEvent 발행
  ([#2166](https://github.com/joshua-jingu-lee/ante/pull/2166),
  [`098d5d9`](https://github.com/joshua-jingu-lee/ante/commit/098d5d9b14314ba9567081f53022f330d44869a6))

- **ipc**: #2109 audit를 correction 직후로 이동 (compute_account_diff 실패가 audit 누락시키지 않도록)
  ([#2291](https://github.com/joshua-jingu-lee/ante/pull/2291),
  [`beae461`](https://github.com/joshua-jingu-lee/ante/commit/beae4611e3cad538704a6b9756f8ede912f02f48))

- **ipc**: #2109 broker.reconcile --fix 실제 보정 시 조건부 audit (핸들러-레벨)
  ([#2291](https://github.com/joshua-jingu-lee/ante/pull/2291),
  [`beae461`](https://github.com/joshua-jingu-lee/ante/commit/beae4611e3cad538704a6b9756f8ede912f02f48))

- **ipc**: #2109 broker.reconcile --fix 실제 보정 시 조건부 audit (핸들러-레벨, fail-closed audit_logger
  required) ([#2291](https://github.com/joshua-jingu-lee/ante/pull/2291),
  [`beae461`](https://github.com/joshua-jingu-lee/ante/commit/beae4611e3cad538704a6b9756f8ede912f02f48))

- **ipc**: #2110 상태변경 명령 7개에 audit_action wiring (system halt/clear-halt, bot create/remove,
  approval approve/reject/cancel) ([#2290](https://github.com/joshua-jingu-lee/ante/pull/2290),
  [`e7e0cf0`](https://github.com/joshua-jingu-lee/ante/commit/e7e0cf00a786744e7b4c90ec1dbec5dd87c77576))

- **ipc**: #2113 member admin mutation 8개 runtime IPC wiring (IPC-first+fallback, secret 비노출, audit)
  ([#2296](https://github.com/joshua-jingu-lee/ante/pull/2296),
  [`8775de9`](https://github.com/joshua-jingu-lee/ante/commit/8775de9f653685f46d0fd97606d5148a764e2c32))

- **member**: #2150 멤버 정지/폐기 시 NotificationEvent 발행(보안 알림 wiring)
  ([#2187](https://github.com/joshua-jingu-lee/ante/pull/2187),
  [`bd6c1ae`](https://github.com/joshua-jingu-lee/ante/commit/bd6c1ae23bce46cb7a4529c167f29ce4d9122996))

- **member**: #2294 #2295 register 무조건 master 게이트 + recovery audit sentinel 비충돌·reserved prefix
  guard ([#2308](https://github.com/joshua-jingu-lee/ante/pull/2308),
  [`c0c1f90`](https://github.com/joshua-jingu-lee/ante/commit/c0c1f9026e128a331d6d7068b7d7004438eb62b5))

- **reconcile**: #2119 broker.reconcile account-level 재설계 — 1봇-total 보정/다중봇 detect-only (Closes
  #2118, #2120, #2121, #2122) ([#2271](https://github.com/joshua-jingu-lee/ante/pull/2271),
  [`aa0b19b`](https://github.com/joshua-jingu-lee/ante/commit/aa0b19b74aab316f29d6b800b101a7b62cb95040))

- **repo**: #1981 config/db/pip_freeze 런타임 스냅샷 git 추적 제거
  ([#2305](https://github.com/joshua-jingu-lee/ante/pull/2305),
  [`06057cd`](https://github.com/joshua-jingu-lee/ante/commit/06057cdf5ff210285327fc51b20a4effcfa714f0))

- **report**: #1999 report submit --run backtest_run_id durable 저장 (effective run_id 검증, 컬럼 마이그레이션)
  ([#2292](https://github.com/joshua-jingu-lee/ante/pull/2292),
  [`cd5ebf3`](https://github.com/joshua-jingu-lee/ante/commit/cd5ebf34d6e498146f53a4209c3f0a4bb4925531))

- **report**: #2025 detail_json을 표준 JSON으로 검증(NaN/Infinity·비JSON 거부)
  ([#2241](https://github.com/joshua-jingu-lee/ante/pull/2241),
  [`96d2314`](https://github.com/joshua-jingu-lee/ante/commit/96d2314c7af8ee24a17139579627b0c7085c5b60))

- **report**: #2136 PerformanceFeedback 조회를 봇 계좌로 스코핑
  ([#2167](https://github.com/joshua-jingu-lee/ante/pull/2167),
  [`ddf89b9`](https://github.com/joshua-jingu-lee/ante/commit/ddf89b9872026756efb020392a7649ece5c67a7b))

- **rule**: #2045 RuleEngine이 modify event symbol/side를 OrderTracker로 enrich (modify_rejected 계약 충족,
  단일 chokepoint) ([#2289](https://github.com/joshua-jingu-lee/ante/pull/2289),
  [`01d1d2f`](https://github.com/joshua-jingu-lee/ante/commit/01d1d2ffd8c27416e4b7185fea607e91db5c96a9))

- **rule**: #2140 RuleEngine 미실현손익 계산을 봇 계좌로 스코핑
  ([#2164](https://github.com/joshua-jingu-lee/ante/pull/2164),
  [`d62523d`](https://github.com/joshua-jingu-lee/ante/commit/d62523d52e2bf5b7680ace84b4b484565b3aed3b))

- **rule**: #2315 미복구 self-order 반복 매수 가드 추가
  ([#2320](https://github.com/joshua-jingu-lee/ante/pull/2320),
  [`900bb1c`](https://github.com/joshua-jingu-lee/ante/commit/900bb1cbc64c5590e0f7e87b877593828b8c82dd))

- **strategy**: #2017 StrategyValidator symbols/exchange 일관성 경고(KRX 형식 불일치 warning)
  ([#2244](https://github.com/joshua-jingu-lee/ante/pull/2244),
  [`445162e`](https://github.com/joshua-jingu-lee/ante/commit/445162e32f6732c15919364bf633cd8602beb874))

- **strategy**: #2018 StrategyValidator가 최상위 if 내부 실행코드 검사
  ([#2213](https://github.com/joshua-jingu-lee/ante/pull/2213),
  [`50ef3c1`](https://github.com/joshua-jingu-lee/ante/commit/50ef3c10a5f2a7e538365067362d72bf26fe2479))

- **strategy**: #2022 StrategyValidator가 모듈 상수로 전달된 invalid exchange 검출
  ([#2212](https://github.com/joshua-jingu-lee/ante/pull/2212),
  [`ead7592`](https://github.com/joshua-jingu-lee/ante/commit/ead75929251e94af5cb3bce4cdb0abf846dae9c6))

- **strategy**: #2023 StrategyValidator가 __builtins__ subscript/attribute 우회 검출
  ([#2214](https://github.com/joshua-jingu-lee/ante/pull/2214),
  [`b94a38e`](https://github.com/joshua-jingu-lee/ante/commit/b94a38e2626c9f1f57a498030d1fed6e3386eef1))

- **strategy**: #2032 #2033 StrategyValidator가 top-level decorator/default 부작용 검출
  ([#2215](https://github.com/joshua-jingu-lee/ante/pull/2215),
  [`80e8be1`](https://github.com/joshua-jingu-lee/ante/commit/80e8be168ef48dbbe72825ae5a888d01584d6a50))

- **strategy**: #2040 StrategyValidator/Loader validate↔load 계약 패리티 (async hook/meta 타입/실제 Strategy
  상속/loader 파일정의) ([#2226](https://github.com/joshua-jingu-lee/ante/pull/2226),
  [`b44b371`](https://github.com/joshua-jingu-lee/ante/commit/b44b371eea115f8e85e2de140c3fd94934cedba4))

- **strategy**: #2040 validate↔load 계약 패리티 — on_step async/meta 타입/실제 Strategy 상속/loader 파일정의 카운트
  (Closes #2041, #2042, #2052) ([#2226](https://github.com/joshua-jingu-lee/ante/pull/2226),
  [`b44b371`](https://github.com/joshua-jingu-lee/ante/commit/b44b371eea115f8e85e2de140c3fd94934cedba4))

- **strategy**: #2041 meta StrategyMeta 호출을 import-aware로 해석(#2042와 일관) — fake.StrategyMeta
  false-positive 차단 ([#2226](https://github.com/joshua-jingu-lee/ante/pull/2226),
  [`b44b371`](https://github.com/joshua-jingu-lee/ante/commit/b44b371eea115f8e85e2de140c3fd94934cedba4))

- **strategy**: #2041 meta 타입 검사를 마지막 할당 기준으로 — 재할당 false-positive 수정
  ([#2226](https://github.com/joshua-jingu-lee/ante/pull/2226),
  [`b44b371`](https://github.com/joshua-jingu-lee/ante/commit/b44b371eea115f8e85e2de140c3fd94934cedba4))

- **strategy**: #2042 base 해석을 정의 순서 단일 패스로 — import-then-local-redefine name resolution 정합
  ([#2226](https://github.com/joshua-jingu-lee/ante/pull/2226),
  [`b44b371`](https://github.com/joshua-jingu-lee/ante/commit/b44b371eea115f8e85e2de140c3fd94934cedba4))

- **strategy**: #2042 module-alias 재바인딩 무효화(name_binding 대칭) + 정적 name-resolution bounded
  known-limitation 명문화 ([#2226](https://github.com/joshua-jingu-lee/ante/pull/2226),
  [`b44b371`](https://github.com/joshua-jingu-lee/ante/commit/b44b371eea115f8e85e2de140c3fd94934cedba4))

- **strategy**: #2042 Strategy 바인딩·클래스 탐지를 module-scope로 한정 — 함수내부 import false-positive 차단
  ([#2226](https://github.com/joshua-jingu-lee/ante/pull/2226),
  [`b44b371`](https://github.com/joshua-jingu-lee/ante/commit/b44b371eea115f8e85e2de140c3fd94934cedba4))

- **strategy**: #2043 StrategyValidator가 비리터럴 최상위 assignment 실행식 차단
  ([#2217](https://github.com/joshua-jingu-lee/ante/pull/2217),
  [`b25c155`](https://github.com/joshua-jingu-lee/ante/commit/b25c15590f80b95814e9502b3a3de1e575ecb5fd))

- **strategy**: #2049 StrategyMeta.__hash__가 list 필드(symbols)를 tuple로 변환 — unhashable TypeError 수정
  ([#2238](https://github.com/joshua-jingu-lee/ante/pull/2238),
  [`f8afac8`](https://github.com/joshua-jingu-lee/ante/commit/f8afac8df35045ac2856bb9ebd849ccfb28b887b))

- **test**: #2277 wall-clock 의존 테스트 결정화 — orchestrator backfill cap 중립화 + fill KST 경계-안전 타임스탬프
  ([#2278](https://github.com/joshua-jingu-lee/ante/pull/2278),
  [`3a2b00b`](https://github.com/joshua-jingu-lee/ante/commit/3a2b00b3ad3896e05e42b3a9746e13d006d0ac28))

- **treasury**: #2128 allocate/deallocate IPC가 bot account_id mismatch를 차단 (broker.reconcile 선례 미러)
  ([#2264](https://github.com/joshua-jingu-lee/ante/pull/2264),
  [`339cf03`](https://github.com/joshua-jingu-lee/ante/commit/339cf03d2f06fde0f5284ad49256186e89416117))

### Chores

- **docs**: #2143 project-structure.md 재생성(test_bot_schema 추가 반영)
  ([#2190](https://github.com/joshua-jingu-lee/ante/pull/2190),
  [`67b750f`](https://github.com/joshua-jingu-lee/ante/commit/67b750fa24e7e4c89aac389cb80474bc80bb4fee))

### Code Style

- **feed**: #2020 instruments 테스트 docstring E501 wrap (lint)
  ([#2269](https://github.com/joshua-jingu-lee/ante/pull/2269),
  [`a7e9ec9`](https://github.com/joshua-jingu-lee/ante/commit/a7e9ec95000f9eb041cbefa885345823146e127a))

### Documentation

- Add module guide ([#1977](https://github.com/joshua-jingu-lee/ante/pull/1977),
  [`efdd9f5`](https://github.com/joshua-jingu-lee/ante/commit/efdd9f5148aceb90ebadb08aa5408881b0243665))

- README guide 문서 구조 보강 ([#1977](https://github.com/joshua-jingu-lee/ante/pull/1977),
  [`efdd9f5`](https://github.com/joshua-jingu-lee/ante/commit/efdd9f5148aceb90ebadb08aa5408881b0243665))

- README·guide 재구성 — 핵심 개념 문서와 에이전트 온램프(llms.txt) 추가
  ([#1977](https://github.com/joshua-jingu-lee/ante/pull/1977),
  [`efdd9f5`](https://github.com/joshua-jingu-lee/ante/commit/efdd9f5148aceb90ebadb08aa5408881b0243665))

- **approval**: #2151 알림 wiring을 현재 구조(ApprovalService가 NotificationEvent 직접 발행)에 맞게 3파일 갱신
  ([#2253](https://github.com/joshua-jingu-lee/ante/pull/2253),
  [`ab0bfd2`](https://github.com/joshua-jingu-lee/ante/commit/ab0bfd23505dace365287192e19bd2d4dd6849d1))

- **broker**: #2159 ReconcileScheduler 절을 실제 구현 계약에 맞게 갱신 (미구현 표기 제거,
  broker_account_id/skip_initial_external_buy/#1946 barrier 반영)
  ([#2249](https://github.com/joshua-jingu-lee/ante/pull/2249),
  [`5619690`](https://github.com/joshua-jingu-lee/ante/commit/561969092a3180b82e0db0f7673630e0c1caa95b))

- **broker-adapter**: #2316 fallback을 full-fill 정확매칭으로 협소화 + external 흡수 한계 정직 선언 (Codex 리뷰 반영)
  ([#2319](https://github.com/joshua-jingu-lee/ante/pull/2319),
  [`1834c3a`](https://github.com/joshua-jingu-lee/ante/commit/1834c3aad15f8b0906918ee2813d16215fb73220))

- **broker-adapter**: #2316 KIS 모의 당일 체결 position-derived bounded fallback 정의
  ([#2319](https://github.com/joshua-jingu-lee/ante/pull/2319),
  [`1834c3a`](https://github.com/joshua-jingu-lee/ante/commit/1834c3aad15f8b0906918ee2813d16215fb73220))

- **broker-adapter**: #2316 §11.6 제목 paper/live → 모의·실전 (용어 가드 #1232 준수)
  ([#2319](https://github.com/joshua-jingu-lee/ante/pull/2319),
  [`1834c3a`](https://github.com/joshua-jingu-lee/ante/commit/1834c3aad15f8b0906918ee2813d16215fb73220))

- **broker-adapter**: #2316 모의 당일 체결 position-derived bounded fallback 정의
  ([#2319](https://github.com/joshua-jingu-lee/ante/pull/2319),
  [`1834c3a`](https://github.com/joshua-jingu-lee/ante/commit/1834c3aad15f8b0906918ee2813d16215fb73220))

- **cli**: #2156 approval audit-types 분류표 줄에 --format 보강 (브랜치 리뷰 반영)
  ([#2247](https://github.com/joshua-jingu-lee/ante/pull/2247),
  [`1665b4a`](https://github.com/joshua-jingu-lee/ante/commit/1665b4a95df951a05645b5b2fd1795124fb4eb56))

- **cli**: #2156 CLI SSOT(03-commands.md) 명령 옵션을 실제 click 정의에 정렬 (data list/backtest run/strategy
  list/approval) (Closes #2157, #2160, #2161)
  ([#2247](https://github.com/joshua-jingu-lee/ante/pull/2247),
  [`1665b4a`](https://github.com/joshua-jingu-lee/ante/commit/1665b4a95df951a05645b5b2fd1795124fb4eb56))

- **cli**: #2156 분류표 줄 원복 — 옵션 보강은 canonical 상세 레퍼런스로 한정 (브랜치 리뷰 수렴)
  ([#2247](https://github.com/joshua-jingu-lee/ante/pull/2247),
  [`1665b4a`](https://github.com/joshua-jingu-lee/ante/commit/1665b4a95df951a05645b5b2fd1795124fb4eb56))

- **cli**: CLI SSOT(03-commands.md) 명령 옵션을 실제 click 정의에 정렬 (data list/backtest run/strategy
  list/approval) ([#2247](https://github.com/joshua-jingu-lee/ante/pull/2247),
  [`1665b4a`](https://github.com/joshua-jingu-lee/ante/commit/1665b4a95df951a05645b5b2fd1795124fb4eb56))

- **eventbus**: #1997 BacktestCompleteEvent.status 문서를 구현(completed)에 정렬
  ([#2210](https://github.com/joshua-jingu-lee/ante/pull/2210),
  [`c577573`](https://github.com/joshua-jingu-lee/ante/commit/c577573bb66b651ba4743b6f78a65fc2fdb2a190))

- **eventbus**: #2146 marker 분류 목록을 코드 _requires_account_id와 정합화 (취소실패/stop order 4건 대상 이동)
  ([#2163](https://github.com/joshua-jingu-lee/ante/pull/2163),
  [`0f49dd9`](https://github.com/joshua-jingu-lee/ante/commit/0f49dd9d8acf13ad90fb6a1b0b00ff31efb0f13c))

- **eventbus**: #2153 중앙 이벤트 표를 events.py dataclass에 정렬 — 필드 7행 drift + 누락
  3행(BotStepCompleted/SystemStarted/DailyReport) (Closes #2148, #2158)
  ([#2248](https://github.com/joshua-jingu-lee/ante/pull/2248),
  [`1451465`](https://github.com/joshua-jingu-lee/ante/commit/1451465e65cf5c1cea9dd0f3ddd3db6c0e730e05))

- **eventbus**: #2186 MemberRegistered/Reactivated 구독자 Notification→Audit (member/07 정합)
  ([#2313](https://github.com/joshua-jingu-lee/ante/pull/2313),
  [`f8d5e73`](https://github.com/joshua-jingu-lee/ante/commit/f8d5e73640522e4152b0928f700b4d9b10e48ae7))

- **eventbus**: #2252 중앙 표 구독자 열의 Notification semantic(domain-notified) 정의 추가
  ([#2254](https://github.com/joshua-jingu-lee/ante/pull/2254),
  [`6a03623`](https://github.com/joshua-jingu-lee/ante/commit/6a036239147a1b3e54456214bb6442d14638d5e2))

- **rule-engine**: #2152 RuleEngine 생성자 예시를 실제 시그니처(kw-only account_id 필수, require_account_id 검증)에
  정렬 ([#2250](https://github.com/joshua-jingu-lee/ante/pull/2250),
  [`69bab0a`](https://github.com/joshua-jingu-lee/ante/commit/69bab0a0da4f9c4b63204ef520d40d1b8b6f521c))

- **strategy**: #2016 StrategyValidator 스펙을 impl에 정렬 — open/globals/locals를 금지 내장함수(에러)로, open() 경고
  항목 제거 ([#2243](https://github.com/joshua-jingu-lee/ante/pull/2243),
  [`30b7eaf`](https://github.com/joshua-jingu-lee/ante/commit/30b7eaf8cd43e2f5cf944014857ec504bd416e1e))

- **strategy**: #2060 backtest --symbols/--timeframe 생략 시 StrategyMeta fallback 계약 명시
  ([#2255](https://github.com/joshua-jingu-lee/ante/pull/2255),
  [`97c868f`](https://github.com/joshua-jingu-lee/ante/commit/97c868f49fc6cb28896b8f4d0d172a8a722a7645))

- **strategy**: #2127 PortfolioView get_positions/get_balance를 모드별(backtest/live·virtual) 키로 명시
  (parity=#2272) ([#2273](https://github.com/joshua-jingu-lee/ante/pull/2273),
  [`b7818b4`](https://github.com/joshua-jingu-lee/ante/commit/b7818b455b9490410dbd5a8f99717669de694011))

- **trade**: #2149 skip_external_buy가 보정+불일치 이벤트 발행을 모두 억제함을 반영 (position-reconciler)
  ([#2251](https://github.com/joshua-jingu-lee/ante/pull/2251),
  [`1c52388`](https://github.com/joshua-jingu-lee/ante/commit/1c52388a32426334064f6a8b71f9c81fd41bc1d3))

### Refactoring

- **member**: #2294 register 무조건 master 게이트 + #2295 recovery sentinel 비충돌 reserved guard
  ([#2308](https://github.com/joshua-jingu-lee/ante/pull/2308),
  [`c0c1f90`](https://github.com/joshua-jingu-lee/ante/commit/c0c1f9026e128a331d6d7068b7d7004438eb62b5))

### Testing

- #1980 asyncio.run mock이 coroutine을 close하지 않아 발생하는 never-awaited 경고 제거
  ([#2303](https://github.com/joshua-jingu-lee/ante/pull/2303),
  [`e1f30be`](https://github.com/joshua-jingu-lee/ante/commit/e1f30be7764a95fd5ed264c7e246fc6d5c0a2757))

- Preserve cli module guide notice ([#1977](https://github.com/joshua-jingu-lee/ante/pull/1977),
  [`efdd9f5`](https://github.com/joshua-jingu-lee/ante/commit/efdd9f5148aceb90ebadb08aa5408881b0243665))

- TestBacktestHistoryRealAuthReadOnlyFilesystem 추가. authenticate_member를
  ([#1979](https://github.com/joshua-jingu-lee/ante/pull/1979),
  [`3c93086`](https://github.com/joshua-jingu-lee/ante/commit/3c93086d157d11ae47f154121c97e856c553e241))

- **backtest**: #1989 oversell 슬리피지 체결수량 회귀를 nonzero slippage로 강화
  ([#2170](https://github.com/joshua-jingu-lee/ante/pull/2170),
  [`8106682`](https://github.com/joshua-jingu-lee/ante/commit/810668252bae4630a99d4de4086000fec6cf6059))

- **backtest**: #1994 order_type 게이트 buy/sell×타입×cap 전 매트릭스 커버(market sell 회귀·stop_limit sell cap
  포함) ([#2228](https://github.com/joshua-jingu-lee/ante/pull/2228),
  [`493aa63`](https://github.com/joshua-jingu-lee/ante/commit/493aa637947f3c0bf35373f30b77869b1ae49344))

- **backtest**: #1994 stop_limit sell + sell-side slippage cap 테스트 보강
  ([#2228](https://github.com/joshua-jingu-lee/ante/pull/2228),
  [`493aa63`](https://github.com/joshua-jingu-lee/ante/commit/493aa637947f3c0bf35373f30b77869b1ae49344))

- **backtest**: #2060 factory_drift allowlist backtest.py Database 행번호 갱신 (라인 shift 반영)
  ([#2255](https://github.com/joshua-jingu-lee/ante/pull/2255),
  [`97c868f`](https://github.com/joshua-jingu-lee/ante/commit/97c868f49fc6cb28896b8f4d0d172a8a722a7645))

- **cli**: #1974 backtest history 실제 read-only fs e2e(비-mock auth) + §4 경계 문서화
  ([#1979](https://github.com/joshua-jingu-lee/ante/pull/1979),
  [`3c93086`](https://github.com/joshua-jingu-lee/ante/commit/3c93086d157d11ae47f154121c97e856c553e241))

- **cli**: #1980 asyncio.run mock이 inline coroutine을 미소비해 발생하는 never-awaited 경고 제거
  ([#2303](https://github.com/joshua-jingu-lee/ante/pull/2303),
  [`e1f30be`](https://github.com/joshua-jingu-lee/ante/commit/e1f30be7764a95fd5ed264c7e246fc6d5c0a2757))

- **cli**: #1980 asyncio_run_returning helper가 positional+keyword 모든 coroutine을 close
  ([#2303](https://github.com/joshua-jingu-lee/ante/pull/2303),
  [`e1f30be`](https://github.com/joshua-jingu-lee/ante/commit/e1f30be7764a95fd5ed264c7e246fc6d5c0a2757))

- **cli**: #2309 bot remove flaky 결정화 — is_active_runtime mock + conftest gc.collect 제거
  ([#2310](https://github.com/joshua-jingu-lee/ante/pull/2310),
  [`c3d0a05`](https://github.com/joshua-jingu-lee/ante/commit/c3d0a05bd7b47ee5ad4dba065c14990fb51ce10b))

- **ipc**: #2304 IPC transport teardown cross-test 오염 제거 (flaky CI 안정화)
  ([#2307](https://github.com/joshua-jingu-lee/ante/pull/2307),
  [`e182b78`](https://github.com/joshua-jingu-lee/ante/commit/e182b78c8b6634e2e8d763e3405e05495c3f199f))

- **ipc**: #2304 IPC transport teardown 누수로 인한 flaky CI 안정화
  ([#2307](https://github.com/joshua-jingu-lee/ante/pull/2307),
  [`e182b78`](https://github.com/joshua-jingu-lee/ante/commit/e182b78c8b6634e2e8d763e3405e05495c3f199f))

- **ipc**: #2304 leak-source 캡처 assert 보강 (빈 캡처 silent-pass 차단)
  ([#2307](https://github.com/joshua-jingu-lee/ante/pull/2307),
  [`e182b78`](https://github.com/joshua-jingu-lee/ante/commit/e182b78c8b6634e2e8d763e3405e05495c3f199f))

- **member**: #2294 #2295 reserved-guard ordering·빈 actor 테스트 충실성 보강
  ([#2308](https://github.com/joshua-jingu-lee/ante/pull/2308),
  [`c0c1f90`](https://github.com/joshua-jingu-lee/ante/commit/c0c1f9026e128a331d6d7068b7d7004438eb62b5))


## v0.10.0 (2026-05-29)

### Bug Fixes

- #1673 config set invalid log_level을 CONFIG_VALIDATION_ERROR JSON envelope로 정리
  ([#1683](https://github.com/joshua-jingu-lee/ante/pull/1683),
  [`7d14ac5`](https://github.com/joshua-jingu-lee/ante/commit/7d14ac518922c4e956c629b2d176e82f2d6c65f3))

- #1674 feed backfill_since 4-surface clean-reject coded {CLI_INVALID_DATE, INVALID_DATE_RANGE}
  ([#1692](https://github.com/joshua-jingu-lee/ante/pull/1692),
  [`45075c5`](https://github.com/joshua-jingu-lee/ante/commit/45075c54dbd8c6d3b53b7a40555fb74c8085dd5b))

- #1675 StrategyValidator source-read + AST-parse 단계 4클래스 content-free 정규화 (bounded B)
  ([#1693](https://github.com/joshua-jingu-lee/ante/pull/1693),
  [`ff1be4c`](https://github.com/joshua-jingu-lee/ante/commit/ff1be4c5de79d4ac20496daca5b6694e0b945777))

- #1676 cursor decode invalid 입력을 안정 'invalid cursor' 400으로 정규화 (strict+canonical, no-reflection)
  ([#1684](https://github.com/joshua-jingu-lee/ante/pull/1684),
  [`f99598b`](https://github.com/joshua-jingu-lee/ante/commit/f99598bb58162c7cbad5659c48c1952ccb0977fe))

- #1681 OpenAPI auto-422를 runtime problem+json+ErrorResponse로 정렬 (normalizer 수렴점 + 07-error-format
  invariant + frontend 동기) ([#1688](https://github.com/joshua-jingu-lee/ante/pull/1688),
  [`1f3c78b`](https://github.com/joshua-jingu-lee/ante/commit/1f3c78b00474e678afd93ffd4217d6451b0bbf92))

- #1682 빈 notification 그룹을 root help·guide/cli.md 양 표면에서 숨김 (hidden=True + _collect_commands
  hidden-skip + 재생성) ([#1689](https://github.com/joshua-jingu-lee/ante/pull/1689),
  [`efa57fb`](https://github.com/joshua-jingu-lee/ante/commit/efa57fb6b68e19ad4c6b447506daef9d81310401))

- #1690 feed backfill --until ghost option 제거 + guide/cli.md 재생성
  ([#1694](https://github.com/joshua-jingu-lee/ante/pull/1694),
  [`f9c88f3`](https://github.com/joshua-jingu-lee/ante/commit/f9c88f3b21f1722a64a81930055a33d1c23ccdb6))

- #1696 CLI reference usage line에 required option 인라인 표시 (generator dual-fix)
  ([#1706](https://github.com/joshua-jingu-lee/ante/pull/1706),
  [`4b82bc3`](https://github.com/joshua-jingu-lee/ante/commit/4b82bc3097c577da206d9fbd33d2c949788ce812))

- #1701 report schema/data list/bot list/member info에 @format_option decorator 추가
  ([#1709](https://github.com/joshua-jingu-lee/ante/pull/1709),
  [`601c4f3`](https://github.com/joshua-jingu-lee/ante/commit/601c4f3293488dfece10a66af14172bffea4ed4a))

- #1705 signal connect 4 validation 오류를 JSON envelope으로 normalize (_fail helper + @format_option)
  ([#1710](https://github.com/joshua-jingu-lee/ante/pull/1710),
  [`945971c`](https://github.com/joshua-jingu-lee/ante/commit/945971c90ad7af5f11277cbd707a8cff0b3ac699))

- #1719 remove dashboard/Web API surface from Dockerfile and verify-install
  ([#1720](https://github.com/joshua-jingu-lee/ante/pull/1720),
  [`b1f1e7a`](https://github.com/joshua-jingu-lee/ante/commit/b1f1e7a4402708433f6d428093c8541c3d99f6e8))

- #1721 ante init이 ANTE_DB_ENCRYPTION_KEY를 생성·persist + Config.load env export
  ([#1731](https://github.com/joshua-jingu-lee/ante/pull/1731),
  [`2d1bc2b`](https://github.com/joshua-jingu-lee/ante/commit/2d1bc2b5f37420610fc7d2af6dc9486c66048164))

- #1722 account CLI crypto error → exit 1 + stable code, no aiosqlite hang
  ([#1732](https://github.com/joshua-jingu-lee/ante/pull/1732),
  [`c56a7db`](https://github.com/joshua-jingu-lee/ante/commit/c56a7db3bc6929aa70ec65ea60bdb5842dc883d4))

- #1723 account create reserve buffer가 inf/nan/negative을 거부하도록 SSOT validator 적용
  ([#1733](https://github.com/joshua-jingu-lee/ante/pull/1733),
  [`8c2ec9b`](https://github.com/joshua-jingu-lee/ante/commit/8c2ec9b71efe123c7cc9cd5dbb0eb9c50ded6d7a))

- #1724 cold-path account 4 명령에 invalid account_id ingress validation
  ([#1734](https://github.com/joshua-jingu-lee/ante/pull/1734),
  [`320bc2a`](https://github.com/joshua-jingu-lee/ante/commit/320bc2a92110e0528dd3850d4830efa6b4416ab1))

- #1724 cold-path account 4 명령에 invalid account_id ingress validation 추가
  ([#1734](https://github.com/joshua-jingu-lee/ante/pull/1734),
  [`320bc2a`](https://github.com/joshua-jingu-lee/ante/commit/320bc2a92110e0528dd3850d4830efa6b4416ab1))

- #1725 treasury status/snapshot이 valid-but-missing account_id에 ACCOUNT_NOT_FOUND 반환 + hang 차단
  ([#1735](https://github.com/joshua-jingu-lee/ante/pull/1735),
  [`1111e20`](https://github.com/joshua-jingu-lee/ante/commit/1111e2070cd2a75618c5b447232b6dccdc5279b6))

- #1726 _create_rule_engine cleanup이 db.connect() 자체를 감싸도록 정렬
  ([#1736](https://github.com/joshua-jingu-lee/ante/pull/1736),
  [`2ad7433`](https://github.com/joshua-jingu-lee/ante/commit/2ad743328658e21b5e81b9fdad1b3bc9ffc3e804))

- #1726 rule info가 valid-but-missing account_id에 ACCOUNT_NOT_FOUND 우선 반환
  ([#1736](https://github.com/joshua-jingu-lee/ante/pull/1736),
  [`2ad7433`](https://github.com/joshua-jingu-lee/ante/commit/2ad743328658e21b5e81b9fdad1b3bc9ffc3e804))

- #1726 rule info가 valid-but-missing account_id에 ACCOUNT_NOT_FOUND 우선 반환 + SSOT consolidation
  ([#1736](https://github.com/joshua-jingu-lee/ante/pull/1736),
  [`2ad7433`](https://github.com/joshua-jingu-lee/ante/commit/2ad743328658e21b5e81b9fdad1b3bc9ffc3e804))

- #1727 broker balance/positions가 valid-but-missing account_id에 ACCOUNT_NOT_FOUND 반환
  ([#1737](https://github.com/joshua-jingu-lee/ante/pull/1737),
  [`db43c04`](https://github.com/joshua-jingu-lee/ante/commit/db43c04403030d4afb841eb0e591be3d69b5ef84))

- #1730 D-018 후 init/config의 [web] 섹션 제거 (web surface stale config sweep)
  ([#1740](https://github.com/joshua-jingu-lee/ante/pull/1740),
  [`6ffb6a8`](https://github.com/joshua-jingu-lee/ante/commit/6ffb6a8c9fc59956647bd53ddbf1a2f671721d62))

- #1752 backtest run --format json이 단일 JSON document만 출력하도록 분기
  ([#1762](https://github.com/joshua-jingu-lee/ante/pull/1762),
  [`eed2a14`](https://github.com/joshua-jingu-lee/ante/commit/eed2a14a8b1cc135d4a2a1ae27d4c6f6f098e88a))

- #1753 fresh init 후 strategy/trade 조회 CLI public read contract 정합
  ([#1763](https://github.com/joshua-jingu-lee/ante/pull/1763),
  [`e0389a9`](https://github.com/joshua-jingu-lee/ante/commit/e0389a9d82a71be348244ebc115a0e08704f28ae))

- #1754 IPC ClickException 경로를 --format json envelope으로 변환
  ([#1764](https://github.com/joshua-jingu-lee/ante/pull/1764),
  [`1196f0a`](https://github.com/joshua-jingu-lee/ante/commit/1196f0a35536345f074fd20372b33b85813db0d3))

- #1755 report/approval CLI db cleanup으로 stderr traceback과 hang 차단
  ([#1765](https://github.com/joshua-jingu-lee/ante/pull/1765),
  [`dab8580`](https://github.com/joshua-jingu-lee/ante/commit/dab85802715dcb21c2ca7a5960547b641b776421))

- #1756 strategy submit meta shape ingress validation
  ([#1766](https://github.com/joshua-jingu-lee/ante/pull/1766),
  [`d18cb9a`](https://github.com/joshua-jingu-lee/ante/commit/d18cb9a7144a3d4e00faea8144578da7b4442278))

- #1757 system start --format json 자식 stdout 격리
  ([#1767](https://github.com/joshua-jingu-lee/ante/pull/1767),
  [`2591083`](https://github.com/joshua-jingu-lee/ante/commit/25910838a8f43557e9bcc6d9f01a0c6ab0f199e1))

- #1758 treasury read 계열 valid-but-missing account_id ACCOUNT_NOT_FOUND 매핑
  ([#1768](https://github.com/joshua-jingu-lee/ante/pull/1768),
  [`b9da81f`](https://github.com/joshua-jingu-lee/ante/commit/b9da81fda82b025bc554aa3cac86eeb038253d55))

- #1759 BotManager start_bot/stop_bot strict state machine + BOT_STATE_CONFLICT
  ([#1769](https://github.com/joshua-jingu-lee/ante/pull/1769),
  [`69b5973`](https://github.com/joshua-jingu-lee/ante/commit/69b5973a186c9a0a0d8d0de59f26920653c7ff22))

- #1760 server-side BotManager에 SignalKeyManager 주입
  ([#1771](https://github.com/joshua-jingu-lee/ante/pull/1771),
  [`42f451e`](https://github.com/joshua-jingu-lee/ante/commit/42f451ef0e1e419c4373a291cf90fa770846b7da))

- #1761 bot signal-key --rotate에 accepts_external_signals 게이트
  ([#1772](https://github.com/joshua-jingu-lee/ante/pull/1772),
  [`4fc278a`](https://github.com/joshua-jingu-lee/ante/commit/4fc278a3bb9848739f7516c73d0f0de8f01c4785))

- #1773-#1782 CLI 에러코드 명명 규칙 sweep (10 commands)
  ([#1783](https://github.com/joshua-jingu-lee/ante/pull/1783),
  [`58bc07a`](https://github.com/joshua-jingu-lee/ante/commit/58bc07a08d2de9a42060c927c71082699189bc88))

- #1784,#1789,#1795-#1798,#1800 Group A typed code + envelope sweep (7 issues)
  ([#1801](https://github.com/joshua-jingu-lee/ante/pull/1801),
  [`dca3d8d`](https://github.com/joshua-jingu-lee/ante/commit/dca3d8de7e3964e806e0eee7908742ee81f10fd7))

- #1792 treasury allocate/deallocate에 bot 존재 검증 추가
  ([#1803](https://github.com/joshua-jingu-lee/ante/pull/1803),
  [`74cb69b`](https://github.com/joshua-jingu-lee/ante/commit/74cb69b02101a4eae8cad43a275e2f6a2171a4a0))

- #1794 approval CLI args key mismatch (approval_id → id)
  ([#1802](https://github.com/joshua-jingu-lee/ante/pull/1802),
  [`254bfc5`](https://github.com/joshua-jingu-lee/ante/commit/254bfc554146c408c9c8f44eb39e70c697675384))

- #1799 bot create cleanup leaked aiosqlite (active account 0/2+ hang)
  ([#1804](https://github.com/joshua-jingu-lee/ante/pull/1804),
  [`a5d8edf`](https://github.com/joshua-jingu-lee/ante/commit/a5d8edf77cdbd1235089fa4de6acede7f831e9da))

- #1805/#1808/#1810/#1811 Group P missing-resource typed code sweep (4 issues)
  ([#1817](https://github.com/joshua-jingu-lee/ante/pull/1817),
  [`cb48603`](https://github.com/joshua-jingu-lee/ante/commit/cb48603c7604763a22f747f415f12b494db57e68))

- #1806/#1807 Group R member duplicate+validation typed code sweep (2 issues)
  ([#1826](https://github.com/joshua-jingu-lee/ante/pull/1826),
  [`bb9e594`](https://github.com/joshua-jingu-lee/ante/commit/bb9e5947e900bcbc6521751815b483b7262f4670))

- #1809 Group S treasury allocate/deallocate typed reject exception (contract change)
  ([#1828](https://github.com/joshua-jingu-lee/ante/pull/1828),
  [`eb15e6a`](https://github.com/joshua-jingu-lee/ante/commit/eb15e6a29b2fce62de6b0a35e78e6f328dc7b484))

- #1812/#1813/#1814 Group Q state-conflict typed code sweep (3 issues)
  ([#1825](https://github.com/joshua-jingu-lee/ante/pull/1825),
  [`adf8319`](https://github.com/joshua-jingu-lee/ante/commit/adf83197ed209663de7e9e768801af349b111854))

- - src/ante/report/models.py: __post_init__ 제거,
  ([#1445](https://github.com/joshua-jingu-lee/ante/pull/1445),
  [`64ab2e7`](https://github.com/joshua-jingu-lee/ante/commit/64ab2e730e2160fb033152b0ec34c76036109dcc))

- Add pyyaml to dev dependencies (CI test fix for #1841 drift allowlist loader)
  ([#1864](https://github.com/joshua-jingu-lee/ante/pull/1864),
  [`95cc2e0`](https://github.com/joshua-jingu-lee/ante/commit/95cc2e0454fd79a3f34764a81d1acbc75204eb86))

- Load import guard by path in pytest ([#1290](https://github.com/joshua-jingu-lee/ante/pull/1290),
  [`01eeb7d`](https://github.com/joshua-jingu-lee/ante/commit/01eeb7d4d33cd0cf28f0ad03cedb40f2d3b0eb09))

- **account**: Allow empty default in POST trading_hours pattern
  ([#1344](https://github.com/joshua-jingu-lee/ante/pull/1344),
  [`1dd1cda`](https://github.com/joshua-jingu-lee/ante/commit/1dd1cdacf78e408fff06431a6418e157db1a9064))

- **account**: Allow market_order_reserve_buffer_rate in cold-path update (#1333 P2)
  ([#1350](https://github.com/joshua-jingu-lee/ante/pull/1350),
  [`563df47`](https://github.com/joshua-jingu-lee/ante/commit/563df4742324680ade2126daf6aa4c7b5bb466f5))

- **account**: Expose InvalidAccountIdError as VALIDATION_ERROR through IPC dispatch
  ([#1246](https://github.com/joshua-jingu-lee/ante/pull/1246),
  [`45ae880`](https://github.com/joshua-jingu-lee/ante/commit/45ae880d92861fcc85c2801be4dcdec2387a7fa5))

- **account**: Include multi-step deletion procedure in AccountHasActiveBotsError message
  ([#1162](https://github.com/joshua-jingu-lee/ante/pull/1162),
  [`77beea8`](https://github.com/joshua-jingu-lee/ante/commit/77beea89d52837f64cd6a25e1aaaa3e12b4d3db1))

- **account**: Resolve mypy shadow on AccountService.list return types
  ([#1248](https://github.com/joshua-jingu-lee/ante/pull/1248),
  [`9623aad`](https://github.com/joshua-jingu-lee/ante/commit/9623aad4b8f43bcfbc9365d199a1d6bedf099324))

- **account**: Validate canonical exchange in service + align OpenAPI enum (#1583)
  ([#1586](https://github.com/joshua-jingu-lee/ante/pull/1586),
  [`6e286b4`](https://github.com/joshua-jingu-lee/ante/commit/6e286b4918d74ebe0b12c967e5cf375f2f6b9846))

- **account**: Validate trading_hours_start/end as strict HH:MM
  ([#1344](https://github.com/joshua-jingu-lee/ante/pull/1344),
  [`1dd1cda`](https://github.com/joshua-jingu-lee/ante/commit/1dd1cdacf78e408fff06431a6418e157db1a9064))

- **account**: Validate trading_hours_start/end as strict HH:MM (#1334)
  ([#1344](https://github.com/joshua-jingu-lee/ante/pull/1344),
  [`1dd1cda`](https://github.com/joshua-jingu-lee/ante/commit/1dd1cdacf78e408fff06431a6418e157db1a9064))

- **account,cli,ipc**: Align account cold-path with 1.0 single-active-runtime policy
  ([#1162](https://github.com/joshua-jingu-lee/ante/pull/1162),
  [`77beea8`](https://github.com/joshua-jingu-lee/ante/commit/77beea89d52837f64cd6a25e1aaaa3e12b4d3db1))

- **account,cli,ipc**: Align account cold-path with 1.0 single-active-runtime policy (#1139)
  ([#1162](https://github.com/joshua-jingu-lee/ante/pull/1162),
  [`77beea8`](https://github.com/joshua-jingu-lee/ante/commit/77beea89d52837f64cd6a25e1aaaa3e12b4d3db1))

- **account,web**: Align PUT /api/accounts request body schema and add Content-Type 415 gate (#1153)
  ([#1166](https://github.com/joshua-jingu-lee/ante/pull/1166),
  [`e901d97`](https://github.com/joshua-jingu-lee/ante/commit/e901d97842cd9de0cca63e194c90dd8153aeab3f))

- **account,web**: Block runtime structural mutations with cold-path 409
  ([#1146](https://github.com/joshua-jingu-lee/ante/pull/1146),
  [`57780c2`](https://github.com/joshua-jingu-lee/ante/commit/57780c2882e197e8ce139140bb355b8a0049bc3f))

- **account,web**: Expose POST /api/accounts request body OpenAPI schema (#1143)
  ([#1155](https://github.com/joshua-jingu-lee/ante/pull/1155),
  [`91de6fa`](https://github.com/joshua-jingu-lee/ante/commit/91de6fa9c502fd1288863a2f397a7191a30a0bba))

- **account,web-api**: Enforce IANA timezone on PUT ingress + service boundary (#1473)
  ([#1483](https://github.com/joshua-jingu-lee/ante/pull/1483),
  [`4cb273c`](https://github.com/joshua-jingu-lee/ante/commit/4cb273cd5d64d4c1234ebcff72d8c0070ebfe9f0))

- **api,cli**: Enforce schema-required fields at report submit boundary (#1625)
  ([#1638](https://github.com/joshua-jingu-lee/ante/pull/1638),
  [`25b3ead`](https://github.com/joshua-jingu-lee/ante/commit/25b3ead30d0eee6e7da18aecbc5bb50fed42ed30))

- **api,cli**: Exit/404 on strategy performance for missing account
  ([#1572](https://github.com/joshua-jingu-lee/ante/pull/1572),
  [`c690fde`](https://github.com/joshua-jingu-lee/ante/commit/c690fdee46d767e1ffba68c272f29d58970741e8))

- **api,cli**: Exit/404 on strategy performance for missing account (#1563)
  ([#1572](https://github.com/joshua-jingu-lee/ante/pull/1572),
  [`c690fde`](https://github.com/joshua-jingu-lee/ante/commit/c690fdee46d767e1ffba68c272f29d58970741e8))

- **approval**: Block legacy invalid approval type approve + executor missing as EXECUTION_FAILED
  (#1470) ([#1486](https://github.com/joshua-jingu-lee/ante/pull/1486),
  [`199b9bc`](https://github.com/joshua-jingu-lee/ante/commit/199b9bcf19955ffb8e37891bef9d6afbca9353d5))

- **audit**: Allow human members to read audit logs without scope
  ([#1369](https://github.com/joshua-jingu-lee/ante/pull/1369),
  [`b81a785`](https://github.com/joshua-jingu-lee/ante/commit/b81a7859d9fff59e7fa970c76dcdecead0f41872))

- **audit**: Allow members with audit:read scope to read audit logs
  ([#1369](https://github.com/joshua-jingu-lee/ante/pull/1369),
  [`b81a785`](https://github.com/joshua-jingu-lee/ante/commit/b81a7859d9fff59e7fa970c76dcdecead0f41872))

- **audit**: Normalize compact/week ISO date to YYYY-MM-DD (codex FAIL r3)
  ([#1444](https://github.com/joshua-jingu-lee/ante/pull/1444),
  [`f2dae4f`](https://github.com/joshua-jingu-lee/ante/commit/f2dae4f4b5b8d5d2742c988185db17f557340976))

- **audit**: Normalize Z/offset datetime to storage format (codex FAIL r2)
  ([#1444](https://github.com/joshua-jingu-lee/ante/pull/1444),
  [`f2dae4f`](https://github.com/joshua-jingu-lee/ante/commit/f2dae4f4b5b8d5d2742c988185db17f557340976))

- **audit**: Order auth dependency before audit_logger to enforce 401 over 503
  ([#1369](https://github.com/joshua-jingu-lee/ante/pull/1369),
  [`b81a785`](https://github.com/joshua-jingu-lee/ante/commit/b81a7859d9fff59e7fa970c76dcdecead0f41872))

- **audit**: Preserve date-only semantic in audit query (codex FAIL r1)
  ([#1444](https://github.com/joshua-jingu-lee/ante/pull/1444),
  [`f2dae4f`](https://github.com/joshua-jingu-lee/ante/commit/f2dae4f4b5b8d5d2742c988185db17f557340976))

- **audit**: Reject suspended/revoked members from audit read
  ([#1369](https://github.com/joshua-jingu-lee/ante/pull/1369),
  [`b81a785`](https://github.com/joshua-jingu-lee/ante/commit/b81a7859d9fff59e7fa970c76dcdecead0f41872))

- **audit**: Require authenticated audit:read for /api/audit (#1359)
  ([#1369](https://github.com/joshua-jingu-lee/ante/pull/1369),
  [`b81a785`](https://github.com/joshua-jingu-lee/ante/commit/b81a7859d9fff59e7fa970c76dcdecead0f41872))

- **backtest**: Programmatic config symbol/timeframe vocabulary 검증 (#1604)
  ([#1618](https://github.com/joshua-jingu-lee/ante/pull/1618),
  [`063fe54`](https://github.com/joshua-jingu-lee/ante/commit/063fe54b7dd7f75a81afc4a6127a8c88dcff5c88))

- **bot**: #1901 SignalKeyManager.rotate partial-failure rollback 가드 (defense-in-depth)
  ([#1907](https://github.com/joshua-jingu-lee/ante/pull/1907),
  [`e4a099d`](https://github.com/joshua-jingu-lee/ante/commit/e4a099d97347ea79935c6fc7c18ee81d8bb22799))

- **bot**: Atomic rollback for BotConfig on budget failure in update_bot
  ([#1506](https://github.com/joshua-jingu-lee/ante/pull/1506),
  [`c1a5d71`](https://github.com/joshua-jingu-lee/ante/commit/c1a5d7177dbe56a34122b96832962c3ab2bdb8f0))

- **bot**: Conditional rollback to avoid concurrent update_bot race
  ([#1506](https://github.com/joshua-jingu-lee/ante/pull/1506),
  [`c1a5d71`](https://github.com/joshua-jingu-lee/ante/commit/c1a5d7177dbe56a34122b96832962c3ab2bdb8f0))

- **bot**: Hard-delete bot row on create rollback
  ([#1345](https://github.com/joshua-jingu-lee/ante/pull/1345),
  [`016a328`](https://github.com/joshua-jingu-lee/ante/commit/016a3285cb2900a83636eaf6397040b841f4bf6a))

- **bot**: Make update_bot budget failure atomic — rollback runtime control changes
  ([#1506](https://github.com/joshua-jingu-lee/ante/pull/1506),
  [`c1a5d71`](https://github.com/joshua-jingu-lee/ante/commit/c1a5d7177dbe56a34122b96832962c3ab2bdb8f0))

- **bot**: Map create budget failure to 422 with hard rollback (#1335)
  ([#1345](https://github.com/joshua-jingu-lee/ante/pull/1345),
  [`016a328`](https://github.com/joshua-jingu-lee/ante/commit/016a3285cb2900a83636eaf6397040b841f4bf6a))

- **bot**: Mirror BotConfig invariants at create_bot service boundary
  ([#1508](https://github.com/joshua-jingu-lee/ante/pull/1508),
  [`c2b89c4`](https://github.com/joshua-jingu-lee/ante/commit/c2b89c4741812c32df7d1dde230e888890ffde85))

- **bot**: Persist runtime controls + auto_restart across BotConfig DB roundtrip
  ([#1500](https://github.com/joshua-jingu-lee/ante/pull/1500),
  [`026a8c4`](https://github.com/joshua-jingu-lee/ante/commit/026a8c4a4087da84b0ed245e8f15fbe7258aaff3))

- **bot**: Serialize update_bot per-bot to prevent concurrent atomicity race
  ([#1506](https://github.com/joshua-jingu-lee/ante/pull/1506),
  [`c1a5d71`](https://github.com/joshua-jingu-lee/ante/commit/c1a5d7177dbe56a34122b96832962c3ab2bdb8f0))

- **bot**: Skip update_bot rollback DB save on delete/recreate race
  ([#1506](https://github.com/joshua-jingu-lee/ante/pull/1506),
  [`c1a5d71`](https://github.com/joshua-jingu-lee/ante/commit/c1a5d7177dbe56a34122b96832962c3ab2bdb8f0))

- **bot**: Skip update_bot rollback on in-place BotConfig mutation
  ([#1506](https://github.com/joshua-jingu-lee/ante/pull/1506),
  [`c1a5d71`](https://github.com/joshua-jingu-lee/ante/commit/c1a5d7177dbe56a34122b96832962c3ab2bdb8f0))

- **bot**: Skip virtual fill for stop/stop_limit OrderApprovedEvent
  ([#1348](https://github.com/joshua-jingu-lee/ante/pull/1348),
  [`ce0efab`](https://github.com/joshua-jingu-lee/ante/commit/ce0efab8cc58277b3323d1560ba8f8ef87ccd8ed))

- **bot**: Support cold-path remove ([#1196](https://github.com/joshua-jingu-lee/ante/pull/1196),
  [`d563f0a`](https://github.com/joshua-jingu-lee/ante/commit/d563f0a00ed9615131c356e9e3b7ab55fa6032ea))

- **broker**: #1951 KIS 40240000 매도가능잔고 없음 PERMANENT 분류
  ([#1955](https://github.com/joshua-jingu-lee/ante/pull/1955),
  [`4c4059c`](https://github.com/joshua-jingu-lee/ante/commit/4c4059cb2879477227f71bbf77fe1b56d970012a))

- **broker**: Classify KIS 40570000 (장시작전) as permanent (#1317)
  ([#1327](https://github.com/joshua-jingu-lee/ante/pull/1327),
  [`a86fa12`](https://github.com/joshua-jingu-lee/ante/commit/a86fa1277180a99e8843d9d2b63f1612baf3be57))

- **broker**: Preserve KIS msg_cd on HTTP 5xx wrapped business errors (#1338)
  ([#1347](https://github.com/joshua-jingu-lee/ante/pull/1347),
  [`9035986`](https://github.com/joshua-jingu-lee/ante/commit/9035986d3554e4c150e6134ac3a1e88ad7b6f076))

- **broker**: Scope reconcile scheduler to its broker account (#1240 review)
  ([#1243](https://github.com/joshua-jingu-lee/ante/pull/1243),
  [`83dcd3b`](https://github.com/joshua-jingu-lee/ante/commit/83dcd3b206acade00a7abfd8eb285f0036def1af))

- **broker,ipc,trade**: Account-scope reconcile and skip-aware pagination (#1240 review)
  ([#1243](https://github.com/joshua-jingu-lee/ante/pull/1243),
  [`83dcd3b`](https://github.com/joshua-jingu-lee/ante/commit/83dcd3b206acade00a7abfd8eb285f0036def1af))

- **ci**: Restore ruff import order ([#1150](https://github.com/joshua-jingu-lee/ante/pull/1150),
  [`2e2dd3f`](https://github.com/joshua-jingu-lee/ante/commit/2e2dd3fcca018370d8ea5434f5804efac4454978))

- **ci**: Restore ruff lint pass ([#1150](https://github.com/joshua-jingu-lee/ante/pull/1150),
  [`2e2dd3f`](https://github.com/joshua-jingu-lee/ante/commit/2e2dd3fcca018370d8ea5434f5804efac4454978))

- **ci**: Satisfy ruff format check ([#1150](https://github.com/joshua-jingu-lee/ante/pull/1150),
  [`2e2dd3f`](https://github.com/joshua-jingu-lee/ante/commit/2e2dd3fcca018370d8ea5434f5804efac4454978))

- **ci**: Support latest click typing ([#1150](https://github.com/joshua-jingu-lee/ante/pull/1150),
  [`2e2dd3f`](https://github.com/joshua-jingu-lee/ante/commit/2e2dd3fcca018370d8ea5434f5804efac4454978))

- **ci**: Wrap notification warning log
  ([#1150](https://github.com/joshua-jingu-lee/ante/pull/1150),
  [`2e2dd3f`](https://github.com/joshua-jingu-lee/ante/commit/2e2dd3fcca018370d8ea5434f5804efac4454978))

- **cli**: #1657 strategy performance invalid account_id를 VALIDATION_ERROR로 거부 (read-family
  follow-up) ([#1667](https://github.com/joshua-jingu-lee/ante/pull/1667),
  [`942cbc0`](https://github.com/joshua-jingu-lee/ante/commit/942cbc052a92ddbf02216e9e58c482e174feb576))

- **cli**: #1900 _create_services mock anti-pattern 일괄 정리 (10 factory + helper + advisory scanner)
  ([#1903](https://github.com/joshua-jingu-lee/ante/pull/1903),
  [`c43fccf`](https://github.com/joshua-jingu-lee/ante/commit/c43fccfbb8b405cffdd5313429ad182a4abf7ded))

- **cli**: #1900 _create_services mock anti-pattern 일괄 정리 (10 factory + helper + AST scanner)
  ([#1903](https://github.com/joshua-jingu-lee/ante/pull/1903),
  [`c43fccf`](https://github.com/joshua-jingu-lee/ante/commit/c43fccfbb8b405cffdd5313429ad182a4abf7ded))

- **cli**: #1900 helper ctx 시그니처 production 정합 + scanner decorator 형태 검사 (codex review attempt 2
  finding 2건) ([#1903](https://github.com/joshua-jingu-lee/ante/pull/1903),
  [`c43fccf`](https://github.com/joshua-jingu-lee/ante/commit/c43fccfbb8b405cffdd5313429ad182a4abf7ded))

- **cli**: #1900 scanner advisory mode 격하 + false positive 2건 fix (codex review attempt 6 finding,
  final) ([#1903](https://github.com/joshua-jingu-lee/ante/pull/1903),
  [`c43fccf`](https://github.com/joshua-jingu-lee/ante/commit/c43fccfbb8b405cffdd5313429ad182a4abf7ded))

- **cli**: #1900 scanner decorator-injected mock body assignment + KNOWN-LIMITATION 섹션 (codex review
  attempt 3 finding 1건, bounded-scope) ([#1903](https://github.com/joshua-jingu-lee/ante/pull/1903),
  [`c43fccf`](https://github.com/joshua-jingu-lee/ante/commit/c43fccfbb8b405cffdd5313429ad182a4abf7ded))

- **cli**: #1900 scanner new_callable variants + decorator slot mapping + 2-pass stub collection
  (codex review attempt 4 finding 3건, last fix)
  ([#1903](https://github.com/joshua-jingu-lee/ante/pull/1903),
  [`c43fccf`](https://github.com/joshua-jingu-lee/ante/commit/c43fccfbb8b405cffdd5313429ad182a4abf7ded))

- **cli**: #1900 scanner target-specific stub signature + class decorator method body (codex review
  attempt 5 finding 2건, final) ([#1903](https://github.com/joshua-jingu-lee/ante/pull/1903),
  [`c43fccf`](https://github.com/joshua-jingu-lee/ante/commit/c43fccfbb8b405cffdd5313429ad182a4abf7ded))

- **cli**: #1900 scanner 완전성 보강 (default patch tuple return + positional new) + pip_freeze 되돌리기
  (codex review attempt 1 finding 3건) ([#1903](https://github.com/joshua-jingu-lee/ante/pull/1903),
  [`c43fccf`](https://github.com/joshua-jingu-lee/ante/commit/c43fccfbb8b405cffdd5313429ad182a4abf7ded))

- **cli**: #1911 init lowercase envelope code 일제 SCREAMING_SNAKE 정렬
  ([#1922](https://github.com/joshua-jingu-lee/ante/pull/1922),
  [`952b614`](https://github.com/joshua-jingu-lee/ante/commit/952b614448c72c0b8ee01595c16d657e0268ad01))

- **cli**: #1911 non-auth JSON envelope code SCREAMING_SNAKE 정합
  ([#1922](https://github.com/joshua-jingu-lee/ante/pull/1922),
  [`952b614`](https://github.com/joshua-jingu-lee/ante/commit/952b614448c72c0b8ee01595c16d657e0268ad01))

- **cli**: #1911 non-auth JSON envelope code를 SCREAMING_SNAKE로 정합
  ([#1922](https://github.com/joshua-jingu-lee/ante/pull/1922),
  [`952b614`](https://github.com/joshua-jingu-lee/ante/commit/952b614448c72c0b8ee01595c16d657e0268ad01))

- **cli**: #1913 ANTE_DB_ENCRYPTION_KEY 누락 시 envelope error로 정합
  ([#1932](https://github.com/joshua-jingu-lee/ante/pull/1932),
  [`f76d56d`](https://github.com/joshua-jingu-lee/ante/commit/f76d56d51fb14f80067c148c9182348a133e2b50))

- **cli**: #1913 r1 후속 — chokepoint Config.load 실패 시 env-only fallback
  ([#1932](https://github.com/joshua-jingu-lee/ante/pull/1932),
  [`f76d56d`](https://github.com/joshua-jingu-lee/ante/commit/f76d56d51fb14f80067c148c9182348a133e2b50))

- **cli**: #1914 --data-path default을 config-resolved data root로 정합
  ([#1933](https://github.com/joshua-jingu-lee/ante/pull/1933),
  [`3e526c2`](https://github.com/joshua-jingu-lee/ante/commit/3e526c29f6ea1afd125034bebc79e9c4ff6dfd57))

- **cli**: #1921 update lowercase envelope code를 SCREAMING_SNAKE로 정합
  ([#1935](https://github.com/joshua-jingu-lee/ante/pull/1935),
  [`5d1e6eb`](https://github.com/joshua-jingu-lee/ante/commit/5d1e6eb2a91340e6f9b499ded05e25f7f90c1c31))

- **cli**: Account suspend/activate invalid account_id ingress 거부 (#1655) (#1623 D follow-up)
  ([#1665](https://github.com/joshua-jingu-lee/ante/pull/1665),
  [`5735a08`](https://github.com/joshua-jingu-lee/ante/commit/5735a08459f5a515da575c11a20beef3a4f7829c))

- **cli**: Ante update confirmation gate precedence over server-running + UPDATE_SERVER_RUNNING code
  (#1626) ([#1639](https://github.com/joshua-jingu-lee/ante/pull/1639),
  [`d2ff62a`](https://github.com/joshua-jingu-lee/ante/commit/d2ff62a371e5f7380e5977f26033b79f5e69cb41))

- **cli**: Backtest run symbol/timeframe ingress 검증 (#1603)
  ([#1617](https://github.com/joshua-jingu-lee/ante/pull/1617),
  [`1011a59`](https://github.com/joshua-jingu-lee/ante/commit/1011a591df31572791583256d166978c1467acd8))

- **cli**: Bot create local validation must exit 1 in JSON mode (#1534)
  ([#1546](https://github.com/joshua-jingu-lee/ante/pull/1546),
  [`d328d5d`](https://github.com/joshua-jingu-lee/ante/commit/d328d5d8b2187b240a9a06cb7dc1ffcf96d59705))

- **cli**: Broker IPC invalid account_id envelope 정렬 (#1636) (#1623 Split C)
  ([#1649](https://github.com/joshua-jingu-lee/ante/pull/1649),
  [`690222b`](https://github.com/joshua-jingu-lee/ante/commit/690222b03c388cc909c1f49e4b1d86a92fcf3e6d))

- **cli**: Close db on broker missing-account error to prevent hang (#1535)
  ([#1547](https://github.com/joshua-jingu-lee/ante/pull/1547),
  [`6191164`](https://github.com/joshua-jingu-lee/ante/commit/6191164d1ab307175a90f21e0bd7385d336b4839))

- **cli**: Correct mypy type:ignore code for click.group overload
  ([#1424](https://github.com/joshua-jingu-lee/ante/pull/1424),
  [`f816780`](https://github.com/joshua-jingu-lee/ante/commit/f816780b25511314e6255bd638f805af0007d14b))

- **cli**: Data validate symbol/timeframe ingress 검증 (#1605)
  ([#1619](https://github.com/joshua-jingu-lee/ante/pull/1619),
  [`2472f78`](https://github.com/joshua-jingu-lee/ante/commit/2472f7889a3702182d8539c74096b3aff0449185))

- **cli**: Emit JSON envelope for feed config set unsupported key (#1537)
  ([#1549](https://github.com/joshua-jingu-lee/ante/pull/1549),
  [`66d5cfc`](https://github.com/joshua-jingu-lee/ante/commit/66d5cfcf82dbd70e27ca6a251c850f3ae1811834))

- **cli**: Emit JSON envelope on UsageError when --format json
  ([#1551](https://github.com/joshua-jingu-lee/ante/pull/1551),
  [`1543db9`](https://github.com/joshua-jingu-lee/ante/commit/1543db952c43d9526e59bf068213a98e06e9bfc2))

- **cli**: Emit structured JSON error for auth failures in --format json
  ([#1545](https://github.com/joshua-jingu-lee/ante/pull/1545),
  [`2e2874f`](https://github.com/joshua-jingu-lee/ante/commit/2e2874ffca855c940d5e1c4063608ef705e352eb))

- **cli**: Enforce IntRange min guard on pagination options
  ([#1522](https://github.com/joshua-jingu-lee/ante/pull/1522),
  [`a02d0ba`](https://github.com/joshua-jingu-lee/ante/commit/a02d0ba37f480367959598662dcfa4676286e96b))

- **cli**: Enforce ReportSubmitRequest invariant on CLI submit + StrategyReport guard
  ([#1445](https://github.com/joshua-jingu-lee/ante/pull/1445),
  [`64ab2e7`](https://github.com/joshua-jingu-lee/ante/commit/64ab2e730e2160fb033152b0ec34c76036109dcc))

- **cli**: Enforce ReportSubmitRequest invariant on CLI submit + StrategyReport store guard (#1415)
  ([#1445](https://github.com/joshua-jingu-lee/ante/pull/1445),
  [`64ab2e7`](https://github.com/joshua-jingu-lee/ante/commit/64ab2e730e2160fb033152b0ec34c76036109dcc))

- **cli**: Enforce strict YYYY-MM-DD on audit/treasury date filters
  ([#1523](https://github.com/joshua-jingu-lee/ante/pull/1523),
  [`53249e8`](https://github.com/joshua-jingu-lee/ante/commit/53249e8f3bd67c9ebc2ce660672743dda2c04863))

- **cli**: Exit 1 on bot positions for missing bot
  ([#1568](https://github.com/joshua-jingu-lee/ante/pull/1568),
  [`f3efcbc`](https://github.com/joshua-jingu-lee/ante/commit/f3efcbcd12f6524b7dbe7e5abbc0a153e3b85049))

- **cli**: Exit 1 on bot positions for missing bot (#1558)
  ([#1568](https://github.com/joshua-jingu-lee/ante/pull/1568),
  [`f3efcbc`](https://github.com/joshua-jingu-lee/ante/commit/f3efcbcd12f6524b7dbe7e5abbc0a153e3b85049))

- **cli**: Exit 1 on broker status/reconcile missing-account
  ([#1566](https://github.com/joshua-jingu-lee/ante/pull/1566),
  [`3761a3f`](https://github.com/joshua-jingu-lee/ante/commit/3761a3fb39f86f1dbdca6ac176643b0a2a0f2082))

- **cli**: Exit 1 on broker status/reconcile missing-account (#1556)
  ([#1566](https://github.com/joshua-jingu-lee/ante/pull/1566),
  [`3761a3f`](https://github.com/joshua-jingu-lee/ante/commit/3761a3fb39f86f1dbdca6ac176643b0a2a0f2082))

- **cli**: Exit 1 on instrument import validation errors
  ([#1528](https://github.com/joshua-jingu-lee/ante/pull/1528),
  [`ee3465d`](https://github.com/joshua-jingu-lee/ante/commit/ee3465d3eb760841241ab923a583d4602b893c83))

- **cli**: Exit 1 on member admin command errors (#1557)
  ([#1567](https://github.com/joshua-jingu-lee/ante/pull/1567),
  [`fb783f0`](https://github.com/joshua-jingu-lee/ante/commit/fb783f0c0171be7e897391d9ecf9b07e9cb96456))

- **cli**: Exit 1 on missing-resource error in 5 CLI commands
  ([#1525](https://github.com/joshua-jingu-lee/ante/pull/1525),
  [`c87a5b0`](https://github.com/joshua-jingu-lee/ante/commit/c87a5b0c276ae679e6f7826c420eaa126344ed57))

- **cli**: Exit 1 on report view and treasury snapshot missing-resource (#1538)
  ([#1550](https://github.com/joshua-jingu-lee/ante/pull/1550),
  [`18664ed`](https://github.com/joshua-jingu-lee/ante/commit/18664ed2e1ac4ef244d3523e39c15fddb3729d2a))

- **cli**: Exit 1 on rule list for missing account
  ([#1569](https://github.com/joshua-jingu-lee/ante/pull/1569),
  [`c43f8c6`](https://github.com/joshua-jingu-lee/ante/commit/c43f8c61fec5f729a5708d5c5079725827ec9868))

- **cli**: Exit 1 on rule list for missing account (#1559)
  ([#1569](https://github.com/joshua-jingu-lee/ante/pull/1569),
  [`c43f8c6`](https://github.com/joshua-jingu-lee/ante/commit/c43f8c61fec5f729a5708d5c5079725827ec9868))

- **cli**: Exit 1 on signal connect failures (#1560)
  ([#1570](https://github.com/joshua-jingu-lee/ante/pull/1570),
  [`c193890`](https://github.com/joshua-jingu-lee/ante/commit/c19389000c3fa180d4c66facaca187b216422ed4))

- **cli**: Exit 1 on treasury snapshot option conflict (#1540)
  ([#1552](https://github.com/joshua-jingu-lee/ante/pull/1552),
  [`7a9496b`](https://github.com/joshua-jingu-lee/ante/commit/7a9496b5fc94901bff88a352e9b35638d84fa1ef))

- **cli**: Exit non-zero on signal-key DB error
  ([#1608](https://github.com/joshua-jingu-lee/ante/pull/1608),
  [`2d92db2`](https://github.com/joshua-jingu-lee/ante/commit/2d92db25b1434083ccbba82d4d5ae4261f46f6b0))

- **cli**: Feed inject symbol/timeframe 저장 전 검증 (#1606)
  ([#1620](https://github.com/joshua-jingu-lee/ante/pull/1620),
  [`c5b148c`](https://github.com/joshua-jingu-lee/ante/commit/c5b148c347c46e1ab6203735aa330816fc47d7e3))

- **cli**: Guard non-string import exchange before canonical check
  ([#1582](https://github.com/joshua-jingu-lee/ante/pull/1582),
  [`bae5ae0`](https://github.com/joshua-jingu-lee/ante/commit/bae5ae031b42a7d2c04208ca5ae21ee3aa5603f7))

- **cli**: Instrument import KRX symbol ingress 검증 (#1611)
  ([#1621](https://github.com/joshua-jingu-lee/ante/pull/1621),
  [`b86b529`](https://github.com/joshua-jingu-lee/ante/commit/b86b5294f91895f86caf580f54b6083e3e68dc0c))

- **cli**: Make broker --account required (#1240 review)
  ([#1243](https://github.com/joshua-jingu-lee/ante/pull/1243),
  [`83dcd3b`](https://github.com/joshua-jingu-lee/ante/commit/83dcd3b206acade00a7abfd8eb285f0036def1af))

- **cli**: Normalize missing accounts table as account-not-found in rule list
  ([#1569](https://github.com/joshua-jingu-lee/ante/pull/1569),
  [`c43f8c6`](https://github.com/joshua-jingu-lee/ante/commit/c43f8c61fec5f729a5708d5c5079725827ec9868))

- **cli**: Normalize missing bots table as missing bot in bot positions
  ([#1568](https://github.com/joshua-jingu-lee/ante/pull/1568),
  [`f3efcbc`](https://github.com/joshua-jingu-lee/ante/commit/f3efcbcd12f6524b7dbe7e5abbc0a153e3b85049))

- **cli**: Preflight strategy list --status with structured validation error (#1461)
  ([#1480](https://github.com/joshua-jingu-lee/ante/pull/1480),
  [`a062f74`](https://github.com/joshua-jingu-lee/ante/commit/a062f74af57ade7bd01975f0f38be960abda73ec))

- **cli**: Reject invalid account_id in 3 read-only surfaces before lookup/filter (#1634)
  ([#1647](https://github.com/joshua-jingu-lee/ante/pull/1647),
  [`a68cc28`](https://github.com/joshua-jingu-lee/ante/commit/a68cc28375ec04a6eb08f9b0a0466ddda26c5616))

- **cli**: Reject invalid/source-unsupported exchange in instrument list/sync/import (#1577)
  ([#1582](https://github.com/joshua-jingu-lee/ante/pull/1582),
  [`bae5ae0`](https://github.com/joshua-jingu-lee/ante/commit/bae5ae031b42a7d2c04208ca5ae21ee3aa5603f7))

- **cli**: Reject inverted date range across 4 read/report commands + spec/error-code SSOT (#1597)
  ([#1609](https://github.com/joshua-jingu-lee/ante/pull/1609),
  [`a30935a`](https://github.com/joshua-jingu-lee/ante/commit/a30935a251de1b0beb487a15ade2c2da918b0a00))

- **cli**: Reject NaN/inf/non-positive amounts on treasury allocate/deallocate
  ([#1529](https://github.com/joshua-jingu-lee/ante/pull/1529),
  [`84364b2`](https://github.com/joshua-jingu-lee/ante/commit/84364b299f16fc4de9aadd6697c42854e0ea73d9))

- **cli**: Reject non-canonical/source-unsupported exchange in instrument list/sync/import
  ([#1582](https://github.com/joshua-jingu-lee/ante/pull/1582),
  [`bae5ae0`](https://github.com/joshua-jingu-lee/ante/commit/bae5ae031b42a7d2c04208ca5ae21ee3aa5603f7))

- **cli**: Reject non-finite/non-positive backtest --balance (#1565)
  ([#1574](https://github.com/joshua-jingu-lee/ante/pull/1574),
  [`3528280`](https://github.com/joshua-jingu-lee/ante/commit/352828030b86123047f56b8758911a7921fb1188))

- **cli**: Reject non-positive year in monthly report performance + error-code SSOT (#1599)
  ([#1610](https://github.com/joshua-jingu-lee/ante/pull/1610),
  [`8237fb5`](https://github.com/joshua-jingu-lee/ante/commit/8237fb56d51b0bbbc386014886ff44560010797e))

- **cli**: Reject period-exclusive option conflicts in report performance + spec/error-code SSOT
  (#1593) ([#1600](https://github.com/joshua-jingu-lee/ante/pull/1600),
  [`854f606`](https://github.com/joshua-jingu-lee/ante/commit/854f606b58bb514312a00f457bc89c93c62d22e5))

- **cli**: Reject signal-key for missing bot
  ([#1608](https://github.com/joshua-jingu-lee/ante/pull/1608),
  [`2d92db2`](https://github.com/joshua-jingu-lee/ante/commit/2d92db25b1434083ccbba82d4d5ae4261f46f6b0))

- **cli**: Reject signal-key for missing/deleted bot (#1596)
  ([#1608](https://github.com/joshua-jingu-lee/ante/pull/1608),
  [`2d92db2`](https://github.com/joshua-jingu-lee/ante/commit/2d92db25b1434083ccbba82d4d5ae4261f46f6b0))

- **cli**: Require JSON object for approval --params (#1519)
  ([#1532](https://github.com/joshua-jingu-lee/ante/pull/1532),
  [`5c17ff1`](https://github.com/joshua-jingu-lee/ante/commit/5c17ff198c54aa83caaa0951eebf1f6401361a89))

- **cli**: Resolve get_db_path through Config.resolve_path
  ([#1181](https://github.com/joshua-jingu-lee/ante/pull/1181),
  [`b5e60d7`](https://github.com/joshua-jingu-lee/ante/commit/b5e60d71e2ae2ffb893d657d759d1af9d0fee536))

- **cli**: Reuse validate_iso_date on trade list --from/--to
  ([#1524](https://github.com/joshua-jingu-lee/ante/pull/1524),
  [`d013a71`](https://github.com/joshua-jingu-lee/ante/commit/d013a711ea5d36c1407ed536ea05455f363fbc3b))

- **cli**: Show market_order_reserve_buffer_rate in account info text output (#1333 P3)
  ([#1350](https://github.com/joshua-jingu-lee/ante/pull/1350),
  [`563df47`](https://github.com/joshua-jingu-lee/ante/commit/563df4742324680ade2126daf6aa4c7b5bb466f5))

- **cli**: Strategy validate failure emits single JSON envelope and exit 1 (#1541)
  ([#1553](https://github.com/joshua-jingu-lee/ante/pull/1553),
  [`517b34d`](https://github.com/joshua-jingu-lee/ante/commit/517b34d5e4297c48a25e4c5161b238df3ce8a51f))

- **cli**: Strict YYYY-MM-DD validation for feed date options
  ([#1571](https://github.com/joshua-jingu-lee/ante/pull/1571),
  [`c2e8549`](https://github.com/joshua-jingu-lee/ante/commit/c2e85490951fa0c43c852b80191e3dca5ce8f045))

- **cli**: Strict YYYY-MM-DD validation for feed date options (#1562)
  ([#1571](https://github.com/joshua-jingu-lee/ante/pull/1571),
  [`c2e8549`](https://github.com/joshua-jingu-lee/ante/commit/c2e85490951fa0c43c852b80191e3dca5ce8f045))

- **cli**: Treasury/rule construction lifecycle invalid account_id 경계 (#1635)
  ([#1648](https://github.com/joshua-jingu-lee/ante/pull/1648),
  [`1623291`](https://github.com/joshua-jingu-lee/ante/commit/1623291446db187d10dec66fa2f952435feed0a8))

- **cli**: Treat soft-deleted bot as missing in signal-key
  ([#1608](https://github.com/joshua-jingu-lee/ante/pull/1608),
  [`2d92db2`](https://github.com/joshua-jingu-lee/ante/commit/2d92db25b1434083ccbba82d4d5ae4261f46f6b0))

- **cli**: Use ACCOUNT_NOT_FOUND error code for broker missing-account
  ([#1566](https://github.com/joshua-jingu-lee/ante/pull/1566),
  [`3761a3f`](https://github.com/joshua-jingu-lee/ante/commit/3761a3fb39f86f1dbdca6ac176643b0a2a0f2082))

- **cli**: Use lightweight account existence check in rule list
  ([#1569](https://github.com/joshua-jingu-lee/ante/pull/1569),
  [`c43f8c6`](https://github.com/joshua-jingu-lee/ante/commit/c43f8c61fec5f729a5708d5c5079725827ec9868))

- **cli**: Validate feed --until/--date and unify CLI_INVALID_DATE
  ([#1571](https://github.com/joshua-jingu-lee/ante/pull/1571),
  [`c2e8549`](https://github.com/joshua-jingu-lee/ante/commit/c2e85490951fa0c43c852b80191e3dca5ce8f045))

- **cli**: Validate feed backfill --since at CLI boundary (#1536)
  ([#1548](https://github.com/joshua-jingu-lee/ante/pull/1548),
  [`3eddd58`](https://github.com/joshua-jingu-lee/ante/commit/3eddd5825ecc8610c74ac8856da9a799f3205316))

- **cli**: Validate report performance --start/--end at CLI boundary (#1564)
  ([#1573](https://github.com/joshua-jingu-lee/ante/pull/1573),
  [`20794aa`](https://github.com/joshua-jingu-lee/ante/commit/20794aaf2d4b890a658f5c3ab50f466e5114c319))

- **cli**: Wrap _parse_expires_in to suppress traceback on invalid duration
  ([#1531](https://github.com/joshua-jingu-lee/ante/pull/1531),
  [`3c80211`](https://github.com/joshua-jingu-lee/ante/commit/3c80211a80a1fc23b9c317021ba10930193d08e3))

- **cli,approval**: Enforce ApprovalType enum on CLI request + service create (#1469)
  ([#1481](https://github.com/joshua-jingu-lee/ante/pull/1481),
  [`20918ae`](https://github.com/joshua-jingu-lee/ante/commit/20918aeca0309d17067f193f6128b7f00bfe3947))

- **cli/account**: Pass explicit Config to cold-path guard read_pid_file
  ([#1182](https://github.com/joshua-jingu-lee/ante/pull/1182),
  [`290bcff`](https://github.com/joshua-jingu-lee/ante/commit/290bcff5afbd8688b251a0cc3c1764cb2071fac8))

- **cli/system**: Pass explicit Config to start's read_pid_file
  ([#1182](https://github.com/joshua-jingu-lee/ante/pull/1182),
  [`290bcff`](https://github.com/joshua-jingu-lee/ante/commit/290bcff5afbd8688b251a0cc3c1764cb2071fac8))

- **cli/update**: Pass explicit Config to check_server_running
  ([#1182](https://github.com/joshua-jingu-lee/ante/pull/1182),
  [`290bcff`](https://github.com/joshua-jingu-lee/ante/commit/290bcff5afbd8688b251a0cc3c1764cb2071fac8))

- **config**: Cover register_default and tuple values in finite invariant
  ([#1433](https://github.com/joshua-jingu-lee/ante/pull/1433),
  [`6eab379`](https://github.com/joshua-jingu-lee/ante/commit/6eab379ab7a2e5a7c2a253a203e42c2a157b3bbf))

- **config**: Enforce finite numeric invariant at write and read boundaries
  ([#1433](https://github.com/joshua-jingu-lee/ante/pull/1433),
  [`6eab379`](https://github.com/joshua-jingu-lee/ante/commit/6eab379ab7a2e5a7c2a253a203e42c2a157b3bbf))

- **config**: Enforce finite numeric invariant for dynamic config (write + read defense)
  ([#1433](https://github.com/joshua-jingu-lee/ante/pull/1433),
  [`6eab379`](https://github.com/joshua-jingu-lee/ante/commit/6eab379ab7a2e5a7c2a253a203e42c2a157b3bbf))

- **config**: Recurse finite check into nested dict/list, skip int from isfinite
  ([#1433](https://github.com/joshua-jingu-lee/ante/pull/1433),
  [`6eab379`](https://github.com/joshua-jingu-lee/ante/commit/6eab379ab7a2e5a7c2a253a203e42c2a157b3bbf))

- **config**: Reject invalid system.log_level value at service boundary (#1379)
  ([#1389](https://github.com/joshua-jingu-lee/ante/pull/1389),
  [`8f26812`](https://github.com/joshua-jingu-lee/ante/commit/8f2681247d913b9b89197bc8bfd05e54bf0e796e))

- **config,cli,main**: Resolve db.path through Config.resolve_path to close cold-path split-brain
  (#1158) ([#1181](https://github.com/joshua-jingu-lee/ante/pull/1181),
  [`b5e60d7`](https://github.com/joshua-jingu-lee/ante/commit/b5e60d71e2ae2ffb893d657d759d1af9d0fee536))

- **core**: #1923 Database.transaction이 BaseException 경로에서도 ROLLBACK
  ([#1937](https://github.com/joshua-jingu-lee/ante/pull/1937),
  [`c177b28`](https://github.com/joshua-jingu-lee/ante/commit/c177b28429ec4e818140ff7f2fc7b84ca05da4dc))

- **dashboard**: Align notification settings keys with 1.0 contract
  ([#1163](https://github.com/joshua-jingu-lee/ante/pull/1163),
  [`d5ec35e`](https://github.com/joshua-jingu-lee/ante/commit/d5ec35e5f153f2c3006c6b2a09b17fbd28e842f9))

- **dashboard**: Align notification settings keys with 1.0 contract (#1141)
  ([#1163](https://github.com/joshua-jingu-lee/ante/pull/1163),
  [`d5ec35e`](https://github.com/joshua-jingu-lee/ante/commit/d5ec35e5f153f2c3006c6b2a09b17fbd28e842f9))

- **dashboard**: Preserve INFO fallback and unblock min_level when telegram off
  ([#1163](https://github.com/joshua-jingu-lee/ante/pull/1163),
  [`d5ec35e`](https://github.com/joshua-jingu-lee/ante/commit/d5ec35e5f153f2c3006c6b2a09b17fbd28e842f9))

- **data**: DataCollector symbol/timeframe ingress 검증 (#1614)
  ([#1622](https://github.com/joshua-jingu-lee/ante/pull/1622),
  [`7ced866`](https://github.com/joshua-jingu-lee/ante/commit/7ced8669da695be8679d8f1e99ecfbde34babc96))

- **data**: Enforce canonical exchange on ParquetStore write/append (#1584)
  ([#1587](https://github.com/joshua-jingu-lee/ante/pull/1587),
  [`b037250`](https://github.com/joshua-jingu-lee/ante/commit/b037250d12063ce81cfcc60288cb38ee4b2ccc65))

- **data**: Raise list_datasets limit ceiling to 10000 to preserve dashboard caller
  ([#1366](https://github.com/joshua-jingu-lee/ante/pull/1366),
  [`9b12c08`](https://github.com/joshua-jingu-lee/ante/commit/9b12c087492aab7001ca46ea65f8c2b4f664f6f6))

- **deps**: Cap cryptography <47 to avoid arm64 wheel SIGILL
  ([#1295](https://github.com/joshua-jingu-lee/ante/pull/1295),
  [`93f6823`](https://github.com/joshua-jingu-lee/ante/commit/93f682395deeb8657e0182c0010d64193943e83e))

- **docs**: #1659 broker health/price docs drift 정합 (docs-only sweep)
  ([#1668](https://github.com/joshua-jingu-lee/ante/pull/1668),
  [`14245cf`](https://github.com/joshua-jingu-lee/ante/commit/14245cf05fffdf9e5454d8d33d7fad7d2664f229))

- **docs**: #1660 bot start/stop/status를 미구현(follow-up)으로 명시 (docs + 생성기 annotation)
  ([#1669](https://github.com/joshua-jingu-lee/ante/pull/1669),
  [`0c62d69`](https://github.com/joshua-jingu-lee/ante/commit/0c62d691a69799a3e6f1e9a2271886cefbf4be41))

- **docs**: #1660 ipc.md bot.query 모순 정정 — 실재 4명령 live-query 보존·bot status만 미구현 분리
  ([#1669](https://github.com/joshua-jingu-lee/ante/pull/1669),
  [`0c62d69`](https://github.com/joshua-jingu-lee/ante/commit/0c62d691a69799a3e6f1e9a2271886cefbf4be41))

- **docs**: #1660 scope를 oracle literal surface로 narrowing (Codex attempt 2 P2x2)
  ([#1669](https://github.com/joshua-jingu-lee/ante/pull/1669),
  [`0c62d69`](https://github.com/joshua-jingu-lee/ante/commit/0c62d691a69799a3e6f1e9a2271886cefbf4be41))

- **eventbus**: #1957 체결 이벤트 소비자 멱등화 (Treasury exactly-once + Bot/SignalChannel/TradeRecorder
  bounded) ([#1960](https://github.com/joshua-jingu-lee/ante/pull/1960),
  [`15638e4`](https://github.com/joshua-jingu-lee/ante/commit/15638e40682e2de659111c4bf31c18983837168d))

- **eventbus**: Preserve account_id on OrderCancelFailedEvent
  ([#1342](https://github.com/joshua-jingu-lee/ante/pull/1342),
  [`71c6d93`](https://github.com/joshua-jingu-lee/ante/commit/71c6d9343eaf7ea58bb307d1e8db21ade1e9e13d))

- **eventbus**: Preserve account_id on OrderCancelFailedEvent (#1332)
  ([#1342](https://github.com/joshua-jingu-lee/ante/pull/1342),
  [`71c6d93`](https://github.com/joshua-jingu-lee/ante/commit/71c6d9343eaf7ea58bb307d1e8db21ade1e9e13d))

- **feed**: #1943 feed run daily --date를 명시 파라미터로 전달
  ([#1944](https://github.com/joshua-jingu-lee/ante/pull/1944),
  [`3c56d49`](https://github.com/joshua-jingu-lee/ante/commit/3c56d49a65ee6cab3c8306df6d2bb46ae22d9d3e))

- **frontend**: Add release to TRANSACTION_TYPE_LABELS/VARIANT (#1476 codex P2)
  ([#1482](https://github.com/joshua-jingu-lee/ante/pull/1482),
  [`9c24fe9`](https://github.com/joshua-jingu-lee/ante/commit/9c24fe933726d7837335bba5c11524f200a20084))

- **frontend**: Normalize legacy percent win_rate values for backwards compatibility
  ([#1363](https://github.com/joshua-jingu-lee/ante/pull/1363),
  [`0dcb64a`](https://github.com/joshua-jingu-lee/ante/commit/0dcb64a386730d74acc1f34bf346ae7416db3c93))

- **frontend,member**: Separate display HumanRole from API payload role
  ([#1487](https://github.com/joshua-jingu-lee/ante/pull/1487),
  [`7796c11`](https://github.com/joshua-jingu-lee/ante/commit/7796c116574b9670ce6097b4e1a14131597ce9cf))

- **gateway**: Split-3 prefix-exact ResponseCache invalidate
  ([#1247](https://github.com/joshua-jingu-lee/ante/pull/1247),
  [`91b2afb`](https://github.com/joshua-jingu-lee/ante/commit/91b2afb3bd264ec5ef212bde1df29c0e0205a180))

- **ipc**: Reject dispatch during resource drain
  ([#1193](https://github.com/joshua-jingu-lee/ante/pull/1193),
  [`af00382`](https://github.com/joshua-jingu-lee/ante/commit/af003825ed840c43c706440d0720bb469dfe23bd))

- **ipc**: Reject mutating commands during shutdown
  ([#1193](https://github.com/joshua-jingu-lee/ante/pull/1193),
  [`af00382`](https://github.com/joshua-jingu-lee/ante/commit/af003825ed840c43c706440d0720bb469dfe23bd))

- **ipc**: Reject shutdown-time mutating dispatch
  ([#1193](https://github.com/joshua-jingu-lee/ante/pull/1193),
  [`af00382`](https://github.com/joshua-jingu-lee/ante/commit/af003825ed840c43c706440d0720bb469dfe23bd))

- **ipc**: Satisfy mypy for unix server kwargs
  ([#1194](https://github.com/joshua-jingu-lee/ante/pull/1194),
  [`ecaf0e4`](https://github.com/joshua-jingu-lee/ante/commit/ecaf0e41ac90ddfcc12f774a3d1caf0b7681d704))

- **ipc**: Scope cleanup_socket=False to Python 3.13+ for 3.11/3.12 boot compat
  ([#1183](https://github.com/joshua-jingu-lee/ante/pull/1183),
  [`7d8d9a5`](https://github.com/joshua-jingu-lee/ante/commit/7d8d9a53494f6fcd82d7baed8a77235f5d472aab))

- **ipc,cli**: #1656 E bucket invalid account_id를 VALIDATION_ERROR로 거부 (#1623 E follow-up)
  ([#1666](https://github.com/joshua-jingu-lee/ante/pull/1666),
  [`ae1b885`](https://github.com/joshua-jingu-lee/ante/commit/ae1b88542909c90b7d424ebe4e263d3bb546e2e4))

- **ipc,main**: Close cold-path race window via 3-phase IPC shutdown ordering (#1159)
  ([#1183](https://github.com/joshua-jingu-lee/ante/pull/1183),
  [`7d8d9a5`](https://github.com/joshua-jingu-lee/ante/commit/7d8d9a53494f6fcd82d7baed8a77235f5d472aab))

- **main**: Add startup booting marker guard
  ([#1195](https://github.com/joshua-jingu-lee/ante/pull/1195),
  [`609f70a`](https://github.com/joshua-jingu-lee/ante/commit/609f70a166ac34cbffca033f196410b1841269ce))

- **main**: Cutover to single-canonical PID resolver (no legacy read-fallback)
  ([#1182](https://github.com/joshua-jingu-lee/ante/pull/1182),
  [`290bcff`](https://github.com/joshua-jingu-lee/ante/commit/290bcff5afbd8688b251a0cc3c1764cb2071fac8))

- **main**: Defer IPC socket unlink to after DB close to close cold-path race
  ([#1183](https://github.com/joshua-jingu-lee/ante/pull/1183),
  [`7d8d9a5`](https://github.com/joshua-jingu-lee/ante/commit/7d8d9a53494f6fcd82d7baed8a77235f5d472aab))

- **main**: Emit legacy PID deprecation warning at most once per process
  ([#1182](https://github.com/joshua-jingu-lee/ante/pull/1182),
  [`290bcff`](https://github.com/joshua-jingu-lee/ante/commit/290bcff5afbd8688b251a0cc3c1764cb2071fac8))

- **main**: Resolve _init_core db.path through Config.resolve_path
  ([#1181](https://github.com/joshua-jingu-lee/ante/pull/1181),
  [`b5e60d7`](https://github.com/joshua-jingu-lee/ante/commit/b5e60d71e2ae2ffb893d657d759d1af9d0fee536))

- **member**: #1915 emoji/master-protect 오류를 typed exception으로 정합
  ([#1934](https://github.com/joshua-jingu-lee/ante/pull/1934),
  [`a3b5c75`](https://github.com/joshua-jingu-lee/ante/commit/a3b5c752092af2ed0c70b0719bb6300d72d58351))

- **member**: Align Web API + CLI surface guards to master-only contract
  ([#1555](https://github.com/joshua-jingu-lee/ante/pull/1555),
  [`b656348`](https://github.com/joshua-jingu-lee/ante/commit/b65634867953de5ddee39e9eb1c672c12f539fe1))

- **member**: Block legacy invalid-role member/token in auth read-path (#1466)
  ([#1484](https://github.com/joshua-jingu-lee/ante/pull/1484),
  [`2707cf7`](https://github.com/joshua-jingu-lee/ante/commit/2707cf79bed06d20e230ca1b37f6f53902d33464))

- **member**: Include --yes in revoke_command and drop unwired --db-path
  ([#1509](https://github.com/joshua-jingu-lee/ante/pull/1509),
  [`71ae6cb`](https://github.com/joshua-jingu-lee/ante/commit/71ae6cb1017d46601b304e5efa6019ada4889bc4))

- **member**: Introduce SCOPE_VOCABULARY SSOT + Pydantic/service/CLI validation (#1439)
  ([#1451](https://github.com/joshua-jingu-lee/ante/pull/1451),
  [`207bfc6`](https://github.com/joshua-jingu-lee/ante/commit/207bfc6b361213b052708357aa3d762939c47a51))

- **member**: Normalize --config-dir to absolute path in revoke_command payload
  ([#1509](https://github.com/joshua-jingu-lee/ante/pull/1509),
  [`71ae6cb`](https://github.com/joshua-jingu-lee/ante/commit/71ae6cb1017d46601b304e5efa6019ada4889bc4))

- **member**: Preserve --config-dir in revoke_command payload
  ([#1509](https://github.com/joshua-jingu-lee/ante/pull/1509),
  [`71ae6cb`](https://github.com/joshua-jingu-lee/ante/commit/71ae6cb1017d46601b304e5efa6019ada4889bc4))

- **member**: Require_master self-sentinel + correct test count
  ([#1555](https://github.com/joshua-jingu-lee/ante/pull/1555),
  [`b656348`](https://github.com/joshua-jingu-lee/ante/commit/b65634867953de5ddee39e9eb1c672c12f539fe1))

- **member**: Shell-safe revoke_command and omit on legacy_revoked
  ([#1509](https://github.com/joshua-jingu-lee/ante/pull/1509),
  [`71ae6cb`](https://github.com/joshua-jingu-lee/ante/commit/71ae6cb1017d46601b304e5efa6019ada4889bc4))

- **members**: Forbid extra keys on ScopesUpdateRequest to match OpenAPI
  ([#1361](https://github.com/joshua-jingu-lee/ante/pull/1361),
  [`bc9fd4a`](https://github.com/joshua-jingu-lee/ante/commit/bc9fd4a9998b0e51000281dbd5f9689898610cf0))

- **members**: Require authenticated master for mutation routes
  ([#1361](https://github.com/joshua-jingu-lee/ante/pull/1361),
  [`bc9fd4a`](https://github.com/joshua-jingu-lee/ante/commit/bc9fd4a9998b0e51000281dbd5f9689898610cf0))

- **members**: Require authenticated master for mutation routes (#1351)
  ([#1361](https://github.com/joshua-jingu-lee/ante/pull/1361),
  [`bc9fd4a`](https://github.com/joshua-jingu-lee/ante/commit/bc9fd4a9998b0e51000281dbd5f9689898610cf0))

- **members**: Restore update_scopes OpenAPI body schema and propagate PermissionDeniedError to CLI
  ([#1361](https://github.com/joshua-jingu-lee/ante/pull/1361),
  [`bc9fd4a`](https://github.com/joshua-jingu-lee/ante/commit/bc9fd4a9998b0e51000281dbd5f9689898610cf0))

- **modify**: Emit terminal OrderModifyRejectedEvent for ctx.modify_order (#1331)
  ([#1341](https://github.com/joshua-jingu-lee/ante/pull/1341),
  [`fde7c2e`](https://github.com/joshua-jingu-lee/ante/commit/fde7c2ed4b6b8c91495dc6992dc9bdcdc29bf4b2))

- **report**: Align ReportStore.get_schema win_rate example with percent unit
  ([#1363](https://github.com/joshua-jingu-lee/ante/pull/1363),
  [`0dcb64a`](https://github.com/joshua-jingu-lee/ante/commit/0dcb64a386730d74acc1f34bf346ae7416db3c93))

- **report**: Enforce metrics invariant at ReportStore save boundary (codex FAIL r3)
  ([#1445](https://github.com/joshua-jingu-lee/ante/pull/1445),
  [`64ab2e7`](https://github.com/joshua-jingu-lee/ante/commit/64ab2e730e2160fb033152b0ec34c76036109dcc))

- **report**: Reject invalid submit metrics and unify win_rate to ratio
  ([#1363](https://github.com/joshua-jingu-lee/ante/pull/1363),
  [`0dcb64a`](https://github.com/joshua-jingu-lee/ante/commit/0dcb64a386730d74acc1f34bf346ae7416db3c93))

- **report**: Split StrategyReport invariant to opt-in function + validate JSON shape (codex FAIL
  r1) ([#1445](https://github.com/joshua-jingu-lee/ante/pull/1445),
  [`64ab2e7`](https://github.com/joshua-jingu-lee/ante/commit/64ab2e730e2160fb033152b0ec34c76036109dcc))

- **reports**: Reject unknown list status with 422 via ReportStatus enum (#1355)
  ([#1365](https://github.com/joshua-jingu-lee/ante/pull/1365),
  [`fa1cb96`](https://github.com/joshua-jingu-lee/ante/commit/fa1cb961af73cc643ea2b3242089b359819cd660))

- **reports**: Validate ReportSubmitRequest input ranges and reject NaN/Inf (#1353)
  ([#1363](https://github.com/joshua-jingu-lee/ante/pull/1363),
  [`0dcb64a`](https://github.com/joshua-jingu-lee/ante/commit/0dcb64a386730d74acc1f34bf346ae7416db3c93))

- **review**: Address PR approval findings
  ([#1136](https://github.com/joshua-jingu-lee/ante/pull/1136),
  [`4792745`](https://github.com/joshua-jingu-lee/ante/commit/4792745743af86d1f682a248314d25e33bbb66b2))

- **rule**: Also normalize price in safe rejected event builder
  ([#1311](https://github.com/joshua-jingu-lee/ante/pull/1311),
  [`6a7f6c2`](https://github.com/joshua-jingu-lee/ante/commit/6a7f6c2e0b24bab3c6b9ad4d8da356ef9e552dc3))

- **rule**: Also reject non-string Signal.side in OrderRequestEvent preflight
  ([#1306](https://github.com/joshua-jingu-lee/ante/pull/1306),
  [`f7c9f56`](https://github.com/joshua-jingu-lee/ante/commit/f7c9f56416989186d1c10eb349fa0be0f58e5953))

- **rule**: Apply safe_quantity normalization to all preflight reject paths
  ([#1311](https://github.com/joshua-jingu-lee/ante/pull/1311),
  [`6a7f6c2`](https://github.com/joshua-jingu-lee/ante/commit/6a7f6c2e0b24bab3c6b9ad4d8da356ef9e552dc3))

- **rule**: Coerce non-string side to repr in OrderRejectedEvent payload
  ([#1306](https://github.com/joshua-jingu-lee/ante/pull/1306),
  [`f7c9f56`](https://github.com/joshua-jingu-lee/ante/commit/f7c9f56416989186d1c10eb349fa0be0f58e5953))

- **rule**: Graceful reject for invalid timezone in TradingHoursRule
  ([#1507](https://github.com/joshua-jingu-lee/ante/pull/1507),
  [`d73a98b`](https://github.com/joshua-jingu-lee/ante/commit/d73a98b6ba8f27961ba54ea7b81f9fe8270e991c))

- **rule**: Handle OverflowError in finite-quantity check for large int
  ([#1311](https://github.com/joshua-jingu-lee/ante/pull/1311),
  [`6a7f6c2`](https://github.com/joshua-jingu-lee/ante/commit/6a7f6c2e0b24bab3c6b9ad4d8da356ef9e552dc3))

- **rule**: Inject default trading_hours for KIS + classify 40580000 (#1296)
  ([#1315](https://github.com/joshua-jingu-lee/ante/pull/1315),
  [`747fd37`](https://github.com/joshua-jingu-lee/ante/commit/747fd3765ef05dd1799f1682a02c0ffff41b33dc))

- **rule**: Inject default trading_hours for KIS + classify 40580000 as permanent
  ([#1315](https://github.com/joshua-jingu-lee/ante/pull/1315),
  [`747fd37`](https://github.com/joshua-jingu-lee/ante/commit/747fd3765ef05dd1799f1682a02c0ffff41b33dc))

- **rule**: Merge DynamicConfig overrides on RuleEngineManager init
  ([#1315](https://github.com/joshua-jingu-lee/ante/pull/1315),
  [`747fd37`](https://github.com/joshua-jingu-lee/ante/commit/747fd3765ef05dd1799f1682a02c0ffff41b33dc))

- **rule**: Reject invalid KRX numeric symbol at OrderRequestEvent preflight (#1299)
  ([#1308](https://github.com/joshua-jingu-lee/ante/pull/1308),
  [`894d5db`](https://github.com/joshua-jingu-lee/ante/commit/894d5db2a7605bc17506fb8b3c626c4340fbb2c5))

- **rule**: Reject invalid Signal.order_type at OrderRequestEvent preflight (#1298)
  ([#1307](https://github.com/joshua-jingu-lee/ante/pull/1307),
  [`b1538a1`](https://github.com/joshua-jingu-lee/ante/commit/b1538a1bf219645360663e301b97853fee4ce433))

- **rule**: Reject invalid Signal.side at OrderRequestEvent preflight
  ([#1306](https://github.com/joshua-jingu-lee/ante/pull/1306),
  [`f7c9f56`](https://github.com/joshua-jingu-lee/ante/commit/f7c9f56416989186d1c10eb349fa0be0f58e5953))

- **rule**: Reject invalid Signal.side at OrderRequestEvent preflight (#1297)
  ([#1306](https://github.com/joshua-jingu-lee/ante/pull/1306),
  [`f7c9f56`](https://github.com/joshua-jingu-lee/ante/commit/f7c9f56416989186d1c10eb349fa0be0f58e5953))

- **rule**: Reject NaN/Inf in account rule params at service boundary (#1380)
  ([#1390](https://github.com/joshua-jingu-lee/ante/pull/1390),
  [`94181ef`](https://github.com/joshua-jingu-lee/ante/commit/94181efb2c9a7fc6f809fa46de1181e792b64f9e))

- **rule**: Reject NaN/inf/negative stop_price at OrderRequestEvent preflight (#1319)
  ([#1329](https://github.com/joshua-jingu-lee/ante/pull/1329),
  [`8d507b4`](https://github.com/joshua-jingu-lee/ante/commit/8d507b4baf3351260d45dbccbaa6e09c31e5f6e8))

- **rule**: Reject NaN/inf/non-number price at OrderRequestEvent preflight (#1303)
  ([#1312](https://github.com/joshua-jingu-lee/ante/pull/1312),
  [`b623ddb`](https://github.com/joshua-jingu-lee/ante/commit/b623ddbd945a5b9bdc93b7cbb77d47043ac047ce))

- **rule**: Reject NaN/inf/non-number quantity + safe reject builder (#1302)
  ([#1311](https://github.com/joshua-jingu-lee/ante/pull/1311),
  [`6a7f6c2`](https://github.com/joshua-jingu-lee/ante/commit/6a7f6c2e0b24bab3c6b9ad4d8da356ef9e552dc3))

- **rule**: Reject NaN/inf/non-number quantity at OrderRequestEvent preflight
  ([#1311](https://github.com/joshua-jingu-lee/ante/pull/1311),
  [`6a7f6c2`](https://github.com/joshua-jingu-lee/ante/commit/6a7f6c2e0b24bab3c6b9ad4d8da356ef9e552dc3))

- **rule**: Reject negative price at OrderRequestEvent preflight (#1316)
  ([#1326](https://github.com/joshua-jingu-lee/ante/pull/1326),
  [`ac9af66`](https://github.com/joshua-jingu-lee/ante/commit/ac9af66124169da5f244c72c686be17e8a1f6fe0))

- **rule**: Reject negative quantity at OrderRequestEvent preflight (#1304)
  ([#1313](https://github.com/joshua-jingu-lee/ante/pull/1313),
  [`f818216`](https://github.com/joshua-jingu-lee/ante/commit/f818216435de88e20d9e449d07bcc6678d3bceec))

- **rule**: Reject zero price at OrderRequestEvent preflight (#1318)
  ([#1328](https://github.com/joshua-jingu-lee/ante/pull/1328),
  [`05cad6e`](https://github.com/joshua-jingu-lee/ante/commit/05cad6efc66dda0bc454405399fda859d9fb74d9))

- **rule**: Reject zero quantity at OrderRequestEvent preflight (#1305)
  ([#1314](https://github.com/joshua-jingu-lee/ante/pull/1314),
  [`1948122`](https://github.com/joshua-jingu-lee/ante/commit/1948122fa15cdc9deb92778bb489011de4b463dd))

- **rule**: Reject zero stop_price at OrderRequestEvent preflight (#1320)
  ([#1330](https://github.com/joshua-jingu-lee/ante/pull/1330),
  [`f3d2cfb`](https://github.com/joshua-jingu-lee/ante/commit/f3d2cfb09153b0cb9fbe75c374915a09233f66e5))

- **rule**: Require price for limit/stop_limit at OrderRequestEvent preflight (#1300)
  ([#1309](https://github.com/joshua-jingu-lee/ante/pull/1309),
  [`8861cdc`](https://github.com/joshua-jingu-lee/ante/commit/8861cdc81b8d2a4b3f9b9510d832c468229de938))

- **rule**: Require stop_price for stop/stop_limit at OrderRequestEvent preflight (#1301)
  ([#1310](https://github.com/joshua-jingu-lee/ante/pull/1310),
  [`28a8233`](https://github.com/joshua-jingu-lee/ante/commit/28a8233571278e625567ebe5f3f73f05384daa45))

- **rule**: Scope ConfigChangedEvent reload to own account key
  ([#1315](https://github.com/joshua-jingu-lee/ante/pull/1315),
  [`747fd37`](https://github.com/joshua-jingu-lee/ante/commit/747fd3765ef05dd1799f1682a02c0ffff41b33dc))

- **rule**: Use TypeGuard for _is_finite_quantity to satisfy mypy
  ([#1311](https://github.com/joshua-jingu-lee/ante/pull/1311),
  [`6a7f6c2`](https://github.com/joshua-jingu-lee/ante/commit/6a7f6c2e0b24bab3c6b9ad4d8da356ef9e552dc3))

- **rule**: Wrap preflight in try + safe reject builder for fail-closed audit
  ([#1311](https://github.com/joshua-jingu-lee/ante/pull/1311),
  [`6a7f6c2`](https://github.com/joshua-jingu-lee/ante/commit/6a7f6c2e0b24bab3c6b9ad4d8da356ef9e552dc3))

- **rule,gateway,bot**: Emit terminal OrderModifyRejectedEvent for ctx.modify_order
  ([#1341](https://github.com/joshua-jingu-lee/ante/pull/1341),
  [`fde7c2e`](https://github.com/joshua-jingu-lee/ante/commit/fde7c2ed4b6b8c91495dc6992dc9bdcdc29bf4b2))

- **stop-order**: Split-3 require account_id on price tick
  ([#1247](https://github.com/joshua-jingu-lee/ante/pull/1247),
  [`91b2afb`](https://github.com/joshua-jingu-lee/ante/commit/91b2afb3bd264ec5ef212bde1df29c0e0205a180))

- **stream,trade**: Propagate account_id to OrderFilledEvent and position_history (#1240 review)
  ([#1243](https://github.com/joshua-jingu-lee/ante/pull/1243),
  [`83dcd3b`](https://github.com/joshua-jingu-lee/ante/commit/83dcd3b206acade00a7abfd8eb285f0036def1af))

- **system**: Emit Z suffix for kill-switch changed_at (#1360)
  ([#1370](https://github.com/joshua-jingu-lee/ante/pull/1370),
  [`743c5ed`](https://github.com/joshua-jingu-lee/ante/commit/743c5ede357b7b86b852f6d1a1c91cda50172f70))

- **test**: #1897 aiosqlite/sqlite Connection 누수 fixture 정리 (broker test isolation 해결, #1904
  unblock) ([#1905](https://github.com/joshua-jingu-lee/ante/pull/1905),
  [`1c51824`](https://github.com/joshua-jingu-lee/ante/commit/1c51824faca78d24b39c76dd4415a8b5dbd909dc))

- **test**: #1897 follow-up — autouse mock.patch.stopall() in cleanup fixture (PR #1904 unblock)
  ([#1906](https://github.com/joshua-jingu-lee/ante/pull/1906),
  [`17700cb`](https://github.com/joshua-jingu-lee/ante/commit/17700cbeeb6c3147721708277c63c9144b9095f7))

- **test**: #1909 contracts shell test를 subprocess isolation으로 변환 (sys.modules pollution → CI 결정적
  fail 해소) ([#1910](https://github.com/joshua-jingu-lee/ante/pull/1910),
  [`17c800a`](https://github.com/joshua-jingu-lee/ante/commit/17c800a9656d28db16845897242620675ee822e6))

- **test**: #1941 error_drift_allowlist.yaml anchor 갱신
  ([#1942](https://github.com/joshua-jingu-lee/ante/pull/1942),
  [`b8cea12`](https://github.com/joshua-jingu-lee/ante/commit/b8cea12b2d6ae9bab607fa6d613b405418547493))

- **test**: Align trade_info_not_found exit code with #1515 invariant
  ([#1527](https://github.com/joshua-jingu-lee/ante/pull/1527),
  [`a11ef76`](https://github.com/joshua-jingu-lee/ante/commit/a11ef7698b1d38b3afabeb6b0a50ed3b77b980ef))

- **test**: Align treasury_allocate_fail exit code with #1517 invariant
  ([#1530](https://github.com/joshua-jingu-lee/ante/pull/1530),
  [`e9e2107`](https://github.com/joshua-jingu-lee/ante/commit/e9e2107d54787adb5b340031d93aaeeccccde828))

- **test**: Align two stale exit-code assertions with #1515 missing-resource invariant
  ([#1526](https://github.com/joshua-jingu-lee/ante/pull/1526),
  [`f425d71`](https://github.com/joshua-jingu-lee/ante/commit/f425d71f8aaaf351709309ab8229c40a8954b616))

- **test**: Scope BotManager cooldown sleep patch to avoid affecting Bot._run_loop (#1456 codex
  review) ([#1478](https://github.com/joshua-jingu-lee/ante/pull/1478),
  [`88015b4`](https://github.com/joshua-jingu-lee/ante/commit/88015b45be0deb674a35490c409e5452907097b9))

- **test**: Use stdout for click split assertions
  ([#1150](https://github.com/joshua-jingu-lee/ante/pull/1150),
  [`2e2dd3f`](https://github.com/joshua-jingu-lee/ante/commit/2e2dd3fcca018370d8ea5434f5804efac4454978))

- **trade**: #1946 fill catch-up 실패 barrier 우회·EOD 만료 미호출 수정
  ([#1953](https://github.com/joshua-jingu-lee/ante/pull/1953),
  [`9f548b4`](https://github.com/joshua-jingu-lee/ante/commit/9f548b463cf4f6794fc788270a58cfa084471eb4))

- **trade**: #1946 fill-recovery poll-first 순서 invariant로 startup 복구완전성/barrier 종합 수정
  ([#1953](https://github.com/joshua-jingu-lee/ante/pull/1953),
  [`9f548b4`](https://github.com/joshua-jingu-lee/ante/commit/9f548b463cf4f6794fc788270a58cfa084471eb4))

- **trade**: #1948 expire_stale UPDATE…RETURNING으로 TOCTOU evict race 제거
  ([#1959](https://github.com/joshua-jingu-lee/ante/pull/1959),
  [`241e558`](https://github.com/joshua-jingu-lee/ante/commit/241e558b76aead43f103aefca0e2ae7affd25d79))

- **trade**: #1950 reconciler self-submitted fill 구분 (외부 매수 오분류 방지)
  ([#1956](https://github.com/joshua-jingu-lee/ante/pull/1956),
  [`8576711`](https://github.com/joshua-jingu-lee/ante/commit/857671147468454bd6f985265de95d3a94b5fbb2))

- **treasury**: #1947 매수 부분체결 비례 정산 ([#1954](https://github.com/joshua-jingu-lee/ante/pull/1954),
  [`f2d25fb`](https://github.com/joshua-jingu-lee/ante/commit/f2d25fb6a5fa02d66861b9271a408273b5d2c98c))

- **treasury**: Emit terminal reject for market buy without quote (#1292)
  ([#1294](https://github.com/joshua-jingu-lee/ante/pull/1294),
  [`5d3de66`](https://github.com/joshua-jingu-lee/ante/commit/5d3de662c8ddbdef583184da6efd961d540fa47e))

- **treasury**: Enforce finite-positive amount at Web API + Treasury service entry
  ([#1432](https://github.com/joshua-jingu-lee/ante/pull/1432),
  [`5292d08`](https://github.com/joshua-jingu-lee/ante/commit/5292d08e628a93feff266a67287c7297aae2e7fa))

- **treasury**: Normalize transaction type vocabulary (5-value) (#1476)
  ([#1482](https://github.com/joshua-jingu-lee/ante/pull/1482),
  [`9c24fe9`](https://github.com/joshua-jingu-lee/ante/commit/9c24fe933726d7837335bba5c11524f200a20084))

- **treasury**: Normalize transaction type vocabulary (5-value:
  allocate/deallocate/release/fill/bot_stopped_release)
  ([#1482](https://github.com/joshua-jingu-lee/ante/pull/1482),
  [`9c24fe9`](https://github.com/joshua-jingu-lee/ante/commit/9c24fe933726d7837335bba5c11524f200a20084))

- **treasury**: Reject non-finite/negative balance at API and service
  ([#1343](https://github.com/joshua-jingu-lee/ante/pull/1343),
  [`db12f00`](https://github.com/joshua-jingu-lee/ante/commit/db12f0099c75df83a2ab53cbe7ebdb689f8137d0))

- **treasury**: Reject non-finite/negative balance at API and service (#1340)
  ([#1343](https://github.com/joshua-jingu-lee/ante/pull/1343),
  [`db12f00`](https://github.com/joshua-jingu-lee/ante/commit/db12f0099c75df83a2ab53cbe7ebdb689f8137d0))

- **treasury**: Reject non-finite/non-positive market buy quote (#1333 P2)
  ([#1350](https://github.com/joshua-jingu-lee/ante/pull/1350),
  [`563df47`](https://github.com/joshua-jingu-lee/ante/commit/563df4742324680ade2126daf6aa4c7b5bb466f5))

- **treasury**: Skip reserve for buy stop/stop_limit at registration
  ([#1348](https://github.com/joshua-jingu-lee/ante/pull/1348),
  [`ce0efab`](https://github.com/joshua-jingu-lee/ante/commit/ce0efab8cc58277b3323d1560ba8f8ef87ccd8ed))

- **treasury**: Skip reserve for buy stop/stop_limit at registration (#1337)
  ([#1348](https://github.com/joshua-jingu-lee/ante/pull/1348),
  [`ce0efab`](https://github.com/joshua-jingu-lee/ante/commit/ce0efab8cc58277b3323d1560ba8f8ef87ccd8ed))

- **treasury,trade**: Scope sync/daily-report aggregations to single account (#1240 review)
  ([#1243](https://github.com/joshua-jingu-lee/ante/pull/1243),
  [`83dcd3b`](https://github.com/joshua-jingu-lee/ante/commit/83dcd3b206acade00a7abfd8eb285f0036def1af))

- **web**: 422 validation 응답의 거부 입력 값 반사 차단 (#1629 L1)
  ([#1644](https://github.com/joshua-jingu-lee/ante/pull/1644),
  [`28953f6`](https://github.com/joshua-jingu-lee/ante/commit/28953f6ddf1d9017cd9969d374bbd0b4d41e272b))

- **web**: Accept ante_session cookie auth in POST /api/members
  ([#1346](https://github.com/joshua-jingu-lee/ante/pull/1346),
  [`db30498`](https://github.com/joshua-jingu-lee/ante/commit/db30498a8f3cc526fa01dfe69272a5bd2115bb5b))

- **web**: Accept JSON null body on suspend route as default reason
  ([#1362](https://github.com/joshua-jingu-lee/ante/pull/1362),
  [`7bbea7a`](https://github.com/joshua-jingu-lee/ante/commit/7bbea7ac240db8e95d9a8ce5f5d338833112301f))

- **web**: Align PUT /api/accounts/{id} no-op responses to 422 (#1152)
  ([#1168](https://github.com/joshua-jingu-lee/ante/pull/1168),
  [`6c34618`](https://github.com/joshua-jingu-lee/ante/commit/6c346186251a53293cc77e87a067f3af3b684ebb))

- **web**: Align PUT no-op responses to 422 (breaking change #1152)
  ([#1168](https://github.com/joshua-jingu-lee/ante/pull/1168),
  [`6c34618`](https://github.com/joshua-jingu-lee/ante/commit/6c346186251a53293cc77e87a067f3af3b684ebb))

- **web**: Convert mutable validation errors to 422 explicitly (attempt 5)
  ([#1146](https://github.com/joshua-jingu-lee/ante/pull/1146),
  [`57780c2`](https://github.com/joshua-jingu-lee/ante/commit/57780c2882e197e8ce139140bb355b8a0049bc3f))

- **web**: Dataset_id path traversal 차단 — 2계층 path-safe 방어 (#1631)
  ([#1642](https://github.com/joshua-jingu-lee/ante/pull/1642),
  [`c0aa6ed`](https://github.com/joshua-jingu-lee/ante/commit/c0aa6ed6e5bf74580adb0c73f2ff97cea3b30406))

- **web**: Drop unreachable POST/DELETE success contract on accounts cold-path
  ([#1146](https://github.com/joshua-jingu-lee/ante/pull/1146),
  [`57780c2`](https://github.com/joshua-jingu-lee/ante/commit/57780c2882e197e8ce139140bb355b8a0049bc3f))

- **web**: Enforce auth check before body validation in POST /api/members
  ([#1346](https://github.com/joshua-jingu-lee/ante/pull/1346),
  [`db30498`](https://github.com/joshua-jingu-lee/ante/commit/db30498a8f3cc526fa01dfe69272a5bd2115bb5b))

- **web**: Enforce cold-path invariants on account routes (attempt 3)
  ([#1146](https://github.com/joshua-jingu-lee/ante/pull/1146),
  [`57780c2`](https://github.com/joshua-jingu-lee/ante/commit/57780c2882e197e8ce139140bb355b8a0049bc3f))

- **web**: Expose MemberCreateRequest in OpenAPI components (#1339 P1)
  ([#1346](https://github.com/joshua-jingu-lee/ante/pull/1346),
  [`db30498`](https://github.com/joshua-jingu-lee/ante/commit/db30498a8f3cc526fa01dfe69272a5bd2115bb5b))

- **web**: Forbid extra fields in MemberCreateRequest (#1339 P3)
  ([#1346](https://github.com/joshua-jingu-lee/ante/pull/1346),
  [`db30498`](https://github.com/joshua-jingu-lee/ante/commit/db30498a8f3cc526fa01dfe69272a5bd2115bb5b))

- **web**: Lazy resolve account_service in PUT to preserve cold-path 409 (attempt 6)
  ([#1146](https://github.com/joshua-jingu-lee/ante/pull/1146),
  [`57780c2`](https://github.com/joshua-jingu-lee/ante/commit/57780c2882e197e8ce139140bb355b8a0049bc3f))

- **web**: Member API가 token/password/recovery hash를 응답에 노출 (#1627)
  ([#1640](https://github.com/joshua-jingu-lee/ante/pull/1640),
  [`7e079b5`](https://github.com/joshua-jingu-lee/ante/commit/7e079b5fe1c299dd60b2f8ce817d5a09696123d5))

- **web**: Mirror session caller into request.state.member_id (#1339 P2)
  ([#1346](https://github.com/joshua-jingu-lee/ante/pull/1346),
  [`db30498`](https://github.com/joshua-jingu-lee/ante/commit/db30498a8f3cc526fa01dfe69272a5bd2115bb5b))

- **web**: Move account_id guard before strategy registry lookup in get_strategy_performance
  ([#1637](https://github.com/joshua-jingu-lee/ante/pull/1637),
  [`1dc7f47`](https://github.com/joshua-jingu-lee/ante/commit/1dc7f47493f99a36ed778bfc5dd3a2108f9aa0d1))

- **web**: Normalize extra_forbidden loc trailing segment at runtime (#1650)
  ([#1652](https://github.com/joshua-jingu-lee/ante/pull/1652),
  [`d24d115`](https://github.com/joshua-jingu-lee/ante/commit/d24d1157c7decf6cafeff2192316310b071166c0))

- **web**: POST /api/members invalid member_type을 422로 거부 (#1628)
  ([#1641](https://github.com/joshua-jingu-lee/ante/pull/1641),
  [`c7d43e1`](https://github.com/joshua-jingu-lee/ante/commit/c7d43e1d0c80c3eacd1f967091e734f25f54bb13))

- **web**: Preserve nullable suspend body contract in OpenAPI schema
  ([#1362](https://github.com/joshua-jingu-lee/ante/pull/1362),
  [`7bbea7a`](https://github.com/joshua-jingu-lee/ante/commit/7bbea7ac240db8e95d9a8ce5f5d338833112301f))

- **web**: Register AccountSuspendRequest in OpenAPI components for suspend route
  ([#1362](https://github.com/joshua-jingu-lee/ante/pull/1362),
  [`7bbea7a`](https://github.com/joshua-jingu-lee/ante/commit/7bbea7ac240db8e95d9a8ce5f5d338833112301f))

- **web**: Register ErrorResponse model on PUT account error responses (attempt 7)
  ([#1146](https://github.com/joshua-jingu-lee/ante/pull/1146),
  [`57780c2`](https://github.com/joshua-jingu-lee/ante/commit/57780c2882e197e8ce139140bb355b8a0049bc3f))

- **web**: Reject extra body on POST /api/accounts/{id}/activate
  ([#1521](https://github.com/joshua-jingu-lee/ante/pull/1521),
  [`a614dfc`](https://github.com/joshua-jingu-lee/ante/commit/a614dfc7f9657edbff44276d33e71170a69c5b8e))

- **web**: Reject invalid timeframe filter in datasets API
  ([#1601](https://github.com/joshua-jingu-lee/ante/pull/1601),
  [`e5482b8`](https://github.com/joshua-jingu-lee/ante/commit/e5482b8f39a472113f08569ab03e5f573ef0adb6))

- **web**: Reject invalid timeframe filter in datasets API (#1594)
  ([#1601](https://github.com/joshua-jingu-lee/ante/pull/1601),
  [`e5482b8`](https://github.com/joshua-jingu-lee/ante/commit/e5482b8f39a472113f08569ab03e5f573ef0adb6))

- **web**: Reject inverted date range across 4 read APIs
  ([#1607](https://github.com/joshua-jingu-lee/ante/pull/1607),
  [`e8ca3ba`](https://github.com/joshua-jingu-lee/ante/commit/e8ca3ba8e1c418fcb39d5d905533c985a30eb2dc))

- **web**: Reject inverted date range across 4 read APIs (#1595)
  ([#1607](https://github.com/joshua-jingu-lee/ante/pull/1607),
  [`e8ca3ba`](https://github.com/joshua-jingu-lee/ante/commit/e8ca3ba8e1c418fcb39d5d905533c985a30eb2dc))

- **web**: Reject negative pagination limit across list endpoints (#1356)
  ([#1366](https://github.com/joshua-jingu-lee/ante/pull/1366),
  [`9b12c08`](https://github.com/joshua-jingu-lee/ante/commit/9b12c087492aab7001ca46ea65f8c2b4f664f6f6))

- **web**: Reject provided runtime-invalid account_id at read-API ingress
  ([#1637](https://github.com/joshua-jingu-lee/ante/pull/1637),
  [`1dc7f47`](https://github.com/joshua-jingu-lee/ante/commit/1dc7f47493f99a36ed778bfc5dd3a2108f9aa0d1))

- **web**: Reject provided runtime-invalid account_id at read-API ingress (#1624)
  ([#1637](https://github.com/joshua-jingu-lee/ante/pull/1637),
  [`1dc7f47`](https://github.com/joshua-jingu-lee/ante/commit/1dc7f47493f99a36ed778bfc5dd3a2108f9aa0d1))

- **web**: Reject unknown approval list status with 422 via ApprovalStatus enum (#1357)
  ([#1367](https://github.com/joshua-jingu-lee/ante/pull/1367),
  [`a260b80`](https://github.com/joshua-jingu-lee/ante/commit/a260b8060d86978654398c41957154bc65777122))

- **web**: Reject unknown data_type with 422 on data endpoints (#1354)
  ([#1364](https://github.com/joshua-jingu-lee/ante/pull/1364),
  [`b09a585`](https://github.com/joshua-jingu-lee/ante/commit/b09a58503b5b46cd1615a597d18340513d0c37ab))

- **web**: Reject unknown member list type/status with 422 via enum (#1358)
  ([#1368](https://github.com/joshua-jingu-lee/ante/pull/1368),
  [`6276eca`](https://github.com/joshua-jingu-lee/ante/commit/6276ecadcc206c679580a69c6fb90838c0bed81e))

- **web**: Reject unsupported report submit `sections` field (#1632)
  ([#1645](https://github.com/joshua-jingu-lee/ante/pull/1645),
  [`e97535d`](https://github.com/joshua-jingu-lee/ante/commit/e97535d7ef4665a255826cb10b10d6958c1a0e8d))

- **web**: Relax orderable typing for mypy src in date_params
  ([#1607](https://github.com/joshua-jingu-lee/ante/pull/1607),
  [`e8ca3ba`](https://github.com/joshua-jingu-lee/ante/commit/e8ca3ba8e1c418fcb39d5d905533c985a30eb2dc))

- **web**: Require auth for POST /api/members (#1339)
  ([#1346](https://github.com/joshua-jingu-lee/ante/pull/1346),
  [`db30498`](https://github.com/joshua-jingu-lee/ante/commit/db30498a8f3cc526fa01dfe69272a5bd2115bb5b))

- **web**: Require authenticated master for POST /api/members
  ([#1346](https://github.com/joshua-jingu-lee/ante/pull/1346),
  [`db30498`](https://github.com/joshua-jingu-lee/ante/commit/db30498a8f3cc526fa01dfe69272a5bd2115bb5b))

- **web**: Require authenticated master for runtime mutation routes
  ([#1362](https://github.com/joshua-jingu-lee/ante/pull/1362),
  [`7bbea7a`](https://github.com/joshua-jingu-lee/ante/commit/7bbea7ac240db8e95d9a8ce5f5d338833112301f))

- **web**: Require authenticated master for runtime mutation routes (#1352)
  ([#1362](https://github.com/joshua-jingu-lee/ante/pull/1362),
  [`7bbea7a`](https://github.com/joshua-jingu-lee/ante/commit/7bbea7ac240db8e95d9a8ce5f5d338833112301f))

- **web**: Require config:write or master/human auth for PUT /api/config/{key} (#1373)
  ([#1383](https://github.com/joshua-jingu-lee/ante/pull/1383),
  [`1525c9c`](https://github.com/joshua-jingu-lee/ante/commit/1525c9c7c5d983a8854e8d9d3068008089d185d0))

- **web**: Require master auth for bot create/delete (#1371)
  ([#1381](https://github.com/joshua-jingu-lee/ante/pull/1381),
  [`74b9995`](https://github.com/joshua-jingu-lee/ante/commit/74b99953cdc74850c9db4ac789900497a2b6d62a))

- **web**: Require master auth for GET /api/audit
  ([#1369](https://github.com/joshua-jingu-lee/ante/pull/1369),
  [`b81a785`](https://github.com/joshua-jingu-lee/ante/commit/b81a7859d9fff59e7fa970c76dcdecead0f41872))

- **web**: Require master auth for PATCH /api/members/{id}/password (#1377)
  ([#1387](https://github.com/joshua-jingu-lee/ante/pull/1387),
  [`13c5e09`](https://github.com/joshua-jingu-lee/ante/commit/13c5e098c3e8da3aa26bb250054ffd9cebaa88bd))

- **web**: Require master auth for PUT /api/accounts/{id}/rules/{type} (#1376)
  ([#1386](https://github.com/joshua-jingu-lee/ante/pull/1386),
  [`05235df`](https://github.com/joshua-jingu-lee/ante/commit/05235df0b63f1efd3e68640b7c88266662f1619b))

- **web**: Require master auth for system halt/clear-halt (#1375)
  ([#1385](https://github.com/joshua-jingu-lee/ante/pull/1385),
  [`651a4ce`](https://github.com/joshua-jingu-lee/ante/commit/651a4ceb61fcbce27b9b882fce135069f6e10986))

- **web**: Require master auth for treasury budget allocate/deallocate (#1372)
  ([#1382](https://github.com/joshua-jingu-lee/ante/pull/1382),
  [`591be51`](https://github.com/joshua-jingu-lee/ante/commit/591be5170269f1a577dfbb9f12867454b159c17a))

- **web**: Require master/human/report:write auth for POST /api/reports (#1374)
  ([#1384](https://github.com/joshua-jingu-lee/ante/pull/1384),
  [`3282074`](https://github.com/joshua-jingu-lee/ante/commit/3282074a660b05ebde3b9898aab1a41837174099))

- **web**: Require master/human/strategy:write auth for PATCH /api/strategies/{id}/status (#1378)
  ([#1388](https://github.com/joshua-jingu-lee/ante/pull/1388),
  [`72c0489`](https://github.com/joshua-jingu-lee/ante/commit/72c0489c4b2357a55a996f3d49b2e0fd8332e1a9))

- **web**: Restore mutable field type validation on PUT account (attempt 9)
  ([#1146](https://github.com/joshua-jingu-lee/ante/pull/1146),
  [`57780c2`](https://github.com/joshua-jingu-lee/ante/commit/57780c2882e197e8ce139140bb355b8a0049bc3f))

- **web**: Split account PUT mutable schema and convert ValidationError to 422 (attempt 4)
  ([#1146](https://github.com/joshua-jingu-lee/ante/pull/1146),
  [`57780c2`](https://github.com/joshua-jingu-lee/ante/commit/57780c2882e197e8ce139140bb355b8a0049bc3f))

- **web**: Validate pagination limit/offset on list endpoints
  ([#1366](https://github.com/joshua-jingu-lee/ante/pull/1366),
  [`9b12c08`](https://github.com/joshua-jingu-lee/ante/commit/9b12c087492aab7001ca46ea65f8c2b4f664f6f6))

- **web**: Validate timeframe before store-None guard in datasets API
  ([#1601](https://github.com/joshua-jingu-lee/ante/pull/1601),
  [`e5482b8`](https://github.com/joshua-jingu-lee/ante/commit/e5482b8f39a472113f08569ab03e5f573ef0adb6))

- **web,build**: Unify suspend raw-body pattern and restore pip_freeze snapshot
  ([#1362](https://github.com/joshua-jingu-lee/ante/pull/1362),
  [`7bbea7a`](https://github.com/joshua-jingu-lee/ante/commit/7bbea7ac240db8e95d9a8ce5f5d338833112301f))

- **web-api**: #1654 PUT /api/accounts unknown-key 422 detail caller key 미반사 (F3)
  ([#1664](https://github.com/joshua-jingu-lee/ante/pull/1664),
  [`c5e7479`](https://github.com/joshua-jingu-lee/ante/commit/c5e74798707b5d8a8b79a2e12d6b6ff1ad93a6be))

- **web-api**: Add anyOf strategy_id/strategy_name to BOT_CREATE_REQUEST_SCHEMA (codex FAIL r1)
  ([#1448](https://github.com/joshua-jingu-lee/ante/pull/1448),
  [`62e403a`](https://github.com/joshua-jingu-lee/ante/commit/62e403ac25369a6a69ecf47f3bea4f3e35dafa8f))

- **web-api**: Correct bot logs pagination + tz-normalize date filters (codex FAIL r1)
  ([#1449](https://github.com/joshua-jingu-lee/ante/pull/1449),
  [`8b6b49a`](https://github.com/joshua-jingu-lee/ante/commit/8b6b49a1cfacbcf9a4f5de6cd55ca71137522fa9))

- **web-api**: Enforce BotCreateRequest extra=forbid + strategy required + serialize ValidationError
  (#1436) ([#1448](https://github.com/joshua-jingu-lee/ante/pull/1448),
  [`62e403a`](https://github.com/joshua-jingu-lee/ante/commit/62e403ac25369a6a69ecf47f3bea4f3e35dafa8f))

- **web-api**: Enforce BotCreateRequest extra=forbid + strategy required, sync spec
  ([#1448](https://github.com/joshua-jingu-lee/ante/pull/1448),
  [`62e403a`](https://github.com/joshua-jingu-lee/ante/commit/62e403ac25369a6a69ecf47f3bea4f3e35dafa8f))

- **web-api**: Enforce finite-positive budget on BotCreateRequest/BotUpdateRequest (#1435)
  ([#1447](https://github.com/joshua-jingu-lee/ante/pull/1447),
  [`d077a1f`](https://github.com/joshua-jingu-lee/ante/commit/d077a1feb0ec503e9969cb10793703d55b027424))

- **web-api**: Enforce HaltRequest/ClearHaltRequest extra=forbid (#1442)
  ([#1455](https://github.com/joshua-jingu-lee/ante/pull/1455),
  [`452a4f6`](https://github.com/joshua-jingu-lee/ante/commit/452a4f6fadce766c25ea16b4ec375a0c9fceb872))

- **web-api**: Enforce ISO 8601 on audit date filter
  ([#1444](https://github.com/joshua-jingu-lee/ante/pull/1444),
  [`f2dae4f`](https://github.com/joshua-jingu-lee/ante/commit/f2dae4f4b5b8d5d2742c988185db17f557340976))

- **web-api**: Enforce ISO 8601 on audit date filter (#1414)
  ([#1444](https://github.com/joshua-jingu-lee/ante/pull/1444),
  [`f2dae4f`](https://github.com/joshua-jingu-lee/ante/commit/f2dae4f4b5b8d5d2742c988185db17f557340976))

- **web-api**: Enforce StatusUpdateRequest extra=forbid + Literal transition (#1441)
  ([#1453](https://github.com/joshua-jingu-lee/ante/pull/1453),
  [`1f8e410`](https://github.com/joshua-jingu-lee/ante/commit/1f8e410e368c82961f90572be8e1303af5f7d5d3))

- **web-api**: Expose ApprovalStatusUpdate status enum (approved/rejected) (#1434)
  ([#1446](https://github.com/joshua-jingu-lee/ante/pull/1446),
  [`cc0f334`](https://github.com/joshua-jingu-lee/ante/commit/cc0f334d324bb1ad322501e623ecc72dc2e7bb46))

- **web-api**: Expose strategies/validate + approvals/status requestBody and validate path type
  ([#1431](https://github.com/joshua-jingu-lee/ante/pull/1431),
  [`5a03510`](https://github.com/joshua-jingu-lee/ante/commit/5a03510b88b63c98884731c0cb0bb116f9cb6674))

- **web-api**: Expose total and offset/start_date/end_date for bot logs
  ([#1449](https://github.com/joshua-jingu-lee/ante/pull/1449),
  [`8b6b49a`](https://github.com/joshua-jingu-lee/ante/commit/8b6b49a1cfacbcf9a4f5de6cd55ca71137522fa9))

- **web-api**: Expose total/offset/date filters for bot logs API (#1437)
  ([#1449](https://github.com/joshua-jingu-lee/ante/pull/1449),
  [`8b6b49a`](https://github.com/joshua-jingu-lee/ante/commit/8b6b49a1cfacbcf9a4f5de6cd55ca71137522fa9))

- **web-api**: Keyword-only until/offset + SQL payload filter for bot logs (codex FAIL r2)
  ([#1449](https://github.com/joshua-jingu-lee/ante/pull/1449),
  [`8b6b49a`](https://github.com/joshua-jingu-lee/ante/commit/8b6b49a1cfacbcf9a4f5de6cd55ca71137522fa9))

- **web-api**: Map bot create budget failure to 422 with rollback
  ([#1345](https://github.com/joshua-jingu-lee/ante/pull/1345),
  [`016a328`](https://github.com/joshua-jingu-lee/ante/commit/016a3285cb2900a83636eaf6397040b841f4bf6a))

- **web-api**: Narrow anyOf branches with properties for BotCreateRequest (codex FAIL r2)
  ([#1448](https://github.com/joshua-jingu-lee/ante/pull/1448),
  [`62e403a`](https://github.com/joshua-jingu-lee/ante/commit/62e403ac25369a6a69ecf47f3bea4f3e35dafa8f))

- **web-api**: Narrow DELETE dataset data_type to Literal['ohlcv','fundamental'] (#1438)
  ([#1450](https://github.com/joshua-jingu-lee/ante/pull/1450),
  [`05633f3`](https://github.com/joshua-jingu-lee/ante/commit/05633f35675ad5bceccd79c7225eda4f85f2ddc7))

- **web-api**: Reject non-zero-padded date strings in query date helper (codex FAIL r1)
  ([#1452](https://github.com/joshua-jingu-lee/ante/pull/1452),
  [`e258c2a`](https://github.com/joshua-jingu-lee/ante/commit/e258c2aa9ae4386ca45c34ddca4cf1c3630fe40c))

- **web-api**: Remove in-memory cap so ring buffer-bounded logs return all matching events (codex
  r3) ([#1449](https://github.com/joshua-jingu-lee/ante/pull/1449),
  [`8b6b49a`](https://github.com/joshua-jingu-lee/ante/commit/8b6b49a1cfacbcf9a4f5de6cd55ca71137522fa9))

- **web-api**: Serialize ValidationError detail for BotCreateRequest model_validator (codex FAIL r3)
  ([#1448](https://github.com/joshua-jingu-lee/ante/pull/1448),
  [`62e403a`](https://github.com/joshua-jingu-lee/ante/commit/62e403ac25369a6a69ecf47f3bea4f3e35dafa8f))

- **web-api**: Validate ISO date params for portfolio/treasury endpoints
  ([#1452](https://github.com/joshua-jingu-lee/ante/pull/1452),
  [`e258c2a`](https://github.com/joshua-jingu-lee/ante/commit/e258c2aa9ae4386ca45c34ddca4cf1c3630fe40c))

- **web-api**: Validate ISO date params for portfolio/treasury endpoints (#1440)
  ([#1452](https://github.com/joshua-jingu-lee/ante/pull/1452),
  [`e258c2a`](https://github.com/joshua-jingu-lee/ante/commit/e258c2aa9ae4386ca45c34ddca4cf1c3630fe40c))

- **web-api,bot**: Enforce runtime control range on BotUpdateRequest/BotConfig
  ([#1478](https://github.com/joshua-jingu-lee/ante/pull/1478),
  [`88015b4`](https://github.com/joshua-jingu-lee/ante/commit/88015b45be0deb674a35490c409e5452907097b9))

- **web-api,bot**: Enforce runtime control range on BotUpdateRequest/BotConfig (#1456)
  ([#1478](https://github.com/joshua-jingu-lee/ante/pull/1478),
  [`88015b4`](https://github.com/joshua-jingu-lee/ante/commit/88015b45be0deb674a35490c409e5452907097b9))

- **web-api,member**: Enforce MemberRole enum on MemberCreateRequest + service register (#1465)
  ([#1479](https://github.com/joshua-jingu-lee/ante/pull/1479),
  [`565df1e`](https://github.com/joshua-jingu-lee/ante/commit/565df1ec2725948dd867304f0c810d602661a4d2))

- **web-api,treasury**: Enforce Literal vocabulary on GET /api/treasury/transactions type filter
  (#1477) ([#1485](https://github.com/joshua-jingu-lee/ante/pull/1485),
  [`1f6ea68`](https://github.com/joshua-jingu-lee/ante/commit/1f6ea681a9e00c74821b709b8451b6155e470f72))

### Chores

- #1843-4 regenerate project-structure.md (treasury equivalence test 등록)
  ([#1868](https://github.com/joshua-jingu-lee/ante/pull/1868),
  [`4f23925`](https://github.com/joshua-jingu-lee/ante/commit/4f2392529cd8f6380ff6e641c86037e6af4bc46b))

- Re-trigger CI ([#1884](https://github.com/joshua-jingu-lee/ante/pull/1884),
  [`2928536`](https://github.com/joshua-jingu-lee/ante/commit/292853678b3c1b5be6634e7dcfacd9045a4b473d))

- Re-trigger CI (post-100min wait) ([#1884](https://github.com/joshua-jingu-lee/ante/pull/1884),
  [`2928536`](https://github.com/joshua-jingu-lee/ante/commit/292853678b3c1b5be6634e7dcfacd9045a4b473d))

- Trigger workflows ([#1136](https://github.com/joshua-jingu-lee/ante/pull/1136),
  [`4792745`](https://github.com/joshua-jingu-lee/ante/commit/4792745743af86d1f682a248314d25e33bbb66b2))

- Trigger workflows after bot fix ([#1136](https://github.com/joshua-jingu-lee/ante/pull/1136),
  [`4792745`](https://github.com/joshua-jingu-lee/ante/commit/4792745743af86d1f682a248314d25e33bbb66b2))

- Trigger workflows after bot fix attempt 2
  ([#1136](https://github.com/joshua-jingu-lee/ante/pull/1136),
  [`4792745`](https://github.com/joshua-jingu-lee/ante/commit/4792745743af86d1f682a248314d25e33bbb66b2))

- **ci**: Align GitHub Actions Python runtime to 3.13 (#1188)
  ([#1198](https://github.com/joshua-jingu-lee/ante/pull/1198),
  [`fbfe942`](https://github.com/joshua-jingu-lee/ante/commit/fbfe942b33ef464e68483f940cf0a5c24b94ee13))

- **ci**: Extend merge-gate ci wait to 90 minutes
  ([#1154](https://github.com/joshua-jingu-lee/ante/pull/1154),
  [`c2666c2`](https://github.com/joshua-jingu-lee/ante/commit/c2666c25c87870f08811df2443f2287eca4c03b1))

- **ci**: Guard merge-gate with ci success wait
  ([#1154](https://github.com/joshua-jingu-lee/ante/pull/1154),
  [`c2666c2`](https://github.com/joshua-jingu-lee/ante/commit/c2666c25c87870f08811df2443f2287eca4c03b1))

- **ci**: Mark AI review as advisory check
  ([#1154](https://github.com/joshua-jingu-lee/ante/pull/1154),
  [`c2666c2`](https://github.com/joshua-jingu-lee/ante/commit/c2666c25c87870f08811df2443f2287eca4c03b1))

- **ci**: Rely on auto-merge required-check wait
  ([#1154](https://github.com/joshua-jingu-lee/ante/pull/1154),
  [`c2666c2`](https://github.com/joshua-jingu-lee/ante/commit/c2666c25c87870f08811df2443f2287eca4c03b1))

- **config,main,cli**: Introduce runtime path canonical resolver (single-canonical cutover) (#1157)
  ([#1182](https://github.com/joshua-jingu-lee/ante/pull/1182),
  [`290bcff`](https://github.com/joshua-jingu-lee/ante/commit/290bcff5afbd8688b251a0cc3c1764cb2071fac8))

- **deploy**: Remove staging compose override
  ([`1a6e694`](https://github.com/joshua-jingu-lee/ante/commit/1a6e694f22a50cc89ba372d9ee4babf48a551a56))

- **deps**: Align pyproject to Python 3.13 single runtime contract
  ([#1199](https://github.com/joshua-jingu-lee/ante/pull/1199),
  [`8fc0685`](https://github.com/joshua-jingu-lee/ante/commit/8fc0685d886f41f72ff51a80d525e3df81579adf))

- **deps,ipc,docker**: Align project to Python 3.13 single runtime
  ([#1199](https://github.com/joshua-jingu-lee/ante/pull/1199),
  [`8fc0685`](https://github.com/joshua-jingu-lee/ante/commit/8fc0685d886f41f72ff51a80d525e3df81579adf))

- **dev**: Add local Python 3.13 runtime drift guards (#1190)
  ([#1200](https://github.com/joshua-jingu-lee/ante/pull/1200),
  [`797a769`](https://github.com/joshua-jingu-lee/ante/commit/797a7696d85a5346c9934e245cb91fa6b5d4b060))

- **docker**: Bump runtime base image to python:3.13-slim
  ([#1199](https://github.com/joshua-jingu-lee/ante/pull/1199),
  [`8fc0685`](https://github.com/joshua-jingu-lee/ante/commit/8fc0685d886f41f72ff51a80d525e3df81579adf))

- **docs**: #1899 attempt 2 — required checks 확장값을 Gate C/git-workflow/release 게이트 문서에 일관 반영 (codex
  review finding) ([#1908](https://github.com/joshua-jingu-lee/ante/pull/1908),
  [`dafd2ab`](https://github.com/joshua-jingu-lee/ante/commit/dafd2ab59950d2bb3ddbe07dd97c23f81735f763))

- **docs**: #1899 attempt 3 — Rationale 정정 (GitHub required check 동작에 맞게 방어 근거 명확화)
  ([#1908](https://github.com/joshua-jingu-lee/ante/pull/1908),
  [`dafd2ab`](https://github.com/joshua-jingu-lee/ante/commit/dafd2ab59950d2bb3ddbe07dd97c23f81735f763))

- **docs**: #1899 merge-safety required-checks 컨텍스트 확장 권장값 (옵션 B docs only)
  ([#1908](https://github.com/joshua-jingu-lee/ante/pull/1908),
  [`dafd2ab`](https://github.com/joshua-jingu-lee/ante/commit/dafd2ab59950d2bb3ddbe07dd97c23f81735f763))

- **frontend**: Regenerate OpenAPI + types for #1335 422/500 description
  ([#1345](https://github.com/joshua-jingu-lee/ante/pull/1345),
  [`016a328`](https://github.com/joshua-jingu-lee/ante/commit/016a3285cb2900a83636eaf6397040b841f4bf6a))

- **frontend**: Regenerate OpenAPI artifacts for BotInfo.config
  ([#1501](https://github.com/joshua-jingu-lee/ante/pull/1501),
  [`64c7d45`](https://github.com/joshua-jingu-lee/ante/commit/64c7d451fe5bf399f961b739c6f5aff6092dc022))

- **frontend**: Regenerate openapi.json + api.generated.ts for problem+json alignment
  ([#1180](https://github.com/joshua-jingu-lee/ante/pull/1180),
  [`19002a9`](https://github.com/joshua-jingu-lee/ante/commit/19002a996b8757b8fdba9e4e1b524e0ff017c982))

- **frontend**: Sync openapi.json and types for HH:MM pattern
  ([#1344](https://github.com/joshua-jingu-lee/ante/pull/1344),
  [`1dd1cda`](https://github.com/joshua-jingu-lee/ante/commit/1dd1cdacf78e408fff06431a6418e157db1a9064))

- **ipc**: Drop Python 3.11/3.12 compat branch and align IPC to 3.13 single runtime
  ([#1199](https://github.com/joshua-jingu-lee/ante/pull/1199),
  [`8fc0685`](https://github.com/joshua-jingu-lee/ante/commit/8fc0685d886f41f72ff51a80d525e3df81579adf))

- **openapi**: Include session cookie auth in MemberCreateRequest schema description (#1339 P3)
  ([#1346](https://github.com/joshua-jingu-lee/ante/pull/1346),
  [`db30498`](https://github.com/joshua-jingu-lee/ante/commit/db30498a8f3cc526fa01dfe69272a5bd2115bb5b))

- **openapi**: Regenerate frontend openapi.json + TS types
  ([#1350](https://github.com/joshua-jingu-lee/ante/pull/1350),
  [`563df47`](https://github.com/joshua-jingu-lee/ante/commit/563df4742324680ade2126daf6aa4c7b5bb466f5))

- **openapi**: Regenerate openapi.json and types for balance minimum
  ([#1343](https://github.com/joshua-jingu-lee/ante/pull/1343),
  [`db12f00`](https://github.com/joshua-jingu-lee/ante/commit/db12f0099c75df83a2ab53cbe7ebdb689f8137d0))

- **release**: Bump version to 0.9.0 ([#1136](https://github.com/joshua-jingu-lee/ante/pull/1136),
  [`4792745`](https://github.com/joshua-jingu-lee/ante/commit/4792745743af86d1f682a248314d25e33bbb66b2))

- **runbook**: Align implement-issue advisory wording
  ([#1154](https://github.com/joshua-jingu-lee/ante/pull/1154),
  [`c2666c2`](https://github.com/joshua-jingu-lee/ante/commit/c2666c25c87870f08811df2443f2287eca4c03b1))

- **runbook**: Align release docs to advisory ai-review
  ([#1154](https://github.com/joshua-jingu-lee/ante/pull/1154),
  [`c2666c2`](https://github.com/joshua-jingu-lee/ante/commit/c2666c25c87870f08811df2443f2287eca4c03b1))

- **scripts**: Drop PR-phase-only AI review and fix support
  ([#1178](https://github.com/joshua-jingu-lee/ante/pull/1178),
  [`729950e`](https://github.com/joshua-jingu-lee/ante/commit/729950ecdb0fb267e30b44c0fb277b29346606dc))

- **spec,frontend**: Document PUT 422 semantics + regen artifacts
  ([#1168](https://github.com/joshua-jingu-lee/ante/pull/1168),
  [`6c34618`](https://github.com/joshua-jingu-lee/ante/commit/6c346186251a53293cc77e87a067f3af3b684ebb))

- **strategy**: Remove qa fixture strategies
  ([`040c1af`](https://github.com/joshua-jingu-lee/ante/commit/040c1af1bcea05413872a493e2b9a48bc5a38a08))

- **test**: Remove repo-local qa harness
  ([`c5fcb93`](https://github.com/joshua-jingu-lee/ante/commit/c5fcb93449871b0913f85b31f339fa3956509977))

- **web**: Align explicit 4xx/5xx OpenAPI content-type to application/problem+json (#1164)
  ([#1180](https://github.com/joshua-jingu-lee/ante/pull/1180),
  [`19002a9`](https://github.com/joshua-jingu-lee/ante/commit/19002a996b8757b8fdba9e4e1b524e0ff017c982))

- **web**: Apply ErrorResponse model to all explicit 4xx/5xx responses
  ([#1165](https://github.com/joshua-jingu-lee/ante/pull/1165),
  [`700a750`](https://github.com/joshua-jingu-lee/ante/commit/700a750c2a7dd0e7eb77038051c55c3f54900aff))

- **web**: Apply ErrorResponse model to all explicit 4xx/5xx responses (#1145)
  ([#1165](https://github.com/joshua-jingu-lee/ante/pull/1165),
  [`700a750`](https://github.com/joshua-jingu-lee/ante/commit/700a750c2a7dd0e7eb77038051c55c3f54900aff))

- **web**: Drop ANTE_TEST_MODE gate and legacy test_seed route
  ([#1165](https://github.com/joshua-jingu-lee/ante/pull/1165),
  [`700a750`](https://github.com/joshua-jingu-lee/ante/commit/700a750c2a7dd0e7eb77038051c55c3f54900aff))

- **workflows**: Remove claude/codex PR approval and auto-fix jobs
  ([#1178](https://github.com/joshua-jingu-lee/ante/pull/1178),
  [`729950e`](https://github.com/joshua-jingu-lee/ante/commit/729950ecdb0fb267e30b44c0fb277b29346606dc))

- **workflows,docs**: Retire PR-stage AI approval/auto-fix workers (#1167)
  ([#1178](https://github.com/joshua-jingu-lee/ante/pull/1178),
  [`729950e`](https://github.com/joshua-jingu-lee/ante/commit/729950ecdb0fb267e30b44c0fb277b29346606dc))

### Continuous Integration

- #1896 ci-gate job을 fail-fast로 강제하여 skip 우회 차단
  ([#1904](https://github.com/joshua-jingu-lee/ante/pull/1904),
  [`fe005c8`](https://github.com/joshua-jingu-lee/ante/commit/fe005c825d83b2fe2e22592e6bab39871cdb67e8))

- **frontend**: Gate api type boundary checks
  ([#1278](https://github.com/joshua-jingu-lee/ante/pull/1278),
  [`3b6b9aa`](https://github.com/joshua-jingu-lee/ante/commit/3b6b9aa0def4924754264abdff58c187e12280af))

- **release**: Align PyPI publish secret name
  ([#1962](https://github.com/joshua-jingu-lee/ante/pull/1962),
  [`78422a0`](https://github.com/joshua-jingu-lee/ante/commit/78422a0c0dfb6953f8ef0581631abdaab523211b))

### Documentation

- #1660 bot start/stop/status CLI 미구현(follow-up) 명시 (oracle literal surface)
  ([#1669](https://github.com/joshua-jingu-lee/ante/pull/1669),
  [`0c62d69`](https://github.com/joshua-jingu-lee/ante/commit/0c62d691a69799a3e6f1e9a2271886cefbf4be41))

- #1661 ROOT-ONLY 명령 trailing/bracketed --format json 예시를 root form으로 정렬
  ([#1670](https://github.com/joshua-jingu-lee/ante/pull/1670),
  [`a030c00`](https://github.com/joshua-jingu-lee/ante/commit/a030c00e535c10395a413dd7265abf5b312568b6))

- #1662 account-scoped CLI 필수 --account를 required 형태로 정렬
  ([#1671](https://github.com/joshua-jingu-lee/ante/pull/1671),
  [`3acdee9`](https://github.com/joshua-jingu-lee/ante/commit/3acdee93958c9ec88e3b6e30646c455d74a55e07))

- #1663 approval reopen 옵션 SSOT를 실제 Click(--body/--params)로 정정
  ([#1672](https://github.com/joshua-jingu-lee/ante/pull/1672),
  [`9470a9d`](https://github.com/joshua-jingu-lee/ante/commit/9470a9d5301649a40bb5b499577168758c62d58d))

- #1678 #1213 머지 후 stale 구현상태 노트 제거 (web-api/04-system-endpoints + ipc 대칭)
  ([#1685](https://github.com/joshua-jingu-lee/ante/pull/1685),
  [`a6be538`](https://github.com/joshua-jingu-lee/ante/commit/a6be5387612fabeda1e645831fbb7a430e31cf29))

- #1679 비활성 /api/notifications를 paginated-route 주장에서 제거 (06-pagination 수기 + project-structure 생성
  #1660 dual-fix) ([#1686](https://github.com/joshua-jingu-lee/ante/pull/1686),
  [`1b613a5`](https://github.com/joshua-jingu-lee/ante/commit/1b613a55918e7cb2604eaaae7a813b5a67e34731))

- #1680 generated project-structure CLI inventory stale 정합 (4 CLI 셀 #1660 dual-fix + 전체 재생성)
  ([#1687](https://github.com/joshua-jingu-lee/ante/pull/1687),
  [`5c6d6de`](https://github.com/joshua-jingu-lee/ante/commit/5c6d6de7f497c9fbbf4c942decdd8e9d228b96c2))

- #1691 outdated dashboard user-stories 제거 + 코드/문서/생성산출물 dual-fix
  ([#1695](https://github.com/joshua-jingu-lee/ante/pull/1695),
  [`b8ada77`](https://github.com/joshua-jingu-lee/ante/commit/b8ada777c76359c9fe98263358c51f4b252aa85c))

- #1699 account-id-contract historical narrative에서 broker health/price `ante` prefix 제거
  ([#1707](https://github.com/joshua-jingu-lee/ante/pull/1707),
  [`9a05315`](https://github.com/joshua-jingu-lee/ante/commit/9a05315b5d43f48055b54c5e3dd97d0eaca25e48))

- #1700 dashboard mockup/React/guide의 ante data show/collect fake CLI 정리
  ([#1708](https://github.com/joshua-jingu-lee/ante/pull/1708),
  [`70f2fd6`](https://github.com/joshua-jingu-lee/ante/commit/70f2fd62a075fd4a6256a497e2665c8c537f6512))

- #1702 project-structure CLI inventory 8 항목 현행화 (DEFAULT_DESCRIPTIONS + md 재생성)
  ([#1714](https://github.com/joshua-jingu-lee/ante/pull/1714),
  [`8479e53`](https://github.com/joshua-jingu-lee/ante/commit/8479e53878b650f097ce2ef0a58b34bfb93abe40))

- #1711 bot start/stop/status CLI·IPC 계약 스펙 확정 (Web API 라우트 정렬)
  ([#1715](https://github.com/joshua-jingu-lee/ante/pull/1715),
  [`cf1e32b`](https://github.com/joshua-jingu-lee/ante/commit/cf1e32b69bc1c18d588ddda052bd41ef4a2e45b5))

- #1728 #1698 epic 완료 후 stale 진행 문구 제거 (bot CLI usage + cli commands)
  ([#1738](https://github.com/joshua-jingu-lee/ante/pull/1738),
  [`f835f90`](https://github.com/joshua-jingu-lee/ante/commit/f835f9043970e879ab3dde9bc2c390cb6fea4d78))

- #1729 #1404 close 후 CLI 인증 설계 stale 진행 문구 정리
  ([#1739](https://github.com/joshua-jingu-lee/ante/pull/1739),
  [`84278a7`](https://github.com/joshua-jingu-lee/ante/commit/84278a7bf3ee4f5d7349119118937d7540b7f1a4))

- #1746 EventBus 스펙 D-018 정합 publisher 정정
  ([#1749](https://github.com/joshua-jingu-lee/ante/pull/1749),
  [`49a7bf6`](https://github.com/joshua-jingu-lee/ante/commit/49a7bf666572a682f9b0145ecd733cbcb933c95f))

- #1747 invalid-role runbook의 stale CLI path 정정
  ([#1750](https://github.com/joshua-jingu-lee/ante/pull/1750),
  [`371a168`](https://github.com/joshua-jingu-lee/ante/commit/371a168e35fd26b08c9f5631fe11be6fbb55a048))

- #1748 rule-engine 인덱스의 stale 11-rest-api.md 링크 제거
  ([#1751](https://github.com/joshua-jingu-lee/ante/pull/1751),
  [`ae19043`](https://github.com/joshua-jingu-lee/ante/commit/ae190439537e5e6bc649329cbfb83c847e1d3440))

- #1821 CLI/IPC envelope shape SSOT (4 normative forms)
  ([#1838](https://github.com/joshua-jingu-lee/ante/pull/1838),
  [`c3f08ff`](https://github.com/joshua-jingu-lee/ante/commit/c3f08ff787c98e370d19cc6ff1359120ef866b3e))

- #1824 contract SSOT index + 4-epic cross-check (meta-epic #1820 close)
  ([#1838](https://github.com/joshua-jingu-lee/ante/pull/1838),
  [`c3f08ff`](https://github.com/joshua-jingu-lee/ante/commit/c3f08ff787c98e370d19cc6ff1359120ef866b3e))

- #1839 stable error taxonomy spec + auth middleware code policy
  ([#1860](https://github.com/joshua-jingu-lee/ante/pull/1860),
  [`34ad127`](https://github.com/joshua-jingu-lee/ante/commit/34ad127b69a75cdfe1019bb15edfaaed9082deb1))

- #1841 regen project-structure.md (+drift allowlist + 2 test files)
  ([#1862](https://github.com/joshua-jingu-lee/ante/pull/1862),
  [`862e37c`](https://github.com/joshua-jingu-lee/ante/commit/862e37cf63e62077fb42a8c2e44550eee7ff87a8))

- #1842 regen project-structure (account CLI/IPC equivalence test 반영)
  ([#1863](https://github.com/joshua-jingu-lee/ante/pull/1863),
  [`31a1413`](https://github.com/joshua-jingu-lee/ante/commit/31a14137062f8bc578ae21a4c8bd1698bdd36371))

- #1843 sub-PR 1 regen project-structure (member CLI/IPC equivalence test 반영)
  ([#1865](https://github.com/joshua-jingu-lee/ante/pull/1865),
  [`419ddf5`](https://github.com/joshua-jingu-lee/ante/commit/419ddf5a922518263287a74cb936eab5705b5f3f))

- #1843-5 project-structure regen for new broker tests
  ([#1869](https://github.com/joshua-jingu-lee/ante/pull/1869),
  [`18b1e94`](https://github.com/joshua-jingu-lee/ante/commit/18b1e9430a7c7c4dd8569512caad51e59a0c6ac1))

- #1843-6 project-structure.md regen — 3 equivalence test 추가 반영
  ([#1871](https://github.com/joshua-jingu-lee/ante/pull/1871),
  [`4a194a3`](https://github.com/joshua-jingu-lee/ante/commit/4a194a33e9038b106be544fc6d5f47df7ef601ea))

- #1846 regenerate project-structure (account drift test)
  ([#1874](https://github.com/joshua-jingu-lee/ante/pull/1874),
  [`e334589`](https://github.com/joshua-jingu-lee/ante/commit/e334589c466126acec77b8180f43e6a03ad12136))

- #1847 sub-PR 4 regenerate project-structure.md
  ([#1878](https://github.com/joshua-jingu-lee/ante/pull/1878),
  [`eaa340f`](https://github.com/joshua-jingu-lee/ante/commit/eaa340f3a7f314799efdc119ce7ea19b04285820))

- #1847 sub-PR 5 regenerate project-structure.md (strategy drift test added)
  ([#1879](https://github.com/joshua-jingu-lee/ante/pull/1879),
  [`fa9ccbb`](https://github.com/joshua-jingu-lee/ante/commit/fa9ccbb0b718da19984555b102e0362b595de9f3))

- #1847 sub-PR 6 regenerate project-structure after adding data + report drift tests
  ([#1880](https://github.com/joshua-jingu-lee/ante/pull/1880),
  [`0172374`](https://github.com/joshua-jingu-lee/ante/commit/017237446ffdb546bba8725481d06f0a5052c244))

- #1847-2 regenerate project structure (bot drift test added)
  ([#1876](https://github.com/joshua-jingu-lee/ante/pull/1876),
  [`3debab9`](https://github.com/joshua-jingu-lee/ante/commit/3debab9189278d47f3db86022f94381a5922af0a))

- #1848 regenerate project-structure.md for new contracts test files
  ([#1894](https://github.com/joshua-jingu-lee/ante/pull/1894),
  [`a8bb234`](https://github.com/joshua-jingu-lee/ante/commit/a8bb23457663e9a75ded0ffce05baa95c0987689))

- #1854 CLI offline service factory contract + read_only policy + ctx-based path resolution
  ([#1887](https://github.com/joshua-jingu-lee/ante/pull/1887),
  [`a54c397`](https://github.com/joshua-jingu-lee/ante/commit/a54c3972a43ce2f48be982fa7ff509abf6549283))

- Align paper terminology cleanup ([#1288](https://github.com/joshua-jingu-lee/ante/pull/1288),
  [`173aba3`](https://github.com/joshua-jingu-lee/ante/commit/173aba33d55b0038b4c3f5546fb8722a6142277a))

- Raise autopilot issue limit to 25 ([#1859](https://github.com/joshua-jingu-lee/ante/pull/1859),
  [`9a2d5a9`](https://github.com/joshua-jingu-lee/ante/commit/9a2d5a93e50063bfeb4c4136a15a98ddfac6bb50))

- **#1847-1**: Regen project-structure with member drift test
  ([#1875](https://github.com/joshua-jingu-lee/ante/pull/1875),
  [`d728fc1`](https://github.com/joshua-jingu-lee/ante/commit/d728fc1d0f25c55a33f7e92b887433be1940108e))

- **account**: #1218 Edge resolver SPLIT 적용 위치 추가
  ([#1249](https://github.com/joshua-jingu-lee/ante/pull/1249),
  [`c7b6719`](https://github.com/joshua-jingu-lee/ante/commit/c7b67190ba0e4b09d8dd2ccc595bb5888e33cdab))

- **account**: Account create→D follow-up 재분류 + current 런타임 상태 단정 전면 제거 (#1633 attempt 3 blocking
  2건) ([#1646](https://github.com/joshua-jingu-lee/ante/pull/1646),
  [`d5c6e0d`](https://github.com/joshua-jingu-lee/ante/commit/d5c6e0d521b3be1b3bbadf04779e1e7338b0eab7))

- **account**: Account_id CLI 에러코드 SSOT + inventory 결정표 확정
  ([#1646](https://github.com/joshua-jingu-lee/ante/pull/1646),
  [`d5c6e0d`](https://github.com/joshua-jingu-lee/ante/commit/d5c6e0d521b3be1b3bbadf04779e1e7338b0eab7))

- **account**: Account_id CLI 에러코드 SSOT + inventory 결정표 확정 (#1633)
  ([#1646](https://github.com/joshua-jingu-lee/ante/pull/1646),
  [`d5c6e0d`](https://github.com/joshua-jingu-lee/ante/commit/d5c6e0d521b3be1b3bbadf04779e1e7338b0eab7))

- **account**: Align KIS credential key examples with BrokerPreset SSOT
  ([#1203](https://github.com/joshua-jingu-lee/ante/pull/1203),
  [`72e2620`](https://github.com/joshua-jingu-lee/ante/commit/72e26204d0d61bfcd3992c4e2ddf541957ec8048))

- **account**: Clarify require_account_id error to exclude 'test' from fallback list
  ([#1239](https://github.com/joshua-jingu-lee/ante/pull/1239),
  [`270a17a`](https://github.com/joshua-jingu-lee/ante/commit/270a17a192886233658cf2229d136fc4511c642f))

- **account**: Document service-layer runtime guard invariants S1-S5
  ([#1169](https://github.com/joshua-jingu-lee/ante/pull/1169),
  [`90dc2b8`](https://github.com/joshua-jingu-lee/ante/commit/90dc2b8fdb4fd5888ee760e0e0bc305ee8e44a4b))

- **account**: Document trading_hours strict HH:MM invariant
  ([#1344](https://github.com/joshua-jingu-lee/ante/pull/1344),
  [`1dd1cda`](https://github.com/joshua-jingu-lee/ante/commit/1dd1cdacf78e408fff06431a6418e157db1a9064))

- **account**: Inventory 결정표를 normative target으로 재프레임 — current 런타임 산출 단정 전면 제거 (#1633 attempt 3)
  ([#1646](https://github.com/joshua-jingu-lee/ante/pull/1646),
  [`d5c6e0d`](https://github.com/joshua-jingu-lee/ante/commit/d5c6e0d521b3be1b3bbadf04779e1e7338b0eab7))

- **account**: Make AMEX drift explicit in exchange SSOT pointer
  ([#1580](https://github.com/joshua-jingu-lee/ante/pull/1580),
  [`2562168`](https://github.com/joshua-jingu-lee/ante/commit/25621685a511a5aa8f843efa7d7b5e922665e324))

- **account**: Rule account_id 표면 정합 + error-code SSOT require_account_id 한정 (#1633 attempt 2)
  ([#1646](https://github.com/joshua-jingu-lee/ante/pull/1646),
  [`d5c6e0d`](https://github.com/joshua-jingu-lee/ante/commit/d5c6e0d521b3be1b3bbadf04779e1e7338b0eab7))

- **account**: Split read surfaces from bucket E — snapshot=B(#1635), strategy-perf=read-family
  follow-up (#1633 attempt5) ([#1646](https://github.com/joshua-jingu-lee/ante/pull/1646),
  [`d5c6e0d`](https://github.com/joshua-jingu-lee/ante/commit/d5c6e0d521b3be1b3bbadf04779e1e7338b0eab7))

- **agent**: Align generated artifact checklist (#1268)
  ([#1281](https://github.com/joshua-jingu-lee/ante/pull/1281),
  [`377ba52`](https://github.com/joshua-jingu-lee/ante/commit/377ba523c8e0a9743f92d9dd217898f512732cd6))

- **agent**: Align implement-issue stage table and exit criteria with new merge-gate policy
  ([#1178](https://github.com/joshua-jingu-lee/ante/pull/1178),
  [`729950e`](https://github.com/joshua-jingu-lee/ante/commit/729950ecdb0fb267e30b44c0fb277b29346606dc))

- **agent**: Drop PR approval references from autopilot/implement-issue/release commands
  ([#1178](https://github.com/joshua-jingu-lee/ante/pull/1178),
  [`729950e`](https://github.com/joshua-jingu-lee/ante/commit/729950ecdb0fb267e30b44c0fb277b29346606dc))

- **agent**: Rewrite review-pr/receive-review/code-reviewer to focus on Codex + manual paths
  ([#1178](https://github.com/joshua-jingu-lee/ante/pull/1178),
  [`729950e`](https://github.com/joshua-jingu-lee/ante/commit/729950ecdb0fb267e30b44c0fb277b29346606dc))

- **architecture**: Add db schema check mode (#1267)
  ([#1280](https://github.com/joshua-jingu-lee/ante/pull/1280),
  [`9846dd8`](https://github.com/joshua-jingu-lee/ante/commit/9846dd845e3daea1821bbff1d8f4ed436370eebd))

- **architecture**: Add project structure generator (#1266)
  ([#1279](https://github.com/joshua-jingu-lee/ante/pull/1279),
  [`a2325ce`](https://github.com/joshua-jingu-lee/ante/commit/a2325ceb8187edee986714a1fdb460d6db850c98))

- **auth**: Add D-015 default-deny auth gate ADR + Web/CLI spec updates (#1402)
  ([#1420](https://github.com/joshua-jingu-lee/ante/pull/1420),
  [`a125c11`](https://github.com/joshua-jingu-lee/ante/commit/a125c11a8c9c5dd70daa825568c4b7a6625c2231))

- **cli**: #1912 03-commands.md detail block에 누락된 leaf command 13건 추가
  ([#1925](https://github.com/joshua-jingu-lee/ante/pull/1925),
  [`df81e28`](https://github.com/joshua-jingu-lee/ante/commit/df81e287fdff69135e26d0f8995439dfd25da28c))

- **cli**: #1916 strategy performance --account-id semantic-required 표기 정합
  ([#1927](https://github.com/joshua-jingu-lee/ante/pull/1927),
  [`a1fd48c`](https://github.com/joshua-jingu-lee/ante/commit/a1fd48c39bdf3129be12707b6629fddff8224523))

- **cli**: Adopt non-interactive input contract as CLI SSOT
  ([#1203](https://github.com/joshua-jingu-lee/ante/pull/1203),
  [`72e2620`](https://github.com/joshua-jingu-lee/ante/commit/72e26204d0d61bfcd3992c4e2ddf541957ec8048))

- **commands**: Add plan preflight command
  ([`88d96d7`](https://github.com/joshua-jingu-lee/ante/commit/88d96d7aca14e844bf358b0335efc929df0b39ad))

- **commands**: Remove arch review command
  ([`92d6b79`](https://github.com/joshua-jingu-lee/ante/commit/92d6b7913c83144c945faffcdcd821d80c2bb225))

- **core**: Align Data API symbol owner + close strategy timeframe enum (#1612 review)
  ([#1615](https://github.com/joshua-jingu-lee/ante/pull/1615),
  [`0295cdb`](https://github.com/joshua-jingu-lee/ante/commit/0295cdbfe5f3a5695c7a1ec858bf5dcbb192a3fd))

- **core**: Make DataStore read consistent with legacy policy + section-wide consistency pass
  ([#1580](https://github.com/joshua-jingu-lee/ante/pull/1580),
  [`2562168`](https://github.com/joshua-jingu-lee/ante/commit/25621685a511a5aa8f843efa7d7b5e922665e324))

- **core**: Scope Account Web 409 to POST + PUT-structural, allow PUT mutable
  ([#1580](https://github.com/joshua-jingu-lee/ante/pull/1580),
  [`2562168`](https://github.com/joshua-jingu-lee/ante/commit/25621685a511a5aa8f843efa7d7b5e922665e324))

- **core**: Scope KRX symbol shape to KRX surface + fix #1611 import consumer (#1612 review2)
  ([#1615](https://github.com/joshua-jingu-lee/ante/pull/1615),
  [`0295cdb`](https://github.com/joshua-jingu-lee/ante/commit/0295cdbfe5f3a5695c7a1ec858bf5dcbb192a3fd))

- **core**: Scope matrix to vocabulary contract, defer surface specifics to #1577/#1578
  ([#1580](https://github.com/joshua-jingu-lee/ante/pull/1580),
  [`2562168`](https://github.com/joshua-jingu-lee/ante/commit/25621685a511a5aa8f843efa7d7b5e922665e324))

- **core**: Separate exchange-validity vs 1.0 preset-availability axes
  ([#1580](https://github.com/joshua-jingu-lee/ante/pull/1580),
  [`2562168`](https://github.com/joshua-jingu-lee/ante/commit/25621685a511a5aa8f843efa7d7b5e922665e324))

- **core**: Symbol-axis cross-spec reconciliation — schema/datasets symbol semantics (#1612 review3
  meta) ([#1615](https://github.com/joshua-jingu-lee/ante/pull/1615),
  [`0295cdb`](https://github.com/joshua-jingu-lee/ante/commit/0295cdbfe5f3a5695c7a1ec858bf5dcbb192a3fd))

- **core**: Symbol/timeframe canonical vocabulary 계약 SSOT 신설
  ([#1615](https://github.com/joshua-jingu-lee/ante/pull/1615),
  [`0295cdb`](https://github.com/joshua-jingu-lee/ante/commit/0295cdbfe5f3a5695c7a1ec858bf5dcbb192a3fd))

- **core**: Symbol/timeframe canonical vocabulary 계약 SSOT 신설 (#1612)
  ([#1615](https://github.com/joshua-jingu-lee/ante/pull/1615),
  [`0295cdb`](https://github.com/joshua-jingu-lee/ante/commit/0295cdbfe5f3a5695c7a1ec858bf5dcbb192a3fd))

- **core**: Use real CLI command name account create
  ([#1580](https://github.com/joshua-jingu-lee/ante/pull/1580),
  [`2562168`](https://github.com/joshua-jingu-lee/ante/commit/25621685a511a5aa8f843efa7d7b5e922665e324))

- **core,account**: Use exact MUTABLE_FIELDS names trading_hours_start/end
  ([#1580](https://github.com/joshua-jingu-lee/ante/pull/1580),
  [`2562168`](https://github.com/joshua-jingu-lee/ante/commit/25621685a511a5aa8f843efa7d7b5e922665e324))

- **core,decisions**: Define canonical exchange vocabulary SSOT
  ([#1580](https://github.com/joshua-jingu-lee/ante/pull/1580),
  [`2562168`](https://github.com/joshua-jingu-lee/ante/commit/25621685a511a5aa8f843efa7d7b5e922665e324))

- **core,decisions**: Define canonical exchange vocabulary SSOT (#1575)
  ([#1580](https://github.com/joshua-jingu-lee/ante/pull/1580),
  [`2562168`](https://github.com/joshua-jingu-lee/ante/commit/25621685a511a5aa8f843efa7d7b5e922665e324))

- **db**: Align schema constant convention (#1229)
  ([#1254](https://github.com/joshua-jingu-lee/ante/pull/1254),
  [`8f04aff`](https://github.com/joshua-jingu-lee/ante/commit/8f04aff250e76e61e77d0ced10366cf15cbf5731))

- **db**: Regenerate account-aware schema reference (#1260)
  ([#1273](https://github.com/joshua-jingu-lee/ante/pull/1273),
  [`92dc769`](https://github.com/joshua-jingu-lee/ante/commit/92dc769f53314e76e66684c91e6e07e92f1e7acc))

- **decisions**: Recover D-016 contract paraphrase to core.md SSOT link
  ([#1580](https://github.com/joshua-jingu-lee/ante/pull/1580),
  [`2562168`](https://github.com/joshua-jingu-lee/ante/commit/25621685a511a5aa8f843efa7d7b5e922665e324))

- **eventbus**: Document `_consumed` transient marker convention
  ([#1341](https://github.com/joshua-jingu-lee/ante/pull/1341),
  [`fde7c2e`](https://github.com/joshua-jingu-lee/ante/commit/fde7c2ed4b6b8c91495dc6992dc9bdcdc29bf4b2))

- **frontend**: Align API type SSOT rules (#1221)
  ([#1250](https://github.com/joshua-jingu-lee/ante/pull/1250),
  [`0ef6963`](https://github.com/joshua-jingu-lee/ante/commit/0ef6963f48ad43f78ce9dfc97c678d2de6f8a4b7))

- **guide**: Align guide with non-interactive CLI contract
  ([#1210](https://github.com/joshua-jingu-lee/ante/pull/1210),
  [`40dec44`](https://github.com/joshua-jingu-lee/ante/commit/40dec44a75f34f197be3f0135e77307a7d9be1f1))

- **guide**: Fix KIS credential example missing account_no and reset-password positional arg
  ([#1210](https://github.com/joshua-jingu-lee/ante/pull/1210),
  [`40dec44`](https://github.com/joshua-jingu-lee/ante/commit/40dec44a75f34f197be3f0135e77307a7d9be1f1))

- **member**: Clarify member admin mutation is master-only (#1542)
  ([#1554](https://github.com/joshua-jingu-lee/ante/pull/1554),
  [`93975fe`](https://github.com/joshua-jingu-lee/ante/commit/93975fe2a6e4165697b20268113b0ff3e4c69894))

- **plan**: Note writing plans superpower
  ([`21cc97e`](https://github.com/joshua-jingu-lee/ante/commit/21cc97e00bd27d08ee80d44720f58bcd658139ff))

- **plan-preflight**: Narrow split handling to planning
  ([#1245](https://github.com/joshua-jingu-lee/ante/pull/1245),
  [`c29ce8d`](https://github.com/joshua-jingu-lee/ante/commit/c29ce8d229f040e6c09650607217ca2930a2f23d))

- **release**: Split prepare and publish flow
  ([`4269ec6`](https://github.com/joshua-jingu-lee/ante/commit/4269ec620428c42e425f3d908048c01ee31f0d02))

- **runbook**: #1924 코드 주석 정합 원칙을 development-process §10에 추가
  ([#1938](https://github.com/joshua-jingu-lee/ante/pull/1938),
  [`f6642fc`](https://github.com/joshua-jingu-lee/ante/commit/f6642fc08d76359639c3e8382b526e81e0b504c2))

- **runbook**: Add plan preflight lane
  ([`2ec1259`](https://github.com/joshua-jingu-lee/ante/commit/2ec12594dd84f48896acb31697306df1bfddd90d))

- **runbook**: Add release command flow
  ([`3453f8c`](https://github.com/joshua-jingu-lee/ante/commit/3453f8cea65ab37273375615fb96de4f6940934d))

- **runbook**: Align development/git/agent-structure runbooks with new gate model
  ([#1178](https://github.com/joshua-jingu-lee/ante/pull/1178),
  [`729950e`](https://github.com/joshua-jingu-lee/ante/commit/729950ecdb0fb267e30b44c0fb277b29346606dc))

- **runbook**: Align interaction flow with preflight
  ([`ce46bd1`](https://github.com/joshua-jingu-lee/ante/commit/ce46bd161b061c2ef4239d1d397c6001da98212d))

- **runbook**: Align release pr references
  ([`f2dc7e5`](https://github.com/joshua-jingu-lee/ante/commit/f2dc7e567a6bdfc7279f350e3882ab7d5d78a924))

- **runbook**: Assign start note to dev agent
  ([`914d350`](https://github.com/joshua-jingu-lee/ante/commit/914d350d8dcb1a5ffd2833174e3509639441faed))

- **runbook**: Clarify implement issue lane
  ([`696a8a4`](https://github.com/joshua-jingu-lee/ante/commit/696a8a42acba569d846ca7f00c430f645de356c7))

- **runbook**: Clarify recovery ssot
  ([`b1afb7e`](https://github.com/joshua-jingu-lee/ante/commit/b1afb7ecbe17c759b46b9bb9d020543e272173c5))

- **runbook**: Delegate plan review to codex
  ([`80d4419`](https://github.com/joshua-jingu-lee/ante/commit/80d44192517215799c1155d4cbe2abfe9b7f1919))

- **runbook**: Detail issue spec paths
  ([`555a553`](https://github.com/joshua-jingu-lee/ante/commit/555a5531a9e94dc5c35803d740fed3ecfbef4ef9))

- **runbook**: Fold plan finalization into preflight
  ([`f10e063`](https://github.com/joshua-jingu-lee/ante/commit/f10e0635ddb75cdc3867187b2f747eb713c29b4d))

- **runbook**: Fold review gate into ci cd
  ([`1a746ef`](https://github.com/joshua-jingu-lee/ante/commit/1a746ef0899e1ed95572aa49a22804ed5f5459a2))

- **runbook**: Make autopilot command ssot
  ([`f75bce8`](https://github.com/joshua-jingu-lee/ante/commit/f75bce8b2dbe445dbfbf0850a3cee5089f0cb0e2))

- **runbook**: Map issue processing flow
  ([`98eac18`](https://github.com/joshua-jingu-lee/ante/commit/98eac1871eb57b79491f100f6b49572413e82bbb))

- **runbook**: Merge plan review flow
  ([`08e5518`](https://github.com/joshua-jingu-lee/ante/commit/08e55185e87e076b98b79302cacb8384b39846ab))

- **runbook**: Move branch review in process
  ([`c5158ee`](https://github.com/joshua-jingu-lee/ante/commit/c5158eeba00d53b49a07c7c64c02ee3bfb30611b))

- **runbook**: Realign interaction flow tree
  ([`9db3392`](https://github.com/joshua-jingu-lee/ante/commit/9db3392522859e56660adc5aa4ef66a494319011))

- **runbook**: Require issue comment checkpoints
  ([`e5d1c4a`](https://github.com/joshua-jingu-lee/ante/commit/e5d1c4a9d9cc0510e0443f3c0093495b937ebd16))

- **runbook**: Retire PR approval/auto-fix gates from CI/CD spec
  ([#1178](https://github.com/joshua-jingu-lee/ante/pull/1178),
  [`729950e`](https://github.com/joshua-jingu-lee/ante/commit/729950ecdb0fb267e30b44c0fb277b29346606dc))

- **runbook**: Route preflight through plan review
  ([`7a228e8`](https://github.com/joshua-jingu-lee/ante/commit/7a228e81cd57eb9b926253824e3a6d0a39ea6094))

- **runbook**: Split plan preflight labels
  ([`bebad44`](https://github.com/joshua-jingu-lee/ante/commit/bebad4461c99dc23be9bc4b981df4fa5fdc5fe88))

- **runbook**: Tag preflight-ready issues
  ([`79dc70f`](https://github.com/joshua-jingu-lee/ante/commit/79dc70f0a75a3ced0df4093a54c9136e6dc8967a))

- **runbook**: Trim delegated process details
  ([`b153b84`](https://github.com/joshua-jingu-lee/ante/commit/b153b84aa87a2a4657f6dba994f1cca1ee44d5fc))

- **runbook**: Trim issue management process details
  ([`ef6522b`](https://github.com/joshua-jingu-lee/ante/commit/ef6522b897ed9898382a6fb8f0aa4fcce2bd4a44))

- **runtime**: Align user-facing docs to Python 3.13 single runtime contract (#1186)
  ([#1197](https://github.com/joshua-jingu-lee/ante/pull/1197),
  [`7e0c8aa`](https://github.com/joshua-jingu-lee/ante/commit/7e0c8aa103fa4ebcb26dff8bfafc8bf3facd4f2f))

- **spec**: #1917 instrument invalid exchange enforcement #1577 완료 시제 정합
  ([#1928](https://github.com/joshua-jingu-lee/ante/pull/1928),
  [`f1d20c5`](https://github.com/joshua-jingu-lee/ante/commit/f1d20c5335882c74b9af054b0cd4fb33eea128be))

- **spec**: #1918 master-only CLI guard #1543 완료 시제 정합
  ([#1929](https://github.com/joshua-jingu-lee/ante/pull/1929),
  [`d29b0e2`](https://github.com/joshua-jingu-lee/ante/commit/d29b0e29785072c03fe01c79b06e74465e393b63))

- **spec**: #1919 offline-factory contract #1855/#1856/#1857 완료 시제 정합
  ([#1931](https://github.com/joshua-jingu-lee/ante/pull/1931),
  [`1c9ebdb`](https://github.com/joshua-jingu-lee/ante/commit/1c9ebdb9058aed1031e8f445f5631505087f6a29))

- **spec**: #1920 DataCollector ingress enforcement #1614 완료 시제 정합
  ([#1930](https://github.com/joshua-jingu-lee/ante/pull/1930),
  [`779c4da`](https://github.com/joshua-jingu-lee/ante/commit/779c4da04621ea1167f8ddbe2d7cc46a82b5cbd1))

- **spec**: #1926 core.md #1577 narrative/sub-axis 시제 정합
  ([#1936](https://github.com/joshua-jingu-lee/ante/pull/1936),
  [`1208fb2`](https://github.com/joshua-jingu-lee/ante/commit/1208fb2399846207cb12c90a8762641e31143e72))

- **spec**: #1946 fill-recovery 스펙 선반영 (18-fill-recovery + 11/19 정합 + trade)
  ([#1953](https://github.com/joshua-jingu-lee/ante/pull/1953),
  [`9f548b4`](https://github.com/joshua-jingu-lee/ante/commit/9f548b463cf4f6794fc788270a58cfa084471eb4))

- **spec**: Add #1213 implementation status banner to halt/clear-halt SSOT
  ([#1230](https://github.com/joshua-jingu-lee/ante/pull/1230),
  [`cc20511`](https://github.com/joshua-jingu-lee/ante/commit/cc205112c61b419b6b9b2d9e64099a4c97d3f3a5))

- **spec**: Align account api field names
  ([`d638f3e`](https://github.com/joshua-jingu-lee/ante/commit/d638f3eb019b1ead783c6e52d5bdb35c5132ebd4))

- **spec**: Align core/core.md telegram contract and clarify DELETED exclusion
  ([#1230](https://github.com/joshua-jingu-lee/ante/pull/1230),
  [`cc20511`](https://github.com/joshua-jingu-lee/ante/commit/cc205112c61b419b6b9b2d9e64099a4c97d3f3a5))

- **spec**: Align System Kill Switch contract to halt/clear-halt
  ([#1230](https://github.com/joshua-jingu-lee/ante/pull/1230),
  [`cc20511`](https://github.com/joshua-jingu-lee/ante/commit/cc205112c61b419b6b9b2d9e64099a4c97d3f3a5))

- **spec**: Align treasury virtual sync interface
  ([`8b567c2`](https://github.com/joshua-jingu-lee/ante/commit/8b567c2f3f9d3a8f598d225b5f571b85bba8a138))

- **spec**: Clarify compatibility document role
  ([`3793123`](https://github.com/joshua-jingu-lee/ante/commit/3793123133163983a2d89c4ad182652d2c9323b6))

- **spec**: Classify runtime command boundaries
  ([`0b38ae9`](https://github.com/joshua-jingu-lee/ante/commit/0b38ae9278d5331106fa6c24d07fc27c0a9e54c2))

- **spec**: Clean up legacy contract remnants
  ([`58552e5`](https://github.com/joshua-jingu-lee/ante/commit/58552e57904e7b338e589c1b9a06839defea7ad7))

- **spec**: Define account lifecycle cold path
  ([`bf448ce`](https://github.com/joshua-jingu-lee/ante/commit/bf448ceb236fee2539d31efbcfea664a737e7d4d))

- **spec**: Define auth scope ssot
  ([`928efb7`](https://github.com/joshua-jingu-lee/ante/commit/928efb72c3b75b20d22440d4361e126a96a86af2))

- **spec**: Define cli command inventory ssot
  ([`ff6fb86`](https://github.com/joshua-jingu-lee/ante/commit/ff6fb8600b555d0fe988582fb4afc27cf15665bc))

- **spec**: Define datastore merge writes
  ([`19cc3fd`](https://github.com/joshua-jingu-lee/ante/commit/19cc3fd0d32a31db4a97d95f3b1ea72074df25f1))

- **spec**: Define instance path contract
  ([`63bbadb`](https://github.com/joshua-jingu-lee/ante/commit/63bbadb311e2bdfd85f3f286c92165dd122460bd))

- **spec**: Define rule config storage contract
  ([`72f1224`](https://github.com/joshua-jingu-lee/ante/commit/72f1224a80e4d0f6269f579d2b460571388035cd))

- **spec**: Document application/problem+json content-type alignment for 4xx/5xx
  ([#1180](https://github.com/joshua-jingu-lee/ante/pull/1180),
  [`19002a9`](https://github.com/joshua-jingu-lee/ante/commit/19002a996b8757b8fdba9e4e1b524e0ff017c982))

- **spec**: Mark pykrx flow as phase 2
  ([`bc531f6`](https://github.com/joshua-jingu-lee/ante/commit/bc531f6799b0f79848a1492f68f52159f00765a3))

- **spec**: Reconcile notification quiet hours status
  ([`e66105b`](https://github.com/joshua-jingu-lee/ante/commit/e66105b967b48adc6827d8a1c20c1c260067ccf4))

- **spec**: Refine #1213 pending banner — only clear-halt is new
  ([#1230](https://github.com/joshua-jingu-lee/ante/pull/1230),
  [`cc20511`](https://github.com/joshua-jingu-lee/ante/commit/cc205112c61b419b6b9b2d9e64099a4c97d3f3a5))

- **spec**: Remove stale open issue docs
  ([`9eface5`](https://github.com/joshua-jingu-lee/ante/commit/9eface5fe6e4f31132d45e0a0be43f1990742851))

- **spec**: Simplify notification settings contract
  ([`6be165e`](https://github.com/joshua-jingu-lee/ante/commit/6be165efe6c4d8ecb4bdeb210e0fe98ad361977d))

- **spec**: Split-3 close + stream events marker policy
  ([#1247](https://github.com/joshua-jingu-lee/ante/pull/1247),
  [`91b2afb`](https://github.com/joshua-jingu-lee/ante/commit/91b2afb3bd264ec5ef212bde1df29c0e0205a180))

- **spec**: Use /clear_halt for telegram slash command (no hyphen allowed)
  ([#1230](https://github.com/joshua-jingu-lee/ante/pull/1230),
  [`cc20511`](https://github.com/joshua-jingu-lee/ante/commit/cc205112c61b419b6b9b2d9e64099a4c97d3f3a5))

- **spec**: Use lowercase wire value for kill switch status enum
  ([#1230](https://github.com/joshua-jingu-lee/ante/pull/1230),
  [`cc20511`](https://github.com/joshua-jingu-lee/ante/commit/cc205112c61b419b6b9b2d9e64099a4c97d3f3a5))

- **specs**: Document buy stop/stop_limit no-reserve policy
  ([#1348](https://github.com/joshua-jingu-lee/ante/pull/1348),
  [`ce0efab`](https://github.com/joshua-jingu-lee/ante/commit/ce0efab8cc58277b3323d1560ba8f8ef87ccd8ed))

- **specs**: Document market_order_reserve_buffer_rate and quote resolver
  ([#1350](https://github.com/joshua-jingu-lee/ante/pull/1350),
  [`563df47`](https://github.com/joshua-jingu-lee/ante/commit/563df4742324680ade2126daf6aa4c7b5bb466f5))

- **specs**: Document stop order on_order_update routing policy
  ([#1349](https://github.com/joshua-jingu-lee/ante/pull/1349),
  [`58af809`](https://github.com/joshua-jingu-lee/ante/commit/58af809433e1586374dabeaec795cefb2813dae6))

- **test**: Clear qa harness leftovers
  ([`c29bde8`](https://github.com/joshua-jingu-lee/ante/commit/c29bde8002085ebf6be21505036cd2d7dc2f5e24))

- **web**: Document datasets timeframe 400 contract in OpenAPI
  ([#1601](https://github.com/joshua-jingu-lee/ante/pull/1601),
  [`e5482b8`](https://github.com/joshua-jingu-lee/ante/commit/e5482b8f39a472113f08569ab03e5f573ef0adb6))

- **web-api**: #1651 discovery lock known-limitation + follow-up rule (user A decision)
  ([#1653](https://github.com/joshua-jingu-lee/ante/pull/1653),
  [`30b43a5`](https://github.com/joshua-jingu-lee/ante/commit/30b43a5cdba6e282e6fda6d839eeb8c1ae144b3a))

- **web-api**: Add 70-route scope decision SSOT (#1409)
  ([#1425](https://github.com/joshua-jingu-lee/ante/pull/1425),
  [`3bd69e6`](https://github.com/joshua-jingu-lee/ante/commit/3bd69e6369375b132273a59d89cd51f1a6ef30e7))

- **web-api**: Document POST /api/bots budget failure policy
  ([#1345](https://github.com/joshua-jingu-lee/ante/pull/1345),
  [`016a328`](https://github.com/joshua-jingu-lee/ante/commit/016a3285cb2900a83636eaf6397040b841f4bf6a))

### Features

- #1712 bot.start/stop/status IPC handler 등록 (Web API 정렬 + behavior-preserving helper)
  ([#1716](https://github.com/joshua-jingu-lee/ante/pull/1716),
  [`8605926`](https://github.com/joshua-jingu-lee/ante/commit/86059263c0dea25cfa32530a6529c3ab3bf20486))

- #1713 ante bot start/stop/status CLI leaf command 등록 (#1698 epic 완료)
  ([#1717](https://github.com/joshua-jingu-lee/ante/pull/1717),
  [`386462e`](https://github.com/joshua-jingu-lee/ante/commit/386462ed20f2f1e584251b575fbf879b3a045af5))

- #1820 meta-epic contract SSOT 공통 인프라 (closes #1820/#1821/#1822/#1823/#1824)
  ([#1838](https://github.com/joshua-jingu-lee/ante/pull/1838),
  [`c3f08ff`](https://github.com/joshua-jingu-lee/ante/commit/c3f08ff787c98e370d19cc6ff1359120ef866b3e))

- #1822 contract vocabulary SSOT module (ContractKind/EnvelopeForm/AuthMode)
  ([#1838](https://github.com/joshua-jingu-lee/ante/pull/1838),
  [`c3f08ff`](https://github.com/joshua-jingu-lee/ante/commit/c3f08ff787c98e370d19cc6ff1359120ef866b3e))

- 70개 Web 라우트 scope 결정 일관 부착 (#1407) ([#1428](https://github.com/joshua-jingu-lee/ante/pull/1428),
  [`c345244`](https://github.com/joshua-jingu-lee/ante/commit/c345244d32190e013f3024a7fc7a0562b6fecc73))

- **account**: Add account_id scoping helper with runtime/creation policy split
  ([#1239](https://github.com/joshua-jingu-lee/ante/pull/1239),
  [`270a17a`](https://github.com/joshua-jingu-lee/ante/commit/270a17a192886233658cf2229d136fc4511c642f))

- **account**: Add market_order_reserve_buffer_rate cold-path field
  ([#1350](https://github.com/joshua-jingu-lee/ante/pull/1350),
  [`563df47`](https://github.com/joshua-jingu-lee/ante/commit/563df4742324680ade2126daf6aa4c7b5bb466f5))

- **account**: Align edge account resolver fallback policy
  ([#1249](https://github.com/joshua-jingu-lee/ante/pull/1249),
  [`c7b6719`](https://github.com/joshua-jingu-lee/ante/commit/c7b67190ba0e4b09d8dd2ccc595bb5888e33cdab))

- **account**: Edge resolver align - cli/strategy account-required
  ([#1249](https://github.com/joshua-jingu-lee/ante/pull/1249),
  [`c7b6719`](https://github.com/joshua-jingu-lee/ante/commit/c7b67190ba0e4b09d8dd2ccc595bb5888e33cdab))

- **account**: Edge resolver align - report feedback BotNotFoundError
  ([#1249](https://github.com/joshua-jingu-lee/ante/pull/1249),
  [`c7b6719`](https://github.com/joshua-jingu-lee/ante/commit/c7b67190ba0e4b09d8dd2ccc595bb5888e33cdab))

- **account**: Edge resolver align - web/bots single-active resolver
  ([#1249](https://github.com/joshua-jingu-lee/ante/pull/1249),
  [`c7b6719`](https://github.com/joshua-jingu-lee/ante/commit/c7b67190ba0e4b09d8dd2ccc595bb5888e33cdab))

- **account**: Edge resolver align - web/strategies cumulative + performance
  ([#1249](https://github.com/joshua-jingu-lee/ante/pull/1249),
  [`c7b6719`](https://github.com/joshua-jingu-lee/ante/commit/c7b67190ba0e4b09d8dd2ccc595bb5888e33cdab))

- **account**: Restrict _bootstrap=True to BROKER_PRESETS seed accounts only
  ([#1239](https://github.com/joshua-jingu-lee/ante/pull/1239),
  [`270a17a`](https://github.com/joshua-jingu-lee/ante/commit/270a17a192886233658cf2229d136fc4511c642f))

- **account**: Split-1 runtime fallback marker for events/treasury/rule/trade/ipc/web
  ([#1243](https://github.com/joshua-jingu-lee/ante/pull/1243),
  [`83dcd3b`](https://github.com/joshua-jingu-lee/ante/commit/83dcd3b206acade00a7abfd8eb285f0036def1af))

- **account**: Split-1 runtime fallback marker for events/treasury/rule/trade/ipc/web (#1240)
  ([#1243](https://github.com/joshua-jingu-lee/ante/pull/1243),
  [`83dcd3b`](https://github.com/joshua-jingu-lee/ante/commit/83dcd3b206acade00a7abfd8eb285f0036def1af))

- **account**: Split-2 bot/approval account-scoped require_account_id
  ([#1246](https://github.com/joshua-jingu-lee/ante/pull/1246),
  [`45ae880`](https://github.com/joshua-jingu-lee/ante/commit/45ae880d92861fcc85c2801be4dcdec2387a7fa5))

- **account**: Split-2 require_account_id for bot/approval/main.py (#1241)
  ([#1246](https://github.com/joshua-jingu-lee/ante/pull/1246),
  [`45ae880`](https://github.com/joshua-jingu-lee/ante/commit/45ae880d92861fcc85c2801be4dcdec2387a7fa5))

- **account**: Split-3 APIGateway/Stream + multi-account lifecycle pool (#1242)
  ([#1247](https://github.com/joshua-jingu-lee/ante/pull/1247),
  [`91b2afb`](https://github.com/joshua-jingu-lee/ante/commit/91b2afb3bd264ec5ef212bde1df29c0e0205a180))

- **account**: Split-3 multi-account StreamIntegration pool
  ([#1247](https://github.com/joshua-jingu-lee/ante/pull/1247),
  [`91b2afb`](https://github.com/joshua-jingu-lee/ante/commit/91b2afb3bd264ec5ef212bde1df29c0e0205a180))

- **account**: Tighten _bootstrap=True to require (broker_type, default_account_id) pair
  ([#1239](https://github.com/joshua-jingu-lee/ante/pull/1239),
  [`270a17a`](https://github.com/joshua-jingu-lee/ante/commit/270a17a192886233658cf2229d136fc4511c642f))

- **account**: Tolerant load + repair-timezone for legacy invalid IANA timezone rows
  ([#1505](https://github.com/joshua-jingu-lee/ante/pull/1505),
  [`8092b19`](https://github.com/joshua-jingu-lee/ante/commit/8092b19149df01dae64428f22866be728ff3f07d))

- **account-api**: Expose market_order_reserve_buffer_rate via Web/CLI
  ([#1350](https://github.com/joshua-jingu-lee/ante/pull/1350),
  [`563df47`](https://github.com/joshua-jingu-lee/ante/commit/563df4742324680ade2126daf6aa4c7b5bb466f5))

- **approval,cli,ipc**: Audit-types + cancel-invalid for legacy invalid approval cleanup (#1472)
  ([#1520](https://github.com/joshua-jingu-lee/ante/pull/1520),
  [`acea2c2`](https://github.com/joshua-jingu-lee/ante/commit/acea2c2886585cff8acc6118e1cf11de6b45d5c0))

- **backtest**: Add --exchange override with canonical validation + full propagation (#1585)
  ([#1588](https://github.com/joshua-jingu-lee/ante/pull/1588),
  [`7dc6e9b`](https://github.com/joshua-jingu-lee/ante/commit/7dc6e9bce0c1a7fc10d580a86117f372b70e1fa4))

- **backtest**: Add --exchange override with canonical validation + plumbing
  ([#1588](https://github.com/joshua-jingu-lee/ante/pull/1588),
  [`7dc6e9b`](https://github.com/joshua-jingu-lee/ante/commit/7dc6e9bce0c1a7fc10d580a86117f372b70e1fa4))

- **backtest**: Plumb --exchange through executor to BacktestTrade labels
  ([#1588](https://github.com/joshua-jingu-lee/ante/pull/1588),
  [`7dc6e9b`](https://github.com/joshua-jingu-lee/ante/commit/7dc6e9bce0c1a7fc10d580a86117f372b70e1fa4))

- **backtest**: Serialize trade exchange in BacktestResult.to_dict
  ([#1588](https://github.com/joshua-jingu-lee/ante/pull/1588),
  [`7dc6e9b`](https://github.com/joshua-jingu-lee/ante/commit/7dc6e9bce0c1a7fc10d580a86117f372b70e1fa4))

- **bot**: Route StopOrder events through on_order_update
  ([#1349](https://github.com/joshua-jingu-lee/ante/pull/1349),
  [`58af809`](https://github.com/joshua-jingu-lee/ante/commit/58af809433e1586374dabeaec795cefb2813dae6))

- **bot,web-api**: Expose runtime controls via nested BotInfo.config
  ([#1501](https://github.com/joshua-jingu-lee/ante/pull/1501),
  [`64c7d45`](https://github.com/joshua-jingu-lee/ante/commit/64c7d451fe5bf399f961b739c6f5aff6092dc022))

- **broker**: Make order registry account-aware (#1256)
  ([#1269](https://github.com/joshua-jingu-lee/ante/pull/1269),
  [`a7a18ae`](https://github.com/joshua-jingu-lee/ante/commit/a7a18aed708d7fc21e76742a98ea5f37cab1459e))

- **broker**: Split-3 multi-broker ReconcileScheduler pool
  ([#1247](https://github.com/joshua-jingu-lee/ante/pull/1247),
  [`91b2afb`](https://github.com/joshua-jingu-lee/ante/commit/91b2afb3bd264ec5ef212bde1df29c0e0205a180))

- **cli**: Add enum preflight to account/approval/report list before DB
  ([#1503](https://github.com/joshua-jingu-lee/ante/pull/1503),
  [`9e8d68c`](https://github.com/joshua-jingu-lee/ante/commit/9e8d68cf174e52bff2706b9bfef75f784b8cc392))

- **cli**: Authenticated_group factory default-deny gate (#1404)
  ([#1422](https://github.com/joshua-jingu-lee/ante/pull/1422),
  [`c8f698b`](https://github.com/joshua-jingu-lee/ante/commit/c8f698b27deb8a2874050f466b951b26e7fba4a0))

- **cli/init**: Emit [runtime] section in system.toml template
  ([#1182](https://github.com/joshua-jingu-lee/ante/pull/1182),
  [`290bcff`](https://github.com/joshua-jingu-lee/ante/commit/290bcff5afbd8688b251a0cc3c1764cb2071fac8))

- **config**: Add Config.resolve_path for config_dir-relative path normalization
  ([#1181](https://github.com/joshua-jingu-lee/ante/pull/1181),
  [`b5e60d7`](https://github.com/joshua-jingu-lee/ante/commit/b5e60d71e2ae2ffb893d657d759d1af9d0fee536))

- **config**: Add runtime path resolver convenience methods
  ([#1182](https://github.com/joshua-jingu-lee/ante/pull/1182),
  [`290bcff`](https://github.com/joshua-jingu-lee/ante/commit/290bcff5afbd8688b251a0cc3c1764cb2071fac8))

- **dashboard**: Add 30s polling to kill switch status accounts query
  ([#1238](https://github.com/joshua-jingu-lee/ante/pull/1238),
  [`95a4928`](https://github.com/joshua-jingu-lee/ante/commit/95a492814aa77c217aa15cb21bdda4f25af58ec2))

- **dashboard**: Align kill switch frontend to halt/clear-halt SSOT
  ([#1238](https://github.com/joshua-jingu-lee/ante/pull/1238),
  [`95a4928`](https://github.com/joshua-jingu-lee/ante/commit/95a492814aa77c217aa15cb21bdda4f25af58ec2))

- **dashboard**: Align system kill switch frontend to halt/clear-halt SSOT
  ([#1238](https://github.com/joshua-jingu-lee/ante/pull/1238),
  [`95a4928`](https://github.com/joshua-jingu-lee/ante/commit/95a492814aa77c217aa15cb21bdda4f25af58ec2))

- **db**: Migrate legacy percent win_rate values to ratio (v005)
  ([#1363](https://github.com/joshua-jingu-lee/ante/pull/1363),
  [`0dcb64a`](https://github.com/joshua-jingu-lee/ante/commit/0dcb64a386730d74acc1f34bf346ae7416db3c93))

- **eventbus**: Add account_id to StopOrder events
  ([#1349](https://github.com/joshua-jingu-lee/ante/pull/1349),
  [`58af809`](https://github.com/joshua-jingu-lee/ante/commit/58af809433e1586374dabeaec795cefb2813dae6))

- **eventbus**: Split-3 account_id strict marker on stream events
  ([#1247](https://github.com/joshua-jingu-lee/ante/pull/1247),
  [`91b2afb`](https://github.com/joshua-jingu-lee/ante/commit/91b2afb3bd264ec5ef212bde1df29c0e0205a180))

- **frontend**: Adapt approval generated types
  ([#1276](https://github.com/joshua-jingu-lee/ante/pull/1276),
  [`ba3e993`](https://github.com/joshua-jingu-lee/ante/commit/ba3e9933965709e3b6a0db94256ee4f9ef9fbda8))

- **frontend**: Adapt auth member generated types
  ([#1274](https://github.com/joshua-jingu-lee/ante/pull/1274),
  [`1cd8277`](https://github.com/joshua-jingu-lee/ante/commit/1cd82777977c65d9d6a2996623f5987da1be8d1e))

- **frontend**: Adapt strategy report data generated types
  ([#1275](https://github.com/joshua-jingu-lee/ante/pull/1275),
  [`5f4baa6`](https://github.com/joshua-jingu-lee/ante/commit/5f4baa626909d02e5645c008a75a7ec54a4f5e16))

- **frontend**: Align account bot adapter view contracts (#1223)
  ([#1252](https://github.com/joshua-jingu-lee/ante/pull/1252),
  [`6685970`](https://github.com/joshua-jingu-lee/ante/commit/6685970710bdb43bd4cc9acbabcf9a2727b7cae0))

- **frontend**: Align system adapter view contract (#1222)
  ([#1251](https://github.com/joshua-jingu-lee/ante/pull/1251),
  [`348afe8`](https://github.com/joshua-jingu-lee/ante/commit/348afe8ced21ca6d6fb906ae2dc6c8936f7460c9))

- **frontend**: Align treasury portfolio adapter views (#1224)
  ([#1253](https://github.com/joshua-jingu-lee/ante/pull/1253),
  [`80ec9cd`](https://github.com/joshua-jingu-lee/ante/commit/80ec9cd0042819c0524f7ba5a9ab213788443243))

- **frontend**: Prepare api type boundary strict gate
  ([#1277](https://github.com/joshua-jingu-lee/ante/pull/1277),
  [`370b7d9`](https://github.com/joshua-jingu-lee/ante/commit/370b7d9840e4e6f11abe70484be2ccfc7b78252f))

- **frontend,approval**: Extend ApprovalType with backend SSOT 5 entries and add unknown fallback
  ([#1504](https://github.com/joshua-jingu-lee/ante/pull/1504),
  [`5b16c96`](https://github.com/joshua-jingu-lee/ante/commit/5b16c96d6132f17451161b096e7a5790936dabf1))

- **gateway**: Split-3 per-bot LiveDataProvider with account_id binding
  ([#1247](https://github.com/joshua-jingu-lee/ante/pull/1247),
  [`91b2afb`](https://github.com/joshua-jingu-lee/ante/commit/91b2afb3bd264ec5ef212bde1df29c0e0205a180))

- **gateway**: Split-3 require_account_id on APIGateway and StreamIntegration ctor
  ([#1247](https://github.com/joshua-jingu-lee/ante/pull/1247),
  [`91b2afb`](https://github.com/joshua-jingu-lee/ante/commit/91b2afb3bd264ec5ef212bde1df29c0e0205a180))

- **main**: Mark account_service runtime started after boot migration
  ([#1169](https://github.com/joshua-jingu-lee/ante/pull/1169),
  [`90dc2b8`](https://github.com/joshua-jingu-lee/ante/commit/90dc2b8fdb4fd5888ee760e0e0bc305ee8e44a4b))

- **main**: Wire APIGateway-backed quote resolver into Treasury
  ([#1350](https://github.com/joshua-jingu-lee/ante/pull/1350),
  [`563df47`](https://github.com/joshua-jingu-lee/ante/commit/563df4742324680ade2126daf6aa4c7b5bb466f5))

- **member**: Add list-invalid-roles CLI and runbook for legacy cleanup
  ([#1509](https://github.com/joshua-jingu-lee/ante/pull/1509),
  [`71ae6cb`](https://github.com/joshua-jingu-lee/ante/commit/71ae6cb1017d46601b304e5efa6019ada4889bc4))

- **member,cli**: Operator cleanup tooling for legacy invalid-role rows
  ([#1509](https://github.com/joshua-jingu-lee/ante/pull/1509),
  [`71ae6cb`](https://github.com/joshua-jingu-lee/ante/commit/71ae6cb1017d46601b304e5efa6019ada4889bc4))

- **stop**: Route stop registered/triggered/expired through on_order_update (#1336)
  ([#1349](https://github.com/joshua-jingu-lee/ante/pull/1349),
  [`58af809`](https://github.com/joshua-jingu-lee/ante/commit/58af809433e1586374dabeaec795cefb2813dae6))

- **system**: Align kill switch backend to halt/clear-halt SSOT
  ([#1237](https://github.com/joshua-jingu-lee/ante/pull/1237),
  [`6304774`](https://github.com/joshua-jingu-lee/ante/commit/6304774ba83a4b74417c690089f962bd58d1982e))

- **trade**: #1946 KIS 체결 반영 경로 — OrderTracker + FillApplier + REST 백스톱 폴
  ([#1953](https://github.com/joshua-jingu-lee/ante/pull/1953),
  [`9f548b4`](https://github.com/joshua-jingu-lee/ante/commit/9f548b463cf4f6794fc788270a58cfa084471eb4))

- **trade**: #1946 KIS 체결 반영 경로(fill-recovery) — OrderTracker + FillApplier + REST 백스톱
  ([#1953](https://github.com/joshua-jingu-lee/ante/pull/1953),
  [`9f548b4`](https://github.com/joshua-jingu-lee/ante/commit/9f548b463cf4f6794fc788270a58cfa084471eb4))

- **trade**: #1948 전략 get_open_orders(live) OrderTracker sync 백엔드
  ([#1959](https://github.com/joshua-jingu-lee/ante/pull/1959),
  [`241e558`](https://github.com/joshua-jingu-lee/ante/commit/241e558b76aead43f103aefca0e2ae7affd25d79))

- **trade**: #1949 체결 이벤트 transactional outbox — durability/at-least-once
  ([#1958](https://github.com/joshua-jingu-lee/ante/pull/1958),
  [`ee19d56`](https://github.com/joshua-jingu-lee/ante/commit/ee19d56e6468286f6d6435c409420e5cb917240d))

- **trade**: Enforce account-aware trades schema (#1257)
  ([#1270](https://github.com/joshua-jingu-lee/ante/pull/1270),
  [`43bde21`](https://github.com/joshua-jingu-lee/ante/commit/43bde21ecf703289fdfae00917d3809ca7233fb8))

- **trade**: Make positions account-aware (#1259)
  ([#1272](https://github.com/joshua-jingu-lee/ante/pull/1272),
  [`71cceb8`](https://github.com/joshua-jingu-lee/ante/commit/71cceb8a02720a4e638bcb000ceeab1a58dd585a))

- **treasury**: Account-scoped quote resolver for market buy reserve (#1333)
  ([#1350](https://github.com/joshua-jingu-lee/ante/pull/1350),
  [`563df47`](https://github.com/joshua-jingu-lee/ante/commit/563df4742324680ade2126daf6aa4c7b5bb466f5))

- **treasury**: Add quote resolver path for market buy reserve
  ([#1350](https://github.com/joshua-jingu-lee/ante/pull/1350),
  [`563df47`](https://github.com/joshua-jingu-lee/ante/commit/563df4742324680ade2126daf6aa4c7b5bb466f5))

- **treasury**: Align account-aware DB schema (#1258)
  ([#1271](https://github.com/joshua-jingu-lee/ante/pull/1271),
  [`e1c002c`](https://github.com/joshua-jingu-lee/ante/commit/e1c002c3742d8671233681a3c3e9f228a525e7ca))

- **web**: Add minProperties:1 to mutable update request schema
  ([#1168](https://github.com/joshua-jingu-lee/ante/pull/1168),
  [`6c34618`](https://github.com/joshua-jingu-lee/ante/commit/6c346186251a53293cc77e87a067f3af3b684ebb))

- **web**: Install openapi customizer to guarantee ErrorResponse in components
  ([#1180](https://github.com/joshua-jingu-lee/ante/pull/1180),
  [`19002a9`](https://github.com/joshua-jingu-lee/ante/commit/19002a996b8757b8fdba9e4e1b524e0ff017c982))

- **web**: RequireAuthMiddleware default-deny gate + 197 fixture migration (#1403)
  ([#1421](https://github.com/joshua-jingu-lee/ante/pull/1421),
  [`e3c782f`](https://github.com/joshua-jingu-lee/ante/commit/e3c782ff6018044ee8f6d5aa79ea469a5c2a23f6))

- **web-api**: #1651 비-extra_forbidden loc default-deny discovery lock (옵션3 하이브리드, 사용자 A)
  ([#1653](https://github.com/joshua-jingu-lee/ante/pull/1653),
  [`30b43a5`](https://github.com/joshua-jingu-lee/ante/commit/30b43a5cdba6e282e6fda6d839eeb8c1ae144b3a))

### Refactoring

- #1724 validate_new_account_id에 context 파라미터 추가 (require_account_id 동형 정렬)
  ([#1734](https://github.com/joshua-jingu-lee/ante/pull/1734),
  [`320bc2a`](https://github.com/joshua-jingu-lee/ante/commit/320bc2a92110e0528dd3850d4830efa6b4416ab1))

- #1823 contract drift test helper skeleton (Click leaf / IPC registry / exception / fmt.error
  iterators) ([#1838](https://github.com/joshua-jingu-lee/ante/pull/1838),
  [`c3f08ff`](https://github.com/joshua-jingu-lee/ante/commit/c3f08ff787c98e370d19cc6ff1359120ef866b3e))

- #1840 ErrorSpec mapper + CLI/IPC error helper (helper-only, no callsite migration)
  ([#1861](https://github.com/joshua-jingu-lee/ante/pull/1861),
  [`a541176`](https://github.com/joshua-jingu-lee/ante/commit/a541176fecf46c5e83c6bad9de6df9d93a17bb5e))

- #1842 account error contract registry mirror + CLI direct ↔ IPC equivalence lock
  ([#1863](https://github.com/joshua-jingu-lee/ante/pull/1863),
  [`31a1413`](https://github.com/joshua-jingu-lee/ante/commit/31a14137062f8bc578ae21a4c8bd1698bdd36371))

- #1842 align account CLI 9 callsites via emit_cli_error
  ([#1863](https://github.com/joshua-jingu-lee/ante/pull/1863),
  [`31a1413`](https://github.com/joshua-jingu-lee/ante/commit/31a14137062f8bc578ae21a4c8bd1698bdd36371))

- #1842 register account 12 sub-class to ErrorSpec registry (mirror .code)
  ([#1863](https://github.com/joshua-jingu-lee/ante/pull/1863),
  [`31a1413`](https://github.com/joshua-jingu-lee/ante/commit/31a14137062f8bc578ae21a4c8bd1698bdd36371))

- #1843 sub-PR 1 register member 5 sub-class + align CLI member callsites
  ([#1865](https://github.com/joshua-jingu-lee/ante/pull/1865),
  [`419ddf5`](https://github.com/joshua-jingu-lee/ante/commit/419ddf5a922518263287a74cb936eab5705b5f3f))

- #1843 sub-PR 2 align approval CLI 9 callsites via emit_cli_error
  ([#1866](https://github.com/joshua-jingu-lee/ante/pull/1866),
  [`a19d873`](https://github.com/joshua-jingu-lee/ante/commit/a19d873cc9450df9befb0cc914afb76510980c86))

- #1843 sub-PR 2 register approval 2 sub-class to ErrorSpec registry (mirror .code)
  ([#1866](https://github.com/joshua-jingu-lee/ante/pull/1866),
  [`a19d873`](https://github.com/joshua-jingu-lee/ante/commit/a19d873cc9450df9befb0cc914afb76510980c86))

- #1843 sub-PR 3 register bot 5 sub-class + align CLI bot callsites
  ([#1867](https://github.com/joshua-jingu-lee/ante/pull/1867),
  [`3b5f2b5`](https://github.com/joshua-jingu-lee/ante/commit/3b5f2b5f0cf64a03916a0875bafd971cceb57929))

- #1843-1 member error contract registry mirror + CLI direct ↔ IPC equivalence lock
  ([#1865](https://github.com/joshua-jingu-lee/ante/pull/1865),
  [`419ddf5`](https://github.com/joshua-jingu-lee/ante/commit/419ddf5a922518263287a74cb936eab5705b5f3f))

- #1843-2 approval error contract registry mirror + CLI direct ↔ IPC equivalence lock
  ([#1866](https://github.com/joshua-jingu-lee/ante/pull/1866),
  [`a19d873`](https://github.com/joshua-jingu-lee/ante/commit/a19d873cc9450df9befb0cc914afb76510980c86))

- #1843-3 bot error contract registry mirror + CLI direct ↔ IPC equivalence lock
  ([#1867](https://github.com/joshua-jingu-lee/ante/pull/1867),
  [`3b5f2b5`](https://github.com/joshua-jingu-lee/ante/commit/3b5f2b5f0cf64a03916a0875bafd971cceb57929))

- #1843-4 CLI treasury callsite emit_cli_error 정렬 (Step 2)
  ([#1868](https://github.com/joshua-jingu-lee/ante/pull/1868),
  [`4f23925`](https://github.com/joshua-jingu-lee/ante/commit/4f2392529cd8f6380ff6e641c86037e6af4bc46b))

- #1843-4 register treasury 7 sub-class in error registry (Step 1)
  ([#1868](https://github.com/joshua-jingu-lee/ante/pull/1868),
  [`4f23925`](https://github.com/joshua-jingu-lee/ante/commit/4f2392529cd8f6380ff6e641c86037e6af4bc46b))

- #1843-4 treasury error contract registry mirror + CLI direct ↔ IPC equivalence lock
  ([#1868](https://github.com/joshua-jingu-lee/ante/pull/1868),
  [`4f23925`](https://github.com/joshua-jingu-lee/ante/commit/4f2392529cd8f6380ff6e641c86037e6af4bc46b))

- #1843-5 broker error contract registry + origin msg_cd log-only separation
  ([#1869](https://github.com/joshua-jingu-lee/ante/pull/1869),
  [`18b1e94`](https://github.com/joshua-jingu-lee/ante/commit/18b1e9430a7c7c4dd8569512caad51e59a0c6ac1))

- #1843-5 broker exceptions .code + registry mirror + CLI helper alignment
  ([#1869](https://github.com/joshua-jingu-lee/ante/pull/1869),
  [`18b1e94`](https://github.com/joshua-jingu-lee/ante/commit/18b1e9430a7c7c4dd8569512caad51e59a0c6ac1))

- #1843-6 drift allowlist Final lock — strategy/update + base-only
  ([#1871](https://github.com/joshua-jingu-lee/ante/pull/1871),
  [`4a194a3`](https://github.com/joshua-jingu-lee/ante/commit/4a194a33e9038b106be544fc6d5f47df7ef601ea))

- #1843-6 strategy/config/rule typed code + ErrorSpec registry
  ([#1871](https://github.com/joshua-jingu-lee/ante/pull/1871),
  [`4a194a3`](https://github.com/joshua-jingu-lee/ante/commit/4a194a33e9038b106be544fc6d5f47df7ef601ea))

- #1843-6 strategy/config/rule/update sweep + final allowlist clear (closes #1843)
  ([#1871](https://github.com/joshua-jingu-lee/ante/pull/1871),
  [`4a194a3`](https://github.com/joshua-jingu-lee/ante/commit/4a194a33e9038b106be544fc6d5f47df7ef601ea))

- #1843-6 strategy/update CLI fmt.error code 정렬
  ([#1871](https://github.com/joshua-jingu-lee/ante/pull/1871),
  [`4a194a3`](https://github.com/joshua-jingu-lee/ante/commit/4a194a33e9038b106be544fc6d5f47df7ef601ea))

- #1844 CLI command contract registry shell + leaf coverage skeleton
  ([#1872](https://github.com/joshua-jingu-lee/ante/pull/1872),
  [`cebd617`](https://github.com/joshua-jingu-lee/ante/commit/cebd617d8080903db6d91b2ba73e5b93d3caa534))

- #1846 account domain OutputContract migration (9 leaf entries + drift lock + baseline test 종료)
  ([#1874](https://github.com/joshua-jingu-lee/ante/pull/1874),
  [`e334589`](https://github.com/joshua-jingu-lee/ante/commit/e334589c466126acec77b8180f43e6a03ad12136))

- #1846 register account 9 OutputContract entries and ease baseline tests
  ([#1874](https://github.com/joshua-jingu-lee/ante/pull/1874),
  [`e334589`](https://github.com/joshua-jingu-lee/ante/commit/e334589c466126acec77b8180f43e6a03ad12136))

- #1847 sub-PR 4 treasury OutputContract registry (9 leaf)
  ([#1878](https://github.com/joshua-jingu-lee/ante/pull/1878),
  [`eaa340f`](https://github.com/joshua-jingu-lee/ante/commit/eaa340f3a7f314799efdc119ce7ea19b04285820))

- #1847 sub-PR 5 strategy OutputContract registry (7 leaf)
  ([#1879](https://github.com/joshua-jingu-lee/ante/pull/1879),
  [`fa9ccbb`](https://github.com/joshua-jingu-lee/ante/commit/fa9ccbb0b718da19984555b102e0362b595de9f3))

- #1847 sub-PR 7 — broker + system OutputContract migration (9 leaf)
  ([#1881](https://github.com/joshua-jingu-lee/ante/pull/1881),
  [`45d5163`](https://github.com/joshua-jingu-lee/ante/commit/45d51639612b21e5ba88534ff7f8f779bc7d977c))

- #1847 sub-PR 8 — instrument + config + rule OutputContract migration (10 leaf)
  ([#1882](https://github.com/joshua-jingu-lee/ante/pull/1882),
  [`ba222c5`](https://github.com/joshua-jingu-lee/ante/commit/ba222c574dbb3f1d7e8434d08f47d22a0ae29d22))

- #1847 sub-PR 9 (final) — trade+backtest+audit+signal + leaf coverage final lock (6 leaf)
  ([#1883](https://github.com/joshua-jingu-lee/ante/pull/1883),
  [`1e8f4e9`](https://github.com/joshua-jingu-lee/ante/commit/1e8f4e9ea44c5543c0f7785f0950f743dfe0d594))

- #1847-1 member domain OutputContract migration (12 leaf entries)
  ([#1875](https://github.com/joshua-jingu-lee/ante/pull/1875),
  [`d728fc1`](https://github.com/joshua-jingu-lee/ante/commit/d728fc1d0f25c55a33f7e92b887433be1940108e))

- #1847-2 bot domain OutputContract migration (11 leaf entries)
  ([#1876](https://github.com/joshua-jingu-lee/ante/pull/1876),
  [`3debab9`](https://github.com/joshua-jingu-lee/ante/commit/3debab9189278d47f3db86022f94381a5922af0a))

- #1847-2 register bot domain 11 leaf contracts in CLI registry
  ([#1876](https://github.com/joshua-jingu-lee/ante/pull/1876),
  [`3debab9`](https://github.com/joshua-jingu-lee/ante/commit/3debab9189278d47f3db86022f94381a5922af0a))

- #1847-3 approval domain OutputContract migration (10 leaf entries)
  ([#1877](https://github.com/joshua-jingu-lee/ante/pull/1877),
  [`caeb3fe`](https://github.com/joshua-jingu-lee/ante/commit/caeb3fec741087786bfa0be483f0e72423fe7dc3))

- #1847-4 treasury domain OutputContract migration (9 leaf entries)
  ([#1878](https://github.com/joshua-jingu-lee/ante/pull/1878),
  [`eaa340f`](https://github.com/joshua-jingu-lee/ante/commit/eaa340f3a7f314799efdc119ce7ea19b04285820))

- #1847-5 strategy domain OutputContract migration (7 leaf entries)
  ([#1879](https://github.com/joshua-jingu-lee/ante/pull/1879),
  [`fa9ccbb`](https://github.com/joshua-jingu-lee/ante/commit/fa9ccbb0b718da19984555b102e0362b595de9f3))

- #1847-6 data + report domain OutputContract migration (11 leaf entries)
  ([#1880](https://github.com/joshua-jingu-lee/ante/pull/1880),
  [`0172374`](https://github.com/joshua-jingu-lee/ante/commit/017237446ffdb546bba8725481d06f0a5052c244))

- #1849 CommandSpec metadata 7 필드 확장 + 27 commands 필수값 채우기
  ([#1884](https://github.com/joshua-jingu-lee/ante/pull/1884),
  [`2928536`](https://github.com/joshua-jingu-lee/ante/commit/292853678b3c1b5be6634e7dcfacd9045a4b473d))

- #1849 IPC CommandSpec metadata 필드 확장 + 27 commands 필수값 채우기
  ([#1884](https://github.com/joshua-jingu-lee/ante/pull/1884),
  [`2928536`](https://github.com/joshua-jingu-lee/ante/commit/292853678b3c1b5be6634e7dcfacd9045a4b473d))

- #1850 IPC dispatch wrapper required_services + account_id_policy preflight
  ([#1885](https://github.com/joshua-jingu-lee/ante/pull/1885),
  [`860125d`](https://github.com/joshua-jingu-lee/ante/commit/860125db8232b49ffb959ea1f24fa161bd19f37a))

- #1851 IPC dispatch wrapper audit_action auto-fire + _audit_detail reserved strip
  ([#1886](https://github.com/joshua-jingu-lee/ante/pull/1886),
  [`2b6f42c`](https://github.com/joshua-jingu-lee/ante/commit/2b6f42c6e882fa9858b4391a0f97bb96fbc22c0c))

- #1852 account IPC handler wrapper migration
  ([#1888](https://github.com/joshua-jingu-lee/ante/pull/1888),
  [`2a638eb`](https://github.com/joshua-jingu-lee/ante/commit/2a638ebbbcce8bff7729f75ea91081f121b5973f))

- #1853 IPC metadata drift + remaining handler migration (closes #1819)
  ([#1890](https://github.com/joshua-jingu-lee/ante/pull/1890),
  [`4fc6a0b`](https://github.com/joshua-jingu-lee/ante/commit/4fc6a0b475ea8a3a0a99458005ed165eeb673a45))

- #1853 rule.update audit handler migration to dispatch wrapper
  ([#1890](https://github.com/joshua-jingu-lee/ante/pull/1890),
  [`4fc6a0b`](https://github.com/joshua-jingu-lee/ante/commit/4fc6a0b475ea8a3a0a99458005ed165eeb673a45))

- #1855 CLI DB lifecycle async context manager (open_cli_db)
  ([#1889](https://github.com/joshua-jingu-lee/ante/pull/1889),
  [`a183051`](https://github.com/joshua-jingu-lee/ante/commit/a18305198468d007827b4b5956462c5a092d15b6))

- #1856 account/member/approval CLI factory migration (open_cli_db 활용)
  ([#1891](https://github.com/joshua-jingu-lee/ante/pull/1891),
  [`1894a23`](https://github.com/joshua-jingu-lee/ante/commit/1894a23db65d62cfb05b7f3f7b5ee38334a592b2))

- #1857 remaining offline/cold-path CLI domain factory migration (broker/signal 제외)
  ([#1892](https://github.com/joshua-jingu-lee/ante/pull/1892),
  [`7c1337c`](https://github.com/joshua-jingu-lee/ante/commit/7c1337c4bcc9210c4bd0ced590c4ef3d28945948))

- #1870 bot/config text-mode prefix UX — allowlist intended_no_code 영구 이동
  ([#1895](https://github.com/joshua-jingu-lee/ante/pull/1895),
  [`3a0ce2c`](https://github.com/joshua-jingu-lee/ante/commit/3a0ce2c188d9b823a274c2c1044e7ee453d18de1))

- Align approval bot create executor contract
  ([#1285](https://github.com/joshua-jingu-lee/ante/pull/1285),
  [`f1be173`](https://github.com/joshua-jingu-lee/ante/commit/f1be17337de35dfe4201410c3a8fdf877d94b104))

- Align bot create auto approve with virtual accounts
  ([#1284](https://github.com/joshua-jingu-lee/ante/pull/1284),
  [`c98e6c3`](https://github.com/joshua-jingu-lee/ante/commit/c98e6c3f9399dea7d4b3c5873a33fb53c1b01493))

- Align frontend bot trading mode ([#1287](https://github.com/joshua-jingu-lee/ante/pull/1287),
  [`dcf7ccb`](https://github.com/joshua-jingu-lee/ante/commit/dcf7ccb393bfbf36da603ecc88449c07a788bf70))

- Dependency scope-only 단순화 — middleware 책임 분리 (#1408)
  ([#1430](https://github.com/joshua-jingu-lee/ante/pull/1430),
  [`5535d9f`](https://github.com/joshua-jingu-lee/ante/commit/5535d9f2480e2b4a21eb0fbe924e5aac2b1ae758))

- Nest cli success json data ([#1291](https://github.com/joshua-jingu-lee/ante/pull/1291),
  [`7b259e7`](https://github.com/joshua-jingu-lee/ante/commit/7b259e725b1663bfdd5069b53a7c0a64a8cf2bc4))

- Remove dashboard and web api core surface
  ([#1718](https://github.com/joshua-jingu-lee/ante/pull/1718),
  [`267434f`](https://github.com/joshua-jingu-lee/ante/commit/267434fe57b45d2084be1675d17b065ec098e4c6))

- Rename virtual bot provider internals
  ([#1286](https://github.com/joshua-jingu-lee/ante/pull/1286),
  [`17d3f20`](https://github.com/joshua-jingu-lee/ante/commit/17d3f20e9faf07e13c1809d30c006f5740d26303))

- Require_scope dependency factory 일반화 (#1406)
  ([#1427](https://github.com/joshua-jingu-lee/ante/pull/1427),
  [`c329a4a`](https://github.com/joshua-jingu-lee/ante/commit/c329a4a170b94e29b994900a57c19956d08ad476))

- **#1847-1**: Register member 12 OutputContract entries
  ([#1875](https://github.com/joshua-jingu-lee/ante/pull/1875),
  [`d728fc1`](https://github.com/joshua-jingu-lee/ante/commit/d728fc1d0f25c55a33f7e92b887433be1940108e))

- **account**: Add AccountStructuralChangeRequiresStoppedServerError with stable code
  ([#1169](https://github.com/joshua-jingu-lee/ante/pull/1169),
  [`90dc2b8`](https://github.com/joshua-jingu-lee/ante/commit/90dc2b8fdb4fd5888ee760e0e0bc305ee8e44a4b))

- **account**: Add runtime guard to AccountService create/update/delete
  ([#1169](https://github.com/joshua-jingu-lee/ante/pull/1169),
  [`90dc2b8`](https://github.com/joshua-jingu-lee/ante/commit/90dc2b8fdb4fd5888ee760e0e0bc305ee8e44a4b))

- **account**: Add service-layer runtime guard for structural mutations (#1144)
  ([#1169](https://github.com/joshua-jingu-lee/ante/pull/1169),
  [`90dc2b8`](https://github.com/joshua-jingu-lee/ante/commit/90dc2b8fdb4fd5888ee760e0e0bc305ee8e44a4b))

- **account**: Encapsulate bootstrap seed creation as private helper
  ([#1239](https://github.com/joshua-jingu-lee/ante/pull/1239),
  [`270a17a`](https://github.com/joshua-jingu-lee/ante/commit/270a17a192886233658cf2229d136fc4511c642f))

- **bot**: #1924 2차 — src/ante/bot/ invariant 중심 주석 정리
  ([#1940](https://github.com/joshua-jingu-lee/ante/pull/1940),
  [`1d628ed`](https://github.com/joshua-jingu-lee/ante/commit/1d628edab10bb99070783d1fb8df36b60a47b64a))

- **cli**: #1924 middleware.py invariant 중심 주석 정리
  ([#1939](https://github.com/joshua-jingu-lee/ante/pull/1939),
  [`391f552`](https://github.com/joshua-jingu-lee/ante/commit/391f55287deb6fab046e22edaf1f6a1b9c5d7c39))

- **cli**: #1941 commands/ invariant 중심 주석 정리 (#1924 시리즈 3차)
  ([#1942](https://github.com/joshua-jingu-lee/ante/pull/1942),
  [`b8cea12`](https://github.com/joshua-jingu-lee/ante/commit/b8cea12b2d6ae9bab607fa6d613b405418547493))

- **cli**: Align JSON error envelope with SSOT (status/code/message)
  ([#1226](https://github.com/joshua-jingu-lee/ante/pull/1226),
  [`b73f9dd`](https://github.com/joshua-jingu-lee/ante/commit/b73f9dd501f018ac75ea58f7bac091cba6a0592d))

- **cli**: Enforce --yes gate before no-update early return
  ([#1207](https://github.com/joshua-jingu-lee/ante/pull/1207),
  [`c1b0227`](https://github.com/joshua-jingu-lee/ante/commit/c1b0227ab71b67b2dab82c5f88e813a2c8f61004))

- **cli**: Make account create/set-credentials/delete non-interactive
  ([#1206](https://github.com/joshua-jingu-lee/ante/pull/1206),
  [`20034a4`](https://github.com/joshua-jingu-lee/ante/commit/20034a4ec77873c0b2d7a4bfd99e4917dc4f562f))

- **cli**: Make bot create/remove non-interactive (#1175)
  ([#1204](https://github.com/joshua-jingu-lee/ante/pull/1204),
  [`cc6565c`](https://github.com/joshua-jingu-lee/ante/commit/cc6565cd2efbaf5a86c79fc0f2b0da28f5cc8e08))

- **cli**: Make member revoke/reset-password/regenerate-recovery-key non-interactive
  ([#1208](https://github.com/joshua-jingu-lee/ante/pull/1208),
  [`e875a73`](https://github.com/joshua-jingu-lee/ante/commit/e875a73978930e95ac96aaae4bf3479be4a1a580))

- **cli**: Make update non-interactive ([#1207](https://github.com/joshua-jingu-lee/ante/pull/1207),
  [`c1b0227`](https://github.com/joshua-jingu-lee/ante/commit/c1b0227ab71b67b2dab82c5f88e813a2c8f61004))

- **cli**: Move update --yes gate before PyPI lookup
  ([#1207](https://github.com/joshua-jingu-lee/ante/pull/1207),
  [`c1b0227`](https://github.com/joshua-jingu-lee/ante/commit/c1b0227ab71b67b2dab82c5f88e813a2c8f61004))

- **cli**: Reject empty direct credential value and store decimal broker_config as float
  ([#1206](https://github.com/joshua-jingu-lee/ante/pull/1206),
  [`20034a4`](https://github.com/joshua-jingu-lee/ante/commit/20034a4ec77873c0b2d7a4bfd99e4917dc4f562f))

- **cli/ipc**: Resolve IPC socket via runtime resolver
  ([#1182](https://github.com/joshua-jingu-lee/ante/pull/1182),
  [`290bcff`](https://github.com/joshua-jingu-lee/ante/commit/290bcff5afbd8688b251a0cc3c1764cb2071fac8))

- **contracts**: #1847 sub-PR 6 register data + report OutputContract entries
  ([#1880](https://github.com/joshua-jingu-lee/ante/pull/1880),
  [`0172374`](https://github.com/joshua-jingu-lee/ante/commit/017237446ffdb546bba8725481d06f0a5052c244))

- **core**: Introduce ante.core.market_data_vocab SSOT + behavior-preserving consumer delegation
  (#1613) ([#1616](https://github.com/joshua-jingu-lee/ante/pull/1616),
  [`1e4ada8`](https://github.com/joshua-jingu-lee/ante/commit/1e4ada8b99e32ed7970fcedbc883aa2b99d1ff2f))

- **core**: Introduce exchange vocabulary SSOT, delegate validator/store (#1576)
  ([#1581](https://github.com/joshua-jingu-lee/ante/pull/1581),
  [`2b9352d`](https://github.com/joshua-jingu-lee/ante/commit/2b9352d2cdfb8a8b98cc277f2cc3b9b6202dfc23))

- **ipc**: Split IPCServer.stop into stop_accepting + drain_connections + unlink_socket
  ([#1183](https://github.com/joshua-jingu-lee/ante/pull/1183),
  [`7d8d9a5`](https://github.com/joshua-jingu-lee/ante/commit/7d8d9a53494f6fcd82d7baed8a77235f5d472aab))

- **ipc**: Use exception.code attribute for stable error codes
  ([#1169](https://github.com/joshua-jingu-lee/ante/pull/1169),
  [`90dc2b8`](https://github.com/joshua-jingu-lee/ante/commit/90dc2b8fdb4fd5888ee760e0e0bc305ee8e44a4b))

- **main,cli/system**: Migrate PID file and IPC socket to runtime resolver with legacy read fallback
  ([#1182](https://github.com/joshua-jingu-lee/ante/pull/1182),
  [`290bcff`](https://github.com/joshua-jingu-lee/ante/commit/290bcff5afbd8688b251a0cc3c1764cb2071fac8))

- **reports**: Scope down to input validation; defer ratio unification to follow-up
  ([#1363](https://github.com/joshua-jingu-lee/ante/pull/1363),
  [`0dcb64a`](https://github.com/joshua-jingu-lee/ante/commit/0dcb64a386730d74acc1f34bf346ae7416db3c93))

- **strategy,cli**: Lazy-load IndicatorCalculator via PEP 562 __getattr__
  ([#1502](https://github.com/joshua-jingu-lee/ante/pull/1502),
  [`29c241f`](https://github.com/joshua-jingu-lee/ante/commit/29c241f23043f7189ae98d59d6df7ecb349d1483))

- **web**: Align explicit 4xx/5xx responses to application/problem+json
  ([#1180](https://github.com/joshua-jingu-lee/ante/pull/1180),
  [`19002a9`](https://github.com/joshua-jingu-lee/ante/commit/19002a996b8757b8fdba9e4e1b524e0ff017c982))

- **web**: Catch AccountStructuralChangeRequiresStoppedServerError as 409
  ([#1169](https://github.com/joshua-jingu-lee/ante/pull/1169),
  [`90dc2b8`](https://github.com/joshua-jingu-lee/ante/commit/90dc2b8fdb4fd5888ee760e0e0bc305ee8e44a4b))

### Testing

- #1722 R3 cleanup spy를 AsyncMock + await_count로 교체
  ([#1732](https://github.com/joshua-jingu-lee/ante/pull/1732),
  [`c56a7db`](https://github.com/joshua-jingu-lee/ante/commit/c56a7db3bc6929aa70ec65ea60bdb5842dc883d4))

- #1759 R3/R4 subprocess CLI coverage 추가 (Codex blocking)
  ([#1770](https://github.com/joshua-jingu-lee/ante/pull/1770),
  [`7aa83b4`](https://github.com/joshua-jingu-lee/ante/commit/7aa83b40fb855e83a022083112cb57b8682574d8))

- #1841 error taxonomy drift guard + fmt.error code missing allowlist (3 families)
  ([#1862](https://github.com/joshua-jingu-lee/ante/pull/1862),
  [`862e37c`](https://github.com/joshua-jingu-lee/ante/commit/862e37cf63e62077fb42a8c2e44550eee7ff87a8))

- #1842 account CLI direct ↔ IPC error code equivalence lock (17 tests)
  ([#1863](https://github.com/joshua-jingu-lee/ante/pull/1863),
  [`31a1413`](https://github.com/joshua-jingu-lee/ante/commit/31a14137062f8bc578ae21a4c8bd1698bdd36371))

- #1843 sub-PR 1 member CLI direct ↔ IPC error code equivalence lock (14 tests)
  ([#1865](https://github.com/joshua-jingu-lee/ante/pull/1865),
  [`419ddf5`](https://github.com/joshua-jingu-lee/ante/commit/419ddf5a922518263287a74cb936eab5705b5f3f))

- #1843 sub-PR 2 approval CLI direct ↔ IPC error code equivalence lock (7 tests)
  ([#1866](https://github.com/joshua-jingu-lee/ante/pull/1866),
  [`a19d873`](https://github.com/joshua-jingu-lee/ante/commit/a19d873cc9450df9befb0cc914afb76510980c86))

- #1843 sub-PR 3 bot CLI direct ↔ IPC envelope error code equivalence lock
  ([#1867](https://github.com/joshua-jingu-lee/ante/pull/1867),
  [`3b5f2b5`](https://github.com/joshua-jingu-lee/ante/commit/3b5f2b5f0cf64a03916a0875bafd971cceb57929))

- #1843-4 treasury allowlist 정리 + CLI↔IPC equivalence lock (Steps 3-4)
  ([#1868](https://github.com/joshua-jingu-lee/ante/pull/1868),
  [`4f23925`](https://github.com/joshua-jingu-lee/ante/commit/4f2392529cd8f6380ff6e641c86037e6af4bc46b))

- #1843-5 broker CLI ↔ IPC error equivalence + origin msg_cd separation
  ([#1869](https://github.com/joshua-jingu-lee/ante/pull/1869),
  [`18b1e94`](https://github.com/joshua-jingu-lee/ante/commit/18b1e9430a7c7c4dd8569512caad51e59a0c6ac1))

- #1843-6 strategy/config/rule CLI ↔ IPC error code equivalence lock
  ([#1871](https://github.com/joshua-jingu-lee/ante/pull/1871),
  [`4a194a3`](https://github.com/joshua-jingu-lee/ante/commit/4a194a33e9038b106be544fc6d5f47df7ef601ea))

- #1845 CLI registry auth-scope-master drift tests (4 family deferred lock)
  ([#1873](https://github.com/joshua-jingu-lee/ante/pull/1873),
  [`f47007b`](https://github.com/joshua-jingu-lee/ante/commit/f47007baca811e39b17303682201f26f3231de39))

- #1846 account success output ↔ registry OutputContract drift lock
  ([#1874](https://github.com/joshua-jingu-lee/ante/pull/1874),
  [`e334589`](https://github.com/joshua-jingu-lee/ante/commit/e334589c466126acec77b8180f43e6a03ad12136))

- #1847 sub-PR 4 treasury success output drift lock (12 scenarios)
  ([#1878](https://github.com/joshua-jingu-lee/ante/pull/1878),
  [`eaa340f`](https://github.com/joshua-jingu-lee/ante/commit/eaa340f3a7f314799efdc119ce7ea19b04285820))

- #1847 sub-PR 5 strategy success output drift lock (10 scenarios)
  ([#1879](https://github.com/joshua-jingu-lee/ante/pull/1879),
  [`fa9ccbb`](https://github.com/joshua-jingu-lee/ante/commit/fa9ccbb0b718da19984555b102e0362b595de9f3))

- #1847-2 bot CLI success output ↔ registry OutputContract drift lock
  ([#1876](https://github.com/joshua-jingu-lee/ante/pull/1876),
  [`3debab9`](https://github.com/joshua-jingu-lee/ante/commit/3debab9189278d47f3db86022f94381a5922af0a))

- #1848 CLI registry ↔ docs drift + guide/cli.md regen idempotent (closes #1815)
  ([#1894](https://github.com/joshua-jingu-lee/ante/pull/1894),
  [`a8bb234`](https://github.com/joshua-jingu-lee/ante/commit/a8bb23457663e9a75ded0ffce05baa95c0987689))

- #1848 docs/specs/cli/03-commands.md command table parser helper
  ([#1894](https://github.com/joshua-jingu-lee/ante/pull/1894),
  [`a8bb234`](https://github.com/joshua-jingu-lee/ante/commit/a8bb23457663e9a75ded0ffce05baa95c0987689))

- #1848 Family A — CLI registry ↔ docs command table drift tests + baseline
  ([#1894](https://github.com/joshua-jingu-lee/ante/pull/1894),
  [`a8bb234`](https://github.com/joshua-jingu-lee/ante/commit/a8bb23457663e9a75ded0ffce05baa95c0987689))

- #1848 Family B — guide/cli.md regen idempotent + determinism tests
  ([#1894](https://github.com/joshua-jingu-lee/ante/pull/1894),
  [`a8bb234`](https://github.com/joshua-jingu-lee/ante/commit/a8bb23457663e9a75ded0ffce05baa95c0987689))

- #1850 fixture 보강 — required_services preflight 통과를 위한 mock 주입
  ([#1885](https://github.com/joshua-jingu-lee/ante/pull/1885),
  [`860125d`](https://github.com/joshua-jingu-lee/ante/commit/860125db8232b49ffb959ea1f24fa161bd19f37a))

- #1853 IPC docs taxonomy + CLI runtime_ipc cross-ref drift guards
  ([#1890](https://github.com/joshua-jingu-lee/ante/pull/1890),
  [`4fc6a0b`](https://github.com/joshua-jingu-lee/ante/commit/4fc6a0b475ea8a3a0a99458005ed165eeb673a45))

- #1858 offline factory drift checks + CLI execution class 연동 검증 (closes #1818)
  ([#1893](https://github.com/joshua-jingu-lee/ante/pull/1893),
  [`24a24d2`](https://github.com/joshua-jingu-lee/ante/commit/24a24d29c01b3e6623e912973d738c118538b882))

- Cover explicit --config-dir PID resolution across CLI guards
  ([#1182](https://github.com/joshua-jingu-lee/ante/pull/1182),
  [`290bcff`](https://github.com/joshua-jingu-lee/ante/commit/290bcff5afbd8688b251a0cc3c1764cb2071fac8))

- Cover runtime resolver cwd-independence across system/IPC/cold-path
  ([#1182](https://github.com/joshua-jingu-lee/ante/pull/1182),
  [`290bcff`](https://github.com/joshua-jingu-lee/ante/commit/290bcff5afbd8688b251a0cc3c1764cb2071fac8))

- Guard local import path ([#1289](https://github.com/joshua-jingu-lee/ante/pull/1289),
  [`0654e38`](https://github.com/joshua-jingu-lee/ante/commit/0654e3851841a0aada3ca5e90c81b653985644ee))

- Lock cross-resolver db.path integration regression for #1158
  ([#1181](https://github.com/joshua-jingu-lee/ante/pull/1181),
  [`b5e60d7`](https://github.com/joshua-jingu-lee/ante/commit/b5e60d71e2ae2ffb893d657d759d1af9d0fee536))

- 라우트 인증 정적 검증 + PUBLIC_PATHS 회귀 테스트 (#1405)
  ([#1426](https://github.com/joshua-jingu-lee/ante/pull/1426),
  [`a597583`](https://github.com/joshua-jingu-lee/ante/commit/a59758308926ffa27d6f6d918e0e8929f34a938b))

- **#1841**: Add auth middleware code policy regression lock (Family C)
  ([#1862](https://github.com/joshua-jingu-lee/ante/pull/1862),
  [`862e37c`](https://github.com/joshua-jingu-lee/ante/commit/862e37cf63e62077fb42a8c2e44550eee7ff87a8))

- **#1841**: Add error taxonomy drift allowlist baseline YAML
  ([#1862](https://github.com/joshua-jingu-lee/ante/pull/1862),
  [`862e37c`](https://github.com/joshua-jingu-lee/ante/commit/862e37cf63e62077fb42a8c2e44550eee7ff87a8))

- **#1841**: Add error taxonomy drift guard (Family A + B + staleness)
  ([#1862](https://github.com/joshua-jingu-lee/ante/pull/1862),
  [`862e37c`](https://github.com/joshua-jingu-lee/ante/commit/862e37cf63e62077fb42a8c2e44550eee7ff87a8))

- **#1841**: Add load_drift_allowlist() helper + dataclasses
  ([#1862](https://github.com/joshua-jingu-lee/ante/pull/1862),
  [`862e37c`](https://github.com/joshua-jingu-lee/ante/commit/862e37cf63e62077fb42a8c2e44550eee7ff87a8))

- **#1847-1**: Member 12-leaf success output drift lock
  ([#1875](https://github.com/joshua-jingu-lee/ante/pull/1875),
  [`d728fc1`](https://github.com/joshua-jingu-lee/ante/commit/d728fc1d0f25c55a33f7e92b887433be1940108e))

- **account**: Split-2 bot/approval account-scoped test coverage
  ([#1246](https://github.com/joshua-jingu-lee/ante/pull/1246),
  [`45ae880`](https://github.com/joshua-jingu-lee/ante/commit/45ae880d92861fcc85c2801be4dcdec2387a7fa5))

- **account**: Treasury query 정책 회귀 테스트
  ([#1249](https://github.com/joshua-jingu-lee/ante/pull/1249),
  [`c7b6719`](https://github.com/joshua-jingu-lee/ante/commit/c7b67190ba0e4b09d8dd2ccc595bb5888e33cdab))

- **account,ipc**: Add runtime guard / init order / ipc code mapping tests
  ([#1169](https://github.com/joshua-jingu-lee/ante/pull/1169),
  [`90dc2b8`](https://github.com/joshua-jingu-lee/ante/commit/90dc2b8fdb4fd5888ee760e0e0bc305ee8e44a4b))

- **bot**: Cover nested BotInfo.config runtime controls
  ([#1501](https://github.com/joshua-jingu-lee/ante/pull/1501),
  [`64c7d45`](https://github.com/joshua-jingu-lee/ante/commit/64c7d451fe5bf399f961b739c6f5aff6092dc022))

- **cli**: #1913 r1 — success payload leak assertion + broker healthy 필드 보강
  ([#1932](https://github.com/joshua-jingu-lee/ante/pull/1932),
  [`f76d56d`](https://github.com/joshua-jingu-lee/ante/commit/f76d56d51fb14f80067c148c9182348a133e2b50))

- **cli**: #1913 r2 — broker status missing-key stdout exchange 부재 assertion 보강
  ([#1932](https://github.com/joshua-jingu-lee/ante/pull/1932),
  [`f76d56d`](https://github.com/joshua-jingu-lee/ante/commit/f76d56d51fb14f80067c148c9182348a133e2b50))

- **cli**: Add dependency-isolation smoke test infra (#1464)
  ([#1490](https://github.com/joshua-jingu-lee/ante/pull/1490),
  [`52cc460`](https://github.com/joshua-jingu-lee/ante/commit/52cc4601208d47fbab9ae368fbfc67b220e0c29b))

- **cli**: Clean up dead input_text helper params
  ([#1209](https://github.com/joshua-jingu-lee/ante/pull/1209),
  [`0849a5c`](https://github.com/joshua-jingu-lee/ante/commit/0849a5c32c1b19dabf374060744b623176dc3da4))

- **cli**: Cover BadArgumentUsage subclass in usage error json tests
  ([#1551](https://github.com/joshua-jingu-lee/ante/pull/1551),
  [`1543db9`](https://github.com/joshua-jingu-lee/ante/commit/1543db952c43d9526e59bf068213a98e06e9bfc2))

- **cli**: Cover require_auth and _wrap_callback_with_auth emit paths
  ([#1545](https://github.com/joshua-jingu-lee/ante/pull/1545),
  [`2e2874f`](https://github.com/joshua-jingu-lee/ante/commit/2e2874ffca855c940d5e1c4063608ef705e352eb))

- **cli**: Drop unused unpacked locals in strategy performance tests
  ([#1572](https://github.com/joshua-jingu-lee/ante/pull/1572),
  [`c690fde`](https://github.com/joshua-jingu-lee/ante/commit/c690fdee46d767e1ffba68c272f29d58970741e8))

- **cli**: Patch ipc_helpers.ipc_send so reconcile missing-account test stays offline
  ([#1566](https://github.com/joshua-jingu-lee/ante/pull/1566),
  [`3761a3f`](https://github.com/joshua-jingu-lee/ante/commit/3761a3fb39f86f1dbdca6ac176643b0a2a0f2082))

- **cli/ipc**: Align config-dir propagation expectations with runtime resolver
  ([#1182](https://github.com/joshua-jingu-lee/ante/pull/1182),
  [`290bcff`](https://github.com/joshua-jingu-lee/ante/commit/290bcff5afbd8688b251a0cc3c1764cb2071fac8))

- **cli/system**: Cover stop resolver path message and legacy stale cleanup
  ([#1182](https://github.com/joshua-jingu-lee/ante/pull/1182),
  [`290bcff`](https://github.com/joshua-jingu-lee/ante/commit/290bcff5afbd8688b251a0cc3c1764cb2071fac8))

- **contracts**: #1847 sub-PR 6 drift tests lock data + report JSON envelope shapes
  ([#1880](https://github.com/joshua-jingu-lee/ante/pull/1880),
  [`0172374`](https://github.com/joshua-jingu-lee/ante/commit/017237446ffdb546bba8725481d06f0a5052c244))

- **db**: Load schema generator by file path (#1229)
  ([#1255](https://github.com/joshua-jingu-lee/ante/pull/1255),
  [`21db431`](https://github.com/joshua-jingu-lee/ante/commit/21db4317bc7df926a719de993f8cfe3807f5010d))

- **eventbus**: Supply account_id when constructing OrderCancelFailedEvent
  ([#1342](https://github.com/joshua-jingu-lee/ante/pull/1342),
  [`71c6d93`](https://github.com/joshua-jingu-lee/ante/commit/71c6d9343eaf7ea58bb307d1e8db21ade1e9e13d))

- **exchange**: Cross-module canonical vocabulary contract regression
  ([#1589](https://github.com/joshua-jingu-lee/ante/pull/1589),
  [`e7acbc9`](https://github.com/joshua-jingu-lee/ante/commit/e7acbc9f7163d8fd99b3994c450461ce62291e9f))

- **exchange**: Cross-module canonical vocabulary contract regression (#1579)
  ([#1589](https://github.com/joshua-jingu-lee/ante/pull/1589),
  [`e7acbc9`](https://github.com/joshua-jingu-lee/ante/commit/e7acbc9f7163d8fd99b3994c450461ce62291e9f))

- **exchange**: Isolate CLI config-dir/db-path in contract regression
  ([#1589](https://github.com/joshua-jingu-lee/ante/pull/1589),
  [`e7acbc9`](https://github.com/joshua-jingu-lee/ante/commit/e7acbc9f7163d8fd99b3994c450461ce62291e9f))

- **rule,gateway,bot**: Cover OrderModifyEvent terminal event lifecycle
  ([#1341](https://github.com/joshua-jingu-lee/ante/pull/1341),
  [`fde7c2e`](https://github.com/joshua-jingu-lee/ante/commit/fde7c2ed4b6b8c91495dc6992dc9bdcdc29bf4b2))

- **stop**: Cover stop event account_id propagation and on_order_update routing
  ([#1349](https://github.com/joshua-jingu-lee/ante/pull/1349),
  [`58af809`](https://github.com/joshua-jingu-lee/ante/commit/58af809433e1586374dabeaec795cefb2813dae6))

- **strategy**: Add pandas-ta Python 3.13 regression gate
  ([#1201](https://github.com/joshua-jingu-lee/ante/pull/1201),
  [`5dd9a36`](https://github.com/joshua-jingu-lee/ante/commit/5dd9a36ca7032e9a92c59213d9f07dd624512595))

- **strategy**: Make pandas-ta filterwarnings pandas-version-neutral
  ([#1201](https://github.com/joshua-jingu-lee/ante/pull/1201),
  [`5dd9a36`](https://github.com/joshua-jingu-lee/ante/commit/5dd9a36ca7032e9a92c59213d9f07dd624512595))

- **treasury**: Cover balance API and service invariants
  ([#1343](https://github.com/joshua-jingu-lee/ante/pull/1343),
  [`db12f00`](https://github.com/joshua-jingu-lee/ante/commit/db12f0099c75df83a2ab53cbe7ebdb689f8137d0))

- **web**: Allow content-map ErrorResponse refs in 4xx/5xx invariant
  ([#1165](https://github.com/joshua-jingu-lee/ante/pull/1165),
  [`700a750`](https://github.com/joshua-jingu-lee/ante/commit/700a750c2a7dd0e7eb77038051c55c3f54900aff))

- **web**: Close discovery-lock fail-open gaps (default-deny default, per-(owner,path) dict proof,
  per-surface-id CV3, RuleUpdate sentinel)
  ([#1653](https://github.com/joshua-jingu-lee/ante/pull/1653),
  [`30b43a5`](https://github.com/joshua-jingu-lee/ante/commit/30b43a5cdba6e282e6fda6d839eeb8c1ae144b3a))

- **web**: Conform discovery-lock to refined INV-1/3/4 (per-site dict key, single fail-closed sink,
  per-path/non-collateral canary) ([#1653](https://github.com/joshua-jingu-lee/ante/pull/1653),
  [`30b43a5`](https://github.com/joshua-jingu-lee/ante/commit/30b43a5cdba6e282e6fda6d839eeb8c1ae144b3a))

- **web**: Enforce per-handler ValidationError chokepoint (#1651 attempt-7)
  ([#1653](https://github.com/joshua-jingu-lee/ante/pull/1653),
  [`30b43a5`](https://github.com/joshua-jingu-lee/ante/commit/30b43a5cdba6e282e6fda6d839eeb8c1ae144b3a))

- **web**: Helper caller-site preservation + AST-semantic ValidationError-handler gate
  ([#1653](https://github.com/joshua-jingu-lee/ante/pull/1653),
  [`30b43a5`](https://github.com/joshua-jingu-lee/ante/commit/30b43a5cdba6e282e6fda6d839eeb8c1ae144b3a))

- **web**: Non-extra_forbidden caller-controlled loc 종합 정책 — S1∪S2 default-deny discovery lock
  ([#1653](https://github.com/joshua-jingu-lee/ante/pull/1653),
  [`30b43a5`](https://github.com/joshua-jingu-lee/ante/commit/30b43a5cdba6e282e6fda6d839eeb8c1ae144b3a))

- **web**: Preserve enclosing-handler qualname in S1/S2 site-id (no over-merge)
  ([#1653](https://github.com/joshua-jingu-lee/ante/pull/1653),
  [`30b43a5`](https://github.com/joshua-jingu-lee/ante/commit/30b43a5cdba6e282e6fda6d839eeb8c1ae144b3a))

- **web**: Redesign discovery-lock PASS-computation to single default-deny form (INV-1..5)
  ([#1653](https://github.com/joshua-jingu-lee/ante/pull/1653),
  [`30b43a5`](https://github.com/joshua-jingu-lee/ante/commit/30b43a5cdba6e282e6fda6d839eeb8c1ae144b3a))

- **web**: S1 recursive routes/** discovery + S2 mount known-type fail-closed
  ([#1653](https://github.com/joshua-jingu-lee/ante/pull/1653),
  [`30b43a5`](https://github.com/joshua-jingu-lee/ante/commit/30b43a5cdba6e282e6fda6d839eeb8c1ae144b3a))

- **web**: Seal 3 attempt-9 fail-open vectors in non-extra loc discovery lock
  ([#1653](https://github.com/joshua-jingu-lee/ante/pull/1653),
  [`30b43a5`](https://github.com/joshua-jingu-lee/ante/commit/30b43a5cdba6e282e6fda6d839eeb8c1ae144b3a))

- **web**: Seal AnnAssign taint + BaseModel ctor-path S1 + real-resolver canary (#1651 attempt-8)
  ([#1653](https://github.com/joshua-jingu-lee/ante/pull/1653),
  [`30b43a5`](https://github.com/joshua-jingu-lee/ante/commit/30b43a5cdba6e282e6fda6d839eeb8c1ae144b3a))


## v0.9.0 (2026-04-25)

### BREAKING CHANGES

- **cli**: `ante member bootstrap` removed, `ante init` is now non-interactive
  (issue #1125). master 생성과 default 테스트 계좌 생성이 `ante init` 내부 단일
  흐름으로 통합되었으며, 플래그는 `--member-id` / `--name` / `--dir`만 받는다.
  대화형 프롬프트와 죽은 `--seed` 플래그는 제거되었다. 패스워드는 자동 생성되며
  토큰·Recovery Key와 함께 화면에 **1회만** 표시된다. 기존 설치는 디렉토리
  삭제 후 재실행하는 방식으로 마이그레이션한다. `MemberService.bootstrap_master()`
  서비스 API 자체는 변경 없음.

> 자세한 변경 사항은 [GitHub Release v0.9.0](https://github.com/joshua-jingu-lee/ante/releases/tag/v0.9.0) 노트를 참조.

## v0.8.1 (2026-03-29)

### Bug Fixes

- POST /api/reports 500 에러 수정 (#1065) ([#1069](https://github.com/joshua-jingu-lee/ante/pull/1069),
  [`d60e826`](https://github.com/joshua-jingu-lee/ante/commit/d60e82663d6a3fcb5f7ffffed79caedbb5f37c47))

- Rule info 미존재 시 종료 코드 1 반환에 맞춰 유닛 테스트 수정
  ([#1056](https://github.com/joshua-jingu-lee/ante/pull/1056),
  [`f5decef`](https://github.com/joshua-jingu-lee/ante/commit/f5decef32aae42168e4332b847557815ff0b65ed))

- **api**: GET /api/members 에러 핸들링 및 로깅 추가 (#1084)
  ([#1087](https://github.com/joshua-jingu-lee/ante/pull/1087),
  [`b6c979d`](https://github.com/joshua-jingu-lee/ante/commit/b6c979d6b709446fbe78b8e9bfee3c34ce873409))

- **approval**: Strategy_adopt 결재 생성 시 params 검증 추가
  ([#1083](https://github.com/joshua-jingu-lee/ante/pull/1083),
  [`1a259ab`](https://github.com/joshua-jingu-lee/ante/commit/1a259ab90e00936ddc5ef0928cb2d5f2d05a2a68))

- **cli**: Approval 서브커맨드에 @format_option 데코레이터 추가
  ([#1080](https://github.com/joshua-jingu-lee/ante/pull/1080),
  [`d5364f7`](https://github.com/joshua-jingu-lee/ante/commit/d5364f73f29f6c07a7bc16ec9e56df6ef19d14d9))

- **cli**: Backtest run 시작일 > 종료일 입력 검증 추가 (#1066)
  ([#1068](https://github.com/joshua-jingu-lee/ante/pull/1068),
  [`ef5f17b`](https://github.com/joshua-jingu-lee/ante/commit/ef5f17ba72d4d69f21d8ddc8211b4a99ec433bee))

- **tc**: Approval/workflow.feature pending 결재 자체 시딩으로 SKIP 해소
  ([#1077](https://github.com/joshua-jingu-lee/ante/pull/1077),
  [`652ee9a`](https://github.com/joshua-jingu-lee/ante/commit/652ee9a761885e3e8fc5829dbc2b1100d48d6516))

- **tc**: Background 계좌 DELETE 제거 및 전략 필터 Step 변경
  ([#1081](https://github.com/joshua-jingu-lee/ante/pull/1081),
  [`7c8a282`](https://github.com/joshua-jingu-lee/ante/commit/7c8a2820ec8d98eea1e9f399c9f4fda5f68eb33b))

- **tc**: Background에 잔존 데이터 정리 Step 추가하여 반복 실행 안정성 확보
  ([#1075](https://github.com/joshua-jingu-lee/ante/pull/1075),
  [`49bc94c`](https://github.com/joshua-jingu-lee/ante/commit/49bc94c36f26fed091effbfc5e92d5ad702816cd))

- **tc**: Bot/crud.feature 미구현 엔드포인트 참조 수정
  ([#1088](https://github.com/joshua-jingu-lee/ante/pull/1088),
  [`554f038`](https://github.com/joshua-jingu-lee/ante/commit/554f0387d9e7b9946a6313ddd5009c3264d57ed1))

- **tc**: CLI --format json 옵션 위치 수정 및 기대값 불일치 해소 (#1064)
  ([#1067](https://github.com/joshua-jingu-lee/ante/pull/1067),
  [`5c83775`](https://github.com/joshua-jingu-lee/ante/commit/5c837753a253737a58d680f106f1d2ac15eb0208))

- **tc**: QA 기대값 불일치 4건 수정 (#1070) ([#1071](https://github.com/joshua-jingu-lee/ante/pull/1071),
  [`f622546`](https://github.com/joshua-jingu-lee/ante/commit/f622546388e6e50fed309f3c293589f156234cf2))

- **tc**: Rule/query.feature QA 환경 기본 룰 미시딩으로 3건 FAIL (#1086)
  ([#1089](https://github.com/joshua-jingu-lee/ante/pull/1089),
  [`ada94fd`](https://github.com/joshua-jingu-lee/ante/commit/ada94fd4e187c55bccd8c4f1d6793de6095a9075))

- **tc**: TC 스펙/구현체 불일치 4건 수정 + 개선 2건 ([#1053](https://github.com/joshua-jingu-lee/ante/pull/1053),
  [`2dab1da`](https://github.com/joshua-jingu-lee/ante/commit/2dab1da00a6471d569208520872ff091c33ab856))

- **tc**: 전략 조회 TC에 전략 이름을 명시적으로 지정 ([#1076](https://github.com/joshua-jingu-lee/ante/pull/1076),
  [`72397bb`](https://github.com/joshua-jingu-lee/ante/commit/72397bbb4386aebb6c1ed4d214a0b8a4b04c7b5f))

### Testing

- 리스크 룰 조회 TC 추가 (#1043) ([#1056](https://github.com/joshua-jingu-lee/ante/pull/1056),
  [`f5decef`](https://github.com/joshua-jingu-lee/ante/commit/f5decef32aae42168e4332b847557815ff0b65ed))

- 리스크 룰 조회 TC 추가 (rule/query.feature) #1043
  ([#1056](https://github.com/joshua-jingu-lee/ante/pull/1056),
  [`f5decef`](https://github.com/joshua-jingu-lee/ante/commit/f5decef32aae42168e4332b847557815ff0b65ed))

- **approval**: 결재 워크플로우 승인/거부 TC 추가 (#1042)
  ([#1055](https://github.com/joshua-jingu-lee/ante/pull/1055),
  [`91921b4`](https://github.com/joshua-jingu-lee/ante/commit/91921b46c0eac5089fa82d4c17f95e4e0be4b72d))

- **audit**: 감사 로그 조회 및 필터링 TC 추가 (#1046)
  ([#1057](https://github.com/joshua-jingu-lee/ante/pull/1057),
  [`fc9ca46`](https://github.com/joshua-jingu-lee/ante/commit/fc9ca462e5f29c2c549bab0a0d44dafe298df795))

- **backtest**: 백테스트 실행 및 성과 검증 TC 추가 (#1044)
  ([#1058](https://github.com/joshua-jingu-lee/ante/pull/1058),
  [`8074e2d`](https://github.com/joshua-jingu-lee/ante/commit/8074e2d7d3aa82c4622c67a38a6baf65b3ac7dd8))

- **data**: 데이터 피드 및 저장 관리 TC 추가 (feed.feature)
  ([#1061](https://github.com/joshua-jingu-lee/ante/pull/1061),
  [`0a9f183`](https://github.com/joshua-jingu-lee/ante/commit/0a9f183650d3394d23392d71752b138420d69fb5))

- **report**: 리포트 제출 및 조회 TC 추가 (#1045)
  ([#1059](https://github.com/joshua-jingu-lee/ante/pull/1059),
  [`d34adc1`](https://github.com/joshua-jingu-lee/ante/commit/d34adc199aeae7e21e43877f7cbe8bd70d371c07))

- **report**: 성과 집계 조회 TC 추가 (#1048) ([#1060](https://github.com/joshua-jingu-lee/ante/pull/1060),
  [`703d1fd`](https://github.com/joshua-jingu-lee/ante/commit/703d1fd56f405324135bb03b6ded38937b51865d))

- **scenario**: E2E 전체 사이클 TC 추가 (#1050)
  ([#1063](https://github.com/joshua-jingu-lee/ante/pull/1063),
  [`c0f2e4b`](https://github.com/joshua-jingu-lee/ante/commit/c0f2e4b0adcbeb5f13645d21ae37e05f2365868a))

- **trade**: 거래 실행 및 포지션 반영 TC 추가 (#1041)
  ([#1054](https://github.com/joshua-jingu-lee/ante/pull/1054),
  [`b362897`](https://github.com/joshua-jingu-lee/ante/commit/b362897bec06fb5276730fb858f9714d963ce977))

- **trade,config**: Trade/query, config/dynamic TC 시나리오 확장
  ([#1062](https://github.com/joshua-jingu-lee/ante/pull/1062),
  [`5c82e6a`](https://github.com/joshua-jingu-lee/ante/commit/5c82e6a5192dd61d154735208018f967a6527445))


## v0.8.0 (2026-03-25)

### Bug Fixes

- Commission_rate 테스트를 Config 시드 등록(#965) 현행에 맞게 갱신
  ([#978](https://github.com/joshua-jingu-lee/ante/pull/978),
  [`f02f666`](https://github.com/joshua-jingu-lee/ante/commit/f02f6667bb6169ee49bd6c77c3370cae81be0e91))

- DataProvider.get_ohlcv() 반환 타입을 pl.DataFrame으로 통일 Refs #970
  ([#980](https://github.com/joshua-jingu-lee/ante/pull/980),
  [`6a59db5`](https://github.com/joshua-jingu-lee/ante/commit/6a59db5ea4add15d899ee4dde7f0efc61339fb63))

- Dataset 목록 API 테스트를 row_count=0 반환 현행에 맞게 갱신
  ([#978](https://github.com/joshua-jingu-lee/ante/pull/978),
  [`f02f666`](https://github.com/joshua-jingu-lee/ante/commit/f02f6667bb6169ee49bd6c77c3370cae81be0e91))

- Strategy_adopt/retire 결재 실행기 ReportStatus enum 전달 Refs #974
  ([#978](https://github.com/joshua-jingu-lee/ante/pull/978),
  [`f02f666`](https://github.com/joshua-jingu-lee/ante/commit/f02f6667bb6169ee49bd6c77c3370cae81be0e91))

- Strategy_adopt/retire 결재 실행기에 ReportStatus enum 전달
  ([#978](https://github.com/joshua-jingu-lee/ante/pull/978),
  [`f02f666`](https://github.com/joshua-jingu-lee/ante/commit/f02f6667bb6169ee49bd6c77c3370cae81be0e91))

- 봇 생성 API 필드 불일치 해소 — strategy_name/account_id/budget 지원
  ([#979](https://github.com/joshua-jingu-lee/ante/pull/979),
  [`dc1e8d6`](https://github.com/joshua-jingu-lee/ante/commit/dc1e8d6de86aa0b5a98077cad1b21edad879c989))

- **account**: Is_paper를 Account.broker_config으로 이관 Refs #989
  ([#992](https://github.com/joshua-jingu-lee/ante/pull/992),
  [`ab318e2`](https://github.com/joshua-jingu-lee/ante/commit/ab318e2dcd7773bb40f4bce3185b447c3005d594))

- **api**: Approvals/members 목록 total을 전체 건수로 수정
  ([#962](https://github.com/joshua-jingu-lee/ante/pull/962),
  [`be497cf`](https://github.com/joshua-jingu-lee/ante/commit/be497cfc883e8c477306905aaa334a09e4f94230))

- **api**: Datasets 목록 data_type 기본값을 None으로 변경하여 전체 타입 반환
  ([#964](https://github.com/joshua-jingu-lee/ante/pull/964),
  [`d340df7`](https://github.com/joshua-jingu-lee/ante/commit/d340df7f3de787310145f3fdc5d5c5ed6cf60766))

- **api**: 리포트 상세 응답에 config/datasets 필드 추가
  ([#976](https://github.com/joshua-jingu-lee/ante/pull/976),
  [`450368b`](https://github.com/joshua-jingu-lee/ante/commit/450368bca38c370410553965aaeff98088889706))

- **api**: 리포트 상세 응답에 config/datasets 필드 추가 Refs #971
  ([#976](https://github.com/joshua-jingu-lee/ante/pull/976),
  [`450368b`](https://github.com/joshua-jingu-lee/ante/commit/450368bca38c370410553965aaeff98088889706))

- **approval**: CLI에서 ApprovalService.list → list_approvals 호출 누락 수정
  ([#1020](https://github.com/joshua-jingu-lee/ante/pull/1020),
  [`f510e6b`](https://github.com/joshua-jingu-lee/ante/commit/f510e6b2889a17339e42aea1798063c73ceb84ec))

- **approval**: ExecutionContent 컴포넌트 삭제 Refs #1010
  ([#1040](https://github.com/joshua-jingu-lee/ante/pull/1040),
  [`e47f3b9`](https://github.com/joshua-jingu-lee/ante/commit/e47f3b9a1e0222f4f829b59b38379a50ac0e72a2))

- **approval**: 결재 승인 시 StrategyRegistry 상태도 함께 전환 Refs #1001
  ([#1040](https://github.com/joshua-jingu-lee/ante/pull/1040),
  [`e47f3b9`](https://github.com/joshua-jingu-lee/ante/commit/e47f3b9a1e0222f4f829b59b38379a50ac0e72a2))

- **backtest**: Get_indicator() stub을 실제 지표 계산으로 교체 Refs #969
  ([#977](https://github.com/joshua-jingu-lee/ante/pull/977),
  [`6368596`](https://github.com/joshua-jingu-lee/ante/commit/6368596e61eeb7f6c261ed554b21f68060c294be))

- **bot**: 봇 생성 모달 전략 셀렉트를 ADOPTED 상태만 필터링 (#1006)
  ([#1040](https://github.com/joshua-jingu-lee/ante/pull/1040),
  [`e47f3b9`](https://github.com/joshua-jingu-lee/ante/commit/e47f3b9a1e0222f4f829b59b38379a50ac0e72a2))

- **broker**: KIS WebSocket approval_key REST URL 유추 로직 반전 수정 Refs #988
  ([`37dcac7`](https://github.com/joshua-jingu-lee/ante/commit/37dcac7bbd21a12013c1e5e7439400cb136ce25b))

- **broker**: KIS WebSocket 모의/실전 포트 번호 반전 수정
  ([#943](https://github.com/joshua-jingu-lee/ante/pull/943),
  [`e8ddc24`](https://github.com/joshua-jingu-lee/ante/commit/e8ddc2405a582f512a80524d55878f80dfc1039d))

- **ci**: Mypy union-attr 오류 및 v004 마이그레이션 테스트 실패 수정
  ([#1040](https://github.com/joshua-jingu-lee/ante/pull/1040),
  [`e47f3b9`](https://github.com/joshua-jingu-lee/ante/commit/e47f3b9a1e0222f4f829b59b38379a50ac0e72a2))

- **ci**: Publish.yml에서 static 디렉토리 생성 추가
  ([`ca5f406`](https://github.com/joshua-jingu-lee/ante/commit/ca5f40653e7f2d7cfd1064ef2a60f79a92e72218))

- **ci**: Test job timeout을 10분에서 15분으로 증가
  ([#1009](https://github.com/joshua-jingu-lee/ante/pull/1009),
  [`8f17014`](https://github.com/joshua-jingu-lee/ante/commit/8f17014f9880ff5b5a0a8986accde212f9f48fdb))

- **cli**: Broker reconcile 오프라인 폴백에서 불필요한 의존성 제거
  ([#947](https://github.com/joshua-jingu-lee/ante/pull/947),
  [`281e65c`](https://github.com/joshua-jingu-lee/ante/commit/281e65c378518a5ea89a0d1d4ab6a12ba656cf93))

- **cli**: Strategy info에서 rationale/risks 키 누락으로 인한 KeyError 수정
  ([#1009](https://github.com/joshua-jingu-lee/ante/pull/1009),
  [`8f17014`](https://github.com/joshua-jingu-lee/ante/commit/8f17014f9880ff5b5a0a8986accde212f9f48fdb))

- **cli**: 잔여 mypy 오류 15건 해소 및 overrides 전체 삭제 (#1031)
  ([#1032](https://github.com/joshua-jingu-lee/ante/pull/1032),
  [`41ae2c1`](https://github.com/joshua-jingu-lee/ante/commit/41ae2c1c5fef61b17c3512c140b5651ff634c4a2))

- **data**: DART 체크포인트 키 형식 수정 및 순서 비교 오류 해결
  ([#945](https://github.com/joshua-jingu-lee/ante/pull/945),
  [`1de7442`](https://github.com/joshua-jingu-lee/ante/commit/1de74422622601f7dc43cc9ad174ee4705dc4af5))

- **db**: V003 마이그레이션에서 accounts 테이블 존재 여부 확인
  ([`3f7ecb7`](https://github.com/joshua-jingu-lee/ante/commit/3f7ecb78d0c668926ee20ab352e6da484d33a7a5))

- **frontend**: 데이터셋 목록에서 file_size/row_count 의존 제거
  ([#952](https://github.com/joshua-jingu-lee/ante/pull/952),
  [`dd80412`](https://github.com/joshua-jingu-lee/ante/commit/dd80412db1ec48935609c14010f359a52a741a9b))

- **member**: Agent 기본 scope에서 비표준 approval:create/review를 표준 scope로 수정
  ([#998](https://github.com/joshua-jingu-lee/ante/pull/998),
  [`9015837`](https://github.com/joshua-jingu-lee/ante/commit/90158370f1027794a63a84fe53872271c5d8a8ca))

- **notification**: Telegram_enabled 초기값 전달 및 chat_id 파싱 안전 처리
  ([#1009](https://github.com/joshua-jingu-lee/ante/pull/1009),
  [`8f17014`](https://github.com/joshua-jingu-lee/ante/commit/8f17014f9880ff5b5a0a8986accde212f9f48fdb))

- **notification**: 텔레그램 명령 수신 설정을 dynamic_config로 통합 Refs #997
  ([#1009](https://github.com/joshua-jingu-lee/ante/pull/1009),
  [`8f17014`](https://github.com/joshua-jingu-lee/ante/commit/8f17014f9880ff5b5a0a8986accde212f9f48fdb))

- **notification**: 텔레그램 명령 수신 설정을 dynamic_config로 통합 및 allowed_user_ids 제거
  ([#1009](https://github.com/joshua-jingu-lee/ante/pull/1009),
  [`8f17014`](https://github.com/joshua-jingu-lee/ante/commit/8f17014f9880ff5b5a0a8986accde212f9f48fdb))

- **scripts**: 앵커 링크 버그 수정 및 미사용 테이블 항목 제거 Refs #987
  ([#991](https://github.com/joshua-jingu-lee/ante/pull/991),
  [`f8bec96`](https://github.com/joshua-jingu-lee/ante/commit/f8bec9662447d4874427d748d53f3a4e16803112))

- **strategy**: 전략 상세 페이지 rationale·risks·params 미노출 수정
  ([#995](https://github.com/joshua-jingu-lee/ante/pull/995),
  [`788a1b8`](https://github.com/joshua-jingu-lee/ante/commit/788a1b862ca906251f79b2fd4bd228d45d3e3d07))

- **test**: CI 기존 테스트 실패 2건 수정 ([#976](https://github.com/joshua-jingu-lee/ante/pull/976),
  [`450368b`](https://github.com/joshua-jingu-lee/ante/commit/450368bca38c370410553965aaeff98088889706))

- **test**: Commission defaults 테스트를 #965 시드 등록에 맞게 수정
  ([#976](https://github.com/joshua-jingu-lee/ante/pull/976),
  [`450368b`](https://github.com/joshua-jingu-lee/ante/commit/450368bca38c370410553965aaeff98088889706))

- **test**: Config 시드 등록·목록 API 최적화에 맞게 테스트 3건 수정
  ([`52fe3e5`](https://github.com/joshua-jingu-lee/ante/commit/52fe3e59d4e6847e34a6fbca5d5e35f7ab410460))

- **test**: StrategyRecord author → author_name/author_id 변경 반영
  ([#985](https://github.com/joshua-jingu-lee/ante/pull/985),
  [`296853d`](https://github.com/joshua-jingu-lee/ante/commit/296853d9af346cabb037c2d3e815f4495f0f81d8))

- **test**: Test_init_account에 Config 주입 누락 수정
  ([#1020](https://github.com/joshua-jingu-lee/ante/pull/1020),
  [`f510e6b`](https://github.com/joshua-jingu-lee/ante/commit/f510e6b2889a17339e42aea1798063c73ceb84ec))

- **treasury**: Is_virtual 판정을 Account.trading_mode 기반으로 변경
  ([#993](https://github.com/joshua-jingu-lee/ante/pull/993),
  [`7b158b1`](https://github.com/joshua-jingu-lee/ante/commit/7b158b1cafb0893b100c15faccef50b9bcd8126d))

- **treasury**: Replace private _get_writer() with public fetch_one() in release_budget
  ([#984](https://github.com/joshua-jingu-lee/ante/pull/984),
  [`a658468`](https://github.com/joshua-jingu-lee/ante/commit/a658468d97d372974b019558d30ad6235e26546b))

- **treasury**: 봇 삭제 시 인메모리에 없는 budget도 DB fallback으로 환수 Refs #982
  ([#984](https://github.com/joshua-jingu-lee/ante/pull/984),
  [`a658468`](https://github.com/joshua-jingu-lee/ante/commit/a658468d97d372974b019558d30ad6235e26546b))

- **treasury**: 봇 삭제 시 할당 예산 DB fallback 환수 Refs #982
  ([#984](https://github.com/joshua-jingu-lee/ante/pull/984),
  [`a658468`](https://github.com/joshua-jingu-lee/ante/commit/a658468d97d372974b019558d30ad6235e26546b))

- **typing**: Cli/main.py mypy has-type 오류 18건 inline ignore 처리
  ([#1020](https://github.com/joshua-jingu-lee/ante/pull/1020),
  [`f510e6b`](https://github.com/joshua-jingu-lee/ante/commit/f510e6b2889a17339e42aea1798063c73ceb84ec))

- **typing**: Mypy ignore 목록 단순 오류 14건 해소 Refs #1012
  ([#1020](https://github.com/joshua-jingu-lee/ante/pull/1020),
  [`f510e6b`](https://github.com/joshua-jingu-lee/ante/commit/f510e6b2889a17339e42aea1798063c73ceb84ec))

- **typing**: Mypy ignore 목록 중간 난이도 오류 27건 해소
  ([#1020](https://github.com/joshua-jingu-lee/ante/pull/1020),
  [`f510e6b`](https://github.com/joshua-jingu-lee/ante/commit/f510e6b2889a17339e42aea1798063c73ceb84ec))

- **typing**: Mypy ignore 목록 중복·타입 오류 27건 해소 Refs #1013
  ([#1020](https://github.com/joshua-jingu-lee/ante/pull/1020),
  [`f510e6b`](https://github.com/joshua-jingu-lee/ante/commit/f510e6b2889a17339e42aea1798063c73ceb84ec))

- **web**: BotStrategy 타입 author → author_name/author_id 누락 수정 Refs #983
  ([`2a78af8`](https://github.com/joshua-jingu-lee/ante/commit/2a78af8a3d7213538be01ddbdd340deb7dd578a3))

- **web**: 브라우저 탭 타이틀·파비콘 변경 Refs #963 ([#967](https://github.com/joshua-jingu-lee/ante/pull/967),
  [`b1b327e`](https://github.com/joshua-jingu-lee/ante/commit/b1b327ee78c7880b7fd20131c3bb8043d91be0c7))

- **web**: 사이드바 UI 버그 3건 수정 Refs #957 ([#966](https://github.com/joshua-jingu-lee/ante/pull/966),
  [`272055b`](https://github.com/joshua-jingu-lee/ante/commit/272055bc98178b548875bc80c9d00e832005451c))

- **web**: 전략 상세 페이지 파라미터 미표시 및 빈 값 렌더링 수정 Refs #972
  ([#975](https://github.com/joshua-jingu-lee/ante/pull/975),
  [`dbb4894`](https://github.com/joshua-jingu-lee/ante/commit/dbb489407e91ebac07157441c22e6eefd699aa21))

### Chores

- Config/system.toml을 .gitignore에 추가하고 추적 제거
  ([`303f8d1`](https://github.com/joshua-jingu-lee/ante/commit/303f8d153172725544ed581b0e49588a792bf3e6))

- Trigger CI ([#978](https://github.com/joshua-jingu-lee/ante/pull/978),
  [`f02f666`](https://github.com/joshua-jingu-lee/ante/commit/f02f6667bb6169ee49bd6c77c3370cae81be0e91))

### Continuous Integration

- CI 파이프라인 개선 — 병렬화, 품질 게이트, 중복 실행 방지
  ([`baf6d71`](https://github.com/joshua-jingu-lee/ante/commit/baf6d7195bbbf92e68e5905f7ffe1e265788bff8))

- Test job timeout을 20분으로 증가 ([#1009](https://github.com/joshua-jingu-lee/ante/pull/1009),
  [`8f17014`](https://github.com/joshua-jingu-lee/ante/commit/8f17014f9880ff5b5a0a8986accde212f9f48fdb))

- Test job timeout을 30분으로 증가 ([#1009](https://github.com/joshua-jingu-lee/ante/pull/1009),
  [`8f17014`](https://github.com/joshua-jingu-lee/ante/commit/8f17014f9880ff5b5a0a8986accde212f9f48fdb))

- Test timeout 45분, pytest 출력 최소화로 CI 속도 개선
  ([#1009](https://github.com/joshua-jingu-lee/ante/pull/1009),
  [`8f17014`](https://github.com/joshua-jingu-lee/ante/commit/8f17014f9880ff5b5a0a8986accde212f9f48fdb))

- Trigger CI re-run ([#978](https://github.com/joshua-jingu-lee/ante/pull/978),
  [`f02f666`](https://github.com/joshua-jingu-lee/ante/commit/f02f6667bb6169ee49bd6c77c3370cae81be0e91))

### Documentation

- README에 Mermaid 아키텍처 다이어그램 추가
  ([`9899f68`](https://github.com/joshua-jingu-lee/ante/commit/9899f684249a50dac760c1921025996a006e1d7b))

- **guide**: README·getting-started·security 가이드 톤 통일 및 내용 보강
  ([`93e3705`](https://github.com/joshua-jingu-lee/ante/commit/93e37053ad992918f4a9e74b2988c11482709b21))

- **readme**: Mermaid 다이어그램을 SVG 이미지로 교체
  ([`3da6d8e`](https://github.com/joshua-jingu-lee/ante/commit/3da6d8e714b69ba5aecac323a7016add068ab9bf))

- **readme**: README 개선 및 How it works SVG 다이어그램 추가
  ([`9260b3c`](https://github.com/joshua-jingu-lee/ante/commit/9260b3c1c52f242974da0e90cc87ad47438476b7))

- **readme**: 역할별 섹션 보강 및 문서 링크 가이드로 전환
  ([`5cc09dc`](https://github.com/joshua-jingu-lee/ante/commit/5cc09dcd4317d1dad37b6e43cbf9f9e73fb096d8))

### Features

- **cli**: CLI 레퍼런스 문서에 필요 scope·토큰 타입 자동 표시 Refs #981
  ([#986](https://github.com/joshua-jingu-lee/ante/pull/986),
  [`07dc04d`](https://github.com/joshua-jingu-lee/ante/commit/07dc04da94a92e74f2ac6c83c08554f13a0e0d91))

- **config**: 트레이딩/리스크/알림 기본값을 Config 서비스에 시드 등록 Refs #965
  ([#968](https://github.com/joshua-jingu-lee/ante/pull/968),
  [`731bd0e`](https://github.com/joshua-jingu-lee/ante/commit/731bd0e12f41644b68d8f50a8b57dc7f77214803))

- **scripts**: Db-schema.md 자동 생성 스크립트 구현 Refs #987
  ([#991](https://github.com/joshua-jingu-lee/ante/pull/991),
  [`f8bec96`](https://github.com/joshua-jingu-lee/ante/commit/f8bec9662447d4874427d748d53f3a4e16803112))

- **strategy**: 전략 상태 변경 API 및 목록 필터 검증 구현 Refs #1003
  ([#1040](https://github.com/joshua-jingu-lee/ante/pull/1040),
  [`e47f3b9`](https://github.com/joshua-jingu-lee/ante/commit/e47f3b9a1e0222f4f829b59b38379a50ac0e72a2))

- **strategy**: 전략 채택/폐기 executor에 NotificationEvent 발행 추가 Refs #1004
  ([#1040](https://github.com/joshua-jingu-lee/ante/pull/1040),
  [`e47f3b9`](https://github.com/joshua-jingu-lee/ante/commit/e47f3b9a1e0222f4f829b59b38379a50ac0e72a2))

### Performance Improvements

- **api**: Cursor 페이지네이션 순회 최적화 ([#962](https://github.com/joshua-jingu-lee/ante/pull/962),
  [`be497cf`](https://github.com/joshua-jingu-lee/ante/commit/be497cfc883e8c477306905aaa334a09e4f94230))

- **api**: Datasets 목록 API 이벤트 루프 블로킹 해소 ([#956](https://github.com/joshua-jingu-lee/ante/pull/956),
  [`c71c0bd`](https://github.com/joshua-jingu-lee/ante/commit/c71c0bd9f137e8ba34947cb4ecb867f02b269c40))

- **api**: Strategies 목록 N+1 조회를 asyncio.gather 병렬화 Refs #951
  ([#962](https://github.com/joshua-jingu-lee/ante/pull/962),
  [`be497cf`](https://github.com/joshua-jingu-lee/ante/commit/be497cfc883e8c477306905aaa334a09e4f94230))

### Refactoring

- **api**: 전략 상세 봇 탐색 중복 코드를 헬퍼 함수로 통합 ([#962](https://github.com/joshua-jingu-lee/ante/pull/962),
  [`be497cf`](https://github.com/joshua-jingu-lee/ante/commit/be497cfc883e8c477306905aaa334a09e4f94230))

- **strategy**: StrategyMeta author -> author_name/author_id 분리 Refs #983
  ([#985](https://github.com/joshua-jingu-lee/ante/pull/985),
  [`296853d`](https://github.com/joshua-jingu-lee/ante/commit/296853d9af346cabb037c2d3e815f4495f0f81d8))

- **strategy**: StrategyMeta author 필드를 author_name/author_id 2필드로 분리 Refs #983
  ([#985](https://github.com/joshua-jingu-lee/ante/pull/985),
  [`296853d`](https://github.com/joshua-jingu-lee/ante/commit/296853d9af346cabb037c2d3e815f4495f0f81d8))

- **strategy**: StrategyStatus 3단계 간소화 (REGISTERED/ADOPTED/ARCHIVED) Refs #1000
  ([#1040](https://github.com/joshua-jingu-lee/ante/pull/1040),
  [`e47f3b9`](https://github.com/joshua-jingu-lee/ante/commit/e47f3b9a1e0222f4f829b59b38379a50ac0e72a2))

- **types**: Main.py Optional 필드 33건 assert 가드로 해소
  ([#1020](https://github.com/joshua-jingu-lee/ante/pull/1020),
  [`f510e6b`](https://github.com/joshua-jingu-lee/ante/commit/f510e6b2889a17339e42aea1798063c73ceb84ec))


## v0.7.0 (2026-03-24)

### Bug Fixes

- Dockerfile.test 프론트 빌드 및 DynamicConfig default=None 처리 수정
  ([`28f134b`](https://github.com/joshua-jingu-lee/ante/commit/28f134b0ed4fd3bf0f7e703e3834df5c7d0f092c))

- QA 전수 검사에서 발견된 버그 4건 수정
  ([`b3cd466`](https://github.com/joshua-jingu-lee/ante/commit/b3cd466f9828ca5c7ef51ac8182913280ef11678))

- 에픽 통합 시 DDL 누락 컬럼 반영 및 테스트 호환성 수정 ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- 인증정보 없는 계좌의 봇 시작 시 422 에러 반환 (#670) ([#676](https://github.com/joshua-jingu-lee/ante/pull/676),
  [`d121eb8`](https://github.com/joshua-jingu-lee/ante/commit/d121eb86a3dbef86f64462150815d45b6bf2db4b))

- **account**: Create()에서 account_id 형식 검증 추가
  ([#789](https://github.com/joshua-jingu-lee/ante/pull/789),
  [`2379f56`](https://github.com/joshua-jingu-lee/ante/commit/2379f567b10e8aeb3640eaa6ff25e718097ccd9d))

- **account**: Create()에서 required_credentials 검증 추가
  ([#803](https://github.com/joshua-jingu-lee/ante/pull/803),
  [`67e228c`](https://github.com/joshua-jingu-lee/ante/commit/67e228c4a08b0bb6d3f3e3f90525eedf0e987904))

- **account**: Create()에서 required_credentials 검증 추가 #775
  ([#803](https://github.com/joshua-jingu-lee/ante/pull/803),
  [`67e228c`](https://github.com/joshua-jingu-lee/ante/commit/67e228c4a08b0bb6d3f3e3f90525eedf0e987904))

- **account**: Credentials Fernet 암호화 적용 #721
  ([#740](https://github.com/joshua-jingu-lee/ante/pull/740),
  [`8a89127`](https://github.com/joshua-jingu-lee/ante/commit/8a891273311f7ee7de0ca7fe5896142090d8f049))

- **account**: Credentials Fernet 암호화 적용 — 평문 DB 저장 제거
  ([#740](https://github.com/joshua-jingu-lee/ante/pull/740),
  [`8a89127`](https://github.com/joshua-jingu-lee/ante/commit/8a891273311f7ee7de0ca7fe5896142090d8f049))

- **account**: Delete()에서 이벤트 발행 및 CLI IPC 전환
  ([#720](https://github.com/joshua-jingu-lee/ante/pull/720),
  [`dd45dc1`](https://github.com/joshua-jingu-lee/ante/commit/dd45dc128214aeabbf1bb3ca2164639c54e1acbc))

- **account**: Delete()에서 이벤트 발행 및 CLI IPC 전환 #717
  ([#720](https://github.com/joshua-jingu-lee/ante/pull/720),
  [`dd45dc1`](https://github.com/joshua-jingu-lee/ante/commit/dd45dc128214aeabbf1bb3ca2164639c54e1acbc))

- **account**: DELETED 계좌 suspend/delete 상태 전이 가드 추가 #718
  ([#725](https://github.com/joshua-jingu-lee/ante/pull/725),
  [`9309429`](https://github.com/joshua-jingu-lee/ante/commit/9309429cddb91dd42bd4713849d8b07ef72f212d))

- **account**: DELETED 계좌에 suspend/delete 상태 전이 가드 추가
  ([#725](https://github.com/joshua-jingu-lee/ante/pull/725),
  [`9309429`](https://github.com/joshua-jingu-lee/ante/commit/9309429cddb91dd42bd4713849d8b07ef72f212d))

- **account**: Kis-overseas 프리셋 제거 — 미구현 브로커 타입 생성 차단 #770
  ([#780](https://github.com/joshua-jingu-lee/ante/pull/780),
  [`f5c58c7`](https://github.com/joshua-jingu-lee/ante/commit/f5c58c7d0f4fdb693cc322f4702b38f2e67123cc))

- **account**: MissingCredentialsError를 422로 매핑 Refs #848
  ([#850](https://github.com/joshua-jingu-lee/ante/pull/850),
  [`93a26af`](https://github.com/joshua-jingu-lee/ante/commit/93a26afde7d58e8db9791cbaa3c27d547b5bcd8c))

- **account**: Soft-delete된 계좌 ID 충돌 시 409 반환
  ([#680](https://github.com/joshua-jingu-lee/ante/pull/680),
  [`e0efb2c`](https://github.com/joshua-jingu-lee/ante/commit/e0efb2c5262f952cfb1d19adc755c6ccc2d2cf28))

- **account**: Test 브로커 required_credentials 추가
  ([#656](https://github.com/joshua-jingu-lee/ante/pull/656),
  [`2d7da9a`](https://github.com/joshua-jingu-lee/ante/commit/2d7da9a2e0527f96a221f21e200343712e967d8d))

- **account**: Update()에서 미인식 필드 전달 시 ValueError 발생 (#748)
  ([#756](https://github.com/joshua-jingu-lee/ante/pull/756),
  [`193762c`](https://github.com/joshua-jingu-lee/ante/commit/193762c85d624f6812ab42c8414806bb40bc4962))

- **account**: 불변 필드(exchange, currency, trading_mode, broker_type) 수정 차단 (#690)
  ([#691](https://github.com/joshua-jingu-lee/ante/pull/691),
  [`0a32f1d`](https://github.com/joshua-jingu-lee/ante/commit/0a32f1d0cf4fb0fcefc90235647b4cf06c88420d))

- **account**: 삭제된 계좌 활성화 시 409 반환 (#660)
  ([#666](https://github.com/joshua-jingu-lee/ante/pull/666),
  [`94c8ab9`](https://github.com/joshua-jingu-lee/ante/commit/94c8ab99fc3f2d5791a8e4689753de50f3910ff0))

- **account**: 이미 정지된 계좌 재정지 시 409 반환 ([#655](https://github.com/joshua-jingu-lee/ante/pull/655),
  [`cf234dd`](https://github.com/joshua-jingu-lee/ante/commit/cf234dd168490902797228c28c8bce1d5b24b225))

- **api**: Body 없는 POST /accounts/{id}/suspend 422 해결
  ([#646](https://github.com/joshua-jingu-lee/ante/pull/646),
  [`ea4305c`](https://github.com/joshua-jingu-lee/ante/commit/ea4305c38a6f0d378425b94676e2162b91baca4d))

- **api**: 전략 상세 응답에 root-level status 필드 추가 (#672)
  ([#674](https://github.com/joshua-jingu-lee/ante/pull/674),
  [`1f752df`](https://github.com/joshua-jingu-lee/ante/commit/1f752df5260c58e02884d37769f780cde542888d))

- **bot**: Bot 생성 시 Account 상태(active) 검증 추가 #736
  ([#746](https://github.com/joshua-jingu-lee/ante/pull/746),
  [`352917c`](https://github.com/joshua-jingu-lee/ante/commit/352917c480c3fc43a80b7ed8c6f2384ef1bcb83e))

- **bot**: Bot.stop()에서 ERROR→STOPPED 상태 전이 허용
  ([#809](https://github.com/joshua-jingu-lee/ante/pull/809),
  [`e26ca99`](https://github.com/joshua-jingu-lee/ante/commit/e26ca99019b317721462349baa7a324659e3b660))

- **bot**: BotConfig.paper_initial_balance 필드 제거 #747
  ([#766](https://github.com/joshua-jingu-lee/ante/pull/766),
  [`b5c5d41`](https://github.com/joshua-jingu-lee/ante/commit/b5c5d4149fb44b818f8cdca9bed966e36737a05d))

- **bot**: Get_info()에 trading_mode, exchange, currency 필드 추가 #750
  ([#761](https://github.com/joshua-jingu-lee/ante/pull/761),
  [`3d42939`](https://github.com/joshua-jingu-lee/ante/commit/3d42939e8237d80d167b540e6d4376e92a3792e6))

- **bot**: PUT /api/bots/{id} budget 수정 시 TreasuryError를 422로 반환
  ([#853](https://github.com/joshua-jingu-lee/ante/pull/853),
  [`9aebeca`](https://github.com/joshua-jingu-lee/ante/commit/9aebecaa076547c5ac4734e2adf32715d2a5062d))

- **bot**: SignalChannel에 OrderCancelFailedEvent 구독 추가 #779
  ([#816](https://github.com/joshua-jingu-lee/ante/pull/816),
  [`bdabbc6`](https://github.com/joshua-jingu-lee/ante/commit/bdabbc69af18d9c39057d08c61c41bca42abbc8f))

- **bot**: 계좌 상태 검증을 strategy meta 조건에서 분리
  ([#746](https://github.com/joshua-jingu-lee/ante/pull/746),
  [`352917c`](https://github.com/joshua-jingu-lee/ante/commit/352917c480c3fc43a80b7ed8c6f2384ef1bcb83e))

- **bot**: 연속 타임아웃 초과 시 ERROR 상태 전이 및 BotErrorEvent 발행 #793
  ([#811](https://github.com/joshua-jingu-lee/ante/pull/811),
  [`c89b952`](https://github.com/joshua-jingu-lee/ante/commit/c89b9527f2fd03c12ae630e153bbc749e0d3b298))

- **bot**: 정지된 계좌에서 봇 생성 시 409 반환 ([#654](https://github.com/joshua-jingu-lee/ante/pull/654),
  [`77efd2c`](https://github.com/joshua-jingu-lee/ante/commit/77efd2cf8ac5e55d177207f6becd50ff16519e54))

- **broker**: AccountService.get_broker()에 is_paper 주입 — KIS 모의투자 모드 수정
  ([#897](https://github.com/joshua-jingu-lee/ante/pull/897),
  [`e5ad5b8`](https://github.com/joshua-jingu-lee/ante/commit/e5ad5b8f82ed3206af0e6cbb1db316c62f65fffe))

- **cli**: Broker CLI IPC 우선 전환으로 토큰 재발급 방지
  ([#898](https://github.com/joshua-jingu-lee/ante/pull/898),
  [`272cccb`](https://github.com/joshua-jingu-lee/ante/commit/272cccba4d3fa213466e5eba79dc78886ab749dd))

- **cli**: Config set JSON 출력에 status 필드 복원 #705
  ([#707](https://github.com/joshua-jingu-lee/ante/pull/707),
  [`4b0d7aa`](https://github.com/joshua-jingu-lee/ante/commit/4b0d7aaffc4e4de445e39fe13bcd3d442cd24109))

- **cli**: DART API 키 프롬프트 EOF 수신 시 Abort 대신 기본값 처리 (#673)
  ([#675](https://github.com/joshua-jingu-lee/ante/pull/675),
  [`3739108`](https://github.com/joshua-jingu-lee/ante/commit/3739108276744f5661fab1440130f5e55e37ee14))

- **cli**: Trade CLI hang 해결 — 서비스 생성자 인자 수정
  ([#649](https://github.com/joshua-jingu-lee/ante/pull/649),
  [`1ba6321`](https://github.com/joshua-jingu-lee/ante/commit/1ba6321fafd799bca10289f0fb9ef6e9bdd61fcc))

- **config**: 웹 대시보드 기본 포트를 8000에서 3982로 변경
  ([#600](https://github.com/joshua-jingu-lee/ante/pull/600),
  [`3f194ae`](https://github.com/joshua-jingu-lee/ante/commit/3f194aea4b69df11959a112d5ecfc2f011c40c86))

- **event**: BotRestartExhaustedEvent에 account_id 필드 추가
  ([#757](https://github.com/joshua-jingu-lee/ante/pull/757),
  [`bf8997d`](https://github.com/joshua-jingu-lee/ante/commit/bf8997da15d102f3e0f63c8bd0c43f4acaafe143))

- **event**: BotRestartExhaustedEvent에 account_id 필드 추가 #749
  ([#757](https://github.com/joshua-jingu-lee/ante/pull/757),
  [`bf8997d`](https://github.com/joshua-jingu-lee/ante/commit/bf8997da15d102f3e0f63c8bd0c43f4acaafe143))

- **frontend**: BotEditModal 전략 변경이 서버에 전송되지 않는 버그 수정
  ([#899](https://github.com/joshua-jingu-lee/ante/pull/899),
  [`94590c3`](https://github.com/joshua-jingu-lee/ante/commit/94590c385d8118576422148991eb79f1cb24ae09))

- **frontend**: Revoked 에이전트 목록 숨김 및 suspended 아바타 dimmed 적용
  ([#901](https://github.com/joshua-jingu-lee/ante/pull/901),
  [`ce49851`](https://github.com/joshua-jingu-lee/ante/commit/ce49851f561039b8bf68da7c7e44c19ea3ac1fce))

- **frontend**: 결재 승인 완료 시 positive 배너 추가
  ([#901](https://github.com/joshua-jingu-lee/ante/pull/901),
  [`ce49851`](https://github.com/joshua-jingu-lee/ante/commit/ce49851f561039b8bf68da7c7e44c19ea3ac1fce))

- **frontend**: 디자인 토큰 위반 일괄 수정 — 시맨틱 토큰으로 치환
  ([#873](https://github.com/joshua-jingu-lee/ante/pull/873),
  [`b4904a3`](https://github.com/joshua-jingu-lee/ante/commit/b4904a394bdbd581cc2918dcd83a2319f0cdc1d5))

- **frontend**: 리포트 rejected 라벨 '미채택'으로 변경 및 수행자 ID 병기
  ([#901](https://github.com/joshua-jingu-lee/ante/pull/901),
  [`ce49851`](https://github.com/joshua-jingu-lee/ante/commit/ce49851f561039b8bf68da7c7e44c19ea3ac1fce))

- **frontend**: 설정 페이지 필드 누락 및 리스크 규칙 레이아웃 구분
  ([#909](https://github.com/joshua-jingu-lee/ante/pull/909),
  [`f5d1314`](https://github.com/joshua-jingu-lee/ante/commit/f5d1314f5a418d8685cf3f5b625e3034c50d86c2))

- **frontend**: 에이전트 등록 폼 개선 및 상태 버튼 상세 전용 전환
  ([#904](https://github.com/joshua-jingu-lee/ante/pull/904),
  [`cd2f469`](https://github.com/joshua-jingu-lee/ante/commit/cd2f469d5de218bcafbfe75324b8477e0a0189ba))

- **frontend**: 에이전트 등록 폼 소속 자유입력 및 Agent ID 정규식 검증 추가
  ([#904](https://github.com/joshua-jingu-lee/ante/pull/904),
  [`cd2f469`](https://github.com/joshua-jingu-lee/ante/commit/cd2f469d5de218bcafbfe75324b8477e0a0189ba))

- **frontend**: 에이전트 상태 전환 버튼을 카드에서 제거하여 상세 페이지에서만 노출
  ([#904](https://github.com/joshua-jingu-lee/ante/pull/904),
  [`cd2f469`](https://github.com/joshua-jingu-lee/ante/commit/cd2f469d5de218bcafbfe75324b8477e0a0189ba))

- **frontend**: 유저스토리 라벨·문구 스펙 불일치 5건 수정 (#900)
  ([#901](https://github.com/joshua-jingu-lee/ante/pull/901),
  [`ce49851`](https://github.com/joshua-jingu-lee/ante/commit/ce49851f561039b8bf68da7c7e44c19ea3ac1fce))

- **frontend**: 전략 상태 뱃지 archived 라벨 '보관됨' → '보관' 수정
  ([#901](https://github.com/joshua-jingu-lee/ante/pull/901),
  [`ce49851`](https://github.com/joshua-jingu-lee/ante/commit/ce49851f561039b8bf68da7c7e44c19ea3ac1fce))

- **member**: Reactivate()에 MemberReactivatedEvent 발행 추가 #797
  ([#813](https://github.com/joshua-jingu-lee/ante/pull/813),
  [`f281fb0`](https://github.com/joshua-jingu-lee/ante/commit/f281fb02db1ccc0d21ad6d0af414175f9992fed1))

- **member**: RecoveryKeyManager 인증 실패 시 NotificationEvent 발행 추가 #807
  ([#814](https://github.com/joshua-jingu-lee/ante/pull/814),
  [`c08fe22`](https://github.com/joshua-jingu-lee/ante/commit/c08fe22089efe977807d725e9c80afdcaa5edaae))

- **member**: Register/update_scopes master 권한 검증 추가
  ([#763](https://github.com/joshua-jingu-lee/ante/pull/763),
  [`58ed8bd`](https://github.com/joshua-jingu-lee/ante/commit/58ed8bdd49233bf502c8d4540fd460823748b004))

- **member**: Register/update_scopes에 master 권한 검증 추가 #739
  ([#763](https://github.com/joshua-jingu-lee/ante/pull/763),
  [`58ed8bd`](https://github.com/joshua-jingu-lee/ante/commit/58ed8bdd49233bf502c8d4540fd460823748b004))

- **member**: 패스워드 변경/리셋 시 NotificationEvent 발행 추가
  ([#787](https://github.com/joshua-jingu-lee/ante/pull/787),
  [`4b3f1df`](https://github.com/joshua-jingu-lee/ante/commit/4b3f1df6bc1ff55bac2ce1b2cef746e96f95b876))

- **member**: 패스워드 변경/리셋 시 기존 토큰 무효화 추가 ([#784](https://github.com/joshua-jingu-lee/ante/pull/784),
  [`d97dce1`](https://github.com/joshua-jingu-lee/ante/commit/d97dce10dc4b83fc70d15946173c7a5c5362c0da))

- **qa**: Docker exec 시 CLI 토큰 파일 폴백으로 인증 실패 해결 Refs #854
  ([#858](https://github.com/joshua-jingu-lee/ante/pull/858),
  [`d3c1894`](https://github.com/joshua-jingu-lee/ante/commit/d3c18948b1b18874a7a648a224f9c991a9f66f8d))

- **qa**: QA TC 환경 결함 5건 수정 — 토큰·credentials·allocation·데이터셋·룰 params
  ([#868](https://github.com/joshua-jingu-lee/ante/pull/868),
  [`055f578`](https://github.com/joshua-jingu-lee/ante/commit/055f578b8af2564ea1b0111f6af0b0a6a227ed16))

- **qa**: QA 엔트리포인트에 risk.test_qa_key 동적 설정 시드 등록
  ([#638](https://github.com/joshua-jingu-lee/ante/pull/638),
  [`0f9daec`](https://github.com/joshua-jingu-lee/ante/commit/0f9daec0cde9e552ce23e94baebb3726cf2af10d))

- **qa**: QA 전략 레지스트리 시딩 구현 ([#657](https://github.com/joshua-jingu-lee/ante/pull/657),
  [`5ae41ac`](https://github.com/joshua-jingu-lee/ante/commit/5ae41ac3230bc0622af809e80468259127112d7f))

- **qa**: QA 컨테이너에 ANTE_MEMBER_TOKEN 설정 — CLI TC 인증 실패 해결
  ([#849](https://github.com/joshua-jingu-lee/ante/pull/849),
  [`4cfe4ff`](https://github.com/joshua-jingu-lee/ante/commit/4cfe4ff46874f4ffa05c851d7974fa6cf2868a6b))

- **qa**: QA 환경에 qa_sample.py 전략 파일 추가 ([#637](https://github.com/joshua-jingu-lee/ante/pull/637),
  [`4d123eb`](https://github.com/joshua-jingu-lee/ante/commit/4d123eb6e4b8f41fe5b52fd0eef016e888b600fa))

- **qa**: Treasury 503 — get_treasury fallback 및 QA 시드 계좌 추가
  ([#648](https://github.com/joshua-jingu-lee/ante/pull/648),
  [`14bf435`](https://github.com/joshua-jingu-lee/ante/commit/14bf435e9c7813735b7496e0697ed0b0f988a2c6))

- **qa**: 전략 시딩 스크립트 모듈 수준 변수 참조 지원
  ([`d222323`](https://github.com/joshua-jingu-lee/ante/commit/d222323b55c9b4f0507b1f0c8cd7680800e7c56d))

- **rule**: DailyLossLimitRule 손실률 분모를 전일 총 자산으로 수정
  ([#712](https://github.com/joshua-jingu-lee/ante/pull/712),
  [`89bb965`](https://github.com/joshua-jingu-lee/ante/commit/89bb965017bb23f5272b36c48bcd65febdbdb92e))

- **rule**: DailyLossLimitRule/TotalExposureLimitRule 매도(손절) 허용 및 알림 전환
  ([#716](https://github.com/joshua-jingu-lee/ante/pull/716),
  [`c912271`](https://github.com/joshua-jingu-lee/ante/commit/c912271b8a6fa58ffe3f89481662caf9a7e8ff38))

- **rule**: PositionSizeRule 분모를 봇 할당 예산으로 수정 (#771)
  ([#782](https://github.com/joshua-jingu-lee/ante/pull/782),
  [`cc51989`](https://github.com/joshua-jingu-lee/ante/commit/cc5198940019e17c094c875f301fc0825438946f))

- **rule**: RuleEngine.start() sync 시그니처 확인 및 회귀 테스트 추가 #742
  ([#760](https://github.com/joshua-jingu-lee/ante/pull/760),
  [`26bfbf5`](https://github.com/joshua-jingu-lee/ante/commit/26bfbf517c6ee0d273e0bac4f590c18f94de16a5))

- **rule**: TotalExposureLimitRule 노출률을 전 봇 합산/총 자산으로 수정
  ([#714](https://github.com/joshua-jingu-lee/ante/pull/714),
  [`5c20546`](https://github.com/joshua-jingu-lee/ante/commit/5c20546479b8cce36c6ac6978860eb2566c29399))

- **rule**: TotalExposureLimitRule 노출률을 전 봇 합산/총 자산으로 수정 #710
  ([#714](https://github.com/joshua-jingu-lee/ante/pull/714),
  [`5c20546`](https://github.com/joshua-jingu-lee/ante/commit/5c20546479b8cce36c6ac6978860eb2566c29399))

- **rule**: TradingHoursRule이 Account의 거래시간을 RuleContext 경유로 사용 #781
  ([#818](https://github.com/joshua-jingu-lee/ante/pull/818),
  [`be6ec32`](https://github.com/joshua-jingu-lee/ante/commit/be6ec32fbe351c2e204b30a00ff2ed32c1821e2f))

- **rule**: UnrealizedLossLimitRule metadata 경유 제거 및 데이터 주입 구현 #783
  ([#810](https://github.com/joshua-jingu-lee/ante/pull/810),
  [`47590a1`](https://github.com/joshua-jingu-lee/ante/commit/47590a13b9757c16cf1b5c461381abb49e4d7629))

- **rule**: 계좌 리스크 룰 config validation 추가 — 음수 값 거부
  ([#851](https://github.com/joshua-jingu-lee/ante/pull/851),
  [`3942c2a`](https://github.com/joshua-jingu-lee/ante/commit/3942c2abf6b86e63003a5a93233997a2a4a8dfd4))

- **strategy**: 전략 성과 조회 500 에러 수정 (#659)
  ([#665](https://github.com/joshua-jingu-lee/ante/pull/665),
  [`eba47a3`](https://github.com/joshua-jingu-lee/ante/commit/eba47a3a7b707231f7a40ab8399fbf6a90f5021c))

- **tc**: Account create 대화형 테스트에 인증정보 입력 추가
  ([`b2f6e42`](https://github.com/joshua-jingu-lee/ante/commit/b2f6e42add84da157c44c1a54b54248ad3b5a6bf))

- **tc**: Account/rules TC 재실행 시 409 Conflict 실패 수정
  ([#861](https://github.com/joshua-jingu-lee/ante/pull/861),
  [`ed3daff`](https://github.com/joshua-jingu-lee/ante/commit/ed3daff0138ed0444045c1517cd99689b4992785))

- **tc**: Allocation.feature 멱등성 확보 — 봇 삭제 후 재생성 방식
  ([`fb1aa0f`](https://github.com/joshua-jingu-lee/ante/commit/fb1aa0fd1d512d3f7d2ebffcdb62f67b76cc5448))

- **tc**: Allocation.feature 봇 생성에 bot_id 필드 추가
  ([`de96a76`](https://github.com/joshua-jingu-lee/ante/commit/de96a76aa0d0ee33b9e39e8de58dbc3701c244f1))

- **tc**: Allocation.feature 봇 생성에 strategy_id 누락 수정
  ([`ed09b08`](https://github.com/joshua-jingu-lee/ante/commit/ed09b089b04f23e750bb325544a5814ac9103895))

- **tc**: Broker_type mock → test로 일괄 변경 ([#636](https://github.com/joshua-jingu-lee/ante/pull/636),
  [`f22562d`](https://github.com/joshua-jingu-lee/ante/commit/f22562dad19f7c1dba79d522a92795ec2c5cde30))

- **tc**: Credentials.feature broker_type 재설계 (#662)
  ([#669](https://github.com/joshua-jingu-lee/ante/pull/669),
  [`58d3259`](https://github.com/joshua-jingu-lee/ante/commit/58d325982d5f86dcadbf5def08ab79c42f7939e3))

- **tc**: Credentials.feature 멱등성 확보 — 계좌/봇 생성 시 409 허용
  ([`92f25fa`](https://github.com/joshua-jingu-lee/ante/commit/92f25fa8f9934d9a125e2d7311a079eba0930148))

- **tc**: Init.feature CLI 시스템 상태 필드명 수정
  ([`9698c97`](https://github.com/joshua-jingu-lee/ante/commit/9698c976e3cdc1cf03a28e30f6199f4c62efc4f1))

- **tc**: Init.feature 응답 구조 및 환경값 불일치 수정 (#661)
  ([#668](https://github.com/joshua-jingu-lee/ante/pull/668),
  [`8a905a5`](https://github.com/joshua-jingu-lee/ante/commit/8a905a52b6635cfeb768adc0243a872b4da5ab2f))

- **tc**: Install.feature DART 프롬프트 입력 추가 및 allocation.feature 멱등성 보강
  ([`363798c`](https://github.com/joshua-jingu-lee/ante/commit/363798c5e902a9b3c1ddc88248d5cb6e02f66cf3))

- **tc**: TC 데이터 보완 — DELETE 204, 봇 필수필드, 비밀번호 불일치
  ([#647](https://github.com/joshua-jingu-lee/ante/pull/647),
  [`82eedf2`](https://github.com/joshua-jingu-lee/ante/commit/82eedf2e6b7620920135ce246eb5197a304cb962))

- **tc**: Treasury TC credentials API 404 수정 및 allocation 정리 추가
  ([#859](https://github.com/joshua-jingu-lee/ante/pull/859),
  [`a8620ae`](https://github.com/joshua-jingu-lee/ante/commit/a8620ae9f3d4ae1fa5807607e82a872b31c8703d))

- **test**: _on_restart_exhausted 호출에 account_id 파라미터 추가
  ([#757](https://github.com/joshua-jingu-lee/ante/pull/757),
  [`bf8997d`](https://github.com/joshua-jingu-lee/ante/commit/bf8997da15d102f3e0f63c8bd0c43f4acaafe143))

- **test**: Account delete 테스트 mock 대상을 IPC로 전환
  ([#720](https://github.com/joshua-jingu-lee/ante/pull/720),
  [`dd45dc1`](https://github.com/joshua-jingu-lee/ante/commit/dd45dc128214aeabbf1bb3ca2164639c54e1acbc))

- **test**: Account 생성 시 credentials 누락된 테스트 일괄 수정 #803
  ([#803](https://github.com/joshua-jingu-lee/ante/pull/803),
  [`67e228c`](https://github.com/joshua-jingu-lee/ante/commit/67e228c4a08b0bb6d3f3e3f90525eedf0e987904))

- **test**: BacktestConfig 테스트에서 commission_rate를 buy/sell로 분리 반영 #734
  ([#734](https://github.com/joshua-jingu-lee/ante/pull/734),
  [`91c7e4e`](https://github.com/joshua-jingu-lee/ante/commit/91c7e4e1fbd56cc0f571a16df027c761bd1f209a))

- **test**: FakeTreasury에 get_latest_snapshot 메서드 추가
  ([#714](https://github.com/joshua-jingu-lee/ante/pull/714),
  [`5c20546`](https://github.com/joshua-jingu-lee/ante/commit/5c20546479b8cce36c6ac6978860eb2566c29399))

- **test**: IPC 핸들러 등록 테스트 기대값 15 → 16으로 수정
  ([#720](https://github.com/joshua-jingu-lee/ante/pull/720),
  [`dd45dc1`](https://github.com/joshua-jingu-lee/ante/commit/dd45dc128214aeabbf1bb3ca2164639c54e1acbc))

- **test**: Portfolio history 존재하지 않는 account_id 테스트 기대값을 404로 수정
  ([#714](https://github.com/joshua-jingu-lee/ante/pull/714),
  [`5c20546`](https://github.com/joshua-jingu-lee/ante/commit/5c20546479b8cce36c6ac6978860eb2566c29399))

- **test**: PortfolioHistoryResponse 테스트 mock 데이터를 현행 모델에 맞게 갱신
  ([#714](https://github.com/joshua-jingu-lee/ante/pull/714),
  [`5c20546`](https://github.com/joshua-jingu-lee/ante/commit/5c20546479b8cce36c6ac6978860eb2566c29399))

- **test**: Replace private _handlers access with public get_handlers() API
  ([#758](https://github.com/joshua-jingu-lee/ante/pull/758),
  [`946a7ed`](https://github.com/joshua-jingu-lee/ante/commit/946a7edcaffea13703d5ca5083a6a6ade2810cd2))

- **test**: Test_config_path를 대화형 init 흐름에 맞게 수정
  ([`9636743`](https://github.com/joshua-jingu-lee/ante/commit/9636743c01c257d5b23e6a90e0cc3dc2e5c570b5))

- **test**: Test_consecutive_timeout_stops_bot를 ERROR 전이 검증으로 수정 #793
  ([#811](https://github.com/joshua-jingu-lee/ante/pull/811),
  [`c89b952`](https://github.com/joshua-jingu-lee/ante/commit/c89b9527f2fd03c12ae630e153bbc749e0d3b298))

- **test**: Test_register_sets_expiry에 master 조회 mock 추가
  ([#763](https://github.com/joshua-jingu-lee/ante/pull/763),
  [`58ed8bd`](https://github.com/joshua-jingu-lee/ante/commit/58ed8bdd49233bf502c8d4540fd460823748b004))

- **test**: TestBotManagerExchangeValidation에 credentials 추가 #803
  ([#803](https://github.com/joshua-jingu-lee/ante/pull/803),
  [`67e228c`](https://github.com/joshua-jingu-lee/ante/commit/67e228c4a08b0bb6d3f3e3f90525eedf0e987904))

- **test**: 에픽 브랜치 통합 후 테스트 수정 ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **trade**: Force_update() 후 인메모리 캐시 갱신 누락 수정
  ([#754](https://github.com/joshua-jingu-lee/ante/pull/754),
  [`0742e38`](https://github.com/joshua-jingu-lee/ante/commit/0742e382cb138ee0a66dac4e4180a45eb09c2157))

- **trade**: INSERT문에 exchange 컬럼 누락 수정 (#737)
  ([#764](https://github.com/joshua-jingu-lee/ante/pull/764),
  [`0830c1d`](https://github.com/joshua-jingu-lee/ante/commit/0830c1ddac6d645efd9db99813c6187cd5d89a7c))

- **trade**: MDD 비율 계산을 equity curve 기반으로 전환 #788
  ([#815](https://github.com/joshua-jingu-lee/ante/pull/815),
  [`bd9aed3`](https://github.com/joshua-jingu-lee/ante/commit/bd9aed30b0441bac702c14cfedd83de963af187c))

- **trade**: PerformanceTracker JOIN 조건을 trade_id FK 기반으로 변경 #785
  ([#817](https://github.com/joshua-jingu-lee/ante/pull/817),
  [`1519d14`](https://github.com/joshua-jingu-lee/ante/commit/1519d1415ee2747ba7e097488fbacdc24781dcce))

- **trade**: PerformanceTracker.calculate()에서 account_id 필수 검증 추가
  ([#805](https://github.com/joshua-jingu-lee/ante/pull/805),
  [`d49117c`](https://github.com/joshua-jingu-lee/ante/commit/d49117cf84d8801cb15160b91d031b7442d01f72))

- **trade**: QA 시드 데이터 trade_id UUID 파싱 실패 수정 Refs #865
  ([#867](https://github.com/joshua-jingu-lee/ante/pull/867),
  [`06afba0`](https://github.com/joshua-jingu-lee/ante/commit/06afba02e3e5646c2a452f3e74b7143e4221a30a))

- **trade**: 체결 알림에 누적 수량/평단가/손익 추가 #777 ([#819](https://github.com/joshua-jingu-lee/ante/pull/819),
  [`3aec7b7`](https://github.com/joshua-jingu-lee/ante/commit/3aec7b70b5773247b85d680cc43b1dd2ab2cc798))

- **trade**: 초과 매도 시 보유 수량 기준으로 PnL 계산 #769
  ([#778](https://github.com/joshua-jingu-lee/ante/pull/778),
  [`a686bd0`](https://github.com/joshua-jingu-lee/ante/commit/a686bd064472aa2c6630534ac59d1dd54d4c3d15))

- **treasury**: DailyReportEvent 구독 priority 70→80 통일
  ([#758](https://github.com/joshua-jingu-lee/ante/pull/758),
  [`946a7ed`](https://github.com/joshua-jingu-lee/ante/commit/946a7edcaffea13703d5ca5083a6a6ade2810cd2))

- **treasury**: DailyReportEvent 구독 priority 70→80 통일 #751
  ([#758](https://github.com/joshua-jingu-lee/ante/pull/758),
  [`946a7ed`](https://github.com/joshua-jingu-lee/ante/commit/946a7edcaffea13703d5ca5083a6a6ade2810cd2))

- **treasury**: Reserve_for_order()에 amount <= 0 입력 검증 추가
  ([#808](https://github.com/joshua-jingu-lee/ante/pull/808),
  [`ff56e99`](https://github.com/joshua-jingu-lee/ante/commit/ff56e99598ccc0e290aaf6ec6b3da8e3b4ce9ec3))

- **treasury**: Take_snapshot()이 스냅샷 dict를 반환하도록 수정 #752
  ([#759](https://github.com/joshua-jingu-lee/ante/pull/759),
  [`cba10bb`](https://github.com/joshua-jingu-lee/ante/commit/cba10bbbd0c39561a92dde94a7a35de1f7a06f8e))

- **treasury**: Total_asset 산식을 ante_eval_amount + unallocated로 수정
  ([#755](https://github.com/joshua-jingu-lee/ante/pull/755),
  [`54201f9`](https://github.com/joshua-jingu-lee/ante/commit/54201f9ff20106aa9ae35d350815a3ac1e5e1900))

- **treasury**: Treasury_state 테이블에 누락 필드 추가하여 재시작 시 평가액 데이터 복원
  ([#765](https://github.com/joshua-jingu-lee/ante/pull/765),
  [`9e5e2de`](https://github.com/joshua-jingu-lee/ante/commit/9e5e2de31b6551399994cc7c9956e254d6959edf))

- **treasury**: Treasury_transactions account_id DEFAULT 제거, NOT NULL 강제
  ([#812](https://github.com/joshua-jingu-lee/ante/pull/812),
  [`c411495`](https://github.com/joshua-jingu-lee/ante/commit/c411495acb75f4cf82cecc83ff674230d10054a1))

- **treasury**: 봇 삭제 시 Treasury budget 환수 및 정리
  ([#679](https://github.com/joshua-jingu-lee/ante/pull/679),
  [`273c9ea`](https://github.com/joshua-jingu-lee/ante/commit/273c9eae93972dae445598ae6e565760ae11d3a8))

- **treasury**: 존재하지 않는 봇 예산 할당 시 404 반환 (#658)
  ([#664](https://github.com/joshua-jingu-lee/ante/pull/664),
  [`bd6caf8`](https://github.com/joshua-jingu-lee/ante/commit/bd6caf8b7a8c92b20efca64124550b47e0916b4f))

- **ui**: 타이포그래피 위반 22건 + 인라인 스타일 1건 수정 ([#872](https://github.com/joshua-jingu-lee/ante/pull/872),
  [`0960bd2`](https://github.com/joshua-jingu-lee/ante/commit/0960bd2bb9c10522f64f1fbe896a37761157547f))

- **web**: /api/auth/me 엔드포인트에 Bearer 토큰 인증 지원 추가 #704
  ([#706](https://github.com/joshua-jingu-lee/ante/pull/706),
  [`170babe`](https://github.com/joshua-jingu-lee/ante/commit/170babef129a8b8f68f283815d4b0ac58d3b5351))

- **web**: PR #688 리뷰 지적 사항 반영 — 하위 호환성 및 response_model 추가
  ([#688](https://github.com/joshua-jingu-lee/ante/pull/688),
  [`272857f`](https://github.com/joshua-jingu-lee/ante/commit/272857fd62a75f077483b5311413cf8b0cd6685d))

- **web**: 멤버 API 라우트 caller_id를 request.state.member_id에서 취득 #767
  ([#768](https://github.com/joshua-jingu-lee/ante/pull/768),
  [`c63f094`](https://github.com/joshua-jingu-lee/ante/commit/c63f0940e733f5b08baf46022677bde2b6b6ef26))

### Chores

- .claude/ 전체 gitignore 처리
  ([`2a1d9fd`](https://github.com/joshua-jingu-lee/ante/commit/2a1d9fd580af869ead7d66245cb561c813a8de8a))

- Dockerfile 테스트 시드 제거 및 대시보드 기본 활성화
  ([`62eb08a`](https://github.com/joshua-jingu-lee/ante/commit/62eb08adad3dcdb29691f7aad9dc1ff1df834e53))

- Trigger CI ([#740](https://github.com/joshua-jingu-lee/ante/pull/740),
  [`8a89127`](https://github.com/joshua-jingu-lee/ante/commit/8a891273311f7ee7de0ca7fe5896142090d8f049))

- 스킬 파일 정리 및 QA 환경 설정 보완
  ([`e40f507`](https://github.com/joshua-jingu-lee/ante/commit/e40f5079885fea6a6e4187c2a13bbfc43e5554a2))

- **ci**: CI/QA에 ANTE_DB_ENCRYPTION_KEY 환경변수 추가
  ([#744](https://github.com/joshua-jingu-lee/ante/pull/744),
  [`3d7a5be`](https://github.com/joshua-jingu-lee/ante/commit/3d7a5bee325b0e25e31b7120dd76321b97c965ca))

- **deps**: Add cryptography package for Fernet encryption
  ([#735](https://github.com/joshua-jingu-lee/ante/pull/735),
  [`fe219a0`](https://github.com/joshua-jingu-lee/ante/commit/fe219a0cf85dfbf7621b0d5549507c296e332ea5))

- **tc**: Credentials.feature 사전 정리 단계 추가 — API+DB 2단계 클린업
  ([`b138c20`](https://github.com/joshua-jingu-lee/ante/commit/b138c206215c619395fb319d49562a3995cc2a7c))

### Code Style

- Pyproject.toml 섹션 간 빈 줄 추가 ([#609](https://github.com/joshua-jingu-lee/ante/pull/609),
  [`1072c26`](https://github.com/joshua-jingu-lee/ante/commit/1072c262bd7e170aefff20f3b8f4a75d8305a183))

### Continuous Integration

- PyPI 배포 워크플로우 추가 Refs #919 ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- Semantic-release에서 Docker 빌드·push 단계 제거
  ([`4e146a4`](https://github.com/joshua-jingu-lee/ante/commit/4e146a44c81b260fcefb2154ffc8af9d9e1b812b))

### Documentation

- Getting Started 가이드 작성 및 ante init 스펙 갱신
  ([`76ec15a`](https://github.com/joshua-jingu-lee/ante/commit/76ec15a60fa5d6bdfd142c4871b0b4c4f6dbd38c))

- README.md 간결화 및 태그라인 수정
  ([`8bef8c9`](https://github.com/joshua-jingu-lee/ante/commit/8bef8c93b3098b3e9e9b024ec68e5578882ffa64))

- 공개용 사용자 가이드 디렉토리 초기 구조 생성
  ([`2ddaddd`](https://github.com/joshua-jingu-lee/ante/commit/2ddaddd056c77206a739492d538b4d157bfe2831))

- **account**: Suspend/delete docstring에 AccountDeletedException 누락 보완
  ([#725](https://github.com/joshua-jingu-lee/ante/pull/725),
  [`9309429`](https://github.com/joshua-jingu-lee/ante/commit/9309429cddb91dd42bd4713849d8b07ef72f212d))

- **cli**: 헤더를 사용자 친화적 소개 문구로 변경
  ([`141eb4f`](https://github.com/joshua-jingu-lee/ante/commit/141eb4f16f57b4efe685087f806df3c16c6b7b06))

- **guide**: Account 모델 반영하여 가이드 문서 업데이트 (#576)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **guide**: Docker 설치 섹션 제거 및 플랫폼 요구사항 명시
  ([`078a405`](https://github.com/joshua-jingu-lee/ante/commit/078a405a7dee2e4c5c7874fbf5495a32637ae1c0))

- **guide**: Treasury snapshot 커맨드를 cli.md에 등록
  ([#687](https://github.com/joshua-jingu-lee/ante/pull/687),
  [`057283b`](https://github.com/joshua-jingu-lee/ante/commit/057283ba662fde219b17f0231ac7a7fee483227d))

- **guide**: 대시보드·보안 가이드 포트 번호 수정 (8000 → 3982)
  ([`119797b`](https://github.com/joshua-jingu-lee/ante/commit/119797ba497e716b1b793a0bdde6f8ac7da926c7))

- **guide**: 대시보드·보안·전략 가이드 문서 작성
  ([`a2a2356`](https://github.com/joshua-jingu-lee/ante/commit/a2a235674f906347d8967935d19c1a95ae078769))

- **tc**: Gherkin TC 컨벤션 가이드 작성 ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

### Features

- 결재함 서버사이드 검색 + 스토리지 유형별 용량 표시 (#905) ([#906](https://github.com/joshua-jingu-lee/ante/pull/906),
  [`ca4a0da`](https://github.com/joshua-jingu-lee/ante/commit/ca4a0da81cc483696ff2be404c44b63d8a888cb8))

- 자금 거래내역 날짜 필터, 데이터셋 파일크기/미리보기, 검색 debounce
  ([#904](https://github.com/joshua-jingu-lee/ante/pull/904),
  [`cd2f469`](https://github.com/joshua-jingu-lee/ante/commit/cd2f469d5de218bcafbfe75324b8477e0a0189ba))

- 프로젝트 에이전트 6종 추가 (.claude/agents/)
  ([`ee67b52`](https://github.com/joshua-jingu-lee/ante/commit/ee67b526b9dc4b21d03474129e04f5cbc209fe1c))

- **account**: Account 모델·서비스·DB 스키마 생성 (#560)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **approval**: GET /api/approvals에 search 쿼리 파라미터 추가 #794
  ([#830](https://github.com/joshua-jingu-lee/ante/pull/830),
  [`4319fe6`](https://github.com/joshua-jingu-lee/ante/commit/4319fe6768222600fc56da96da97415f8b598c02))

- **approval**: 결재함 제목 검색을 서버사이드로 전환 ([#906](https://github.com/joshua-jingu-lee/ante/pull/906),
  [`ca4a0da`](https://github.com/joshua-jingu-lee/ante/commit/ca4a0da81cc483696ff2be404c44b63d8a888cb8))

- **backtest**: _validate_config() -> BacktestConfig 통합 + 수수료 분리 #727
  ([#734](https://github.com/joshua-jingu-lee/ante/pull/734),
  [`91c7e4e`](https://github.com/joshua-jingu-lee/ante/commit/91c7e4e1fbd56cc0f571a16df027c761bd1f209a))

- **backtest**: BacktestConfig/DatasetInfo 데이터클래스 생성 Refs #722
  ([#734](https://github.com/joshua-jingu-lee/ante/pull/734),
  [`91c7e4e`](https://github.com/joshua-jingu-lee/ante/commit/91c7e4e1fbd56cc0f571a16df027c761bd1f209a))

- **backtest**: BacktestDataProvider에 loaded_datasets 이력 기록 Refs #726
  ([#734](https://github.com/joshua-jingu-lee/ante/pull/734),
  [`91c7e4e`](https://github.com/joshua-jingu-lee/ante/commit/91c7e4e1fbd56cc0f571a16df027c761bd1f209a))

- **backtest**: BacktestResult에 config/datasets 필드 추가 Refs #723
  ([#734](https://github.com/joshua-jingu-lee/ante/pull/734),
  [`91c7e4e`](https://github.com/joshua-jingu-lee/ante/commit/91c7e4e1fbd56cc0f571a16df027c761bd1f209a))

- **bot**: BotConfig에 account_id 추가, bot_type·exchange 제거 (#564)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **bot**: BotStepCompletedEvent 추가 및 봇 실행 로그 API #786
  ([#821](https://github.com/joshua-jingu-lee/ante/pull/821),
  [`d5b6ba6`](https://github.com/joshua-jingu-lee/ante/commit/d5b6ba6263283193c8d3bb12d223a1836d965d7e))

- **bot**: DELETE /api/bots/{id}에 handle_positions 옵션 추가 #796
  ([#830](https://github.com/joshua-jingu-lee/ante/pull/830),
  [`4319fe6`](https://github.com/joshua-jingu-lee/ante/commit/4319fe6768222600fc56da96da97415f8b598c02))

- **bot**: GET /api/bots 응답에 strategy_name, strategy_author_name 추가 #792
  ([#830](https://github.com/joshua-jingu-lee/ante/pull/830),
  [`4319fe6`](https://github.com/joshua-jingu-lee/ante/commit/4319fe6768222600fc56da96da97415f8b598c02))

- **bot**: PUT /api/bots/{bot_id} 봇 설정 수정 API #795
  ([#830](https://github.com/joshua-jingu-lee/ante/pull/830),
  [`4319fe6`](https://github.com/joshua-jingu-lee/ante/commit/4319fe6768222600fc56da96da97415f8b598c02))

- **cli**: Ante account 명령어 그룹 구현 (#571) ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **cli**: Ante init 대화형 통합 초기 설정 ([#557](https://github.com/joshua-jingu-lee/ante/pull/557),
  [`cc3c301`](https://github.com/joshua-jingu-lee/ante/commit/cc3c301d04ddf663009bd26f334d0a431fc92d73))

- **cli**: Ante update --format json 지원 Refs #920
  ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **cli**: Ante update 명령 구현 ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **cli**: CLI 레퍼런스 문서에 자동 목차 생성 추가
  ([`0f9adb7`](https://github.com/joshua-jingu-lee/ante/commit/0f9adb7b1ef82c2931692384bdda9953b9f90a9e))

- **cli**: CLI 버전을 importlib.metadata에서 자동 읽기 Refs #911
  ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **cli**: CLI 전 커맨드에 --format json 서브커맨드 옵션 추가 (#632)
  ([#639](https://github.com/joshua-jingu-lee/ante/pull/639),
  [`4e4151a`](https://github.com/joshua-jingu-lee/ante/commit/4e4151a93da2b008e7b96400ccd196c9fc0a4516))

- **cli**: System status --format json 옵션 추가 (#663)
  ([#667](https://github.com/joshua-jingu-lee/ante/pull/667),
  [`a900322`](https://github.com/joshua-jingu-lee/ante/commit/a900322109a46de7e7d74ebb15c72df21c392575))

- **cli**: Treasury snapshot 커맨드 구현 ([#687](https://github.com/joshua-jingu-lee/ante/pull/687),
  [`057283b`](https://github.com/joshua-jingu-lee/ante/commit/057283ba662fde219b17f0231ac7a7fee483227d))

- **cli**: 기존 CLI 명령어에 --account 옵션 추가 (#573)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **cli**: 서버 실행 중 확인 유틸 함수 추가 ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **dashboard**: 결재함·에이전트·백테스트·리포트 보완 (Phase 5) Refs #838
  ([#845](https://github.com/joshua-jingu-lee/ante/pull/845),
  [`e5423ae`](https://github.com/joshua-jingu-lee/ante/commit/e5423aef16462f6cbd53e5050fbdec16302292a3))

- **dashboard**: 리포트 상세 페이지 자산 커브 차트 연동 #838
  ([#864](https://github.com/joshua-jingu-lee/ante/pull/864),
  [`e529169`](https://github.com/joshua-jingu-lee/ante/commit/e5291692ffa1fc4ad81398fc491ee98222979906))

- **dashboard**: 봇 관리 실행 설정·수정·삭제 API 연동 (Phase 3b) #835
  ([#862](https://github.com/joshua-jingu-lee/ante/pull/862),
  [`2a2bcbe`](https://github.com/joshua-jingu-lee/ante/commit/2a2bcbe528a62ee49a0492e0510f1f36601c2365))

- **dashboard**: 전략 목록 UI 보강 — PAGE_SIZE 15, 검색, 보관 탭, 더보기 링크 #836
  ([#843](https://github.com/joshua-jingu-lee/ante/pull/843),
  [`585dfcf`](https://github.com/joshua-jingu-lee/ante/commit/585dfcfd4f25a4f4ebe2d1646ee3228f46384361))

- **dashboard**: 전략과 성과 Phase 4b — 차트·성과·필터·상태 전환 Refs #837
  ([#863](https://github.com/joshua-jingu-lee/ante/pull/863),
  [`96c1993`](https://github.com/joshua-jingu-lee/ante/commit/96c19939e02c1d32beaf2fa81fb10164570a42db))

- **data**: Parquet 경로에 exchange 차원 추가 (#577)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **data**: ParquetStore.resolve_path() public 노출
  ([#734](https://github.com/joshua-jingu-lee/ante/pull/734),
  [`91c7e4e`](https://github.com/joshua-jingu-lee/ante/commit/91c7e4e1fbd56cc0f571a16df027c761bd1f209a))

- **data**: 데이터셋 파일 크기 연동 및 미리보기 구현 ([#904](https://github.com/joshua-jingu-lee/ante/pull/904),
  [`cd2f469`](https://github.com/joshua-jingu-lee/ante/commit/cd2f469d5de218bcafbfe75324b8477e0a0189ba))

- **data**: 스토리지 현황에 유형별(OHLCV/Fundamental) 용량 표시 추가
  ([#906](https://github.com/joshua-jingu-lee/ante/pull/906),
  [`ca4a0da`](https://github.com/joshua-jingu-lee/ante/commit/ca4a0da81cc483696ff2be404c44b63d8a888cb8))

- **db**: Database 트랜잭션 컨텍스트 매니저 추가 Refs #912
  ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **db**: Parquet 마이그레이션을 중앙 러너에 통합 Refs #924
  ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **db**: Schema_version 테이블 + 중앙 마이그레이션 러너 Refs #913
  ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **eventbus**: Account 이벤트 3종 추가 및 기존 이벤트 account_id 확장 (#562)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **frontend**: 데이터셋 파일크기/미리보기 UI 및 종목 검색 debounce 적용
  ([#904](https://github.com/joshua-jingu-lee/ante/pull/904),
  [`cd2f469`](https://github.com/joshua-jingu-lee/ante/commit/cd2f469d5de218bcafbfe75324b8477e0a0189ba))

- **frontend**: 로그인 스펙 정합성 보완 (Phase 1) Refs #832
  ([#841](https://github.com/joshua-jingu-lee/ante/pull/841),
  [`fd7e389`](https://github.com/joshua-jingu-lee/ante/commit/fd7e389ab122999a95795ed27daa2b029631e8ac))

- **frontend**: 리포트 상세 듀얼 차트·마크다운·수익률% 병기 Refs #892
  ([#909](https://github.com/joshua-jingu-lee/ante/pull/909),
  [`f5d1314`](https://github.com/joshua-jingu-lee/ante/commit/f5d1314f5a418d8685cf3f5b625e3034c50d86c2))

- **frontend**: 봇 관리 카드·UI 정리 (Phase 3a) Refs #834
  ([#844](https://github.com/joshua-jingu-lee/ante/pull/844),
  [`e1f8a35`](https://github.com/joshua-jingu-lee/ante/commit/e1f8a35e58d1adb4187a58f60a479cb28f8f4283))

- **frontend**: 자금관리 Phase 2 — 가상 거래 배너 + 자산 추이 차트 + 예산 가드
  ([#842](https://github.com/joshua-jingu-lee/ante/pull/842),
  [`98c01af`](https://github.com/joshua-jingu-lee/ante/commit/98c01af86042150aeabf731c8cce9fa417e4ba41))

- **infra**: 백엔드 전용 QA Docker 이미지 작성 (#606)
  ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

- **ipc**: IPC 인프라 구축 — ServiceRegistry, 프로토콜, IPCServer/Client #695
  ([#700](https://github.com/joshua-jingu-lee/ante/pull/700),
  [`3002f10`](https://github.com/joshua-jingu-lee/ante/commit/3002f10f4dc691954cd948081dc61f95a6a17021))

- **qa**: QA 데이터셋 시드 스크립트 추가 Refs #856 ([#860](https://github.com/joshua-jingu-lee/ante/pull/860),
  [`262f33b`](https://github.com/joshua-jingu-lee/ante/commit/262f33bcc6a40bc7c7165c023cc17c7cb9a8be72))

- **qa**: QA 서버 설정 및 엔트리포인트 작성 (#607) ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

- **qa**: 자동 버그 리포팅 및 --fix 수정 연동, night-mode QA 통합 (#618)
  ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

- **rule**: RuleContext 자산/노출 필드 추가 및 Treasury 조회 헬퍼 추출
  ([#713](https://github.com/joshua-jingu-lee/ante/pull/713),
  [`639bfc9`](https://github.com/joshua-jingu-lee/ante/commit/639bfc9d1ba2ec3513ff556e1e7c1f86a676058a))

- **skill**: QA 테스트 에이전트 스킬 작성 (.claude/skills/qa-tester/)
  ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

- **strategy**: Exchange 호환성 검증 추가 (#570)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **system**: 서버 시작 시 최신 버전 확인 로그 Refs #923
  ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **tc**: 대화형 설치 프로세스 검증 TC 추가 (install.feature)
  ([`8de7a59`](https://github.com/joshua-jingu-lee/ante/commit/8de7a59661e15255df08ce88deba95cecbad7f77))

- **tc**: 최초 설치 검증 TC 및 QA 환경 가이드 추가
  ([`8a673ff`](https://github.com/joshua-jingu-lee/ante/commit/8a673ff204295452aa48c2dfaea3cb2ad848330e))

- **trade**: DailyReportScheduler Account 기반 실행 시각 + DailyReportEvent 신설
  ([#683](https://github.com/joshua-jingu-lee/ante/pull/683),
  [`ffd7a68`](https://github.com/joshua-jingu-lee/ante/commit/ffd7a68e20da579626119815a54935e2974c1645))

- **trade**: TradeRecord·PositionSnapshot에 account_id, currency 필드 추가
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **treasury**: Treasury 계좌별 인스턴스 전환 및 TreasuryManager 도입
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **treasury**: Virtual 모드 자산 평가 동기화 — Trade DB 기반 계산 (#692)
  ([#693](https://github.com/joshua-jingu-lee/ante/pull/693),
  [`d4b3e7d`](https://github.com/joshua-jingu-lee/ante/commit/d4b3e7d9a1bf31cead4b345ac258095e2407bc08))

- **treasury**: 일별 자산 스냅샷 확장 — 성과 필드, 범위 조회, 자동 삭제 (#682)
  ([#686](https://github.com/joshua-jingu-lee/ante/pull/686),
  [`16c5788`](https://github.com/joshua-jingu-lee/ante/commit/16c57887ed7bd250c284424bbedc0ffaebd6aac0))

- **treasury**: 자금 거래내역 기간(날짜) 필터 추가 ([#904](https://github.com/joshua-jingu-lee/ante/pull/904),
  [`cd2f469`](https://github.com/joshua-jingu-lee/ante/commit/cd2f469d5de218bcafbfe75324b8477e0a0189ba))

- **update**: DB 안전 백업 함수 구현 Refs #916 ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **update**: 디스크 공간 사전 검사 Refs #922 ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **update**: 마이그레이션 실패 시 자동 롤백 Refs #918
  ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **update**: 업데이트 전 의존성 스냅샷 저장 Refs #921
  ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **web**: Account CRUD REST API 엔드포인트 추가 (#574)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **web**: Agent 토큰 인증 시 last_active_at 갱신 (5분 스로틀링)
  ([#604](https://github.com/joshua-jingu-lee/ante/pull/604),
  [`4a48b97`](https://github.com/joshua-jingu-lee/ante/commit/4a48b976275dbcc1c382390378d977698f4f0090))

- **web**: Agent 토큰 인증 시 last_active_at 갱신 미들웨어 추가
  ([#604](https://github.com/joshua-jingu-lee/ante/pull/604),
  [`4a48b97`](https://github.com/joshua-jingu-lee/ante/commit/4a48b976275dbcc1c382390378d977698f4f0090))

- **web**: GET /api/data/datasets/{dataset_id} 데이터셋 상세 API #799
  ([#830](https://github.com/joshua-jingu-lee/ante/pull/830),
  [`4319fe6`](https://github.com/joshua-jingu-lee/ante/commit/4319fe6768222600fc56da96da97415f8b598c02))

- **web**: GET /api/strategies 응답에 cumulative_return 추가 #800
  ([#830](https://github.com/joshua-jingu-lee/ante/pull/830),
  [`4319fe6`](https://github.com/joshua-jingu-lee/ante/commit/4319fe6768222600fc56da96da97415f8b598c02))

- **web**: GET /api/strategies/{id} 응답에 params, rationale, risks 추가 #802
  ([#830](https://github.com/joshua-jingu-lee/ante/pull/830),
  [`4319fe6`](https://github.com/joshua-jingu-lee/ante/commit/4319fe6768222600fc56da96da97415f8b598c02))

- **web**: GET/PUT /api/accounts/{id}/rules 리스크 룰 조회·수정 API #798
  ([#830](https://github.com/joshua-jingu-lee/ante/pull/830),
  [`4319fe6`](https://github.com/joshua-jingu-lee/ante/commit/4319fe6768222600fc56da96da97415f8b598c02))

- **web**: 기존 API 엔드포인트에 account_id 필터 및 응답 필드 추가 (#575)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **web**: 일별 자산 스냅샷 Web API 엔드포인트 (#684)
  ([#688](https://github.com/joshua-jingu-lee/ante/pull/688),
  [`272857f`](https://github.com/joshua-jingu-lee/ante/commit/272857fd62a75f077483b5311413cf8b0cd6685d))

- **web**: 일별 자산 스냅샷 Web API 엔드포인트 구현 ([#688](https://github.com/joshua-jingu-lee/ante/pull/688),
  [`272857f`](https://github.com/joshua-jingu-lee/ante/commit/272857fd62a75f077483b5311413cf8b0cd6685d))

### Performance Improvements

- **backtest**: Equity_curve 일봉 리샘플링으로 detail_json 저장 최적화 #741
  ([#762](https://github.com/joshua-jingu-lee/ante/pull/762),
  [`d5d96c5`](https://github.com/joshua-jingu-lee/ante/commit/d5d96c5d11632c629ed82597fe0814a6bc78f53e))

### Refactoring

- CLI 레퍼런스 출력 경로를 guide/cli.md로 일원화
  ([`3d17074`](https://github.com/joshua-jingu-lee/ante/commit/3d17074ad90a8aaf205eb82d2e0972646936e2dc))

- **account**: Account 모델에 broker_config 필드 추가
  ([#941](https://github.com/joshua-jingu-lee/ante/pull/941),
  [`ce4f312`](https://github.com/joshua-jingu-lee/ante/commit/ce4f312f77a56aea3e94a18a00cc9f862fce6d9e))

- **broker**: KISAdapter → KISBaseAdapter + KISDomesticAdapter 분리 (#561)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **cli**: Ante init 흐름에서 KIS 연동을 Account 등록으로 교체
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **cli**: Bot/Treasury 커맨드 IPC 전환 #697 ([#702](https://github.com/joshua-jingu-lee/ante/pull/702),
  [`bc7316b`](https://github.com/joshua-jingu-lee/ante/commit/bc7316b0d809cedeceb71b1a898bd76f73910a86))

- **cli**: CLI 레퍼런스 정렬을 알파벳순에서 등록순으로 변경
  ([`2d5fb24`](https://github.com/joshua-jingu-lee/ante/commit/2d5fb24a60d2605a9b1155fd5fd85ba3a7d56e63))

- **cli**: Config/Approval/Broker 커맨드 IPC 전환 및 IPC 헬퍼 통합 #698
  ([#703](https://github.com/joshua-jingu-lee/ante/pull/703),
  [`a61fc8c`](https://github.com/joshua-jingu-lee/ante/commit/a61fc8c8c16dca4a04ccfe5dd563a89f83452513))

- **cli**: System/Account 커맨드 IPC 전환 #696
  ([#701](https://github.com/joshua-jingu-lee/ante/pull/701),
  [`1449a20`](https://github.com/joshua-jingu-lee/ante/commit/1449a2030691b28a25edced7d5e7d422f174788c))

- **config**: Account 모델로 이관되는 broker 설정 키 제거
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **core**: SystemState 제거 및 Kill Switch를 Account.status 기반으로 일원화 (#568)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **db**: 기존 분산 _migrate_*() 메서드 제거 ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **frontend**: BacktestData 페이지 데이터 흐름 컨벤션 준수 (api → hooks → pages)
  ([#882](https://github.com/joshua-jingu-lee/ante/pull/882),
  [`3bbe5a8`](https://github.com/joshua-jingu-lee/ante/commit/3bbe5a8c331084546607e7ec7336ac9737b31de0))

- **frontend**: 라우팅·사이드바·대시보드 정리 (Phase 0) Refs #831
  ([#840](https://github.com/joshua-jingu-lee/ante/pull/840),
  [`8e95cf1`](https://github.com/joshua-jingu-lee/ante/commit/8e95cf1c25e48c88a3802188693612fd44edabc9))

- **gateway**: APIGateway 계좌 라우팅 전환 (#567)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **main**: Account 중심 Composition Root 재구성 (#578)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **rule**: Rule Engine 계좌별 인스턴스 전환 (#566)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **test**: E2E/Integration 테스트 인프라 및 Docker 테스트 설정 제거
  ([#609](https://github.com/joshua-jingu-lee/ante/pull/609),
  [`1072c26`](https://github.com/joshua-jingu-lee/ante/commit/1072c262bd7e170aefff20f3b8f4a75d8305a183))

- **test**: E2E/Integration 테스트 인프라 제거 ([#609](https://github.com/joshua-jingu-lee/ante/pull/609),
  [`1072c26`](https://github.com/joshua-jingu-lee/ante/commit/1072c262bd7e170aefff20f3b8f4a75d8305a183))

- **web**: Portfolio API에서 daily_pnl_pct 하위호환 필드 제거
  ([#689](https://github.com/joshua-jingu-lee/ante/pull/689),
  [`fbd6b3c`](https://github.com/joshua-jingu-lee/ante/commit/fbd6b3c3a9b4ba0a2007ef359a75afe524e58b14))

- **web**: 토큰 인증 last_active_at 갱신에 5분 스로틀링 추가
  ([#604](https://github.com/joshua-jingu-lee/ante/pull/604),
  [`4a48b97`](https://github.com/joshua-jingu-lee/ante/commit/4a48b976275dbcc1c382390378d977698f4f0090))

### Testing

- QA 테스트 케이스 추가 (approval, bot, data)
  ([`038d7e2`](https://github.com/joshua-jingu-lee/ante/commit/038d7e2ac5620e57fcdc5f414a8aefde38d66a38))

- **backtest**: Run() 실행 후 config/datasets 주입 검증 테스트 추가
  ([#734](https://github.com/joshua-jingu-lee/ante/pull/734),
  [`91c7e4e`](https://github.com/joshua-jingu-lee/ante/commit/91c7e4e1fbd56cc0f571a16df027c761bd1f209a))

- **bot**: _resolve_paper_balance 정상/KeyError 경로 테스트 추가
  ([#766](https://github.com/joshua-jingu-lee/ante/pull/766),
  [`b5c5d41`](https://github.com/joshua-jingu-lee/ante/commit/b5c5d4149fb44b818f8cdca9bed966e36737a05d))

- **rule**: RuleEngine WARN 결과 경로 단위 테스트 추가 #806
  ([#820](https://github.com/joshua-jingu-lee/ante/pull/820),
  [`730231e`](https://github.com/joshua-jingu-lee/ante/commit/730231ecb11612f27cbc8aa8bb577d9fdc8e8969))

- **tc**: Account 모듈 TC 확장 — lifecycle + credentials (#612)
  ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

- **tc**: Member 모듈 TC 작성 (auth + management)
  ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

- **tc**: Strategy + Config + Trade 모듈 TC 작성
  ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

- **tc**: Treasury 모듈 TC 작성 (balance + allocation) (#615)
  ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

- **tc**: 계좌 CRUD 파일럿 TC 작성 (account/crud.feature)
  ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))


## v0.6.1 (2026-03-19)

### Bug Fixes

- **build**: Pandas-ta 의존성 버전 스펙 수정
  ([`3bf9125`](https://github.com/joshua-jingu-lee/ante/commit/3bf91251c1d9d801ed6314121791c7cc6b247362))


## v0.6.0 (2026-03-19)

### Bug Fixes

- Asyncio.CancelledError 미재발생 버그 수정 (6건) ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- Display.currency_position 기본값 등록으로 설정 페이지 에러 해결
  ([`b62b59a`](https://github.com/joshua-jingu-lee/ante/commit/b62b59a7c454a475a3101ec0f2a04f23906bda69))

- Docker 시드 로딩 및 trade_id UUID 형식 수정
  ([`6dbed88`](https://github.com/joshua-jingu-lee/ante/commit/6dbed887a62512d95057facba6ab94e48a690139))

- 에픽 통합 테스트 실패 수정 ([#473](https://github.com/joshua-jingu-lee/ante/pull/473),
  [`64d10b7`](https://github.com/joshua-jingu-lee/ante/commit/64d10b7019ac85a2c6f82176c8d4243e83624de4))

- 전략 성과 API 경로를 실제 라우트와 일치하도록 수정 ([#395](https://github.com/joshua-jingu-lee/ante/pull/395),
  [`eac0340`](https://github.com/joshua-jingu-lee/ante/commit/eac034048f15b8f2066955db5c4a3a1a802eeb44))

- **api**: 백테스트 데이터 API 응답 형식·필드 불일치 수정
  ([`6c66b25`](https://github.com/joshua-jingu-lee/ante/commit/6c66b25847f5ee4f9bb8547806f5db6809f25407))

- **api**: 전략 상세 페이지 weekly-summary API 404 해소
  ([`f47ef69`](https://github.com/joshua-jingu-lee/ante/commit/f47ef6912146777a68fff230047b26acc90d3b8a))

- **bot**: 봇 시작 시 전략별 룰 로드, 중지 시 제거 (#498)
  ([#508](https://github.com/joshua-jingu-lee/ante/pull/508),
  [`4760f47`](https://github.com/joshua-jingu-lee/ante/commit/4760f477787622002d514f1e8837f3e8904cc9dd))

- **ci**: Dev 의존성에 httpx 추가
  ([`58431a4`](https://github.com/joshua-jingu-lee/ante/commit/58431a414ccde43bf4aaaa3fa4bf2582eaa0cfb6))

- **dashboard**: ApprovalType 확장에 따른 누락 엔트리 추가
  ([`2c992b3`](https://github.com/joshua-jingu-lee/ante/commit/2c992b3789d7360df046d6ee4a4dc5693e0af663))

- **dashboard**: 멤버 관리 비밀번호 변경 기능 구현
  ([`be46b6c`](https://github.com/joshua-jingu-lee/ante/commit/be46b6cbfeff616157afec907da0c4e68dab2b09))

- **dashboard**: 백테스트 데이터 페이지 CLI 안내 문구를 `ante feed`로 수정
  ([`e923432`](https://github.com/joshua-jingu-lee/ante/commit/e923432152b41f80fa014af2a33448b14c8e6edf))

- **dashboard**: 사이드바 목업 충실도 미세 조정
  ([`14ec6be`](https://github.com/joshua-jingu-lee/ante/commit/14ec6bedc1da7149b45309169d54bc0b060f51a4))

- **dashboard**: 사이드바 버전을 pyproject.toml에서 빌드 타임 주입
  ([`fc4b3dc`](https://github.com/joshua-jingu-lee/ante/commit/fc4b3dc4faccb7cd8d55cc5cf94103cb0208f022))

- **dashboard**: 에이전트 등록 시 member_type 필드 누락 수정
  ([`cdbb90e`](https://github.com/joshua-jingu-lee/ante/commit/cdbb90e48ef61d45b6713ccb6d1414e18ab5800b))

- **instrument**: 부동소수점 동등 비교를 math.isclose()로 교체
  ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **logging**: Except-pass 7건에 logger.warning 추가
  ([#544](https://github.com/joshua-jingu-lee/ante/pull/544),
  [`cc5014f`](https://github.com/joshua-jingu-lee/ante/commit/cc5014f54e48b60f3ed370e455e1edeb1cf277ce))

- **main**: NotificationService 초기화 코드 정리
  ([#502](https://github.com/joshua-jingu-lee/ante/pull/502),
  [`7cb6183`](https://github.com/joshua-jingu-lee/ante/commit/7cb6183b94137106c04057f5013708ea7611219e))

- **member**: Revoke 시 상태 검증 누락 수정 ([#506](https://github.com/joshua-jingu-lee/ante/pull/506),
  [`afeb63d`](https://github.com/joshua-jingu-lee/ante/commit/afeb63de391874c90a1f3983960564f5ac17c178))

- **rule**: ConfigChangedEvent 수신 시 전역/전략 룰 실제 재로드
  ([#507](https://github.com/joshua-jingu-lee/ante/pull/507),
  [`513ccef`](https://github.com/joshua-jingu-lee/ante/commit/513ccef116d73a569878d4ea48b2e1b136fd18b3))

- **scripts**: Click 8.2+ Sentinel.UNSET 호환성 수정
  ([`1a5b6de`](https://github.com/joshua-jingu-lee/ante/commit/1a5b6deb2de8d0960794c1bdd92e5cfe473d15cf))

- **telegram**: /bots 응답 메시지를 스펙(bot.md)에 맞게 수정
  ([#556](https://github.com/joshua-jingu-lee/ante/pull/556),
  [`2d93a65`](https://github.com/joshua-jingu-lee/ante/commit/2d93a65cafc30c62eb99a10a4e4c1dd89e4eb98d))

- **telegram**: /halt 응답 메시지를 스펙에 맞게 수정 (#540)
  ([#556](https://github.com/joshua-jingu-lee/ante/pull/556),
  [`2d93a65`](https://github.com/joshua-jingu-lee/ante/commit/2d93a65cafc30c62eb99a10a4e4c1dd89e4eb98d))

- **test**: CI에서 scripts/ 모듈 import 실패 수정
  ([`c3928c0`](https://github.com/joshua-jingu-lee/ante/commit/c3928c0948d87067332f7c25f451b46656337641))

- **test**: CLI 서브커맨드 docstring 누락 방지 회귀 테스트 추가 (#494)
  ([#511](https://github.com/joshua-jingu-lee/ante/pull/511),
  [`9f9fbe6`](https://github.com/joshua-jingu-lee/ante/commit/9f9fbe65d2b7da19ff0d0b26ef6b07666b1e06eb))

### Documentation

- HTTPException 응답을 OpenAPI 스펙에 문서화 ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

### Features

- 각 모듈에 NotificationEvent 발행 추가 (16건) ([#502](https://github.com/joshua-jingu-lee/ante/pull/502),
  [`7cb6183`](https://github.com/joshua-jingu-lee/ante/commit/7cb6183b94137106c04057f5013708ea7611219e))

- **approval**: Suppress_notification 파라미터 추가 (#516)
  ([#555](https://github.com/joshua-jingu-lee/ante/pull/555),
  [`eafcb29`](https://github.com/joshua-jingu-lee/ante/commit/eafcb29c90ba01be96aac7a956ab8ae34105c9af))

- **approval**: 결재 executor 8건 등록 ([#463](https://github.com/joshua-jingu-lee/ante/pull/463),
  [`72bbe14`](https://github.com/joshua-jingu-lee/ante/commit/72bbe1477f04d168c51d173702938191a5c26c3e))

- **approval**: 결재 만료 스케줄러 구현 ([#473](https://github.com/joshua-jingu-lee/ante/pull/473),
  [`64d10b7`](https://github.com/joshua-jingu-lee/ante/commit/64d10b7019ac85a2c6f82176c8d4243e83624de4))

- **approval**: 결재 사전 검증(validator) 구현 ([#473](https://github.com/joshua-jingu-lee/ante/pull/473),
  [`64d10b7`](https://github.com/joshua-jingu-lee/ante/commit/64d10b7019ac85a2c6f82176c8d4243e83624de4))

- **approval**: 결재 실행 실패 상태(EXECUTION_FAILED) 구현
  ([#473](https://github.com/joshua-jingu-lee/ante/pull/473),
  [`64d10b7`](https://github.com/joshua-jingu-lee/ante/commit/64d10b7019ac85a2c6f82176c8d4243e83624de4))

- **approval**: 결재 재상신(reopen) 구현 ([#473](https://github.com/joshua-jingu-lee/ante/pull/473),
  [`64d10b7`](https://github.com/joshua-jingu-lee/ante/commit/64d10b7019ac85a2c6f82176c8d4243e83624de4))

- **approval**: 결재 전결(자동 승인) 구현 ([#464](https://github.com/joshua-jingu-lee/ante/pull/464),
  [`3b8aeaf`](https://github.com/joshua-jingu-lee/ante/commit/3b8aeafcb8825e3fe8e99a02681dbc135f9a0061))

- **audit**: 감사 로그 기록 연동 — Web API + CLI ([#478](https://github.com/joshua-jingu-lee/ante/pull/478),
  [`c6e4acc`](https://github.com/joshua-jingu-lee/ante/commit/c6e4acca00a7102dba4affb8e1961821b5bae50c))

- **audit**: 감사 로그 보존 기간 정책(retention) 구현
  ([#478](https://github.com/joshua-jingu-lee/ante/pull/478),
  [`c6e4acc`](https://github.com/joshua-jingu-lee/ante/commit/c6e4acca00a7102dba4affb8e1961821b5bae50c))

- **audit**: 감사 로그 조회 필터 확장 — 날짜 필터 + limit 클램핑
  ([#478](https://github.com/joshua-jingu-lee/ante/pull/478),
  [`c6e4acc`](https://github.com/joshua-jingu-lee/ante/commit/c6e4acca00a7102dba4affb8e1961821b5bae50c))

- **backtest**: 백테스트→리포트 DRAFT 자동 생성 플로우 구현 (#493)
  ([#512](https://github.com/joshua-jingu-lee/ante/pull/512),
  [`6cc068b`](https://github.com/joshua-jingu-lee/ante/commit/6cc068bd06e45d48e749aef0101bf41d32701d9e))

- **bot**: BotManager 전략 배정/변경/재개 메서드 구현 ([#463](https://github.com/joshua-jingu-lee/ante/pull/463),
  [`72bbe14`](https://github.com/joshua-jingu-lee/ante/commit/72bbe1477f04d168c51d173702938191a5c26c3e))

- **bot**: Stop_bot()에 suppress_notification 파라미터 추가 (#518)
  ([#555](https://github.com/joshua-jingu-lee/ante/pull/555),
  [`eafcb29`](https://github.com/joshua-jingu-lee/ante/commit/eafcb29c90ba01be96aac7a956ab8ae34105c9af))

- **broker**: Broker.type 설정 기반 KIS ↔ Test 브로커 전환
  ([#454](https://github.com/joshua-jingu-lee/ante/pull/454),
  [`492cc2e`](https://github.com/joshua-jingu-lee/ante/commit/492cc2eb3febfdfaf57806fb8424adc305399045))

- **broker**: PriceSimulator — GBM 기반 가격 시뮬레이션 엔진
  ([#454](https://github.com/joshua-jingu-lee/ante/pull/454),
  [`492cc2e`](https://github.com/joshua-jingu-lee/ante/commit/492cc2eb3febfdfaf57806fb8424adc305399045))

- **broker**: ReconcileScheduler — 주기적 자동 대사 스케줄러 구현
  ([#481](https://github.com/joshua-jingu-lee/ante/pull/481),
  [`4475caa`](https://github.com/joshua-jingu-lee/ante/commit/4475caa22d29bbeb711a5fad3c9f4fbf036543c8))

- **broker**: TestBrokerAdapter — 개발/검증용 테스트 브로커 구현
  ([#454](https://github.com/joshua-jingu-lee/ante/pull/454),
  [`492cc2e`](https://github.com/joshua-jingu-lee/ante/commit/492cc2eb3febfdfaf57806fb8424adc305399045))

- **broker**: 브로커 메타정보(이름, 거래소) 동적 표출 ([#381](https://github.com/joshua-jingu-lee/ante/pull/381),
  [`342cac0`](https://github.com/joshua-jingu-lee/ante/commit/342cac082e9554f49d9dc73eff5752ac5a6d1f30))

- **cli**: `ante strategy submit` 커맨드 구현 (#500)
  ([#510](https://github.com/joshua-jingu-lee/ante/pull/510),
  [`9335331`](https://github.com/joshua-jingu-lee/ante/commit/9335331cc1a278e4763262cb70b198cb7317468b))

- **cli**: Ante strategy list/info/performance 커맨드 구현
  ([#505](https://github.com/joshua-jingu-lee/ante/pull/505),
  [`aba8e18`](https://github.com/joshua-jingu-lee/ante/commit/aba8e189a11e7e883a0bf1187471a3739b7e82f7))

- **cli**: Ante system start/stop — CLI 시스템 시작·종료 커맨드 구현
  ([#482](https://github.com/joshua-jingu-lee/ante/pull/482),
  [`a18af9a`](https://github.com/joshua-jingu-lee/ante/commit/a18af9a4b51376d5a83d05a17657d06fa2172a3a))

- **cli**: Click introspection 기반 CLI 레퍼런스 문서 자동 생성
  ([#395](https://github.com/joshua-jingu-lee/ante/pull/395),
  [`eac0340`](https://github.com/joshua-jingu-lee/ante/commit/eac034048f15b8f2066955db5c4a3a1a802eeb44))

- **config**: SystemState.set_state()에 suppress_notification 옵션 추가
  ([#555](https://github.com/joshua-jingu-lee/ante/pull/555),
  [`eafcb29`](https://github.com/joshua-jingu-lee/ante/commit/eafcb29c90ba01be96aac7a956ab8ae34105c9af))

- **dashboard**: Feed 상태 및 API 키 현황 UI 추가
  ([#367](https://github.com/joshua-jingu-lee/ante/pull/367),
  [`2306318`](https://github.com/joshua-jingu-lee/ante/commit/2306318260a4783f34e9e13fe5ee49559552a58c))

- **data**: 백테스트 데이터 API에 fundamental 데이터 유형 지원 추가
  ([`aa6ce56`](https://github.com/joshua-jingu-lee/ante/commit/aa6ce560f85de97bcd8f42a6cadda0816eb6758d))

- **eventbus**: SystemStartedEvent 도메인 이벤트 추가
  ([#552](https://github.com/joshua-jingu-lee/ante/pull/552),
  [`732175d`](https://github.com/joshua-jingu-lee/ante/commit/732175d224ac42602e8de65ff9023b0cd75936e9))

- **frontend**: Openapi-typescript 기반 프론트엔드 타입 자동 생성 파이프라인
  ([#395](https://github.com/joshua-jingu-lee/ante/pull/395),
  [`eac0340`](https://github.com/joshua-jingu-lee/ante/commit/eac034048f15b8f2066955db5c4a3a1a802eeb44))

- **gateway**: KISStreamClient ↔ APIGateway 실시간 시세 연동
  ([#479](https://github.com/joshua-jingu-lee/ante/pull/479),
  [`90ace1f`](https://github.com/joshua-jingu-lee/ante/commit/90ace1fdae2c29194e9a065ff3543a1a62305be4))

- **gateway**: LiveDataProvider.get_ohlcv() ParquetStore 연동
  ([#480](https://github.com/joshua-jingu-lee/ante/pull/480),
  [`ec1688e`](https://github.com/joshua-jingu-lee/ante/commit/ec1688eaa3f95de193223adb1c4940d00870e106))

- **notification**: Quiet_hours 동적 설정 연동 (#532)
  ([#553](https://github.com/joshua-jingu-lee/ante/pull/553),
  [`0844354`](https://github.com/joshua-jingu-lee/ante/commit/0844354b47edd612cb93913c11c29a877d8ead7d))

- **notification**: Telegram 결재 연동 — 인라인 버튼 + 명령어
  ([#473](https://github.com/joshua-jingu-lee/ante/pull/473),
  [`64d10b7`](https://github.com/joshua-jingu-lee/ante/commit/64d10b7019ac85a2c6f82176c8d4243e83624de4))

- **seed**: Python 시드 데이터 생성기 구현
  ([`4ceb010`](https://github.com/joshua-jingu-lee/ante/commit/4ceb0103094cbce83b02237d655650c90e27dba5))

- **telegram**: /activate 응답 메시지 스펙 적용 ([#556](https://github.com/joshua-jingu-lee/ante/pull/556),
  [`2d93a65`](https://github.com/joshua-jingu-lee/ante/commit/2d93a65cafc30c62eb99a10a4e4c1dd89e4eb98d))

- **telegram**: /balance 응답을 스펙 상세 형식으로 확장
  ([#514](https://github.com/joshua-jingu-lee/ante/pull/514),
  [`aba6679`](https://github.com/joshua-jingu-lee/ante/commit/aba6679c64aec849aaac59227935b823f9cc0706))

- **telegram**: /stop 응답 메시지를 스펙(bot.md) 기준으로 확장
  ([#556](https://github.com/joshua-jingu-lee/ante/pull/556),
  [`2d93a65`](https://github.com/joshua-jingu-lee/ante/commit/2d93a65cafc30c62eb99a10a4e4c1dd89e4eb98d))

- **telegram**: 명령 호출부에 suppress_notification=True 전달 (#519)
  ([#555](https://github.com/joshua-jingu-lee/ante/pull/555),
  [`eafcb29`](https://github.com/joshua-jingu-lee/ante/commit/eafcb29c90ba01be96aac7a956ab8ae34105c9af))

- **trade**: 장 마감 후 일일 성과 요약 알림 스케줄러 구현 (#503)
  ([#513](https://github.com/joshua-jingu-lee/ante/pull/513),
  [`8519a27`](https://github.com/joshua-jingu-lee/ante/commit/8519a275c60610d9250d6d607adc052b0e5145a2))

- **treasury,rule**: Treasury.update_budget() 및 RuleEngine.update_rules() 구현
  ([#463](https://github.com/joshua-jingu-lee/ante/pull/463),
  [`72bbe14`](https://github.com/joshua-jingu-lee/ante/commit/72bbe1477f04d168c51d173702938191a5c26c3e))

- **web**: 전 엔드포인트 response_model 추가 ([#396](https://github.com/joshua-jingu-lee/ante/pull/396),
  [`791be60`](https://github.com/joshua-jingu-lee/ante/commit/791be60a240eb0145410292ff92030177140c6fa))

- **web**: 전 엔드포인트 response_model 추가 및 OpenAPI 스키마 정비
  ([#395](https://github.com/joshua-jingu-lee/ante/pull/395),
  [`eac0340`](https://github.com/joshua-jingu-lee/ante/commit/eac034048f15b8f2066955db5c4a3a1a802eeb44))

### Refactoring

- FeedOrchestrator God Class 분해 ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- Main.py Composition Root 분리 ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- 문자열 리터럴 상수 추출 (S1192) ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- 불필요한 async 함수 정리 (#418) ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **approval**: Create()/approve() 메서드 분할 및 executor 중복 제거 (#523)
  ([#544](https://github.com/joshua-jingu-lee/ante/pull/544),
  [`cc5014f`](https://github.com/joshua-jingu-lee/ante/commit/cc5014f54e48b60f3ed370e455e1edeb1cf277ce))

- **broker**: KIS 어댑터 _request() 관심사 분리 ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **broker**: Realtime_price_stream/realtime_order_stream 스펙 아웃 제거
  ([#544](https://github.com/joshua-jingu-lee/ante/pull/544),
  [`cc5014f`](https://github.com/joshua-jingu-lee/ante/commit/cc5014f54e48b60f3ed370e455e1edeb1cf277ce))

- **cli**: Config_get() 인지 복잡도 개선 (CC 13 → 3)
  ([#544](https://github.com/joshua-jingu-lee/ante/pull/544),
  [`cc5014f`](https://github.com/joshua-jingu-lee/ante/commit/cc5014f54e48b60f3ed370e455e1edeb1cf277ce))

- **cli**: Rule enable/disable 커맨드 제거 ([#509](https://github.com/joshua-jingu-lee/ante/pull/509),
  [`a7a0365`](https://github.com/joshua-jingu-lee/ante/commit/a7a0365d1aba628580a2d0e9cfe2d63cef7668d2))

- **cli**: Strategy_info() 인지 복잡도 감소 (CC 14 → 7)
  ([#544](https://github.com/joshua-jingu-lee/ante/pull/544),
  [`cc5014f`](https://github.com/joshua-jingu-lee/ante/commit/cc5014f54e48b60f3ed370e455e1edeb1cf277ce))

- **data**: RetentionPolicy.enforce() CC 감소를 위한 메서드 분리
  ([#544](https://github.com/joshua-jingu-lee/ante/pull/544),
  [`cc5014f`](https://github.com/joshua-jingu-lee/ante/commit/cc5014f54e48b60f3ed370e455e1edeb1cf277ce))

- **data**: Store.write() CC 13→4로 분리 ([#544](https://github.com/joshua-jingu-lee/ante/pull/544),
  [`cc5014f`](https://github.com/joshua-jingu-lee/ante/commit/cc5014f54e48b60f3ed370e455e1edeb1cf277ce))

- **events**: NotificationEvent 필드 재설계 — title/category/buttons 추가
  ([#502](https://github.com/joshua-jingu-lee/ante/pull/502),
  [`7cb6183`](https://github.com/joshua-jingu-lee/ante/commit/7cb6183b94137106c04057f5013708ea7611219e))

- **feed**: BackfillRunner.run docstring 축소로 함수 50줄 제한 충족
  ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **feed**: FeedOrchestrator God Class 분해
  ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **feed**: Validate_business 복잡도 개선 — 검증 규칙별 함수 분리
  ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **feed**: 스케줄러 루프 및 출력 로직을 독립 모듈로 분리 ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **main**: _init_broker 중첩 깊이 3단계 이하로 축소
  ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **main**: _init_feed에서 ApprovalService 초기화를 _init_approval로 분리
  ([#544](https://github.com/joshua-jingu-lee/ante/pull/544),
  [`cc5014f`](https://github.com/joshua-jingu-lee/ante/commit/cc5014f54e48b60f3ed370e455e1edeb1cf277ce))

- **main**: Composition Root을 독립 초기화 함수로 분리
  ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **member**: MemberService 관심사 분리 (AuthService, TokenManager, RecoveryKeyManager)
  ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **notification**: Notification_history 관련 코드 전량 제거
  ([#502](https://github.com/joshua-jingu-lee/ante/pull/502),
  [`7cb6183`](https://github.com/joshua-jingu-lee/ante/commit/7cb6183b94137106c04057f5013708ea7611219e))

- **notification**: NotificationService 단일 핸들러 통합
  ([#502](https://github.com/joshua-jingu-lee/ante/pull/502),
  [`7cb6183`](https://github.com/joshua-jingu-lee/ante/commit/7cb6183b94137106c04057f5013708ea7611219e))

- **notification**: 중앙 템플릿 파일 삭제 ([#502](https://github.com/joshua-jingu-lee/ante/pull/502),
  [`7cb6183`](https://github.com/joshua-jingu-lee/ante/commit/7cb6183b94137106c04057f5013708ea7611219e))

- **schemas**: Extra="allow" 주석 추가 및 response_model 정합성 테스트
  ([`8b22160`](https://github.com/joshua-jingu-lee/ante/commit/8b221600ad01b5b338300e1d4e50f2539e0415c2))

- **schemas**: Response model 내부 dict[str, Any]를 구체 Pydantic 모델로 전환
  ([#467](https://github.com/joshua-jingu-lee/ante/pull/467),
  [`adb5dfc`](https://github.com/joshua-jingu-lee/ante/commit/adb5dfcb96d45ea981748e39f7999d647f17bc3f))

- **strategy**: TA-Lib → pandas-ta 전환 및 LiveDataProvider 지표 계산 구현
  ([#457](https://github.com/joshua-jingu-lee/ante/pull/457),
  [`96f9778`](https://github.com/joshua-jingu-lee/ante/commit/96f97787ab764d1ca248ac9b7e91d0b3733b5e5c))

- **web**: 라우트 의존성 주입 전환 + Annotated 타입 힌트 적용
  ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))


## v0.4.1 (2026-03-17)

### Bug Fixes

- 미사용 BacktestMetrics 컴포넌트 삭제 및 unused import 제거
  ([`672f7d6`](https://github.com/joshua-jingu-lee/ante/commit/672f7d62749a1faa72b8acca263743d3e0f3576d))


## v0.4.0 (2026-03-17)

### Features

- **봇 관리**: 봇 상세 예산 카드·보유종목 테이블 데이터 연동
  ([`736d492`](https://github.com/joshua-jingu-lee/ante/commit/736d492))
- **봇 관리**: 봇 카드 UI 개선 — 로봇 아이콘 애니메이션, 실행간격 표시
  ([`dc0b438`](https://github.com/joshua-jingu-lee/ante/commit/dc0b438))
- **봇 관리**: 봇 상세 UI 보강 — 뒤로가기, stopped 상태 헤더, 설정 수정 모달
  ([`cfbbd22`](https://github.com/joshua-jingu-lee/ante/commit/cfbbd22))
- **봇 관리**: 봇 생성 모달 개선 — 전략 셀렉트, 힌트 텍스트, 입력 검증
  ([`d886602`](https://github.com/joshua-jingu-lee/ante/commit/d886602))
- **봇 관리**: 봇 중지/삭제 모달 구현 — 보유종목별 분기, 포지션 처리 옵션
  ([`096d8d3`](https://github.com/joshua-jingu-lee/ante/commit/096d8d3))
- **결재함**: 결재 유형 enum을 백엔드/스펙 기준으로 수정
  ([`e0aaa91`](https://github.com/joshua-jingu-lee/ante/commit/e0aaa91))
- **결재함**: 결재함 목록 필터를 목업 기준으로 개선
  ([`722694f`](https://github.com/joshua-jingu-lee/ante/commit/722694f))
- **결재함**: 결재 상세 공통 레이아웃 및 유형별 실행 내용 구현
  ([`71d3069`](https://github.com/joshua-jingu-lee/ante/commit/71d3069))
- **결재함**: 결재 상세 본문 마크다운 렌더링 구현
  ([`c12f164`](https://github.com/joshua-jingu-lee/ante/commit/c12f164))
- **결재함**: 결재 승인/거부 확인 모달 구현
  ([`cb6c646`](https://github.com/joshua-jingu-lee/ante/commit/cb6c646))
- **리포트**: 리포트 상세 페이지 및 API 엔드포인트 구현
  ([`38c8a4f`](https://github.com/joshua-jingu-lee/ante/commit/38c8a4f))
- **자금관리**: Bot 예산 비중 파이 차트 구현
  ([`2a9a390`](https://github.com/joshua-jingu-lee/ante/commit/2a9a390))
- **자금관리**: Bot당 예산 테이블 보강 — 보유종목 데이터 연동, 컬럼 재구성
  ([`6fc5fbb`](https://github.com/joshua-jingu-lee/ante/commit/6fc5fbb))
- **멤버 관리**: Human 멤버 카드 보강 — 역할 뱃지, 왕관 표시, 액션 버튼
  ([`c6b01d4`](https://github.com/joshua-jingu-lee/ante/commit/c6b01d4))
- **멤버 관리**: 멤버 관리 상태 필터 탭 구현 및 소속 필터 위치 수정
  ([`4d25ee6`](https://github.com/joshua-jingu-lee/ante/commit/4d25ee6))
- **설정**: HALTED 정지 시각·사유 표시 및 금액 단위 토글 구현
  ([`b05a25b`](https://github.com/joshua-jingu-lee/ante/commit/b05a25b))
- **KIS**: KIS 계좌 헤더 보강 — 계좌번호, 모의투자 뱃지, 동기화 상태
  ([`e94a451`](https://github.com/joshua-jingu-lee/ante/commit/e94a451))

### Bug Fixes

- **백테스트**: 백테스트 데이터 페이지네이션·용량 정보 레이아웃 수정
  ([`b80d0a2`](https://github.com/joshua-jingu-lee/ante/commit/b80d0a2))
- **백테스트**: 백테스트 데이터 카드 레이아웃·배너·필터 목업 불일치 수정
  ([`f771c5b`](https://github.com/joshua-jingu-lee/ante/commit/f771c5b))
- **백테스트**: 백테스트 데이터 삭제 모달 목업 불일치 수정
  ([`34f8b68`](https://github.com/joshua-jingu-lee/ante/commit/34f8b68))
- **멤버 관리**: 멤버 관리 revoked 스타일 및 상세 브레드크럼 추가
  ([`3347717`](https://github.com/joshua-jingu-lee/ante/commit/3347717))
- **멤버 관리**: 멤버 관리 라우트·타이틀·라벨 목업 불일치 수정
  ([`026be4c`](https://github.com/joshua-jingu-lee/ante/commit/026be4c))
- **자금관리**: 자금 변동 이력 페이지네이션 스타일 및 타이틀 수정
  ([`b0a4a3c`](https://github.com/joshua-jingu-lee/ante/commit/b0a4a3c))
- **설정**: 설정 거래 모드 뱃지 및 거래 설정 버튼 방식 수정
  ([`dfa24ba`](https://github.com/joshua-jingu-lee/ante/commit/dfa24ba))

### Tests

- E2E 시나리오 추가 및 색상 수정 (자금관리, 멤버관리, 백테스트, 설정)
  ([`df165e6`](https://github.com/joshua-jingu-lee/ante/commit/df165e6))
- 봇 관리 E2E 시나리오를 목업 기준으로 보강
  ([`69bedec`](https://github.com/joshua-jingu-lee/ante/commit/69bedec))
- 결재함/리포트 상세 E2E 시나리오 초안 작성
  ([`e43662b`](https://github.com/joshua-jingu-lee/ante/commit/e43662b))


## v0.3.2 (2026-03-17)

### Bug Fixes

- **frontend**: 봇 목록/상세/생성 폼에 name 필드 추가
  ([`001260c`](https://github.com/joshua-jingu-lee/ante/commit/001260c))
- **frontend**: 봇 관리 페이지를 카드 레이아웃으로 변경하고 섹션 구분 추가
  ([`ea4ddcb`](https://github.com/joshua-jingu-lee/ante/commit/ea4ddcb))
- **frontend**: 전략 목록에 제출자 컬럼 및 페이지네이션 추가
  ([`1daffa6`](https://github.com/joshua-jingu-lee/ante/commit/1daffa6))
- **frontend**: 전략 상세 페이지 목업 대비 UI 괴리 개선
  ([`5e0adea`](https://github.com/joshua-jingu-lee/ante/commit/5e0adea))
- **frontend**: 봇 상세 페이지 목업 대비 UI 괴리 개선
  ([`f33b7c2`](https://github.com/joshua-jingu-lee/ante/commit/f33b7c2))
- **frontend**: 결재함 목업 대비 UI 괴리 개선
  ([`74f5194`](https://github.com/joshua-jingu-lee/ante/commit/74f5194))
- **frontend**: 멤버 관리 UI를 목업 기준으로 개선
  ([`570f477`](https://github.com/joshua-jingu-lee/ante/commit/570f477))
- **treasury**: 자금관리 UI를 목업 기준으로 전면 개선
  ([`5a255cc`](https://github.com/joshua-jingu-lee/ante/commit/5a255cc))
- **frontend**: 설정 페이지를 목업 기준으로 개선
  ([`e033ff7`](https://github.com/joshua-jingu-lee/ante/commit/e033ff7))
- **frontend**: 백테스트 데이터 저장소 용량 상세 + 타임프레임 한글 라벨
  ([`34c8738`](https://github.com/joshua-jingu-lee/ante/commit/34c8738))


## v0.3.1 (2026-03-16)

### Bug Fixes

- **frontend**: 전략 상세 페이지 성과 데이터 없을 때 빈 상태 메시지 추가
  ([`ea60387`](https://github.com/joshua-jingu-lee/ante/commit/ea60387b53d17b665790a828fc2ad3ce6d47e511))


## v0.2.0 (2026-03-16)

### Chores

- GitHub Issue 템플릿 추가 (feature, bug, refactor)
  ([`348905c`](https://github.com/joshua-jingu-lee/ante/commit/348905c31ef1006db19ef218330c2517c2bde04f))

### Continuous Integration

- Release 워크플로우에 Docker 이미지 빌드 + ghcr.io push 추가
  ([`08a4b7c`](https://github.com/joshua-jingu-lee/ante/commit/08a4b7c0147176da038bc12a20895c6b389eb1f9))

### Features

- Docker 지원 추가 (multi-stage 빌드 + docker-compose)
  ([`75f950a`](https://github.com/joshua-jingu-lee/ante/commit/75f950a09dbaa41fe0b6849f70ac291097ef3ec5))


## v0.1.0 (2026-03-16)

- Initial Release
