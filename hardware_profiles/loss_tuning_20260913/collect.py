"""Independent all-returned-packet verification; missing packets are not bit errors."""
import json
import os
from pathlib import Path
import sys

repo = Path(r'E:\by2025\AD9361_test_board\AD9361_test2\AD9361_test2.sdk')
sys.path.insert(0, str(repo / 'hardware_profiles/payload_power_20260912'))
from analyze_capture import analyze

diag = Path(os.environ['TEMP']) / 'ad9361-diag-20260906'
for specification in sys.argv[1:]:
    tag, mib = specification.split('=')
    size = int(mib) * 1048576
    result = analyze(diag / tag / 'received_wire.bin', size)
    events = [json.loads(line) for line in (diag / (tag + '-receiver.stdout')).read_text(encoding='utf-8-sig').splitlines() if line.startswith('{')]
    wire = next(e for e in events if e['event'] == 'WIRE_CHECK')
    source = next(e for e in events if e['event'] == 'SOURCE_CHECK')
    assert result['received_packets'] == wire['blocks'] and result['missing_count'] == wire['missing_count']
    assert result['bit_errors'] == wire['bit_errors'] and result['weak_payload_bit_errors'] == source['weak_payload_bit_errors']
    assert result['protected_payload_bit_errors'] == source['protected_payload_bit_errors']
    full = {'tag': tag, 'test_bytes': size, **result}
    (diag / tag / 'independent.summary.json').write_text(json.dumps(full, indent=2), encoding='utf-8')
    compact = {k: v for k, v in full.items() if k not in ('missing', 'bad_details')}
    print(json.dumps(compact))
