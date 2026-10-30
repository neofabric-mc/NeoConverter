"""Validate the shipped executable itself, including its bundled Tcl/Tk."""
from pathlib import Path
import hashlib
import json
import os
import struct
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / ".validation" / "packaged"
BASE.mkdir(parents=True, exist_ok=True)
exe = Path(sys.argv[1]).resolve()
data = exe.read_bytes()
assert data[:2] == b"MZ"
pe = struct.unpack_from("<I",data,0x3C)[0]
assert data[pe:pe+4] == b"PE\0\0"
assert struct.unpack_from("<H",data,pe+4+20+68)[0] == 2, "Expected Windows GUI subsystem"
original = BASE / "中文 模组.jar"
plain = BASE / "普通库.jar"
with zipfile.ZipFile(original,"w") as archive:
    archive.writestr("fabric.mod.json",b'{"schemaVersion":1,"id":"packaged_test","version":"1.0"}')
    archive.writestr("assets/data.bin",bytes(range(256)))
    archive.writestr("LICENSE",b"Keep original license")
    for name in ("META-INF/A.SF","META-INF/A.RSA","META-INF/nested/a.dsa"):
        archive.writestr(name,b"test signature marker")
with zipfile.ZipFile(plain,"w") as archive:
    archive.writestr("lib/data.bin",b"not a Fabric mod")
original_hash=hashlib.sha256(original.read_bytes()).hexdigest()
environment=os.environ.copy()
temporary=ROOT/".cache/tmp"
temporary.mkdir(parents=True,exist_ok=True)
environment["TEMP"]=environment["TMP"]=str(temporary)
batch_report=BASE/"batch.json"
subprocess.run([str(exe),"--batch",str(original),str(plain),"--report",str(batch_report)],check=True,timeout=45,env=environment,cwd=ROOT)
batch=json.loads(batch_report.read_text(encoding="utf-8"))
assert (batch["success"],batch["skipped"])==(1,1)
result=next(row for row in batch["results"] if row["success"])
with zipfile.ZipFile(result["output"]) as archive:
    assert json.loads(archive.read("fabric.mod.json"))["neofabric"] is True
    assert archive.read("assets/data.bin")==bytes(range(256))
    assert archive.read("LICENSE")==b"Keep original license"
    assert not any(name.lower().endswith((".sf",".rsa",".dsa")) for name in archive.namelist())
assert hashlib.sha256(original.read_bytes()).hexdigest()==original_hash
gui_report=BASE/"gui.json"
subprocess.run([str(exe),"--gui-smoke-report",str(gui_report)],check=True,timeout=45,env=environment,cwd=ROOT)
gui=json.loads(gui_report.read_text(encoding="utf-8"))
assert gui["nativeDrop"] and gui["startButtonVisible"] and gui["footerVisible"],gui
assert gui["version"]=="1.0.0"
report={"exe":str(exe),"size":len(data),"sha256":hashlib.sha256(data).hexdigest(),"batchSuccess":1,"nonFabricSkipped":1,"signaturesRemoved":3,"originalUnchanged":True,"gui":gui}
(BASE/"verified.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(report,ensure_ascii=False,indent=2))
