param(
    [string]$SourceRoot = 'E:\MIO\cwb_compensation_20261004',
    [string]$PatcherRoot = 'E:\MIO\github\OriginOS-OnePlus-Brightness-Patcher',
    [string]$TutorialPath = 'E:\MIO\OriginOS_一加亮度_HDR_CWB_从零适配教程_20261005.txt',
    [string]$OutputRoot = 'C:\Users\a1510\Videos',
    [string]$Donor13TRoot = 'E:\MIO\tools\OplusDisplayBuilder\research\incoming_13t\donor',
    [string]$PackageName = 'OP13_CWB_Source_Backup_20261005',
    [string[]]$PrivateDeviceIdentifiers = @(),
    [switch]$IncludePrivateInputs,
    [string]$PublicRoot
)

$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false, $true)
$SourceRoot = (Resolve-Path -LiteralPath $SourceRoot).Path
$PatcherRoot = (Resolve-Path -LiteralPath $PatcherRoot).Path
$TutorialPath = (Resolve-Path -LiteralPath $TutorialPath).Path
if ($PackageName -notmatch '^[A-Za-z0-9_-]+$') { throw 'PackageName只能包含英文、数字、横线和下划线' }
$output = [System.IO.Path]::GetFullPath($OutputRoot)
$package = Join-Path $output $PackageName
if (Test-Path -LiteralPath $package) { throw "输出目录已存在，未覆盖: $package" }
if (Test-Path -LiteralPath ($package + '.zip')) { throw '同名ZIP已存在，未覆盖' }
New-Item -ItemType Directory -Path $package | Out-Null
$selected = New-Object 'System.Collections.Generic.List[object]'

function Copy-Selected([string]$From, [string]$Relative, [string]$Category = 'source') {
    if (-not (Test-Path -LiteralPath $From -PathType Leaf)) { throw "必要输入不存在: $From" }
    if ($Relative -match '(^|[\\/])\.\.([\\/]|$)' -or [System.IO.Path]::IsPathRooted($Relative)) { throw '非法相对路径' }
    $destination = Join-Path $package $Relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $From -Destination $destination
    $selected.Add([pscustomobject]@{ Path=$Relative.Replace('\','/'); Category=$Category; Bytes=(Get-Item -LiteralPath $destination).Length })
}

# Explicit source allowlist: never sweep logs, dumps, screenshots, ELF or personal data.
Get-ChildItem -LiteralPath $SourceRoot -File | Where-Object {
    $_.Extension -in '.cpp','.h','.py','.ps1','.sh' -or $_.Name -eq 'cwb_check.sh.in'
} | Sort-Object Name | ForEach-Object { Copy-Selected $_.FullName ('cwb_compensation_20261004/' + $_.Name) }
foreach ($name in 'module.prop','customize.sh','sepolicy.rule','display_nodes.cil','user_additions.cil','README.txt') {
    Copy-Selected (Join-Path $SourceRoot ('module_files/' + $name)) ('cwb_compensation_20261004/module_files/' + $name)
}
foreach ($name in 'AndroidManifest.xml','MainActivity.java','build.py') {
    Copy-Selected (Join-Path $SourceRoot ('pattern_app/' + $name)) ('cwb_compensation_20261004/pattern_app/' + $name)
}
foreach ($name in 'research_native.py','native.py','configs.py','sources.py','cil_policy.py','rom_io.py','requirements.txt','LICENSE') {
    Copy-Selected (Join-Path $PatcherRoot $name) ('tools/OplusOriginPatcher/' + $name) 'supporting-source'
}
# Oracle metadata, not extracted instruction listings or runtime captures.
Get-ChildItem -LiteralPath (Join-Path $SourceRoot 'official_branch_audit') -Recurse -File -Filter '*.json' |
    Where-Object { $_.Name -eq 'index.json' -or $_.DirectoryName -eq (Join-Path $SourceRoot 'official_branch_audit') } |
    ForEach-Object {
        $relative = $_.FullName.Substring($SourceRoot.Length + 1).Replace('\','/')
        Copy-Selected $_.FullName ('cwb_compensation_20261004/' + $relative) 'offline-audit-metadata'
    }
Copy-Selected $TutorialPath 'docs/OriginOS_一加亮度_HDR_CWB20261005.txt' 'tutorial'
foreach ($name in 'CWB源码交接说明.txt','13T适配取材清单.txt') {
    Copy-Selected (Join-Path $PSScriptRoot ('cwb_backup_docs/' + $name)) $name 'handoff'
    Copy-Selected (Join-Path $PSScriptRoot ('cwb_backup_docs/' + $name)) ('tools/cwb_backup_docs/' + $name) 'packaging-template'
}
Copy-Selected $PSCommandPath 'tools/Backup-OriginOSCwbSources.ps1' 'packaging-script'

if ($IncludePrivateInputs) {
    foreach ($name in 'preinstall_libsensorservice.so','preinstall_libsensorcompat_ovsc.so',
        'libsensorservice_live.so','coloros_live_client.so','coloros_live_ext.so',
        'cwb_hidl.so','cwb_aidl.so','displaypanelfeature.so','origin_live_vendor_cwb.so',
        'origin_live_libsdmclient.so','origin_live_libsdmcore.so','origin_live_libbinder_ndk.so',
        'origin_live_libgui.so','origin_live_libui.so','origin_live_surfaceflinger') {
        Copy-Selected (Join-Path $SourceRoot $name) ('private_inputs/OP13/' + $name) 'private-rom-input'
    }
    $deployed = Join-Path $output 'OP13_OriginOS_CWB_Compensation_Test_20261005_v5.zip'
    if (Test-Path -LiteralPath $deployed) {
        Copy-Selected $deployed ('private_inputs/deployed/' + (Split-Path -Leaf $deployed)) 'private-deployed-baseline'
    }
    if (Test-Path -LiteralPath $Donor13TRoot) {
        Get-ChildItem -LiteralPath (Join-Path $Donor13TRoot 'my_product/etc/fusionlight_profile') -File -Filter '*.json' |
            ForEach-Object { Copy-Selected $_.FullName ('private_inputs/OP13T/my_product/etc/fusionlight_profile/' + $_.Name) 'private-13t-reference' }
        Get-ChildItem -LiteralPath (Join-Path $Donor13TRoot 'odm/etc/display') -File -Filter '*cwb_weights*.json' |
            ForEach-Object { Copy-Selected $_.FullName ('private_inputs/OP13T/odm/etc/display/' + $_.Name) 'private-13t-reference' }
    }
}

$manifest = [ordered]@{
    version=1; snapshot='2026-10-05'; source_state='current development source; not identical to deployed v5';
    raw_source_preserved=$true; includes_private_inputs=[bool]$IncludePrivateInputs;
    exclusions=@('runtime logs','screenshots','account data','persist or per-device W_VIEW','Git credentials','SDK/build caches');
    files=$selected.ToArray()
}
[System.IO.File]::WriteAllText((Join-Path $package 'BACKUP_MANIFEST.json'), ($manifest | ConvertTo-Json -Depth 8), $utf8)

if ($PublicRoot) {
    $PublicRoot = [System.IO.Path]::GetFullPath($PublicRoot)
    if (Test-Path -LiteralPath $PublicRoot) { throw '公开快照目录已存在，未覆盖' }
    New-Item -ItemType Directory -Path $PublicRoot | Out-Null
    $publicChanges = New-Object 'System.Collections.Generic.List[string]'
    foreach ($entry in $selected | Where-Object { $_.Category -notlike 'private-*' }) {
        $sourceFile = Join-Path $package $entry.Path
        $destination = Join-Path $PublicRoot $entry.Path
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        $body = $utf8.GetString([System.IO.File]::ReadAllBytes($sourceFile))
        # Public scripts must not identify the owner's phone; local snapshot stays byte-exact.
        if ($entry.Path -match '\.(ps1|py|sh)$') {
            $masked = $body
            foreach ($identifier in $PrivateDeviceIdentifiers) {
                if ($identifier) { $masked = $masked.Replace($identifier, 'DEVICE_SERIAL') }
            }
            if ($masked -cne $body) { $publicChanges.Add($entry.Path) }
            $body = $masked
        }
        if ($body -match '(?i)github_pat_[A-Za-z0-9_]{15,}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----') {
            throw "发现疑似凭据，停止生成公开快照: $($entry.Path)"
        }
        [System.IO.File]::WriteAllText($destination, $body, $utf8)
    }
    $publicManifest = [ordered]@{
        version=1; snapshot='2026-10-05'; includes_private_inputs=$false;
        device_identifier_redacted_in=$publicChanges.ToArray(); source_state=$manifest.source_state;
        excluded_from_public=@('private_inputs/','firmware ELF','deployed module binaries','runtime logs','persist or per-device W_VIEW');
        files=@($selected | Where-Object { $_.Category -notlike 'private-*' })
    }
    [System.IO.File]::WriteAllText((Join-Path $PublicRoot 'BACKUP_MANIFEST.json'), ($publicManifest | ConvertTo-Json -Depth 8), $utf8)
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open(($package + '.zip'), [System.IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($file in Get-ChildItem -LiteralPath $package -Recurse -File) {
        $relative = $file.FullName.Substring($package.Length + 1).Replace('\','/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $file.FullName,
            ($PackageName + '/' + $relative), [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally { $zip.Dispose() }
[pscustomobject]@{ Directory=$package; Zip=($package+'.zip'); Files=$selected.Count; Bytes=(Get-Item -LiteralPath ($package+'.zip')).Length; PublicRoot=$PublicRoot } | ConvertTo-Json
