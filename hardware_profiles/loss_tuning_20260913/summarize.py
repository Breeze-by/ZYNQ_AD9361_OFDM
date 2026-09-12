"""Compact view of raw test output; does not change source/captured data."""
import json
from pathlib import Path
import sys

for line in Path(sys.argv[1]).read_text(encoding='utf-8-sig').splitlines():
    try:
        item = json.loads(line)
    except ValueError:
        continue
    event = item.get('event')
    if event in ('registered', 'SOURCE_CHECK'):
        print(json.dumps(item))
    elif event == 'WIRE_CHECK':
        print(json.dumps({k: v for k, v in item.items() if k != 'bad'}))
    elif event == 'RESULT' and item.get('role') == 'sender':
        print(json.dumps({'event': 'SENDER_RESULT', **{k: item['stats'][k] for k in ('total_size', 'bytes_acked', 'packets_sent', 'retries_used', 'average_rate_kib_s')}}))
    elif event == 'SERIAL_LOG':
        print('SERIAL_ERRORS', item['errors'])
        lines = [s for s in item['text'].splitlines() if 'S2MM RX stat' in s or 'STAT state' in s or 'error' in s.lower() or 'stall' in s.lower()]
        print('\n'.join(lines[-3:]))
