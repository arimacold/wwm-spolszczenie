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


def engine(world, server, session, lang="en", cancelled=None, notify=None, confirm=None, variant="full"):
    log = []
    e = Engine(world.game, lang, lambda v, t: log.append((v, t)), cancelled, server, notify, session, confirm,
               variant=variant)
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

    def __init__(self, world, lang, delay=0.3, revert_once=False, write=True, content=None):
        self.world, self.lang, self.delay, self.revert_once, self.write = world, lang, delay, revert_once, write
        self.content = content
        self.started = []

    def __call__(self, game_path, platform, notify):
        self.started.append(platform)
        if self.write:
            threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        time.sleep(self.delay)
        target = self.world.diff(self.lang)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.content or self.world.original(self.lang, "diff"))
        if self.revert_once:
            time.sleep(0.8)
            target.write_bytes(self.world.original(self.lang, "diff"))   # gra cofa nasz plik


@pytest.fixture
def fast_watch(monkeypatch):
    monkeypatch.setattr(Engine, "CONFIRM_SECONDS", 1.0)
    monkeypatch.setattr(Engine, "GERMAN_FALLBACK", 1.0)
    monkeypatch.setattr(Engine, "WATCH_TIMEOUT", 8)
    monkeypatch.setattr(Engine, "LAUNCHER_WATCH_TIMEOUT", 8)
    monkeypatch.setattr(Engine, "GAME_CONFIRM_SECONDS", 1.0)


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


def test_injector_accepts_leftover_diff_when_game_redownloads_original(world, server, session, monkeypatch, fast_watch):
    """Pozostałość po starym instalatorze (nieznany hash) nie blokuje startu – liczy się świeżo pobrany plik."""
    installed(world, server, session)
    world.diff("en").parent.mkdir(parents=True, exist_ok=True)
    world.diff("en").write_bytes(b"stare polskie tlumaczenie ze starego instalatora")
    monkeypatch.setattr(operations, "start_game", FakeGame(world, "en"))
    assert engine(world, server, session).launch(str(world.game), "steam") == "patched"
    assert world.diff("en").read_bytes() == world.translated("en", "diff")


def test_injector_fails_fast_and_rolls_back_when_game_downloads_other_version(world, server, session, monkeypatch,
                                                                              fast_watch):
    """Gra zaktualizowana: świeży plik różni się od oryginału z repozytorium – nie nakładamy starego tłumaczenia."""
    installed(world, server, session)
    before = b"stan sprzed startu"
    world.diff("en").parent.mkdir(parents=True, exist_ok=True)
    world.diff("en").write_bytes(before)
    monkeypatch.setattr(Engine, "FOREIGN_SECONDS", 1.0)
    monkeypatch.setattr(operations, "start_game", FakeGame(world, "en", content=b"nowa wersja pliku z serwera gry"))
    started = time.monotonic()
    with pytest.raises(OperationError, match="inną wersję"):
        engine(world, server, session).launch(str(world.game), "steam")
    assert time.monotonic() - started < 6                      # nie czekamy całych 300 s
    assert world.diff("en").read_bytes() == b"nowa wersja pliku z serwera gry"   # plik gry zostaje nietknięty
    assert not Journal(world.game).pending.exists()


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
    magic = bytes.fromhex("efbeadde")          # prawdziwe pliki gry mają ten nagłówek
    for lang in ("en", "de"):
        (tmp_path / "files" / lang).mkdir(parents=True, exist_ok=True)
        for key in ("main", "diff"):
            name = world.name(lang, key)
            (tmp_path / "files" / lang / name).write_bytes(magic + world.translated(lang, key))
            (tmp_path / "files" / "orginal").mkdir(exist_ok=True)
            (tmp_path / "files" / "orginal" / name).write_bytes(magic + world.original(lang, key))
    tool = Path(__file__).resolve().parents[1] / "tools" / "make_manifest.py"
    run = lambda: subprocess.run([sys.executable, str(tool), "--version", "3.0", "--files", str(tmp_path / "files"),
                                  "--originals", str(tmp_path / "files" / "orginal")], capture_output=True, text=True)
    result = run()
    assert result.returncode == 0, result.stderr
    payload = json.loads((tmp_path / "files" / "manifest.json").read_text())
    entry = payload["languages"]["en"]["files"][world.name("en", "main")]
    assert entry == {"sha256": sha(magic + world.translated("en", "main")),
                     "original": sha(magic + world.original("en", "main"))}
    assert world.name("en", "small") not in payload["languages"]["en"]["files"]
    # plik bez nagłówka gry (uszkodzony / zły format) nie przechodzi
    (tmp_path / "files" / "en" / world.name("en", "main")).write_bytes(b"\x8c\xd1'F zly plik")
    result = run()
    assert result.returncode == 1 and "nagłówka" in result.stderr


# ------------------------------------------- gra nowsza niż tłumaczenie: ostrzeżenie i wybór użytkownika

def test_install_newer_game_file_when_user_accepts(world, server, session):
    world.publish()
    world.install_game_files("en")
    newer = b"plik gry po aktualizacji"
    world.pkg("en").write_bytes(newer)
    asked = []
    engine(world, server, session, confirm=lambda names: asked.append(names) or True).install()
    assert asked == [[world.name("en", "main")]]                       # pytamy raz, ze wskazaniem pliku
    assert world.pkg("en").read_bytes() == world.translated("en", "main")
    manifest = load_local_manifest(data_path(world.game, "en"), "en")
    assert manifest.files[world.name("en", "main")].original == sha(newer)
    assert compute_status(world.game, "en", "1.0.0").state == "current"
    # przywracanie oddaje prawdziwy (nowszy) plik gry, a nie stary oryginał z repozytorium
    assert engine(world, server, session).restore() == []
    assert world.pkg("en").read_bytes() == newer


def test_install_newer_game_file_when_user_declines(world, server, session):
    world.publish()
    world.install_game_files("en")
    newer = b"plik gry po aktualizacji"
    world.pkg("en").write_bytes(newer)
    with pytest.raises(Cancelled):
        engine(world, server, session, confirm=lambda names: False).install()
    assert world.pkg("en").read_bytes() == newer
    assert load_local_manifest(data_path(world.game, "en"), "en") is None


def test_launch_newer_diff_when_user_accepts(world, server, session, monkeypatch, fast_watch):
    installed(world, server, session)
    newer = b"nowa wersja pliku z serwera gry"
    monkeypatch.setattr(Engine, "FOREIGN_SECONDS", 1.0)
    monkeypatch.setattr(operations, "start_game", FakeGame(world, "en", content=newer))
    asked = []
    result = engine(world, server, session, confirm=lambda names: asked.append(names) or True).launch(
        str(world.game), "steam")
    assert result == "patched" and len(asked) == 1
    assert world.diff("en").read_bytes() == world.translated("en", "diff")
    assert not Journal(world.game).pending.exists()
    # przywracanie nie wkłada starego oryginału: plik znika i gra pobierze własną, aktualną wersję
    assert engine(world, server, session).restore() == []
    assert not world.diff("en").exists()


def test_launch_newer_diff_when_user_declines(world, server, session, monkeypatch, fast_watch):
    installed(world, server, session)
    newer = b"nowa wersja pliku z serwera gry"
    monkeypatch.setattr(Engine, "FOREIGN_SECONDS", 1.0)
    monkeypatch.setattr(operations, "start_game", FakeGame(world, "en", content=newer))
    with pytest.raises(Cancelled):
        engine(world, server, session, confirm=lambda names: False).launch(str(world.game), "steam")
    assert world.diff("en").read_bytes() == newer                    # świeży plik gry zostaje nietknięty
    assert not Journal(world.game).pending.exists()


def test_waiting_for_the_decision_does_not_count_to_timeout(world, server, session, monkeypatch, fast_watch):
    installed(world, server, session)
    monkeypatch.setattr(Engine, "FOREIGN_SECONDS", 0.5)
    monkeypatch.setattr(Engine, "WATCH_TIMEOUT", 3)                  # krótszy niż „namysł" użytkownika

    def slow_yes(names):
        time.sleep(4)
        return True

    monkeypatch.setattr(operations, "start_game", FakeGame(world, "en", content=b"nowa wersja z serwera"))
    assert engine(world, server, session, confirm=slow_yes).launch(str(world.game), "steam") == "patched"


# ------------------------------------------------------------------ warianty: pełne / fabularne

def test_switch_full_to_story_and_back(world, server, session):
    world.publish()
    world.publish_story()
    world.install_game_files("en")
    engine(world, server, session).install()
    assert world.pkg("en").read_bytes() == world.translated("en", "main")
    m = engine(world, server, session, variant="story").install()
    assert m.variant == "story"
    assert world.pkg("en").read_bytes() == world.story[("en", "main")]
    assert compute_status(world.game, "en", "0.1.0-beta", "story").state == "current"
    assert compute_status(world.game, "en", "1.0.0", "full").state == "other_variant"
    engine(world, server, session).install()
    assert world.pkg("en").read_bytes() == world.translated("en", "main")
    assert compute_status(world.game, "en", "1.0.0", "full").state == "current"


def test_story_restore_uses_original_from_repo_root(world, server, session):
    world.publish()
    world.publish_story()
    world.install_game_files("en")
    engine(world, server, session, variant="story").install()
    import shutil
    shutil.rmtree(data_path(world.game, "en") / "backup")          # brak lokalnej kopii -> pobranie z repo
    assert engine(world, server, session, variant="story").restore() == []
    assert world.pkg("en").read_bytes() == world.original("en", "main")


def test_story_not_published_yet(world, server, session):
    world.publish()
    world.install_game_files("en")
    with pytest.raises(OperationError, match="nie jest jeszcze dostępny"):
        engine(world, server, session, variant="story").install()
    assert world.pkg("en").read_bytes() == world.original("en", "main")


def test_story_version_file(world, server, session):
    world.publish_story("0.2.0")
    assert fetch_server_version(server + "fabula/", session) == "0.2.0"


# ------------------------------------------------- oficjalny launcher: pliki w LocalData\Patch

def test_launcher_layout_is_recognised_and_resolved(lworld):
    assert core.is_valid_game_path(lworld.game)
    assert not core.is_valid_game_path(lworld.game.parent)                       # sam folder „wwm”
    assert core.resolve_game_root(lworld.game.parent) == lworld.game             # wskazano za wysoko
    assert core.resolve_game_root(lworld.game / core.DIFF_DIR) == lworld.game    # wskazano locale
    assert core.resolve_game_root(lworld.game / "Engine" / "Binaries" / "Win64r") == lworld.game
    assert core.resolve_game_root(lworld.game.parent.parent / "nic") is None


def test_launcher_install_restore_and_launch(lworld, lserver, session, monkeypatch, fast_watch):
    lworld.publish()
    lworld.install_game_files("en")
    main = lworld.game / core.DIFF_DIR / lworld.name("en", "main")
    engine(lworld, lserver, session).install()
    assert main.read_bytes() == lworld.translated("en", "main")                 # plik główny podmieniony w Patch
    assert not (lworld.game / core.PACKAGE_DIR).exists()                       # nic nie trafia do Package
    assert compute_status(lworld.game, "en", "1.0.0").state == "current"
    assert read_version_file(lworld.game) == "1.0.0"                           # polish_version.txt obok plików
    monkeypatch.setattr(operations, "start_game", FakeGame(lworld, "en"))
    monkeypatch.setattr(Engine, "_game_running", lambda self: True)
    assert engine(lworld, lserver, session).launch(str(lworld.game), "launcher") == "patched"
    assert lworld.diff("en").read_bytes() == lworld.translated("en", "diff")
    assert engine(lworld, lserver, session).restore() == []
    assert main.read_bytes() == lworld.original("en", "main")


def test_launcher_without_language_files_gives_clear_message(lworld, lserver, session):
    lworld.publish()
    with pytest.raises(OperationError, match="Uruchom grę raz"):
        engine(lworld, lserver, session).install()


def test_find_launch_exe_prefers_launcher_and_ignores_case(lworld):
    game_exe = lworld.game / "Engine" / "Binaries" / "Win64r" / "wwm.exe"
    game_exe.write_bytes(b"MZ")
    assert core.find_launch_exe(lworld.game) == game_exe                       # małe litery też pasują
    launcher = lworld.game.parent / "WWM_Launcher.exe"
    launcher.write_bytes(b"MZ")
    (lworld.game.parent / "uninst_launcher.exe").write_bytes(b"MZ")
    assert core.find_launch_exe(lworld.game) == launcher                       # launcher ma pierwszeństwo


def test_find_game_path_scans_drives_for_launcher(lworld, monkeypatch):
    monkeypatch.setattr(core, "_available_drives", lambda: [str(lworld.game.parent.parent)])
    monkeypatch.setattr(core, "LAUNCHER_RELATIVE", ["wwm"])
    monkeypatch.setattr(core, "LAUNCHER_CANDIDATES", [])
    monkeypatch.setattr(core, "_registry_install_locations", lambda log: [])
    monkeypatch.setattr(core, "_epic_install_locations", lambda log: [])
    assert core.find_game_path("launcher") == str(lworld.game)


def test_steam_main_file_follows_patch_copy_if_game_downloaded_one(world, server, session):
    """Gdy gra (także Steam) trzyma nowszy plik główny w Patch, podmieniamy ten, którego gra używa."""
    world.publish()
    patch_main = world.game / core.DIFF_DIR / world.name("en", "main")
    patch_main.parent.mkdir(parents=True, exist_ok=True)
    patch_main.write_bytes(world.original("en", "main"))
    world.install_game_files("en")
    engine(world, server, session).install()
    assert patch_main.read_bytes() == world.translated("en", "main")


def test_launcher_search_skips_steam_and_finds_nested_wwm_standard(tmp_path, monkeypatch):
    """Steam i launcher na jednym dysku: dla launchera nie wolno wybrać folderu ze Steam."""
    drive = tmp_path / "D"
    steam_game = drive / "SteamLibrary" / "steamapps" / "common" / "Where Winds Meet"
    (steam_game / core.PACKAGE_DIR).mkdir(parents=True)
    launcher_game = drive / "SteamLibrary" / "wwm_standard"          # jak u Arimy: D:\SteamLibrary\wwm_standard
    (launcher_game / core.DIFF_DIR).mkdir(parents=True)
    monkeypatch.setattr(core, "_available_drives", lambda: [str(drive)])
    monkeypatch.setattr(core, "LAUNCHER_CANDIDATES", [])
    monkeypatch.setattr(core, "_registry_install_locations", lambda log: [steam_game])   # wpis Steama w rejestrze
    monkeypatch.setattr(core, "_executed_game_paths", lambda log: [])
    monkeypatch.setattr(core, "_epic_install_locations", lambda log: [])
    assert core.find_game_path("launcher") == str(launcher_game)


def test_launcher_search_prefers_recently_used_install(tmp_path, monkeypatch):
    import os
    drive = tmp_path / "E"
    standard = drive / "Games" / "wwm" / "wwm_standard"
    lite = drive / "Games" / "wwm" / "wwm_lite"
    for root in (standard, lite):
        (root / core.DIFF_DIR).mkdir(parents=True)
    os.utime(standard / core.DIFF_DIR, (1_000_000, 1_000_000))       # standard dawno nieużywany
    monkeypatch.setattr(core, "_available_drives", lambda: [str(drive)])
    monkeypatch.setattr(core, "LAUNCHER_CANDIDATES", [])
    monkeypatch.setattr(core, "_registry_install_locations", lambda log: [])
    monkeypatch.setattr(core, "_executed_game_paths", lambda log: [])
    monkeypatch.setattr(core, "_epic_install_locations", lambda log: [])
    assert core.find_game_path("launcher") == str(lite)


def test_launcher_config_and_run_traces_are_used(tmp_path, monkeypatch):
    game = tmp_path / "X" / "anything" / "wwm_lite"
    (game / core.DIFF_DIR).mkdir(parents=True)
    (game / "Engine" / "Binaries" / "Win64r").mkdir(parents=True)
    launcher_dir = tmp_path / "ProgramFiles" / "wwm"
    launcher_dir.mkdir(parents=True)
    (launcher_dir / "config.json").write_text('{"gamePath": "%s"}' % str(game).replace("\\", "\\\\"))
    log = __import__("wwmpl.logs", fromlist=["get"]).get()
    found = core._launcher_config_paths([launcher_dir], log)
    if game.drive:                                                   # wzorzec ścieżek dotyczy dysków Windows
        assert any(core.resolve_game_root(p) == game for p in found)
    monkeypatch.setattr(core, "_available_drives", lambda: [])
    monkeypatch.setattr(core, "LAUNCHER_CANDIDATES", [])
    monkeypatch.setattr(core, "_registry_install_locations", lambda log: [])
    monkeypatch.setattr(core, "_epic_install_locations", lambda log: [])
    monkeypatch.setattr(core, "_executed_game_paths", lambda log: [game / "Engine" / "Binaries" / "Win64r"])
    assert core.find_game_path("launcher") == str(game)


def test_real_layout_from_arima_diagnostics(tmp_path, monkeypatch):
    """Odwzorowanie raportu diagnostycznego: Steam + launcher, setting.ini z InstallPath, gra bez Package."""
    drive = tmp_path / "D"
    steam_game = drive / "SteamLibrary" / "steamapps" / "common" / "Where Winds Meet"
    (steam_game / core.PACKAGE_DIR).mkdir(parents=True)
    (steam_game / core.DIFF_DIR).mkdir(parents=True)
    game = drive / "SteamLibrary" / "wwm_standard"
    (game / core.DIFF_DIR).mkdir(parents=True)
    (game / core.DIFF_DIR / "translate_words_map_en").write_bytes(b"x")
    for sub in ("Win64r", "Win64rh"):
        (game / "Engine" / "Binaries" / sub).mkdir(parents=True)
        (game / "Engine" / "Binaries" / sub / "wwm.exe").write_bytes(b"MZ")
    launcher = tmp_path / "Program Files" / "wwm"
    deploy = launcher / "Win32" / "deploy"
    deploy.mkdir(parents=True)
    (deploy / "launcher.exe").write_bytes(b"MZ")
    (deploy / "updater.exe").write_bytes(b"MZ")
    (launcher / "uninstaller.exe").write_bytes(b"MZ")
    (deploy / "setting.ini").write_text(f"[General]\nlang=en\nchannel=netease_global\n\nInstallPath={game.as_posix()}\n")
    monkeypatch.setattr(core, "_netease_launcher_dirs", lambda log: [launcher])
    monkeypatch.setattr(core, "_registry_install_locations", lambda log: [steam_game, deploy, launcher])
    monkeypatch.setattr(core, "_executed_game_paths",
                        lambda log: [steam_game / "Engine" / "Binaries" / "Win64r"])   # ślad Steama – ignorowany
    monkeypatch.setattr(core, "_epic_install_locations", lambda log: [])
    monkeypatch.setattr(core, "_available_drives", lambda: [str(drive)])
    monkeypatch.setattr(core, "LAUNCHER_CANDIDATES", [])
    assert core.find_game_path("launcher") == str(game)
    assert core.find_official_launcher() == deploy / "launcher.exe"
    assert core.FileSpec("translate_words_map_en", "a" * 64, "b" * 64).target(game).parent == game / core.DIFF_DIR
    assert core.find_launch_exe(game).parent.name == "Win64r"



class FakeOfficialLauncher:
    """Zachowanie oficjalnego launchera: weryfikuje pliki (przywraca oryginalny diff I plik główny),
    a grę uruchamia dopiero po chwili („Graj”). Gra przy starcie jeszcze raz przywraca diff."""

    def __init__(self, world, lang="en"):
        self.world, self.lang = world, lang
        self.game_started = False

    def __call__(self, game_path, platform, notify):
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        w, lang = self.world, self.lang
        time.sleep(0.3)
        w.diff(lang).write_bytes(w.original(lang, "diff"))       # weryfikacja w launcherze
        w.pkg(lang).write_bytes(w.original(lang, "main"))        # launcher „naprawia” też plik główny
        time.sleep(2.0)                                          # gracz klika „Graj”
        self.game_started = True
        time.sleep(0.3)
        w.diff(lang).write_bytes(w.original(lang, "diff"))       # gra sprawdza pliki przy starcie


def test_official_launcher_waits_for_game_and_keeps_translation(lworld, lserver, session, monkeypatch, fast_watch):
    lworld.publish()
    lworld.install_game_files("en")
    engine(lworld, lserver, session).install()
    launcher = FakeOfficialLauncher(lworld)
    monkeypatch.setattr(operations, "start_game", launcher)
    monkeypatch.setattr(Engine, "_game_running", lambda self: launcher.game_started)
    started = time.monotonic()
    e = engine(lworld, lserver, session)
    assert e.launch(str(lworld.game), "launcher") == "patched"
    assert time.monotonic() - started > 2.3                       # nie ogłoszono sukcesu przed startem gry
    assert lworld.diff("en").read_bytes() == lworld.translated("en", "diff")
    assert lworld.pkg("en").read_bytes() == lworld.translated("en", "main")
    assert any("czekam na uruchomienie gry" in text.lower() or "graj" in text.lower() for _, text in e.log)


def test_launch_repairs_main_file_restored_by_launcher(lworld, lserver, session, monkeypatch, fast_watch):
    lworld.publish()
    lworld.install_game_files("en")
    engine(lworld, lserver, session).install()
    lworld.pkg("en").write_bytes(lworld.original("en", "main"))  # launcher przywrócił oryginał między sesjami
    monkeypatch.setattr(operations, "start_game", FakeGame(lworld, "en"))
    monkeypatch.setattr(Engine, "_game_running", lambda self: True)
    assert engine(lworld, lserver, session).launch(str(lworld.game), "launcher") == "patched"
    assert lworld.pkg("en").read_bytes() == lworld.translated("en", "main")
