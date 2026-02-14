# Instrument Session Checklist

## Priority 1: Re-optimize Boundary Warning Compounds

Widen CE search scope by 10-15 V and re-run for these compounds:
- [ ] PFNS (#35) — CE boundary on both channels (quant CE=50, qual CE=45)
- [ ] PFPeS (#11, batch 1) — qualifier CE boundary
- [ ] M3PFHxS-13C3 (#15, batch 1) — qualifier CE boundary
- [ ] 8:2-FTS (#25, batch 1) — qualifier CE boundary
- [ ] MeFOSAA-d3 (#41) — quant CE boundary (CE=20, detail selected boundary at 20)
- [ ] Export OptimizeResult text file to external SSD

### Evaluate weak/dead transitions
Verify these are usable or drop them:
- [ ] M8FOSA 506→172 (qual): ALL ZEROS in CE scan — consider dropping (IS only needs quantifier)
- [ ] FOSA 498→119 (qual): max 111 counts — marginal
- [ ] FOSA 498→169 (qual): max 67 counts — marginal
- [ ] MeFOSAA-d3 573→483 (qual): all zeros
- [ ] MeFOSAA-d3 573→515 (qual): max 111 counts — marginal

## Priority 2: Enter Method into LabSolutions

- [ ] Open optimized method file in LabSolutions
- [ ] Update MRM table with all optimized CE, Q1 Pre Bias, Q3 Pre Bias values from compounds.yaml
- [ ] Set dwell times (currently 5-6 ms — review total cycle time vs concurrent MRMs)
- [ ] Set RT windows wide initially (1.0 min) since RTs are from SOP, not measured
- [ ] Verify LC gradient program is entered
- [ ] Set source parameters: interface voltage, DL temp, heat block temp, nebulizing gas, drying gas

## Priority 3: First Column Run — Establish Retention Times

- [ ] Install analytical column (if not already)
- [ ] Condition column: 5-10 min flush at initial gradient conditions
- [ ] Inject PFAC-24PAR + MPFAC-24ES mix at mid-level concentration
- [ ] Run full gradient
- [ ] Identify all peaks — record actual retention times
- [ ] Evaluate peak shapes (tailing, splitting, broadening)
- [ ] Export data and bring back RTs to update compounds.yaml

## Priority 4: System Blank Evaluation

- [ ] Run solvent blank (mobile phase only) — isolate LC system contamination
- [ ] Run reagent/procedural blank — check vials, pipettes, mobile phase bottles
- [ ] Evaluate for PFOA, PFOS, PFHxS, PFHxA (common lab contaminants)
- [ ] **Install delay column** between pump and injector if blanks show contamination
- [ ] Re-run blank after delay column to confirm cleanup
- [ ] Check carryover: run blank after highest-level standard

## Priority 5: Method Refinement

- [ ] Tighten RT windows based on measured RTs (aim for +/- 0.3 min)
- [ ] Recalculate dwell times with tighter windows to maximize points per peak
- [ ] Verify ion ratios (qualifier/quantifier) are consistent across concentration levels
- [ ] Run duplicate injections to check reproducibility

## Priority 6: Calibration

- [ ] Prepare calibration standards (7+ levels spanning expected range)
- [ ] Run calibration curve
- [ ] Evaluate linearity (r² > 0.99, or 1/x weighted regression if needed)
- [ ] Run second source / independent check standard (ICV) to verify calibration
- [ ] Check carryover: blank after highest calibrator

## Priority 7: Method Validation

### MDL Study
- [ ] Prepare 7+ replicates at low concentration (near estimated detection limit)
- [ ] Analyze replicates
- [ ] Calculate MDL = t(n-1, 0.99) x standard deviation

### Accuracy & Precision
- [ ] Laboratory fortified blank (LFB): spike known amount into clean matrix, measure recovery
- [ ] Target recovery: 70-130% for each analyte
- [ ] Replicate precision: RSD < 20%

### QC Protocol
- [ ] Define run sequence: Cal → ICV → Method blank → LFB → Samples → CCV
- [ ] Set CCV frequency (every 10-20 samples)
- [ ] Set CCV acceptance criteria (80-120% of expected)
- [ ] Set method blank acceptance criteria (< 1/3 reporting limit)

### Matrix Evaluation (if applicable)
- [ ] Matrix spike / matrix spike duplicate (MS/MSD) for target sample type
- [ ] Evaluate matrix effects (ion suppression/enhancement)

---

## Supplies Needed
- [ ] PFAC-24PAR native standard mix (Wellington)
- [ ] MPFAC-24ES internal standard mix (Wellington)
- [ ] Second source standard for ICV (different lot or vendor)
- [ ] LC-MS grade methanol and water
- [ ] Ammonium acetate (for mobile phase, if method uses it)
- [ ] Polypropylene vials and labware (PFAS adsorb to glass)
- [ ] Delay column (C18 or similar, for between pump and injector)

## Files to Bring Back
After each session, copy to external SSD for import:
- [ ] OptimizeResult .txt files (for any re-optimizations)
- [ ] .lcd data files from standard/blank runs
- [ ] Export MRM table from final method as .txt
- [ ] Calibration results export
