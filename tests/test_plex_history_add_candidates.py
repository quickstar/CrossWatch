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


def test_filter_add_candidates_enters_and_exits_selected_user_scope(monkeypatch) -> None:
    catalog = _catalog()
    events: list[str] = []

    monkeypatch.setattr(
        history,
        "home_scope_enter",
        lambda _adapter: (events.append("enter") or (True, True, 42, "shared")),
    )
    monkeypatch.setattr(
        history,
        "_get_history_catalog",
        lambda *_a, **_k: (events.append("catalog") or catalog),
    )
    monkeypatch.setattr(
        history,
        "home_scope_exit",
        lambda _adapter, switched: events.append(f"exit:{switched}"),
    )
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())

    result = history.filter_add_candidates(object(), [_episode(1)])

    assert result["items"] == [_episode(1)]
    assert events == ["enter", "catalog", "exit:True"]


def test_filter_add_candidates_fails_open_when_selected_user_scope_cannot_apply(monkeypatch) -> None:
    monkeypatch.setattr(
        history,
        "home_scope_enter",
        lambda _adapter: (True, False, 42, "shared"),
    )

    def unexpected_catalog(*_args, **_kwargs):
        raise AssertionError("catalog must not scan the token owner's libraries")

    monkeypatch.setattr(history, "_get_history_catalog", unexpected_catalog)
    item = _episode(1)

    result = history.filter_add_candidates(object(), [item])

    assert result == {"items": [item], "skipped_count": 0, "reason_counts": {}}


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


def test_filter_add_candidates_refreshes_catalog_before_dropping_movie(monkeypatch) -> None:
    cached = history.HistoryCatalog()
    cached.guid_complete = True
    refreshed = history.HistoryCatalog()
    refreshed.guid_complete = True
    refreshed.add(
        {
            "rk": "movie-1",
            "type": "movie",
            "ids": {"imdb": "tt0000001"},
        }
    )
    calls: list[bool] = []

    def get_catalog(_adapter, _allow, *, force=False):
        calls.append(force)
        return refreshed if force else cached

    monkeypatch.setattr(history, "_get_history_catalog", get_catalog)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())
    monkeypatch.setitem(history._CATALOG_CACHE, "miss_refresh_ts", 0.0)
    item = {"type": "movie", "ids": {"imdb": "tt0000001"}}

    result = history.filter_add_candidates(object(), [item])

    assert result["items"] == [item]
    assert result["skipped_count"] == 0
    assert calls == [False, True]


def test_filter_add_candidates_refreshes_guid_catalog_for_episode(monkeypatch) -> None:
    cached = history.HistoryCatalog()
    cached.guid_complete = True
    refreshed = history.HistoryCatalog()
    refreshed.guid_complete = True
    refreshed.add({"rk": "show-1", "type": "show", "ids": {"tvdb": "81797"}})
    calls: list[bool] = []

    def get_catalog(_adapter, _allow, *, force=False):
        calls.append(force)
        return refreshed if force else cached

    def populate(_adapter, _allow, catalog):
        catalog.add(
            {
                "rk": "episode-1",
                "type": "episode",
                "show_rk": "show-1",
                "show_ids": {"tvdb": "81797"},
                "season": 1,
                "episode": 1,
            }
        )
        catalog.episode_complete = True
        return 1

    monkeypatch.setattr(history, "_get_history_catalog", get_catalog)
    monkeypatch.setattr(history, "_populate_catalog_episode_leaves", populate)
    monkeypatch.setattr(history, "_store_history_catalog", lambda *_a, **_k: None)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())
    monkeypatch.setitem(history._CATALOG_CACHE, "miss_refresh_ts", 0.0)
    item = {
        "type": "episode",
        "show_ids": {"tvdb": "81797"},
        "season": 1,
        "episode": 1,
    }

    result = history.filter_add_candidates(object(), [item])

    assert result["items"] == [item]
    assert result["skipped_count"] == 0
    assert calls == [False, True]


def test_filter_add_candidates_refreshes_complete_catalog_for_missing_episode(monkeypatch) -> None:
    cached = _catalog()
    refreshed = history.HistoryCatalog()
    refreshed.guid_complete = True
    refreshed.add({"rk": "show-1", "type": "show", "ids": {"imdb": "tt14688458"}})
    calls: list[bool] = []

    def get_catalog(_adapter, _allow, *, force=False):
        calls.append(force)
        return refreshed if force else cached

    def populate(_adapter, _allow, catalog):
        catalog.add(
            {
                "rk": "episode-2",
                "type": "episode",
                "show_rk": "show-1",
                "show_ids": {"imdb": "tt14688458"},
                "season": 3,
                "episode": 2,
            }
        )
        catalog.episode_complete = True
        return 1

    monkeypatch.setattr(history, "_get_history_catalog", get_catalog)
    monkeypatch.setattr(history, "_populate_catalog_episode_leaves", populate)
    monkeypatch.setattr(history, "_store_history_catalog", lambda *_a, **_k: None)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())
    monkeypatch.setitem(history._CATALOG_CACHE, "miss_refresh_ts", 0.0)

    result = history.filter_add_candidates(object(), [_episode(2)])

    assert result["items"] == [_episode(2)]
    assert result["skipped_count"] == 0
    assert calls == [False, True]


def test_filter_add_candidates_reuses_complete_catalog_for_known_episode(monkeypatch) -> None:
    catalog = _catalog()

    def unexpected_scan(*_args, **_kwargs):
        raise AssertionError("unexpected episode scan")

    monkeypatch.setattr(history, "_get_history_catalog", lambda *_a, **_k: catalog)
    monkeypatch.setattr(history, "_populate_catalog_episode_leaves", unexpected_scan)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())

    result = history.filter_add_candidates(object(), [_episode(1)])

    assert result["items"] == [_episode(1)]
    assert result["skipped_count"] == 0


def test_filter_add_candidates_reuses_complete_catalog_for_missing_episode(monkeypatch) -> None:
    catalog = _catalog()

    def unexpected_scan(*_args, **_kwargs):
        raise AssertionError("unexpected episode scan")

    monkeypatch.setattr(history, "_get_history_catalog", lambda *_a, **_k: catalog)
    monkeypatch.setattr(history, "_populate_catalog_episode_leaves", unexpected_scan)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())

    first = history.filter_add_candidates(object(), [_episode(2)])
    second = history.filter_add_candidates(object(), [_episode(2)])

    assert first["items"] == []
    assert second["items"] == []


def test_filter_add_candidates_keeps_movie_resolvable_by_plex_rating_key(monkeypatch) -> None:
    catalog = history.HistoryCatalog()
    catalog.guid_complete = True
    catalog.add({"rk": "123", "type": "movie", "ids": {"imdb": "tt0000001"}})
    monkeypatch.setattr(history, "_get_history_catalog", lambda *_a, **_k: catalog)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())
    item = {"type": "movie", "ids": {"plex": "123"}}

    result = history.filter_add_candidates(object(), [item])

    assert result["items"] == [item]
    assert result["skipped_count"] == 0


def test_filter_add_candidates_keeps_idless_movie_for_title_fallback(monkeypatch) -> None:
    catalog = history.HistoryCatalog()
    catalog.guid_complete = True
    monkeypatch.setattr(history, "_get_history_catalog", lambda *_a, **_k: catalog)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())
    monkeypatch.setattr(history, "plex_cfg_get", lambda *_a, **_k: False)
    item = {"type": "movie", "title": "Arrival", "year": 2016, "ids": {}}

    result = history.filter_add_candidates(object(), [item])

    assert result["items"] == [item]
    assert result["skipped_count"] == 0


def test_filter_add_candidates_keeps_id_bearing_movie_for_title_fallback(monkeypatch) -> None:
    catalog = history.HistoryCatalog()
    catalog.guid_complete = True
    monkeypatch.setattr(history, "_get_history_catalog", lambda *_a, **_k: catalog)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())
    monkeypatch.setattr(history, "plex_cfg_get", lambda *_a, **_k: False)
    item = {
        "type": "movie",
        "title": "Arrival",
        "year": 2016,
        "ids": {"imdb": "tt9999999"},
    }

    result = history.filter_add_candidates(object(), [item])

    assert result["items"] == [item]
    assert result["skipped_count"] == 0


def test_filter_add_candidates_keeps_episode_for_series_title_fallback(monkeypatch) -> None:
    catalog = history.HistoryCatalog()
    catalog.guid_complete = True
    catalog.episode_complete = True
    monkeypatch.setattr(history, "_get_history_catalog", lambda *_a, **_k: catalog)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())
    monkeypatch.setattr(history, "plex_cfg_get", lambda *_a, **_k: False)
    item = {
        "type": "episode",
        "series_title": "Silo",
        "show_ids": {"imdb": "tt9999999"},
        "season": 1,
        "episode": 2,
    }

    result = history.filter_add_candidates(object(), [item])

    assert result["items"] == [item]
    assert result["skipped_count"] == 0


def test_filter_add_candidates_keeps_episode_resolvable_by_plex_rating_key(monkeypatch) -> None:
    catalog = history.HistoryCatalog()
    catalog.guid_complete = True
    catalog.episode_complete = True
    catalog.add({"rk": "456", "type": "episode", "season": 1, "episode": 2})
    monkeypatch.setattr(history, "_get_history_catalog", lambda *_a, **_k: catalog)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())
    item = {"type": "episode", "ids": {"plex": "456"}, "season": 1, "episode": 2}

    result = history.filter_add_candidates(object(), [item])

    assert result["items"] == [item]
    assert result["skipped_count"] == 0


def test_filter_add_candidates_keeps_episode_resolvable_by_episode_guid(monkeypatch) -> None:
    catalog = history.HistoryCatalog()
    catalog.guid_complete = True
    catalog.episode_complete = True
    catalog.add(
        {
            "rk": "456",
            "type": "episode",
            "ids": {"imdb": "tt12345678"},
            "show_ids": {"imdb": "tt87654321"},
            "season": 1,
            "episode": 2,
        }
    )
    monkeypatch.setattr(history, "_get_history_catalog", lambda *_a, **_k: catalog)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())
    item = {
        "type": "episode",
        "ids": {"imdb": "tt12345678"},
        "season": 1,
        "episode": 2,
    }

    result = history.filter_add_candidates(object(), [item])

    assert result["items"] == [item]
    assert result["skipped_count"] == 0


def test_filter_add_candidates_throttles_forced_refresh_for_persistent_miss(monkeypatch) -> None:
    catalog = history.HistoryCatalog()
    catalog.guid_complete = True
    calls: list[bool] = []

    def get_catalog(_adapter, _allow, *, force=False):
        calls.append(force)
        return catalog

    monkeypatch.setattr(history, "_get_history_catalog", get_catalog)
    monkeypatch.setattr(history, "_catalog_cache_key", lambda *_a, **_k: "catalog-key")
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())
    monkeypatch.setattr(history.time, "time", lambda: 1000.0)
    monkeypatch.setitem(history._CATALOG_CACHE, "key", "catalog-key")
    monkeypatch.setitem(history._CATALOG_CACHE, "miss_refresh_ts", 0.0)
    item = {"type": "movie", "ids": {"imdb": "tt-missing"}}

    history.filter_add_candidates(object(), [item])
    history.filter_add_candidates(object(), [item])

    assert calls == [False, True, False]


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


def test_filter_add_candidates_fails_open_for_episode_guid_miss_when_leaf_scan_is_incomplete(
    monkeypatch,
) -> None:
    catalog = history.HistoryCatalog()
    catalog.guid_complete = True
    catalog.episode_complete = False
    monkeypatch.setattr(history, "_get_history_catalog", lambda *_a, **_k: catalog)
    monkeypatch.setattr(history, "_populate_catalog_episode_leaves", lambda *_a, **_k: 0)
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())
    item = {
        "type": "episode",
        "ids": {"imdb": "tt12345678"},
        "season": 1,
        "episode": 2,
    }

    result = history.filter_add_candidates(object(), [item])

    assert result["items"] == [item]
    assert result["skipped_count"] == 0


def test_filter_add_candidates_caches_complete_empty_episode_scan(monkeypatch) -> None:
    catalog = _catalog()
    catalog.episode_complete = False
    stored: list[history.HistoryCatalog] = []

    def populate(_adapter, _allow, cat):
        cat.episode_complete = True
        return 0

    monkeypatch.setattr(history, "_get_history_catalog", lambda *_a, **_k: catalog)
    monkeypatch.setattr(history, "_populate_catalog_episode_leaves", populate)
    monkeypatch.setattr(history, "_store_history_catalog", lambda _a, _allow, cat: stored.append(cat))
    monkeypatch.setattr(history, "plex_feature_library_ids", lambda *_a, **_k: set())

    result = history.filter_add_candidates(object(), [_episode(2)])

    assert result["items"] == []
    assert result["skipped_count"] == 1
    assert stored == [catalog]


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
