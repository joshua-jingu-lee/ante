"""KIS get_order_history fold + 실체결가 매핑 테스트 (#1946 R1-4).

- 체결가 = 체결금액/체결수량 (ord_unpr 주문가 아님).
- 같은 odno 여러 row → max 누적 + 최신 평균가로 fold.
- broker_order_id(odno)/cumulative/avg/영업일(ord_dt) 반환 포함.
"""

from __future__ import annotations

from ante.broker.kis import KISDomesticAdapter

_fold = KISDomesticAdapter._fold_order_history


def test_fill_price_uses_executed_amount_not_order_price():
    """체결가 = tot_ccld_amt / tot_ccld_qty (ord_unpr 주문가가 아님)."""
    rows = [
        {
            "odno": "0001",
            "pdno": "005930",
            "sll_buy_dvsn_cd": "02",
            "ord_qty": "100",
            "tot_ccld_qty": "100",
            "tot_ccld_amt": "1010000",  # 실체결 평균 10100원.
            "ord_unpr": "10000",  # 주문가 10000원 — 쓰면 안 됨.
            "ord_dt": "20260529",
        }
    ]
    folded = _fold(rows)
    assert len(folded) == 1
    item = folded[0]
    assert item["order_id"] == "0001"
    assert item["filled_quantity"] == 100.0
    assert item["price"] == 10100.0  # 1010000 / 100, NOT 10000.
    assert item["side"] == "buy"
    assert item["timestamp"] == "20260529"


def test_fill_price_falls_back_to_avg_prvs():
    """tot_ccld_amt 없으면 avg_prvs(평균체결가) fallback."""
    rows = [
        {
            "odno": "0001",
            "tot_ccld_qty": "50",
            "tot_ccld_amt": "0",
            "avg_prvs": "9900",
            "ord_unpr": "10000",
            "ord_dt": "20260529",
            "sll_buy_dvsn_cd": "01",
        }
    ]
    folded = _fold(rows)
    assert folded[0]["price"] == 9900.0
    assert folded[0]["side"] == "sell"


def test_fill_price_falls_back_to_order_price_when_no_fill():
    """체결금액·평균가 모두 없으면 ord_unpr."""
    rows = [
        {
            "odno": "0001",
            "tot_ccld_qty": "0",
            "tot_ccld_amt": "0",
            "avg_prvs": "0",
            "ord_unpr": "10000",
            "ord_dt": "20260529",
            "sll_buy_dvsn_cd": "02",
        }
    ]
    folded = _fold(rows)
    assert folded[0]["price"] == 10000.0
    assert folded[0]["filled_quantity"] == 0.0
    assert folded[0]["status"] == "pending"


def test_fold_partial_rows_takes_max_cumulative():
    """같은 odno 부분체결 여러 row → max 누적 체결qty + 해당(최신) row 가격."""
    rows = [
        {
            "odno": "0001",
            "tot_ccld_qty": "40",
            "tot_ccld_amt": "400000",  # 10000
            "ord_unpr": "10000",
            "ord_qty": "100",
            "ord_dt": "20260529",
            "sll_buy_dvsn_cd": "02",
            "pdno": "005930",
        },
        {
            "odno": "0001",
            "tot_ccld_qty": "100",  # 누적 더 큼 — 이 row 채택.
            "tot_ccld_amt": "1020000",  # 10200
            "ord_unpr": "10000",
            "ord_qty": "100",
            "ord_dt": "20260529",
            "sll_buy_dvsn_cd": "02",
            "pdno": "005930",
        },
    ]
    folded = _fold(rows)
    assert len(folded) == 1
    assert folded[0]["filled_quantity"] == 100.0
    assert folded[0]["price"] == 10200.0  # 1020000 / 100.


def test_fold_unordered_partial_rows():
    """row 순서가 역순(큰 누적이 먼저)이어도 max 누적 채택."""
    rows = [
        {
            "odno": "0001",
            "tot_ccld_qty": "100",
            "tot_ccld_amt": "1020000",
            "ord_dt": "20260529",
            "sll_buy_dvsn_cd": "02",
        },
        {
            "odno": "0001",
            "tot_ccld_qty": "40",
            "tot_ccld_amt": "400000",
            "ord_dt": "20260529",
            "sll_buy_dvsn_cd": "02",
        },
    ]
    folded = _fold(rows)
    assert len(folded) == 1
    assert folded[0]["filled_quantity"] == 100.0
    assert folded[0]["price"] == 10200.0


def test_fold_separates_by_odno_and_date():
    """다른 odno 또는 다른 영업일은 별도 항목으로 분리."""
    rows = [
        {
            "odno": "0001",
            "tot_ccld_qty": "10",
            "tot_ccld_amt": "100000",
            "ord_dt": "20260529",
            "sll_buy_dvsn_cd": "02",
        },
        {
            "odno": "0002",
            "tot_ccld_qty": "20",
            "tot_ccld_amt": "200000",
            "ord_dt": "20260529",
            "sll_buy_dvsn_cd": "02",
        },
        {
            "odno": "0001",
            "tot_ccld_qty": "5",
            "tot_ccld_amt": "50000",
            "ord_dt": "20260528",
            "sll_buy_dvsn_cd": "02",
        },
    ]
    folded = _fold(rows)
    keys = {(f["order_id"], f["timestamp"]) for f in folded}
    assert keys == {("0001", "20260529"), ("0002", "20260529"), ("0001", "20260528")}


def test_fold_skips_rows_without_odno():
    rows = [{"odno": "", "tot_ccld_qty": "10", "ord_dt": "20260529"}]
    assert _fold(rows) == []


def test_fold_empty():
    assert _fold([]) == []
