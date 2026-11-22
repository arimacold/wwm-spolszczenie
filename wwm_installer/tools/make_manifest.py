#!/usr/bin/env python3
"""Generuje files/manifest.json dla instalatora.

Układ wejścia (zgodny ze starym repozytorium):

  files/en/translate_words_map_en          <- polskie tłumaczenie
  files/en/translate_words_map_en_diff
  files/de/translate_words_map_de
  files/de/translate_words_map_de_diff
  orginal/translate_words_map_en           <- ORYGINALNE pliki gry (z czystej instalacji)
  orginal/translate_words_map_en_diff         (może też być orginal/en/<nazwa>)
  ...

Pliki `__small` są opcjonalne – jeśli ich nie ma, zostaną pominięte.

Użycie:
  python tools/make_manifest.py --version 1.2.0 --files files --originals files/orginal
  python tools/make_manifest.py --version 1.2.0 --files files --originals files/orginal --split-mb 90
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wwmpl.core import LANGUAGES, Manifest, expected_names, sha256_file  # noqa: E402


def find_original(originals: Path, language: str, name: str):
    for candidate in (originals / language / name, originals / name):
        if candidate.is_file():
            return candidate
    return None


MAGIC = bytes.fromhex("efbeadde")   # każdy plik translate_words_map_* gry zaczyna się od tych 4 bajtów


def has_game_header(path: Path) -> bool:
    with path.open("rb") as stream:
        return stream.read(4) == MAGIC


def split_file(path: Path, size: int) -> list:
    parts = []
    with path.open("rb") as stream:
        index = 1
        while chunk := stream.read(size):
            part = path.with_name(f"{path.name}.part{index:03d}")
            part.write_bytes(chunk)
            parts.append(part.name)
            index += 1
    return parts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", required=True, help="wersja tłumaczenia (taka sama jak w version.txt)")
    parser.add_argument("--files", type=Path, default=Path("files"), help="katalog z podkatalogami en/ i de/")
    parser.add_argument("--originals", type=Path, default=Path("files/orginal"), help="oryginalne pliki gry")
    parser.add_argument("--out", type=Path, help="gdzie zapisać manifest (domyślnie <files>/manifest.json)")
    parser.add_argument("--split-mb", type=int, default=0,
                        help="dziel pliki większe niż N MB na części (limit GitHuba to 100 MB)")
    args = parser.parse_args()

    payload = {"version": args.version, "languages": {}}
    for language in LANGUAGES:
        names = expected_names(language)
        entries = {}
        for key in ("main", "diff", "small", "small_diff"):
            name = names[key]
            translated = args.files / language / name
            required = key in ("main", "diff")
            if not translated.is_file():
                if required:
                    print(f"BŁĄD: brak pliku {translated}", file=sys.stderr)
                    return 1
                continue
            if not has_game_header(translated):
                print(f"BŁĄD: {translated} nie jest prawidłowym plikiem gry (brak nagłówka EF BE AD DE). "
                      "Plik jest uszkodzony albo zapisany w złym formacie – wygeneruj go ponownie.", file=sys.stderr)
                return 1
            original = find_original(args.originals, language, name)
            if original is None:
                if required:
                    print(f"BŁĄD: brak oryginału {name} w {args.originals}", file=sys.stderr)
                    return 1
                print(f"Pominięto opcjonalny {name}: brak oryginału do porównania")
                continue
            if not has_game_header(original):
                print(f"BŁĄD: oryginał {original} nie jest prawidłowym plikiem gry (brak nagłówka EF BE AD DE).",
                      file=sys.stderr)
                return 1
            entry = {"sha256": sha256_file(translated), "original": sha256_file(original)}
            if args.split_mb and translated.stat().st_size > args.split_mb * 1024 * 1024:
                entry["parts"] = split_file(translated, args.split_mb * 1024 * 1024)
                print(f"{name}: podzielono na {len(entry['parts'])} części (wgraj części zamiast pliku)")
            entries[name] = entry
            print(f"{language}/{name}: OK")
        payload["languages"][language] = {"files": entries}

    for language in LANGUAGES:  # walidacja dokładnie tym kodem, którego użyje instalator
        Manifest.parse(payload, language)
    out = args.out or args.files / "manifest.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    version_file = args.files.resolve().parent / "version.txt"
    version_file.write_text(args.version + "\n", encoding="utf-8")  # manifest i version.txt zawsze zgodne
    print(f"\nZapisano {out} oraz {version_file} (wersja {args.version}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
