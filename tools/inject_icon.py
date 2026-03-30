"""
inject_icon.py  –  Inject a Windows .ico into a PyCrucible exe without
corrupting the appended zip payload.

Strategy:
  1. Find the zip payload in the exe by locating its End-of-Central-Directory
     (EOCD) record just before the PyCrucible magic bytes.
  2. Extract: runner_bytes (before zip), zip_bytes, footer_bytes (magic + any
     preceding u64 offsets).
  3. Write runner to a temp file; run rcedit on it.
  4. Update any absolute offsets stored in the footer to account for the
     runner's new size.
  5. Concatenate: new_runner + zip_bytes + updated_footer.

Usage:
    python tools/inject_icon.py dist/SpyDE.exe spyde/Spyde.ico
"""

import struct, subprocess, shutil, sys, tempfile, os
from pathlib import Path

MAGIC    = bytes([80, 89, 67, 82, 85, 67, 73])   # b'PYCRUCL' (PyCrucible)
ZIP_EOCD = b'PK\x05\x06'                          # zip end-of-central-directory
RCEDIT   = Path("tools/rcedit.exe")


def locate_zip_start(data: bytes, magic_pos: int) -> int:
    """
    The zip payload's EOCD sits somewhere before the magic bytes.
    The EOCD at offset E tells us the zip starts at:
        zip_start = E - eocd_cd_offset - eocd_cd_size
    We scan backward from magic_pos for the last EOCD.
    """
    search_area = data[:magic_pos]

    # Find all EOCD records; we want the last one
    pos = 0
    eocd_pos = -1
    while True:
        p = search_area.find(ZIP_EOCD, pos)
        if p == -1:
            break
        eocd_pos = p
        pos = p + 4

    if eocd_pos == -1:
        raise RuntimeError("No zip EOCD found before magic bytes")

    # Standard EOCD layout (22 bytes minimum):
    #   4  signature
    #   2  disk number
    #   2  disk with cd start
    #   2  entries on this disk
    #   2  total entries
    #   4  cd size
    #   4  cd offset (relative to zip start)  ← we need this
    #   2  comment length
    cd_offset_field = struct.unpack_from('<I', data, eocd_pos + 16)[0]
    cd_size_field   = struct.unpack_from('<I', data, eocd_pos + 12)[0]

    # zip_start = eocd_pos - cd_size - cd_offset_field
    # (because offset is relative to start of zip)
    zip_start = eocd_pos - cd_size_field - cd_offset_field

    # Sanity: should see "PK\x03\x04" there
    if data[zip_start:zip_start+4] != b'PK\x03\x04':
        # Fallback: try offset alone
        alt = eocd_pos - cd_offset_field
        if data[alt:alt+4] == b'PK\x03\x04':
            zip_start = alt
        else:
            raise RuntimeError(
                f"Could not verify zip start: {data[zip_start:zip_start+4].hex()} "
                f"at {zip_start} (eocd={eocd_pos}, cd_off={cd_offset_field}, cd_sz={cd_size_field})"
            )

    print(f"  EOCD          : offset {eocd_pos:,}")
    print(f"  CD offset     : {cd_offset_field:,}   CD size: {cd_size_field:,}")
    print(f"  Zip start     : {zip_start:,}")
    return zip_start


def update_footer_offsets(footer: bytes, old_runner_size: int, new_runner_size: int) -> bytes:
    """
    Scan every 8-byte word in the footer (before the magic) for values that
    equal old_runner_size (absolute offsets into the original file) and
    replace them with new_runner_size.
    """
    magic_offset = footer.rfind(MAGIC)
    if magic_offset == -1:
        raise RuntimeError("Magic not in footer slice")

    pre_magic = bytearray(footer[:magic_offset])
    updated = False
    for i in range(0, len(pre_magic) - 7, 8):
        val = struct.unpack_from('<Q', pre_magic, i)[0]
        if val == old_runner_size:
            struct.pack_into('<Q', pre_magic, i, new_runner_size)
            print(f"  Footer offset updated at byte {i}: {old_runner_size:,} → {new_runner_size:,}")
            updated = True
    if not updated:
        print("  No footer offsets needed updating (none matched old runner size).")
    return bytes(pre_magic) + footer[magic_offset:]


def main():
    if len(sys.argv) < 3:
        sys.exit(f"Usage: {sys.argv[0]} <SpyDE.exe> <icon.ico>")

    exe  = Path(sys.argv[1])
    ico  = Path(sys.argv[2])

    if not exe.exists():  sys.exit(f"Exe not found: {exe}")
    if not ico.exists():  sys.exit(f"Icon not found: {ico}")
    if not RCEDIT.exists(): sys.exit(f"rcedit not found at {RCEDIT}")

    data     = exe.read_bytes()
    filesize = len(data)
    print(f"\nReading {exe}  ({filesize:,} bytes)")

    # Locate magic (always at the very end of the file)
    magic_pos = data.rfind(MAGIC)
    if magic_pos == -1 or magic_pos != filesize - len(MAGIC):
        sys.exit("PyCrucible magic bytes not found at expected position")
    print(f"Magic at        : {magic_pos:,}  (last {filesize - magic_pos} bytes)")

    # Locate zip start
    zip_start = locate_zip_start(data, magic_pos)
    zip_end   = magic_pos          # zip bytes run up to (but not including) magic
    zip_bytes = data[zip_start : zip_end]

    # Footer = magic + the N bytes just before zip_start that aren't the zip
    # (PyCrucible may store u64 offsets between the zip and the magic; in
    # practice zip_end == magic_pos so footer = magic only)
    runner_bytes = data[:zip_start]
    footer_bytes = data[zip_end:]          # just the 7 magic bytes

    old_runner_size = len(runner_bytes)
    print(f"  Runner size   : {old_runner_size:,}")
    print(f"  Zip size      : {len(zip_bytes):,}")
    print(f"  Footer size   : {len(footer_bytes)}")
    print(f"  Total         : {old_runner_size + len(zip_bytes) + len(footer_bytes):,}  (expected {filesize:,})")

    # Write stripped runner to a temp file
    tmp = tempfile.NamedTemporaryFile(suffix='.exe', delete=False)
    tmp.write(runner_bytes)
    tmp.close()
    print(f"\nStripped runner written to: {tmp.name}")

    # Apply rcedit
    print(f"Running rcedit  : {RCEDIT} ... --set-icon {ico}")
    result = subprocess.run(
        [str(RCEDIT), tmp.name, "--set-icon", str(ico)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        os.unlink(tmp.name)
        sys.exit(f"rcedit failed:\n{result.stdout}\n{result.stderr}")
    print("  rcedit OK")

    new_runner = Path(tmp.name).read_bytes()
    os.unlink(tmp.name)
    new_runner_size = len(new_runner)
    delta = new_runner_size - old_runner_size
    print(f"  New runner size: {new_runner_size:,}  (Δ {delta:+,})")

    # Update any absolute offsets in the footer
    updated_footer = update_footer_offsets(footer_bytes, old_runner_size, new_runner_size)

    # Assemble final file
    backup = exe.with_suffix('.exe.bak')
    shutil.copy2(exe, backup)
    print(f"\nBackup: {backup}")

    final = new_runner + zip_bytes + updated_footer
    exe.write_bytes(final)
    print(f"Written {exe}  ({len(final):,} bytes)")
    print("\n✓ Icon injected successfully.")


if __name__ == "__main__":
    main()

