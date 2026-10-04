#!/bin/bash
set -eu
cd "$(dirname "$0")/.."
base=$(pwd)
mkdir -p assets/native
cd libsepol/src
make -B -j8 libsepol.a CC=x86_64-w64-mingw32-gcc AR=x86_64-w64-mingw32-ar RANLIB=x86_64-w64-mingw32-ranlib CFLAGS="-O2 -Werror=implicit-function-declaration -I$base/native/compat -include $base/native/compat/compat.h -D__USE_MINGW_ANSI_STDIO=1"
cd "$base"
x86_64-w64-mingw32-gcc -O2 -static -DANDROID -include native/compat/compat.h -Ilibsepol/include -Ilibsepol/cil/include -Inative/compat secilc/secilc.c native/compat.c libsepol/src/libsepol.a -lws2_32 -lwinpthread -o assets/native/secilc.exe
