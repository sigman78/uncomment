import sys
sys.path.insert(0, r"D:\non-esp\uncomment\src")
import numpy as np
from pathlib import Path
from model2vec import StaticModel
from unwaffle.extract import extract_source
from unwaffle.languages import spec_for_path
from unwaffle.model import Kind

ESPERDECK = Path(r"C:\tmp\claude\D--non-esp-uncomment\de55049b-d365-43bf-a1cc-fac3d9adf6f6\scratchpad\esperdeck")
VEND = {"esp_hid","monocypher","libssh2_esp","terminal","_deps","managed_components"}
pairs = []
for glob in ("*.c","*.h"):
    for p in sorted((ESPERDECK/"components").rglob(glob)):
        if any(part in VEND or part.startswith("build") for part in p.parts): continue
        s = spec_for_path(str(p))
        if s is None: continue
        sf = extract_source(str(p), p.read_text(encoding="utf-8-sig", errors="replace"), s)
        pairs += [(c.content.replace("\n"," ")[:400], c.attached_code.strip()[:200])
                  for c in sf.comments if c.kind is not Kind.DOC and c.word_count>=5 and c.attached_code.strip()]
model = StaticModel.from_pretrained("minishlab/potion-base-8M")
ec = model.encode([t for t,_ in pairs]); ex = model.encode([c for _,c in pairs])
def cos(a,b): return (a*b).sum(-1)/(np.linalg.norm(a,axis=-1)*np.linalg.norm(b,axis=-1)+1e-9)
rng = np.random.default_rng(7)
gap = cos(ec, ex) - cos(ec, ex[rng.permutation(len(ex))])
print(f"esperdeck transplant gap: mean {gap.mean():+.3f} over {len(pairs)} comments (house A was +0.150, mumble ~0)")
