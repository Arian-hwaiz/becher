# Becher starten, stoppen und prüfen, ohne dass Fenster offen stehen bleiben.
#
#   powershell -ExecutionPolicy Bypass -File scripts\becher.ps1 start      # alles starten
#   powershell -ExecutionPolicy Bypass -File scripts\becher.ps1 stop       # alles stoppen
#   powershell -ExecutionPolicy Bypass -File scripts\becher.ps1 restart    # neu starten (z. B. nach git pull)
#   powershell -ExecutionPolicy Bypass -File scripts\becher.ps1 status     # was läuft?
#   ... becher.ps1 restart -Teil dashboard,admin                           # nur einzelne Teile
#
# Teile:
#   dashboard  Nutzeransicht   http://localhost:8501
#   admin      Admin-Bereich   http://localhost:8502
#   scraper    eigene Scraper im Dauerbetrieb (Collector aus .env, alle -Interval Sekunden, mit Scan)
#
# Alles läuft unsichtbar im Hintergrund. Ausgaben stehen in logs\<teil>.log, die Prozessnummern in .run\<teil>.pid.
# "stop" beendet auch übrig gebliebene Becher-Prozesse und Fenster aus früheren Starts.
param(
    [Parameter(Position = 0)][ValidateSet("start", "stop", "restart", "status")][string]$Aktion = "status",
    [ValidateSet("dashboard", "admin", "scraper")][string[]]$Teil = @("dashboard", "admin", "scraper"),
    [int]$Port = 8501,
    [int]$AdminPort = 8502,
    [int]$Interval = 900
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
$runDir = Join-Path $repo ".run"
$logDir = Join-Path $repo "logs"
if (-not (Test-Path $python)) { Write-Error "venv fehlt: $python (siehe docs/HANDBUCH.md)"; exit 1 }
New-Item -ItemType Directory -Force -Path $runDir, $logDir | Out-Null

# Je Teil: Argumente für python.exe und ein Muster, an dem man den Prozess in der Prozessliste wiedererkennt
$teile = @{
    dashboard = @{ Args = @("-m", "streamlit", "run", "dashboard\app.py", "--server.port", "$Port", "--server.headless", "true")
                   Muster = "streamlit*dashboard?app.py"; Url = "http://localhost:$Port" }
    admin     = @{ Args = @("-m", "streamlit", "run", "dashboard\admin.py", "--server.port", "$AdminPort", "--server.headless", "true")
                   Muster = "streamlit*dashboard?admin.py"; Url = "http://localhost:$AdminPort" }
    scraper   = @{ Args = @("-m", "collectors.run", "--scan", "--interval", "$Interval")
                   Muster = "collectors.run"; Url = "" }
}

function Get-BecherProzesse([string]$Muster) {
    # Alle Python-Prozesse, deren Befehlszeile zum Teil passt (auch solche aus früheren Starts in eigenen Fenstern)
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
        Where-Object { $_.CommandLine -and ($_.CommandLine -like "*$Muster*") }
}

function Stop-Teil([string]$Name) {
    $pidFile = Join-Path $runDir "$Name.pid"
    $ids = @()
    if (Test-Path $pidFile) { $ids += [int](Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1) }
    $ids += @(Get-BecherProzesse $teile[$Name].Muster | ForEach-Object { [int]$_.ProcessId })
    $ids = $ids | Where-Object { $_ -gt 0 } | Sort-Object -Unique
    foreach ($id in $ids) {
        if (Get-Process -Id $id -ErrorAction SilentlyContinue) {
            & taskkill.exe /PID $id /T /F 2>$null | Out-Null     # /T beendet auch Kindprozesse (z. B. den Browser des Scrapers)
        }
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    if ($ids) { Write-Host "$Name gestoppt." } else { Write-Host "$Name lief nicht." }
}

function Close-AlteFenster {
    # Fenster aus früheren Starts ("Becher Scraper", "Becher Dashboard", "Becher Admin") schließen. Andere Fenster bleiben unberührt.
    Get-Process powershell, pwsh -ErrorAction SilentlyContinue |
        Where-Object { $_.Id -ne $PID -and $_.MainWindowTitle -like "Becher *" } |
        ForEach-Object { & taskkill.exe /PID $_.Id /T /F 2>$null | Out-Null; Write-Host "Altes Fenster geschlossen: $($_.MainWindowTitle)" }
}

function Start-Teil([string]$Name) {
    if (@(Get-BecherProzesse $teile[$Name].Muster).Count -gt 0) { Write-Host "$Name läuft schon."; return }
    $log = Join-Path $logDir "$Name.log"
    $env:PYTHONUNBUFFERED = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $p = Start-Process -FilePath $python -ArgumentList $teile[$Name].Args -WorkingDirectory $repo -WindowStyle Hidden `
        -RedirectStandardOutput $log -RedirectStandardError (Join-Path $logDir "$Name.fehler.log") -PassThru
    Set-Content -Path (Join-Path $runDir "$Name.pid") -Value $p.Id
    Write-Host ("$Name gestartet (Prozess $($p.Id)) " + $teile[$Name].Url)
}

function Show-Status {
    foreach ($name in @("dashboard", "admin", "scraper")) {
        $ps = @(Get-BecherProzesse $teile[$name].Muster)
        if ($ps.Count -gt 0) { Write-Host ("{0,-10} läuft   (Prozess {1}) {2}" -f $name, ($ps.ProcessId -join ", "), $teile[$name].Url) }
        else { Write-Host ("{0,-10} gestoppt" -f $name) }
    }
    Write-Host "Protokolle: $logDir"
}

switch ($Aktion) {
    "start"   { foreach ($t in $Teil) { Start-Teil $t }; Show-Status }
    "stop"    { foreach ($t in $Teil) { Stop-Teil $t }; Close-AlteFenster }
    "restart" { foreach ($t in $Teil) { Stop-Teil $t }; Close-AlteFenster; Start-Sleep -Seconds 1; foreach ($t in $Teil) { Start-Teil $t }; Show-Status }
    "status"  { Show-Status }
}
