"""Explicit small-model download step; never imported by the running app."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / '.tools/models'


def download(url, path, expected=None, limit=700_000_000):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and (expected is None or path.stat().st_size == expected):
        return
    pending = path.with_suffix(path.suffix + '.partial')
    try:
        with urllib.request.urlopen(url, timeout=60) as response, pending.open('wb') as output:
            count = 0
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > limit:
                    raise RuntimeError('Download exceeds the small-model size limit. Review it explicitly.')
                output.write(chunk)
        if expected is not None and count != expected:
            raise RuntimeError('Download size mismatch')
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def setup(kind):
    if kind in ('stt', 'all'):
        print('Whisper Tiny multilingual: 39M parameters; 78.2 MB; CPU INT8; estimated RAM 0.3–0.8 GB.', flush=True)
        for name, size in [('config.json', 2249), ('model.bin', 75538270),
                           ('tokenizer.json', 2203239), ('vocabulary.txt', 459861)]:
            download('https://huggingface.co/Systran/faster-whisper-tiny/resolve/d90ca5fe260221311c53c58e660288d3deb8d356/' + name,
                     MODELS / 'faster-whisper-tiny' / name, size)
    if kind in ('llm', 'all'):
        print('Qwen3-0.6B: 0.6B parameters; Q8_0; 639,446,688 bytes; estimated RAM 1–2 GB.', flush=True)
        download('https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q8_0.gguf',
                 MODELS / 'Qwen3-0.6B-Q8_0.gguf', 639446688)
        runtime = ROOT / '.tools/llama-cpp'
        if not (runtime / 'llama-server.exe').exists():
            tag = 'b11146'  # Runtime actually validated with this application.
            with urllib.request.urlopen('https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/' + tag) as response:
                release = json.load(response)
            asset = next(a for a in release['assets'] if a['name'].endswith('bin-win-cpu-x64.zip'))
            print('Official llama.cpp CPU runtime:', tag, asset['size'], 'bytes', flush=True)
            archive = ROOT / '.tools/llama-cpu.zip'
            download(asset['browser_download_url'], archive, asset['size'], 100_000_000)
            runtime.mkdir(exist_ok=True)
            with zipfile.ZipFile(archive) as bundle:
                for entry in bundle.infolist():
                    if entry.is_dir():
                        continue
                    name = Path(entry.filename).name
                    with bundle.open(entry) as source, (runtime / name).open('wb') as target:
                        shutil.copyfileobj(source, target)
            (runtime / 'release.json').write_text(json.dumps({'tag': tag, 'url': asset['browser_download_url']}))
    manifest = []
    for path in MODELS.rglob('*'):
        if path.is_file() and '.cache' not in path.parts and path.name != 'manifest.json':
            with path.open('rb') as file:
                digest = hashlib.file_digest(file, 'sha256').hexdigest()
            manifest.append({'path': str(path.relative_to(ROOT)), 'bytes': path.stat().st_size, 'sha256': digest})
    (MODELS / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print('Local setup complete.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--component', choices=['stt', 'llm', 'all'], default='all')
    setup(parser.parse_args().component)
