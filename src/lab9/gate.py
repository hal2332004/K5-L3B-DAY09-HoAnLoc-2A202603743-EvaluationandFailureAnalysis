"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []

    # 1. Any metric value in pr["metrics"] that is NaN or inf
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, (int, float)):
            if math.isnan(v) or math.isinf(v):
                problems.append(f"metric {k} has invalid value {v}")

    # 2. len(pr["rows"]) != manifest items x len(manifest seeds) (dropped / duplicated rows)
    manifest = pr.get("manifest") or {}
    items_count = manifest.get("items", 0)
    seeds = manifest.get("seeds") or []
    expected_rows = items_count * len(seeds)
    rows = pr.get("rows") or []
    if len(rows) != expected_rows:
        problems.append(f"row count {len(rows)} != expected {expected_rows}")

    # Check for duplicate rows in PR
    seen_pairs: set[tuple[Any, Any]] = set()
    for r in rows:
        pair = (r.get("item_id"), r.get("seed"))
        if pair in seen_pairs:
            problems.append(f"duplicate row for {pair}")
        seen_pairs.add(pair)

    # 3. the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
    base_rows = base.get("rows") or []
    base_pairs = set((r.get("item_id"), r.get("seed")) for r in base_rows)
    pr_pairs = set((r.get("item_id"), r.get("seed")) for r in rows)
    if pr_pairs != base_pairs:
        problems.append("PR (item_id, seed) set differs from baseline")

    # 4. pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is None
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s)")

    spec_metric_ids = {m["id"] for m in spec.get("metrics") or []}
    for r in rows:
        for mid in spec_metric_ids:
            if mid in r and r[mid] is None:
                problems.append(f"row {r.get('item_id')}@{r.get('seed')} has None for metric {mid}")
                break

    # 5. base_spec given and a threshold in spec is LOOSER than in base_spec for the same eval-set version (ratchet)
    if base_spec is not None and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        base_metrics = {m["id"]: m for m in base_spec.get("metrics") or []}
        spec_metrics = {m["id"]: m for m in spec.get("metrics") or []}

        # Check for missing metrics
        for mid, bm in base_metrics.items():
            if mid not in spec_metrics:
                problems.append(f"metric {mid} disappeared from spec")
                continue
            sm = spec_metrics[mid]
            if bm.get("blocking") and not sm.get("blocking"):
                problems.append(f"blocking metric {mid} became non-blocking")

            b_th = bm.get("threshold") or {}
            s_th = sm.get("threshold") or {}

            if "min" in b_th:
                if "min" not in s_th or s_th["min"] < b_th["min"]:
                    problems.append(f"min threshold for {mid} loosened from {b_th['min']} to {s_th.get('min')}")
            if "max" in b_th:
                if "max" not in s_th or s_th["max"] > b_th["max"]:
                    problems.append(f"max threshold for {mid} loosened from {b_th['max']} to {s_th.get('max')}")
            if "max_increase" in b_th:
                if "max_increase" not in s_th or s_th["max_increase"] > b_th["max_increase"]:
                    problems.append(f"max_increase for {mid} loosened from {b_th['max_increase']} to {s_th.get('max_increase')}")
            if b_th.get("no_significant_drop") and not s_th.get("no_significant_drop"):
                problems.append(f"no_significant_drop dropped for {mid}")

        # Check slices in ratchet
        base_slices = {s["name"]: s for s in base_spec.get("slices") or []}
        spec_slices = {s["name"]: s for s in spec.get("slices") or []}
        for sname, bs_item in base_slices.items():
            if sname not in spec_slices:
                problems.append(f"slice {sname} disappeared from spec")
                continue
            ss_item = spec_slices[sname]
            if bs_item.get("blocking") and not ss_item.get("blocking"):
                problems.append(f"blocking slice {sname} became non-blocking")
            if "min" in bs_item:
                if "min" not in ss_item or ss_item["min"] < bs_item["min"]:
                    problems.append(f"min threshold for slice {sname} loosened")
            if bs_item.get("no_significant_drop") and not ss_item.get("no_significant_drop"):
                problems.append(f"no_significant_drop dropped for slice {sname}")

    # 6. an item's slice tags in PR rows differ from the baseline's
    base_item_slices: dict[str, set[str]] = {}
    for r in base_rows:
        base_item_slices.setdefault(r.get("item_id"), set(r.get("slices") or []))
    for r in rows:
        iid = r.get("item_id")
        if iid in base_item_slices:
            if set(r.get("slices") or []) != base_item_slices[iid]:
                problems.append(f"slice tags for item {iid} altered")
                break

    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices", []):
        name = s["name"]
        mid = s["metric"]
        th_min = s.get("min")
        blocking = s.get("blocking", True)

        pr_items = per_item(pr, mid, slice_name=name)
        if not pr_items:
            continue
        val = sum(pr_items.values()) / len(pr_items)

        verdict, note = "ok", ""
        if th_min is not None and val < th_min:
            verdict = "fail"

        if s.get("no_significant_drop"):
            base_items = per_item(base, mid, slice_name=name)
            keys = sorted(set(pr_items) & set(base_items))
            if keys:
                d, lo, hi = stats.paired_bootstrap([pr_items[k] for k in keys], [base_items[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"

        sid = f"slice:{name}/{mid}"
        if verdict != "ok" and blocking:
            blocked.append(sid)

        label = {"ok": "ok"}.get(verdict, "BLOCK" if blocking else "warn")
        lines.append(f"  {sid:<22} {val!s:<8} min={th_min} {note:<28} {label}")

    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
