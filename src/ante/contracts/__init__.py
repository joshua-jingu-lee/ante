"""Contract SSOT 공통 인프라.

이 package는 CLI(#1815)/IPC(#1819) 계열 contract surface가
공유할 vocabulary 등 공통 정의의 SSOT 위치다.

본 패키지 초기 버전(#1822)은 vocabulary 정의(``ante.contracts.vocab``)만
포함하며, package marker 역할만 한다. alias re-export는 의도적으로 하지
않는다 -- 소비자는 `from ante.contracts.vocab import ...` 형태로
명시 import하여, vocabulary 위치가 단일 SSOT로 고정되도록 한다.
"""
