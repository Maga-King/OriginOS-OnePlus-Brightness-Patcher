param([int]$WaitSeconds=3)
# Finite WINDOW-only brightness stimuli. Does not change system settings,
# sysfs, subscriptions, screen resolution, SSC timing, or kernel modes.
$ErrorActionPreference='Stop'
if ($WaitSeconds -lt 2 -or $WaitSeconds -gt 5) { throw 'WaitSeconds must be 2..5' }
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
if (-not ((Invoke-Adb -AdbArguments @('shell','dumpsys','power')) -match 'mWakefulness=Awake')) { throw 'Display must already be awake' }
if (-not ((Invoke-Adb -AdbArguments @('shell','dumpsys','activity','activities')) -match 'topResumedActivity=.*local.nyako.cwbpattern')) { throw 'Pattern app must already be foreground' }
$servicePid=(Invoke-Adb -AdbArguments @('shell','pidof','system_server')).Trim()
$composerPid=(Invoke-Adb -AdbArguments @('shell','pidof','vendor.qti.hardware.display.composer-service')).Trim()
if ($servicePid -notmatch '^\d+$' -or $composerPid -notmatch '^\d+$') { throw 'Invalid service PIDs' }
$folder=Join-Path $PSScriptRoot ('passive_brightness_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $folder | Out-Null
$settingsBefore=@('screen_brightness','screen_brightness_float','screen_brightness_mode') | ForEach-Object {
    $_+'='+(Invoke-Adb -AdbArguments @('shell','settings','get','system',$_))
}
$settingsBefore | Out-File -LiteralPath (Join-Path $folder 'settings_before.txt') -Encoding utf8
try {
    foreach ($percent in @(30,5,1,30)) {
        Invoke-Adb -AdbArguments @('shell','am','start','-f','0x20000000','-n','local.nyako.cwbpattern/.MainActivity',
            '--ei','patch','-65536','--ez','control','false','--ei','animateMs','0',
            '--ei','testBrightnessPercent',([string]$percent)) | Out-Null
        Start-Sleep -Seconds $WaitSeconds
        if ((Invoke-Adb -AdbArguments @('shell','pidof','system_server')).Trim() -ne $servicePid) { throw 'system_server changed' }
        $gate=Invoke-Adb -AdbArguments @('shell','su','-c',"/data/local/tmp/cwb_gate_probe $servicePid")
        $status=Invoke-Adb -AdbArguments @('shell','su','-c',"/data/local/tmp/cwb_status_snapshot $servicePid")
        $raw=Invoke-Adb -AdbArguments @('shell','su','-c',"/data/local/tmp/cwb_state_snapshot $composerPid")
        @($gate,$status,$raw) | Out-File -LiteralPath (Join-Path $folder ($percent.ToString()+'_'+(Get-Date -Format 'HHmmss')+'.txt')) -Encoding utf8
        Write-Output "WINDOW_BRIGHTNESS_PERCENT=$percent"
        $gate | Where-Object { $_ -match '^(CALLBACK_RGB|RAW_MODE)' }
        $status | Where-Object { $_ -match '^COMP_SNAPSHOT' }
        $raw | Where-Object { $_ -match '^(CWB_RGB_CACHE|CWB_STATE|CWB_PIXELS)' }
    }
} finally {
    # Missing test extra resets only this Activity's override; global brightness
    # and automatic-brightness state remain untouched by this script.
    Invoke-Adb -AdbArguments @('shell','am','start','-f','0x20000000','-n','local.nyako.cwbpattern/.MainActivity',
        '--ei','patch','-65536','--ez','control','false','--ei','animateMs','0') | Out-Null
    $settingsAfter=@('screen_brightness','screen_brightness_float','screen_brightness_mode') | ForEach-Object {
        $_+'='+(Invoke-Adb -AdbArguments @('shell','settings','get','system',$_))
    }
    $settingsAfter | Out-File -LiteralPath (Join-Path $folder 'settings_after.txt') -Encoding utf8
    Write-Output 'Red restored; Activity brightness follows system again.'
}
Write-Output "Saved: $folder; no system setting/sysfs/SSC writes."
