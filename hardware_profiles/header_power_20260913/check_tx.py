"""Independently check accepted samples, protected region, and fractional power."""
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

root=Path(sys.argv[1])
baseline=None
for level in range(6):
    path=root/f'tx_level{level}.csv'
    with path.open(newline='') as f:
        rows=[{k:int(v) for k,v in row.items()} for row in csv.DictReader(f)]
    if baseline is None: baseline=rows
    assert len(rows)==len(baseline) and len(rows)>27000
    assert next(n for n,r in enumerate(rows) if r['state']==7)==400
    energy=raw_energy=0
    for n,row in enumerate(rows):
        assert row['sample']==n
        active=n>=2960
        assert row['active']==active
        if row['state']==7:
            assert row['data_symbol']==(n-400)//80
            assert row['sample_in_symbol']==(n-400)%80
        for c in ('i','q'):
            raw=row['raw_'+c]
            assert raw==baseline[n][c]
            a=abs(raw)
            if active and level:
                a=(a*3+32)//64 if level==5 else (a+(1<<(level-1)))>>level
            expected=-a if raw<0 else a
            assert row[c]==expected,(level,n,c,row,expected)
        if active:
            energy+=row['i']**2+row['q']**2
            raw_energy+=row['raw_i']**2+row['raw_q']**2
    print(json.dumps(dict(level=level,samples=len(rows),weak_power_ratio=energy/raw_energy,
                         weak_scaling_db=10*math.log10(energy/raw_energy),
                         peak_component=max(abs(r[c]) for r in rows for c in ('i','q')),
                         sha256=hashlib.sha256(path.read_bytes()).hexdigest())))
print('STAGE20_TX_NUMERIC_CHECK_COMPLETE')
