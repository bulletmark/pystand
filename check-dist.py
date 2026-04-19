#!/usr/bin/python
import re
import subprocess
import sys

import pystand

cmd = 'pystand show -a'.split()
out = subprocess.run(cmd, capture_output=True, text=True).stdout
alldists = set(re.sub(r'.+"(.+)".*', r'\1', ln) for ln in out.splitlines())

error = 0
for mach, dist in pystand.DISTRIBUTIONS.items():
    if dist not in alldists:
        machstr = f'{mach[0]}-{mach[1]}'
        print(f'{machstr} invalid distribution: "{dist}"', file=sys.stderr)
        error = 1

sys.exit(error)
