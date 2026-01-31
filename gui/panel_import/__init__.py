"""Panel import module for parsing KiCad/KiKit panel files.

Main entry point: PanelImportWizard from panel_import_wizard module.
"""

from .kikit_parser import parse_kikit_config, KiKitLayout
from .kicad_parser import (
    parse_kicad_pcb, extract_board_outline, detect_board_pitch,
    PanelInfo, BoardOutline, Point, GridPitch
)
from .panel_preview import PanelData, PanelPreviewWidget
from .panel_import_wizard import PanelImportWizard

__all__ = [
    # Main wizard
    'PanelImportWizard',
    
    # Data classes
    'PanelData',
    'PanelInfo',
    'BoardOutline',
    'GridPitch',
    'KiKitLayout',
    'Point',
    
    # Parsers
    'parse_kikit_config',
    'parse_kicad_pcb', 
    'extract_board_outline',
    'detect_board_pitch',
    
    # Widgets
    'PanelPreviewWidget',
]
