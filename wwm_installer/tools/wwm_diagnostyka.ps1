<#
  Diagnostyka instalacji Where Winds Meet (oficjalny launcher / Epic / Steam)
  Skrypt TYLKO CZYTA: niczego nie zmienia, nie usuwa i nie wysyła.
  Wynik: plik "wwm_diagnostyka.txt" na pulpicie.
  Uruchom:  powershell -ExecutionPolicy Bypass -File ".\wwm_diagnostyka.ps1"
  Opcjonalnie wskaż folder gry:  ... -File ".\wwm_diagnostyka.ps1" -GamePath "D:\SteamLibrary\wwm_standard"
#>
param([string]$GamePath = "")

$ErrorActionPreference = "SilentlyContinue"
$out = Join-Path ([Environment]::GetFolderPath("Desktop")) "wwm_diagnostyka.txt"
$lines = New-Object System.Collections.Generic.List[string]
function W([string]$text = "") { $lines.Add($text) }
function Section([string]$title) { W ""; W ("=" * 70); W "  $title"; W ("=" * 70) }
function Hide([string]$text) {
  # ukrywa długie ciągi (tokeny, identyfikatory) i nazwę użytkownika Windows
  $t = $text -replace '[A-Za-z0-9+/=_\-]{28,}', '[ukryto]'
  if ($env:USERNAME) { $t = $t -replace [regex]::Escape($env:USERNAME), '<uzytkownik>' }
  return $t
}
$pattern = 'where\s*winds|wherewinds|wwm|netease|燕云'

W "WWM diagnostyka – $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
W "Windows: $([Environment]::OSVersion.VersionString)  |  64-bit: $([Environment]::Is64BitOperatingSystem)"
W "Dyski: $((Get-PSDrive -PSProvider FileSystem | ForEach-Object { $_.Root }) -join ', ')"

# ---------------------------------------------------------------- 1. Programy i funkcje
Section "1. Wpisy instalacji w rejestrze (Programy i funkcje)"
$uninstallRoots = @(
  "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
  "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
  "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall")
$launcherDirs = @()
foreach ($root in $uninstallRoots) {
  Get-ChildItem $root | ForEach-Object {
    $p = Get-ItemProperty $_.PSPath
    $hay = "$($p.DisplayName) $($p.Publisher) $($_.PSChildName)"
    if ($hay -match $pattern) {
      W "[$root\$($_.PSChildName)]"
      foreach ($name in "DisplayName","Publisher","DisplayVersion","InstallLocation","DisplayIcon","UninstallString","InstallSource") {
        if ($p.$name) { W ("   {0,-16} {1}" -f $name, (Hide $p.$name)) }
      }
      if ($p.InstallLocation -and $p.InstallLocation -notmatch 'steamapps') { $launcherDirs += $p.InstallLocation.Trim('"') }
      elseif ($p.UninstallString -and $p.UninstallString -notmatch 'steam') {
        $u = ($p.UninstallString -replace '^"([^"]+)".*$', '$1') -replace '\s+/.*$', ''
        $launcherDirs += (Split-Path $u -Parent)
      }
      W ""
    }
  }
}

# ---------------------------------------------------------------- 2. Inne klucze rejestru
Section "2. Klucze rejestru producenta (Software\...)"
foreach ($base in "HKCU:\Software","HKLM:\SOFTWARE","HKLM:\SOFTWARE\WOW6432Node") {
  Get-ChildItem $base | Where-Object { $_.PSChildName -match $pattern } | ForEach-Object {
    W "[$($_.Name)]"
    Get-ChildItem $_.PSPath -Recurse -Depth 2 | Select-Object -First 40 | ForEach-Object {
      $props = Get-ItemProperty $_.PSPath
      $vals = ($props.PSObject.Properties | Where-Object { $_.Name -notlike 'PS*' } |
               ForEach-Object { "$($_.Name)=$(Hide ([string]$_.Value))" }) -join '; '
      W "   $($_.Name)  $vals"
    }
  }
}

# ---------------------------------------------------------------- 3. Ślady uruchomień
Section "3. Ślady uruchomionych programów (MuiCache, Asystent zgodności)"
$traceKeys = @(
  "HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache",
  "HKCU:\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Compatibility Assistant\Store")
$gameDirsFromTraces = @()
foreach ($key in $traceKeys) {
  $item = Get-Item $key
  if ($item) {
    foreach ($name in $item.GetValueNames()) {
      if ($name -match $pattern -or $name -match 'launcher\.exe') {
        W "   $(Hide $name)"
        if ($name -match '^(.*\\(wwm_standard|wwm_lite|wwm_ultimate))\\') { $gameDirsFromTraces += $Matches[1] }
      }
    }
  }
}

# ---------------------------------------------------------------- 4. Skróty
Section "4. Skróty w menu Start i na pulpicie"
$shell = New-Object -ComObject WScript.Shell
$shortcutDirs = @("$env:ProgramData\Microsoft\Windows\Start Menu\Programs", "$env:APPDATA\Microsoft\Windows\Start Menu\Programs",
                  [Environment]::GetFolderPath("Desktop"), "$env:PUBLIC\Desktop")
foreach ($dir in $shortcutDirs) {
  Get-ChildItem $dir -Recurse -Filter *.lnk | Where-Object { $_.Name -match $pattern } | ForEach-Object {
    $lnk = $shell.CreateShortcut($_.FullName)
    W "   $(Hide $_.FullName)"
    W "      -> $(Hide $lnk.TargetPath)  $(Hide $lnk.Arguments)   (start w: $(Hide $lnk.WorkingDirectory))"
    if ($lnk.TargetPath -and $lnk.TargetPath -notmatch 'steam') { $launcherDirs += (Split-Path $lnk.TargetPath -Parent) }
  }
}

# ---------------------------------------------------------------- 5. Folder launchera
Section "5. Folder launchera (pliki i ścieżki w konfiguracji)"
$launcherDirs = $launcherDirs | Where-Object { $_ -and (Test-Path $_) } | Sort-Object -Unique
if (-not $launcherDirs) { W "   Nie znaleziono folderu launchera w rejestrze ani w skrótach." }
foreach ($dir in $launcherDirs) {
  W "[$(Hide $dir)]"
  Get-ChildItem $dir -Recurse -Depth 2 -File | Select-Object -First 150 | ForEach-Object {
    W ("   {0,10:N0} B  {1}" -f $_.Length, (Hide $_.FullName.Substring($dir.Length)))
  }
  W "   --- wiersze z plików konfiguracyjnych zawierające ścieżki (dane długie ukryte) ---"
  Get-ChildItem $dir -Recurse -Depth 3 -File -Include *.json,*.ini,*.cfg,*.xml,*.txt,*.config,*.conf,*.yaml,*.dat |
    Where-Object { $_.Length -lt 2MB } | ForEach-Object {
      $file = $_
      Select-String -Path $file.FullName -Pattern '[A-Za-z]:[\\/]|wwm_|install|path|dir' -Encoding UTF8 |
        Select-Object -First 25 | ForEach-Object {
          $txt = $_.Line.Trim(); if ($txt.Length -gt 220) { $txt = $txt.Substring(0, 220) + "…" }
          W "   $(Hide $file.Name):$($_.LineNumber): $(Hide $txt)"
        }
    }
}

# ---------------------------------------------------------------- 6. Szukanie folderów gry na dyskach
Section "6. Foldery wwm_standard / wwm_lite / wwm_ultimate na dyskach (do 3 poziomów)"
$found = @()
foreach ($drive in (Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -ne $null })) {
  $r = $drive.Root
  $level1 = Get-ChildItem $r -Directory | Where-Object { $_.Name -notmatch '^(Windows|\$Recycle\.Bin|System Volume Information|ProgramData)$' }
  $all = @($level1)
  foreach ($d in $level1) { $all += Get-ChildItem $d.FullName -Directory }
  $level2 = @($all)
  foreach ($d in $level2) { if ($d.Name -match '^wwm$|games|netease|where') { $all += Get-ChildItem $d.FullName -Directory } }
  $all | Where-Object { $_.Name -match '^wwm_(standard|lite|ultimate)$' -and $_.FullName -notmatch 'steamapps' } |
    ForEach-Object { $found += $_.FullName }
}
$found = ($found + $gameDirsFromTraces) | Sort-Object -Unique
if (-not $found) { W "   Nic nie znaleziono." }
foreach ($f in $found) { W "   $(Hide $f)" }
if ($GamePath) { $found = @($GamePath) + $found }

# ---------------------------------------------------------------- 7. Budowa folderu gry
foreach ($game in ($found | Select-Object -Unique | Select-Object -First 3)) {
  Section "7. Budowa folderu gry: $(Hide $game)"
  W "   Foldery główne:"
  Get-ChildItem $game | ForEach-Object { W ("      {0}{1}" -f $_.Name, $(if ($_.PSIsContainer) { "\" } else { "  ($($_.Length) B)" })) }
  foreach ($rel in "Package\HD\oversea\locale","LocalData\Patch\HD\oversea\locale","LocalData\Patch\HD\oversea","LocalData\Patch") {
    $p = Join-Path $game $rel
    if (Test-Path $p) {
      W "   [$rel]"
      Get-ChildItem $p | Select-Object -First 60 | ForEach-Object {
        W ("      {0,-45} {1,14:N0} B   {2}" -f $_.Name, $_.Length, $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm'))
      }
    } else { W "   [$rel]  — brak" }
  }
  W "   Pliki .exe (do 4 poziomów, bez Package/LocalData):"
  Get-ChildItem $game -Recurse -Depth 4 -Filter *.exe | Where-Object { $_.FullName -notmatch '\\(Package|LocalData)\\' } |
    Select-Object -First 30 | ForEach-Object { W "      $($_.FullName.Substring($game.Length))" }
  W "   Pliki konfiguracyjne w głównym folderze gry:"
  Get-ChildItem (Join-Path $game '*') -File -Include *.json,*.ini,*.cfg,*.txt,*.xml | ForEach-Object { W "      $($_.Name) ($($_.Length) B)" }
}

# ---------------------------------------------------------------- 8. Steam (dla porównania)
Section "8. Gra w Steam (dla porównania)"
$steam = (Get-ItemProperty "HKCU:\Software\Valve\Steam").SteamPath
W "   SteamPath: $(Hide $steam)"
if ($steam) {
  $vdf = Join-Path $steam "steamapps\libraryfolders.vdf"
  if (Test-Path $vdf) {
    Select-String -Path $vdf -Pattern '"path"' | ForEach-Object {
      $lib = ($_.Line -replace '.*"path"\s*"([^"]+)".*', '$1') -replace '\\\\', '\'
      $g = Join-Path $lib "steamapps\common\Where Winds Meet"
      W ("   {0}  -> gra: {1}" -f (Hide $lib), $(if (Test-Path $g) { "TAK" } else { "nie" }))
    }
  }
}

$lines | Set-Content -Path $out -Encoding UTF8
Write-Host ""
Write-Host "Gotowe. Raport zapisano na pulpicie: $out" -ForegroundColor Green
Write-Host "Przejrzyj go przed wysłaniem – długie identyfikatory i nazwa użytkownika są ukryte." -ForegroundColor Yellow
