from PyInstaller.utils.hooks import collect_all
datas=[('assets','assets')];binaries=[];hiddenimports=[]
d,b,h=collect_all('capstone');datas+=d;binaries+=b;hiddenimports+=h
a=Analysis(['app.py'],pathex=[],binaries=binaries,datas=datas,hiddenimports=hiddenimports,
           hookspath=[],hooksconfig={},runtime_hooks=[],excludes=['unicorn'],noarchive=False,optimize=0)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='MIO_OriginOS_Patcher',debug=False,
        bootloader_ignore_signals=False,strip=False,upx=False,console=False,
        disable_windowed_traceback=False,argv_emulation=False,target_arch=None,
        codesign_identity=None,entitlements_file=None)
