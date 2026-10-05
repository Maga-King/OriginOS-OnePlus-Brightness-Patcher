param([string]$Prefix = 'coloros_spatial')
$ErrorActionPreference = 'Stop'
$adb = 'C:\adb-fastboot\adb.exe'
$serial = 'DEVICE_SERIAL'
function Adb([string[]]$Arguments) {
    & $adb -s $serial @Arguments
    if ($LASTEXITCODE -ne 0) { throw "adb failed: $Arguments" }
}
if ((Adb @('shell','getprop','ro.gsid.image_running')).Trim() -ne '0') {
    throw 'This test uses the existing official Fusion client: main ColorOS only'
}
$phases = @(
    @{ Name='roi_red'; Color='-65536'; Control='false' },
    @{ Name='roi_green'; Color='-16711936'; Control='false' },
    @{ Name='roi_blue'; Color='-16776961'; Control='false' },
    @{ Name='roi_black'; Color='-16777216'; Control='false' },
    @{ Name='offroi_red'; Color='-65536'; Control='true' },
    @{ Name='white'; Color='-1'; Control='false' }
)
try {
    foreach ($phase in $phases) {
        Adb @('shell','am','start','-n','local.nyako.cwbpattern/.MainActivity',
            '--ei','patch',$phase.Color,'--ez','control',$phase.Control) | Out-Null
        & (Join-Path $PSScriptRoot 'Capture-OfficialBaseline.ps1') -Prefix ($Prefix+'_'+$phase.Name)
    }
} finally {
    & $adb -s $serial shell su -c 'dumpsys sensorservice fusionlight_debug false' | Out-Null
    & $adb -s $serial shell am start -n local.nyako.cwbpattern/.MainActivity --ei patch -1 --ez control false | Out-Null
}
