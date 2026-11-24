<#
  Monitor zachowania launchera i gry Where Winds Meet (wersja z oficjalnego launchera).
  Skrypt TYLKO OBSERWUJE: niczego nie zmienia ani nie wysyła.
  Co sekundę-pół zapisuje: start/stop procesów (launcher, updater, wwm) oraz każdą zmianę plików
  tłumaczeń w LocalData\Patch\HD\oversea\locale – z sumą SHA-256 i opisem, czy to TŁUMACZENIE czy ORYGINAŁ.
  Wynik: "wwm_monitor.txt" na pulpicie (zapisywany na bieżąco – Ctrl+C niczego nie traci).

  Uruchom:  powershell -ExecutionPolicy Bypass -File ".\wwm_monitor.ps1"
  Opcje:    -GamePath "D:\SteamLibrary\wwm_standard"   -Minutes 15
#>
param([string]$GamePath = "", [int]$Minutes = 15)

$ErrorActionPreference = "SilentlyContinue"
$out = Join-Path ([Environment]::GetFolderPath("Desktop")) "wwm_monitor.txt"
function Hide([string]$text) {
  $t = $text -replace '[A-Za-z0-9+/=_\-]{28,}', '[ukryto]'
  if ($env:USERNAME) { $t = $t -replace [regex]::Escape($env:USERNAME), '<uzytkownik>' }
  return $t
}
$t0 = Get-Date
function Log([string]$text, [string]$color = "Gray") {
  $stamp = (Get-Date).ToString("HH:mm:ss.fff")
  $rel = "{0,7:N1}s" -f ((Get-Date) - $t0).TotalSeconds
  $line = "$stamp  +$rel  $(Hide $text)"
  Add-Content -Path $out -Value $line -Encoding UTF8
  Write-Host $line -ForegroundColor $color
}

# ---------------------------------------------------------------- znajdź grę i launcher
$launcherDir = (Get-ItemProperty "HKCU:\Software\Netease\wwm").installpath
$settingIni = if ($launcherDir) { Join-Path $launcherDir "Win32\deploy\setting.ini" } else { "" }
if (-not $GamePath -and $settingIni -and (Test-Path $settingIni)) {
  $line = Select-String -Path $settingIni -Pattern '^\s*InstallPath\s*=' | Select-Object -First 1
  if ($line) { $GamePath = ($line.Line -split '=', 2)[1].Trim().Trim('"') -replace '/', '\' }
}
Set-Content -Path $out -Value "WWM monitor – start $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -Encoding UTF8
if (-not $GamePath -or -not (Test-Path $GamePath)) {
  Log "Nie znaleziono folderu gry. Uruchom ponownie z parametrem -GamePath ""ścieżka\wwm_standard""" "Red"
  exit 1
}
$locale = Join-Path $GamePath "LocalData\Patch\HD\oversea\locale"
$patch = Join-Path $GamePath "LocalData\Patch"
$launcherLog = if ($launcherDir) { Join-Path $launcherDir "Win32\deploy\launcher.log" } else { "" }
Log "Folder gry:      $GamePath"
Log "Folder launchera: $launcherDir"
Log "Pliki tłumaczeń: $locale"

# ---------------------------------------------------------------- znane sumy z instalatora spolszczenia
$known = @{}
foreach ($lang in "en", "de") {
  $mf = Join-Path $GamePath "Spolszczenie_Data\WWMPL\$lang\manifest.json"
  if (Test-Path $mf) {
    $json = Get-Content $mf -Raw -Encoding UTF8 | ConvertFrom-Json
    $files = $json.languages.$lang.files
    foreach ($p in $files.PSObject.Properties) {
      $known[$p.Value.sha256.ToUpper()] = "TŁUMACZENIE ($($p.Name), wersja $($json.version))"
      $known[$p.Value.original.ToUpper()] = "ORYGINAŁ ($($p.Name))"
    }
    Log "Wczytano sumy z manifestu spolszczenia ($lang, wersja $($json.version), wariant $($json.variant))"
  }
}
if ($known.Count -eq 0) { Log "Brak manifestu spolszczenia – sumy będą bez opisu (zainstaluj najpierw spolszczenie)" "Yellow" }

Log ""
Log "Teraz: uruchom grę tak jak zwykle (launcher -> Graj), wejdź do menu gry, sprawdź napisy, zamknij grę." "Cyan"
Log "Monitor działa $Minutes min albo do Ctrl+C." "Cyan"
Log ""

# ---------------------------------------------------------------- stan początkowy i pętla
$procNames = "launcher", "updater", "wwm", "UniCrashReporter"
$procState = @{}
$fileState = @{}
$logSize = if ($launcherLog -and (Test-Path $launcherLog)) { (Get-Item $launcherLog).Length } else { 0 }

function Running() { ((Get-Process -Name $procNames | ForEach-Object { $_.Name }) | Sort-Object -Unique) -join "," }

function CheckFile([string]$path, [bool]$hash) {
  $item = Get-Item $path
  $sig = if ($item) { "$($item.Length)|$($item.LastWriteTimeUtc.Ticks)" } else { "BRAK" }
  if ($fileState[$path] -ne $sig) {
    $first = -not $fileState.ContainsKey($path)
    $fileState[$path] = $sig
    $name = Split-Path $path -Leaf
    if (-not $item) { Log ("PLIK  {0,-34} {1}   [działa: {2}]" -f $name, "USUNIĘTY / BRAK", (Running)) "Red"; return }
    $label = ""
    if ($hash) {
      Start-Sleep -Milliseconds 300   # daj programowi dokończyć zapis
      $h = (Get-FileHash $path -Algorithm SHA256).Hash
      if (-not $h) { $fileState[$path] = $null; return }   # plik zajęty w trakcie zapisu – sprawdzimy za chwilę
      $label = if ($known.ContainsKey($h)) { $known[$h] } else { "INNA WERSJA ($($h.Substring(0,12)))" }
    }
    $prefix = if ($first) { "START" } else { "ZMIANA" }
    $color = if ($label -like "TŁUMACZENIE*") { "Green" } elseif ($label -like "ORYGINAŁ*") { "Yellow" } else { "Gray" }
    Log ("{0,-6}{1,-34} {2,12:N0} B  {3}  {4}   [działa: {5}]" -f $prefix, $name, $item.Length,
         $item.LastWriteTime.ToString("HH:mm:ss"), $label, (Running)) $color
  }
}

$end = (Get-Date).AddMinutes($Minutes)
while ((Get-Date) -lt $end) {
  # procesy
  foreach ($n in $procNames) {
    $procs = Get-Process -Name $n
    $now = ($procs | ForEach-Object { $_.Id }) -join ","
    if ($procState[$n] -ne $now) {
      if ($now) {
        $path = ($procs | Select-Object -First 1).Path
        Log ("PROCES START  {0,-18} PID {1}  {2}" -f $n, $now, $path) "Cyan"
      } elseif ($procState.ContainsKey($n)) {
        Log ("PROCES STOP   {0}" -f $n) "Magenta"
      }
      $procState[$n] = $now
    }
  }
  # pliki tłumaczeń (z sumą) i pliki blokad/stanu launchera (bez sumy)
  foreach ($f in (Get-ChildItem $locale -Filter "translate_words_map_*" | ForEach-Object { $_.FullName })) { CheckFile $f $true }
  foreach ($known_name in "translate_words_map_en", "translate_words_map_en_diff", "translate_words_map_de", "translate_words_map_de_diff") {
    $p = Join-Path $locale $known_name
    if ($fileState.ContainsKey($p) -and -not (Test-Path $p)) { CheckFile $p $true }
  }
  foreach ($f in "game.lock", "bg_patch.lock", "essential.txt", "extra_version", "CanCompactSize.tag") {
    CheckFile (Join-Path $patch $f) $false
  }
  # nowe linie w logu launchera
  if ($launcherLog -and (Test-Path $launcherLog)) {
    $size = (Get-Item $launcherLog).Length
    if ($size -lt $logSize) { $logSize = 0 }
    if ($size -gt $logSize) {
      $fs = [System.IO.File]::Open($launcherLog, 'Open', 'Read', 'ReadWrite')
      $fs.Seek($logSize, 'Begin') | Out-Null
      $reader = New-Object System.IO.StreamReader($fs)
      $new = $reader.ReadToEnd(); $reader.Close(); $fs.Close()
      foreach ($l in ($new -split "`r?`n" | Where-Object { $_.Trim() })) {
        $short = if ($l.Length -gt 200) { $l.Substring(0, 200) + "…" } else { $l }
        Log "LAUNCHER.LOG  $short" "DarkGray"
      }
      $logSize = $size
    }
  }
  Start-Sleep -Milliseconds 500
}
Log "Koniec monitorowania. Raport: $out" "Green"
