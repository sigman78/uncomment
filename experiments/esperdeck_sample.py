import sys
sys.path.insert(0, r"D:\non-esp\uncomment\src")
import numpy as np
from pathlib import Path
from model2vec import StaticModel
import importlib.util
spec = importlib.util.spec_from_file_location("pilot", r"experiments\mumble_pilot.py")
# reuse harvest/cos from the pilot without rerunning its __main__ prints: inline instead
from unwaffle.extract import extract_source
from unwaffle.languages import spec_for_path
from unwaffle.model import Kind

ESPERDECK = Path(r"C:\tmp\claude\D--non-esp-uncomment\de55049b-d365-43bf-a1cc-fac3d9adf6f6\scratchpad\esperdeck")
VEND = {"esp_hid","monocypher","libssh2_esp","terminal","_deps","managed_components"}
def harvest(root, glob):
    out=[]
    for p in sorted(root.rglob(glob)):
        if any(part in VEND or part.startswith("build") for part in p.parts): continue
        s = spec_for_path(str(p))
        if s is None: continue
        sf = extract_source(str(p), p.read_text(encoding="utf-8-sig", errors="replace"), s)
        out += [c.content.replace("\n"," ")[:400] for c in sf.comments if c.kind is not Kind.DOC and c.word_count>=5]
    return out

MUMBLE_FILE = Path(r"experiments\mumble_pilot.py").read_text(encoding="utf-8")
import ast
tree = ast.parse(MUMBLE_FILE)
MUMBLE = next(ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "MUMBLE")

model = StaticModel.from_pretrained("minishlab/potion-base-8M")
A = harvest(Path(r"src\unwaffle"), "*.py")
B = harvest(ESPERDECK/"components", "*.c") + harvest(ESPERDECK/"components", "*.h")
eA, eB, eC = model.encode(A), model.encode(B), model.encode(MUMBLE)
def cos(a,b): return (a*b).sum(-1)/(np.linalg.norm(a,axis=-1)*np.linalg.norm(b,axis=-1)+1e-9)
cenA, cenC = eA.mean(0), eC.mean(0)
s = cos(eB, cenC) - cos(eB, cenA)
print("top-15 mumble-scored esperdeck comments:")
for i in np.argsort(s)[-15:][::-1]:
    print(f"  {s[i]:+.3f}  {B[i][:84]}")
