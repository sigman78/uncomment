import re, sys
sys.path.insert(0, r"D:\non-esp\uncomment\src")
import numpy as np
from pathlib import Path
from model2vec import StaticModel
from unwaffle.extract import extract_source
from unwaffle.languages import spec_for_path
from unwaffle.model import Kind

exec(Path(r"experiments\phase1_roc.py").read_text(encoding="utf-8").split("model = StaticModel")[0])

model = StaticModel.from_pretrained("minishlab/potion-base-8M")
enc = lambda texts: model.encode(list(texts))
def norm(E): return E / (np.linalg.norm(E, axis=-1, keepdims=True) + 1e-9)

eH_unw = norm(enc([t for t,_ in H_unw])); eH_esp = norm(enc([t for t,_ in H_esp]))
eM_free = norm(enc(M_FREE))
eM_plain = norm(enc([t for t,_ in M_plain])); eM_drop = norm(enc([t for t,_ in M_drop]))
slop_cen = eM_free[::2].mean(0)
test_free = eM_free[1::2]

K = 5
def r_knn(E, repo, loo):
    sims = E @ repo.T
    if loo:
        np.fill_diagonal(sims, -1) if sims.shape[0] == sims.shape[1] else None
    top = np.sort(sims, axis=1)[:, -K:]
    return (E @ slop_cen) - top.mean(1)

R = {
    "H_unw": r_knn(eH_unw, eH_unw, True),
    "H_esp": r_knn(eH_esp, eH_esp, True),
    "M_free": r_knn(test_free, eH_esp, False),
    "M_plain": r_knn(eM_plain, eH_esp, False),
    "M_drop": r_knn(eM_drop, eH_esp, False),
}
def auc(pos, neg):
    pos, neg = np.asarray(pos), np.asarray(neg)
    return ((pos[:,None] > neg[None,:]).sum() + 0.5*(pos[:,None] == neg[None,:]).sum())/(len(pos)*len(neg))
H = np.concatenate([R["H_unw"], R["H_esp"]])
print(f"{'band':8} {'AUC R-knn':>10}   recall@5%FPR")
thr = np.quantile(H, 0.95)
for band in ("M_free","M_plain","M_drop"):
    print(f"{band:8} {auc(R[band], H):10.3f}   {(R[band] > thr).mean()*100:5.1f}%")
texts = [t for t,_ in H_unw] + [t for t,_ in H_esp]
print("\nremaining top FPs (R-knn):")
for i in np.argsort(H)[-8:][::-1]:
    print(f"  {H[i]:+.3f}  {texts[i][:82]}")
