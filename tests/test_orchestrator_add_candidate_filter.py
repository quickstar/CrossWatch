from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

import pytest

from cw_platform.id_map import canonical_key
from cw_platform.orchestrator.facade import Orchestrator
from cw_platform.orchestrator._pairs_oneway import filter_destination_add_candidates


def _items() -> list[dict]:
    return [
        {"type": "movie", "ids": {"imdb": "tt0000001"}},
        {"type": "movie", "ids": {"imdb": "tt0000002"}},
    ]


def test_destination_filter_reports_expected_skips() -> None:
    class _Ops:
        def filter_add_candidates(self, _cfg, *, feature, items):
            assert feature == "history"
            rows = list(items)
            return {
                "items": rows[:1],
                "skipped_count": 1,
                "reason_counts": {"not_in_target_catalog": 1},
            }

    events: list[tuple[str, dict]] = []
    kept, skipped, skipped_items = filter_destination_add_candidates(
        _Ops(),
        cfg={},
        feature="history",
        items=_items(),
        emit=lambda event, **data: events.append((event, data)),
        dbg=lambda *_a, **_k: None,
        dst_name="PLEX",
    )

    assert kept == _items()[:1]
    assert skipped == 1
    assert skipped_items == []
    assert events == [
        (
            "add_candidates:filtered",
            {
                "dst": "PLEX",
                "feature": "history",
                "before": 2,
                "after": 1,
                "skipped": 1,
                "reason_counts": {"not_in_target_catalog": 1},
            },
        )
    ]


def test_destination_filter_trusts_explicit_skip_count() -> None:
    class _Ops:
        def filter_add_candidates(self, _cfg, *, feature, items):
            rows = list(items)
            return {"items": rows[:1], "skipped_count": 0}

    events: list[tuple[str, dict]] = []
    kept, skipped, skipped_items = filter_destination_add_candidates(
        _Ops(),
        cfg={},
        feature="history",
        items=_items(),
        emit=lambda event, **data: events.append((event, data)),
        dbg=lambda *_a, **_k: None,
        dst_name="PLEX",
    )

    assert kept == _items()[:1]
    assert skipped == 0
    assert skipped_items == []
    assert events == []


def test_destination_filter_rejects_injected_candidates() -> None:
    class _Ops:
        def filter_add_candidates(self, _cfg, *, feature, items):
            return {
                "items": [{"type": "movie", "ids": {"imdb": "tt9999999"}}],
                "skipped_count": 1,
            }

    debug: list[tuple[tuple, dict]] = []
    kept, skipped, skipped_items = filter_destination_add_candidates(
        _Ops(),
        cfg={},
        feature="history",
        items=_items(),
        emit=lambda *_a, **_k: None,
        dbg=lambda *args, **kwargs: debug.append((args, kwargs)),
        dst_name="PLEX",
    )

    assert kept == _items()
    assert skipped == 0
    assert skipped_items == []
    assert debug[0][0] == ("add_candidates.filter_invalid_subset",)


def test_destination_filter_fails_open() -> None:
    class _Ops:
        def filter_add_candidates(self, _cfg, *, feature, items):
            raise RuntimeError("catalog unavailable")

    debug: list[tuple[tuple, dict]] = []
    kept, skipped, skipped_items = filter_destination_add_candidates(
        _Ops(),
        cfg={},
        feature="history",
        items=_items(),
        emit=lambda *_a, **_k: None,
        dbg=lambda *args, **kwargs: debug.append((args, kwargs)),
        dst_name="PLEX",
    )

    assert kept == _items()
    assert skipped == 0
    assert skipped_items == []
    assert debug[0][0] == ("add_candidates.filter_failed",)


@dataclass
class _HistoryOps:
    provider: str
    index: dict[str, dict[str, Any]]
    keep_first: bool = False
    add_calls: list[list[dict[str, Any]]] = field(default_factory=list)

    def name(self) -> str:
        return self.provider

    def label(self) -> str:
        return self.provider

    def features(self) -> Mapping[str, bool]:
        return {"history": True}

    def capabilities(self) -> Mapping[str, Any]:
        return {"bidirectional": True, "history": {"index_semantics": "present"}}

    def is_configured(self, _cfg: Mapping[str, Any]) -> bool:
        return True

    def health(self, _cfg: Mapping[str, Any], **_kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "status": "ok", "features": {"history": True}, "api": {}}

    def build_index(self, _cfg: Mapping[str, Any], *, feature: str):
        assert feature == "history"
        return dict(self.index)

    def filter_add_candidates(self, _cfg, *, feature, items):
        rows = list(items)
        if not self.keep_first:
            return {"items": rows}
        return {
            "items": rows[:1],
            "skipped": [{"item": item, "reason": "not_in_target_catalog"} for item in rows[1:]],
            "skipped_count": len(rows[1:]),
            "reason_counts": {"not_in_target_catalog": len(rows[1:])},
        }

    def add(self, _cfg, items: Iterable[Mapping[str, Any]], *, feature: str, dry_run=False):
        batch = [dict(item) for item in items]
        self.add_calls.append(batch)
        keys = [canonical_key(item) for item in batch]
        return {"ok": True, "count": len(batch), "confirmed_keys": [key for key in keys if key]}

    def remove(self, _cfg, items, *, feature: str, dry_run=False):
        return {"ok": True, "count": 0, "confirmed_keys": []}


@pytest.mark.parametrize("dry_run,clears_existing", [(False, True), (True, False)])
def test_orchestrator_applies_only_destination_candidates(
    config_base: Any,
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
    clears_existing: bool,
) -> None:
    src = _HistoryOps(
        "SRC",
        {
            "imdb:tt0000001": {
                "type": "movie",
                "ids": {"imdb": "tt0000001"},
                "watched_at": "2026-08-08T10:00:00Z",
            },
            "imdb:tt0000002": {
                "type": "movie",
                "ids": {"imdb": "tt0000002"},
                "watched_at": "2026-08-08T11:00:00Z",
            },
        },
    )
    dst = _HistoryOps("DST", {}, keep_first=True)
    cleared: list[tuple[str, str, list[str]]] = []
    monkeypatch.setattr(
        "cw_platform.orchestrator.facade.load_sync_providers",
        lambda: {"SRC": src, "DST": dst},
    )
    monkeypatch.setattr(
        "cw_platform.orchestrator._snapshots.provider_configured",
        lambda _cfg, _name: True,
    )
    monkeypatch.setattr(
        "cw_platform.orchestrator._pairs_oneway.clear_unresolved",
        lambda dst_name, feature, keys: (
            cleared.append((dst_name, feature, list(keys)))
            or {"ok": True, "count": len(list(keys))}
        ),
    )

    result = Orchestrator(
        {
            "runtime": {"snapshot_ttl_sec": 0},
            "sync": {"enable_add": True, "enable_remove": False},
            "pairs": [
                {
                    "id": "history-filter",
                    "enabled": True,
                    "source": "SRC",
                    "target": "DST",
                    "mode": "one-way",
                    "feature": "history",
                    "features": {"history": {"enable": True, "add": True, "remove": False}},
                }
            ],
        }
    ).run(dry_run=dry_run, write_state_json=False)

    assert result["added"] == (0 if dry_run else 1)
    assert result["skipped"] == 1
    assert len(dst.add_calls) == 1
    assert [item["ids"]["imdb"] for item in dst.add_calls[0]] == ["tt0000001"]
    filtered_clear = ("DST", "history", ["imdb:tt0000002"])
    if clears_existing:
        assert filtered_clear in cleared
    else:
        assert filtered_clear not in cleared


def test_bidirectional_orchestrator_applies_destination_candidates(
    config_base: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = _HistoryOps(
        "SRC",
        {
            "imdb:tt0000001": {
                "type": "movie",
                "ids": {"imdb": "tt0000001"},
                "watched_at": "2026-08-08T10:00:00Z",
            },
            "imdb:tt0000002": {
                "type": "movie",
                "ids": {"imdb": "tt0000002"},
                "watched_at": "2026-08-08T11:00:00Z",
            },
        },
    )
    dst = _HistoryOps("DST", {}, keep_first=True)
    monkeypatch.setattr(
        "cw_platform.orchestrator.facade.load_sync_providers",
        lambda: {"SRC": src, "DST": dst},
    )
    monkeypatch.setattr(
        "cw_platform.orchestrator._snapshots.provider_configured",
        lambda _cfg, _name: True,
    )

    result = Orchestrator(
        {
            "runtime": {"snapshot_ttl_sec": 0},
            "sync": {"enable_add": True, "enable_remove": False},
            "pairs": [
                {
                    "id": "history-filter-two-way",
                    "enabled": True,
                    "source": "SRC",
                    "target": "DST",
                    "mode": "two-way",
                    "feature": "history",
                    "features": {"history": {"enable": True, "add": True, "remove": False}},
                }
            ],
        }
    ).run(write_state_json=False)

    assert result["added"] == 1
    assert result["skipped"] == 1
    assert [item["ids"]["imdb"] for item in dst.add_calls[0]] == ["tt0000001"]
    assert src.add_calls == []
