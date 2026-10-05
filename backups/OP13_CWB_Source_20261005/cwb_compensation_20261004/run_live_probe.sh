#!/system/bin/sh
set -eu
cd /data/local/tmp/op13_compensator_test
chmod 0755 live_probe math_probe
LD_LIBRARY_PATH=/data/local/tmp/op13_compensator_test:/system/lib64:/system_ext/lib64:/vendor/lib64:/odm/lib64
export LD_LIBRARY_PATH
exec ./live_probe
