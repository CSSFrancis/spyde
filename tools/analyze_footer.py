"""Analyze the PyCrucible footer structure to understand payload layout."""
import struct, sys
from pathlib import Path

exe = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dist/SpyDE.exe")
data = exe.read_bytes()
size = len(data)
MAGIC = bytes([80, 89, 67, 82, 85, 67, 73])

print(f"File size : {size:,} bytes")

# Locate magic
pos = data.rfind(MAGIC)
print(f"Magic pos : {pos:,}  (last {size - pos} bytes from end)")
print(f"Bytes after magic: {size - pos - 7}")

# Dump 32 bytes before + magic
print(f"\nLast 32 raw bytes: {data[-32:].hex()}")
print(f"Footer area      : {data[pos-24:].hex()}")

# Try every plausible u64 in the 24 bytes before magic as a possible offset/size
print("\n--- Candidate u64 values ---")
for offset in range(0, 24, 8):
    raw = data[pos - 24 + offset : pos - 24 + offset + 8]
    val_le = struct.unpack('<Q', raw)[0]
    # Is it a plausible payload START offset?
    if 0 < val_le < size:
        sig = data[val_le:val_le+4]
        note = f"→ bytes@{val_le}: {sig.hex()} ({sig})"
    else:
        note = "(out of range)"
    # Is it a plausible payload SIZE (negative from end)?
    end_off = size - val_le
    if 0 < end_off < size:
        sig2 = data[end_off:end_off+4]
        note += f"  |  as size→start@{end_off}: {sig2.hex()} ({sig2})"
    print(f"  @footer[-{24-offset}:-{24-offset-8}]: LE={val_le} ({hex(val_le)})  {note}")

# Scan for ALL zip local-file-header signatures in the file
ZIP_SIG = b'PK\x03\x04'
zip_positions = []
p = 0
while True:
    p = data.find(ZIP_SIG, p)
    if p == -1:
        break
    zip_positions.append(p)
    p += 4

print(f"\nZip 'PK\\x03\\x04' signatures found: {len(zip_positions)}")
if zip_positions:
    print(f"  First: {zip_positions[0]:,}")
    print(f"  Last : {zip_positions[-1]:,}")
    # The last one is likely the start of the outer payload zip
    last = zip_positions[-1]
    print(f"\nBytes immediately before last PK sig ({last-8}..{last}):")
    print(f"  {data[last-8:last].hex()}")

