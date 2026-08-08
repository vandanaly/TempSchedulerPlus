from pathlib import Path
import gzip
import shutil

import config

try:
    import zstandard as zstd
except ImportError:
    zstd = None


def compress_file(source_path, destination_path=None):
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"Compression skipped. File not found: {source.name}")

    if destination_path is None:
        destination = config.COMPRESSED / f"{source.name}.gz"
    else:
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

    with source.open("rb") as file_in:
        with gzip.open(destination, "wb") as file_out:
            shutil.copyfileobj(file_in, file_out)

    return destination


def decompress_file(source_path, destination_path=None):
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"Decompression skipped. File not found: {source.name}")

    if destination_path is None:
        name = source.name[:-3] if source.name.endswith(".gz") else f"{source.stem}.decompressed"
        destination = source.with_name(name)
    else:
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

    with gzip.open(source, "rb") as file_in:
        with destination.open("wb") as file_out:
            shutil.copyfileobj(file_in, file_out)

    return destination


def compress_file_zstd(source_path, destination_path=None, level=10):
    if zstd is None:
        raise RuntimeError("zstandard package is required for zstd compression")

    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"Compression skipped. File not found: {source.name}")

    if destination_path is None:
        destination = config.COMPRESSED / f"{source.name}.zst"
    else:
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

    compressor = zstd.ZstdCompressor(level=level)
    with source.open("rb") as file_in:
        payload = file_in.read()
    compressed = compressor.compress(payload)

    with destination.open("wb") as file_out:
        file_out.write(compressed)

    return destination
