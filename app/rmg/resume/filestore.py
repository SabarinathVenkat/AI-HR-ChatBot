"""Where uploaded files live: a directory outside the repository, addressed by random keys.

A key is generated here and never taken from a user, and `get` accepts only keys of that exact shape, so a crafted key
cannot reach another path.
"""
import re
import uuid
from pathlib import Path

KEY = re.compile(r"^[0-9a-f]{32}\.(docx|pdf|txt)$")
SUFFIXES = frozenset({".docx", ".pdf", ".txt"})


class FileStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes, suffix: str) -> str:
        if suffix not in SUFFIXES:
            raise ValueError("unsupported file type")
        key = uuid.uuid4().hex + suffix
        (self.root / key).write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        if not KEY.match(key or ""):
            raise FileNotFoundError("no such file")
        return (self.root / key).read_bytes()

    def delete(self, key: str) -> None:
        if KEY.match(key or ""):
            (self.root / key).unlink(missing_ok=True)
