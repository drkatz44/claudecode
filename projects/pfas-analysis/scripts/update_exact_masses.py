#!/usr/bin/env python3
"""Update compounds.yaml with exact monoisotopic masses and corrected [M-H]- precursor m/z values.

Computed from molecular formulas using IUPAC 2021 atomic masses:
  12C  = 12.00000    13C = 13.00335
  1H   =  1.00783    2H  =  2.01410
  19F  = 18.99840    16O = 15.99491
  14N  = 14.00307    32S = 31.97207
  e-   =  0.00055 (electron mass)

[M-H]- = monoisotopic_mass - 1.00728 (proton mass = H - e-)
"""

import yaml
from pathlib import Path

# Exact monoisotopic masses (neutral molecule) calculated from molecular formulas
# Native analytes
EXACT_MASSES = {
    # PFCAs
    "PFBA":       213.9865,  # C4HF7O2
    "PFPeA":      263.9833,  # C5HF9O2
    "PFHxA":      313.9801,  # C6HF11O2
    "PFHpA":      363.9769,  # C7HF13O2
    "PFOA":       413.9737,  # C8HF15O2
    "PFNA":       463.9705,  # C9HF17O2
    "PFDA":       513.9673,  # C10HF19O2
    "PFUdA":      563.9641,  # C11HF21O2
    "PFDoA":      613.9609,  # C12HF23O2
    "PFTrDA":     663.9577,  # C13HF25O2
    "PFTeDA":     713.9545,  # C14HF27O2
    # PFSAs
    "PFBS":       299.9502,  # C4HF9O3S
    "PFPeS":      349.9470,  # C5HF11O3S
    "PFHxS":      399.9438,  # C6HF13O3S
    "PFHpS":      449.9406,  # C7HF15O3S
    "PFOS":       499.9374,  # C8HF17O3S
    "PFNS":       549.9342,  # C9HF19O3S
    "PFDS":       599.9310,  # C10HF21O3S
    # FTS
    "4:2-FTS":    327.9816,  # C6H5F9O3S
    "6:2-FTS":    427.9752,  # C8H5F13O3S
    "8:2-FTS":    527.9688,  # C10H5F17O3S
    # Sulfonamides
    "FOSA":       498.9534,  # C8H2F17NO2S
    "N-MeFOSAA":  570.9746,  # C11H6F17NO4S
    "N-EtFOSAA":  584.9902,  # C12H8F17NO4S
    # Ethers
    "HFPO-DA":    329.9750,  # C6HF11O3
    "ADONA":      377.9761,  # C7H2F12O4
    # Internal standards (13C or d-labeled)
    "MPFBA-13C4":       217.9999,  # 13C4-HF7O2
    "M5PFPeA-13C5":     269.0000,  # 13C5-HF9O2
    "M3PFBS-13C3":      302.9603,  # 13C3-C1HF9O3S
    "M5PFHxA-13C5":     318.9968,  # 13C5-C1HF11O2
    "M2-4:2-FTS-13C2":  329.9883,  # 13C2-C4H5F9O3S
    "M4PFHpA-13C4":     367.9903,  # 13C4-C3HF13O2
    "M3PFHxS-13C3":     402.9539,  # 13C3-C3HF13O3S
    "M8PFOA-13C8":      422.0005,  # 13C8-HF15O2
    "M2-6:2-FTS-13C2":  429.9819,  # 13C2-C6H5F13O3S
    "M9PFNA-13C9":      473.0006,  # 13C9-HF17O2
    "M8FOSA":           506.9802,  # 13C8-H2F17NO2S
    "M8PFOS-13C8":      507.9642,  # 13C8-HF17O3S
    "M6PFDA-13C6":      519.9874,  # 13C6-C4HF19O2
    "M2-8:2-FTS-13C2":  529.9755,  # 13C2-C8H5F17O3S
    "M7PFUdA-13C7":     570.9875,  # 13C7-C4HF21O2
    "MeFOSAA-d3":       573.9934,  # C11H3D3F17NO4S
    "EtFOSAA-d5":       590.0216,  # C12H3D5F17NO4S
    "M2PFDoA-13C2":     615.9676,  # 13C2-C10HF23O2
    "M2PFTeDA-13C2":    715.9612,  # 13C2-C12HF27O2
    "M3HFPO-DA":        332.9850,  # 13C3-C3HF11O3
}

PROTON_MASS = 1.00728  # Da (H atom - electron)


def compute_precursor_mz(monoisotopic_mass: float) -> float:
    """Compute [M-H]- precursor m/z, rounded to 0.1 Da."""
    exact = monoisotopic_mass - PROTON_MASS
    return round(exact, 1)


def main():
    compounds_path = Path(__file__).parent.parent / "data" / "methods" / "compounds.yaml"

    with open(compounds_path) as f:
        data = yaml.safe_load(f)

    changes = []

    for compound in data["compounds"]:
        abbrev = compound["abbreviation"]

        if abbrev not in EXACT_MASSES:
            print(f"WARNING: No exact mass for {abbrev}")
            continue

        mono_mass = EXACT_MASSES[abbrev]
        correct_precursor = compute_precursor_mz(mono_mass)

        # Add monoisotopic_mass
        compound["monoisotopic_mass"] = mono_mass

        # Fix precursor_mz in all transitions
        for t in compound["transitions"]:
            old_precursor = t["precursor_mz"]
            if abs(old_precursor - correct_precursor) > 0.01:
                changes.append(
                    f"  {abbrev}: precursor {old_precursor} -> {correct_precursor}"
                )
                t["precursor_mz"] = correct_precursor

    # Write updated file
    with open(compounds_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"Updated {compounds_path}")
    print(f"\nMonoisotopic masses added to all {len(data['compounds'])} compounds")
    print(f"\nPrecursor m/z corrections ({len(changes)}):")
    for c in changes:
        print(c)


if __name__ == "__main__":
    main()
