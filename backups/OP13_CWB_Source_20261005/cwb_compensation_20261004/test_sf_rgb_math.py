"""Compare reconstructed C++ against the real official ARM64 function offline."""
from pathlib import Path
import json
import random
import struct
import subprocess
from sf_rgb_oracle import OfficialSF, IDENTITY, ROOT, SOURCE

def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]

def case(name, pixels, width, height, matrix=None, linear=False, gains=(1.,1.,1.), thresholds=(2,216,32,38), debug=False):
    return dict(name=name, pixels=pixels, width=width, height=height,
                matrix=list(matrix or IDENTITY), linear=linear, gains=gains, thresholds=thresholds, debug=debug)

def run():
    oracle = OfficialSF()
    rng = random.Random(23821)
    cases = [case('gray-'+str(v), [(v,v,v,255)]*9, 3, 3) for v in range(256)]
    for name, pixel in [('red',(255,0,0,255)),('green',(0,255,0,255)),('blue',(0,0,255,255)),
                        ('transparent',(0,0,0,0)),('white',(255,255,255,255))]:
        cases.append(case(name, [pixel]*1596,38,42))
    for dark in (0,31,32,33,37,38,39):
        for light in (215,216,217,254,255):
            pixels=[(v,v,v,255) for v in [dark,light,dark,light]*36]
            cases.append(case(f'classification-{dark}-{light}',pixels,12,12))
    for i in range(100):
        width,height=rng.randrange(1,20),rng.randrange(1,20)
        pixels=[tuple(rng.randrange(256) for ch in range(4)) for j in range(width*height)]
        matrix=IDENTITY.copy()
        if i%4==1:
            for channel in range(3): matrix[channel*5]=f32(rng.uniform(0.05,0.95))
        elif i%4==2:
            for channel in range(3): matrix[channel*5]=-1.
            for channel in range(3): matrix[12+channel]=0.0
        elif i%4==3:
            matrix=[f32(rng.uniform(0.01,0.30)) if row<3 and column<3 else 0.0
                    for column in range(4) for row in range(4)]
            matrix[-1]=1.0
        gains=tuple(f32(rng.uniform(0.1,1.)) for channel in range(3))
        cases.append(case(f'matrix-{i}',pixels,width,height,matrix,linear=i%4 in (1,3),gains=gains,debug=i%7==0))
    # Do not sample unsampled pixels: native official loop advances x/y by 3.
    for i in range(8):
        pixels=[(rng.randrange(256),rng.randrange(256),rng.randrange(256),255) for j in range(49)]
        for y in range(0,7,3):
            for x in range(0,7,3): pixels[y*7+x]=(i*31,i*31,i*31,255)
        cases.append(case(f'stride3-{i}',pixels,7,7))
    payload=[]
    expected=[]
    for c in cases:
        result,matrix=oracle.calculate(c['pixels'],c['width'],c['height'],c['matrix'],c['linear'],c['gains'],c['thresholds'],c['debug'])
        expected.append((result,matrix))
        words=[c['width'],c['height'],int(c['linear']),*c['thresholds'],*c['gains'],*c['matrix']]
        words.extend(v for pixel in c['pixels'] for v in pixel)
        payload.append(' '.join(str(v) for v in words))
    native=subprocess.run(['wsl','--','/mnt/e/MIO/cwb_compensation_20261004/sf_rgb_math_probe'],
                          input='\n'.join(payload)+'\n',text=True,encoding='utf8',capture_output=True,check=True)
    actual=native.stdout.strip().splitlines()
    if len(actual)!=len(cases): raise AssertionError(('native count',len(actual),len(cases),native.stderr))
    errors=[]
    for c,line,(rgb,matrix) in zip(cases,actual,expected):
        fields=line.split()
        native_rgb=[int(v) for v in fields[1:5]]
        native_matrix=[float(v) for v in fields[5:]]
        if fields[0]!='1' or native_rgb!=rgb:
            errors.append(dict(case=c['name'],official=rgb,reconstructed=native_rgb))
        if any(struct.pack('<f',a)!=struct.pack('<f',b) for a,b in zip(matrix,native_matrix)):
            errors.append(dict(case=c['name'],matrix_official=matrix,matrix_reconstructed=native_matrix))
    report={'source':str(SOURCE),'cases':len(cases),'errors':errors,'pass':not errors,
            'coverage':['256 grayscale values','RGBA and alpha','3-pixel sampling stride',
                        'gamma LUT and nearest inverse lookup','purity thresholds',
                        'positive and negative matrices','linear correction branches and RGB gains',
                        'diagnostic logging on/off'],
            'not_covered':['SF listener and dirty-frame lifecycle','actual display color matrix acquisition',
                           'SSC capture/present fences and DC integration','power consumption']}
    (ROOT/'official_branch_audit/sf_rgb_math_test_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('coverage','not_covered','source')},ensure_ascii=False,indent=2))
    if errors: raise SystemExit(1)

if __name__=='__main__': run()
