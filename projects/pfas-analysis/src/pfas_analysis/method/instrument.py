"""Shimadzu LCMS-8060 instrument method parameters."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class GradientStep:
    """Single step in the LC gradient program."""

    time_min: float
    percent_b: float
    flow_ml_min: float = 0.4


@dataclass
class LCMethod:
    """LC method parameters for Nexera X2 system."""

    # Column
    column_name: str = ""
    column_dimensions: str = ""  # e.g., "2.1 x 100 mm"
    particle_size_um: float = 0.0
    column_temp_c: float = 40.0

    # Mobile phases
    mobile_phase_a: str = "2 mM ammonium acetate in water"
    mobile_phase_b: str = "methanol"

    # Gradient
    gradient: list[GradientStep] = field(default_factory=list)
    total_flow_ml_min: float = 0.4

    # Injection
    injection_volume_ul: float = 10.0
    needle_wash_solvent: str = "50:50 MeOH:water"

    # Autosampler (SIL-30AC MP)
    cooler_temp_c: float = 4.0
    rinse_mode: str = "before and after aspiration"


@dataclass
class MSMethod:
    """MS method parameters for LCMS-8060 triple quad."""

    # Interface / source
    ionization_mode: str = "ESI"
    polarity: str = "negative"
    nebulizing_gas_flow_l_min: float = 3.0
    drying_gas_flow_l_min: float = 10.0
    heating_gas_flow_l_min: float = 10.0
    interface_temp_c: float = 300.0
    dl_temp_c: float = 250.0  # desolvation line
    heat_block_temp_c: float = 400.0
    interface_voltage_kv: float = 4.0  # capillary voltage

    # Acquisition
    acquisition_mode: str = "MRM"
    mrm_optimization: str = "compound"  # compound vs event-based
    pause_time_ms: float = 3.0
    loop_time_ms: float | None = None  # auto-calculated if None


@dataclass
class InstrumentMethod:
    """Complete instrument method combining LC and MS parameters."""

    name: str = ""
    lc: LCMethod = field(default_factory=LCMethod)
    ms: MSMethod = field(default_factory=MSMethod)

    def save(self, path: Path) -> None:
        """Save method to YAML."""
        data = {
            "method_name": self.name,
            "lc": {
                "column": {
                    "name": self.lc.column_name,
                    "dimensions": self.lc.column_dimensions,
                    "particle_size_um": self.lc.particle_size_um,
                    "temperature_c": self.lc.column_temp_c,
                },
                "mobile_phases": {
                    "a": self.lc.mobile_phase_a,
                    "b": self.lc.mobile_phase_b,
                },
                "gradient": [
                    {
                        "time_min": s.time_min,
                        "percent_b": s.percent_b,
                        "flow_ml_min": s.flow_ml_min,
                    }
                    for s in self.lc.gradient
                ],
                "injection_volume_ul": self.lc.injection_volume_ul,
                "autosampler": {
                    "cooler_temp_c": self.lc.cooler_temp_c,
                    "rinse_mode": self.lc.rinse_mode,
                    "needle_wash_solvent": self.lc.needle_wash_solvent,
                },
            },
            "ms": {
                "ionization_mode": self.ms.ionization_mode,
                "polarity": self.ms.polarity,
                "source": {
                    "nebulizing_gas_flow_l_min": self.ms.nebulizing_gas_flow_l_min,
                    "drying_gas_flow_l_min": self.ms.drying_gas_flow_l_min,
                    "heating_gas_flow_l_min": self.ms.heating_gas_flow_l_min,
                    "interface_temp_c": self.ms.interface_temp_c,
                    "dl_temp_c": self.ms.dl_temp_c,
                    "heat_block_temp_c": self.ms.heat_block_temp_c,
                    "interface_voltage_kv": self.ms.interface_voltage_kv,
                },
                "acquisition": {
                    "mode": self.ms.acquisition_mode,
                    "mrm_optimization": self.ms.mrm_optimization,
                    "pause_time_ms": self.ms.pause_time_ms,
                },
            },
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    @classmethod
    def load(cls, path: Path) -> "InstrumentMethod":
        """Load method from YAML."""
        with open(path) as f:
            data = yaml.safe_load(f)

        lc_data = data.get("lc", {})
        ms_data = data.get("ms", {})
        col = lc_data.get("column", {})
        phases = lc_data.get("mobile_phases", {})
        autosampler = lc_data.get("autosampler", {})
        source = ms_data.get("source", {})
        acq = ms_data.get("acquisition", {})

        gradient = [GradientStep(**s) for s in lc_data.get("gradient", [])]

        lc = LCMethod(
            column_name=col.get("name", ""),
            column_dimensions=col.get("dimensions", ""),
            particle_size_um=col.get("particle_size_um", 0.0),
            column_temp_c=col.get("temperature_c", 40.0),
            mobile_phase_a=phases.get("a", ""),
            mobile_phase_b=phases.get("b", ""),
            gradient=gradient,
            injection_volume_ul=lc_data.get("injection_volume_ul", 10.0),
            cooler_temp_c=autosampler.get("cooler_temp_c", 4.0),
            rinse_mode=autosampler.get("rinse_mode", ""),
            needle_wash_solvent=autosampler.get("needle_wash_solvent", ""),
        )

        ms = MSMethod(
            ionization_mode=ms_data.get("ionization_mode", "ESI"),
            polarity=ms_data.get("polarity", "negative"),
            nebulizing_gas_flow_l_min=source.get("nebulizing_gas_flow_l_min", 3.0),
            drying_gas_flow_l_min=source.get("drying_gas_flow_l_min", 10.0),
            heating_gas_flow_l_min=source.get("heating_gas_flow_l_min", 10.0),
            interface_temp_c=source.get("interface_temp_c", 300.0),
            dl_temp_c=source.get("dl_temp_c", 250.0),
            heat_block_temp_c=source.get("heat_block_temp_c", 400.0),
            interface_voltage_kv=source.get("interface_voltage_kv", 4.0),
            acquisition_mode=acq.get("mode", "MRM"),
            mrm_optimization=acq.get("mrm_optimization", "compound"),
            pause_time_ms=acq.get("pause_time_ms", 3.0),
        )

        return cls(name=data.get("method_name", ""), lc=lc, ms=ms)
