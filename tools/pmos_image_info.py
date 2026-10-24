"""Read exported 4096-sector GPT/ext4 identifiers without mounts or privileges."""
from pathlib import Path
import json
import struct
import uuid

def inspect_image(image: Path) -> dict:
    sector = 4096
    result = {'image': str(image.resolve()), 'bytes': image.stat().st_size, 'sector_size': sector, 'partitions': []}
    with image.open('rb') as stream:
        stream.seek(sector)
        header = stream.read(sector)
        assert header[:8] == b'EFI PART', 'Expected 4096-sector GPT'
        table, count, entry_size = struct.unpack_from('<QII', header, 72)
        assert 0 < count <= 1024 and 128 <= entry_size <= 4096
        for index in range(count):
            stream.seek(table * sector + index * entry_size)
            entry = stream.read(entry_size)
            if not any(entry[:16]):
                continue
            first, last = struct.unpack_from('<QQ', entry, 32)
            assert first <= last and (last + 1) * sector <= result['bytes']
            stream.seek(first * sector + 1024)
            sb = stream.read(1024)
            assert sb[56:58] == b'\x53\xef', 'Expected ext4 partition'
            result['partitions'].append({'index': index + 1, 'start': first, 'sectors': last-first+1,
                'uuid': str(uuid.UUID(bytes=sb[104:120])),
                'label': sb[120:136].split(b'\0')[0].decode()})
    result['root_uuid'] = next(p['uuid'] for p in result['partitions'] if p['label'] == 'pmOS_root')
    return result

if __name__ == '__main__':
    import sys
    record = inspect_image(Path(sys.argv[1]))
    print(record['root_uuid'] if '--root-uuid' in sys.argv else json.dumps(record, indent=2))
