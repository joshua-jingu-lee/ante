# CHANGELOG

<!-- version list -->

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
