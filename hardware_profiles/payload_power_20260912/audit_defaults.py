"""Read-only audit of original-project merge and preserved user/BSP sources."""
import hashlib
import json
import os
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

project = Path(r'E:\by2025\AD9361_test_board\AD9361_test2')
repo = project / 'AD9361_test2.sdk'
diag = Path(os.environ['TEMP']) / 'ad9361-diag-20260906'
backup = diag / 'stage18-before-defaults'
changed_rtl = {
    'openofdm_tx/src/openofdm_tx.v', 'openofdm_tx/src/dot11_tx.v',
    'openofdm_rx/src/openofdm_rx.v', 'openofdm_rx/src/dot11.v',
    'openofdm_rx/src/equalizer.v', 'openofdm_rx/src/ofdm_decoder.v',
    'openofdm_rx/src/demodulate.v', 'openofdm_tx/src/payload_power_tx.vh',
    'openofdm_rx/src/payload_power_rx.vh',
}
changed_ip = changed_rtl | {'openofdm_tx/component.xml', 'openofdm_rx/component.xml'}
changed_app = {'app/main.c', 'app/app_config.h', 'utils/COMMON.c', 'utils/rf_board_local.h.example'}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

count = 0
for old_root, new_root, allowed in (
    (backup / 'ip_repo', project / 'ip_repo', changed_ip),
    (backup / 'sdk/AD9361_test2/src', repo / 'AD9361_test2/src', changed_app),
    (backup / 'sdk/AD9361_test2_bsp', repo / 'AD9361_test2_bsp', set()),
):
    for old in old_root.rglob('*'):
        if not old.is_file():
            continue
        relative = old.relative_to(old_root)
        if relative.as_posix() not in allowed:
            assert digest(old) == digest(new_root / relative), str(relative)
            count += 1
print('STAGE18_UNRELATED_FILES_UNCHANGED', count)

bd = Path('AD9361_test2.srcs/sources_1/bd/System/System.bd')
before = json.loads((backup / bd).read_text(encoding='utf-8-sig'))
after = json.loads((project / bd).read_text(encoding='utf-8-sig'))
differences = []
def compare(a, b, path=''):
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(a.keys() | b.keys()):
            compare(a.get(key), b.get(key), path + '/' + key)
    elif a != b:
        differences.append({'path': path, 'before': a, 'after': b})
compare(before, after)
for difference in differences:
    assert difference['path'].startswith('/design/nets/') and difference['path'].endswith('/ports'), difference
    assert sorted(difference['before']) == sorted(difference['after']), difference
print('STAGE18_BD_PORT_ORDER_ONLY', json.dumps([d['path'] for d in differences]))

reports = diag / 'stage18-original-build'
new_hdf = reports / 'System_wrapper.hdf'
if new_hdf.exists():
    with zipfile.ZipFile(backup / 'sdk/System_wrapper_hw_platform_0/system.hdf') as old, zipfile.ZipFile(new_hdf) as new:
        for name in ('ps7_init.c', 'ps7_init.h', 'ps7_init_gpl.c', 'ps7_init_gpl.h', 'ps7_init.html', 'ps7_init.tcl'):
            assert old.read(name) == new.read(name), name
        def ranges(archive):
            root = ET.fromstring(archive.read('System.hwh'))
            return sorted(tuple(sorted(item.attrib.items())) for item in root.iter('MEMRANGE'))
        old_ranges, new_ranges = ranges(old), ranges(new)
        assert old_ranges and old_ranges == new_ranges, 'Hardware address map changed'
        bit_hash = hashlib.sha256(new.read('System_wrapper.bit')).hexdigest()
        assert bit_hash == digest(reports / 'System_wrapper.bit')
        assert bit_hash == digest(project / 'AD9361_test2.runs/impl_1/System_wrapper.bit')
        print('STAGE18_PS_AND_ADDRESS_MAP_UNCHANGED', len(old_ranges))
        print('STAGE18_EXPORTED_BIT_MATCH', bit_hash)
else:
    print('STAGE18_EXPORT_NOT_BUILT_YET')
print('STAGE18_AUDIT_COMPLETE')
