#!/usr/bin/env python3
"""fdat_to_tar.py FDAT.BIN OUT.TAR : read the decrypted UDTRFIRM header and write the firmware tar.
Header layout from fwtool.py (fwtool/sony/fdat.py, FdatHeader)."""
import struct, sys

src, dst = sys.argv[1], sys.argv[2]
f = open(src, 'rb')
h = f.read(0x40)
assert h[:8] == b'UDTRFIRM', 'not a decrypted FDAT (run decrypt_fdat.py first)'
minor, major = h[0x20], h[0x21]
model, region = struct.unpack_from('<II', h, 0x24)
fw_off, fw_size = struct.unpack_from('<II', h, 0x30)
print('version %x.%02x  model 0x%08x  region 0x%08x' % (major, minor, model, region))
print('firmware tar at 0x%x, %d bytes' % (fw_off, fw_size))
f.seek(fw_off)
with open(dst, 'wb') as o:
    left = fw_size
    while left:
        b = f.read(min(left, 1 << 24))
        if not b:
            sys.exit('truncated input')
        o.write(b); left -= len(b)
print('wrote', dst)
