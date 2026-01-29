"""Board Status Module - Centralized status definitions and utilities.

This module consolidates all board status-related code including:
- Status enums (VisionStatus, ProbeStatus, ProgramStatus, ProvisionStatus, TestStatus)
- BoardStatus class with status tracking
- BoardInfo class for collected board data
- Status color mapping
- Status symbol mapping (dots, spinners)

Used by: sequence.py, gridcell.py, board_detail_popup.py, kvui.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List, Tuple

from logger import get_logger

log = get_logger(__name__)


# =============================================================================
# Status Enums
# =============================================================================

class VisionStatus(Enum):
    """Status of the vision/QR scanning operation."""
    IDLE = "Pending"
    IN_PROGRESS = "Scanning"
    PASSED = "QR OK"
    FAILED = "QR Failed"
    SKIPPED = "Skipped"


class ProbeStatus(Enum):
    """Status of the probing operation."""
    IDLE = "Pending"
    PROBING = "Probing"
    PASSED = "Contact OK"
    FAILED = "Contact Failed"
    SKIPPED = "Skipped"
    INTERRUPTED = "Interrupted"


class ProgramStatus(Enum):
    """Status of the programming operation."""
    IDLE = "Pending"
    PROGRAMMING = "Programming"
    IDENTIFYING = "Identifying"
    IDENTIFIED = "Identified"
    COMPLETED = "Programmed"
    FAILED = "Program Failed"
    SKIPPED = "Skipped"
    INTERRUPTED = "Interrupted"


class ProvisionStatus(Enum):
    """Status of the provisioning operation."""
    IDLE = "Pending"
    PROVISIONING = "Provisioning"
    COMPLETED = "Provisioned"
    FAILED = "Provision Failed"
    SKIPPED = "Skipped"
    INTERRUPTED = "Interrupted"


class TestStatus(Enum):
    """Status of the testing operation."""
    IDLE = "Pending"
    TESTING = "Testing"
    COMPLETED = "Tested"
    FAILED = "Test Failed"
    SKIPPED = "Skipped"
    INTERRUPTED = "Interrupted"


# =============================================================================
# Status Visual Mappings
# =============================================================================

# Background colors for board status (RGBA 0-1)
STATUS_COLORS = {
    # Disabled/skipped
    'disabled': [0, 0, 0, 1],  # Black
    'interrupted': [1, 0.5, 0, 1],  # Orange
    
    # Completion states (green variants)
    'test_completed': [0, 0.8, 0, 1],  # Bright green
    'provision_completed': [0, 0.6, 0, 1],  # Medium green
    'program_completed': [0, 0.5, 0, 1],  # Dark green
    'identified': [1, 0, 1, 1],  # Purple (identify-only mode)
    'vision_passed': [0, 0.7, 0.7, 1],  # Teal
    
    # Failure states (red variants)
    'failed': [1, 0, 0, 1],  # Red
    'vision_failed': [0.5, 0, 0, 1],  # Dark red
    'skipped': [1, 0, 0, 1],  # Red (soft skip due to error)
    
    # In-progress states
    'testing': [0, 1, 1, 1],  # Cyan
    'provisioning': [0.5, 1, 0.5, 1],  # Light green
    'programming': [1, 1, 0, 1],  # Yellow
    'probing': [0, 1, 1, 1],  # Cyan
    'scanning': [0.5, 0.5, 1, 1],  # Light blue
    
    # Default
    'pending': [0.5, 0.5, 0.5, 1],  # Mid-gray
}

# Status dot symbols
DOT_PASS = "☑"
DOT_FAIL = "☒"
DOT_PENDING = "☐"
DOT_DISABLED = "·"

# Braille spinner frames for in-progress animation
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Status names that indicate "in progress"
IN_PROGRESS_STATUSES = frozenset([
    "IN_PROGRESS", "PROBING", "PROGRAMMING", "IDENTIFYING", "PROVISIONING", "TESTING"
])

# Status names that indicate "passed/completed"
PASSED_STATUSES = frozenset([
    "PASSED", "COMPLETED", "IDENTIFIED"
])


# =============================================================================
# Utility Functions
# =============================================================================

def status_to_dot(status_name: str, enabled: bool, spinner_index: int = 0) -> Tuple[str, bool]:
    """Convert a status name to a dot symbol and spinning flag.
    
    Args:
        status_name: The status enum name (e.g., "COMPLETED", "FAILED")
        enabled: Whether this phase is enabled
        spinner_index: Current spinner frame index (for in-progress animation)
        
    Returns:
        Tuple of (dot_symbol, is_spinning)
    """
    if not enabled:
        return (DOT_DISABLED, False)
    elif status_name in PASSED_STATUSES:
        return (DOT_PASS, False)
    elif status_name == "FAILED":
        return (DOT_FAIL, False)
    elif status_name in IN_PROGRESS_STATUSES:
        return (SPINNER_FRAMES[spinner_index % len(SPINNER_FRAMES)], True)
    elif status_name in ("IDLE", "PENDING", "SKIPPED"):
        return (DOT_PENDING, False)
    else:
        return (DOT_PENDING, False)


def get_phase_color(status_name: str) -> List[float]:
    """Get RGBA color for a phase status (used in detail popup).
    
    Args:
        status_name: The status enum name
        
    Returns:
        RGBA color list [r, g, b, a] with values 0-1
    """
    if status_name in PASSED_STATUSES:
        return [0.3, 0.8, 0.3, 1]  # Green
    elif status_name == "FAILED":
        return [0.9, 0.3, 0.3, 1]  # Red
    elif status_name in IN_PROGRESS_STATUSES or status_name in ("RUNNING", "CAPTURING"):
        return [0.3, 0.6, 1, 1]  # Blue
    elif status_name == "SKIPPED":
        return [0.6, 0.6, 0.6, 1]  # Gray
    else:
        return [0.8, 0.8, 0.8, 1]  # Light gray (idle/pending)


def get_status_bg_color(board_status) -> List[float]:
    """Determine background color for a GridCell based on BoardStatus.
    
    Priority order: disabled > interrupted > completed states > 
                   failures > soft skips > in-progress > defaults
    
    Args:
        board_status: BoardStatus instance
        
    Returns:
        RGBA color list [r, g, b, a] with values 0-1
    """
    if not board_status.enabled:
        return STATUS_COLORS['disabled']
    
    # Check for interrupted states
    if any(getattr(board_status, attr).name == "INTERRUPTED" 
           for attr in ('program_status', 'probe_status', 'provision_status', 'test_status')):
        return STATUS_COLORS['interrupted']
    
    # Check completion states (highest priority completions first)
    if board_status.test_status.name == "COMPLETED":
        return STATUS_COLORS['test_completed']
    if board_status.provision_status.name == "COMPLETED":
        return STATUS_COLORS['provision_completed']
    if board_status.program_status.name == "IDENTIFIED":
        return STATUS_COLORS['identified']
    if board_status.program_status.name == "COMPLETED":
        return STATUS_COLORS['program_completed']
    
    # Check failure states
    if board_status.test_status.name == "FAILED":
        return STATUS_COLORS['failed']
    if board_status.provision_status.name == "FAILED":
        return STATUS_COLORS['failed']
    if board_status.program_status.name == "FAILED":
        return STATUS_COLORS['failed']
    if board_status.probe_status.name == "FAILED":
        return STATUS_COLORS['failed']
    if board_status.vision_status.name == "FAILED":
        return STATUS_COLORS['vision_failed']
    
    # Check soft skips (error occurred, remaining phases skipped)
    if any(getattr(board_status, attr).name == "SKIPPED" 
           for attr in ('program_status', 'probe_status', 'provision_status', 'test_status')):
        return STATUS_COLORS['skipped']
    
    # Check in-progress states
    if board_status.test_status.name == "TESTING":
        return STATUS_COLORS['testing']
    if board_status.provision_status.name == "PROVISIONING":
        return STATUS_COLORS['provisioning']
    if board_status.program_status.name in ("PROGRAMMING", "IDENTIFYING"):
        return STATUS_COLORS['programming']
    if board_status.probe_status.name == "PROBING":
        return STATUS_COLORS['probing']
    if board_status.vision_status.name == "IN_PROGRESS":
        return STATUS_COLORS['scanning']
    
    # Vision passed but nothing else done yet
    if board_status.vision_status.name == "PASSED":
        return STATUS_COLORS['vision_passed']
    
    # Default
    return STATUS_COLORS['pending']


def is_processing(board_status) -> bool:
    """Check if a board is currently being processed (any phase in progress).
    
    Args:
        board_status: BoardStatus instance
        
    Returns:
        True if any phase is in progress
    """
    return (
        board_status.vision_status.name == "IN_PROGRESS" or
        board_status.probe_status.name == "PROBING" or
        board_status.program_status.name in ("PROGRAMMING", "IDENTIFYING") or
        board_status.provision_status.name == "PROVISIONING" or
        board_status.test_status.name == "TESTING"
    )


def has_failure(board_status) -> bool:
    """Check if any phase has failed.
    
    Args:
        board_status: BoardStatus instance
        
    Returns:
        True if any phase failed
    """
    return (
        board_status.vision_status.name == "FAILED" or
        board_status.probe_status.name == "FAILED" or
        board_status.program_status.name == "FAILED" or
        board_status.provision_status.name == "FAILED" or
        board_status.test_status.name == "FAILED"
    )


def all_phases_passed(board_status, enabled_phases: Dict[str, bool]) -> bool:
    """Check if all enabled phases have passed.
    
    Args:
        board_status: BoardStatus instance
        enabled_phases: Dict of phase_name -> is_enabled
        
    Returns:
        True if all enabled phases completed successfully
    """
    if enabled_phases.get('vision', True):
        if board_status.vision_status.name not in ("PASSED", "COMPLETED"):
            return False
    if enabled_phases.get('program', True):
        if board_status.program_status.name not in ("COMPLETED", "IDENTIFIED"):
            return False
    if enabled_phases.get('provision', False):
        if board_status.provision_status.name != "COMPLETED":
            return False
    if enabled_phases.get('test', False):
        if board_status.test_status.name != "COMPLETED":
            return False
    return True


# =============================================================================
# Data Classes
# =============================================================================

class BoardInfo:
    """Information collected about an individual board."""
    
    def __init__(self, serial_number: Optional[str] = None):
        """Initialize board information."""
        self.serial_number: Optional[str] = serial_number  # Scanned from QR code
        self.qr_image: Optional[bytes] = None  # Cropped QR image as PNG bytes
        self.test_data: dict = {}  # Testing phase data (key-value pairs)
        self.position: Optional[tuple] = None  # (col, row) position in panel
        self.timestamp_qr_scan: Optional[str] = None  # When QR was scanned
        self.timestamp_probe: Optional[str] = None  # When probing completed
        self.timestamp_program: Optional[str] = None  # When programming completed
        self.probe_result: Optional[bool] = None  # True if probing passed
        self.program_result: Optional[bool] = None  # True if programming passed
        self.notes: str = ""  # Any additional notes or error messages
        
        # Phase logs for detail display
        self.vision_log: list = []  # Log entries from vision phase
        self.probe_log: list = []   # Log entries from probe phase
        self.program_log: list = [] # Log entries from programming phase
        self.provision_log: list = []  # Log entries from provisioning phase
        self.test_log: list = []    # Log entries from test phase
        
        # Device info captured during programming
        self.device_id: Optional[str] = None  # Chip ID or device identifier
        self.firmware_version: Optional[str] = None  # Flashed firmware version
    
    def to_dict(self) -> dict:
        """Convert to dictionary for export (CSV/database).
        
        Returns:
            Dictionary with all board information
        """
        return {
            'serial_number': self.serial_number,
            'position_col': self.position[0] if self.position else None,
            'position_row': self.position[1] if self.position else None,
            'timestamp_qr_scan': self.timestamp_qr_scan,
            'timestamp_probe': self.timestamp_probe,
            'timestamp_program': self.timestamp_program,
            'probe_result': self.probe_result,
            'program_result': self.program_result,
            'notes': self.notes,
            **self.test_data  # Include all test data as separate columns
        }
    
    def __repr__(self):
        return f"BoardInfo(serial={self.serial_number}, pos={self.position})"


class BoardStatus:
    """Tracks the status of a single board position."""
    
    def __init__(self, position: Tuple[int, int]):
        """Initialize board status.
        
        Args:
            position: Tuple (col, row) for this board position
        """
        self.position = position
        self.enabled = True
        self.vision_status = VisionStatus.IDLE
        self.probe_status = ProbeStatus.IDLE
        self.program_status = ProgramStatus.IDLE
        self.provision_status = ProvisionStatus.IDLE
        self.test_status = TestStatus.IDLE
        self.qr_code: Optional[str] = None  # Scanned QR code data (deprecated - use board_info)
        self.board_info: Optional[BoardInfo] = None  # Detailed board information
        self.failure_reason: Optional[str] = None  # Why the board failed (if applicable)
    
    @property
    def status_text(self) -> Tuple[str, str, str, str]:
        """Return text description of current state.
        
        Returns:
            Tuple of (probe_text, program_text, provision_text, test_text) for display
        """
        if not self.enabled:
            return ("DISABLED", "", "", "")
        
        # Show probe, program, provision, and test status
        probe_text = self.probe_status.value if self.probe_status else "Pending"
        program_text = self.program_status.value if self.program_status else "Pending"
        provision_text = self.provision_status.value if self.provision_status else "Pending"
        test_text = self.test_status.value if self.test_status else "Pending"
        
        # If there's a failure reason, include it
        if self.probe_status == ProbeStatus.FAILED and self.failure_reason:
            probe_text = f"{probe_text} ({self.failure_reason})"
        if self.program_status == ProgramStatus.FAILED and self.failure_reason:
            program_text = f"{program_text} ({self.failure_reason})"
        if self.provision_status == ProvisionStatus.FAILED and self.failure_reason:
            provision_text = f"{provision_text} ({self.failure_reason})"
        if self.test_status == TestStatus.FAILED and self.failure_reason:
            test_text = f"{test_text} ({self.failure_reason})"
        
        return (probe_text, program_text, provision_text, test_text)
    
    def reset(self):
        """Reset all status fields to initial state."""
        self.vision_status = VisionStatus.IDLE
        self.probe_status = ProbeStatus.IDLE
        self.program_status = ProgramStatus.IDLE
        self.provision_status = ProvisionStatus.IDLE
        self.test_status = TestStatus.IDLE
        self.qr_code = None
        self.board_info = None
        self.failure_reason = None
    
    def __repr__(self):
        return f"BoardStatus({self.position}, enabled={self.enabled}, probe={self.probe_status.name}, prog={self.program_status.name})"
