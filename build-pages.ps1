<#
.SYNOPSIS
  Regenerates docs/index.html for GitHub Pages from app.html, with the live Render
  backend URL injected. Run this then commit+push whenever app.html changes.
#>
param(
  [string]$ApiBase = "https://cpm-ground-app.onrender.com/api/v1"
)
$src = Join-Path $PSScriptRoot "app.html"
$docsDir = Join-Path $PSScriptRoot "docs"
New-Item -ItemType Directory -Force -Path $docsDir | Out-Null
$html = Get-Content $src -Raw
$inject = "<script>window.CPM_API_BASE=" + "'" + $ApiBase + "'" + ";</script>`n"
$html = $html -replace '(<meta charset="utf-8">)', ('$1' + "`n" + $inject)
Set-Content -Path (Join-Path $docsDir "index.html") -Value $html -Encoding utf8
Write-Output "Wrote $docsDir\index.html with API base: $ApiBase"
