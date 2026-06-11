#!/usr/bin/env pwsh
# Build + push the Agience Prism embeddings image (bge-m3, GPU) to the registry.
# Local convenience; the CI equivalent is .github/workflows/build.yml.
#
#   .\.scripts\build.ps1                            # build + push <reg>/agience-prism:gpu
#   .\.scripts\build.ps1 -Tag v0.1.0               # also tags that
#   .\.scripts\build.ps1 -Push:$false              # build only
# (Windows PowerShell 5.1 works — just run the file; no `pwsh` needed. Or use the
#  VS Code task "Prism: Build & push image".)
#
# Requires Docker (BuildKit) and — until agience-host is on PyPI — the host
# repo as a SIBLING dir (../agience-host) for the build context. Log in first:
#   docker login            (Docker Hub; same registry the core suite uses)
[CmdletBinding()]
param(
  [string]$Registry = $(if ($env:REGISTRY) { $env:REGISTRY } else { "agience" }),
  [string]$Image    = "agience-prism",
  [string]$Tag      = "gpu",
  [string]$HostPath   = "../agience-host",
  [bool]  $Push     = $true
)
$ErrorActionPreference = "Stop"
$env:DOCKER_BUILDKIT = "1"

$ref = "$Registry/${Image}:${Tag}"
Write-Host "==> Building $ref  (host context: $HostPath)" -ForegroundColor Cyan
docker build --build-context "host=$HostPath" -f Dockerfile.gpu -t $ref .
if ($LASTEXITCODE -ne 0) { throw "docker build failed" }

if ($Push) {
  Write-Host "==> Pushing $ref" -ForegroundColor Cyan
  docker push $ref
  if ($LASTEXITCODE -ne 0) { throw "docker push failed (run 'docker login' first)" }
  Write-Host "==> Pushed $ref" -ForegroundColor Green
} else {
  Write-Host "==> Built $ref (not pushed)" -ForegroundColor Yellow
}
Write-Host "Next: deploy -> prism-agience-ai/.scripts/deploy-runpod.ps1 -Image $ref" -ForegroundColor Cyan
