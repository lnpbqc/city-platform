param([switch]$Stop)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$storage = if ($env:MAP_STORAGE_DIR) { [IO.Path]::GetFullPath($env:MAP_STORAGE_DIR) } else { Join-Path $repo 'map_back/storage' }
$configPath = Join-Path $storage 'tile-service.json'
$pidPath = Join-Path $storage 'tile-service-launcher.json'
$distro = 'Ubuntu'

function Initialize-TileConfig([string]$Path) {
    if (Test-Path -LiteralPath $Path) { return }
    [IO.Directory]::CreateDirectory((Split-Path -Parent $Path)) | Out-Null
    $bytes = New-Object byte[] 32
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($bytes) } finally { $random.Dispose() }
    $config = @{ url = 'http://127.0.0.1:18744'; backend = 'http://127.0.0.1:8000'; token = -join ($bytes | ForEach-Object { $_.ToString('x2') }) }
    # CreateNew preserves an existing configuration even if two start requests race.
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $payload = [Text.Encoding]::UTF8.GetBytes(($config | ConvertTo-Json))
        $stream.Write($payload, 0, $payload.Length)
    } finally { $stream.Dispose() }
}
function Convert-ToWslPath([string]$Path) {
    $value = & wsl.exe -d $distro -- wslpath -a -u $Path.Replace('\', '/')
    if ($LASTEXITCODE -ne 0) { throw '无法转换 WSL 路径，请先确认 Ubuntu 已安装。' }
    return ($value -join '').Trim()
}
function Get-ManagedLauncher($Record) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($Record.pid)" -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    if ([IO.Path]::GetFileName($process.ExecutablePath) -ine 'wsl.exe' -or
        $process.CreationDate.ToUniversalTime().Ticks -ne ([datetime]$Record.created).ToUniversalTime().Ticks -or
        -not $process.CommandLine.Contains($Record.script) -or -not $process.CommandLine.Contains($Record.config)) {
        throw '启动进程身份已变化，拒绝停止其他进程。'
    }
    return $process
}

if ($Stop) {
    if (-not (Test-Path -LiteralPath $pidPath)) { Write-Host '没有此脚本管理的切片服务。'; return }
    $record = Get-Content -LiteralPath $pidPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $expectedScript = Convert-ToWslPath (Join-Path $PSScriptRoot 'start.sh')
    $expectedConfig = Convert-ToWslPath $configPath
    if ($record.script -ne $expectedScript -or $record.config -ne $expectedConfig) { throw '启动记录不属于当前仓库和配置，拒绝停止。' }
    $launcher = Get-ManagedLauncher $record
    & wsl.exe -d $distro -- env "CITY_TILE_CONFIG=$($record.config)" bash $record.script --stop
    if ($LASTEXITCODE -ne 0) { throw '切片服务未能安全停止，已保留进程记录。' }
    $launcher = Get-ManagedLauncher $record
    if ($launcher) { Stop-Process -Id $launcher.ProcessId -ErrorAction Stop }
    Remove-Item -LiteralPath $pidPath
    Write-Host '切片服务已停止。'
    return
}
if (Test-Path -LiteralPath $pidPath) {
    $record = Get-Content -LiteralPath $pidPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (Get-ManagedLauncher $record) { Write-Host '切片服务启动进程正在运行。'; return }
}
Initialize-TileConfig $configPath
$scriptPath = Convert-ToWslPath (Join-Path $PSScriptRoot 'start.sh')
$linuxConfig = Convert-ToWslPath $configPath
$launcher = Start-Process -FilePath 'wsl.exe' -ArgumentList @('-d', $distro, '--', 'env', "`"CITY_TILE_CONFIG=$linuxConfig`"", 'bash', "`"$scriptPath`"") -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $storage 'tile-service.stdout.log') -RedirectStandardError (Join-Path $storage 'tile-service.stderr.log')
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $($launcher.Id)"
if (-not $process) { throw '切片服务启动失败，请检查 tile-service.stderr.log。' }
@{ pid = $launcher.Id; created = $process.CreationDate.ToUniversalTime().ToString('o'); script = $scriptPath; config = $linuxConfig } | ConvertTo-Json | Set-Content -LiteralPath $pidPath -Encoding UTF8
$configuration = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try {
        $health = Invoke-RestMethod ($configuration.url.TrimEnd('/') + '/health') -TimeoutSec 1
        if ($health.status -eq 'ok' -and $health.worker_alive) {
            Write-Host '切片服务已启动，HTTP 健康检查通过。'
            return
        }
    } catch { }
    Start-Sleep -Milliseconds 500
}
& $PSCommandPath -Stop
throw '切片服务未通过健康检查，请查看 storage/tile-service.stderr.log。'
