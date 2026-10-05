param([string]$Prefix = 'coloros_screenon')
$ErrorActionPreference = 'Stop'
if ($Prefix -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Unsafe capture prefix' }
$adb = 'C:\adb-fastboot\adb.exe'
$captureRoot = $PSScriptRoot
if ((& $adb shell getprop ro.gsid.image_running).Trim() -ne '0') { throw 'Official baseline requires the main ColorOS system' }
$servicePid = (& $adb shell dumpsys --pid vendor.oplus.hardware.cwb.ICwbService/default).Trim()
if ($servicePid -notmatch '^\d+$') { throw 'Cannot locate the registered CWB service process' }
& $adb push "$captureRoot\cwb_state_probe" /data/local/tmp/op13_cwb_state
if ($LASTEXITCODE -ne 0) { throw 'State probe push failed' }
& $adb shell su -c 'chmod 755 /data/local/tmp/op13_cwb_state'
$statePath = Join-Path $captureRoot ($Prefix + '_state.txt')
$verbosePath = Join-Path $captureRoot ($Prefix + '_verbose.txt')
& $adb shell getprop ro.build.display.id | Out-File $statePath -Encoding utf8
& $adb shell dumpsys power | Select-String -Pattern 'mWakefulness=|mWakefulnessChanging=' | Out-File $statePath -Append -Encoding utf8
& $adb shell su -c "/data/local/tmp/op13_cwb_state $servicePid" | Out-File $statePath -Append -Encoding utf8
try {
    & $adb shell su -c 'dumpsys sensorservice fusionlight_debug true' | Out-Null
    & $adb shell su -c 'timeout 6 logcat -T 1 -s FusionLightNextGen' | Out-File $verbosePath -Encoding utf8
} finally {
    & $adb shell su -c 'dumpsys sensorservice fusionlight_debug false' | Out-Null
}
& $adb shell su -c "/data/local/tmp/op13_cwb_state $servicePid" | Out-File $statePath -Append -Encoding utf8
& $adb shell dumpsys power | Select-String -Pattern 'mWakefulness=|mWakefulnessChanging=' | Out-File $statePath -Append -Encoding utf8
& $adb shell getprop persist.sys.oplus.sensor.debug.level | Out-File $statePath -Append -Encoding utf8
Get-Content $statePath
