"""Operacje instalatora: instalacja, przywracanie i injector „w locie".
Brak zależności od GUI – postęp i komunikaty przekazywane przez wywołania zwrotne."""
from __future__ import annotations

import json
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import requests

from . import logs

from .core import (
    DEFAULT_VARIANT, RAW_URL, VARIANTS, Cancelled, Change, FileSpec, Journal, LANGUAGES, Manifest, OperationError,
    adopt_legacy_backup, atomic_copy, data_path, file_hash, game_lock, has_installed_files,
    load_local_manifest, matches, original_backup, payload_path, read_version_file, remove_file,
    save_original, sha256_file, start_game, sync_version_file, variant_url, describe_game_folder,
    DIFF_DIR, process_running,
)

Progress = Callable[[float, str], None]


def fetch_server_version(base_url: str = RAW_URL, session=None, timeout: float = 5) -> Optional[str]:
    try:
        response = (session or requests).get(base_url + "version.txt", timeout=timeout)
        response.raise_for_status()
        return response.text.strip() or None
    except requests.RequestException:
        return None


def _short(digest) -> str:
    return digest[:12] if digest else "brak"


def _mb(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MB"


class ForeignVersionError(OperationError):
    """Gra pobrała plik różnicowy innej wersji niż oryginał z manifestu (np. po aktualizacji gry)."""


class Engine:
    WATCH_TIMEOUT = 300      # s – tyle czekamy, aż gra utworzy plik różnicowy
    CONFIRM_SECONDS = 8      # s – tyle plik musi pozostać podmieniony
    GERMAN_FALLBACK = 8      # s – plik DE nie pojawił się = tłumaczenie jest już w plikach gry
    FOREIGN_SECONDS = 3      # s – tyle plik od gry musi stabilnie różnić się od oryginału, by uznać go za inną wersję
    # Oficjalny launcher sam weryfikuje i pobiera pliki ZANIM uruchomi grę – dlatego czekamy na proces gry:
    LAUNCHER_WATCH_TIMEOUT = 1200   # s – czas na kliknięcie „Graj” (launcher może też pobierać aktualizację)
    GAME_CONFIRM_SECONDS = 30       # s – tyle gra musi działać z naszym tłumaczeniem, zanim ogłosimy sukces

    def __init__(self, root, language: str, progress: Progress,
                 cancelled: Optional[threading.Event] = None, base_url: str = RAW_URL,
                 notify: Optional[Callable[[str], None]] = None, session=None,
                 confirm: Optional[Callable[[list], bool]] = None, variant: str = DEFAULT_VARIANT):
        self.root = Path(root)
        self.language = language
        self.data = data_path(self.root, language)
        self.progress = progress
        self.cancelled = cancelled or threading.Event()
        self.repo_url = base_url if base_url.endswith("/") else base_url + "/"
        self.variant = variant if variant in VARIANTS else DEFAULT_VARIANT
        self.base_url = variant_url(self.repo_url, self.variant)   # pliki i manifest wybranego wariantu
        self.notify = notify or (lambda text: None)
        self.http = session or requests.Session()
        self.confirm = confirm         # pytanie „użyć mimo nowszej wersji gry?"; bez niego silnik jest restrykcyjny
        self._decision: Optional[bool] = None
        self._accepted: set = set()    # sumy obcych (nowszych) plików gry, które użytkownik zaakceptował
        self._foreign_seen = False
        self.skipped: list = []
        self.logger = logs.get()

    # ------------------------------------------------------------------ pomocnicze
    def check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise Cancelled()

    def fetch_manifest(self) -> Manifest:
        self.check_cancelled()
        try:
            response = self.http.get(self.base_url + "files/manifest.json", timeout=15)
            response.raise_for_status()
            payload = response.json()
        except requests.HTTPError as error:
            status = getattr(error.response, "status_code", None)
            if status == 404 and self.variant != DEFAULT_VARIANT:
                raise OperationError(f"Wariant „{VARIANTS[self.variant][0]}” nie jest jeszcze dostępny na serwerze. "
                                     "Wybierz wariant Pełne albo spróbuj później.") from error
            raise OperationError(f"Nie udało się pobrać manifestu tłumaczenia: {error}") from error
        except (requests.RequestException, ValueError) as error:
            raise OperationError(f"Nie udało się pobrać manifestu tłumaczenia: {error}") from error
        return Manifest.parse(payload, self.language)

    def _download(self, spec: FileSpec, target: Path, base: float, share: float) -> None:
        parts = spec.parts or (spec.name,)
        with target.open("wb") as stream:
            for index, part in enumerate(parts):
                offset = stream.tell()
                url = f"{self.base_url}files/{self.language}/{part}"
                for attempt in range(3):
                    stream.seek(offset)
                    stream.truncate()
                    try:
                        with self.http.get(url, stream=True, timeout=30) as response:
                            response.raise_for_status()
                            total = int(response.headers.get("Content-Length", 0))
                            done = 0
                            for chunk in response.iter_content(chunk_size=256 * 1024):
                                self.check_cancelled()
                                stream.write(chunk)
                                done += len(chunk)
                                fraction = done / total if total else 0
                                value = base + share * (index + fraction) / len(parts)
                                tail = f" ({_mb(done)} / {_mb(total)})" if total else ""
                                self.progress(value, f"Pobieranie: {spec.name}{tail}")
                        break
                    except requests.RequestException as error:
                        if attempt == 2:
                            raise OperationError(f"Błąd pobierania pliku {part}: {error}") from error
                        self.cancelled.wait(1.5 * (attempt + 1))
                        self.check_cancelled()
        if not matches(target, spec.sha256):
            target.unlink(missing_ok=True)
            raise OperationError(f"Nieprawidłowa suma kontrolna pliku {spec.name}. Spróbuj ponownie.")

    def _guarded(self, manifest: Manifest) -> list:
        """Pliki główne leżące w LocalData\\Patch (wersja z launchera) – launcher może je przywracać."""
        return [spec for spec in manifest.packages if spec.target(self.root).parent == self.root / DIFF_DIR]

    def _allow_mismatch(self, names: list) -> bool:
        """Pyta (raz na operację), czy użyć tłumaczenia mimo że plik gry jest w nowszej wersji niż tłumaczenie."""
        if self._decision is None:
            if self.confirm is None:
                return False
            self.progress(0.30, "Czekam na Twoją decyzję…")
            self._decision = bool(self.confirm(list(names)))
        return self._decision

    def _download_original(self, spec: FileSpec, staging: Path) -> Optional[Path]:
        """Ostatnia deska ratunku przy przywracaniu: oryginał z repozytorium, zweryfikowany sumą."""
        target = staging / ("orig_" + spec.name)
        try:
            with self.http.get(f"{self.repo_url}files/orginal/{spec.name}", stream=True, timeout=30) as response:
                response.raise_for_status()
                with target.open("wb") as stream:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        self.check_cancelled()
                        stream.write(chunk)
        except requests.RequestException:
            return None
        return target if matches(target, spec.original) else None

    # -------------------------------------------------------------------- instalacja
    def install(self) -> Manifest:
        self.logger.info("INSTALACJA: język=%s wariant=%s folder=%s", self.language, self.variant, self.root)
        self.logger.info("Folder gry: %s", describe_game_folder(self.root))
        self.progress(0.02, "Pobieranie informacji o tłumaczeniu…")
        manifest = self.fetch_manifest()
        self.logger.info("Manifest z serwera: wersja %s, pliki: %s (%s)", manifest.version,
                      ", ".join(manifest.files), self.base_url)
        with game_lock(self.root):
            journal = Journal(self.root)
            journal.recover()
            previous = load_local_manifest(self.data, self.language)
            applied = self._install(manifest, previous, journal)
        sync_version_file(self.root)
        self.logger.info("Zainstalowano wersję %s (%s), pominięte: %s", applied.version, applied.variant,
                      ", ".join(self.skipped) or "—")
        return applied

    def _install(self, manifest: Manifest, previous: Optional[Manifest], journal: Journal) -> Manifest:
        root, data = self.root, self.data
        prev_files = previous.files if previous else {}
        legacy = previous is None and read_version_file(root) is not None
        data.mkdir(parents=True, exist_ok=True)
        self.skipped = []
        with tempfile.TemporaryDirectory(dir=data) as directory:
            staging = Path(directory)
            changes: list = []
            jobs: list = []
            overrides: dict = {}
            for spec in manifest.packages:
                self.check_cancelled()
                target = spec.target(root)
                if spec.optional and not target.exists():
                    self.skipped.append(spec.name)  # pliki small: brak w grze = pomijamy bez błędu
                    continue
                current = file_hash(target)
                known = prev_files.get(spec.name)
                problem = None
                self.logger.info("Plik %s -> %s | w grze=%s oryginał=%s tłumaczenie=%s", spec.name, target,
                              _short(current), _short(spec.original), _short(spec.sha256))
                if current is None and not spec.optional:
                    where = "LocalData\\Patch" if target.parent.parts[-5:-4] == ("LocalData",) else "Package"
                    raise OperationError(
                        f"W folderze gry nie ma pliku {spec.name} ({where}\\…\\locale). Uruchom grę raz przez "
                        f"Steam lub launcher i wybierz w ustawieniach język {LANGUAGES[self.language]}, aby gra "
                        "pobrała pliki językowe. Potem zamknij grę i zainstaluj spolszczenie ponownie.")
                if current == spec.original:
                    save_original(data, target, current)
                elif current == spec.sha256:
                    pass
                elif current is not None and ((known and current == known.sha256) or legacy):
                    if original_backup(data, spec.name, spec.original) is None and \
                            adopt_legacy_backup(data, target, spec.original) is None:
                        problem = (f"Nie znaleziono kopii oryginału pliku {spec.name}. Sprawdź spójność "
                                   "plików gry w Steam lub launcherze, a potem zainstaluj ponownie.")
                elif current is not None and not spec.optional and self._allow_mismatch([spec.name]):
                    # gra nowsza niż tłumaczenie, a użytkownik zdecydował: używamy mimo to. Prawdziwy plik gry
                    # trafia do kopii i staje się „oryginałem" tej instalacji (przywracanie odda właśnie jego).
                    save_original(data, target, current)
                    overrides[spec.name] = current
                elif current is not None and not spec.optional and self.confirm is not None:
                    raise Cancelled()
                else:
                    problem = (f"Niezgodna wersja pliku {spec.name} – gra mogła zostać zaktualizowana. "
                               "Sprawdź spójność plików gry albo poczekaj na aktualizację tłumaczenia.")
                if problem:
                    self.logger.warning("Problem z %s: %s", spec.name, problem)
                    if spec.optional:
                        self.skipped.append(spec.name)
                        continue
                    raise OperationError(problem)
                if current != spec.sha256:
                    jobs.append(spec)
                    changes.append(Change(target, current, staging / spec.name, spec.sha256))

            for spec in manifest.diffs:
                old = prev_files.get(spec.name)
                target = spec.target(root)
                if old and old.sha256 != spec.sha256 and file_hash(target) == old.sha256:
                    # stary plik różnicowy z tłumaczeniem: cofamy do oryginału (gra i tak pobierze go ponownie)
                    backup = original_backup(data, spec.name, old.original)
                    changes.append(Change(target, old.sha256, backup, old.original if backup else None))
                if not matches(payload_path(data, spec), spec.sha256):
                    jobs.append(spec)

            for index, spec in enumerate(jobs):
                self.check_cancelled()
                cached = payload_path(data, spec)
                if matches(cached, spec.sha256):
                    # tłumaczenie tej wersji już leży w kopii (np. launcher przywrócił oryginał) – bez pobierania
                    self.progress(0.05 + 0.80 * (index + 1) / len(jobs), f"Kopia lokalna: {spec.name}")
                    self.logger.info("%s: używam lokalnej kopii tłumaczenia (bez pobierania)", spec.name)
                    atomic_copy(cached, staging / spec.name)
                    continue
                self._download(spec, staging / spec.name, 0.05 + 0.80 * index / len(jobs), 0.80 / len(jobs))
            for spec in manifest.diffs:
                if (staging / spec.name).exists():
                    atomic_copy(staging / spec.name, payload_path(data, spec))

            applied = manifest.without(self.skipped).with_originals(overrides)
            applied.variant = self.variant
            staged = staging / "manifest.json"
            staged.write_text(json.dumps(applied.dump(), indent=2), encoding="utf-8")
            local = data / "manifest.json"
            changes.append(Change(local, file_hash(local), staged, sha256_file(staged)))
            self.progress(0.92, "Zapisywanie plików gry…")
            journal.apply(changes, self.check_cancelled)

        for spec in self._guarded(applied):
            payload = payload_path(data, spec)
            if not matches(payload, spec.sha256) and matches(spec.target(root), spec.sha256):
                atomic_copy(spec.target(root), payload)     # kopia do odtworzenia, gdy launcher go nadpisze
        keep = {spec.sha256 for spec in applied.diffs} | {spec.sha256 for spec in self._guarded(applied)}
        for stale in (data / "payload").glob("*.pol"):
            if stale.stem not in keep:
                stale.unlink(missing_ok=True)
        self.progress(1.0, "Zakończono.")
        return applied

    # ------------------------------------------------------------------ przywracanie
    def restore(self) -> list:
        """Zwraca listę plików, których nie dało się bezpiecznie przywrócić."""
        self.logger.info("PRZYWRACANIE: język=%s folder=%s", self.language, self.root)
        self.progress(0.05, "Sprawdzanie plików…")
        root, data = self.root, self.data
        with game_lock(root):
            journal = Journal(root)
            recovered = journal.recover()
            previous = load_local_manifest(data, self.language)
            if previous is None:
                if recovered:
                    return []
                raise OperationError("Brak zapisanej instalacji tłumaczenia dla tego języka.")
            skipped: list = []
            changes: list = []
            data.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=data) as directory:
                staging = Path(directory)
                for spec in previous.packages:
                    self.check_cancelled()
                    target = spec.target(root)
                    current = file_hash(target)
                    if current == spec.original:
                        continue
                    if current not in (None, spec.sha256):
                        skipped.append(spec.name)  # plik zmieniony przez grę – nie ruszamy
                        continue
                    source = original_backup(data, spec.name, spec.original)
                    if source is None:
                        self.progress(0.3, f"Pobieranie oryginału: {spec.name}")
                        source = self._download_original(spec, staging)
                    if source is None:
                        skipped.append(spec.name)
                        continue
                    changes.append(Change(target, current, source, spec.original))
                for spec in previous.diffs:
                    target = spec.target(root)
                    current = file_hash(target)
                    if current == spec.sha256:
                        backup = original_backup(data, spec.name, spec.original)
                        changes.append(Change(target, current, backup, spec.original if backup else None))
                if not skipped:
                    manifest = data / "manifest.json"
                    changes.append(Change(manifest, file_hash(manifest), None, None))
                self.progress(0.8, "Przywracanie plików…")
                journal.apply(changes, self.check_cancelled)
            if not skipped:
                shutil.rmtree(data / "payload", ignore_errors=True)
        sync_version_file(root)
        self.progress(1.0 if not skipped else 0.0, "Przywrócono." if not skipped else "Przywracanie niekompletne.")
        return skipped

    # -------------------------------------------------------------- injector w locie
    def launch(self, game_path: str, platform: str) -> str:
        self.logger.info("URUCHOMIENIE: język=%s platforma=%s folder=%s", self.language, platform, self.root)
        root = self.root
        with game_lock(root):
            journal = Journal(root)
            journal.recover()
            manifest = load_local_manifest(self.data, self.language)
            if manifest is None:
                raise OperationError("Najpierw zainstaluj spolszczenie dla wybranego języka.")
            guarded = [spec for spec in self._guarded(manifest) if matches(payload_path(self.data, spec), spec.sha256)]
            for spec in guarded:                       # launcher mógł przywrócić oryginał pliku głównego
                target = spec.target(root)
                if file_hash(target) == spec.original:
                    self.logger.warning("%s: launcher przywrócił oryginał – podmieniam przed startem", spec.name)
                    atomic_copy(payload_path(self.data, spec), target)
            if not has_installed_files(root, self.data, manifest, allow_restored=False):
                raise OperationError("Brakuje plików tłumaczenia lub uległy zmianie. Zainstaluj spolszczenie ponownie.")
            watched, entries, was_missing = [], [], {}
            for spec in manifest.diffs:
                target = spec.target(root)
                current = file_hash(target)
                if current == spec.original:
                    save_original(self.data, target, current)
                elif current not in (None, spec.sha256) and spec.optional:
                    continue
                # Nieznany plik różnicowy (np. pozostałość po starym instalatorze) nie blokuje startu: i tak jest
                # usuwany, a gra pobiera go od nowa. O zgodności decyduje dopiero świeżo pobrany plik (_watch);
                # do tego czasu stan sprzed startu jest zapisany w dzienniku i wraca przy każdej porażce.
                watched.append(spec)
                entries.append((target, current, [None, spec.original, spec.sha256]))
                was_missing[spec.name] = current is None
            self.check_cancelled()
            try:
                journal.prepare(entries)
                self.check_cancelled()
                for target, current, _ in entries:
                    if current is not None:
                        if file_hash(target) != current:
                            raise OperationError(f"Plik {target.name} zmienił się w trakcie uruchamiania.")
                        remove_file(target)  # wymuszamy ponowne pobranie pliku przez grę
                self.progress(0.10, "Uruchamianie gry…")
                start_game(game_path, platform, self.notify)
                result = self._watch(watched, was_missing, guarded, wait_for_game=platform == "launcher")
                self.check_cancelled()
                journal.finish()
            except BaseException:
                if self._foreign_seen:
                    journal.finish()   # na dysku jest świeży plik gry (nie nasz) – niczego nie cofamy do starego stanu
                else:
                    journal.recover()
                raise
        return result

    def _decide_foreign(self, spec: FileSpec, digest: str) -> float:
        """Gra ma nowszy plik niż tłumaczenie: pyta użytkownika; zwraca czas oczekiwania na odpowiedź."""
        started = time.monotonic()
        if self.confirm is None:
            raise ForeignVersionError(
                f"Gra pobrała inną wersję pliku {spec.name} niż oryginał, na którym oparte jest tłumaczenie. "
                "Gra mogła zostać zaktualizowana – poczekaj na aktualizację tłumaczenia.")
        if not self._allow_mismatch([spec.name]):
            raise Cancelled()
        self._accepted.add(digest)
        return time.monotonic() - started

    def _game_running(self) -> bool:
        return process_running()

    def _guard_main_files(self, guarded: list, sigs: dict) -> None:
        """Plik główny w LocalData\\Patch: gdy launcher/gra przywróci oryginał – od razu podmieniamy z kopii."""
        for spec in guarded:
            target = spec.target(self.root)
            try:
                info = target.stat()
            except OSError:
                continue
            signature = (info.st_size, info.st_mtime_ns)
            if sigs.get(spec.name) == signature:
                continue
            sigs[spec.name] = signature
            digest = file_hash(target)
            if digest == spec.original:
                try:
                    atomic_copy(payload_path(self.data, spec), target)
                except OSError:
                    sigs[spec.name] = None                 # plik zajęty – spróbujemy za chwilę
                    continue
                info = target.stat()
                sigs[spec.name] = (info.st_size, info.st_mtime_ns)
                self.logger.info("%s: przywrócono oryginał (launcher/gra) – ponownie podmieniono na tłumaczenie",
                                 spec.name)

    def _watch(self, specs: list, was_missing: dict, guarded: list = (), wait_for_game: bool = False) -> str:
        self.progress(0.30, "Czekam na plik gry. Jeśli gra nie wystartowała, uruchom ją ręcznie.")
        root = self.root
        start = time.monotonic()
        timeout = self.LAUNCHER_WATCH_TIMEOUT if wait_for_game else self.WATCH_TIMEOUT
        guard_sigs: dict = {}
        game_since = None
        last_process_check = 0.0
        told_click = False
        required = [s for s in specs if not s.optional]
        fallback = self.language == "de" and all(was_missing[s.name] for s in required)
        state = {s.name: {"sig": None, "stable": None, "checked": None, "patched": None, "foreign": None,
                          "fdigest": None} for s in specs}
        seen_any = False
        while time.monotonic() - start < timeout:
            self.cancelled.wait(0.1)
            self.check_cancelled()
            now = time.monotonic()
            if guarded:
                self._guard_main_files(guarded, guard_sigs)
            if wait_for_game and now - last_process_check >= 1.0:
                last_process_check = now
                running = self._game_running()
                if running and game_since is None:
                    game_since = now
                    self.logger.info("Gra wystartowała (proces wwm.exe) – pilnuję tłumaczenia przez %s s",
                                     self.GAME_CONFIRM_SECONDS)
                    self.progress(0.85, "Gra wystartowała – pilnuję tłumaczenia…")
                elif not running and game_since is not None:
                    self.logger.info("Proces gry zniknął – czekam ponownie")
                    game_since = None
            game_ok = (not wait_for_game) or (game_since is not None and now - game_since >= self.GAME_CONFIRM_SECONDS)
            for spec in specs:
                st, target = state[spec.name], spec.target(root)
                if st["foreign"] is not None and not spec.optional and now - st["foreign"] >= self.FOREIGN_SECONDS:
                    start += self._decide_foreign(spec, st["fdigest"])   # czas decyzji nie liczy się do limitu
                    st.update(sig=None, checked=None, foreign=None)
                    continue
                try:
                    info = target.stat()
                    seen_any = True
                    signature = (info.st_size, info.st_mtime_ns)
                    if signature != st["sig"]:
                        st.update(sig=signature, stable=now, checked=None, patched=None, foreign=None)
                        continue
                    if st["patched"] is not None or st["checked"] == signature or now - st["stable"] < 0.5:
                        continue
                    st["checked"] = signature
                    digest = sha256_file(target)
                    if digest == spec.sha256:
                        st["patched"] = now
                        self.logger.info("%s: plik gry ma już nasze tłumaczenie", spec.name)
                    elif digest != spec.original and digest not in self._accepted:
                        st["foreign"], st["fdigest"] = now, digest   # gra pobrała inną wersję niż nasz oryginał
                        self.logger.warning("%s: gra pobrała inną wersję niż oryginał z manifestu (%s, oczekiwano %s)",
                                         spec.name, _short(digest), _short(spec.original))
                        self._foreign_seen = True
                    else:
                        save_original(self.data, target, digest)
                        self.check_cancelled()
                        if file_hash(target) != digest:
                            st["sig"] = None
                            continue
                        atomic_copy(payload_path(self.data, spec), target)
                        self.logger.info("%s: gra pobrała plik (%s) – podmieniono na tłumaczenie", spec.name,
                                      _short(digest))
                        info = target.stat()
                        st.update(sig=(info.st_size, info.st_mtime_ns), checked=(info.st_size, info.st_mtime_ns),
                                  patched=now)
                        self.progress(0.80, "Sprawdzam, czy spolszczenie pozostaje aktywne…")
                except (FileNotFoundError, OSError):   # brak pliku albo zajęty przez grę – próbujemy dalej
                    st.update(sig=None, checked=None, patched=None, foreign=None)
            patched_all = bool(required) and all(state[s.name]["patched"] is not None for s in required)
            if wait_for_game and patched_all and game_since is None and not told_click:
                told_click = True
                self.logger.info("Plik podmieniony po weryfikacji launchera – czekam na uruchomienie gry")
                self.progress(0.6, "Tłumaczenie gotowe. Kliknij „Graj” w launcherze – instalator pilnuje plików.")
            if game_ok and required and all(state[s.name]["patched"] is not None
                                            and now - state[s.name]["patched"] >= self.CONFIRM_SECONDS for s in required):
                self.progress(1.0, f"Plik różnicowy podmieniony. W grze wybierz {LANGUAGES[self.language]}.")
                self.logger.info("Wstrzykiwanie zakończone sukcesem")
                return "patched"
            if fallback and not seen_any and game_ok and now - start >= self.GERMAN_FALLBACK:
                self.progress(1.0, "Spolszczenie jest w plikach gry. W ustawieniach wybierz Deutsch.")
                self.logger.info("DE: plik różnicowy nie pojawił się – tłumaczenie działa z plików gry")
                return "files-only"
        self.logger.error("Przekroczono czas oczekiwania (%s s), gra uruchomiona: %s", timeout, game_since is not None)
        raise OperationError("Nie potwierdzono podmiany. Sprawdź, czy gra jest uruchomiona i ma zgodną wersję.")
