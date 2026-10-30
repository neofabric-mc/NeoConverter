"""Download public validation fixtures into .validation only (not redistributed)."""
from pathlib import Path
import hashlib
import json
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / ".validation"
BASE.mkdir(exist_ok=True)


def read_url(url):
    request = urllib.request.Request(url, headers={"User-Agent": "NeoConverter/1.0.0 (local acceptance validation)"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def fetch_json(url):
    return json.loads(read_url(url))


def download(url, target, digest=None, algorithm="sha512"):
    if not target.exists() or (digest and hashlib.new(algorithm, target.read_bytes()).hexdigest() != digest):
        target.parent.mkdir(parents=True, exist_ok=True)
        data = read_url(url)
        if digest:
            assert hashlib.new(algorithm, data).hexdigest() == digest, target
        target.write_bytes(data)
    print(f"Downloaded/verified: {target.name} ({target.stat().st_size} bytes)", flush=True)


# Pin the observed official release so the acceptance test remains reproducible.
version = fetch_json("https://api.modrinth.com/v2/version/N08Z8wog")
assert version["version_type"] == "release" and "1.21.1" in version["game_versions"] and "fabric" in version["loaders"]
file = next((f for f in version["files"] if f.get("primary")), version["files"][0])
assert Path(file["filename"]).name == file["filename"] and file["filename"].endswith(".jar")
original = BASE / "inputs" / file["filename"]
download(file["url"], original, file["hashes"]["sha512"])
loader = BASE / "libraries" / "neofabric-loader-1.2.0.jar"
download("https://github.com/neofabric-mc/NeoFabric/releases/download/v1.2.0/neofabric-loader-1.2.0.jar", loader, "b6c5d9d1f27fc0da250fc96a5095ac68cedb99bf46d6bd45206e0dcb60171f23", "sha256")
with zipfile.ZipFile(original) as jar:
    mod_metadata = json.loads(jar.read("fabric.mod.json"))
with zipfile.ZipFile(loader) as jar:
    installer = json.loads(jar.read("fabric-installer.json"))
(BASE / "installer.json").write_text(json.dumps(installer,indent=2),encoding="utf-8")
manifest = fetch_json("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
game = next(v for v in manifest["versions"] if v["id"] == "1.21.1")
version_data = read_url(game["url"])
assert hashlib.sha1(version_data).hexdigest() == game["sha1"]
game_metadata = json.loads(version_data)
server = game_metadata["downloads"]["server"]
server_path = BASE / "libraries" / "minecraft-server-1.21.1.jar"
download(server["url"], server_path, server["sha1"], "sha1")
record = {"minecraft":"1.21.1","modVersion":version["version_number"],"modrinthVersionId":version["id"],"modUrl":file["url"],"modSha512":file["hashes"]["sha512"],"original":str(original),"modMetadata":mod_metadata,"loader":str(loader),"server":str(server_path)}
(BASE / "fixtures.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"mod":mod_metadata,"loaderLibraries":installer["libraries"]},ensure_ascii=False,indent=2),flush=True)
