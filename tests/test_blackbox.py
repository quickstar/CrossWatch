from __future__ import annotations

from cw_platform.orchestrator import _blackbox as blackbox


def test_clear_blackbox_removes_scoped_entries_and_flap_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(blackbox, "STATE_DIR", tmp_path)
    monkeypatch.setattr(blackbox, "scope_safe", lambda: "profile")

    global_path = blackbox._bb_path("PLEX", "history")
    pair_path = blackbox._bb_path("PLEX", "history", "plex-trakt")
    flap_path = blackbox._flap_path("PLEX", "history")
    blackbox._write_json(global_path, {"drop": {"since": 1}, "keep": {"since": 2}})
    blackbox._write_json(pair_path, {"drop": {"since": 3}})
    blackbox._write_json(flap_path, {"drop": {"consecutive": 3}, "keep": {"consecutive": 1}})

    result = blackbox.clear_blackbox(
        "PLEX",
        "history",
        ["drop"],
        pair="plex-trakt",
    )

    assert result == {"ok": True, "count": 1}
    assert blackbox._read_json(global_path) == {"keep": {"since": 2}}
    assert blackbox._read_json(pair_path) == {}
    assert blackbox._read_json(flap_path) == {"keep": {"consecutive": 1}}
