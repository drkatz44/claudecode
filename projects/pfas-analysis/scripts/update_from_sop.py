"""Update compound database with actual validated parameters from SOP Table 3."""

from pathlib import Path
from pfas_analysis.method.compounds import CompoundDatabase, MRMTransition

# Actual validated data from SOP E-AED-PEB-SOP-1908-1, Table 3
# Waters Xevo TQD parameters
# Format: (RT, quant_transition, dwell, cone, CE, [qualifier_transitions...], IS_ref)
# qualifier_transition = (product_mz, cone, CE)

SOP_DATA = {
    # Native PFASs
    "PFBA":       (1.1, 213, 169, 0.017, 20, 11, [], "MPFBA-13C4"),
    "PFPeA":      (2.6, 263, 219, 0.007, 20, 10, [], "M5PFPeA-13C5"),
    "PFBS":       (3.6, 299, 80,  0.006, 40, 55, [(99, 40, 33)], "M3PFBS-13C3"),
    "PFHxA":      (4.3, 313, 269, 0.005, 20, 10, [(119, 20, 22)], "M5PFHxA-13C5"),
    "4:2-FTS":    (4.2, 327, 307, 0.005, 35, 20, [(81, 35, 20)], "M2-4:2-FTS-13C2"),
    "PFPeS":      (4.5, 349, 80,  0.005, 40, 50, [(99, 40, 50)], "M3PFBS-13C3"),
    "PFHpA":      (4.9, 363, 319, 0.005, 20, 11, [(169, 20, 22)], "M4PFHpA-13C4"),
    "PFHxS":      (5.0, 399, 80,  0.005, 40, 50, [(99, 40, 40)], "M3PFHxS-13C3"),
    "PFOA":       (5.5, 413, 369, 0.005, 20, 11, [(169, 20, 22), (269, 20, 22)], "M8PFOA-13C8"),
    "6:2-FTS":    (5.2, 427, 407, 0.005, 35, 25, [(81, 35, 25)], "M2-6:2-FTS-13C2"),
    "PFHpS":      (5.5, 449, 80,  0.005, 40, 50, [(99, 40, 50)], "M8PFOS-13C8"),
    "PFNA":       (5.8, 463, 419, 0.005, 20, 11, [(419, 20, 22), (219, 20, 22)], "M9PFNA-13C9"),
    "FOSA":       (6.5, 498, 78,  0.005, 45, 40, [(119, 45, 57), (169, 45, 57)], "M8FOSA"),
    "PFOS":       (5.4, 499, 80,  0.005, 40, 60, [(99, 40, 50)], "M8PFOS-13C8"),
    "PFDA":       (6.1, 513, 469, 0.005, 20, 11, [(219, 20, 22), (169, 20, 22)], "M6PFDA-13C6"),
    "8:2-FTS":    (5.9, 527, 507, 0.005, 40, 30, [(81, 40, 30)], "M2-8:2-FTS-13C2"),
    "PFNS":       (6.1, 549, 80,  0.005, 40, 60, [(99, 40, 50)], "M8PFOS-13C8"),
    "PFUdA":      (6.4, 563, 519, 0.005, 20, 11, [(269, 20, 22), (219, 20, 33)], "M7PFUdA-13C7"),
    "N-MeFOSAA":  (6.1, 570, 419, 0.005, 28, 28, [(512, 28, 28), (483, 28, 28)], "MeFOSAA-d3"),
    "N-EtFOSAA":  (6.2, 584, 419, 0.005, 31, 30, [(526, 31, 30), (483, 31, 30)], "EtFOSAA-d5"),
    "PFDS":       (6.4, 599, 80,  0.005, 40, 60, [(99, 40, 50)], "M8PFOS-13C8"),
    "PFDoA":      (6.6, 613, 569, 0.005, 20, 11, [(169, 20, 33), (269, 20, 33)], "M2PFDoA-13C2"),
    "PFTrDA":     (6.8, 663, 619, 0.005, 20, 11, [(169, 20, 33), (269, 20, 33)], "M2PFTeDA-13C2"),
    "PFTeDA":     (6.9, 713, 669, 0.005, 20, 11, [(169, 20, 33), (269, 20, 33)], "M2PFTeDA-13C2"),

    # Internal Standards
    "MPFBA-13C4":       (1.2, 217, 172, 0.017, 20, 11, [], None),
    "M5PFPeA-13C5":     (2.6, 268, 223, 0.007, 20, 11, [], None),
    "M3PFBS-13C3":      (3.6, 302, 80,  0.006, 40, 55, [(99, 40, 33)], None),
    "M5PFHxA-13C5":     (4.3, 318, 273, 0.005, 20, 10, [(119, 20, 22)], None),
    "M2-4:2-FTS-13C2":  (4.2, 329, 309, 0.005, 35, 20, [(81, 35, 20)], None),
    "M4PFHpA-13C4":     (4.9, 367, 322, 0.005, 20, 11, [(171, 20, 22)], None),
    "M3PFHxS-13C3":     (5.0, 402, 80,  0.005, 40, 50, [(99, 40, 40)], None),
    "M8PFOA-13C8":      (5.5, 421, 376, 0.005, 20, 11, [(171, 20, 22), (223, 20, 22)], None),
    "M2-6:2-FTS-13C2":  (5.2, 429, 409, 0.005, 35, 25, [(81, 35, 25)], None),
    "M9PFNA-13C9":      (5.8, 472, 427, 0.005, 20, 11, [(423, 20, 22), (171, 20, 22)], None),
    "M8FOSA":           (6.5, 506, 78,  0.005, 45, 40, [(172, 45, 57)], None),
    "M8PFOS-13C8":      (5.4, 507, 80,  0.005, 40, 60, [(99, 40, 50)], None),
    "M6PFDA-13C6":      (6.1, 519, 474, 0.005, 20, 11, [(219, 20, 22), (169, 20, 22)], None),
    "M2-8:2-FTS-13C2":  (5.9, 529, 509, 0.005, 40, 30, [(81, 40, 30)], None),
    "M7PFUdA-13C7":     (6.4, 570, 525, 0.005, 20, 11, [(269, 20, 22), (219, 20, 33)], None),
    "MeFOSAA-d3":       (6.1, 573, 419, 0.005, 28, 28, [(515, 28, 28), (483, 28, 28)], None),
    "EtFOSAA-d5":       (6.2, 589, 419, 0.005, 31, 30, [(531, 31, 30), (483, 31, 30)], None),
    "M2PFDoA-13C2":     (6.6, 615, 570, 0.005, 20, 11, [(169, 20, 33), (269, 20, 33)], None),
    "M2PFTeDA-13C2":    (6.9, 715, 670, 0.005, 20, 11, [(169, 20, 33), (269, 20, 33)], None),
}

# Method Detection Limits from SOP Table 7 (ng/L, based on 1L sample)
MDLS = {
    "PFBA": 0.05, "PFPeA": 0.03, "PFBS": 0.05, "PFHxA": 0.05,
    "4:2-FTS": 0.10, "PFPeS": 0.11, "PFHpA": 0.06, "PFHxS": 0.07,
    "PFOA": 0.06, "6:2-FTS": 0.12, "PFHpS": 0.16, "PFNA": 0.08,
    "FOSA": 0.07, "PFOS": 0.08, "PFDA": 0.08, "8:2-FTS": 0.24,
    "PFNS": 0.09, "PFUdA": 0.11, "N-MeFOSAA": 0.03, "N-EtFOSAA": 0.08,
    "PFDS": 0.18, "PFDoA": 0.06, "PFTrDA": 0.13, "PFTeDA": 0.86,
}


def main():
    db = CompoundDatabase.load(Path("data/methods/compounds.yaml"))

    for abbr, data in SOP_DATA.items():
        rt, q1, q3, dwell, cone, ce, qualifiers, is_ref = data
        compound = db.get(abbr)
        if not compound:
            print(f"  WARNING: {abbr} not in database, skipping")
            continue

        compound.retention_time_min = rt
        if is_ref is not None:
            compound.internal_standard = is_ref

        # Rebuild transitions from SOP data
        transitions = []
        transitions.append(MRMTransition(
            precursor_mz=float(q1),
            product_mz=float(q3),
            collision_energy=float(ce),
            is_quantifier=True,
            dwell_time_ms=dwell * 1000,  # SOP uses seconds, we store ms
            q1_pre_bias=float(cone),  # Store cone voltage; needs re-optimization on 8060
            q3_pre_bias=0.0,
            polarity="negative",
        ))
        for qual_q3, qual_cone, qual_ce in qualifiers:
            transitions.append(MRMTransition(
                precursor_mz=float(q1),
                product_mz=float(qual_q3),
                collision_energy=float(qual_ce),
                is_quantifier=False,
                dwell_time_ms=dwell * 1000,
                q1_pre_bias=float(qual_cone),
                q3_pre_bias=0.0,
                polarity="negative",
            ))
        compound.transitions = transitions

    db.save(Path("data/methods/compounds.yaml"))

    # Print updated table sorted by RT
    all_compounds = sorted(db.compounds.values(), key=lambda c: c.retention_time_min or 99)
    analytes = [c for c in all_compounds if not c.is_internal_standard]
    standards = [c for c in all_compounds if c.is_internal_standard]

    print()
    print("=" * 130)
    print(f"{'PFAS MRM Transition Table — Validated SOP Parameters (Waters Xevo TQD)':^130s}")
    print(f"{'BEH C18 2.1x50mm 1.7µm | 0.4 mL/min | 45°C | ESI(-) | 40 µL inj':^130s}")
    print("=" * 130)
    print(
        f"{'RT':>4s}  {'Compound':<13s}  {'Class':<6s}  "
        f"{'Quant (Q1>Q3)':^14s} {'Dwell':>5s} {'Cone':>4s} {'CE':>3s}  "
        f"{'Qual 1':^10s} {'CE':>3s}  "
        f"{'Qual 2':^10s} {'CE':>3s}  "
        f"{'IS Reference':<18s} {'MDL':>5s}"
    )
    print(
        f"{'min':>4s}  {'':<13s}  {'':<6s}  "
        f"{'':^14s} {'ms':>5s} {'V':>4s} {'eV':>3s}  "
        f"{'':^10s} {'eV':>3s}  "
        f"{'':^10s} {'eV':>3s}  "
        f"{'':<18s} {'ng/L':>5s}"
    )
    print("-" * 130)

    for c in analytes:
        rt = f"{c.retention_time_min:.1f}" if c.retention_time_min else "?"
        q = c.quantifier
        quals = [t for t in c.transitions if not t.is_quantifier]

        q_str = f"{q.precursor_mz:.0f} > {q.product_mz:.0f}" if q else "—"
        dwell = f"{q.dwell_time_ms:.0f}" if q else ""
        cone = f"{q.q1_pre_bias:.0f}" if q else ""
        ce = f"{q.collision_energy:.0f}" if q else ""

        qual1_str = f"{quals[0].precursor_mz:.0f} > {quals[0].product_mz:.0f}" if len(quals) > 0 else "—"
        qual1_ce = f"{quals[0].collision_energy:.0f}" if len(quals) > 0 else ""
        qual2_str = f"{quals[1].precursor_mz:.0f} > {quals[1].product_mz:.0f}" if len(quals) > 1 else ""
        qual2_ce = f"{quals[1].collision_energy:.0f}" if len(quals) > 1 else ""

        is_name = c.internal_standard or "—"
        mdl = f"{MDLS[c.abbreviation]:.2f}" if c.abbreviation in MDLS else ""

        print(
            f"{rt:>4s}  {c.abbreviation:<13s}  {c.compound_class:<6s}  "
            f"{q_str:>14s} {dwell:>5s} {cone:>4s} {ce:>3s}  "
            f"{qual1_str:>10s} {qual1_ce:>3s}  "
            f"{qual2_str:>10s} {qual2_ce:>3s}  "
            f"{is_name:<18s} {mdl:>5s}"
        )

    print("-" * 130)

    print()
    print(f"{'Internal Standards':^100s}")
    print("-" * 100)
    print(
        f"{'RT':>4s}  {'Compound':<22s}  "
        f"{'Quant (Q1>Q3)':^14s} {'Dwell':>5s} {'Cone':>4s} {'CE':>3s}  "
        f"{'Qual 1':^10s} {'CE':>3s}  "
        f"{'Qual 2':^10s} {'CE':>3s}"
    )
    print("-" * 100)

    for c in standards:
        rt = f"{c.retention_time_min:.1f}" if c.retention_time_min else "?"
        q = c.quantifier
        quals = [t for t in c.transitions if not t.is_quantifier]

        q_str = f"{q.precursor_mz:.0f} > {q.product_mz:.0f}" if q else "—"
        dwell = f"{q.dwell_time_ms:.0f}" if q else ""
        cone = f"{q.q1_pre_bias:.0f}" if q else ""
        ce = f"{q.collision_energy:.0f}" if q else ""

        qual1_str = f"{quals[0].precursor_mz:.0f} > {quals[0].product_mz:.0f}" if len(quals) > 0 else "—"
        qual1_ce = f"{quals[0].collision_energy:.0f}" if len(quals) > 0 else ""
        qual2_str = f"{quals[1].precursor_mz:.0f} > {quals[1].product_mz:.0f}" if len(quals) > 1 else ""
        qual2_ce = f"{quals[1].collision_energy:.0f}" if len(quals) > 1 else ""

        print(
            f"{rt:>4s}  {c.abbreviation:<22s}  "
            f"{q_str:>14s} {dwell:>5s} {cone:>4s} {ce:>3s}  "
            f"{qual1_str:>10s} {qual1_ce:>3s}  "
            f"{qual2_str:>10s} {qual2_ce:>3s}"
        )

    print("-" * 100)

    print()
    print("Gradient Program (from SOP Appendix 7.1):")
    print(f"  {'Time':>5s}  {'Flow':>5s}  {'%A (H2O)':>8s}  {'%C (MeOH)':>9s}  {'Curve':>5s}")
    print(f"  {'(min)':>5s}  {'mL/m':>5s}")
    gradient = [
        (0.00, 0.400, 75.0, 25.0, "Init"),
        (0.50, 0.400, 75.0, 25.0, "6"),
        (5.00, 0.400, 15.0, 85.0, "6"),
        (5.10, 0.400,  5.0, 95.0, "6"),
        (5.60, 0.400,  5.0, 95.0, "6"),
        (7.00, 0.400,  5.0, 95.0, "1"),
        (9.00, 0.400, 75.0, 25.0, "1"),
    ]
    for t, f, a, c_pct, curve in gradient:
        print(f"  {t:5.2f}  {f:5.3f}  {a:8.1f}  {c_pct:9.1f}  {curve:>5s}")

    print()
    print("Waters TQD Source Parameters:")
    print("  Capillary:           1.00 kV")
    print("  Source Temperature:  150 °C")
    print("  Desolvation Temp:    400 °C")
    print("  Cone Gas Flow:       30 L/hr")
    print("  Desolvation Gas:     800 L/hr")
    print("  Column Temperature:  45 °C")
    print("  Sample Temperature:  5 °C")
    print()
    print("Notes:")
    print("  - Cone voltage stored in q1_pre_bias field — NOT directly transferable to 8060")
    print("  - CE values will need re-optimization on 8060 (expect ~10-20% lower)")
    print("  - Dwell times shown are from TQD; 8060 can typically use shorter dwells")
    print("  - GenX (HFPO-DA) and ADONA retain estimated parameters (not in validated SOP)")
    print("  - PFTrDA IS ref is M2PFTeDA (SOP), not M2PFDoA (QAPP) — updated")
    print("  - PFHpS IS ref is M8PFOS (SOP), not M3PFHxS (earlier estimate) — updated")
    print("  - SOP calibration r² ≥ 0.99 (stricter than QAPP's 0.98)")


if __name__ == "__main__":
    main()
