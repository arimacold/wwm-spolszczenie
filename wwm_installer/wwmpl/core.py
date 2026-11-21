"""Rdzeń logiki instalatora (bez GUI): manifest, sumy SHA-256, kopie zapasowe,
zapis atomowy, dziennik odzyskiwania, blokada folderu, wersje i wykrywanie gry."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

try:
    import msvcrt
except ImportError:  # poza Windowsem (np. testy)
    msvcrt = None
    import fcntl

try:
    import winreg
except ImportError:
    winreg = None

GITHUB_USER = "arimacold"
REPO_NAME = "wwm-spolszczenie"
RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_USER}/{REPO_NAME}/main/"
STEAM_GUIDE_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id=3619908590"
COFFEE_URL = "https://buycoffee.to/arima"
STEAM_APP_ID = "3564740"
AUTHORS = (  # (nazwa, profil Steam, nick Discord)
    ("Arima", "https://steamcommunity.com/id/Arima", "arimaone"),
    ("Pikaros", "https://steamcommunity.com/profiles/76561198157037319", "pikaros34pl"),
)

PACKAGE_DIR = Path("Package", "HD", "oversea", "locale")
DIFF_DIR = Path("LocalData", "Patch", "HD", "oversea", "locale")
DATA_DIR = Path("Spolszczenie_Data", "WWMPL")
VERSION_FILE = "polish_version.txt"
LANGUAGES = {"en": "English", "de": "Deutsch"}

HEX = re.compile(r"[0-9a-f]{64}")
PART_NAME = re.compile(r"[\w.\-]+")


class OperationError(Exception):
    """Błąd z komunikatem przeznaczonym dla użytkownika."""


class Cancelled(Exception):
    pass


# --------------------------------------------------------------------------- pliki

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_hash(path: Path) -> Optional[str]:
    try:
        return sha256_file(path)
    except FileNotFoundError:
        return None


def matches(path: Path, digest: Optional[str]) -> bool:
    return digest is not None and file_hash(path) == digest


def make_writable(path: Path) -> None:
    if path.exists():
        path.chmod(stat.S_IWRITE | stat.S_IREAD)


def atomic_copy(source: Path, target: Path) -> None:
    """Kopiuje przez plik tymczasowy w katalogu docelowym i podmienia jednym ruchem."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False, suffix=".tmp") as stream:
        temporary = Path(stream.name)
    try:
        with source.open("rb") as original, temporary.open("wb") as stream:
            shutil.copyfileobj(original, stream, 1024 * 1024)
            stream.flush()
            os.fsync(stream.fileno())
        make_writable(target)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def remove_file(target: Path) -> None:
    if target.exists():
        make_writable(target)
        target.unlink(missing_ok=True)


# ----------------------------------------------------------------------- manifest

def expected_names(language: str) -> dict:
    base = f"translate_words_map_{language}"
    return {"main": base, "diff": base + "_diff", "small": base + "__small", "small_diff": base + "__small_diff"}


@dataclass(frozen=True)
class FileSpec:
    name: str
    sha256: str       # suma pliku z tłumaczeniem
    original: str     # suma oryginalnego pliku gry
    parts: tuple = ()  # opcjonalnie: plik podzielony na części

    @property
    def is_diff(self) -> bool:
        return self.name.endswith("_diff")

    @property
    def optional(self) -> bool:
        """Pliki „small" nie istnieją w obecnej wersji gry – ich brak nigdy nie przerywa instalacji."""
        return "__small" in self.name

    def target(self, root: Path) -> Path:
        return root / (DIFF_DIR if self.is_diff else PACKAGE_DIR) / self.name

    def to_json(self) -> dict:
        data = {"sha256": self.sha256, "original": self.original}
        if self.parts:
            data["parts"] = list(self.parts)
        return data


@dataclass
class Manifest:
    version: str
    language: str
    files: dict  # name -> FileSpec

    @classmethod
    def parse(cls, payload, language: str) -> "Manifest":
        try:
            version = payload["version"]
            entries = payload["languages"][language]["files"]
        except (KeyError, TypeError):
            raise OperationError(f"W manifeście brakuje danych dla języka {LANGUAGES.get(language, language)}.")
        names = expected_names(language)
        required = {names["main"], names["diff"]}
        if (not isinstance(version, str) or not version.strip() or not isinstance(entries, dict)
                or not required <= set(entries) or not set(entries) <= set(names.values())):
            raise OperationError("Nieprawidłowy manifest tłumaczenia.")
        files = {}
        for name in sorted(entries, key=lambda n: (n.endswith("_diff"), n)):
            info = entries[name]
            sha, original = info.get("sha256"), info.get("original")
            if not (isinstance(sha, str) and HEX.fullmatch(sha) and isinstance(original, str) and HEX.fullmatch(original)):
                raise OperationError(f"Nieprawidłowa suma kontrolna pliku {name}.")
            parts = info.get("parts") or []
            if not isinstance(parts, list) or not all(isinstance(p, str) and PART_NAME.fullmatch(p) for p in parts):
                raise OperationError(f"Nieprawidłowa lista części pliku {name}.")
            files[name] = FileSpec(name, sha, original, tuple(parts))
        return cls(version.strip(), language, files)

    def dump(self) -> dict:
        return {"version": self.version,
                "languages": {self.language: {"files": {n: s.to_json() for n, s in self.files.items()}}}}

    def without(self, names: Iterable[str]) -> "Manifest":
        skip = set(names)
        return Manifest(self.version, self.language, {n: s for n, s in self.files.items() if n not in skip})

    @property
    def packages(self):
        return [s for s in self.files.values() if not s.is_diff]

    @property
    def diffs(self):
        return [s for s in self.files.values() if s.is_diff]


def data_root(root: Path) -> Path:
    return root / DATA_DIR


def data_path(root: Path, language: str) -> Path:
    return data_root(root) / language


def load_local_manifest(data: Path, language: str) -> Optional[Manifest]:
    path = data / "manifest.json"
    if not path.is_file():
        return None
    try:
        return Manifest.parse(json.loads(path.read_text(encoding="utf-8")), language)
    except (ValueError, OperationError):
        return None  # uszkodzony lokalny manifest = brak instalacji; instalacja go odtworzy


def payload_path(data: Path, spec: FileSpec) -> Path:
    return data / "payload" / (spec.sha256 + ".pol")


# ---------------------------------------------------------------- kopie oryginałów

def original_backup(data: Path, name: str, digest: Optional[str]) -> Optional[Path]:
    if digest is None:
        return None
    for backup in (data / "backup" / digest / name,):
        if matches(backup, digest):
            return backup
    return None


def save_original(data: Path, target: Path, digest: str) -> None:
    if original_backup(data, target.name, digest) is None:
        backup = data / "backup" / digest / target.name
        atomic_copy(target, backup)
        if not matches(backup, digest):
            raise OperationError(f"Plik {target.name} zmienił się w trakcie tworzenia kopii.")


def adopt_legacy_backup(data: Path, target: Path, digest: str) -> Optional[Path]:
    """Migracja: stary instalator zostawiał kopię jako `<plik>.backup` obok pliku gry."""
    legacy = target.with_name(target.name + ".backup")
    if legacy.is_file() and matches(legacy, digest):
        backup = data / "backup" / digest / target.name
        atomic_copy(legacy, backup)
        return backup if matches(backup, digest) else None
    return None


# ------------------------------------------------------------------------ blokada

@contextmanager
def game_lock(root: Path):
    directory = data_root(root)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "operation.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            if msvcrt:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise OperationError("Inny instalator pracuje już na tym folderze gry.") from error
        try:
            yield
        finally:
            try:
                lock.seek(0)
                if msvcrt:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


# ------------------------------------------------------------ dziennik odzyskiwania

@dataclass
class Change:
    target: Path
    before: Optional[str]   # oczekiwana suma przed zmianą (None = plik nie istnieje)
    source: Optional[Path]  # skąd skopiować (None = usunąć plik)
    after: Optional[str]


class Journal:
    """Zapisuje stan przed zmianą, aby przerwana operacja (błąd, anulowanie, awaria
    zasilania) mogła zostać cofnięta przy następnym uruchomieniu."""

    def __init__(self, root: Path):
        self.root = root
        self.directory = data_root(root) / "recovery"
        self.pending = self.directory / "pending.json"

    def prepare(self, entries) -> None:
        if self.pending.exists():
            raise OperationError("Najpierw zakończ odzyskiwanie poprzedniej operacji.")
        self.directory.mkdir(parents=True, exist_ok=True)
        records = []
        for index, (target, before, afters) in enumerate(entries):
            if file_hash(target) != before:
                raise OperationError(f"Plik {target.name} zmienił się w trakcie operacji.")
            if before is not None:
                snapshot = self.directory / f"{index}.before"
                atomic_copy(target, snapshot)
                if not matches(snapshot, before):
                    raise OperationError(f"Nie udało się zweryfikować kopii pliku {target.name}.")
            records.append({"path": target.relative_to(self.root).as_posix(), "before": before, "after": list(afters)})
        draft = self.directory / "pending.draft"
        try:
            with draft.open("w", encoding="utf-8") as stream:
                json.dump(records, stream)
                stream.flush()
                os.fsync(stream.fileno())
            draft.replace(self.pending)
        finally:
            draft.unlink(missing_ok=True)

    def finish(self) -> None:
        self.pending.unlink(missing_ok=True)
        for snapshot in self.directory.glob("*.before"):
            try:
                snapshot.unlink()
            except OSError:
                pass  # dziennika już nie ma, kopie nie są potrzebne

    def recover(self) -> bool:
        if not self.pending.is_file():
            return False
        allowed_dirs = [self.root / PACKAGE_DIR, self.root / DIFF_DIR, data_root(self.root)]
        try:
            records = json.loads(self.pending.read_text(encoding="utf-8"))
            targets = [Path(os.path.normpath(self.root / r["path"])) for r in records]
        except (ValueError, KeyError, TypeError):
            raise OperationError("Uszkodzony dziennik odzyskiwania. Sprawdź spójność plików gry.")
        if len(set(targets)) != len(targets) or not all(
                any(t.is_relative_to(d) for d in allowed_dirs) for t in targets):
            raise OperationError("Nieprawidłowa lista plików do odzyskania.")
        unresolved = []
        for index in reversed(range(len(records))):
            record, target = records[index], targets[index]
            before = record["before"]
            current = file_hash(target)
            if current == before:
                continue
            snapshot = self.directory / f"{index}.before"
            if current not in record["after"] or (before is not None and not matches(snapshot, before)):
                unresolved.append(target.name)
                continue
            if before is None:
                remove_file(target)
            else:
                atomic_copy(snapshot, target)
        if unresolved:
            raise OperationError(
                "Odzyskiwanie wymaga sprawdzenia spójności plików gry. "
                f"Zachowano pliki i kopie: {', '.join(unresolved)}.")
        self.finish()
        return True

    def apply(self, changes: list, check_cancelled: Callable[[], None]) -> None:
        changes = [c for c in changes if c.before != c.after]
        if not changes:
            return
        check_cancelled()
        self.prepare((c.target, c.before, [c.after]) for c in changes)
        try:
            for change in changes:
                check_cancelled()
                if file_hash(change.target) != change.before:
                    raise OperationError(f"Plik {change.target.name} zmienił się w trakcie operacji.")
                if change.source is None:
                    remove_file(change.target)
                else:
                    atomic_copy(change.source, change.target)
            check_cancelled()
            self.finish()
        except BaseException:
            self.recover()
            raise


# ---------------------------------------------------------------- wersje i status

def read_version_file(root: Path) -> Optional[str]:
    try:
        return (root / PACKAGE_DIR / VERSION_FILE).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def sync_version_file(root: Path) -> None:
    """Plik `polish_version.txt` (jak w starym instalatorze) = wersja zainstalowanego tłumaczenia."""
    path = root / PACKAGE_DIR / VERSION_FILE
    versions = []
    for language in LANGUAGES:
        manifest = load_local_manifest(data_path(root, language), language)
        if manifest:
            versions.append(manifest.version)
    try:
        if versions:
            make_writable(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(versions[0], encoding="utf-8")
        else:
            remove_file(path)
    except OSError:
        pass  # plik informacyjny – prawdziwy stan trzyma manifest


@dataclass
class Status:
    state: str  # no_game | none | legacy | incomplete | outdated | current | unknown
    message: str
    local_version: Optional[str] = None
    server_version: Optional[str] = None


def has_installed_files(root: Path, data: Path, manifest: Manifest) -> bool:
    for spec in manifest.packages:
        if not matches(spec.target(root), spec.sha256):
            return False
    return all(matches(payload_path(data, spec), spec.sha256) for spec in manifest.diffs)


def compute_status(root: Optional[Path], language: str, server_version: Optional[str]) -> Status:
    if root is None:
        return Status("no_game", "NIE ODNALEZIONO GRY!")
    data = data_path(root, language)
    manifest = load_local_manifest(data, language)
    if manifest is None:
        others = any(load_local_manifest(data_path(root, l), l) for l in LANGUAGES if l != language)
        if read_version_file(root) and not others:
            return Status("legacy", "STARA INSTALACJA – ZAINSTALUJ PONOWNIE", read_version_file(root), server_version)
        return Status("none", "BRAK SPOLSZCZENIA", None, server_version)
    if not has_installed_files(root, data, manifest):
        return Status("incomplete", "WYMAGA PONOWNEJ INSTALACJI", manifest.version, server_version)
    if not server_version:
        return Status("unknown", f"ZAINSTALOWANO ({manifest.version})", manifest.version, None)
    if server_version != manifest.version:
        return Status("outdated", f"DOSTĘPNA AKTUALIZACJA (masz {manifest.version})", manifest.version, server_version)
    return Status("current", f"TŁUMACZENIE AKTUALNE ({manifest.version})", manifest.version, server_version)


# ------------------------------------------------------------------ znajdowanie gry

def is_valid_game_path(path) -> bool:
    return bool(path and (Path(path) / PACKAGE_DIR).is_dir())


def steam_libraries(steam_path: Path):
    yield steam_path
    try:
        text = (steam_path / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return
    for found in re.findall(r'^\s*"path"\s*"([^"]+)"', text, re.MULTILINE):
        yield Path(found.replace("\\\\", "\\"))


LAUNCHER_CANDIDATES = [
    r"C:\Program Files\wwm\wwm_standard", r"C:\Program Files\wwm\wwm_lite",
    r"C:\Program Files (x86)\wwm\wwm_standard", r"C:\Program Files (x86)\wwm\wwm_lite",
    r"C:\NetEase\WWM\wwm_standard", r"C:\NetEase\WWM\wwm_lite",
    r"C:\NetEase Games\WWM\wwm_standard", r"C:\NetEase Games\WWM\wwm_lite",
    r"C:\Games\Where Winds Meet\wwm_standard", r"C:\Games\Where Winds Meet\wwm_lite",
    r"D:\Games\Where Winds Meet\wwm_standard", r"D:\Games\Where Winds Meet\wwm_lite",
    r"E:\Games\Where Winds Meet\wwm_standard", r"E:\Games\Where Winds Meet\wwm_lite",
    r"C:\WWM\wwm_standard", r"C:\WWM\wwm_lite", r"D:\WWM\wwm_standard", r"D:\WWM\wwm_lite",
    r"C:\Program Files\Epic Games\WhereWindsMeet\wwm_standard",
    r"C:\Program Files (x86)\Epic Games\WhereWindsMeet\wwm_standard",
    r"D:\Epic Games\WhereWindsMeet\wwm_standard",
    r"C:\Users\Public\Games\Where Winds Meet\wwm_standard",
    r"C:\Users\Public\Games\Where Winds Meet\wwm_lite",
]


def find_game_path(platform: str) -> Optional[str]:
    if platform == "steam":
        if winreg is None:
            return None
        locations = (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Valve\Steam", "InstallPath"),
        )
        for hive, key_name, value in locations:
            try:
                with winreg.OpenKey(hive, key_name) as key:
                    steam_path = Path(winreg.QueryValueEx(key, value)[0])
            except OSError:
                continue
            for library in steam_libraries(steam_path):
                candidate = library / "steamapps" / "common" / "Where Winds Meet"
                if is_valid_game_path(candidate):
                    return str(candidate.resolve())
        return None
    for candidate in LAUNCHER_CANDIDATES:
        if is_valid_game_path(candidate):
            return os.path.abspath(os.path.normpath(candidate))
    return None


def start_game(game_path: str, platform: str, notify: Callable[[str], None]) -> None:
    """Uruchamia grę przez Steam lub plik .exe launchera. Błędy zgłasza komunikatem, nie wyjątkiem."""
    opener = getattr(os, "startfile", None)
    if opener is None:
        notify("Uruchamianie gry jest dostępne tylko w Windows. Uruchom grę ręcznie.")
        return
    if platform == "steam":
        try:
            opener(f"steam://rungameid/{STEAM_APP_ID}")
        except OSError:
            notify("Steam nie odpowiedział automatycznie. Uruchom grę ręcznie z biblioteki.")
        return
    names = ("WhereWindsMeet.exe", "WWM.exe", "WWM_Game.exe", "Launcher.exe")
    for current, dirs, files in os.walk(game_path):
        if len(Path(current).relative_to(game_path).parts) >= 3:
            dirs.clear()
        for name in names:
            if name in files:
                try:
                    opener(os.path.join(current, name))
                except OSError:
                    notify("Nie udało się włączyć gry automatycznie. Uruchom ją ręcznie.")
                return
    notify("Nie znaleziono pliku .exe. Uruchom grę ręcznie ze swojej platformy.")
