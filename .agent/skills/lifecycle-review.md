# 수명주기 리뷰 스킬

> 캐시, 세션, 연결, long-lived adapter, mutable config가 포함된 변경을 리뷰할 때 사용한다.

## 언제 읽나

- `credentials`, `broker_config`, API client 설정, 토큰, endpoint 변경
- 캐시 invalidate / refresh / clear / pop
- 연결 객체 재사용
- background task, polling, retry worker, health/readiness 경로

## 핵심 질문

1. 설정이 바뀐 뒤 **이미 살아 있는 객체**는 어떻게 되는가
2. 캐시를 지운 뒤 **다음 호출**은 무엇을 보장하는가
3. 재생성만 되고 재연결은 안 되는 경로가 있는가
4. 변경된 객체를 소비하는 호출자들이 새 계약을 그대로 만족하는가

## 체크리스트

- 캐시 무효화 뒤 새 객체가 생성되는가
- 새 객체가 필요한 초기화 / connect / authenticate를 다시 수행하는가
- 이전 객체가 남긴 리소스가 누수되지 않는가
- health / readiness / first request 경로가 새 설정을 반영하는가
- "다음 호출부터 바로 반영"이 필요한 설정이 실제로 그렇게 동작하는가
- 이 불변식을 지키는 회귀 테스트가 있는가

## red flags

- `dict.pop()` 또는 cache clear만 있고 재초기화 경로가 보이지 않는다
- config 저장은 되는데 adapter reconnect가 없다
- 호출자는 그대로인데 내부 객체 생명주기만 바뀐다
- 테스트가 저장 성공만 보고 실제 후속 호출까지 보지 않는다
