# Project: pfas-analysis

## Purpose
PFAS method adaptation (Waters TQD → Shimadzu LCMS-8060), data processing, and research reporting.

## Status
optimization

## Stack
Python (uv, pandas, pytest, ruff)

## Instrument Configuration
Shimadzu Nexera X2 / LCMS-8060 system:
- **Pumps**: 2× LC-20AD XR (binary gradient)
- **Autosampler**: SIL-30AC MP
- **Controller**: CBM-20A
- **Detector**: SPD-20A (DAD) + LCMS-8060 (triple quad MS/MS)
- **Column oven**: CTO-20A

## Source Method
- Originally developed on Waters TQD
- Method details available as PDF/paper
- Custom PFAS target list (not tied to specific EPA method)

## Key Files
- `src/pfas_analysis/method/` - compound database, MRM transitions, LC/MS parameters
- `src/pfas_analysis/processing/` - peak integration, calibration, quantitation
- `src/pfas_analysis/reporting/` - research report generation
- `data/methods/` - method parameter files (YAML)
- `data/raw/` - raw instrument data
- `data/processed/` - processed results

## Current State (2026-02)

### Standards
- **Native**: Wellington PFAC-24PAR (24 PFAS compounds)
- **Internal**: MPFAC-24ES (isotope-labeled)

### Key Insight
Shimadzu 8060 MRM optimization via **sequential injection**, not direct infusion.

### Current Focus
- Dwell time optimization (currently 20ms)
- RT window tightening for more data points per peak
- Delay column not yet installed
- No system contamination observed yet

### Next Steps
1. Complete MRM optimization for all 24 compounds
2. Validate with calibration curve
3. Build data processing pipeline

## Notes
- ESI negative mode for most PFAS compounds
- Key differences Waters → Shimadzu: source parameter names, collision energy optimization, MRM dwell times
- LCMS-8060 uses UFsweeper III - generally higher sensitivity than TQD, CE values will need re-optimization
- LabSolutions data export format (ASCII/CSV) for data import
