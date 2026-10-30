"""Run the actual released NeoFabric Loader in separate Java 21 JVMs."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from converter import convert_jar, is_signature

BASE = ROOT / ".validation"
record = json.loads((BASE / "fixtures.json").read_text(encoding="utf-8"))
installer = json.loads((BASE / "installer.json").read_text(encoding="utf-8"))
libraries = [Path(record["loader"]), Path(record["server"])]


def download(url, target, digest=None, algorithm="sha512"):
    if not target.exists():
        request = urllib.request.Request(url, headers={"User-Agent":"NeoConverter/1.0.0 acceptance"})
        with urllib.request.urlopen(request, timeout=90) as response:
            data = response.read()
        if digest:
            assert hashlib.new(algorithm,data).hexdigest() == digest
        target.write_bytes(data)
    if digest:
        assert hashlib.new(algorithm,target.read_bytes()).hexdigest() == digest
    print("Verified library:", target.name, flush=True)


for item in installer["libraries"]["common"] + installer["libraries"].get("server", []):
    group, artifact, version = item["name"].split(":")
    filename = artifact + "-" + version + ".jar"
    url = item["url"].rstrip("/") + "/" + group.replace(".", "/") + "/" + artifact + "/" + version + "/" + filename
    target = BASE / "libraries" / filename
    download(url,target,item["sha512"])
    libraries.append(target)

mappings = BASE / "libraries" / "intermediary-1.21.1.jar"
download("https://maven.fabricmc.net/net/fabricmc/intermediary/1.21.1/intermediary-1.21.1.jar",mappings)
libraries.append(mappings)
original = Path(record["original"])
original_digest = hashlib.sha512(original.read_bytes()).hexdigest()
assert original_digest == record["modSha512"]
assert "neofabric" not in record["modMetadata"]
executable = None
if "--executable" in sys.argv:
    executable = Path(sys.argv[sys.argv.index("--executable") + 1]).resolve()
    executable_report = BASE / "real-exe-conversion.json"
    environment = os.environ.copy()
    environment["TEMP"] = environment["TMP"] = str(ROOT / ".cache/tmp")
    subprocess.run([str(executable), "--batch", str(original), "--report", str(executable_report)], check=True, timeout=45, env=environment)
    result_data = json.loads(executable_report.read_text(encoding="utf-8"))
    assert result_data["success"] == 1, result_data
    converted = Path(result_data["results"][0]["output"])
else:
    result = convert_jar(original)
    assert result.success, result.reason
    converted = result.output
with zipfile.ZipFile(original) as before, zipfile.ZipFile(converted) as after:
    a = json.loads(before.read("fabric.mod.json"))
    b = json.loads(after.read("fabric.mod.json"))
    assert b.pop("neofabric") is True and a == b
    expected = [x for x in before.namelist() if not is_signature(x)]
    assert after.namelist() == expected
    assert not any(is_signature(x) for x in after.namelist())
    for info in after.infolist():
        if info.filename != "fabric.mod.json":
            assert after.read(info) == before.read(info.filename), info.filename
    unchanged_files = len(after.infolist()) - 1
assert hashlib.sha512(original.read_bytes()).hexdigest() == original_digest

plain = next(p for p in libraries if p.name.startswith("asm-9."))
non_fabric = convert_jar(plain)
assert not non_fabric.success and "非 Fabric 模组" in non_fabric.reason
classes = BASE / "probe-classes"
classes.mkdir(exist_ok=True)
subprocess.run(["javac","-cp",str(record["loader"]),"-d",str(classes),str(ROOT/"scripts/NeoConverterLoadProbe.java")],check=True)
classpath = os.pathsep.join(str(p) for p in [classes,*libraries])
outcomes = {}
for mode, jar in (("original",original),("converted",converted)):
    directory = BASE / (mode+"-run")
    mods = directory / "mods"
    mods.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(jar,mods/"lithium.jar")
    log = BASE / (mode+"-loader.log")
    command=["java","-Xmx1536M","-Djava.awt.headless=true","-Djava.io.tmpdir="+str(ROOT/".cache/tmp"),"-cp",classpath,"NeoConverterLoadProbe","true" if mode=="converted" else "false"]
    with log.open("w",encoding="utf-8") as output:
        process=subprocess.run(command,cwd=directory,stdout=output,stderr=subprocess.STDOUT,timeout=300)
    text=log.read_text(encoding="utf-8",errors="replace")
    if process.returncode:
        print(text[-14000:],flush=True)
        raise RuntimeError(f"{mode} probe failed: {log}")
    marker="NEOCONVERTER_ACCEPTED" if mode=="converted" else "NEOCONVERTER_REJECTED_ORIGINAL"
    assert marker in text
    outcomes[mode]=next(line for line in text.splitlines() if marker in line)
    print(outcomes[mode],flush=True)
report={"converter":"packaged-exe" if executable else "source", "exeSha256":hashlib.sha256(executable.read_bytes()).hexdigest() if executable else None, "mod":"Lithium","modVersion":record["modVersion"],"minecraft":"1.21.1","java":21,"loader":"1.2.0","originalSha512":original_digest,"converted":str(converted),"unchangedFiles":unchanged_files,"remainingSignatures":0,"nonFabricSkipped":True,"probes":outcomes,"scope":"Knot init + discovery/resolution/transformers + real mod entrypoint class definition; no full game/server main or gameplay."}
(BASE/"acceptance.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
