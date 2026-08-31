param(
    [string]$BlenderPath = 'D:\softwares\Blender Foundation\Blender 5.1\blender.exe'
)

$ErrorActionPreference = 'Stop'
$testsRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$runRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $testsRoot ('.tmp-integration-040-' + [guid]::NewGuid().ToString('N')))
)
$requiredPrefix = $testsRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not $runRoot.StartsWith($requiredPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing temporary path outside tests directory: $runRoot"
}
if (-not (Test-Path -LiteralPath $BlenderPath -PathType Leaf)) {
    throw "Blender executable not found: $BlenderPath"
}

New-Item -ItemType Directory -Path (Join-Path $runRoot 'config') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $runRoot 'scripts') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $runRoot 'datafiles') -Force | Out-Null

$oldConfig = $env:BLENDER_USER_CONFIG
$oldScripts = $env:BLENDER_USER_SCRIPTS
$oldDatafiles = $env:BLENDER_USER_DATAFILES
$oldTestRoot = $env:BCMB_TEST_ROOT

try {
    $env:BLENDER_USER_CONFIG = Join-Path $runRoot 'config'
    $env:BLENDER_USER_SCRIPTS = Join-Path $runRoot 'scripts'
    $env:BLENDER_USER_DATAFILES = Join-Path $runRoot 'datafiles'
    $env:BCMB_TEST_ROOT = $runRoot

    & $BlenderPath --background --factory-startup --python-exit-code 1 --python (Join-Path $testsRoot 'integration_040_factory.py')
    if ($LASTEXITCODE -ne 0) {
        throw "Blender integration test failed with exit code $LASTEXITCODE"
    }
}
finally {
    $env:BLENDER_USER_CONFIG = $oldConfig
    $env:BLENDER_USER_SCRIPTS = $oldScripts
    $env:BLENDER_USER_DATAFILES = $oldDatafiles
    $env:BCMB_TEST_ROOT = $oldTestRoot

    $resolvedRunRoot = [System.IO.Path]::GetFullPath($runRoot)
    if (
        $resolvedRunRoot.StartsWith($requiredPrefix, [System.StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $resolvedRunRoot)
    ) {
        Remove-Item -LiteralPath $resolvedRunRoot -Recurse -Force
    }
}
