"""ante.feed — DataFeed 모듈 공개 API."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ante.feed.config import FeedConfig

if TYPE_CHECKING:
    from ante.feed.injector import FeedInjector

__all__ = ["FeedConfig", "FeedInjector"]


def __getattr__(name: str):  # noqa: ANN001, ANN202
    if name == "FeedInjector":
        from ante.feed.injector import FeedInjector

        return FeedInjector
    raise AttributeError(f"module 'ante.feed' has no attribute {name!r}")
