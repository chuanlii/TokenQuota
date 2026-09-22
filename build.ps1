<#
.SYNOPSIS
    把 TokenQuota 打包成免安装的 exe（目标机器不需要装 Python / PySide6）。

.EXAMPLE
    .\build.ps1                    # 默认：单文件 dist\TokenQuota.exe
    .\build.ps1 -Mode onedir       # 目录版，启动更快（dist\TokenQuota\TokenQuota.exe）
    .\build.ps1 -Mode both         # 两种都打，自己比一下启动速度
    .\build.ps1 -Console           # 保留控制台窗口，报错能看见
    .\build.ps1 -Clean             # 先清掉 build\ 和 dist\
    .\build.ps1 -NoIcon            # 跳过图标生成，用 PyInstaller 默认图标

.NOTES
    这里故意不把 $ErrorActionPreference 设成 'Stop'：PowerShell 5.1 会把原生命令
    写到 stderr 的任何一行（PyInstaller 的日志就走 stderr）当成 NativeCommandError
    抛出来，构建会被莫名其妙地打断。改成逐条检查 $LASTEXITCODE，并把 stderr 收进
    临时文件，失败时再打出来。
#>
[CmdletBinding()]
param(
    [ValidateSet('onefile', 'onedir', 'both')]
    [string]$Mode = 'onefile',

    [switch]$Console,

    [switch]$Clean,

    [switch]$NoIcon
)

$ErrorActionPreference = 'Continue'

$root = $PSScriptRoot
$specPath = Join-Path $root 'packaging\TokenQuota.spec'
$iconScript = Join-Path $root 'packaging\make_icon.py'
$iconPath = Join-Path $root 'packaging\TokenQuota.ico'
$distDir = Join-Path $root 'dist'

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Invoke-Native {
    <# 跑一个外部程序，返回 stdout；stderr 收进临时文件，失败时打出来并抛错。#>
    param(
        [Parameter(Mandatory)] [string] $Exe,
        [string[]] $Arguments = @(),
        [Parameter(Mandatory)] [string] $What,
        [switch] $ShowStderrOnSuccess
    )

    $errFile = [System.IO.Path]::GetTempFileName()
    try {
        $stdout = & $Exe @Arguments 2> $errFile
        $code = $LASTEXITCODE
        $stderr = if ((Get-Item $errFile).Length -gt 0) {
            @(Get-Content -Encoding UTF8 $errFile)
        } else {
            @()
        }

        if ($code -ne 0) {
            Write-Host "    $What 失败（退出码 $code）" -ForegroundColor Red
            foreach ($line in $stderr) { Write-Host "      $line" -ForegroundColor DarkGray }
            throw "$What 失败"
        }

        if ($stderr.Count -gt 0) {
            $color = if ($ShowStderrOnSuccess) { 'DarkGray' } else { 'Yellow' }
            foreach ($line in $stderr) { Write-Host "      $line" -ForegroundColor $color }
        }

        return $stdout
    } finally {
        Remove-Item $errFile -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------- 环境检查

Write-Step '检查 Python 与打包依赖'

$pythonExe = $null
foreach ($candidate in @('python', 'py')) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found) {
        $pythonExe = $found.Source
        break
    }
}
if (-not $pythonExe) {
    throw '没找到 python，请先安装 Python 3.11+ 并加入 PATH。'
}

$pyVersion = Invoke-Native -Exe $pythonExe -What '读取 Python 版本' `
    -Arguments @('-c', "import sys; print('.'.join(map(str, sys.version_info[:3])))")
Write-Host "    Python      : $pyVersion  ($pythonExe)"

$pySideVersion = Invoke-Native -Exe $pythonExe -What '检查 PySide6' `
    -Arguments @('-c', 'import PySide6; print(PySide6.__version__)')
Write-Host "    PySide6     : $pySideVersion"

$pyiVersion = Invoke-Native -Exe $pythonExe -What '检查 PyInstaller' `
    -Arguments @('-c', 'import PyInstaller; print(PyInstaller.__version__)')
Write-Host "    PyInstaller : $pyiVersion"

# ---------------------------------------------------------------- 版本号一致性

Write-Step '校验版本号'

$appInit = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'app\__init__.py')
if ($appInit -notmatch 'VERSION\s*=\s*"([^"]+)"') {
    throw '没能从 app\__init__.py 里读到 VERSION。'
}
$codeVersion = $Matches[1]

$viText = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'packaging\version_info.txt')
if ($viText -notmatch "FileVersion',\s*'([^']+)'") {
    throw '没能从 packaging\version_info.txt 里读到 FileVersion。'
}
$exeVersion = $Matches[1]

if ($codeVersion -ne $exeVersion) {
    throw "版本号不一致：app\__init__.py 是 $codeVersion，packaging\version_info.txt 是 $exeVersion。请改成一致再打包。"
}
Write-Host "    VERSION     : $codeVersion"

# ---------------------------------------------------------------- 图标

if ($NoIcon) {
    Write-Host ''
    Write-Host '    （-NoIcon：跳过图标生成）' -ForegroundColor DarkGray
} else {
    Write-Step '生成 exe 图标'
    Invoke-Native -Exe $pythonExe -What '生成图标' -Arguments @($iconScript) | Write-Host
    if (-not (Test-Path $iconPath)) {
        throw '图标文件没生成出来。可加 -NoIcon 跳过，先确认打包流程本身是否正常。'
    }
}

# ---------------------------------------------------------------- 清理

if ($Clean) {
    Write-Step '清理旧的构建产物'
    foreach ($path in @((Join-Path $root 'build'), $distDir)) {
        if (Test-Path $path) {
            Remove-Item -Recurse -Force $path
            Write-Host "    已删除 $path"
        }
    }
}

# ---------------------------------------------------------------- 打包

$targets = @($Mode)
if ($Mode -eq 'both') {
    $targets = @('onefile', 'onedir')
}

foreach ($target in $targets) {
    Write-Step "打包（$target）"

    if ($target -eq 'onefile') {
        $env:TOKENQUOTA_ONE_FILE = '1'
    } else {
        $env:TOKENQUOTA_ONE_FILE = '0'
    }
    $env:TOKENQUOTA_CONSOLE = if ($Console) { '1' } else { '0' }

    Invoke-Native -Exe $pythonExe -What "PyInstaller（$target）" -ShowStderrOnSuccess -Arguments @(
        '-m', 'PyInstaller', $specPath,
        '--noconfirm',
        '--distpath', $distDir,
        '--workpath', (Join-Path $root "build\$target"),
        '--log-level', 'WARN'
    ) | Out-Null
}

# ---------------------------------------------------------------- 结果

Write-Step '构建结果'

$artifacts = @(
    @{ Name = '单文件'; Path = (Join-Path $distDir 'TokenQuota.exe') },
    @{ Name = '目录版'; Path = (Join-Path $distDir 'TokenQuota\TokenQuota.exe') }
)

$found = $false
foreach ($item in $artifacts) {
    if (-not (Test-Path $item.Path)) {
        continue
    }
    $found = $true

    $leaf = Get-Item $item.Path
    $sizeText = '{0:N1} MB' -f ($leaf.Length / 1MB)
    if ($item.Name -eq '目录版') {
        $total = (Get-ChildItem (Split-Path $item.Path) -Recurse -File |
            Measure-Object -Property Length -Sum).Sum
        $sizeText = "$sizeText（整个目录 {0:N1} MB）" -f ($total / 1MB)
    }

    Write-Host ''
    Write-Host "    $($item.Name)" -ForegroundColor Green
    Write-Host "      路径：$($item.Path)"
    Write-Host "      大小：$sizeText"
}

if (-not $found) {
    throw '没找到构建产物，请检查上面的 PyInstaller 输出。'
}

Write-Host ''
Write-Host '提示：exe 只是免掉了 Python 运行环境，取数仍然依赖本机的' -ForegroundColor DarkGray
Write-Host '      Codex CLI 登录态和 OpenCode Go 的 key，换机器前先确认这两样。' -ForegroundColor DarkGray
Write-Host ''
