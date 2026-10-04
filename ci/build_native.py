"""Build both ARM64 helper objects and the Windows SELinux compiler from source."""
import os, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


def main():
    for name in ('domain','color','lux','unified'):
        subprocess.run(['clang','--target=aarch64-linux-gnu','-c',str(ROOT/'assets'/(name+'.S')),
                        '-o',str(ROOT/'assets'/(name+'.o'))],check=True)
    subprocess.run(['bash',str(ROOT/'compiler_source/native/build.sh')],check=True)
    destination=ROOT/'assets/native';destination.mkdir(parents=True,exist_ok=True)
    import shutil
    shutil.copy2(ROOT/'compiler_source/assets/native/secilc.exe',destination/'secilc.exe')
    print('四份 ARM64 辅助对象与 Windows secilc 已从源码构建。')


if __name__=='__main__':main()
