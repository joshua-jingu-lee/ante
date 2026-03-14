"""StrategySnapshot 단위 테스트."""

import pytest

from ante.strategy.snapshot import StrategySnapshot


@pytest.fixture
def strategies_dir(tmp_path):
    """임시 strategies 디렉토리."""
    d = tmp_path / "strategies"
    d.mkdir()
    return d


@pytest.fixture
def snapshot(strategies_dir):
    return StrategySnapshot(strategies_dir)


@pytest.fixture
def strategy_file(strategies_dir):
    """테스트용 전략 파일."""
    f = strategies_dir / "my_strategy.py"
    f.write_text("class MyStrategy: pass\n")
    return f


def test_create_copies_file(snapshot, strategy_file):
    """스냅샷 생성 시 파일이 복사된다."""
    result = snapshot.create("bot-1", strategy_file)

    assert result.exists()
    assert result.name == "my_strategy.py"
    assert result.read_text() == strategy_file.read_text()
    assert ".running" in str(result)
    assert "bot-1" in str(result)


def test_create_preserves_original(snapshot, strategy_file):
    """스냅샷 생성 후 원본은 그대로 유지된다."""
    snapshot.create("bot-1", strategy_file)
    assert strategy_file.exists()
    assert strategy_file.read_text() == "class MyStrategy: pass\n"


def test_snapshot_isolated_from_original_change(snapshot, strategy_file):
    """스냅샷 생성 후 원본 수정이 스냅샷에 영향 주지 않음."""
    snapshot_path = snapshot.create("bot-1", strategy_file)

    # 원본 수정
    strategy_file.write_text("class ModifiedStrategy: pass\n")

    assert snapshot_path.read_text() == "class MyStrategy: pass\n"


def test_cleanup_removes_bot_dir(snapshot, strategy_file):
    """cleanup 시 봇의 스냅샷 디렉토리가 삭제된다."""
    snapshot_path = snapshot.create("bot-1", strategy_file)
    bot_dir = snapshot_path.parent

    snapshot.cleanup("bot-1")

    assert not bot_dir.exists()


def test_cleanup_nonexistent_bot(snapshot):
    """존재하지 않는 봇 cleanup은 에러 없이 통과."""
    snapshot.cleanup("nonexistent")  # 에러 없이 통과


def test_cleanup_all(snapshot, strategy_file):
    """cleanup_all은 모든 봇 스냅샷을 정리한다."""
    snapshot.create("bot-1", strategy_file)
    snapshot.create("bot-2", strategy_file)

    count = snapshot.cleanup_all()

    assert count == 2
    running_dir = snapshot._running_dir
    # .running 디렉토리 자체는 남아있지만 하위 봇 디렉토리는 없음
    remaining = list(running_dir.iterdir()) if running_dir.exists() else []
    assert len(remaining) == 0


def test_cleanup_all_empty(snapshot):
    """스냅샷이 없으면 cleanup_all은 0 반환."""
    count = snapshot.cleanup_all()
    assert count == 0


def test_get_snapshot_path(snapshot, strategy_file):
    """스냅샷 경로 조회."""
    expected = snapshot.create("bot-1", strategy_file)
    result = snapshot.get_snapshot_path("bot-1")
    assert result == expected


def test_get_snapshot_path_nonexistent(snapshot):
    """존재하지 않는 봇은 None 반환."""
    assert snapshot.get_snapshot_path("nonexistent") is None


def test_multiple_bots_isolated(snapshot, strategy_file):
    """서로 다른 봇의 스냅샷은 독립적이다."""
    path1 = snapshot.create("bot-1", strategy_file)
    path2 = snapshot.create("bot-2", strategy_file)

    assert path1 != path2
    assert path1.parent != path2.parent

    snapshot.cleanup("bot-1")
    assert not path1.exists()
    assert path2.exists()
