#!/bin/sh
# Assemble bombzones.s and print the bytes for _BZ_CODE in vtoy/dllpatch.py (needs GNU as / objcopy, 32-bit).
set -e
cd "$(dirname "$0")"
as --32 -o /tmp/bz.o bombzones.s
objcopy -O binary -j .text /tmp/bz.o /tmp/bz.bin
python3 -c "
b=open('/tmp/bz.bin','rb').read(); init=int.from_bytes(b[0x7f0:0x7f4],'little'); n=int.from_bytes(b[0x7f4:0x7f8],'little'); code=b[:n]
print('_BZ_INIT =', hex(init)); print('_BZ_SPLASH =', hex(int.from_bytes(b[0x7e0:0x7e4],'little'))); print('_BZ_SPRET =', hex(int.from_bytes(b[0x7e4:0x7e8],'little'))); print('_BZ_DTOR =', hex(int.from_bytes(b[0x7f8:0x7fc],'little'))); print('_BZ_CODE = bytes.fromhex(')
h=code.hex()
for i in range(0, len(h), 100): print('    \"' + h[i:i+100] + '\"')
print(')')
n2=int.from_bytes(b[0x7fc:0x800],'little'); h=b[0x1c00:n2].hex()
print('_BZ_CODE2 = bytes.fromhex(')
for i in range(0, len(h), 100): print('    \"' + h[i:i+100] + '\"')
print(')')"
