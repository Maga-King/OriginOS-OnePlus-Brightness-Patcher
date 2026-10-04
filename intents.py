"""Read HDR/Dolby render intent IDs from the selected hardware's QDCM profiles."""
from configs import json_read


def donor_intents(donor):
    found={}
    for path in donor.paths():
        if 'qdcm_calib_data_' not in path or not path.endswith('.json'):continue
        def walk(obj):
            if isinstance(obj,list):
                for item in obj:walk(item)
                return
            if not isinstance(obj,dict):return
            applicability=obj.get('Applicability',{});name=applicability.get('RenderIntentName','').lower()
            if applicability.get('ColorPrimaries')=='P3':
                key=('dv73' if 'dolby' in name and 'd73' in name else 'dv65' if 'dolby' in name and 'd65' in name else
                     'hdr' if 'hdr' in name and 'd73' in name and 'hbm' not in name else None)
                if key:found.setdefault(key,set()).add(applicability['RenderIntent'])
            for value in obj.values():walk(value)
        walk(json_read(donor.text(path)))
    if set(found)!={'hdr','dv65','dv73'} or any(len(values)!=1 for values in found.values()):
        raise ValueError('官方 QDCM 私有 HDR/杜比模式缺失或面板间不同，不能硬套一加13的编号')
    return {key:next(iter(values)) for key,values in found.items()}
