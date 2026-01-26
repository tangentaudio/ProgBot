"""Programmer plugins registry.

This module provides a registry of available programmer plugins and
utilities for discovering and instantiating them.
"""

from .base import ProgrammerBase
from .nordic_nrf import NordicNrfProgrammer

# Registry of available programmer plugins
# Key is the programmer type ID used in panel settings
PROGRAMMER_REGISTRY = {
    'nordic_nrf': NordicNrfProgrammer,
}


def get_available_programmers() -> dict:
    """Get dictionary of available programmer types.
    
    Returns:
        Dict mapping type_id -> display_name
    """
    return {
        type_id: cls.name 
        for type_id, cls in PROGRAMMER_REGISTRY.items()
    }


def get_programmer_class(type_id: str) -> type:
    """Get programmer class by type ID.
    
    Args:
        type_id: Programmer type identifier (e.g., 'nordic_nrf')
        
    Returns:
        Programmer class (subclass of ProgrammerBase)
        
    Raises:
        KeyError: If type_id is not registered
    """
    return PROGRAMMER_REGISTRY[type_id]


def create_programmer(type_id: str, update_phase_callback, firmware_paths: dict = None):
    """Create a programmer instance.
    
    Args:
        type_id: Programmer type identifier
        update_phase_callback: Function to call to update phase display
        firmware_paths: Dict mapping slot_id -> file_path
        
    Returns:
        Programmer instance
    """
    cls = get_programmer_class(type_id)
    return cls(update_phase_callback, firmware_paths or {})


def get_default_programmer_config(type_id: str) -> dict:
    """Get default configuration for a programmer type.
    
    Args:
        type_id: Programmer type identifier
        
    Returns:
        Dict with 'type', 'steps', and 'firmware' keys
    """
    cls = get_programmer_class(type_id)
    
    steps = {step['id']: step['default'] for step in cls.get_steps()}
    firmware = {slot['id']: slot.get('default', '') for slot in cls.get_firmware_slots()}
    
    return {
        'type': type_id,
        'steps': steps,
        'firmware': firmware,
    }
