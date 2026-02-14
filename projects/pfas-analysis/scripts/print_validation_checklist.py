"""Print formatted validation checklist and gap analysis to terminal."""

from pathlib import Path

import yaml

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "methods"
CHECKLIST_PATH = DATA_DIR / "validation_checklist.yaml"
GAP_PATH = DATA_DIR / "gap_analysis.yaml"

STATUS_SYMBOLS = {
    "pass": "\u2705",
    "fail": "\u274c",
    "pending": "\u2b1c",
    "na": "\u2796",
    "transferred": "\u2705",
    "verified": "\u2705",
    "needs_optimization": "\U0001f7e1",
    "not_applicable": "\u2796",
}


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def print_header(title, width=80):
    print()
    print("=" * width)
    print(f"{title:^{width}s}")
    print("=" * width)


def print_section(title, width=80):
    print()
    print(f"--- {title} {'-' * (width - len(title) - 5)}")


def progress_bar(done, total, width=30):
    pct = done / total if total > 0 else 0
    filled = int(width * pct)
    bar = "\u2588" * filled + "\u2591" * (width - filled)
    return f"[{bar}] {done}/{total} ({pct:.0%})"


def count_statuses(steps):
    counts = {"pass": 0, "fail": 0, "pending": 0, "na": 0}
    for s in steps:
        status = s.get("status", "pending")
        if status in counts:
            counts[status] += 1
    return counts


def print_checklist(checklist):
    print_header("PFAS Method Validation Checklist")
    print("Method: SOP E-AED-PEB-SOP-1908-1 (Waters TQD) \u2192 Shimadzu LCMS-8060")

    # Overall progress
    all_steps = [s for p in checklist["phases"] for s in p["steps"]]
    total = len(all_steps)
    counts = count_statuses(all_steps)
    done = counts["pass"] + counts["na"]

    print()
    print(f"  Overall: {progress_bar(done, total)}")
    print(f"  Pass: {counts['pass']}  Fail: {counts['fail']}  "
          f"Pending: {counts['pending']}  N/A: {counts['na']}")

    # Per-phase
    for phase in checklist["phases"]:
        steps = phase["steps"]
        pc = count_statuses(steps)
        phase_done = pc["pass"] + pc["na"]

        print_section(f"Phase {phase['phase']}: {phase['name']}")
        print(f"  {progress_bar(phase_done, len(steps))}")
        print()

        for step in steps:
            sym = STATUS_SYMBOLS.get(step["status"], "?")
            status_str = step["status"].upper()
            date_str = f"  [{step['date']}]" if step.get("date") else ""
            print(f"  {sym} {step['id']:>5s}  {step['description'].strip()}")
            print(f"         Status: {status_str}{date_str}")
            criteria = step.get("acceptance_criteria", "").strip()
            if criteria:
                # Wrap long criteria
                for i in range(0, len(criteria), 65):
                    prefix = "         Criteria: " if i == 0 else "                   "
                    print(f"{prefix}{criteria[i:i+65]}")
            ref = step.get("reference", "")
            if ref:
                print(f"         Ref: {ref}")
            notes = step.get("notes", "")
            if notes:
                print(f"         Notes: {notes}")
            print()


def print_gap_analysis(gap):
    print_header("Gap Analysis: SOP (Waters TQD) vs Shimadzu 8060")

    # Summary counts
    all_items = gap["lc_parameters"] + gap["ms_source_parameters"] + gap["mrm_transitions"]
    if "qc_criteria" in gap and "criteria" in gap["qc_criteria"]:
        all_items += gap["qc_criteria"]["criteria"]

    status_counts = {}
    for item in all_items:
        s = item.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    print()
    print("  Status Summary:")
    for status, count in sorted(status_counts.items()):
        sym = STATUS_SYMBOLS.get(status, "?")
        print(f"    {sym} {status:24s} {count:3d}")
    print(f"    {'Total':26s} {len(all_items):3d}")

    # LC Parameters
    print_section("LC Parameters")
    print(f"  {'Parameter':<30s} {'SOP Value':<35s} {'Shimadzu':<35s} {'Status'}")
    print(f"  {'-'*30} {'-'*35} {'-'*35} {'-'*20}")
    for p in gap["lc_parameters"]:
        sym = STATUS_SYMBOLS.get(p["status"], "?")
        sop = str(p["sop_value"])[:35]
        shim = str(p["shimadzu_value"])[:35]
        print(f"  {p['parameter']:<30s} {sop:<35s} {shim:<35s} {sym} {p['status']}")

    # MS Source Parameters
    print_section("MS Source Parameters")
    print(f"  {'Parameter':<30s} {'SOP Value':<35s} {'Shimadzu':<35s} {'Status'}")
    print(f"  {'-'*30} {'-'*35} {'-'*35} {'-'*20}")
    for p in gap["ms_source_parameters"]:
        sym = STATUS_SYMBOLS.get(p["status"], "?")
        sop = str(p["sop_value"])[:35]
        shim = str(p["shimadzu_value"])[:35]
        print(f"  {p['parameter']:<30s} {sop:<35s} {shim:<35s} {sym} {p['status']}")

    # MRM Transitions
    print_section("MRM Transitions")
    print(f"  {'Compound':<14s} {'Class':<6s} {'Quantifier':<12s} "
          f"{'SOP CE':>6s} {'8060 CE':>7s} {'SOP RT':>6s} {'8060 RT':>7s} {'Status'}")
    print(f"  {'-'*14} {'-'*6} {'-'*12} {'-'*6} {'-'*7} {'-'*6} {'-'*7} {'-'*20}")
    for t in gap["mrm_transitions"]:
        sym = STATUS_SYMBOLS.get(t["status"], "?")
        rt_8060 = f"{t['shimadzu_rt_min']:.1f}" if t.get("shimadzu_rt_min") else "  -"
        ce_8060 = f"{t['shimadzu_ce']}" if t.get("shimadzu_ce") is not None else "  -"
        print(f"  {t['compound']:<14s} {t['compound_class']:<6s} {t['sop_quantifier']:<12s} "
              f"{t['sop_ce']:>6} {ce_8060:>7s} {t['sop_rt_min']:>6.1f} {rt_8060:>7s} "
              f"{sym} {t['status']}")

    # Compounds not in SOP
    print_section("Compounds Not in SOP (Require Standalone Validation)")
    non_sop = gap["compounds_not_in_sop"]
    for c in non_sop["compounds"]:
        sym = STATUS_SYMBOLS.get(c["status"], "?")
        print(f"  {sym} {c['compound']} ({c.get('other_name', '')})")
        print(f"       Quantifier: {c['quantifier']}  Est. CE: {c['estimated_ce']}  "
              f"Est. RT: {c['estimated_rt_min']} min")
        print(f"       IS: {c['internal_standard']}")
        print(f"       Validation: {c['validation_required'].strip()[:80]}...")
        print()

    # QC Criteria
    if "qc_criteria" in gap and "criteria" in gap["qc_criteria"]:
        print_section("QC Acceptance Criteria")
        print(f"  {'Parameter':<26s} {'SOP Value':<30s} {'Shimadzu':<30s} {'Status'}")
        print(f"  {'-'*26} {'-'*30} {'-'*30} {'-'*20}")
        for c in gap["qc_criteria"]["criteria"]:
            sym = STATUS_SYMBOLS.get(c["status"], "?")
            sop = str(c["sop_value"])[:30]
            shim = str(c["shimadzu_value"])[:30]
            print(f"  {c['parameter']:<26s} {sop:<30s} {shim:<30s} {sym} {c['status']}")


def main():
    checklist = load_yaml(CHECKLIST_PATH)
    gap = load_yaml(GAP_PATH)

    print_checklist(checklist)
    print_gap_analysis(gap)

    # Final summary
    print()
    print("=" * 80)
    all_steps = [s for p in checklist["phases"] for s in p["steps"]]
    counts = count_statuses(all_steps)
    total = len(all_steps)
    done = counts["pass"] + counts["na"]
    print(f"Validation: {done}/{total} steps complete ({done/total*100:.0f}%)")
    if counts["fail"] > 0:
        print(f"  {counts['fail']} step(s) FAILED - review required")
    if counts["pending"] > 0:
        print(f"  {counts['pending']} step(s) pending")
    print("=" * 80)


if __name__ == "__main__":
    main()
