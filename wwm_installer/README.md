# Where Winds Meet – Instalator spolszczenia (wersja 2.0)

Przebudowany instalator: ta sama logika wersji co wcześniej (`version.txt` w repo, `polish_version.txt`
w grze), ale z zabezpieczeniami, kopiami zapasowymi i całkowicie nowym interfejsem (PySide6).


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

Po aktualizacji gry hash oryginału się zmienia: wygeneruj manifest ponownie z nowymi oryginałami.
Do tego czasu instalator odmówi pracy na „nieznanej wersji" zamiast psuć pliki.

## Uruchamianie i testy

```
pip install -r requirements.txt
python main.py                      # tylko Windows (rejestr, blokada plików)
pip install pytest && python -m pytest tests -q     # 32 testy, działają też na Linuksie
```


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
