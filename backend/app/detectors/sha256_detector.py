import hashlib
from pathlib import Path
from typing import BinaryIO


class SHA256Detector:
    @staticmethod
    def from_bytes(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def from_stream(stream: BinaryIO, chunk_size: int = 1024 * 1024) -> str:
        digest = hashlib.sha256()
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def from_path(path: Path) -> str:
        with path.open("rb") as stream:
            return SHA256Detector.from_stream(stream)

