# -*- mode: powershell -*-
# ai-doc-lint 零成本演示脚本（P3-6）
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts-dev\demo_start.ps1        # 仅本地演示（检查容器健康 + 打开浏览器）
#   powershell -ExecutionPolicy Bypass -File scripts-dev\demo_start.ps1 -Remote # 外网演示（额外启动 Cloudflare 免费隧道，打印公网 URL）
# 说明：
#   - 本地演示：确认 7 个容器 healthy，然后打开 http://localhost:8080；
#   - 外网演示：自动下载/定位 cloudflared，启动临时隧道（trycloudflare.com 随机域名），
#     展示给观众即可；Ctrl+C 停止隧道，域名随即失效，无需任何云服务器与费用。
param(
    [switch]$Remote
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

Write-Host ""
Write-Host "==================== ai-doc-lint 演示模式 ====================" -ForegroundColor Cyan

# 1. 检查 Docker 与容器健康
Write-Host "[1/3] 检查 Docker 容器状态 ..." -ForegroundColor Yellow
$compose = Join-Path $Root "docker-compose.yml"
if (-not (Test-Path $compose)) {
    Write-Host "未找到 docker-compose.yml（当前目录: $Root）" -ForegroundColor Red
    exit 1
}
Push-Location $Root
try {
    $ps = docker compose ps --format "{{.Name}} {{.Status}}"
    $healthy = ($ps | Select-String -Pattern "healthy").Count
    $total = ($ps | Measure-Object).Count
    Write-Host "容器: $healthy/$total healthy"
    if ($healthy -lt $total) {
        Write-Host "部分容器未就绪，正在启动 ..." -ForegroundColor Yellow
        docker compose up -d --wait 2>&1 | Out-Host
    }
    $ok = (Invoke-WebRequest -Uri "http://localhost:8080/health" -UseBasicParsing -TimeoutSec 10).StatusCode
    if ($ok -ne 200) { throw "前端健康检查未通过" }
    Write-Host "本地服务就绪: http://localhost:8080" -ForegroundColor Green
} finally {
    Pop-Location
}

# 2. 定位 cloudflared（仅外网模式需要）
$cloudflared = $null
if ($Remote) {
    Write-Host "[2/3] 定位 cloudflared ..." -ForegroundColor Yellow
    $cand = @("cloudflared",
        (Join-Path $Root "scripts-dev\tools\cloudflared.exe"),
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\cloudflared.exe",
        "C:\Program Files (x86)\cloudflared\cloudflared.exe",
        "C:\Program Files\cloudflared\cloudflared.exe")
    foreach ($c in $cand) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { $cloudflared = $cmd.Source; break }
        if (Test-Path $c) { $cloudflared = $c; break }
    }
    if (-not $cloudflared) {
        # 自动下载（GitHub release，约 40MB）
        Write-Host "未安装 cloudflared，自动下载到 scripts-dev/tools/ ..." -ForegroundColor Yellow
        $toolsDir = Join-Path $Root "scripts-dev\tools"
        New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
        $zip = Join-Path $toolsDir "cloudflared.zip"
        Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.zip" `
            -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $toolsDir -Force
        Remove-Item $zip -Force
        $cloudflared = Join-Path $toolsDir "cloudflared.exe"
        if (-not (Test-Path $cloudflared)) { throw "cloudflared 下载失败，请手动安装: winget install Cloudflare.cloudflared" }
    }
    Write-Host "cloudflared: $cloudflared" -ForegroundColor Green
}

# 3. 启动演示
Write-Host "[3/3] 启动演示 ..." -ForegroundColor Yellow
if ($Remote) {
    Write-Host ""
    Write-Host "正在建立 Cloudflare 免费隧道（临时公网地址，约 10 秒就绪）..." -ForegroundColor Cyan
    Write-Host "Ctrl+C 停止隧道；停止后公网地址立即失效，无任何残留。" -ForegroundColor DarkGray
    Write-Host ""
    & $cloudflared tunnel --url http://localhost:8080
} else {
    Start-Process "http://localhost:8080"
    Write-Host "已在浏览器打开 http://localhost:8080" -ForegroundColor Green
    Write-Host "本地演示结束（关闭页面即可）。如需外网演示请加 -Remote 参数。" -ForegroundColor DarkGray
}
