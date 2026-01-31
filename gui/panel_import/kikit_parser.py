"""Parse KiKit configuration files."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class KiKitLayout:
    """Parsed KiKit panel layout configuration."""
    rows: int
    cols: int
    hspace_mm: float  # Horizontal spacing between boards
    vspace_mm: float  # Vertical spacing between boards
    
    # Frame settings (optional)
    frame_hspace_mm: Optional[float] = None
    frame_vspace_mm: Optional[float] = None
    
    # Fiducials (optional)
    has_fiducials: bool = False
    fiducial_hoffset_mm: Optional[float] = None
    fiducial_voffset_mm: Optional[float] = None
    
    # Tooling holes (optional)
    has_tooling: bool = False
    tooling_hoffset_mm: Optional[float] = None
    tooling_voffset_mm: Optional[float] = None
    
    @property
    def total_boards(self) -> int:
        return self.rows * self.cols


def parse_mm_value(value: str) -> float:
    """Parse a KiKit dimension string like '2.5mm' to float mm value."""
    if isinstance(value, (int, float)):
        return float(value)
    
    value = str(value).strip().lower()
    
    # Handle 'mm' suffix
    if value.endswith('mm'):
        return float(value[:-2])
    
    # Handle 'cm' suffix
    if value.endswith('cm'):
        return float(value[:-2]) * 10
    
    # Handle 'in' or 'inch' suffix
    if value.endswith('in'):
        return float(value[:-2]) * 25.4
    if value.endswith('inch'):
        return float(value[:-4]) * 25.4
    
    # Assume mm if no unit
    return float(value)


def parse_kikit_config(config_path: str | Path) -> KiKitLayout:
    """Parse a KiKit JSON configuration file.
    
    Args:
        config_path: Path to kikit-config.json or similar
        
    Returns:
        KiKitLayout with parsed settings
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If required fields are missing
    """
    config_path = Path(config_path)
    
    if not config_path.exists():
        raise FileNotFoundError(f"KiKit config not found: {config_path}")
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # Layout section is required
    layout = config.get('layout', {})
    
    if not layout:
        raise ValueError("KiKit config missing 'layout' section")
    
    # Parse required grid dimensions
    rows = int(layout.get('rows', 1))
    cols = int(layout.get('cols', 1))
    hspace = parse_mm_value(layout.get('hspace', '0mm'))
    vspace = parse_mm_value(layout.get('vspace', '0mm'))
    
    result = KiKitLayout(
        rows=rows,
        cols=cols,
        hspace_mm=hspace,
        vspace_mm=vspace,
    )
    
    # Parse optional framing settings
    framing = config.get('framing', {})
    if framing.get('type'):
        result.frame_hspace_mm = parse_mm_value(framing.get('hspace', '0mm'))
        result.frame_vspace_mm = parse_mm_value(framing.get('vspace', '0mm'))
    
    # Parse optional fiducials
    fiducials = config.get('fiducials', {})
    if fiducials.get('type'):
        result.has_fiducials = True
        result.fiducial_hoffset_mm = parse_mm_value(fiducials.get('hoffset', '0mm'))
        result.fiducial_voffset_mm = parse_mm_value(fiducials.get('voffset', '0mm'))
    
    # Parse optional tooling holes
    tooling = config.get('tooling', {})
    if tooling.get('type'):
        result.has_tooling = True
        result.tooling_hoffset_mm = parse_mm_value(tooling.get('hoffset', '0mm'))
        result.tooling_voffset_mm = parse_mm_value(tooling.get('voffset', '0mm'))
    
    return result
