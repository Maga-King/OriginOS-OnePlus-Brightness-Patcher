param([int]$WaitSeconds=3,[switch]$IncludeSF)
# Finite UI stimuli + read-only snapshots. No CWB client or SSC timing writer.
$ErrorActionPreference='Stop'
if ($WaitSeconds -lt 1 -or $WaitSeconds -gt 6) { throw 'WaitSeconds must be 1..6' }
$adb='C:\adb-fastboot\adb.exe'
$serial='DEVICE_SERIAL'
function Invoke-Adb {
    param([string[]]$AdbArguments)
    $savedPreference=$ErrorActionPreference
    $ErrorActionPreference='Continue'
    try {
        $result=@(& $adb -s $serial @AdbArguments 2>&1) | ForEach-Object { [string]$_ }
        $resultCode=$LASTEXITCODE
    } finally { $ErrorActionPreference=$savedPreference }
    if ($resultCode -ne 0) { throw "adb failed: $AdbArguments; $result" }
    return $result
}
if ((Invoke-Adb -AdbArguments @('shell','getprop','ro.gsid.image_running')).Trim() -ne '1') { throw 'DSU only' }
$power=Invoke-Adb -AdbArguments @('shell','dumpsys','power')
if (-not ($power -match 'mWakefulness=Awake')) { throw 'Display must already be awake' }
$foreground=Invoke-Adb -AdbArguments @('shell','dumpsys','activity','activities')
if (-not ($foreground -match 'topResumedActivity=.*local.nyako.cwbpattern')) { throw 'Pattern app must already be foreground' }
Invoke-Adb -AdbArguments @('push',(Join-Path $PSScriptRoot 'comp_status_probe'),'/data/local/tmp/cwb_status_snapshot') | Out-Null
Invoke-Adb -AdbArguments @('shell','su','-c','chmod 700 /data/local/tmp/cwb_status_snapshot') | Out-Null
Invoke-Adb -AdbArguments @('push',(Join-Path $PSScriptRoot 'cwb_state_probe'),'/data/local/tmp/cwb_state_snapshot') | Out-Null
Invoke-Adb -AdbArguments @('shell','su','-c','chmod 700 /data/local/tmp/cwb_state_snapshot') | Out-Null
$servicePid=(Invoke-Adb -AdbArguments @('shell','pidof','system_server')).Trim()
if ($servicePid -notmatch '^\d+$') { throw 'Invalid system_server PID' }
$composerPid=(Invoke-Adb -AdbArguments @('shell','pidof','vendor.qti.hardware.display.composer-service')).Trim()
if ($composerPid -notmatch '^\d+$') { throw 'Invalid display composer PID' }
$roi=$null
if ($IncludeSF) {
    $displaySize=Invoke-Adb -AdbArguments @('shell','wm','size')
    $sizes=@([regex]::Matches(($displaySize -join "`n"),'(?:Physical|Override) size: (\d+)x(\d+)'))
    if (-not $sizes.Count) { throw 'Unknown display size for finite SF diagnostic' }
    $width=[int]$sizes[-1].Groups[1].Value; $height=[int]$sizes[-1].Groups[2].Value
    if (@('1080x2376','1440x3168') -notcontains "${width}x${height}") { throw 'Unaudited geometry' }
    $roi=@([int][math]::Floor(1010*$width/1440),[int][math]::Floor(148*$height/3168),
           [int][math]::Floor(1048*$width/1440),[int][math]::Floor(190*$height/3168))
    Invoke-Adb -AdbArguments @('push',(Join-Path $PSScriptRoot 'sf_roi_probe'),'/data/local/tmp/sf_roi_probe') | Out-Null
    Invoke-Adb -AdbArguments @('shell','su','-c','chmod 700 /data/local/tmp/sf_roi_probe') | Out-Null
}
$folder=Join-Path $PSScriptRoot ('passive_colors_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $folder | Out-Null
$results=@()
try {
    foreach ($case in @(@('red',-65536),@('green',-16711936),@('blue',-16776961),@('black',-16777216),@('white',-1))) {
        Invoke-Adb -AdbArguments @('shell','am','start','-f','0x20000000','-n','local.nyako.cwbpattern/.MainActivity',
            '--ei','patch',([string]$case[1]),'--ez','control','false','--ei','animateMs','0') | Out-Null
        Start-Sleep -Seconds $WaitSeconds
        $afterPid=(Invoke-Adb -AdbArguments @('shell','pidof','system_server')).Trim()
        if ($afterPid -ne $servicePid) { throw 'system_server changed; abandon samples' }
        $gate=Invoke-Adb -AdbArguments @('shell','su','-c',"/data/local/tmp/cwb_gate_probe $servicePid")
        $status=Invoke-Adb -AdbArguments @('shell','su','-c',"/data/local/tmp/cwb_status_snapshot $servicePid")
        $raw=Invoke-Adb -AdbArguments @('shell','su','-c',"/data/local/tmp/cwb_state_snapshot $composerPid")
        $sf=@()
        if ($IncludeSF) {
            $sf=Invoke-Adb -AdbArguments @('shell','su','-c',('/data/local/tmp/sf_roi_probe '+($roi -join ' ')))
        }
        @($gate,$status,$raw,$sf) | Out-File -LiteralPath (Join-Path $folder ($case[0]+'.txt')) -Encoding utf8
        $selected=@($gate | Where-Object { $_ -match '^(CALLBACK_RGB|RAW_MODE|POLICY_INIT_HBM)' })
        $results+=@{stimulus=$case[0];snapshot=$selected;compensation=$status;hardware=$raw;finite_sf=$sf}
        Write-Output $case[0]
        $selected
        $status | Where-Object { $_ -match '^COMP_SNAPSHOT' }
        $raw | Where-Object { $_ -match '^(CWB_STATE|CWB_ROI|CWB_RGB_CACHE|CWB_PIXELS|ACTIVE_CONFIG)' }
        $sf | Where-Object { $_ -match '^(ROI_BUFFER|ROI_MEAN_DIAGNOSTIC|SF_ALGORITHM_IDENTITY|FINITE_RESULT)' }
    }
} finally {
    # The user was testing red when this finite experiment began.
    Invoke-Adb -AdbArguments @('shell','am','start','-f','0x20000000','-n','local.nyako.cwbpattern/.MainActivity',
        '--ei','patch','-65536','--ez','control','false','--ei','animateMs','0') | Out-Null
    ConvertTo-Json -InputObject $results -Depth 5 | Out-File -LiteralPath (Join-Path $folder 'results.json') -Encoding utf8
}
Write-Output "Saved: $folder; red restored. No lifecycle/SSC writes. IncludeSF=$IncludeSF (max five one-shot ROI captures, no persistent capture loop)."
