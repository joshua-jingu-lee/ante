"""FillDedupGuard — 인메모리 bounded 체결 멱등 가드 (#1957).

#1949 outbox 가 ``OrderFilledEvent`` 를 at-least-once(무손실) 로 재전달하고
결정적 ``fill_dedup_key`` 를 제공한다. EventBus 는 fire-and-forget(핸들러 예외
swallow, 재시도 없음)이라 재전달 시 비멱등 소비자가 같은 fill 을 이중 처리한다.

Treasury 는 전용 DB 테이블(``treasury_fill_dedup``)로 진짜 exactly-once-effect
를 보장하지만, Bot/SignalChannel/TradeRecorder 의 효과(전략 follow-up, 외부 JSON
write, NotificationEvent 재발행)는 **bounded best-effort dedup** 으로 충분하다.
세 소비자가 동일 로직을 중복 구현하지 않도록 이 헬퍼로 추출한다.

한계 (known-limitation, #1957 Stop Conditions):
  - 프로세스 메모리 가드라 **재기동 시 소실** — 재기동 직후 catch_up 재전달은
    이중 처리될 수 있다.
  - ``deque(maxlen)`` 윈도우를 벗어난(긴 시간차) 재전달은 식별하지 못한다.
DB-persisted exactly-once 로의 승격은 #1957 비목표(follow-up 후보).
"""

from __future__ import annotations

from collections import deque

# bounded 윈도우 크기. catch_up 재전달 윈도우는 미발행 outbox 누적분으로 작아
# 기본 512 로 충분하다(#1957 설계 결정 4). 초과 시 가장 오래된 키부터 evict 된다.
DEFAULT_FILL_DEDUP_MAXLEN = 512


class FillDedupGuard:
    """체결 멱등을 위한 인메모리 bounded 가드.

    ``deque(maxlen)`` 이 FIFO 윈도우를, ``set`` 이 O(1) 멤버십을 담당한다. deque
    가 maxlen 초과로 키를 evict 하면 set 미러도 동기화해 두 자료구조가 항상
    같은 집합을 표현한다.
    """

    def __init__(self, maxlen: int = DEFAULT_FILL_DEDUP_MAXLEN) -> None:
        self._order: deque[str] = deque(maxlen=maxlen)
        self._seen: set[str] = set()

    def seen_or_add(self, key: str) -> bool:
        """키를 원자적으로 검사+추가한다.

        이미 처리된 키면 ``True`` (소비자는 effect 를 skip), 처음 보는 키면
        가드에 추가한 뒤 ``False`` (소비자는 처리 진행)를 반환한다.

        **await 없는 동기 원자 구간**이다(#1957 Codex 노트). EventBus 핸들러가
        ``await`` 사이에 인터리브되며 같은 키를 동시에 검사하는 race 를 막으려면
        검사와 추가가 같은 이벤트 루프 틱 안에서 끊김 없이 일어나야 한다. 따라서
        본 메서드는 코루틴이 아니며 내부에서 ``await`` 하지 않는다.
        """
        if key in self._seen:
            return True
        # maxlen 초과 시 deque 가 좌측(가장 오래된) 키를 자동 evict 하므로,
        # append 전에 evict 될 키를 미리 계산해 set 미러를 동기화한다.
        if self._order.maxlen is not None and len(self._order) >= self._order.maxlen:
            evicted = self._order[0]
            self._seen.discard(evicted)
        self._order.append(key)
        self._seen.add(key)
        return False
