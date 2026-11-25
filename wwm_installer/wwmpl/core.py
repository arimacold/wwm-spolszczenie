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
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
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
# Wersja ze Steam trzyma pliki tłumaczeń w Package\…\locale, a wersja z oficjalnego launchera
# w LocalData\Patch\…\locale (tam też gra pobiera pliki *_diff).


def main_dir(root: Path, name: str) -> Path:
    """Folder pliku głównego: tam, gdzie gra go faktycznie trzyma (Patch ma pierwszeństwo, jak w grze)."""
    if (root / DIFF_DIR / name).exists():
        return DIFF_DIR
    if (root / PACKAGE_DIR).is_dir():
        return PACKAGE_DIR
    return DIFF_DIR
DATA_DIR = Path("Spolszczenie_Data", "WWMPL")
VERSION_FILE = "polish_version.txt"
# Warianty tłumaczenia: klucz -> (nazwa, podfolder w repozytorium). Pełne leży w katalogu głównym repo.
VARIANTS = {"full": ("Pełne", ""), "story": ("Fabularne", "fabula/")}
DEFAULT_VARIANT = "full"


def variant_url(base_url: str, variant: str) -> str:
    base = base_url if base_url.endswith("/") else base_url + "/"
    return base + VARIANTS.get(variant, VARIANTS[DEFAULT_VARIANT])[1]
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
        return root / (DIFF_DIR if self.is_diff else main_dir(root, self.name)) / self.name

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
    variant: str = DEFAULT_VARIANT

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
        variant = payload.get("variant") if isinstance(payload, dict) else None
        return cls(version.strip(), language, files, variant if variant in VARIANTS else DEFAULT_VARIANT)

    def dump(self) -> dict:
        return {"version": self.version, "variant": self.variant,
                "languages": {self.language: {"files": {n: s.to_json() for n, s in self.files.items()}}}}

    def without(self, names: Iterable[str]) -> "Manifest":
        skip = set(names)
        return Manifest(self.version, self.language, {n: s for n, s in self.files.items() if n not in skip},
                        self.variant)

    def with_originals(self, mapping: dict) -> "Manifest":
        """Kopia manifestu, w której wskazane pliki mają inną sumę „oryginału" (wersja gry nowsza niż tłumaczenie)."""
        files = {n: (replace(s, original=mapping[n]) if n in mapping else s) for n, s in self.files.items()}
        return Manifest(self.version, self.language, files, self.variant)

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

def version_file_path(root: Path) -> Path:
    return root / (PACKAGE_DIR if (root / PACKAGE_DIR).is_dir() else DIFF_DIR) / VERSION_FILE


def read_version_file(root: Path) -> Optional[str]:
    for folder in (PACKAGE_DIR, DIFF_DIR):
        try:
            value = (root / folder / VERSION_FILE).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return None


def sync_version_file(root: Path) -> None:
    """Plik `polish_version.txt` (jak w starym instalatorze) = wersja zainstalowanego tłumaczenia."""
    path = version_file_path(root)
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
    restored: bool = False   # launcher przywrócił oryginał pliku głównego – wgramy go z kopii przy starcie gry


def launcher_restored(root: Path, data: Path, spec: FileSpec) -> bool:
    """Wersja z launchera: po zamknięciu gry launcher weryfikuje pliki i przywraca oryginał pliku głównego
    w LocalData\\Patch. To nie jest uszkodzona instalacja – tłumaczenie leży w kopii (payload) i wraca przy
    uruchomieniu gry przez instalator, bez ponownego pobierania."""
    target = spec.target(root)
    return (not spec.is_diff and target.parent == root / DIFF_DIR
            and file_hash(target) == spec.original and matches(payload_path(data, spec), spec.sha256))


def restored_packages(root: Path, data: Path, manifest: Manifest) -> list:
    return [spec for spec in manifest.packages if launcher_restored(root, data, spec)]


def has_installed_files(root: Path, data: Path, manifest: Manifest, allow_restored: bool = True) -> bool:
    for spec in manifest.packages:
        if matches(spec.target(root), spec.sha256):
            continue
        if allow_restored and launcher_restored(root, data, spec):
            continue
        return False
    return all(matches(payload_path(data, spec), spec.sha256) for spec in manifest.diffs)


def compute_status(root: Optional[Path], language: str, server_version: Optional[str],
                   variant: str = DEFAULT_VARIANT) -> Status:
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
    restored = bool(restored_packages(root, data, manifest))
    if manifest.variant != variant:
        name = VARIANTS[manifest.variant][0].upper()
        status = Status("other_variant", f"ZAINSTALOWANO WARIANT {name} ({manifest.version})",
                        manifest.version, server_version)
    elif not server_version:
        status = Status("unknown", f"ZAINSTALOWANO ({manifest.version})", manifest.version, None)
    elif server_version != manifest.version:
        status = Status("outdated", f"DOSTĘPNA AKTUALIZACJA (masz {manifest.version})", manifest.version,
                        server_version)
    else:
        status = Status("current", f"TŁUMACZENIE AKTUALNE ({manifest.version})", manifest.version, server_version)
    status.restored = restored
    return status


# ------------------------------------------------------------------ znajdowanie gry

def is_valid_game_path(path) -> bool:
    """Główny folder gry: Steam/Epic mają Package/…/locale, oficjalny launcher – LocalData/Patch."""
    if not path:
        return False
    root = Path(path)
    return (root / PACKAGE_DIR).is_dir() or (root / DIFF_DIR).is_dir() or (root / "LocalData" / "Patch").is_dir()


PREFERRED_SUBFOLDERS = ("wwm_standard", "wwm_ultimate", "wwm_lite", "Where Winds Meet", "WhereWindsMeet", "wwm")


def resolve_game_root(path) -> Optional[Path]:
    """Poprawia ręcznie wskazany folder: szuka korzenia gry w górę (np. wskazano locale lub Engine/Binaries)
    i w dół (np. wskazano folder „wwm” z podfolderami wwm_standard / wwm_lite)."""
    if not path:
        return None
    try:
        start = Path(os.path.abspath(os.path.normpath(str(path))))
    except (OSError, ValueError):
        return None
    current = start
    for _ in range(8):
        if is_valid_game_path(current):
            return current
        if current.parent == current:
            break
        current = current.parent
    level1 = []
    try:
        level1 = [child for child in start.iterdir() if child.is_dir()]
    except OSError:
        pass
    rank = {name.casefold(): i for i, name in enumerate(PREFERRED_SUBFOLDERS)}
    level1.sort(key=lambda child: (rank.get(child.name.casefold(), 99), child.name.casefold()))
    for child in level1:
        if is_valid_game_path(child):
            return child
    for child in level1[:40]:
        try:
            grandchildren = sorted((g for g in child.iterdir() if g.is_dir()),
                                   key=lambda g: (rank.get(g.name.casefold(), 99), g.name.casefold()))
        except OSError:
            continue
        for grandchild in grandchildren:
            if is_valid_game_path(grandchild):
                return grandchild
    return None


def steam_libraries(steam_path: Path):
    yield steam_path
    try:
        text = (steam_path / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return
    for found in re.findall(r'^\s*"path"\s*"([^"]+)"', text, re.MULTILINE):
        yield Path(found.replace("\\\\", "\\"))


# Względne ścieżki sprawdzane na każdym dysku (C:, D:, E: …) – typowe miejsca instalacji launchera i Epic.
LAUNCHER_RELATIVE = [
    r"wwm", r"wwm\wwm_standard", r"wwm\wwm_lite", r"wwm_standard", r"wwm_lite", r"wwm_ultimate",
    r"Where Winds Meet", r"WhereWindsMeet",
    r"Games\wwm", r"Games\Where Winds Meet", r"Games\WhereWindsMeet",
    r"Program Files\wwm", r"Program Files (x86)\wwm", r"Program Files\Where Winds Meet",
    r"Program Files\Epic Games\WhereWindsMeet", r"Program Files (x86)\Epic Games\WhereWindsMeet",
    r"Epic Games\WhereWindsMeet", r"Epic Games\Where Winds Meet",
    r"NetEase\WWM", r"NetEase Games\WWM", r"NetEase\Where Winds Meet", r"NetEase Games\Where Winds Meet",
    r"Users\Public\Games\Where Winds Meet",
]
LAUNCHER_CANDIDATES = [rf"C:\{rel}" for rel in LAUNCHER_RELATIVE]   # zgodność wsteczna (testy, stary kod)


def _available_drives() -> list:
    if os.name != "nt":
        return []
    drives = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        if os.path.exists(root):
            drives.append(root)
    return drives


def _looks_like_wwm(display: str, key_name: str) -> bool:
    text = f"{display} {key_name}".casefold()
    if any(hint in text for hint in ("where winds meet", "wherewindsmeet", "燕云十六声")):
        return True
    return display.casefold().startswith("wwm") or key_name.casefold().startswith("wwm")


def _path_from_registry_value(raw: str) -> Optional[Path]:
    """InstallLocation / DisplayIcon ("C:\\x\\a.exe",0) / UninstallString ("C:\\x\\uninst.exe" /S) -> folder."""
    raw = (raw or "").strip()
    if not raw:
        return None
    quoted = re.match(r'\s*"([^"]+)"', raw)
    if quoted:
        raw = quoted.group(1)
    else:
        exe = re.match(r"(.+?\.(?:exe|ico|dll))\b", raw, re.IGNORECASE)
        raw = exe.group(1) if exe else raw.split(",")[0]
    candidate = Path(raw.strip())
    if candidate.suffix.lower() in (".exe", ".ico", ".dll"):
        candidate = candidate.parent
    return candidate


def _registry_install_locations(log) -> list:
    """Wpisy „Programy i funkcje” (rejestr) – oficjalny launcher zwykle zapisuje tu miejsce instalacji."""
    found = []
    if winreg is None:
        return found
    roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for hive, key_name in roots:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                count = winreg.QueryInfoKey(key)[0]
                for index in range(count):
                    try:
                        sub_name = winreg.EnumKey(key, index)
                        with winreg.OpenKey(key, sub_name) as sub:
                            def value(name):
                                try:
                                    return str(winreg.QueryValueEx(sub, name)[0])
                                except OSError:
                                    return ""
                            display = value("DisplayName")
                            if not _looks_like_wwm(display, sub_name):
                                continue
                            for raw in (value("InstallLocation"), value("DisplayIcon"), value("UninstallString")):
                                candidate = _path_from_registry_value(raw)
                                if candidate is not None:
                                    log.info("Rejestr: %s -> %s", display or sub_name, candidate)
                                    found.append(candidate)
                    except OSError:
                        continue
        except OSError:
            continue
    return found


def _epic_install_locations(log) -> list:
    found = []
    manifests = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    try:
        items = list(manifests.glob("*.item"))
    except OSError:
        return found
    for item in items:
        try:
            data = json.loads(item.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        name = f"{data.get('DisplayName', '')} {data.get('AppName', '')}".casefold()
        if "where winds" in name or "wherewinds" in name:
            location = data.get("InstallLocation")
            if location:
                log.info("Epic: %s -> %s", data.get("DisplayName"), location)
                found.append(Path(location))
    return found


def find_game_path(platform: str) -> Optional[str]:
    from . import logs
    log = logs.get()
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
                    log.info("Steam: znaleziono grę w %s", candidate)
                    return str(candidate.resolve())
                log.debug("Steam: brak gry w %s", candidate)
        log.warning("Steam: nie znaleziono gry w bibliotekach Steam")
        return None

    return find_launcher_game(log)


LAUNCHER_GAME_FOLDERS = ("wwm_standard", "wwm_lite", "wwm_ultimate")
_LAUNCHER_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\"'\r\n<>|*?]{0,240}?wwm_(?:standard|lite|ultimate)", re.IGNORECASE)


def is_steam_path(path) -> bool:
    return "steamapps" in str(path).casefold()


def _recent_activity(root: Path) -> float:
    """Kiedy ostatnio gra była używana (najnowsza zmiana w LocalData) – do wyboru przy kilku instalacjach."""
    for folder in (root / DIFF_DIR, root / "LocalData" / "Patch", root / "LocalData", root):
        try:
            return folder.stat().st_mtime      # gra odświeża ten folder przy każdym uruchomieniu
        except OSError:
            continue
    return 0.0


def _launcher_config_paths(folders: list, log) -> list:
    """Pliki konfiguracyjne launchera (np. C:\\Program Files\\wwm) – szukamy w nich ścieżek wwm_standard/lite."""
    found = []
    for folder in folders:
        try:
            if not folder.is_dir():
                continue
        except OSError:
            continue
        for current, dirs, files in os.walk(folder):
            if len(Path(current).relative_to(folder).parts) >= 3:
                dirs.clear()
            for name in files:
                if not name.casefold().endswith((".json", ".ini", ".cfg", ".txt", ".xml", ".config", ".conf", ".dat", ".yaml")):
                    continue
                path = Path(current) / name
                try:
                    if path.stat().st_size > 2_000_000:
                        continue
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for match in _LAUNCHER_PATH_RE.findall(text.replace("\\\\", "\\")):
                    log.info("Konfiguracja launchera %s: %s", path.name, match)
                    found.append(Path(match.replace("/", "\\") if os.name == "nt" else match))
    return found


def _drive_scan_candidates() -> list:
    """Na każdym dysku: X:\\wwm_standard, X:\\<folder>\\wwm_standard, X:\\<folder>\\wwm\\wwm_standard (+ lite/ultimate)."""
    found = []
    for drive in _available_drives():
        root = Path(drive)
        found.extend(root / rel for rel in LAUNCHER_RELATIVE)
        try:
            children = [child for child in root.iterdir() if child.is_dir()][:300]
        except OSError:
            continue
        for child in children:
            if child.name.casefold() in ("windows", "$recycle.bin", "system volume information", "programdata"):
                continue
            for folder in LAUNCHER_GAME_FOLDERS:
                found.append(child / folder)
                found.append(child / "wwm" / folder)
    return found


def _netease_launcher_dirs(log) -> list:
    """HKCU\\Software\\Netease\\wwm -> installpath (folder launchera, np. C:\\Program Files\\wwm)."""
    found = []
    if winreg is None:
        return found
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key_name in (r"Software\Netease\wwm", r"SOFTWARE\WOW6432Node\Netease\wwm"):
            try:
                with winreg.OpenKey(hive, key_name) as key:
                    value = str(winreg.QueryValueEx(key, "installpath")[0]).strip().strip('"')
            except OSError:
                continue
            if value:
                log.info("Rejestr Netease\\wwm: folder launchera %s", value)
                found.append(Path(value))
    return found


def launcher_setting_paths(launcher_dirs: list, log) -> list:
    """InstallPath z setting.ini launchera (Win32\\deploy\\setting.ini) – zapis samego launchera, gdzie jest gra."""
    found = []
    for folder in launcher_dirs:
        for ini in (folder / "Win32" / "deploy" / "setting.ini", folder / "deploy" / "setting.ini",
                    folder / "setting.ini"):
            try:
                text = ini.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line in text.splitlines():
                key, sep, value = line.partition("=")
                if sep and key.strip().casefold() == "installpath" and value.strip():
                    raw = value.strip().strip('"')
                    path = Path(raw.replace("/", "\\") if os.name == "nt" else raw)
                    log.info("setting.ini launchera (%s): InstallPath=%s", ini, raw)
                    found.append(path)
    return found


def find_launcher_game(log) -> Optional[str]:
    """Oficjalny launcher / Epic – bez instalacji ze Steama.
    Kolejność: setting.ini launchera (pewne) -> ślady uruchomień, konfiguracja, Epic, dyski (ostatnio używana)."""
    install_dirs = _registry_install_locations(log)
    launcher_dirs = _netease_launcher_dirs(log) + [d for d in install_dirs if not is_steam_path(d)]
    expanded = []
    for folder in launcher_dirs:            # DisplayIcon wskazuje Win32\\deploy – dodaj też folder główny
        expanded.append(folder)
        if folder.name.casefold() == "deploy" and folder.parent.name.casefold() == "win32":
            expanded.append(folder.parent.parent)
    launcher_dirs = list({str(d).casefold(): d for d in expanded}.values())
    for path in launcher_setting_paths(launcher_dirs, log):
        if is_steam_path(path):
            continue
        root = resolve_game_root(path) if path.exists() else None
        if root is not None and not is_steam_path(root):
            log.info("Launcher: gra wg setting.ini -> %s", root)
            return str(root)
        log.warning("setting.ini wskazuje %s, ale nie ma tam plików gry", path)
    launcher_dirs = [d for d in install_dirs if not is_steam_path(d)]
    candidates = []
    candidates += _launcher_config_paths(launcher_dirs, log)
    candidates += launcher_dirs
    candidates += _epic_install_locations(log)
    candidates += _drive_scan_candidates()
    candidates += [Path(c) for c in LAUNCHER_CANDIDATES]
    roots, tried = {}, set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key in tried or is_steam_path(candidate):
            continue
        tried.add(key)
        try:
            if not candidate.exists():
                continue
        except OSError:
            continue
        root = resolve_game_root(candidate)
        if root is None or is_steam_path(root):
            continue
        roots.setdefault(str(root).casefold(), root)
    if not roots:
        log.warning("Launcher/Epic: nie znaleziono gry automatycznie (sprawdzono %d miejsc)", len(tried))
        return None
    ranked = sorted(roots.values(), key=_recent_activity, reverse=True)
    for root in ranked:
        log.info("Launcher/Epic: instalacja %s (ostatnia aktywność: %s)", root,
                 time.strftime("%Y-%m-%d %H:%M", time.localtime(_recent_activity(root))))
    log.info("Launcher/Epic: wybrano %s", ranked[0])
    return str(ranked[0])


def describe_game_folder(root) -> str:
    """Krótki opis do logu: które foldery z plikami tłumaczeń istnieją."""
    root = Path(root)
    parts = []
    for label, folder in (("Package/locale", PACKAGE_DIR), ("LocalData/Patch/locale", DIFF_DIR)):
        path = root / folder
        if path.is_dir():
            try:
                names = sorted(p.name for p in path.iterdir() if p.name.startswith("translate_words_map_"))
            except OSError:
                names = []
            parts.append(f"{label}: {len(names)} plików ({', '.join(n.replace('translate_words_map_', '') for n in names[:8])})")
        else:
            parts.append(f"{label}: brak")
    return "; ".join(parts)


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
    from . import logs
    log = logs.get()
    exe = find_official_launcher(log) if platform != "steam" else None
    exe = exe or find_launch_exe(Path(game_path))
    if exe is None:
        log.warning("Nie znaleziono pliku .exe gry/launchera w %s", game_path)
        notify("Nie znaleziono pliku .exe. Uruchom grę ręcznie ze swojej platformy – instalator poczeka na nią.")
        return
    log.info("Uruchamiam: %s", exe)
    try:
        opener(str(exe))
    except OSError as error:
        log.error("Nie udało się uruchomić %s: %s", exe, error)
        notify("Nie udało się włączyć gry automatycznie. Uruchom ją ręcznie – instalator poczeka na nią.")


GAME_EXE_NAMES = ("wherewindsmeet.exe", "wwm.exe", "wwm_game.exe")
GAME_PROCESS = "wwm.exe"


def game_exe_candidates(root: Path) -> list:
    """Pliki wwm.exe gry (wersja globalna Win64r, serwery HK/TW Win64rh) – bez względu na wielkość liter."""
    found = []
    binaries = Path(root) / "Engine" / "Binaries"
    try:
        folders = [d for d in binaries.iterdir() if d.is_dir() and d.name.casefold().startswith("win64")]
    except OSError:
        return found
    for folder in folders:
        try:
            found += [f for f in folder.iterdir() if f.name.casefold() == GAME_PROCESS]
        except OSError:
            continue
    return found


IS_WINDOWS = os.name == "nt"


def process_running(root) -> bool:
    """Czy gra działa – bez przeglądania listy procesów. Windows blokuje plik uruchomionego programu, więc
    próba otwarcia wwm.exe do zapisu kończy się odmową dostępu. Nic nie jest zapisywane: plik jest tylko
    otwierany i od razu zamykany; pliki „tylko do odczytu” pomijamy, by nie dawały fałszywego wyniku."""
    if not IS_WINDOWS or root is None:
        return False
    for exe in game_exe_candidates(Path(root)):
        try:
            if not os.access(exe, os.W_OK):
                continue
            with open(exe, "r+b"):
                pass
        except PermissionError:
            return True
        except OSError:
            continue
    return False


def find_official_launcher(log=None) -> Optional[Path]:
    """launcher.exe oficjalnego klienta (np. C:\\Program Files\\wwm) – z wpisu instalacji w rejestrze."""
    from . import logs
    log = log or logs.get()
    for folder in _netease_launcher_dirs(log) + _registry_install_locations(log):
        if is_steam_path(folder):
            continue
        direct = folder / "Win32" / "deploy" / "launcher.exe"
        if direct.is_file():
            return direct
        try:
            for current, dirs, files in os.walk(folder):
                if len(Path(current).relative_to(folder).parts) >= 3:
                    dirs.clear()
                for name in files:
                    lower = name.casefold()
                    if lower.endswith(".exe") and "launcher" in lower and "uninst" not in lower:
                        return Path(current) / name
        except (OSError, ValueError):
            continue
    return None


def find_launch_exe(root: Path) -> Optional[Path]:
    """Najpierw launcher (pilnuje aktualizacji gry), potem plik gry – bez względu na wielkość liter."""
    for folder in (root, root.parent):
        try:
            for item in sorted(folder.iterdir()):
                lower = item.name.casefold()
                if item.is_file() and lower.endswith(".exe") and "launcher" in lower and "uninst" not in lower:
                    return item
        except OSError:
            continue
    best = None
    for current, dirs, files in os.walk(root):
        depth = len(Path(current).relative_to(root).parts)
        if depth >= 4:
            dirs.clear()
        dirs[:] = [d for d in dirs if d.casefold() not in ("package", "localdata", "spolszczenie_data")]
        for name in files:
            if name.casefold() in GAME_EXE_NAMES:
                path = Path(current) / name
                # wersja globalna gry leży w Engine\Binaries\Win64r
                if best is None or ("win64r" in str(path).casefold() and "win64r" not in str(best).casefold()):
                    best = path
    return best
