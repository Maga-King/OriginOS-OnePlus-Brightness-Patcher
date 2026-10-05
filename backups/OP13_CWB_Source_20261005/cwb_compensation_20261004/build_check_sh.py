"""Package finite read-only probes as one portable Android root shell file."""
from pathlib import Path
import base64, textwrap
root=Path(__file__).resolve().parent
source=(root/'cwb_check.sh.in').read_text(encoding='utf8')
for token,binary in [('@@STATUS_BASE64@@','comp_status_probe'),('@@HARDWARE_BASE64@@','cwb_state_probe'),
                     ('@@GATE_BASE64@@','../analysis/hbm_fod_20261005/cwb_gate_probe')]:
    encoded=base64.b64encode((root/binary).read_bytes()).decode('ascii')
    source=source.replace(token,'\n'.join(textwrap.wrap(encoded,76)))
output=root/'deploy'/'CWB_check.sh'
output.parent.mkdir(exist_ok=True)
output.write_text(source,encoding='utf8',newline='\n')
print(f'{output} ({output.stat().st_size} bytes)')
