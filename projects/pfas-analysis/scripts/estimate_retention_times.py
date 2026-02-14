"""Estimate retention times for PFAS compounds on BEH C18 and print transition table."""

from pathlib import Path
from pfas_analysis.method.compounds import CompoundDatabase

# Estimated retention times (minutes) on BEH C18 2.1x50mm, 1.7µm
# Gradient: 25→95% MeOH over 7.5 min (0.5-8.0 min), 0.4 mL/min, 40°C
# These are estimates based on typical PFAS C18 chromatography.
# Actual RTs will shift depending on column lot, mobile phase prep, system dwell volume, etc.
# Use these as starting points for MRM time windows.

ESTIMATED_RT = {
    # Short-chain PFCAs - weakly retained
    "PFBA": 1.1,
    "PFPeA": 1.9,
    "PFHxA": 2.7,
    "PFHpA": 3.5,
    "PFOA": 4.3,
    "PFNA": 5.0,
    "PFDA": 5.7,
    "PFUdA": 6.2,
    "PFDoA": 6.7,
    "PFTrDA": 7.1,
    "PFTeDA": 7.5,
    # PFSAs - elute after corresponding-length PFCA
    "PFBS": 2.2,
    "PFPeS": 3.0,
    "PFHxS": 3.8,
    "PFHpS": 4.5,
    "PFOS": 5.2,
    "PFNS": 5.8,
    "PFDS": 6.4,
    # FTS - elute near PFSAs of similar chain length
    "4:2-FTS": 2.5,
    "6:2-FTS": 4.2,
    "8:2-FTS": 5.6,
    # Sulfonamides
    "FOSA": 5.9,
    "N-MeFOSAA": 5.4,
    "N-EtFOSAA": 5.7,
    # Ethers - relatively polar, elute early
    "HFPO-DA": 1.8,
    "ADONA": 2.3,
    # IS compounds co-elute with their native analogs
    "MPFBA-13C4": 1.1,
    "M5PFPeA-13C5": 1.9,
    "M3PFBS-13C3": 2.2,
    "M5PFHxA-13C5": 2.7,
    "M2-4:2-FTS-13C2": 2.5,
    "M4PFHpA-13C4": 3.5,
    "M3PFHxS-13C3": 3.8,
    "M8PFOA-13C8": 4.3,
    "M2-6:2-FTS-13C2": 4.2,
    "M9PFNA-13C9": 5.0,
    "M8FOSA": 5.9,
    "M8PFOS-13C8": 5.2,
    "M6PFDA-13C6": 5.7,
    "M2-8:2-FTS-13C2": 5.6,
    "M7PFUdA-13C7": 6.2,
    "MeFOSAA-d3": 5.4,
    "EtFOSAA-d5": 5.7,
    "M2PFDoA-13C2": 6.7,
    "M2PFTeDA-13C2": 7.5,
    "M3HFPO-DA": 1.8,
}


def main():
    db = CompoundDatabase.load(Path("data/methods/compounds.yaml"))

    # Assign estimated RTs
    for abbr, rt in ESTIMATED_RT.items():
        compound = db.get(abbr)
        if compound:
            compound.retention_time_min = rt

    # Save updated database
    db.save(Path("data/methods/compounds.yaml"))

    # Print native analyte table sorted by RT
    analytes = sorted(db.analytes, key=lambda c: c.retention_time_min or 99)

    print()
    print("=" * 112)
    print(f"{'PFAS MRM Transition Table - Shimadzu LCMS-8060':^112s}")
    print(f"{'BEH C18 2.1x50mm | 25→95% MeOH | ESI(-)':^112s}")
    print("=" * 112)
    print(
        f"{'RT':>5s}  "
        f"{'Compound':<16s}  "
        f"{'Class':<6s}  "
        f"{'Quantifier':^22s}  "
        f"{'Qualifier':^22s}  "
        f"{'Internal Standard':<20s}"
    )
    print(
        f"{'(min)':>5s}  "
        f"{'':<16s}  "
        f"{'':<6s}  "
        f"{'Q1 → Q3     CE':^22s}  "
        f"{'Q1 → Q3     CE':^22s}  "
        f"{'':<20s}"
    )
    print("-" * 112)

    for c in analytes:
        rt = f"{c.retention_time_min:.1f}" if c.retention_time_min else "?"
        q = c.quantifier
        qual = c.qualifier

        if q:
            quant_str = f"{q.precursor_mz:6.1f} → {q.product_mz:5.1f}  {q.collision_energy:4.0f}"
        else:
            quant_str = f"{'—':^22s}"

        if qual:
            qual_str = f"{qual.precursor_mz:6.1f} → {qual.product_mz:5.1f}  {qual.collision_energy:4.0f}"
        else:
            qual_str = f"{'—':^22s}"

        is_name = c.internal_standard or "—"

        print(f"{rt:>5s}  {c.abbreviation:<16s}  {c.compound_class:<6s}  {quant_str}  {qual_str}  {is_name:<20s}")

    print("-" * 112)

    # Print IS table
    standards = sorted(db.internal_standards, key=lambda c: c.retention_time_min or 99)

    print()
    print(f"{'Internal Standards':^80s}")
    print("-" * 80)
    print(f"{'RT':>5s}  {'Compound':<22s}  {'Q1 → Q3     CE':^22s}  {'For analyte(s)':<24s}")
    print("-" * 80)

    # Map IS to their native analytes
    is_to_natives: dict[str, list[str]] = {}
    for c in db.analytes:
        if c.internal_standard:
            is_to_natives.setdefault(c.internal_standard, []).append(c.abbreviation)

    for c in standards:
        rt = f"{c.retention_time_min:.1f}" if c.retention_time_min else "?"
        q = c.quantifier
        if q:
            q_str = f"{q.precursor_mz:6.1f} → {q.product_mz:5.1f}  {q.collision_energy:4.0f}"
        else:
            q_str = "—"
        natives = ", ".join(is_to_natives.get(c.abbreviation, []))
        print(f"{rt:>5s}  {c.abbreviation:<22s}  {q_str}  {natives:<24s}")

    print("-" * 80)
    print()
    print("Notes:")
    print("  - Retention times are estimates; verify with standards on your system")
    print("  - CE values are literature starting points; optimize via LabSolutions MRM optimization")
    print("  - Q1/Q3 pre-rod biases set to 0.0; optimize during infusion")
    print("  - All transitions ESI negative mode [M-H]-")
    print("  - PFSAs: quantifier product m/z 80 = SO3⁻; qualifier m/z 99 = FSO3⁻")
    print("  - PFCAs: quantifier = loss of CO2 (44 Da); qualifiers are chain-specific fragments")
    print("  - FTS: quantifier = loss of HF (20 Da)")
    print()


if __name__ == "__main__":
    main()
