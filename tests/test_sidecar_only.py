"""The sidecar-only fork's promises (spudalicious1969, 2026-11-16).

1. Lyrics go to a .lrc/.txt next to the audio, never into its tags.
2. Automatic runs never touch an existing .lrc or .txt.
3. get_on_save never re-saves the audio file, and still clears its guard.
4. Instrumentals and misses write nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.common import state
from src.services import lrclib

SYNCED = "[00:01.00] first line\n[00:05.00] second line"
PLAIN = "first line\nsecond line"


class FakeFile:
    def __init__(self, path: Path) -> None:
        self.filename = str(path)
        self.metadata: dict[str, Any] = {"title": "Song"}
        self.saves = 0

    def save(self) -> None:  # pragma: no cover - must never be called
        self.saves += 1


@pytest.fixture
def run(make_api, make_metadata, tmp_path, monkeypatch):
    """Call process_response the way Picard would, and return what happened."""
    completed: list[str] = []
    asked: list[str] = []
    monkeypatch.setattr(
        lrclib, "confirm_yes_no", lambda *a, **k: asked.append("asked") or True
    )

    def _run(response: Any, method: str = "get_on_save", **config: Any):
        cfg = {
            "plain_as_txt": True,
            "prefer_synced_lyrics": True,
            "ignore_instrumental": True,
            "auto_overwrite": False,
            "save_lrc_file": False,  # deliberately off: the fork writes anyway
        }
        cfg.update(config)
        api = make_api(cfg)
        api.complete_album_task = lambda album, task_id: completed.append(task_id)
        audio = tmp_path / "01 Song.flac"
        audio.write_bytes(b"fLaC")
        f = FakeFile(audio)
        state.files_processing.add(f.filename)
        lrclib.process_response(
            api, method, object(), make_metadata(), "task", [f], response, None, None
        )
        return f, tmp_path, completed, asked

    return _run


def test_synced_goes_to_lrc_and_never_into_tags(run):
    f, d, completed, _ = run({"id": 1, "syncedLyrics": SYNCED, "plainLyrics": PLAIN})
    assert (d / "01 Song.lrc").read_text(encoding="utf-8") == SYNCED
    assert not (d / "01 Song.txt").exists()
    assert "lyrics" not in f.metadata
    assert f.saves == 0
    assert f.filename not in state.files_processing
    assert completed == ["task"]


def test_plain_only_goes_to_txt(run):
    f, d, _, _ = run({"id": 1, "plainLyrics": PLAIN})
    assert (d / "01 Song.txt").read_text(encoding="utf-8") == PLAIN
    assert not (d / "01 Song.lrc").exists()
    assert "lyrics" not in f.metadata


@pytest.mark.parametrize("ext", [".lrc", ".txt"])
@pytest.mark.parametrize("method", ["get_on_save", "get_on_load", "get"])
def test_automatic_runs_never_touch_an_existing_sidecar(run, tmp_path, ext, method):
    (tmp_path / f"01 Song{ext}").write_text("HAND MADE", encoding="utf-8")
    f, d, _, asked = run({"id": 1, "syncedLyrics": SYNCED}, method=method)
    assert (d / f"01 Song{ext}").read_text(encoding="utf-8") == "HAND MADE"
    other = ".txt" if ext == ".lrc" else ".lrc"
    assert not (d / f"01 Song{other}").exists()
    assert asked == []
    assert "lyrics" not in f.metadata


def test_manual_search_asks_then_replaces_and_retires_the_txt(run, tmp_path, monkeypatch):
    (tmp_path / "01 Song.txt").write_text("OLD PLAIN", encoding="utf-8")
    monkeypatch.setattr(lrclib, "show_search_table", lambda *a, **k: {"id": 1, "syncedLyrics": SYNCED})
    f, d, _, asked = run([{"id": 1}], method="search")
    assert asked == ["asked"]
    assert (d / "01 Song.lrc").read_text(encoding="utf-8") == SYNCED
    assert not (d / "01 Song.txt").exists()
    assert "lyrics" not in f.metadata


def test_instrumental_writes_nothing(run):
    f, d, _, _ = run({"id": 1, "instrumental": True, "plainLyrics": ""})
    assert sorted(p.name for p in d.iterdir()) == ["01 Song.flac"]
    assert f.filename not in state.files_processing


def test_miss_writes_nothing_and_clears_guard(run):
    f, d, completed, _ = run({"code": 404})
    assert sorted(p.name for p in d.iterdir()) == ["01 Song.flac"]
    assert f.filename not in state.files_processing
    assert completed == ["task"]
