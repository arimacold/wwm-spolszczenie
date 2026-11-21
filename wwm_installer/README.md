# Where Winds Meet – Instalator spolszczenia (wersja 2.0)

Przebudowany instalator: ta sama logika wersji co wcześniej (`version.txt` w repo, `polish_version.txt`
w grze), ale z zabezpieczeniami, kopiami zapasowymi i całkowicie nowym interfejsem (PySide6).



## Układ repozytorium `arimacold/wwm-spolszczenie`

```
version.txt
files/
  manifest.json                  <- generuje tools/make_manifest.py
  en/translate_words_map_en
  en/translate_words_map_en_diff
  de/translate_words_map_de
  de/translate_words_map_de_diff
  orginal/<te same nazwy>        <- oryginały gry; używane tylko jako ostatnia deska ratunku przy przywracaniu
```

Pliki `__small` nie są wymagane. Jeśli kiedyś wrócą do gry, dodaj je (wraz z oryginałami) do `files/<jezyk>/`
i `files/orginal/` – generator ujmie je w manifeście automatycznie.

### Wydanie nowej wersji tłumaczenia

```
python tools/make_manifest.py --version 1.2.0 --files files --originals files/orginal
```

Skrypt liczy sumy, waliduje manifest tym samym kodem co instalator i zapisuje `files/manifest.json` oraz
`version.txt` (zawsze zgodne). Pliki > 100 MB: dodaj `--split-mb 90`, a wgraj części (`*.part001`…).
**Oryginały muszą pochodzić z czystej instalacji gry** – ich sumy są wzorcem, po którym instalator poznaje,
że plik gry jest nietknięty.

**Skąd brać oryginały:** pliki główne z `Package\HD\oversea\locale`, a pliki `*_diff` z
`LocalData\Patch\HD\oversea\locale` (to wersja, którą gra pobiera z serwera i którą instalator podmienia).

Po aktualizacji gry hash oryginału się zmienia. Do czasu wydania nowego manifestu instalator **nie blokuje**
graczy: pokazuje okno „Nowsza wersja gry” z wyborem *Użyj mimo to* / *Anuluj*. Po akceptacji prawdziwy plik
gry trafia do kopii zapasowej, więc „Przywróć oryginalne tłumaczenie” oddaje właśnie jego, a nie stary
oryginał z repozytorium.

Pakiet niemiecki gra pobiera dopiero po wybraniu języka Deutsch. Jeśli go brakuje, instalator podpowiada,
żeby najpierw uruchomić grę i wybrać niemiecki.

## Uruchamianie i testy

```
pip install -r requirements.txt
python main.py                      # tylko Windows (rejestr, blokada plików)
pip install pytest && python -m pytest tests -q     # 32 testy, działają też na Linuksie
```

## Budowanie EXE (Windows)

Uruchom `build.bat`. Używa **Nuitki w trybie standalone** (folder, nie onefile), bez UPX, z danymi wersji
w EXE i ikoną. To najlepsza praktyczna kombinacja pod kątem fałszywych alarmów antywirusów:

1. Nuitka kompiluje kod do C, więc nie ma popularnego launchera PyInstallera, który antywirusy często flagują.
2. Tryb onefile rozpakowuje się do `%TEMP%` – klasyczny wyzwalacz heurystyk. Folder (w ZIP-ie) tego nie robi.
3. **Podpis cyfrowy jest najskuteczniejszy.** Dla projektów open source jest darmowy
   [SignPath Foundation](https://signpath.org/); są też płatne certyfikaty.
4. Publikuj ZIP w GitHub Releases razem z sumą SHA-256, a kod trzymaj otwarty.
5. Po każdym wydaniu zgłoś plik jako fałszywy alarm do Microsoft Defender i producentów, którzy go oznaczą.

Gwarancji nie ma: program, który podmienia pliki gry i pilnuje pliku w tle, zawsze wygląda heurystycznie
podejrzanie. Ikona i dane wersji pochodzą z `assets/` (`python tools/make_icon.py` odtwarza ikonę).

## Uwagi

- Przy grze w `C:\Program Files` może być potrzebne uruchomienie jako administrator (instalator nie wymusza go sam).
- Instalator zamknięty w trakcie pracy anuluje operację i cofa zmiany.
- Zminimalizowane okno wstrzymuje animacje (zero obciążenia procesora).


