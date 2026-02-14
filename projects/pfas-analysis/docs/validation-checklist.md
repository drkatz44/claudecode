# PFAS Method Validation Checklist
## Shimadzu Nexera X2 / LCMS-8060

**Standards:** Wellington PFAC-24PAR (native) / MPFAC-24ES (internal standards)

---

## 1. Method Optimization (Shimadzu-Specific)

### 1.1 MRM Optimization

> **Note:** Shimadzu 8060 optimization is performed by **sequential injection** (flow injection or on-column), not direct infusion. Use LabSolutions optimization wizard with repeated injections at varying CE/voltages.

- [ ] Inject each compound to confirm precursor ion [M-H]- or [M-F]-
- [ ] Optimize product ions (select quantifier + qualifier)
- [ ] Optimize collision energy (CE) for each transition via sequential injection
- [ ] Optimize Q1 pre-bias voltage
- [ ] Optimize Q3 pre-bias voltage
- [ ] Set appropriate polarity (negative for most PFAS)

### 1.2 Source Parameter Optimization
- [ ] Interface temperature (typical: 300°C)
- [ ] DL (desolvation line) temperature (typical: 250°C)
- [ ] Heat block temperature (typical: 400°C)
- [ ] Nebulizing gas flow (typical: 3 L/min)
- [ ] Drying gas flow (typical: 10 L/min)
- [ ] Heating gas flow (typical: 10 L/min)
- [ ] Interface voltage (start with tune file, optimize if needed)

### 1.3 Acquisition Optimization
- [ ] Dwell time optimization (balance S/N vs points per peak)
- [ ] Calculate cycle time: (dwell × concurrent transitions) + pause times
- [ ] Verify ≥15-20 data points across each peak
- [ ] Set pause time (default 3 ms typically fine)
- [ ] Configure timed MRM / RT windows
- [ ] Minimize concurrent transitions per time segment
- [ ] Verify loop time in method

### 1.4 LC Optimization
- [ ] Column selection (C18 or specific PFAS column)
- [ ] Mobile phase optimization (typically 2-5 mM ammonium acetate)
- [ ] Gradient optimization for peak separation
- [ ] Flow rate optimization
- [ ] Column temperature optimization
- [ ] Injection volume optimization

### 1.5 System Configuration
- [ ] Install delay column (isolator column) to separate system PFAS
- [ ] Replace/minimize PTFE tubing
- [ ] Check LC system for PFAS contamination sources
- [ ] Configure needle wash program

---

## 2. System Validation

### 2.1 Instrument Qualification
- [ ] Tune file current (within 1 month or per SOP)
- [ ] Mass calibration verified (±0.2 Da)
- [ ] Resolution check (unit resolution on both quads)
- [ ] Sensitivity check with tuning standard

### 2.2 System Suitability (run before each batch)
- [ ] Retention time stability (±0.2 min from expected)
- [ ] Peak shape acceptable (tailing factor 0.8-1.5)
- [ ] IS area consistency (RSD <20% across batch)
- [ ] Signal-to-noise meets requirements
- [ ] Blank shows no carryover or contamination

### 2.3 Carryover Assessment
- [ ] Inject high standard followed by blank
- [ ] Carryover <20% of LOQ for all analytes
- [ ] Determine if additional blank injections needed
- [ ] Optimize needle wash if carryover observed

### 2.4 Contamination Check
- [ ] Solvent blank (MeOH or injection solvent)
- [ ] Reagent blank (all reagents, no sample)
- [ ] Instrument blank (no injection)
- [ ] Identify and quantify any system PFAS background
- [ ] Verify delay column separates system peaks from analytes

---

## 3. Method Validation

### 3.1 Selectivity / Specificity
- [ ] No interfering peaks at analyte RTs in blank matrix
- [ ] Qualifier/quantifier ion ratio within ±30% of standard
- [ ] IS transitions free from interference
- [ ] Matrix blank from representative sources tested

### 3.2 Calibration / Linearity
- [ ] Minimum 5-point calibration curve
- [ ] Calibration range covers expected sample concentrations
- [ ] Linear regression r² ≥ 0.99 (or per method requirements)
- [ ] Back-calculated concentrations within ±20% (±25% at LOQ)
- [ ] Residuals randomly distributed
- [ ] Weighting evaluated (1/x, 1/x² if needed)

### 3.3 Sensitivity
- [ ] LOD determined (S/N ≥ 3 or statistical method)
- [ ] LOQ determined (S/N ≥ 10, precision ≤20% RSD, accuracy ±20%)
- [ ] IDL/MDL calculated per EPA guidelines if required
- [ ] Reporting limits established

### 3.4 Accuracy (Recovery)
- [ ] Spike matrix at low, mid, high levels (minimum)
- [ ] Recovery 70-130% (or per method requirements)
- [ ] Recovery consistent across matrices
- [ ] IS recovery tracked

### 3.5 Precision
- [ ] Repeatability: n≥5 replicates same day, RSD ≤15% (≤20% at LOQ)
- [ ] Intermediate precision: different days/analysts, RSD ≤20%
- [ ] Reproducibility (if multi-lab): RSD documented

### 3.6 Matrix Effects
- [ ] Compare response in solvent vs post-extraction spike
- [ ] Matrix effect (%) calculated for each analyte class
- [ ] IS compensation evaluated
- [ ] Matrix-matched calibration if needed

### 3.7 Stability
- [ ] Autosampler stability (sample queue duration)
- [ ] Extract stability (24h, 48h, 7d as needed)
- [ ] Freeze-thaw stability (3 cycles)
- [ ] Stock solution stability
- [ ] Working solution stability

### 3.8 Robustness (optional)
- [ ] Small variations in mobile phase pH
- [ ] Small variations in column temperature
- [ ] Small variations in flow rate
- [ ] Different column lot

---

## 4. QC Requirements (Per Batch)

- [ ] Calibration standards (beginning, end, or per SOP)
- [ ] Method blank (minimum 1 per 20 samples)
- [ ] Laboratory control sample / spike (1 per 20 samples)
- [ ] Matrix spike / matrix spike duplicate (1 per 20 samples)
- [ ] Continuing calibration verification (every 10-12 samples)
- [ ] IS present in all samples and standards

---

## 5. Documentation

- [ ] Method SOP written and approved
- [ ] Validation report complete
- [ ] Instrument logbook entries
- [ ] Training records for analysts
- [ ] Raw data archived

---

## Notes

| Date | Note |
|------|------|
| | |

