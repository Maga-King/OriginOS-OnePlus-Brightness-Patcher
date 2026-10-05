"""Generate OP13-only audited numeric tables, never device calibration."""
import json
from pathlib import Path
import argparse

def generate(source, output):
    p = json.loads(source.read_text(encoding='utf-8-sig'))
    c = p['CommonConfig']
    if c['Project'] != '23821' or not c['SupportScreenshotAlgorithm_V2_1']:
        raise ValueError('This experimental implementation audits project 23821 only')
    if c.get('IRRatioFormulaType', 0) != 0:
        raise ValueError('Only the audited default IR formula is implemented')
    def array(name, shape, values, type_name='long double'):
        def fmt(v):
            if isinstance(v, list): return '{' + ','.join(fmt(i) for i in v) + '}'
            return str(v).strip() + ('L' if type_name == 'long double' else '')
        return 'static const ' + type_name + ' ' + name + shape + '=' + fmt(values) + ';\n'
    s = '#pragma once\n// Generated from official OnePlus 13 JSON. Device W_VIEW is read at runtime.\n'
    s += array('brightness_max', '[9]', [v['BrightnessMax'] for v in p['LinearityBrightnessRange']], 'int')
    s += array('linearity_type', '[4][9]', [[v['type'] for v in ch['Parameter']] for ch in p['LinearityCompensation']], 'int')
    for key, name, count in [('LinearityCompensation', 'linearity_parameters', 4),
                             ('LightLeakageCalculation', 'leak_parameters', 35),
                             ('LightLeakageRatio', 'colour_parameters', 20)]:
        s += array(name, f'[4][9][{count}]', [[[v.get(f'Parameter{i}', 0) for i in range(count)]
                    for v in ch['Parameter']] for ch in p[key]])
    s += array('golden', '[9][4]', [[v[ch+'Golden'] for ch in 'RGBC'] for v in p['LightLeakageGolden']])
    for prefix, dest in [('LuxCoeff', 'lux_coeff'), ('LuxCoeff', 'off_coeff')]:
        keys = ['LuxCoeffLIR_V2_1','LuxCoeffHIR_V2_1','LuxCoeffSuperHIR_V2_1'] if dest == 'lux_coeff' else ['LuxCoeffLirScreenOff','LuxCoeffHirScreenOff','LuxCoeffSuperHirScreenOff']
        n = len(p[keys[0]])
        s += array(dest, f'[3][{n}][4]', [[[v['Channel'+ch] for ch in 'RGBC'] for v in p[k]] for k in keys])
    s += array('count_coeff', '[3][1][4]', [[[v['Channel'+ch] for ch in 'RGBC'] for v in p[k]] for k in ['LuxCoeffLirChCountPolicy','LuxCoeffHirChCountPolicy','LuxCoeffSuperHirChCountPolicy']])
    s += array('ir_threshold', '[2]', [v['IR_Ratio_Max'] for v in p['IRThreshold_V2_1'][:2]])
    s += array('ir_brightness_max', '[3]', [v['BrightnessMax'] for v in p['IRBrightness_V2_1']], 'int')
    s += array('count_max', '[4]', [p['ChannelCountThreshold'][0][ch+'Max'] for ch in 'RGBC'], 'int')
    s += array('roi_values', '[4]', [c['ScreenShotRect'][key] for key in ['LeftTopX','LeftTopY','RightBottomX','RightBottomY']], 'int')
    s += f'static const int native_width={c["ScreenResolution"]["Width"]}, native_height={c["ScreenResolution"]["Height"]};\n'
    s += f'static const int cwb_period_ms={c["CWBScreenshotPeriod"]};\n'
    for key, name in [('CWBScreenshotCalDelay','cwb_delay'),('CWBScreenshotCalDelay90','cwb_delay90'),
                      ('CWBScreenshotCalDelay60','cwb_delay60'),('SamplePeriodFor60','sample_period60')]:
        s += f'static const int {name}={c[key]};\n'
    s += f'static const double match_threshold={c["CWBScreenshotMatchRatioThreshold"]};\n'
    if c.get('ScreenShotMatchParams'):
        raise ValueError('Extended timing tables need a separate ABI audit')
    output.write_text(s, encoding='utf-8')
    print(output)

if __name__ == '__main__':
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('profile', type=Path)
    a.add_argument('output', type=Path)
    ns = a.parse_args()
    generate(ns.profile, ns.output)
