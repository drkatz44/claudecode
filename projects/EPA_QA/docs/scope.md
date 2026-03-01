# Analytical Scope

## Contaminant Categories
- **Contaminants of Emerging Concern (CECs)** - PFAS, pharmaceuticals, microplastics, etc.
- **Contaminants of Immediate Concern** - site/project-specific priority analytes
- **Anthropogenic Tracers** - markers of human activity in environmental media
- **Legacy Contaminants** - PCBs, dioxins, etc.
- **Pesticides**
- **Metals**

## Environmental Matrices
- Wastewater
- Surface water
- Groundwater
- Sediments
- Tissues (biological)

## QA Framework

### QA Category Levels
- **Category A** - (requirements TBD - documentation pending)
- **Category B** - (requirements TBD - documentation pending)

Each category defines distinct requirements for:
- Documentation rigor
- QC sample frequency and types
- Data validation depth
- Reporting standards
- Acceptance criteria

### Core QA Workflow
1. Establish regulatory authority chain (CFR → Federal Register → EPA Orders → Office policies)
2. Ingest foundational docs (policies, procedures, QAPPs, SOPs)
3. Parse and cross-reference all QA requirements against regulatory authority
3. Map requirements to analytical methods and matrices
4. Build recursive checklist: what each result needs to pass audit
5. Pre-audit engine: evaluate results against QA category requirements before formal audit

### Pre-Audit Analysis Requirements
- Method-specific QC criteria (blanks, duplicates, spikes, surrogates, calibration)
- Holding times
- Sample handling and chain of custody
- Detection/reporting limit verification
- Data completeness
- Qualifier assignment
- Traceability to SOPs and QAPP specifications

## Key Deliverable
A system that takes analytical results and QA category designation (A or B),
cross-references against all applicable requirements from QAPPs/SOPs/policies,
and flags any gaps, nonconformances, or documentation deficiencies before formal audit.
