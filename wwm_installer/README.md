# Where Winds Meet – Instalator spolszczenia (wersja 2.0)

Przebudowany instalator: ta sama logika wersji co wcześniej (`version.txt` w repo, `polish_version.txt`
w grze), ale z zabezpieczeniami, kopiami zapasowymi i całkowicie nowym interfejsem (PySide6).

## Co się zmieniło

| Obszar | Teraz |
|---|---|
| Weryfikacja | sumy SHA-256 z `files/manifest.json` (pliki tłumaczenia **i** oryginały gry) |
| Kopie zapasowe | `Spolszczenie_Data/WWMPL/<en\|de>/backup/<hash>/` – tylko prawdziwe oryginały |
| Zapis plików | plik tymczasowy + podmiana, dziennik odzyskiwania cofa przerwaną operację |
| Pliki `small` | **opcjonalne** – nie ma ich w grze, więc są pomijane bez błędu; gdyby wróciły i były w manifeście, zostaną zainstalowane |
| Injector „w locie" | zostaje (przycisk „URUCHOM GRĘ"), ale podmienia plik dopiero po sprawdzeniu hasha i cofa zmiany po timeoucie |
| Steam | szuka też w dodatkowych bibliotekach (`libraryfolders.vdf`) |
| Migracja | stara instalacja (`.backup` + `polish_version.txt`) jest rozpoznawana i bezpiecznie przejmowana |
| Interfejs | animowane tło dzień / noc / świt, bohater biegający po tytule i pasku postępu, własny kursor |

Nastroje: **English → dzień**, **Deutsch → noc**, **po udanej instalacji → świt**, **wariant fabularny → zima**
(śnieg, ośnieżone góry, samuraj w zimowym płaszczu), **„Uruchom grę” → lato** (samuraj z wachlarzem).

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

### Wariant fabularny (BETA)

Instalator ma wybór **Pełne** / **Fabularne**. Wariant fabularny leży w osobnym folderze z tym samym układem:

```
fabula/
  version.txt                    <- osobna wersja wariantu (np. 0.1.0-beta)
  files/
    manifest.json
    en/translate_words_map_en
    en/translate_words_map_en_diff
    de/translate_words_map_de
    de/translate_words_map_de_diff
```

Oryginały są wspólne (`files/orginal/`) – nie kopiuj ich do `fabula/`. Manifest wariantu:

```
python tools/make_manifest.py --version 0.1.0-beta --files fabula/files --originals files/orginal
```

Przełączanie wariantów w instalatorze działa jak aktualizacja (kopie oryginałów są wspólne). Dopóki folderu
`fabula/` nie ma w repozytorium, wybór wariantu fabularnego kończy się komunikatem „nie jest jeszcze dostępny”.

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

## Układ okna i bohater

- Domyślnie okno jest **pionowe (600×830)**. Przycisk w pasku tytułu przełącza na **poziome (880×720)** i z powrotem;
  wybór zapamiętuje `%LOCALAPPDATA%\WWM-Spolszczenie\settings.json`. Na niskim ekranie (wolne miejsce < 870 px)
  instalator sam wybiera układ poziomy. Przełączanie jest zablokowane w trakcie instalacji.
- Samuraj nosi biało-czerwoną flagę: macha nią, kręci, kłania się i tnie mieczem podczas postoju na napisie,
  a po udanej instalacji wbija ją w koniec paska postępu.
- Podgląd klatek bohatera: `python tests/hero_sheet.py /tmp/hero.png`.


## Oficjalny launcher, logi i odliczanie (2.2.0)

- **Oficjalny launcher**: gra z launchera trzyma pliki tłumaczeń w `LocalData\Patch\HD\oversea\locale`
  (bez `Package\…\locale`). Instalator podmienia plik główny tam, gdzie gra go faktycznie trzyma
  (najpierw `LocalData\Patch`, potem `Package`).
- **Wykrywanie dla launchera** – najpierw źródło pewne: `HKCU\Software\Netease\wwm` (`installpath` = folder
  launchera, np. `C:\Program Files\wwm`) → `Win32\deploy\setting.ini` → `InstallPath=` (folder gry).
  Launcher uruchamiany jest z `Win32\deploy\launcher.exe`. Gdy tego zapisu brak (nigdy nie wybiera instalacji
  ze Steam – ścieżki ze `steamapps` są pomijane):
  ślady uruchomionej gry w rejestrze (MuiCache, Asystent zgodności), pliki konfiguracyjne launchera z jego
  folderu instalacji (np. `C:\Program Files\wwm`), manifesty Epic oraz foldery `wwm_standard` / `wwm_lite` /
  `wwm_ultimate` na każdym dysku – także jeden poziom niżej (np. `D:\SteamLibrary\wwm_standard`).
  Przy kilku instalacjach wybierana jest ostatnio używana.
- **Ręczne wskazanie folderu** jest poprawiane automatycznie – można wskazać folder `wwm`, `wwm_standard`,
  a nawet `locale` czy `Engine\Binaries`. Wybrany folder jest zapamiętywany osobno dla Steam i launchera.
- **Uruchamianie**: najpierw launcher (`*launcher*.exe` w folderze gry lub wyżej), potem `wwm.exe`
  z `Engine\Binaries\Win64r` (wielkość liter nie ma znaczenia).
- **Logi**: `%LOCALAPPDATA%\WWM-Spolszczenie\logs\instalator.log` (rotacja 3 × 1 MB). Ikona w prawym
  rogu stopki otwiera panel z podglądem na żywo, przyciskiem *Kopiuj logi* (z nagłówkiem: wersja, platforma,
  język, wariant, folder, status) i *Otwórz folder z logami*.
- **Pożegnanie**: po udanym wstrzyknięciu nad stopką wysuwa się mały pasek z odliczaniem 10 s.
  Samuraj wbija flagę w pasek postępu, kłania się („Do zobaczenia w grze!”), zabiera flagę, skacze na napis,
  czeka przy krzyżyku (macha flagą, przytupuje), w ostatnich 3 s dobywa miecza, a przy zerze przecina krzyżyk
  w skoku – okno rozsypuje się w płatki / liście / śnieg i znika. *Nie zamykaj* przerywa odliczanie
  (samuraj wzrusza ramionami i wraca na napis).

- **Diagnostyka**: `tools/wwm_diagnostyka.ps1` (tylko odczyt) zapisuje na pulpicie raport o instalacjach gry,
  launcherze, wpisach w rejestrze i budowie folderów – do wysłania przy problemach z wykrywaniem.
- **Wstrzykiwanie z oficjalnym launcherem**: launcher sam weryfikuje i pobiera pliki zanim uruchomi grę,
  dlatego przy platformie „Epic / Launcher” instalator nie ogłasza sukcesu po samej podmianie: czeka na proces
  gry `wwm.exe` (do 20 min) i ogłasza sukces dopiero, gdy gra działa 30 s z tłumaczeniem. Pilnuje też pliku
  głównego w `LocalData\Patch` i od razu przywraca tłumaczenie, gdy launcher/gra podmieni go na oryginał.
- **Monitor**: `tools/wwm_monitor.ps1` (tylko obserwuje) nagrywa start/stop procesów launchera i gry oraz każdą
  zmianę plików tłumaczeń z opisem TŁUMACZENIE / ORYGINAŁ – do diagnozy zachowania launchera.
