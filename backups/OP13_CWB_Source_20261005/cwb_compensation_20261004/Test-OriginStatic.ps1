param([string]$Prefix = 'origin_static_white', [int]$Color = -1, [bool]$Control = $false, [int]$AnimateMs = 0)
$ErrorActionPreference = 'Stop'
$adb = 'C:\adb-fastboot\adb.exe'
$serial = 'DEVICE_SERIAL'
function Adb([string[]]$Arguments) {
    & $adb -s $serial @Arguments
    if ($LASTEXITCODE -ne 0) { throw "adb failed: $Arguments" }
}
if ($Prefix -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Unsafe capture prefix' }
if ((Adb @('shell','getprop','ro.gsid.image_running')).Trim() -ne '1') {
    throw 'Active SSC capture testing is restricted to OriginOS DSU, never the official main system'
}
$servicePid = (Adb @('shell','dumpsys','--pid','vendor.oplus.hardware.cwb.ICwbService/default')).Trim()
if ($servicePid -notmatch '^\d+$') { throw 'No registered CWB service PID' }
$power = Adb @('shell','dumpsys','power')
if (-not ($power -match 'mWakefulness=Awake')) { throw 'Please keep the display awake for the finite test' }
Adb @('install','-r',(Join-Path $PSScriptRoot 'pattern_app\CWB_Static_Pattern.apk'))
Adb @('push',(Join-Path $PSScriptRoot 'cwb_state_probe'),'/data/local/tmp/op13_cwb_state')
Adb @('push',(Join-Path $PSScriptRoot 'live_probe'),'/data/local/tmp/op13_compensator_test/live_probe')
Adb @('shell','su','-c','chmod 755 /data/local/tmp/op13_cwb_state /data/local/tmp/op13_compensator_test/live_probe')
$statePath = Join-Path $PSScriptRoot ($Prefix+'_state.txt')
Adb @('shell','getprop','ro.build.display.id') | Out-File $statePath -Encoding utf8
Adb @('shell','dumpsys','power') | Select-String 'mWakefulness=|mWakefulnessChanging=' | Out-File $statePath -Append -Encoding utf8
Adb @('shell','su','-c',"/data/local/tmp/op13_cwb_state $servicePid") | Out-File $statePath -Append -Encoding utf8
Adb @('shell','dumpsys','SurfaceFlinger') | Out-File (Join-Path $PSScriptRoot ($Prefix+'_sf_before.txt')) -Encoding utf8
Adb @('shell','am','start','-n','local.nyako.cwbpattern/.MainActivity','--ei','patch',$Color.ToString(),'--ez','control',$Control.ToString().ToLowerInvariant(),'--ei','animateMs',$AnimateMs.ToString())
# This existing finite binary stops both its sensor subscription and CWB client,
# then checks that no CWB callbacks continue. It does not touch any DBV node.
$probeOutput = & $adb -s $serial shell su -c 'sh /data/local/tmp/op13_compensator_test/run_live_probe.sh'
$probeExit = $LASTEXITCODE
$probeOutput | Out-File (Join-Path $PSScriptRoot ($Prefix+'_probe.txt')) -Encoding utf8
Adb @('shell','su','-c',"/data/local/tmp/op13_cwb_state $servicePid") | Out-File $statePath -Append -Encoding utf8
Adb @('shell','dumpsys','power') | Select-String 'mWakefulness=|mWakefulnessChanging=' | Out-File $statePath -Append -Encoding utf8
Adb @('shell','dumpsys','SurfaceFlinger') | Out-File (Join-Path $PSScriptRoot ($Prefix+'_sf_after.txt')) -Encoding utf8
Get-Content -Encoding utf8 $statePath
$probeOutput | Select-String 'SUMMARY|CWB_CLIENT_SERVICES|MATCHED_SEQUENCE|STOP' | Select-Object -Last 12
if ($probeExit -ne 0) { Write-Warning "Probe returned $probeExit; keep the failed sample for diagnosis" }
