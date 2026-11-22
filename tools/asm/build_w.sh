#!/bin/sh
# Assemble weather.s and print the bytes for _W_CODE in vtoy/dllpatch.py (needs GNU as / objcopy, 32-bit).
set -e
cd "$(dirname "$0")"
as --32 -o /tmp/w.o weather.s
objcopy -O binary -j .text /tmp/w.o /tmp/w.bin
python3 -c "
b=open('/tmp/w.bin','rb').read(); n=int.from_bytes(b[0x7f0:0x7f4],'little'); h=b[:n].hex()
print('_W_CODE = bytes.fromhex(')
for i in range(0, len(h), 100): print('    \"' + h[i:i+100] + '\"')
print(')')"
