<#
.SYNOPSIS
    Install the odin skill for Claude Code and/or Codex.

.EXAMPLE
    ./install.ps1                      # install for every CLI detected
    ./install.ps1 -Target claude       # Claude Code only
    ./install.ps1 -Target codex -Force # Codex only, overwrite
    ./install.ps1 -Scope project -ProjectPath C:\work\repo
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'claude', 'codex')]
    [string]$Target = 'all',

    [ValidateSet('user', 'project')]
    [string]$Scope = 'user',

    [string]$ProjectPath = (Get-Location).Path,

    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$SkillRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$SkillName = 'odin'

# Resolve the home directory explicitly. PowerShell's $HOME follows USERPROFILE on
# Windows and ignores a HOME override, so prefer an explicit odin_home when set.
$UserHome = if ($env:odin_home) { $env:odin_home }
            elseif ($env:USERPROFILE) { $env:USERPROFILE }
            elseif ($env:HOME) { $env:HOME }
            else { $HOME }

if (-not (Test-Path (Join-Path $SkillRoot 'SKILL.md'))) {
    throw "SKILL.md not found next to the installer; expected skill root at $SkillRoot"
}

function Copy-Skill {
    param([string]$Destination)

    if (Test-Path $Destination) {
        if (-not $Force) {
            Write-Host "  exists, skipping (use -Force to overwrite): $Destination"
            return $false
        }
        Remove-Item -Recurse -Force $Destination
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    foreach ($item in @('SKILL.md', 'PROTOCOL.md', 'AGENTS.md', 'README.md')) {
        $source = Join-Path $SkillRoot $item
        if (Test-Path $source) { Copy-Item $source $Destination }
    }
    foreach ($dir in @('reference', 'templates', 'scripts', 'prompts')) {
        $source = Join-Path $SkillRoot $dir
        if (Test-Path $source) {
            Copy-Item $source (Join-Path $Destination $dir) -Recurse
        }
    }
    # Drop compiled bytecode that may have been produced by local testing.
    Get-ChildItem -Path $Destination -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    return $true
}

$installed = @()

if ($Target -in @('all', 'claude')) {
    $base = if ($Scope -eq 'project') {
        Join-Path (Resolve-Path $ProjectPath).Path '.claude/skills'
    } else {
        Join-Path $UserHome '.claude/skills'
    }
    $dest = Join-Path $base $SkillName
    Write-Host "Claude Code -> $dest"
    if (Copy-Skill -Destination $dest) {
        $installed += "Claude Code ($Scope): $dest"
        Write-Host "  installed. Invoke with /odin"
    }
}

if ($Target -in @('all', 'codex')) {
    $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $UserHome '.codex' }
    $dest = Join-Path $codexHome "skills/$SkillName"
    Write-Host "Codex -> $dest"
    if (Copy-Skill -Destination $dest) {
        $installed += "Codex: $dest"
    }

    $promptDir = Join-Path $codexHome 'prompts'
    New-Item -ItemType Directory -Force -Path $promptDir | Out-Null
    $promptFile = Join-Path $promptDir "$SkillName.md"
    if ((Test-Path $promptFile) -and -not $Force) {
        Write-Host "  prompt exists, skipping (use -Force): $promptFile"
    } else {
        $body = Get-Content (Join-Path $SkillRoot 'prompts/odin.md') -Raw
        $body = $body.Replace('{{odin_dir}}', $dest.Replace('\', '/'))
        Set-Content -Path $promptFile -Value $body -Encoding utf8 -NoNewline
        $installed += "Codex prompt: $promptFile"
        Write-Host "  prompt installed. Invoke with /odin"
    }
}

Write-Host ''
if ($installed.Count -eq 0) {
    Write-Host 'Nothing installed.'
} else {
    Write-Host 'Installed:'
    $installed | ForEach-Object { Write-Host "  $_" }
}

$python = Get-Command python3 -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
if ($python) {
    Write-Host "Python found: $($python.Source)"
} else {
    Write-Host 'WARNING: no python3 on PATH. The toolkit needs Python 3.8+ (stdlib only).'
}
