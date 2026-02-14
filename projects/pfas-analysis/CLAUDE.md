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

## Current Focus
1. Define compound database with MRM transitions from Waters method
2. Translate method parameters to Shimadzu 8060 format
3. Build data processing pipeline

## Notes
- ESI negative mode for most PFAS compounds
- Key differences Waters → Shimadzu: source parameter names, collision energy optimization, MRM dwell times
- LCMS-8060 uses UFsweeper III - generally higher sensitivity than TQD, CE values will need re-optimization
- LabSolutions data export format (ASCII/CSV) for data import
