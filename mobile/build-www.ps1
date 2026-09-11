<#
.SYNOPSIS
  Copies ../app.html into www/index.html for the Capacitor build, injecting the
  live backend URL. Run this before every `npx cap sync` / APK build so the app
  picks up both the latest app.html AND the current backend URL.
#>
param(
  [string]$ApiBase = "http://13.207.131.147/api/v1"
)
$src = Join-Path $PSScriptRoot "..\app.html"
$wwwDir = Join-Path $PSScriptRoot "www"
New-Item -ItemType Directory -Force -Path $wwwDir | Out-Null
$html = Get-Content $src -Raw -Encoding UTF8
$inject = "<script>window.CPM_API_BASE=" + "'" + $ApiBase + "'" + ";</script>`n"
$html = $html -replace '(<meta charset="utf-8">)', ('$1' + "`n" + $inject)
Set-Content -Path (Join-Path $wwwDir "index.html") -Value $html -Encoding utf8
Write-Output "Wrote $wwwDir\index.html with API base: $ApiBase"
