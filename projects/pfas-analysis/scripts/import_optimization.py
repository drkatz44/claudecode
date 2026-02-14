#!/usr/bin/env python3
"""Import Shimadzu MRM optimization results into compounds.yaml.

Parses the OptimizeResult text file from LabSolutions MRM Optimization,
extracts optimized CE, Q1 Pre Bias, and Q3 Pre Bias values, and updates
the compounds database.

Policy: native analyte values are applied to both native and IS compounds
(user preference for simplified method).
"""

import re
import sys
import yaml
from pathlib import Path

# Optimization result files — processed in order (later files override earlier)
OPT_DIR = Path("/Volumes/Extreme SSD/Shimadzu/Optimization Data")
OPT_FILES = [
    OPT_DIR / "20260212_140407" / "OptimizeResult_PFAS 533 Optimization_20260212_1407.txt",
    OPT_DIR / "20260213_131609" / "OptimizeResult_PFAS 533 Optimization_20260213_1317.txt",
]

COMPOUNDS_FILE = Path(__file__).parent.parent / "data" / "methods" / "compounds.yaml"

# Map optimization event IDs to compound abbreviations in compounds.yaml
OPT_ID_TO_ABBREV = {
    # Batch 1 (2026-02-12): PFAC-24PAR + MPFAC-24ES core compounds
    1:  "PFBA",
    2:  "MPFBA-13C4",
    3:  "PFPeA",
    4:  "M5PFPeA-13C5",
    5:  "PFBS",
    6:  "M3PFBS-13C3",
    7:  "4:2-FTS",
    8:  "M2-4:2-FTS-13C2",
    9:  "PFHxA",
    10: "M5PFHxA-13C5",
    11: "PFPeS",
    12: "PFHpA",
    13: "M4PFHpA-13C4",
    14: "PFHxS",
    15: "M3PFHxS-13C3",
    16: "PFHpS",
    17: "6:2-FTS",
    18: "M2-6:2-FTS-13C2",
    19: "PFOA",
    20: "M8PFOA-13C8",
    21: "PFOS",
    22: "M8PFOS-13C8",
    23: "PFNA",
    24: "M9PFNA-13C9",
    25: "8:2-FTS",
    26: "M2-8:2-FTS-13C2",
    27: "PFDA",
    28: "M6PFDA-13C6",
    29: "M2PFDoA-13C2",
    30: "PFUdA",
    31: "M7PFUdA-13C7",
    32: "PFDoA",
    33: "PFTrDA",
    34: "PFTeDA",
    # Batch 2 (2026-02-13): Sulfonamides + remaining PFSAs
    35: "PFNS",
    36: "PFDS",
    37: "FOSA",
    38: "N-MeFOSAA",
    39: "N-EtFOSAA",
    40: "M8FOSA",
    41: "MeFOSAA-d3",
    42: "EtFOSAA-d5",
}

# Native → IS pairing (from compounds.yaml internal_standard field)
# Used to apply native CE/bias values to IS compounds
NATIVE_IS_PAIRS = {
    "PFBA":      "MPFBA-13C4",
    "PFPeA":     "M5PFPeA-13C5",
    "PFHxA":     "M5PFHxA-13C5",
    "PFHpA":     "M4PFHpA-13C4",
    "PFOA":      "M8PFOA-13C8",
    "PFNA":      "M9PFNA-13C9",
    "PFDA":      "M6PFDA-13C6",
    "PFUdA":     "M7PFUdA-13C7",
    "PFDoA":     "M2PFDoA-13C2",
    "PFTrDA":    "M2PFTeDA-13C2",
    "PFTeDA":    "M2PFTeDA-13C2",
    "PFBS":      "M3PFBS-13C3",
    "PFPeS":     "M3PFBS-13C3",
    "PFHxS":     "M3PFHxS-13C3",
    "PFHpS":     "M8PFOS-13C8",
    "PFOS":      "M8PFOS-13C8",
    "PFNS":      "M8PFOS-13C8",
    "PFDS":      "M8PFOS-13C8",
    "4:2-FTS":   "M2-4:2-FTS-13C2",
    "6:2-FTS":   "M2-6:2-FTS-13C2",
    "8:2-FTS":   "M2-8:2-FTS-13C2",
    "FOSA":      "M8FOSA",
    "N-MeFOSAA": "MeFOSAA-d3",
    "N-EtFOSAA": "EtFOSAA-d5",
    "HFPO-DA":   "M3HFPO-DA",
    "ADONA":     "M3HFPO-DA",
}


def parse_optimization_results(filepath):
    """Parse the <<Optimum result>> section of the optimization report.

    Returns dict: {abbrev: [{"precursor": float, "product": float,
                              "ce": float, "q1_bias": float, "q3_bias": float,
                              "is_quantifier": bool}, ...]}
    """
    text = filepath.read_text(encoding="utf-8")

    # Extract the <<Optimum result>> section (between <<Optimum result>> and <<Intensity>>)
    opt_match = re.search(r"<<Optimum result>>\s*\n(.+?)<<Intensity>>", text, re.DOTALL)
    if not opt_match:
        raise ValueError("Could not find <<Optimum result>> section")

    opt_text = opt_match.group(1)
    results = {}

    # Parse blocks like:
    # ID1\tCh1\t
    # 213.0000>169.0000 -> 213.0000>169.0000\t
    # Q1 Pre Bias\t15.0 -> 25.0\t
    # CE\t\t10.0 -> 10.0\t
    # Q3 Pre Bias\t15.0 -> 17.0\t
    block_pattern = re.compile(
        r"ID(\d+)\s+Ch(\d+)\s*\n"
        r"([\d.]+)>([\d.]+)\s*->\s*([\d.]+)>([\d.]+)\s*\n"
        r"Q1 Pre Bias\s+([\d.]+)\s*->\s*([\d.]+)\s*\n"
        r"CE\s+([\d.]+)\s*->\s*([\d.]+)\s*\n"
        r"Q3 Pre Bias\s+([\d.]+)\s*->\s*([\d.]+)",
        re.MULTILINE,
    )

    for m in block_pattern.finditer(opt_text):
        event_id = int(m.group(1))
        channel = int(m.group(2))
        precursor = float(m.group(5))  # "new" precursor (should be same as old)
        product = float(m.group(6))    # "new" product
        q1_bias = float(m.group(8))    # optimized Q1
        ce = float(m.group(10))        # optimized CE
        q3_bias = float(m.group(12))   # optimized Q3

        abbrev = OPT_ID_TO_ABBREV.get(event_id)
        if not abbrev:
            print(f"  WARNING: Unknown event ID {event_id}")
            continue

        if abbrev not in results:
            results[abbrev] = []

        results[abbrev].append({
            "precursor": precursor,
            "product": product,
            "ce": ce,
            "q1_bias": q1_bias,
            "q3_bias": q3_bias,
            "is_quantifier": channel == 1,
        })

    return results


def match_transition(compound_transitions, opt_product, opt_is_quant):
    """Find the matching transition in compounds.yaml by product m/z."""
    # First try exact match on product + quantifier status
    for i, t in enumerate(compound_transitions):
        if abs(t["product_mz"] - opt_product) < 0.5 and t["is_quantifier"] == opt_is_quant:
            return i

    # Fallback: match by product m/z only
    for i, t in enumerate(compound_transitions):
        if abs(t["product_mz"] - opt_product) < 0.5:
            return i

    return None


def main():
    print("=" * 70)
    print("Shimadzu MRM Optimization Import")
    print("=" * 70)

    # Accept file paths from CLI or use defaults
    files = [Path(f) for f in sys.argv[1:]] if len(sys.argv) > 1 else OPT_FILES

    # Parse optimization results from all files (later files override earlier)
    opt_results = {}
    for filepath in files:
        if not filepath.exists():
            print(f"  SKIP: {filepath} (not found)")
            continue
        print(f"\nParsing: {filepath.name}")
        batch = parse_optimization_results(filepath)
        print(f"  Found {len(batch)} compounds")
        for abbrev, transitions in batch.items():
            opt_results[abbrev] = transitions  # later overrides earlier

    print(f"\nTotal: optimization results for {len(opt_results)} compounds")

    # Load compounds.yaml
    with open(COMPOUNDS_FILE) as f:
        data = yaml.safe_load(f)

    compounds_by_abbrev = {c["abbreviation"]: c for c in data["compounds"]}

    # Build native CE lookup for IS equalization
    # For each native, store CE per product_mz
    native_ce_lookup = {}  # {native_abbrev: {product_mz_rounded: {ce, q1, q3}}}
    for abbrev, transitions in opt_results.items():
        if abbrev in NATIVE_IS_PAIRS:  # it's a native
            native_ce_lookup[abbrev] = {}
            for t in transitions:
                native_ce_lookup[abbrev][t["is_quantifier"]] = {
                    "ce": t["ce"],
                    "q1_bias": t["q1_bias"],
                    "q3_bias": t["q3_bias"],
                }

    # Apply optimized values
    changes = []
    warnings = []

    for abbrev, opt_transitions in opt_results.items():
        compound = compounds_by_abbrev.get(abbrev)
        if not compound:
            warnings.append(f"Compound {abbrev} not found in compounds.yaml")
            continue

        for opt_t in opt_transitions:
            idx = match_transition(
                compound["transitions"], opt_t["product"], opt_t["is_quantifier"]
            )
            if idx is None:
                warnings.append(
                    f"  {abbrev}: no match for product {opt_t['product']}"
                    f" ({'quant' if opt_t['is_quantifier'] else 'qual'})"
                )
                continue

            t = compound["transitions"][idx]
            old_ce = t["collision_energy"]
            old_q1 = t["q1_pre_bias"]
            old_q3 = t["q3_pre_bias"]

            t["collision_energy"] = opt_t["ce"]
            t["q1_pre_bias"] = opt_t["q1_bias"]
            t["q3_pre_bias"] = opt_t["q3_bias"]

            tag = "quant" if opt_t["is_quantifier"] else "qual"
            if old_ce != opt_t["ce"] or old_q1 != opt_t["q1_bias"] or old_q3 != opt_t["q3_bias"]:
                changes.append(
                    f"  {abbrev:20s} {tag:5s} {t['product_mz']:>6.0f}  "
                    f"CE {old_ce:>5.0f} -> {opt_t['ce']:>5.0f}  "
                    f"Q1 {old_q1:>5.0f} -> {opt_t['q1_bias']:>5.0f}  "
                    f"Q3 {old_q3:>5.0f} -> {opt_t['q3_bias']:>5.0f}"
                )

    # Now apply native values to IS compounds (equalize native/IS)
    print("\n--- Equalizing native/IS values (applying native CE to IS) ---")
    equalized = []

    for native_abbrev, is_abbrev in NATIVE_IS_PAIRS.items():
        if native_abbrev not in opt_results:
            continue  # native wasn't optimized

        is_compound = compounds_by_abbrev.get(is_abbrev)
        if not is_compound:
            continue

        native_opt = opt_results[native_abbrev]

        for native_t in native_opt:
            # Find the IS transition with the same quantifier/qualifier status
            for is_t in is_compound["transitions"]:
                if is_t["is_quantifier"] == native_t["is_quantifier"]:
                    old_ce = is_t["collision_energy"]

                    if old_ce != native_t["ce"]:
                        equalized.append(
                            f"  {is_abbrev:20s} {'quant' if native_t['is_quantifier'] else 'qual':5s} "
                            f"CE {old_ce:>5.0f} -> {native_t['ce']:>5.0f} "
                            f"(from {native_abbrev})"
                        )
                        is_t["collision_energy"] = native_t["ce"]
                    break  # only match first transition with same quant/qual status

    # Handle IS compounds not in optimization but whose native was optimized
    # Apply native CE to unoptimized IS
    print("\n--- Applying native CE to IS compounds not in optimization ---")
    unopt_applied = []

    for native_abbrev, is_abbrev in NATIVE_IS_PAIRS.items():
        if native_abbrev not in opt_results:
            continue
        if is_abbrev in opt_results:
            continue  # IS was already optimized, handled above

        is_compound = compounds_by_abbrev.get(is_abbrev)
        if not is_compound:
            continue

        native_opt = opt_results[native_abbrev]
        # Apply native quantifier CE to IS quantifier
        for native_t in native_opt:
            if native_t["is_quantifier"]:
                for is_t in is_compound["transitions"]:
                    if is_t["is_quantifier"]:
                        old_ce = is_t["collision_energy"]
                        if old_ce != native_t["ce"]:
                            unopt_applied.append(
                                f"  {is_abbrev:20s} quant "
                                f"CE {old_ce:>5.0f} -> {native_t['ce']:>5.0f} "
                                f"(from {native_abbrev}, IS not in optimization)"
                            )
                            is_t["collision_energy"] = native_t["ce"]
                        break
                break

    # Manual overrides: M3PFBS-13C3 should use PFBS CE (36), not PFPeS CE (38)
    # Both PFBS and PFPeS share M3PFBS as IS; PFBS is the primary pairing.
    m3pfbs = compounds_by_abbrev.get("M3PFBS-13C3")
    if m3pfbs and "PFBS" in opt_results:
        for pfbs_t in opt_results["PFBS"]:
            if pfbs_t["is_quantifier"]:
                for is_t in m3pfbs["transitions"]:
                    if is_t["is_quantifier"]:
                        is_t["collision_energy"] = pfbs_t["ce"]
                        break
                break

    # Write updated compounds.yaml
    with open(COMPOUNDS_FILE, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Print report
    print(f"\n{'=' * 70}")
    print("OPTIMIZATION IMPORT REPORT")
    print(f"{'=' * 70}")

    print(f"\nDirect updates from optimization ({len(changes)}):")
    for c in changes:
        print(c)

    print(f"\nNative/IS CE equalization ({len(equalized)}):")
    for e in equalized:
        print(e)

    print(f"\nUnoptimized IS updated from native ({len(unopt_applied)}):")
    for u in unopt_applied:
        print(u)

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings:
            print(w)

    # Print compounds NOT covered by optimization
    optimized_abbrevs = set(opt_results.keys())
    # Also count IS that were equalized
    equalized_is = {NATIVE_IS_PAIRS[n] for n in opt_results if n in NATIVE_IS_PAIRS}
    covered = optimized_abbrevs | equalized_is

    not_covered = []
    for c in data["compounds"]:
        if c["abbreviation"] not in covered:
            not_covered.append(c["abbreviation"])

    if not_covered:
        print(f"\nCompounds NOT covered by optimization ({len(not_covered)}):")
        for nc in not_covered:
            print(f"  {nc} — needs separate optimization")

    # Print final summary table
    print(f"\n{'=' * 70}")
    print("FINAL OPTIMIZED MRM TABLE")
    print(f"{'=' * 70}")
    print(f"{'Compound':22s} {'Type':5s} {'Precursor':>9s} {'Product':>8s} "
          f"{'CE':>5s} {'Q1':>5s} {'Q3':>5s}")
    print("-" * 70)

    for c in data["compounds"]:
        for i, t in enumerate(c["transitions"]):
            tag = "quant" if t["is_quantifier"] else "qual"
            print(f"{c['abbreviation']:22s} {tag:5s} {t['precursor_mz']:>9.1f} "
                  f"{t['product_mz']:>8.1f} {t['collision_energy']:>5.0f} "
                  f"{t['q1_pre_bias']:>5.0f} {t['q3_pre_bias']:>5.0f}")


if __name__ == "__main__":
    main()
