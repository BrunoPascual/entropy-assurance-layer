"""Para cada CSV versionado em data/results, confere se o SHA3-256 do blob
no Git e o do arquivo em disco aparecem no meta correspondente."""
import hashlib
import subprocess
from pathlib import Path


def sha3(data: bytes) -> str:
    return hashlib.sha3_256(data).hexdigest()


def blob(path: str) -> bytes:
    return subprocess.run(["git", "show", f":{path}"], capture_output=True, check=True).stdout


tracked = subprocess.run(
    ["git", "ls-files", "data/results"], capture_output=True, text=True, check=True
).stdout.split()

for path in tracked:
    if not path.endswith(".csv"):
        continue
    meta = Path(path).with_suffix(".meta.json")
    if not meta.exists():
        print(f"SEM META   {path}")
        continue
    text = meta.read_text(encoding="utf-8")
    in_blob = sha3(blob(path)) in text
    in_disk = sha3(Path(path).read_bytes()) in text
    estado = "OK      " if in_blob else "DIVERGE "
    print(f"{estado} {path}  blob={in_blob}  disco={in_disk}")
