"""Phase 1: per-comment discrimination, not population means.

Test sets:
  H_unw / H_esp   real comments with their own attached code (assumed informative)
  M_free          context-free mumble paired with random real code
  M_plain         slop templates attached to real code snippets
  M_drop          same, but cargo-culting a real identifier from that code
                  (the camouflage case lexical anchors could not beat)

Axes:
  G  grounding gap: cos(comment, own code) - mean cos(comment, 64 random codes)
  R  register: cos(comment, slop centroid) - cos(comment, this repo's own
     comment centroid)  [leave-one-out for the repo's own comments]

Reported: AUC per band per axis + combined, and recall at the threshold
that keeps false positives on real comments at 5%.
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
VEND = {"esp_hid", "monocypher", "libssh2_esp", "terminal", "_deps", "managed_components"}
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
rng = np.random.default_rng(11)

M_FREE = [
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

T_PLAIN = [
    "This function carefully handles all the edge cases to ensure correct behavior.",
    "Improves the overall robustness and reliability of the surrounding logic.",
    "This step is important for keeping everything consistent and maintainable.",
    "A clean approach that simplifies the flow and avoids potential issues.",
    "Makes sure the operation completes smoothly under various conditions.",
    "This logic is essential to the correct functioning of the system.",
    "Handles the necessary setup so everything works as expected here.",
]

T_DROP = [
    "This ensures {ident} works correctly across all the different scenarios.",
    "We carefully process {ident} to ensure optimal and reliable results.",
    "Uses {ident} to gracefully handle the various cases in a robust way.",
    "The {ident} logic below is designed for clarity and maintainability.",
    "Properly manages {ident} to avoid subtle issues down the line.",
    "Leverages {ident} to keep the overall behavior consistent and safe.",
    "Important: {ident} must be handled carefully to ensure correctness.",
]


def harvest(root: Path, globs, skip=frozenset()):
    out = []
    for g in globs:
        for p in sorted(root.rglob(g)):
            if any(part in skip or part.startswith("build") for part in p.parts):
                continue
            s = spec_for_path(str(p))
            if s is None:
                continue
            sf = extract_source(str(p), p.read_text(encoding="utf-8-sig", errors="replace"), s)
            for c in sf.comments:
                code = c.attached_code.strip()[:200]
                if c.kind is Kind.DOC or c.word_count < 5 or not code:
                    continue
                out.append((c.content.replace("\n", " ")[:400], code))
    return out


H_unw = harvest(Path(r"D:\non-esp\uncomment\src\unwaffle"), ["*.py"])
H_esp = harvest(ESPERDECK / "components", ["*.c", "*.h"], VEND)
print(f"harvested with code: unwaffle={len(H_unw)}  esperdeck={len(H_esp)}")

# contextual mumble: real code snippets, template comments; half name-drop
pool = H_unw + H_esp
ctx_codes = [pool[i][1] for i in rng.choice(len(pool), size=70, replace=False)]
M_plain = [(T_PLAIN[i % len(T_PLAIN)], code) for i, code in enumerate(ctx_codes[:35])]
M_drop = []
for i, code in enumerate(ctx_codes[35:]):
    m = IDENT_RE.search(code)
    ident = m.group(0) if m else "this value"
    M_drop.append((T_DROP[i % len(T_DROP)].format(ident=ident), code))

model = StaticModel.from_pretrained("minishlab/potion-base-8M")
enc = lambda texts: model.encode(list(texts))


def norm(E):
    return E / (np.linalg.norm(E, axis=-1, keepdims=True) + 1e-9)


def grounding(comments_emb, own_codes_emb, rand_codes_emb):
    own = (comments_emb * own_codes_emb).sum(-1)
    rand = comments_emb @ rand_codes_emb.T
    return own - rand.mean(-1)


# embeddings (normalized: cos = dot)
eH_unw, cH_unw = norm(enc(t for t, _ in H_unw)), norm(enc(c for _, c in H_unw))
eH_esp, cH_esp = norm(enc(t for t, _ in H_esp)), norm(enc(c for _, c in H_esp))
eM_free = norm(enc(M_FREE))
eM_plain, cM_plain = norm(enc(t for t, _ in M_plain)), norm(enc(c for _, c in M_plain))
eM_drop, cM_drop = norm(enc(t for t, _ in M_drop)), norm(enc(c for _, c in M_drop))

rand_codes = norm(enc(pool[i][1] for i in rng.choice(len(pool), size=64, replace=False)))
cM_free = rand_codes[rng.integers(0, 64, size=len(M_FREE))]  # mumble gets arbitrary code

G = {
    "H_unw": grounding(eH_unw, cH_unw, rand_codes),
    "H_esp": grounding(eH_esp, cH_esp, rand_codes),
    "M_free": grounding(eM_free, cM_free, rand_codes),
    "M_plain": grounding(eM_plain, cM_plain, rand_codes),
    "M_drop": grounding(eM_drop, cM_drop, rand_codes),
}

# register axis: slop centroid from HALF of M_free (train); repo's own comments as
# informative reference, leave-one-out for the repo's own
train = eM_free[::2]
slop_cen = train.mean(0)
test_free = eM_free[1::2]


def register(E, repo_emb, loo=False):
    s = E @ slop_cen
    total, n = repo_emb.sum(0), len(repo_emb)
    if loo:
        ref = (total[None, :] - E) / (n - 1)
        r = (E * norm(ref)).sum(-1)
    else:
        r = E @ norm((total / n)[None, :])[0]
    return s - r


R = {
    "H_unw": register(eH_unw, eH_unw, loo=True),
    "H_esp": register(eH_esp, eH_esp, loo=True),
    "M_free": register(test_free, eH_esp),   # score against esperdeck as host repo
    "M_plain": register(eM_plain, eH_esp),
    "M_drop": register(eM_drop, eH_esp),
}


def auc(pos, neg):
    pos, neg = np.asarray(pos), np.asarray(neg)
    return ((pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()) / (len(pos) * len(neg))


H_G = np.concatenate([G["H_unw"], G["H_esp"]])
H_R = np.concatenate([R["H_unw"], R["H_esp"]])
zG = lambda x: (np.mean(H_G) - x) / np.std(H_G)          # high = mumble
zR = lambda x: (x - np.mean(H_R)) / np.std(H_R)

print(f"\n{'band':8} {'AUC G':>7} {'AUC R':>7} {'AUC G+R':>8}")
combined = {}
for band in ("M_free", "M_plain", "M_drop"):
    cG, cR = zG(G[band]), zR(R[band])
    hG, hR = zG(H_G), zR(H_R)
    if band == "M_free":
        hG_band = zG(np.concatenate([G["H_unw"], G["H_esp"]]))
        # G for M_free uses all 40; R only the held-out 20 — align combined on min info
    combined[band] = cG + cR[: len(cG)] if len(cR) == len(cG) else None
    a_g = auc(cG, hG)
    a_r = auc(cR, hR)
    if len(cR) == len(cG):
        a_c = auc(cG + cR, hG + hR)
    else:
        a_c = auc(zG(G[band][1::2]) + cR, hG + hR)
    print(f"{band:8} {a_g:7.3f} {a_r:7.3f} {a_c:8.3f}")

# operating point: threshold at 5% FPR on real comments, combined score
H_comb = zG(H_G) + zR(H_R)
thr = np.quantile(H_comb, 0.95)
print(f"\nrecall at 5% FPR on real comments (combined score, thr={thr:.2f}):")
for band in ("M_free", "M_plain", "M_drop"):
    s = (zG(G[band][1::2]) + zR(R[band])) if band == "M_free" else (zG(G[band]) + zR(R[band]))
    print(f"  {band:8} {(s > thr).mean() * 100:5.1f}%   (n={len(s)})")

print("\nreal comments above threshold (the would-be false positives):")
texts = [t for t, _ in H_unw] + [t for t, _ in H_esp]
for i in np.argsort(H_comb)[-8:][::-1]:
    print(f"  {H_comb[i]:+.2f}  {texts[i][:82]}")
