from __future__ import annotations

from cw_platform.history_events import history_sync_key
from providers.sync.plex import _history as history


def _episode(episode: int) -> dict:
    return {
        "type": "episode",
        "series_title": "Silo",
        "show_ids": {"imdb": "tt14688458"},
        "season": 3,
        "episode": episode,
        "watched_at": "2026-08-08T18:11:00Z",
    }


def _catalog() -> history.HistoryCatalog:
    catalog = history.HistoryCatalog()
    catalog.guid_complete = True
    catalog.episode_complete = True
    catalog.add(
        {
            "rk": "show-1",
            "type": "show",
            "ids": {"imdb": "tt14688458"},
        }
    )
    catalog.add(
        {
            "rk": "episode-1",
            "type": "episode",
            "show_rk": "show-1",
            "show_ids": {"imdb": "tt14688458"},
            "season": 3,
            "episode": 1,
            "watched": False,
        }
    )
    return catalog


def test_filter_add_candidates_keeps_only_items_present_in_plex(
    monkeypatch,
) -> None:
    catalog = _catalog()
    monkeypatch.setattr(history, "_get_history_catalog", lambda *_a, **_k: catalog)
    monkeypatch.setattr(history, "_populate_catalog_episode_leaves", lambda *_a, **_k: 0)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())

    result = history.filter_add_candidates(object(), [_episode(1), _episode(2)])

    assert [item["episode"] for item in result["items"]] == [1]
    assert result["skipped_count"] == 1
    assert result["reason_counts"] == {"show_matched_episode_missing": 1}
    assert history_sync_key(result["skipped"][0]["item"]) == "imdb:tt14688458#s03e02"


def test_filter_add_candidates_rechecks_items_when_library_changes(
    monkeypatch,
) -> None:
    catalog = _catalog()
    monkeypatch.setattr(history, "_get_history_catalog", lambda *_a, **_k: catalog)
    monkeypatch.setattr(history, "_populate_catalog_episode_leaves", lambda *_a, **_k: 0)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())

    first = history.filter_add_candidates(object(), [_episode(2)])
    assert first["items"] == []

    catalog.add(
        {
            "rk": "episode-2",
            "type": "episode",
            "show_rk": "show-1",
            "show_ids": {"imdb": "tt14688458"},
            "season": 3,
            "episode": 2,
            "watched": False,
        }
    )

    second = history.filter_add_candidates(object(), [_episode(2)])
    assert [item["episode"] for item in second["items"]] == [2]
    assert second["skipped_count"] == 0


def test_filter_add_candidates_keeps_ambiguous_items_for_real_resolution(
    monkeypatch,
) -> None:
    class _AmbiguousCatalog:
        def resolve(self, _item, *, strict=False):
            return None, history.CLASS_RESOLVE_AMBIGUOUS

    monkeypatch.setattr(history, "_get_history_catalog", lambda *_a, **_k: _AmbiguousCatalog())
    monkeypatch.setattr(history, "_populate_catalog_episode_leaves", lambda *_a, **_k: 0)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())

    item = _episode(1)
    result = history.filter_add_candidates(object(), [item])

    assert result["items"] == [item]
    assert result["skipped_count"] == 0


def test_filter_add_candidates_fails_open_when_episode_catalog_is_incomplete(
    monkeypatch,
) -> None:
    catalog = _catalog()
    catalog.episode_complete = False
    monkeypatch.setattr(history, "_get_history_catalog", lambda *_a, **_k: catalog)
    monkeypatch.setattr(history, "_populate_catalog_episode_leaves", lambda *_a, **_k: 0)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())

    item = _episode(2)
    result = history.filter_add_candidates(object(), [item])

    assert result["items"] == [item]
    assert result["skipped_count"] == 0


def test_filter_add_candidates_fails_open_when_guid_catalog_is_incomplete(
    monkeypatch,
) -> None:
    catalog = history.HistoryCatalog()
    monkeypatch.setattr(history, "_get_history_catalog", lambda *_a, **_k: catalog)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())
    item = {"type": "movie", "ids": {"imdb": "tt0000001"}}

    result = history.filter_add_candidates(object(), [item])

    assert result["items"] == [item]
    assert result["skipped_count"] == 0


def test_guid_page_failure_marks_catalog_incomplete() -> None:
    class _Response:
        ok = True
        headers = {"content-type": "application/json"}

        def json(self):
            return {
                "MediaContainer": {
                    "Metadata": [{"ratingKey": "1", "Guid": [{"id": "imdb://tt0000001"}]}],
                    "totalSize": 2,
                }
            }

    class _Session:
        headers = {}

        def __init__(self) -> None:
            self.calls = 0

        def get(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("later page failed")
            return _Response()

    class _Server:
        baseurl = "http://plex.local:32400"
        token = "token"

        def __init__(self) -> None:
            self._session = _Session()

    rows, requests_made, complete = history._fetch_section_guid_rows(_Server(), "1", 1)

    assert [row["ratingKey"] for row in rows] == ["1"]
    assert requests_made == 1
    assert complete is False
