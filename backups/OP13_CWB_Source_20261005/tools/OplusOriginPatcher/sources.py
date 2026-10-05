"""Read-only ROM sources: MIO directories, collector ZIP and Android TAR.GZ."""
from pathlib import Path, PurePosixPath
import tarfile
import tempfile
import zipfile

PARTITIONS = {'system', 'system_ext', 'product', 'vendor', 'odm', 'my_product',
              'vendor_dlkm', 'odm_dlkm', 'system_dlkm'}

def canonical(name):
    p = PurePosixPath(name.replace('\\', '/'))
    if p.is_absolute() or '..' in p.parts or any(':' in v for v in p.parts):
        raise ValueError(f'Unsafe archive member: {name}')
    parts = list(p.parts)
    if not parts: return None
    if parts[0] == 'files': parts.pop(0)
    if len(parts) >= 2 and parts[:2] == ['system', 'system']: parts.pop(0)
    if not parts: return None
    if parts[0] not in PARTITIONS and not parts[0].startswith('my_') and parts[0] not in ('runtime', 'metadata'):
        return None
    return '/'.join(parts)

class RomSource:
    def __init__(self, path):
        self.path = Path(str(path).strip().strip('"')).resolve()
        self.index = {}
        self.zip = None
        self.temp = None
        if self.path.is_dir():
            children = list(self.path.iterdir())
            if not any(p.is_dir() and (p.name in PARTITIONS or p.name == 'files') for p in children):
                archives = [p for p in children if p.is_file() and (p.suffix.lower() == '.zip' or p.name.endswith(('.tar.gz', '.tgz')))]
                if len(archives) == 1: self.path = archives[0]
        if self.path.is_dir():
            for p in self.path.rglob('*'):
                if p.is_file() and not p.is_symlink(): self._add(p.relative_to(self.path).as_posix(), p)
        elif zipfile.is_zipfile(self.path):
            self.zip = zipfile.ZipFile(self.path)
            for info in self.zip.infolist():
                if not info.is_dir(): self._add(info.filename, info.filename)
        elif tarfile.is_tarfile(self.path):
            self.temp = tempfile.TemporaryDirectory(prefix='oplus_display_input_')
            root = Path(self.temp.name)
            # Single streaming pass avoids repeatedly decompressing a large capture.
            with tarfile.open(self.path, 'r|*') as archive:
                for member in archive:
                    if not member.isfile(): continue
                    key = canonical(member.name)
                    if key is None: continue
                    # UI application APKs are not patched by this generator.
                    if key.endswith('.apk') and '/framework/' not in key and '/overlay/' not in key: continue
                    target = root / key
                    if key in self.index: raise ValueError(f'Duplicate source path: {key}')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    stream = archive.extractfile(member)
                    with target.open('wb') as out:
                        while chunk := stream.read(1024*1024): out.write(chunk)
                    self.index[key] = target
        else: raise ValueError(f'Unsupported or missing source: {self.path}')

    def _add(self, name, value):
        key = canonical(name)
        if key is None: return
        if key in self.index: raise ValueError(f'Ambiguous source path: {key}')
        self.index[key] = value

    def read(self, key):
        entry = self.index[key.lstrip('/')]
        return self.zip.read(entry) if self.zip else entry.read_bytes()

    def text(self, key): return self.read(key).decode('utf-8-sig', errors='replace')
    def has(self, key): return key.lstrip('/') in self.index
    def paths(self, prefix=''): return sorted(k for k in self.index if k.startswith(prefix))
    def close(self):
        if self.zip: self.zip.close()
        if self.temp: self.temp.cleanup()
    def __enter__(self): return self
    def __exit__(self, *_): self.close()
