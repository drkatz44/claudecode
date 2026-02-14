"""PFAS compound database and MRM transition definitions."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class MRMTransition:
    """Single MRM transition for a compound."""

    precursor_mz: float  # Q1 m/z
    product_mz: float  # Q3 m/z
    collision_energy: float  # CE in volts
    is_quantifier: bool = True  # True = quantifier, False = qualifier
    dwell_time_ms: float = 100.0  # msec
    q1_pre_bias: float = 0.0  # Shimadzu-specific: Q1 pre-rod bias
    q3_pre_bias: float = 0.0  # Shimadzu-specific: Q3 pre-rod bias
    polarity: str = "negative"  # ESI polarity


@dataclass
class Compound:
    """PFAS compound with associated MRM transitions."""

    name: str
    abbreviation: str
    cas_number: str
    molecular_formula: str
    molecular_weight: float
    transitions: list[MRMTransition] = field(default_factory=list)
    retention_time_min: float | None = None  # expected RT (minutes)
    rt_window_min: float = 1.0  # RT window for MRM scheduling
    internal_standard: str | None = None  # abbreviation of associated IS
    is_internal_standard: bool = False
    compound_class: str = ""  # e.g., "PFCA", "PFSA", "precursor"

    @property
    def quantifier(self) -> MRMTransition | None:
        """Return the quantifier transition."""
        return next((t for t in self.transitions if t.is_quantifier), None)

    @property
    def qualifier(self) -> MRMTransition | None:
        """Return the first qualifier transition."""
        return next((t for t in self.transitions if not t.is_quantifier), None)


class CompoundDatabase:
    """Collection of PFAS compounds and their method parameters."""

    def __init__(self):
        self.compounds: dict[str, Compound] = {}

    def add(self, compound: Compound) -> None:
        self.compounds[compound.abbreviation] = compound

    def get(self, abbreviation: str) -> Compound | None:
        return self.compounds.get(abbreviation)

    @property
    def analytes(self) -> list[Compound]:
        """Return non-IS compounds."""
        return [c for c in self.compounds.values() if not c.is_internal_standard]

    @property
    def internal_standards(self) -> list[Compound]:
        """Return internal standard compounds."""
        return [c for c in self.compounds.values() if c.is_internal_standard]

    def save(self, path: Path) -> None:
        """Save compound database to YAML."""
        data = []
        for compound in self.compounds.values():
            entry = {
                "name": compound.name,
                "abbreviation": compound.abbreviation,
                "cas_number": compound.cas_number,
                "molecular_formula": compound.molecular_formula,
                "molecular_weight": compound.molecular_weight,
                "retention_time_min": compound.retention_time_min,
                "rt_window_min": compound.rt_window_min,
                "internal_standard": compound.internal_standard,
                "is_internal_standard": compound.is_internal_standard,
                "compound_class": compound.compound_class,
                "transitions": [
                    {
                        "precursor_mz": t.precursor_mz,
                        "product_mz": t.product_mz,
                        "collision_energy": t.collision_energy,
                        "is_quantifier": t.is_quantifier,
                        "dwell_time_ms": t.dwell_time_ms,
                        "q1_pre_bias": t.q1_pre_bias,
                        "q3_pre_bias": t.q3_pre_bias,
                        "polarity": t.polarity,
                    }
                    for t in compound.transitions
                ],
            }
            data.append(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump({"compounds": data}, f, default_flow_style=False, sort_keys=False)

    @classmethod
    def load(cls, path: Path) -> "CompoundDatabase":
        """Load compound database from YAML."""
        with open(path) as f:
            data = yaml.safe_load(f)

        db = cls()
        for entry in data["compounds"]:
            transitions = [
                MRMTransition(**t) for t in entry.pop("transitions", [])
            ]
            compound = Compound(**entry, transitions=transitions)
            db.add(compound)
        return db
