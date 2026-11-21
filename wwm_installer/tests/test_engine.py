import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import wwmpl.core as core
import wwmpl.operations as operations
from wwmpl.core import (Cancelled, Journal, OperationError, compute_status, data_path, file_hash,
                        load_local_manifest, read_version_file)
from wwmpl.operations import Engine, fetch_server_version

from conftest import sha


def engine(world, server, session, lang="en", cancelled=None, notify=None):
    log = []
    e = Engine(world.game, lang, lambda v, t: log.append((v, t)), cancelled, server, notify, session)
    e.log = log
    return e


# ------------------------------------------------------------------ instalacja

def test_install_replaces_files_and_keeps_originals(world, server, session):
    world.publish()
    world.install_game_files("en")
    e = engine(world, server, session)
    e.install()
    assert world.pkg("en").read_bytes() == world.translated("en", "main")
    data = data_path(world.game, "en")
    assert (data / "backup" / sha(world.original("en", "main")) / world.name("en", "main")).read_bytes() == \
        world.original("en", "main")
    assert (data / "payload" / (sha(world.translated("en", "diff")) + ".pol")).exists()
    assert read_version_file(world.game) == "1.0.0"
    assert not world.diff("en").exists()           # plik diff zostaje dla injectora w locie
    assert not (data.parent / "recovery" / "pending.json").exists()
    assert e.skipped == [world.name("en", "small")] or e.skipped == []
    assert compute_status(world.game, "en", "1.0.0").state == "current"


def test_missing_small_files_never_break_install(world, server, session):
    world.publish(small=True)                      # manifest zna pliki small…
    world.install_game_files("en", small=False)    # …ale gra ich nie ma (stan obecny)
    e = engine(world, server, session)
    manifest = e.install()
    assert world.name("en", "small") in e.skipped
    assert world.name("en", "small") not in manifest.files
    assert world.pkg("en").read_bytes() == world.translated("en", "main")


def test_small_files_are_installed_when_they_return(world, server, session):
    world.publish(small=True)
    world.install_game_files("en", small=True)
    e = engine(world, server, session)
    manifest = e.install()
    assert e.skipped == []
    assert world.pkg("en", "small").read_bytes() == world.translated("en", "small")
    assert world.name("en", "small_diff") in manifest.files
    e.restore()
    assert world.pkg("en", "small").read_bytes() == world.original("en", "small")


def test_unexpected_small_hash_is_skipped_not_fatal(world, server, session):
    world.publish(small=True)
    world.install_game_files("en", small=True)
    world.pkg("en", "small").write_bytes(b"inna wersja gry")
    e = engine(world, server, session)
    e.install()
    assert world.name("en", "small") in e.skipped
    assert world.pkg("en", "small").read_bytes() == b"inna wersja gry"   # nietknięty
    assert world.pkg("en").read_bytes() == world.translated("en", "main")


def test_update_to_new_version(world, server, session):
    world.publish()
    world.install_game_files("en")
    engine(world, server, session).install()
    world.content[("en", "main")] = (b"PL-NEW" * 80, world.original("en", "main"))
    world.publish("1.1.0")
    assert compute_status(world.game, "en", "1.1.0").state == "outdated"
    engine(world, server, session).install()
    assert world.pkg("en").read_bytes() == b"PL-NEW" * 80
    assert read_version_file(world.game) == "1.1.0"
    assert compute_status(world.game, "en", "1.1.0").state == "current"


def test_unknown_required_file_aborts_without_changes(world, server, session):
    world.publish()
    world.install_game_files("en")
    world.pkg("en").write_bytes(b"gra po aktualizacji")
    with pytest.raises(OperationError, match="Niezgodna wersja"):
        engine(world, server, session).install()
    assert world.pkg("en").read_bytes() == b"gra po aktualizacji"
    assert load_local_manifest(data_path(world.game, "en"), "en") is None


def test_corrupted_download_is_rejected(world, server, session):
    world.publish(tamper=world.name("en", "main"))
    world.install_game_files("en")
    with pytest.raises(OperationError, match="sum"):
        engine(world, server, session).install()
    assert world.pkg("en").read_bytes() == world.original("en", "main")


def test_multipart_download(world, server, session):
    world.publish()
    world.install_game_files("en")
    name = world.name("en", "main")
    payload = world.translated("en", "main")
    half = len(payload) // 2
    (world.repo / "files" / "en" / (name + ".part001")).write_bytes(payload[:half])
    (world.repo / "files" / "en" / (name + ".part002")).write_bytes(payload[half:])
    manifest = json.loads((world.repo / "files" / "manifest.json").read_text())
    manifest["languages"]["en"]["files"][name]["parts"] = [name + ".part001", name + ".part002"]
    (world.repo / "files" / "manifest.json").write_text(json.dumps(manifest))
    (world.repo / "files" / "en" / name).unlink()
    engine(world, server, session).install()
    assert world.pkg("en").read_bytes() == payload


def test_failure_in_the_middle_rolls_everything_back(world, server, session, monkeypatch):
    world.publish()
    world.install_game_files("en")
    real = core.atomic_copy
    calls = {"n": 0}

    def flaky(source, target):
        if target.parent == world.game / core.PACKAGE_DIR:
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("dysk pełny")
        return real(source, target)

    monkeypatch.setattr(core, "atomic_copy", flaky)
    with pytest.raises(OSError):
        engine(world, server, session).install()
    assert world.pkg("en").read_bytes() == world.original("en", "main")
    assert load_local_manifest(data_path(world.game, "en"), "en") is None
    assert not Journal(world.game).pending.exists()


def test_cancel_during_download(world, server, session):
    world.publish()
    world.install_game_files("en")
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(Cancelled):
        engine(world, server, session, cancelled=cancelled).install()
    assert world.pkg("en").read_bytes() == world.original("en", "main")


def test_journal_recovers_after_crash(world, server, session):
    world.publish()
    world.install_game_files("en")
    target = world.pkg("en")
    before = file_hash(target)
    journal = Journal(world.game)
    journal.prepare([(target, before, [sha(b"x")])])
    target.write_bytes(b"x")                       # „awaria" po zapisie, przed finish()
    assert Journal(world.game).recover() is True
    assert target.read_bytes() == world.original("en", "main")


def test_migration_from_old_installer(world, server, session):
    """Stary instalator: plik .backup obok i polish_version.txt, brak manifestu."""
    world.publish()
    world.install_game_files("en")
    target = world.pkg("en")
    target.with_name(target.name + ".backup").write_bytes(world.original("en", "main"))
    target.write_bytes(b"stare tlumaczenie ze starego instalatora")
    (world.game / core.PACKAGE_DIR / core.VERSION_FILE).write_text("0.9")
    assert compute_status(world.game, "en", "1.0.0").state == "legacy"
    engine(world, server, session).install()
    assert target.read_bytes() == world.translated("en", "main")
    engine(world, server, session).restore()
    assert target.read_bytes() == world.original("en", "main")


# ---------------------------------------------------------------- przywracanie

def test_restore_returns_original_and_cleans_up(world, server, session):
    world.publish()
    world.install_game_files("en")
    engine(world, server, session).install()
    assert engine(world, server, session).restore() == []
    assert world.pkg("en").read_bytes() == world.original("en", "main")
    assert load_local_manifest(data_path(world.game, "en"), "en") is None
    assert read_version_file(world.game) is None
    assert compute_status(world.game, "en", "1.0.0").state == "none"


def test_restore_skips_files_changed_by_game_update(world, server, session):
    world.publish()
    world.install_game_files("en")
    engine(world, server, session).install()
    world.pkg("en").write_bytes(b"nowa wersja gry")
    e = engine(world, server, session)
    assert e.restore() == [world.name("en", "main")]
    assert world.pkg("en").read_bytes() == b"nowa wersja gry"
    assert load_local_manifest(data_path(world.game, "en"), "en") is not None  # dane zachowane


def test_restore_falls_back_to_repo_original_when_backup_is_lost(world, server, session):
    world.publish()
    world.install_game_files("en")
    engine(world, server, session).install()
    import shutil
    shutil.rmtree(data_path(world.game, "en") / "backup")
    assert engine(world, server, session).restore() == []
    assert world.pkg("en").read_bytes() == world.original("en", "main")


def test_languages_are_independent(world, server, session):
    world.publish()
    world.install_game_files("en")
    world.install_game_files("de")
    engine(world, server, session, "en").install()
    engine(world, server, session, "de").install()
    engine(world, server, session, "en").restore()
    assert world.pkg("en").read_bytes() == world.original("en", "main")
    assert world.pkg("de").read_bytes() == world.translated("de", "main")
    assert read_version_file(world.game) == "1.0.0"


def test_second_instance_is_blocked(world, server, session):
    world.publish()
    world.install_game_files("en")
    with core.game_lock(world.game):
        with pytest.raises(OperationError, match="Inny instalator"):
            engine(world, server, session).install()


# -------------------------------------------------------------- injector w locie

class FakeGame:
    """Udaje grę: po starcie zapisuje oryginalny plik różnicowy (jak po pobraniu z serwera)."""

    def __init__(self, world, lang, delay=0.3, revert_once=False, write=True):
        self.world, self.lang, self.delay, self.revert_once, self.write = world, lang, delay, revert_once, write
        self.started = []

    def __call__(self, game_path, platform, notify):
        self.started.append(platform)
        if self.write:
            threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        time.sleep(self.delay)
        target = self.world.diff(self.lang)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.world.original(self.lang, "diff"))
        if self.revert_once:
            time.sleep(0.8)
            target.write_bytes(self.world.original(self.lang, "diff"))   # gra cofa nasz plik


@pytest.fixture
def fast_watch(monkeypatch):
    monkeypatch.setattr(Engine, "CONFIRM_SECONDS", 1.0)
    monkeypatch.setattr(Engine, "GERMAN_FALLBACK", 1.0)
    monkeypatch.setattr(Engine, "WATCH_TIMEOUT", 8)


def installed(world, server, session, lang="en"):
    world.publish()
    world.install_game_files(lang)
    engine(world, server, session, lang).install()


def test_injector_patches_diff_file(world, server, session, monkeypatch, fast_watch):
    installed(world, server, session)
    game = FakeGame(world, "en")
    monkeypatch.setattr(operations, "start_game", game)
    assert engine(world, server, session).launch(str(world.game), "steam") == "patched"
    assert world.diff("en").read_bytes() == world.translated("en", "diff")
    assert game.started == ["steam"]
    original_backup = data_path(world.game, "en") / "backup" / sha(world.original("en", "diff"))
    assert (original_backup / world.name("en", "diff")).read_bytes() == world.original("en", "diff")
    assert not Journal(world.game).pending.exists()


def test_injector_repatches_when_game_reverts_the_file(world, server, session, monkeypatch, fast_watch):
    installed(world, server, session)
    monkeypatch.setattr(operations, "start_game", FakeGame(world, "en", revert_once=True))
    assert engine(world, server, session).launch(str(world.game), "steam") == "patched"
    assert world.diff("en").read_bytes() == world.translated("en", "diff")


def test_injector_timeout_rolls_back(world, server, session, monkeypatch, fast_watch):
    installed(world, server, session)
    world.diff("en").parent.mkdir(parents=True, exist_ok=True)
    world.diff("en").write_bytes(world.original("en", "diff"))
    monkeypatch.setattr(operations, "start_game", FakeGame(world, "en", write=False))
    monkeypatch.setattr(Engine, "WATCH_TIMEOUT", 1.5)
    with pytest.raises(OperationError, match="Nie potwierdzono"):
        engine(world, server, session).launch(str(world.game), "steam")
    assert world.diff("en").read_bytes() == world.original("en", "diff")   # przywrócony stan sprzed startu
    assert not Journal(world.game).pending.exists()


def test_injector_refuses_unknown_diff_version(world, server, session, monkeypatch, fast_watch):
    installed(world, server, session)
    world.diff("en").parent.mkdir(parents=True, exist_ok=True)
    world.diff("en").write_bytes(b"nowa wersja pliku z serwera gry")
    monkeypatch.setattr(operations, "start_game", FakeGame(world, "en"))
    with pytest.raises(OperationError, match="Niezgodna wersja"):
        engine(world, server, session).launch(str(world.game), "steam")


def test_injector_cancel_restores_state(world, server, session, monkeypatch, fast_watch):
    installed(world, server, session)
    cancelled = threading.Event()
    monkeypatch.setattr(operations, "start_game", FakeGame(world, "en", write=False))
    threading.Timer(0.5, cancelled.set).start()
    with pytest.raises(Cancelled):
        engine(world, server, session, cancelled=cancelled).launch(str(world.game), "steam")
    assert not Journal(world.game).pending.exists()


def test_german_without_diff_file_finishes_via_fallback(world, server, session, monkeypatch, fast_watch):
    installed(world, server, session, "de")
    monkeypatch.setattr(operations, "start_game", FakeGame(world, "de", write=False))
    assert engine(world, server, session, "de").launch(str(world.game), "steam") == "files-only"


def test_launch_requires_installation(world, server, session):
    with pytest.raises(OperationError, match="Najpierw zainstaluj"):
        engine(world, server, session).launch(str(world.game), "steam")


# ------------------------------------------------------------- manifest i narzędzia

def test_server_version(world, server, session):
    world.publish("2.3.4")
    assert fetch_server_version(server, session) == "2.3.4"
    assert fetch_server_version("http://127.0.0.1:9/", session, timeout=1) is None


def test_manifest_rejects_bad_data():
    good = "a" * 64
    ok = {"version": "1", "languages": {"en": {"files": {
        "translate_words_map_en": {"sha256": good, "original": good},
        "translate_words_map_en_diff": {"sha256": good, "original": good}}}}}
    core.Manifest.parse(ok, "en")
    import copy
    bad = copy.deepcopy(ok)
    bad["languages"]["en"]["files"]["../evil"] = {"sha256": good, "original": good}
    with pytest.raises(OperationError):
        core.Manifest.parse(bad, "en")
    bad = copy.deepcopy(ok)
    bad["languages"]["en"]["files"]["translate_words_map_en"]["sha256"] = "xyz"
    with pytest.raises(OperationError):
        core.Manifest.parse(bad, "en")
    bad = copy.deepcopy(ok)
    bad["languages"]["en"]["files"]["translate_words_map_en"]["parts"] = ["../../x"]
    with pytest.raises(OperationError):
        core.Manifest.parse(bad, "en")


def test_make_manifest_tool(world, tmp_path):
    for lang in ("en", "de"):
        (tmp_path / "files" / lang).mkdir(parents=True, exist_ok=True)
        for key in ("main", "diff"):
            name = world.name(lang, key)
            (tmp_path / "files" / lang / name).write_bytes(world.translated(lang, key))
            (tmp_path / "files" / "orginal").mkdir(exist_ok=True)
            (tmp_path / "files" / "orginal" / name).write_bytes(world.original(lang, key))
    tool = Path(__file__).resolve().parents[1] / "tools" / "make_manifest.py"
    result = subprocess.run([sys.executable, str(tool), "--version", "3.0", "--files", str(tmp_path / "files"),
                             "--originals", str(tmp_path / "files" / "orginal")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads((tmp_path / "files" / "manifest.json").read_text())
    entry = payload["languages"]["en"]["files"][world.name("en", "main")]
    assert entry == {"sha256": sha(world.translated("en", "main")), "original": sha(world.original("en", "main"))}
    assert world.name("en", "small") not in payload["languages"]["en"]["files"]
