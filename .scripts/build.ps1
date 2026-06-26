#!/usr/bin/env pwsh
# Build + push the Agience Prism embeddings image (bge-m3, GPU) to the registry,
# and — with -Deploy — roll the RunPod pod, all in one shot.
# Local convenience; the CI equivalent is .github/workflows/build.yml.
#
#   .\.scripts\build.ps1                              # build + push <reg>/agience-prism:gpu
#   .\.scripts\build.ps1 -Tag gpu-2026-06-25          # also build/push that (immutable) tag
#   .\.scripts\build.ps1 -Push:$false                 # build only
#   .\.scripts\build.ps1 -Tag gpu-2026-06-25 -Deploy  # build + push + roll the pod (ONE shot)
# (Windows PowerShell 5.1 works — just run the file; no `pwsh` needed. Or use the
#  VS Code task "Prism: Build & push image".)
#
# Requires Docker (BuildKit) and — until agience-kit is on PyPI — the kit repo as
# a SIBLING dir (../agience-kit) for the build context. Log in first:
#   docker login            (Docker Hub; same registry the core suite uses)
#
# -Deploy chains into the sibling deploy repo's IN-PLACE pod update
# (../prism-agience-ai/.scripts/deploy-runpod.ps1) — same pod id/URL/volume, so no
# edge re-point. Needs $env:RUNPOD_API_KEY. Prefer an immutable -Tag with -Deploy:
# PATCHing the moving :gpu tag can reuse RunPod's image cache and skip the re-pull.
[CmdletBinding()]
param(
  [string]$Registry = $(if ($env:REGISTRY) { $env:REGISTRY } else { "agience" }),
  [string]$Image    = "agience-prism",
  [string]$Tag      = "gpu",
  [string]$KitPath  = "../agience-kit",
  [bool]  $Push     = $true,
  [switch]$Deploy,
  [string]$DeployScript = $(if ($env:PRISM_DEPLOY_SCRIPT) { $env:PRISM_DEPLOY_SCRIPT } else { "../prism-agience-ai/.scripts/deploy-runpod.ps1" })
)
$ErrorActionPreference = "Stop"
$env:DOCKER_BUILDKIT = "1"

if ($Deploy -and -not $Push) { throw "-Deploy needs a pushed image; don't combine it with -Push:`$false" }

$ref = "$Registry/${Image}:${Tag}"
Write-Host "==> Building $ref  (kit context: $KitPath)" -ForegroundColor Cyan
docker build --build-context "kit=$KitPath" -f Dockerfile.gpu -t $ref .
if ($LASTEXITCODE -ne 0) { throw "docker build failed" }

if ($Push) {
  Write-Host "==> Pushing $ref" -ForegroundColor Cyan
  docker push $ref
  if ($LASTEXITCODE -ne 0) { throw "docker push failed (run 'docker login' first)" }
  Write-Host "==> Pushed $ref" -ForegroundColor Green
} else {
  Write-Host "==> Built $ref (not pushed)" -ForegroundColor Yellow
}

if ($Deploy) {
  if (-not (Test-Path $DeployScript)) {
    throw "deploy script not found: $DeployScript (run from the agience-prism repo root with prism-agience-ai as a sibling, or set `$env:PRISM_DEPLOY_SCRIPT)"
  }
  if (-not $env:RUNPOD_API_KEY) { throw "set `$env:RUNPOD_API_KEY to deploy" }
  Write-Host "==> Deploying $ref to RunPod (in-place pod update)" -ForegroundColor Cyan
  & $DeployScript -Image $ref          # throws on failure (its $ErrorActionPreference=Stop)
  Write-Host "==> Deployed $ref" -ForegroundColor Green
} else {
  Write-Host "Next: deploy -> prism-agience-ai/.scripts/deploy-runpod.ps1 -Image $ref  (or re-run with -Deploy)" -ForegroundColor Cyan
}
