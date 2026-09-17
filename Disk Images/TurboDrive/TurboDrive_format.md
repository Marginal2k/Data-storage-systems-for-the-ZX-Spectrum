# TurboDrive / TurboDOS disk format (ZX Spectrum)

Interface "TurboDrive" (Racunari magazine, 1986; Jurhar/Miletic), **FDC WD1770**,
microdrive-compatible DOS in ROM. Reverse-engineered from 3 game images + 2 blank
disks, cross-checked against the published article. Verified: catalog, folder(FAT),
file reconstruction, headers, and .tap rebuild (checksums OK).

## Container & geometry
Extended CPC DSK (.dsk). 10 sectors x 512 B per track (sector IDs 1..10), 40 or 80
tracks, 1-2 sides. **Each side is an independent volume** (unit 1 = side 0, unit 2 =
side 1); ~195 KB usable per side. Track 0 of each side is reserved (catalog + folder).

## Catalog  (track 0, sector 1)
| bytes | meaning |
|-------|---------|
| 0     | 0x3F version mark |
| 1-10  | disk name |
| 11-505| 45 file slots x 11 B: byte0 = 0x3F empty / 0x00 used; bytes1-10 = name |
| 506-511 | unused |
File number is assigned **descending** by slot: bytes 11-21 = file #45 …
bytes 495-505 = file #1. Names starting with CHR$(0) are hidden from CAT.

## Folder = FAT  (track 0, sectors 2,3,…)
Per folder sector: byte0 = folder-sector number (from 2), byte1 = continuation
(0x3F more / 0x00 last), bytes 2-511 = 170 x 3-byte sector descriptors.
Descriptor for one data sector:
- b0: bits0-5 = owning file # (0x3F free, 0x00 permanently used/bad);
      bits6-7 = high bits of data length
- b1: sector ordinal within the file (0-255)
- b2: low bits of length; **length = 512 if (b0>>6)>=2 else ((b0>>6)<<8 | b2)**
      (len<512 => last sector of file; a full-and-last 512 sector uses bits6,7 = 11)

Descriptor index D (across folder sectors) maps to physical **side-sector 10 + D**
(i.e. data begins at track 1 sector 1). One folder sector covers 170 sectors = 17 tracks.

## File reconstruction
Gather all descriptors with a given file #, order by b1 (ordinal), concatenate each
sector's first `length` bytes. The first **9 bytes** of the file are a tape-style header:
`[0]type(0=BASIC,1/2=array,3=CODE) [1:3]blocklen [3:5]load-addr [5:7]prog-len [7:9]autostart`.
Payload = data[9 : 9+blocklen]. (tap: CODE -> param1=addr,param2=32768;
BASIC -> param1=line,param2=prog-len.)

## Sample disks
Pang/Rodland/Myth are single-side (unit 1) game disks: a `run` autoloader (BASIC,
LINE 10), a title BASIC, a `*$` SCREEN$ (6912 @16384), and CODE blocks. Side 2 unused.

## Write-back (not implemented here)
Feasible but FAT-style: allocate free descriptors (0x3F) for the needed sectors, write
the 9-byte header + data across them (set file#, ordinals, lengths), and add the name in
the first free catalog slot (remember the descending numbering). Left for a later pass.

## Write-back (implemented & verified)
`turbodrive.py` now writes too. Verified by rebuilding Pang from a blank template:
every file (and its 9-byte header) re-extracts byte-identical to the original.
- `add IMG payload -o OUT --name N --type code|basic|screen [--addr A --line L --plen P --unit U]`
  appends one file (input image untouched, new image written), with a readback self-check.
- `build TEMPLATE manifest.json -o OUT` assembles a whole release disk from a blank
  template. Manifest is a JSON list of file entries, or `{"disk":"NAME","unit":1,"files":[...]}`
  to also set the disk label. Entry: `{file,name,type,addr?,line?,plen?,unit?}`.
Allocator marks free folder descriptors (0x3F), lays the file across sectors (9-byte
header + payload), writes ordinals/lengths, and claims the first free catalog slot
(honouring the descending file-number rule). Blank templates: Format0-39 / Format0-79.
