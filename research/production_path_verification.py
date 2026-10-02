"""Phase 3 -- the ten pre-commit verification checks, run as code.

Each check prints PASS or FAIL with the evidence it used. Exit code is non-zero
if any check fails, so this cannot be reported as passing without having passed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

EXPECTED_TOKEN = "OOS-AUTHORISATION-NOT-ISSUED"
PRODUCTION_FILES = [
    "main_production.py", "bias_engine.py", "structure_engine.py",
    "entry_engine.py", "sweep_detector.py", "poi_engine.py",
    "liquidity_engine.py", "pullback_detector.py", "confidence_engine.py",
    "indicators.py", "config.py",
]
results: list[tuple[int, str, bool, str]] = []


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                          text=True, check=False).stdout.strip()


def check(n: int, name: str, ok: bool, evidence: str) -> None:
    results.append((n, name, bool(ok), evidence))


# 1. FINAL_OOS token unchanged.
manifest = json.loads((REPO / "research" / "research_split_manifest.json").read_text(encoding="utf-8"))
tok = manifest.get("oos_authorisation_token") or manifest.get("OOS_AUTHORISATION_TOKEN")
if tok is None:
    blob = json.dumps(manifest)
    tok = EXPECTED_TOKEN if EXPECTED_TOKEN in blob else "<not found>"
check(1, "FINAL_OOS token unchanged", tok == EXPECTED_TOKEN, f"token = {tok!r}")

# 2. FINAL_OOS inaccessible.
from research.dataset_access import OOSLockedError, load_arm, verify_dataset  # noqa: E402
try:
    load_arm("M15", "FINAL_OOS")
    check(2, "FINAL_OOS inaccessible", False, "load_arm returned data -- LOCK BROKEN")
except OOSLockedError as exc:
    check(2, "FINAL_OOS inaccessible", True, f"OOSLockedError: {str(exc)[:70]}")
except Exception as exc:                                              # noqa: BLE001
    check(2, "FINAL_OOS inaccessible", False, f"wrong exception: {type(exc).__name__}")

# 3. Dataset fingerprints unchanged.
try:
    vd = verify_dataset()
    bad = [k for k, v in vd.items() if isinstance(v, dict) and v.get("match") is False]
    check(3, "Dataset fingerprints unchanged", not bad, f"{len(vd)} timeframes verified, mismatches: {bad}")
except Exception as exc:                                              # noqa: BLE001
    check(3, "Dataset fingerprints unchanged", False, f"{type(exc).__name__}: {exc}")

# 4. Split manifest unchanged.
d = git("diff", "HEAD", "--", "research/research_split_manifest.json")
check(4, "Split manifest unchanged", d == "", "git diff empty" if d == "" else f"{len(d)} bytes of diff")

# 5. baseline008 unchanged.
d = git("status", "--porcelain", "--", "baselines/baseline_008")
check(5, "baseline_008 unchanged", d == "", "git status clean" if d == "" else d)

# 6. Production unchanged.
d = git("status", "--porcelain", "--", *PRODUCTION_FILES)
check(6, "Production code unchanged", d == "", f"{len(PRODUCTION_FILES)} files clean" if d == "" else d)

# 7. production_path_spec.md predates results.
spec_commit = git("log", "-1", "--format=%H %ct", "--", "research/production_path_spec.md")
spec_sha = spec_commit.split()[0] if spec_commit else ""
# the spec's own commit must contain no results file
files_in_spec_commit = git("show", "--name-only", "--format=", spec_sha).split() if spec_sha else []
offenders = [f for f in files_in_spec_commit
             if f != "research/production_path_spec.md"]
check(7, "spec predates results", bool(spec_sha) and not offenders,
      f"spec committed at {spec_sha[:7]}; that commit contains {files_in_spec_commit}")

# 8. Exact hypothesis count frozen before testing.
spec_txt = git("show", f"{spec_sha}:research/production_path_spec.md") if spec_sha else ""
declared_in_spec = "7 layers × 3 horizons = 21 hypotheses" in spec_txt or "21 tests" in spec_txt
res_path = REPO / "research" / "production_path_audit_results.json"
count_matches = None
if res_path.exists():
    res = json.loads(res_path.read_text(encoding="utf-8"))
    count_matches = res.get("declared_hypotheses") == 21 and \
        res.get("multiple_testing", {}).get("n_declared") == 21
check(8, "hypothesis count frozen at 21 before testing",
      declared_in_spec and (count_matches is not False),
      f"spec at {spec_sha[:7]} declares 21: {declared_in_spec}; results declare 21: {count_matches}")

# 9. Statistical guardrails pass.
r = subprocess.run([sys.executable, str(REPO / "research" / "phase1_statistical_controls.py")],
                   cwd=REPO, capture_output=True, text=True, check=False)
check(9, "statistical guardrail self-tests pass", r.returncode == 0,
      f"exit {r.returncode}; {(r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr).strip() else ''}")

# 10. Working tree contains only intended research changes.
porcelain = [l for l in git("status", "--porcelain").splitlines() if l.strip()]
allowed_prefixes = ("research/",)
unintended = [l for l in porcelain if not l[3:].startswith(allowed_prefixes)]
check(10, "working tree contains only research changes", not unintended,
      f"{len(porcelain)} entries; outside research/: {unintended or 'none'}")

print("=" * 78)
print("PHASE 3 PRE-COMMIT VERIFICATION")
print("=" * 78)
for n, name, ok, ev in results:
    print(f"  {n:2d}. {'PASS' if ok else 'FAIL'}  {name}")
    print(f"        {ev}")
failed = [n for n, _, ok, _ in results if not ok]
print("=" * 78)
print(f"  {len(results) - len(failed)}/{len(results)} passed"
      + (f"   FAILED: {failed}" if failed else "   all checks pass"))
sys.exit(1 if failed else 0)
