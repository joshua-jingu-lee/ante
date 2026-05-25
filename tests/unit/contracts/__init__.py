"""Contract drift test helpers (Refs #1823).

이 패키지는 #1815/#1816/#1818/#1819 후속 epic에서 사용할 공통 helper만
제공한다. 본 패키지는 실제 drift policy/assertion 을 포함하지 않는다 —
helper API skeleton 과 그 helper 자체 unit test만 둔다.

Helper 분류:

- import 기반: Click leaf command iterator, IPC ``CommandRegistry`` spec
  iterator. live runtime service 초기화나 DB 접근 없이 module import 만으로
  동작한다.
- AST/텍스트 기반: ``*Error`` class iterator, ``fmt.error(...)`` callsite
  iterator. production module import 를 피하기 위해 file text 를
  ``ast.parse`` 한다.
"""
