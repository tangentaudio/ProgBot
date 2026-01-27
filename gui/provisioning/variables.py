"""Variable substitution for provisioning commands.

Handles {variable} substitution in command templates, with support
for multiple variable sources and a defined resolution order.
"""

import re
import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Pattern to match {variable_name} in templates
VARIABLE_PATTERN = re.compile(r'\{(\w+)\}')


def get_system_variables(row: int, col: int, panel_name: str) -> dict:
    """Get system-provided variables (always available).
    
    Args:
        row: Board row index (0-based)
        col: Board column index (0-based)
        panel_name: Current panel name
        
    Returns:
        Dictionary of system variable names to values
    """
    now = datetime.now()
    
    return {
        'row': str(row),
        'col': str(col),
        'cell_id': f"R{row}C{col}",
        'timestamp': now.isoformat(),
        'date': now.strftime('%Y-%m-%d'),
        'time': now.strftime('%H:%M:%S'),
        'panel_name': panel_name,
    }


def merge_variable_sources(
    system_vars: dict,
    vision_vars: Optional[dict] = None,
    custom_vars: Optional[dict] = None,
    captured_vars: Optional[dict] = None
) -> dict:
    """Merge variable sources with defined resolution order.
    
    Resolution order (highest priority first):
    1. Script-captured values (most recent)
    2. Vision-provided values (QR scan data)
    3. Panel-defined custom variables
    4. System-provided values (lowest priority)
    
    Args:
        system_vars: System variables (row, col, timestamp, etc.)
        vision_vars: Variables from QR scanning (serial_number, qr_raw)
        custom_vars: Panel-defined custom variables
        captured_vars: Variables captured during script execution
        
    Returns:
        Merged dictionary with all variables
    """
    result = {}
    
    # Add in priority order (lowest first, so higher priority overwrites)
    result.update(system_vars)
    
    if custom_vars:
        result.update(custom_vars)
    
    if vision_vars:
        result.update(vision_vars)
    
    if captured_vars:
        result.update(captured_vars)
    
    return result


def substitute_variables(template: str, variables: dict) -> tuple[str, list[str]]:
    """Replace {variable} placeholders in a template string.
    
    Args:
        template: String containing {variable} placeholders
        variables: Dictionary of variable names to values
        
    Returns:
        Tuple of (substituted_string, list_of_missing_variables)
    """
    missing = []
    
    def replace(match: re.Match) -> str:
        var_name = match.group(1)
        if var_name in variables:
            value = variables[var_name]
            # Convert to string if needed
            if not isinstance(value, str):
                value = str(value)
            return value
        else:
            missing.append(var_name)
            logger.warning(f"Missing variable: {{{var_name}}}")
            # Leave the placeholder in place so it's obvious
            return match.group(0)
    
    result = VARIABLE_PATTERN.sub(replace, template)
    return (result, missing)


def extract_variable_names(template: str) -> list[str]:
    """Extract all variable names referenced in a template.
    
    Args:
        template: String containing {variable} placeholders
        
    Returns:
        List of variable names (without braces)
    """
    return VARIABLE_PATTERN.findall(template)


def validate_variables(
    template: str,
    available_vars: dict,
    allow_capture_vars: bool = True
) -> tuple[bool, list[str]]:
    """Validate that all variables in a template are available.
    
    Args:
        template: String containing {variable} placeholders
        available_vars: Dictionary of available variable names to values
        allow_capture_vars: If True, don't flag variables that might
            be captured in earlier steps (can't validate statically)
            
    Returns:
        Tuple of (is_valid, list_of_unknown_variables)
    """
    var_names = extract_variable_names(template)
    unknown = [name for name in var_names if name not in available_vars]
    
    # If we allow capture vars, we can't fully validate statically
    # since variables might be captured during execution
    if allow_capture_vars:
        return (True, unknown)  # Return unknown as warnings, not errors
    
    return (len(unknown) == 0, unknown)


class VariableContext:
    """Manages variables for a provisioning session.
    
    Provides a convenient interface for building up the variable
    context as a script executes, with captures accumulating.
    """
    
    def __init__(
        self,
        row: int,
        col: int,
        panel_name: str,
        vision_vars: Optional[dict] = None,
        custom_vars: Optional[dict] = None
    ):
        """Initialize the variable context.
        
        Args:
            row: Board row index
            col: Board column index
            panel_name: Panel name
            vision_vars: Variables from vision/QR scanning
            custom_vars: Panel-defined custom variables
        """
        self.system_vars = get_system_variables(row, col, panel_name)
        self.vision_vars = vision_vars or {}
        self.custom_vars = custom_vars or {}
        self.captured_vars: dict = {}
    
    def add_captures(self, captures: dict) -> None:
        """Add captured variables from a step result.
        
        Args:
            captures: Dictionary of captured variable names to values
        """
        self.captured_vars.update(captures)
    
    def get_all(self) -> dict:
        """Get merged dictionary of all variables."""
        return merge_variable_sources(
            self.system_vars,
            self.vision_vars,
            self.custom_vars,
            self.captured_vars
        )
    
    def substitute(self, template: str) -> tuple[str, list[str]]:
        """Substitute variables in a template.
        
        Args:
            template: String with {variable} placeholders
            
        Returns:
            Tuple of (substituted_string, missing_variables)
        """
        return substitute_variables(template, self.get_all())
    
    @property
    def all_captures(self) -> dict:
        """Get all captured variables."""
        return dict(self.captured_vars)
