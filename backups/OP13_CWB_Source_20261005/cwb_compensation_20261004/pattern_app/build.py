"""Build a self-contained static stimulus APK; no external dependencies."""
from pathlib import Path
import os,subprocess,zipfile
root=Path(__file__).parent.resolve()
sdk=Path(r'C:\Users\a1510\AppData\Local\Android\Sdk')
bt=sdk/'build-tools/35.0.0'
java=Path(r'E:\MIO\ace3\tools\temurin17\bin')
build=root/'build'; build.mkdir(exist_ok=True)
classes=build/'classes'; classes.mkdir(exist_ok=True)
android=sdk/'platforms/android-35/android.jar'
tool_environment=os.environ.copy()
tool_environment['JAVA_HOME']=str(java.parent)
tool_environment['PATH']=str(java)+os.pathsep+tool_environment.get('PATH','')
def run(args): subprocess.run([str(a) for a in args],check=True,env=tool_environment)
run([bt/'aapt2.exe','link','-o',build/'resources.apk','--manifest',root/'AndroidManifest.xml','-I',android])
run([java/'javac.exe','-encoding','UTF-8','-source','8','-target','8','-classpath',android,'-d',classes,root/'MainActivity.java'])
run([bt/'d8.bat','--min-api','31','--lib',android,'--output',build,*classes.rglob('*.class')])
with zipfile.ZipFile(build/'resources.apk') as src,zipfile.ZipFile(build/'unsigned.apk','w',zipfile.ZIP_DEFLATED) as dst:
    for info in src.infolist(): dst.writestr(info,src.read(info.filename))
    dst.write(build/'classes.dex','classes.dex')
run([bt/'zipalign.exe','-f','4',build/'unsigned.apk',build/'aligned.apk'])
keystore=Path(r'C:\Users\a1510\.android\debug.keystore')
if not keystore.is_file(): raise FileNotFoundError('Existing Android debug keystore required')
run([bt/'apksigner.bat','sign','--ks',keystore,'--ks-key-alias','androiddebugkey','--ks-pass','pass:android','--key-pass','pass:android','--out',root/'CWB_Static_Pattern.apk',build/'aligned.apk'])
print(root/'CWB_Static_Pattern.apk')
