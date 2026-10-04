"""Package the Windows generator and required third-party notices."""
import importlib.metadata as metadata
import json, platform, shutil, subprocess, sys, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


def main():
    from patcher import VERSION
    dest=ROOT/'dist'/('MIO_OriginOS_Patcher_'+VERSION+'_Windows')
    dest.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'dist/MIO_OriginOS_Patcher.exe',dest)
    shutil.copy2(ROOT/'README.txt',dest/'使用说明.txt')
    shutil.copy2(ROOT/'README.md',dest/'README.md')
    shutil.copy2(ROOT/'LICENSE',dest)
    shutil.copytree(ROOT/'licenses',dest/'licenses',dirs_exist_ok=True)
    for package in ('capstone','pyelftools','pyinstaller'):
        dist=metadata.distribution(package)
        for rel in dist.files or []:
            if any(word in rel.name.lower() for word in ('license','copying','notice')):
                source=Path(dist.locate_file(rel))
                if source.is_file():
                    target=dest/'licenses/dependencies'/package/str(rel).replace('../','')
                    target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    python=Path(sys.base_prefix)
    for source in [python/'LICENSE.txt',*list((python/'tcl').glob('*/license.terms'))]:
        if source.is_file():
            target=dest/'licenses/dependencies/python-tcl'/source.relative_to(python)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    commit=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    manifest={'version':VERSION,'commit':commit,'python':platform.python_version(),'platform':platform.platform(),
              'packages':{name:metadata.version(name) for name in ('pyinstaller','capstone','pyelftools')},
              'native_assets_built_from_source':True}
    (dest/'BUILD_INFO.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    archive=ROOT/'dist'/(dest.name+'.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=5,strict_timestamps=False) as z:
        for p in sorted(dest.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(dest.parent).as_posix())
    print('Windows 发布包：'+str(archive))


if __name__=='__main__':
    sys.path.insert(0,str(ROOT))
    main()
