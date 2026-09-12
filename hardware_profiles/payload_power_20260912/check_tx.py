"""Check generated TX samples and export reproducible RX simulation stimuli."""
import csv
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
baseline = None
for level in range(5):
    with (root / f'tx_level{level}.csv').open(newline='') as f:
        rows = [{k: int(v) for k, v in row.items()} for row in csv.DictReader(f)]
    if baseline is None:
        baseline = rows
    assert len(rows) == len(baseline) and len(rows) > 2900
    data_start = next(n for n, row in enumerate(rows) if row['state'] == 7)
    assert data_start == 400, data_start
    assert sum(row['state'] == 1 for row in rows) == 160
    assert sum(row['state'] == 2 for row in rows) == 160
    assert sum(row['state'] == 3 for row in rows) == 80
    energy = raw_energy = 0
    samples = []
    for n, row in enumerate(rows):
        assert row['sample'] == n
        assert (row['raw_i'], row['raw_q']) == (baseline[n]['i'], baseline[n]['q'])
        active = n >= 400 + 32 * 80
        assert row['active'] == active, (level, n, row)
        if row['state'] == 7:
            assert row['data_symbol'] == (n - 400) // 80
            assert row['sample_in_symbol'] == (n - 400) % 80
        for component in ('i', 'q'):
            raw = row['raw_' + component]
            shift = level if active else 0
            expected = ((abs(raw) + (1 << (shift - 1))) >> shift) if shift else abs(raw)
            expected = -expected if raw < 0 else expected
            assert row[component] == expected, (level, n, component, row, expected)
        if active:
            energy += row['i'] ** 2 + row['q'] ** 2
            raw_energy += row['raw_i'] ** 2 + row['raw_q'] ** 2
        samples.append(f"{row['i'] & 0xffff:04x}{row['q'] & 0xffff:04x}\n")
    (root / f'wave{level}.mem').write_text(''.join(samples), encoding='ascii')
    print(json.dumps({'level': level, 'samples': len(rows), 'first_weak_sample': 2960,
                      'power_ratio': energy / raw_energy,
                      'peak_component': max(abs(r[c]) for r in rows for c in ('i', 'q'))}))
print('STAGE17_TX_NUMERIC_CHECK_COMPLETE')
