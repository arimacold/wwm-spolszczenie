import functools
import hashlib
import http.server
import json
import sys
import threading
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wwmpl.core import DIFF_DIR, PACKAGE_DIR, expected_names  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class World:
    """Fałszywe repozytorium (serwowane po HTTP) + fałszywy folder gry."""

    def __init__(self, tmp: Path):
        self.repo = tmp / "repo"
        self.game = tmp / "game"
        (self.repo / "files").mkdir(parents=True)
        (self.repo / "files" / "orginal").mkdir()
        (self.game / PACKAGE_DIR).mkdir(parents=True)
        self.version = "1.0.0"
        self.content = {}   # (lang, key) -> (translated bytes, original bytes)
        for lang in ("en", "de"):
            for key in ("main", "diff", "small", "small_diff"):
                name = expected_names(lang)[key]
                self.content[(lang, key)] = (f"PL-{name}-v1".encode() * 50, f"ORIG-{name}".encode() * 50)

    def name(self, lang, key):
        return expected_names(lang)[key]

    def translated(self, lang, key):
        return self.content[(lang, key)][0]

    def original(self, lang, key):
        return self.content[(lang, key)][1]

    def publish(self, version=None, small=False, tamper=None):
        """Zapisuje repo: pliki, version.txt i manifest. `tamper` psuje zawartość pliku PL bez zmiany sumy."""
        self.version = version or self.version
        (self.repo / "version.txt").write_text(self.version)
        payload = {"version": self.version, "languages": {}}
        for lang in ("en", "de"):
            (self.repo / "files" / lang).mkdir(exist_ok=True)
            entries = {}
            for key in ("main", "diff") + (("small", "small_diff") if small else ()):
                name = self.name(lang, key)
                tr, orig = self.content[(lang, key)]
                (self.repo / "files" / lang / name).write_bytes(b"BROKEN" if tamper == name else tr)
                (self.repo / "files" / "orginal" / name).write_bytes(orig)
                entries[name] = {"sha256": sha(tr), "original": sha(orig)}
            payload["languages"][lang] = {"files": entries}
        (self.repo / "files" / "manifest.json").write_text(json.dumps(payload))

    def publish_story(self, version="0.1.0-beta"):
        """Wariant fabularny w podfolderze fabula/ (oryginały tylko w katalogu głównym repo)."""
        root = self.repo / "fabula"
        (root / "files").mkdir(parents=True, exist_ok=True)
        (root / "version.txt").write_text(version)
        payload = {"version": version, "languages": {}}
        self.story = {}
        for lang in ("en", "de"):
            (root / "files" / lang).mkdir(exist_ok=True)
            entries = {}
            for key in ("main", "diff"):
                name = self.name(lang, key)
                tr = f"FABULA-{name}".encode() * 50
                self.story[(lang, key)] = tr
                (root / "files" / lang / name).write_bytes(tr)
                entries[name] = {"sha256": sha(tr), "original": sha(self.original(lang, key))}
            payload["languages"][lang] = {"files": entries}
        (root / "files" / "manifest.json").write_text(json.dumps(payload))

    def install_game_files(self, lang="en", small=False):
        for key in ("main",) + (("small",) if small else ()):
            (self.game / PACKAGE_DIR / self.name(lang, key)).write_bytes(self.original(lang, key))

    def pkg(self, lang, key="main"):
        return self.game / PACKAGE_DIR / self.name(lang, key)

    def diff(self, lang, key="diff"):
        return self.game / DIFF_DIR / self.name(lang, key)


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


@pytest.fixture
def server(world):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(world.repo))
    handler.log_message = lambda *a, **k: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()


@pytest.fixture
def session():
    s = requests.Session()
    s.trust_env = False
    return s
