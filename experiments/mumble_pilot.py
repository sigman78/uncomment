"""Phase-0 pilot: can tiny static embeddings separate mumble from
informative comments, deterministically and offline?

Populations:
  A  unwaffle src/ comments        (informative; dogfooded house style)
  B  esperdeck first-party C code  (informative; different repo+language)
  C  synthetic mumble              (gpt/cloud register, context-free)
  D  corpus agent_noise comments   (agent culture-noise; distribution only)

Metrics:
  1. leave-one-out nearest-centroid AUC, A vs C; B scored for generalization
  2. transplant gap: cos(comment, own code) - mean cos(comment, other code);
     informative comments should lose similarity when transplanted, mumble
     should not care
  3. where D lands between the centroids
"""
import re
import sys
from pathlib import Path

import numpy as np
from model2vec import StaticModel

sys.path.insert(0, r"D:\non-esp\uncomment\src")
from unwaffle.extract import extract_source
from unwaffle.languages import spec_for_path
from unwaffle.model import Kind

ESPERDECK = Path(r"C:\tmp\claude\D--non-esp-uncomment\de55049b-d365-43bf-a1cc-fac3d9adf6f6\scratchpad\esperdeck")
VENDORED = {"esp_hid", "monocypher", "libssh2_esp", "terminal", "_deps", "managed_components", "build"}

MUMBLE = [
    "This function leverages the caching layer to ensure optimal performance.",
    "Note that we utilize a robust retry mechanism to seamlessly handle transient failures.",
    "It's worth noting that this comprehensive approach ensures data integrity.",
    "We delve into the payload structure to extract the relevant fields.",
    "Additionally, this elegant solution gracefully handles all edge cases.",
    "This is crucial for maintaining a seamless user experience.",
    "The handler is designed to be highly performant and scalable.",
    "This ensures that the state remains consistent, a key consideration for concurrency.",
    "Let's carefully validate the input to avoid potential issues down the line.",
    "This powerful abstraction streamlines the overall data processing workflow.",
    "The underlying implementation harnesses zero-copy semantics for efficiency.",
    "As previously mentioned, robust error handling is absolutely paramount here.",
    "We meticulously track each connection to foster proper resource hygiene.",
    "This pivotal change underscores our commitment to clean architecture.",
    "Handles various scenarios including but not limited to network timeouts.",
    "Ensures everything works correctly across the different configurations.",
    "A clean and maintainable way to organize the related functionality.",
    "This helper improves readability and keeps the code well structured.",
    "Carefully orchestrates the various components for maximum reliability.",
    "Provides a flexible foundation for future extensibility and growth.",
    "The logic below is straightforward and self-explanatory in most cases.",
    "We gracefully degrade when things go wrong to keep the experience smooth.",
    "This elegant symmetry between the two paths keeps the design honest.",
    "The refactoring validates the overall approach we have taken so far.",
    "Significantly improves the general robustness of the entire pipeline.",
    "Best practices dictate that we handle this case defensively here.",
    "A thoughtful balance between simplicity and power guides this design.",
    "This encapsulates the complexity so callers enjoy a clean interface.",
    "Streamlined for clarity, consistency, and long term maintainability.",
    "The implementation reflects a deliberate and principled design choice.",
    "Adds an extra layer of safety to make the system more resilient.",
    "This step is essential for the correct functioning of the module.",
    "Modern, idiomatic, and clean way of expressing the same intent.",
    "We optimize aggressively here to deliver a truly seamless experience.",
    "Takes care of all the necessary bookkeeping behind the scenes.",
    "Robust by construction, this guards against a wide range of failures.",
    "The code speaks for itself but the intent deserves a brief mention.",
    "Handles the happy path efficiently while remaining fully general.",
    "A small but mighty utility that simplifies everything downstream.",
    "Future proofed so that upcoming requirements slot in effortlessly.",
]


def harvest(root: Path, glob: str, skip_parts=frozenset()):
    out = []
    for p in sorted(root.rglob(glob)):
        if any(part in skip_parts or part.startswith("build") for part in p.parts):
            continue
        spec = spec_for_path(str(p))
        if spec is None:
            continue
        sf = extract_source(str(p), p.read_text(encoding="utf-8-sig", errors="replace"), spec)
        for c in sf.comments:
            if c.kind is Kind.DOC or c.word_count < 5:
                continue
            out.append((c.content.replace("\n", " ")[:400], c.attached_code.strip()[:200]))
    return out


def auc(pos_scores, neg_scores):
    """Mann-Whitney: P(random pos > random neg)."""
    pos, neg = np.asarray(pos_scores), np.asarray(neg_scores)
    wins = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return wins / (len(pos) * len(neg))


def cos(a, b):
    return (a * b).sum(-1) / (np.linalg.norm(a, axis=-1) * np.linalg.norm(b, axis=-1) + 1e-9)


model = StaticModel.from_pretrained("minishlab/potion-base-8M")

A = harvest(Path(r"D:\non-esp\uncomment\src\unwaffle"), "*.py")
B = harvest(ESPERDECK / "components", "*.c", VENDORED) + harvest(ESPERDECK / "components", "*.h", VENDORED)
D = harvest(Path(r"D:\non-esp\uncomment\tests\corpus"), "agent_noise.*")
print(f"harvested: A(unwaffle)={len(A)}  B(esperdeck)={len(B)}  C(mumble)={len(MUMBLE)}  D(agent_noise)={len(D)}")

emb_A = model.encode([t for t, _ in A])
emb_B = model.encode([t for t, _ in B])
emb_C = model.encode(MUMBLE)
emb_D = model.encode([t for t, _ in D])

# --- metric 1: leave-one-out nearest-centroid AUC (A=informative vs C=mumble)
sum_A, sum_C = emb_A.sum(0), emb_C.sum(0)
score_A = [cos(x, (sum_C) / len(emb_C)) - cos(x, (sum_A - x) / (len(emb_A) - 1)) for x in emb_A]
score_C = [cos(x, (sum_C - x) / (len(emb_C) - 1)) - cos(x, sum_A / len(emb_A)) for x in emb_C]
print(f"\nAUC (mumble vs unwaffle house, leave-one-out): {auc(score_C, score_A):.3f}")

cen_A, cen_C = sum_A / len(emb_A), sum_C / len(emb_C)
score = lambda E: cos(E, cen_C) - cos(E, cen_A)
sB, sD = score(emb_B), score(emb_D)
print(f"esperdeck comments scored as mumble (score>0): {(sB > 0).sum()}/{len(sB)}  (generalization check)")
print(f"agent_noise corpus comments scored as mumble:  {(sD > 0).sum()}/{len(sD)}")

# --- metric 2: transplant gap
rng = np.random.default_rng(7)
codes = [code for _, code in A if code]
emb_codes = model.encode(codes)
own_idx = [i for i, (_, code) in enumerate(A) if code]
own_sim = cos(emb_A[own_idx], emb_codes)
shuf = rng.permutation(len(codes))
transplant_A = own_sim - cos(emb_A[own_idx], emb_codes[shuf])
rand_codes = emb_codes[rng.choice(len(codes), size=len(MUMBLE))]
rand_codes2 = emb_codes[rng.choice(len(codes), size=len(MUMBLE))]
transplant_C = cos(emb_C, rand_codes) - cos(emb_C, rand_codes2)
print(f"\ntransplant gap (own-code sim minus random-code sim):")
print(f"  house A : mean {transplant_A.mean():+.3f}  (>0 means comments belong to their code)")
print(f"  mumble C: mean {transplant_C.mean():+.3f}  (~0 means transplantable anywhere)")

# --- qualitative: our own most mumble-scored comments
sA = score(emb_A)
print("\nour own top-6 mumble-scored comments (src/unwaffle):")
for i in np.argsort(sA)[-6:][::-1]:
    print(f"  {sA[i]:+.3f}  {A[i][0][:78]}")
print("\nsynthetic mumble scored most 'informative' (hardest cases):")
for i in np.argsort(score(emb_C))[:3]:
    print(f"  {score(emb_C)[i]:+.3f}  {MUMBLE[i][:78]}")
