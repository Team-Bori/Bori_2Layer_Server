import hashlib
import shutil
import urllib.request
from pathlib import Path


def download_artifact(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url) as response, dest.open("wb") as output:
        shutil.copyfileobj(response, output)


def verify_artifact(path: Path, sha256: str, size: int) -> bool:
    data = path.read_bytes()
    if len(data) != size:
        return False
    return hashlib.sha256(data).hexdigest() == sha256
