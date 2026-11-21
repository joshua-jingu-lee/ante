"""FillDedupGuard — 인메모리 bounded 체결 멱등 가드."""

from __future__ import annotations

from collections import deque

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

    def __contains__(self, key: str) -> bool:
        """read-only 멤버십 검사 (INV-OUT-4).

        ``seen_or_add`` 와 달리 가드 상태를 **변경하지 않는다**. SignalChannel
        ``_on_fill`` 가 enqueue **전** dedup 게이트로 비-커밋 검사를 하기 위한
        seam 이다 — full-drop(enqueue 실패) 시 키를 마킹하지 않아 다음 재전달이
        보존되도록 하려면, 검사 시점에는 커밋하지 않고 ``_emit`` 성공 **후**
        별도로 ``seen_or_add`` 를 호출해야 한다(dedup-mark-after-enqueue).

        ``await`` 없는 동기 read 이며 ``self._seen`` 멤버십만 조회한다.
        """
        return key in self._seen

    def seen_or_add(self, key: str) -> bool:
        """키를 원자적으로 검사+추가한다.

        이미 처리된 키면 ``True`` (소비자는 effect 를 skip), 처음 보는 키면
        가드에 추가한 뒤 ``False`` (소비자는 처리 진행)를 반환한다.

        **await 없는 동기 원자 구간**이다. EventBus 핸들러가
        ``await`` 사이에 인터리브되며 같은 키를 동시에 검사하는 race 를 막으려면
        검사와 추가가 같은 이벤트 루프 틱 안에서 끊김 없이 일어나야 한다. 따라서
        본 메서드는 코루틴이 아니며 내부에서 ``await`` 하지 않는다.
        """
        if key in self._seen:
            return True
        if self._order.maxlen is not None and len(self._order) >= self._order.maxlen:
            evicted = self._order[0]
            self._seen.discard(evicted)
        self._order.append(key)
        self._seen.add(key)
        return False
