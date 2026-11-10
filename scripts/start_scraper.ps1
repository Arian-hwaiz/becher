# Startet die eigenen Scraper im Dauerbetrieb in einem eigenen Fenster.
#
#   powershell -ExecutionPolicy Bypass -File scripts\start_scraper.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start_scraper.ps1 -Collectors "bwin,admiral" -Interval 900
#
# Stoppen: das Fenster „Becher Scraper“ schließen oder darin Strg+C drücken.
# Einzelne Anbieter ab- oder zuschalten: Dashboard → System → Anbieter & Scraper (gilt ab dem nächsten Durchlauf).
# Kostet keine Odds-API-Credits. Blockt ein Anbieter (403/Cloudflare/Captcha), schaltet sich sein
# Collector selbst ab und der Anbieter steht in der Administration auf „blockiert“.
param(
    [string]$Collectors = "bwin,admiral,interwetten",
    [int]$Interval = 900
)

$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "venv fehlt: $python (siehe docs/HANDBUCH.md)"
    exit 1
}

$cmd = "`$Host.UI.RawUI.WindowTitle = 'Becher Scraper'; Set-Location '$repo'; " +
       "& '$python' -m collectors.run --only $Collectors --scan --interval $Interval"
Start-Process powershell -WorkingDirectory $repo -ArgumentList '-NoExit', '-Command', $cmd
Write-Host "Scraper gestartet ($Collectors, alle $Interval s) im Fenster 'Becher Scraper'."
