import time
import subprocess
import threading
import asyncio
import traceback
import os
import cv2
import gc
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
from pynnex import with_emitters, emitter, listener
from programmer_controller import ProgrammerController
from head_controller import HeadController
from target_controller import TargetController
from motion_controller import MotionController
from vision_controller import VisionController
from device_discovery import DevicePortManager

def debug_log(msg):
    """Write debug message to /tmp/debug.txt"""
    try:
        with open('/tmp/debug.txt', 'a') as f:
            import datetime
            timestamp = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
            f.write(f"[{timestamp}] {msg}\n")
            f.flush()
    except Exception:
        pass  # Silently fail if logging doesn't work


class CycleStats:
    """Track timing statistics for programming cycles."""
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        """Clear all statistics for a new cycle."""
        # Per-board timing data: {(col, row): {'qr_scan': time, 'probe': time, 'program': time}}
        self.board_times: Dict[Tuple[int, int], Dict[str, float]] = {}
        
        # Aggregate statistics
        self.cycle_start_time: Optional[float] = None
        self.cycle_end_time: Optional[float] = None
        
        # Running totals for quick aggregate calculation
        self._qr_times: List[float] = []
        self._probe_times: List[float] = []
        self._program_times: List[float] = []
        
        # Board counts
        self.boards_scanned = 0
        self.boards_probed = 0
        self.boards_programmed = 0
        self.boards_skipped = 0
        self.boards_failed = 0
    
    def start_cycle(self):
        """Mark the start of a new cycle."""
        self.reset()
        self.cycle_start_time = time.time()
    
    def end_cycle(self):
        """Mark the end of the cycle."""
        self.cycle_end_time = time.time()
    
    def record_board_time(self, col: int, row: int, phase: str, duration: float):
        """Record timing for a specific board and phase.
        
        Args:
            col: Board column
            row: Board row
            phase: One of 'qr_scan', 'probe', 'program'
            duration: Time in seconds
        """
        key = (col, row)
        if key not in self.board_times:
            self.board_times[key] = {}
        self.board_times[key][phase] = duration
        
        # Update running totals
        if phase == 'qr_scan':
            self._qr_times.append(duration)
            self.boards_scanned += 1
        elif phase == 'probe':
            self._probe_times.append(duration)
            self.boards_probed += 1
        elif phase == 'program':
            self._program_times.append(duration)
            self.boards_programmed += 1
    
    def record_skip(self):
        """Record a skipped board."""
        self.boards_skipped += 1
    
    def record_failure(self):
        """Record a failed board."""
        self.boards_failed += 1
    
    def _calc_stats(self, times: List[float]) -> Tuple[float, float, float]:
        """Calculate min, avg, max for a list of times."""
        if not times:
            return (0.0, 0.0, 0.0)
        return (min(times), sum(times) / len(times), max(times))
    
    @property
    def qr_scan_stats(self) -> Tuple[float, float, float]:
        """Return (min, avg, max) for QR scan times."""
        return self._calc_stats(self._qr_times)
    
    @property
    def probe_stats(self) -> Tuple[float, float, float]:
        """Return (min, avg, max) for probe times."""
        return self._calc_stats(self._probe_times)
    
    @property
    def program_stats(self) -> Tuple[float, float, float]:
        """Return (min, avg, max) for program times."""
        return self._calc_stats(self._program_times)
    
    @property
    def cycle_duration(self) -> float:
        """Return total cycle duration in seconds."""
        if self.cycle_start_time is None:
            return 0.0
        end = self.cycle_end_time or time.time()
        return end - self.cycle_start_time
    
    def get_summary_text(self) -> str:
        """Return formatted summary text for display."""
        lines = []
        
        # Cycle time
        duration = self.cycle_duration
        if duration > 0:
            lines.append(f"Cycle: {duration:.1f}s")
        
        # Board counts
        total = self.boards_scanned + self.boards_skipped
        if total > 0:
            lines.append(f"Boards: {self.boards_programmed}/{total}")
            if self.boards_failed > 0:
                lines.append(f"Failed: {self.boards_failed}")
        
        # QR scan stats
        if self._qr_times:
            mn, avg, mx = self.qr_scan_stats
            lines.append(f"QR: {avg:.1f}s ({mn:.1f}-{mx:.1f})")
        
        # Probe stats  
        if self._probe_times:
            mn, avg, mx = self.probe_stats
            lines.append(f"Probe: {avg:.1f}s ({mn:.1f}-{mx:.1f})")
        
        # Program stats
        if self._program_times:
            mn, avg, mx = self.program_stats
            lines.append(f"Prog: {avg:.1f}s ({mn:.1f}-{mx:.1f})")
        
        return '\n'.join(lines) if lines else 'Ready'


BOARD_X=110.2
BOARD_Y=121.0
BOARD_COL_WIDTH=48.0
BOARD_ROW_HEIGHT=29.0
BOARD_NUM_ROWS=5
BOARD_NUM_COLS=2
PROBE_PLANE_TO_BOARD=4.0


class ProgramStatus(Enum):
    """Status of the programming operation."""
    IDLE = "Idle"
    IDENTIFYING = "Identifying"
    IDENTIFIED = "Identified"
    PROGRAMMING = "Programming"
    COMPLETED = "Programmed"
    FAILED = "Failed"
    SKIPPED = "Skipped"


class ProbeStatus(Enum):
    """Status of the probing operation."""
    IDLE = "Idle"
    PROBING = "Probing"
    COMPLETED = "Probed"
    FAILED = "Probe Failed"
    SKIPPED = "Skipped"


class VisionStatus(Enum):
    """Status of the vision/QR scanning operation."""
    IDLE = "Idle"
    IN_PROGRESS = "Scanning"
    PASSED = "QR Detected"
    FAILED = "No QR"


class OperationMode(Enum):
    """Operating modes for the programming cycle."""
    IDENTIFY_ONLY = "Identify Only"
    PROGRAM = "Program"
    PROGRAM_AND_TEST = "Program & Test"
    TEST_ONLY = "Test Only"

@dataclass
class Config:
    """Config container for board parameters and runtime options."""
    board_x: float = BOARD_X
    board_y: float = BOARD_Y
    board_col_width: float = BOARD_COL_WIDTH
    board_row_height: float = BOARD_ROW_HEIGHT
    board_num_rows: int = BOARD_NUM_ROWS
    board_num_cols: int = BOARD_NUM_COLS
    probe_plane_to_board: float = PROBE_PLANE_TO_BOARD
    contact_adjust_step: float = 0.1  # Y adjustment step in mm when contact fails
    operation_mode: OperationMode = OperationMode.PROGRAM
    skip_board_pos: List[List[int]] = field(default_factory=list)
    motion_port_id: str = ''  # Unique ID for motion controller port
    motion_baud: int = 115200
    head_port_id: str = ''  # Unique ID for head controller port
    head_baud: int = 9600
    target_port_id: str = ''  # Unique ID for target controller port
    target_baud: int = 115200
    network_core_firmware: str = '/home/steve/fw/merged_CPUNET.hex'
    main_core_firmware: str = '/home/steve/fw/merged.hex'
    # Camera/vision settings
    use_camera: bool = True  # Enable QR code scanning
    use_picamera: bool = True  # Use Raspberry Pi camera (vs USB camera)
    camera_index: int = 0  # USB camera index (if not using picamera)
    camera_offset_x: float = 50.0  # X offset from probe head to camera center (global)
    camera_offset_y: float = 50.0  # Y offset from probe head to camera center (global)
    camera_z_height: float = 0.0  # Z height for camera focus (0 = safe height)
    qr_offset_x: float = 0.0  # X offset from board origin to QR code (panel-specific)
    qr_offset_y: float = 0.0  # Y offset from board origin to QR code (panel-specific)
    qr_scan_timeout: float = 5.0  # Seconds to wait for QR code detection (1-10)
    qr_search_offset: float = 2.0  # XY offset in mm to search around QR position if scan fails (0=disabled)


class BoardInfo:
    """Information collected about an individual board."""
    
    def __init__(self, serial_number: Optional[str] = None):
        """Initialize board information."""
        self.serial_number: Optional[str] = serial_number  # Scanned from QR code
        self.test_data: dict = {}  # Testing phase data (key-value pairs)
        self.position: Optional[tuple] = None  # (col, row) position in panel
        self.timestamp_qr_scan: Optional[str] = None  # When QR was scanned
        self.timestamp_probe: Optional[str] = None  # When probing completed
        self.timestamp_program: Optional[str] = None  # When programming completed
        self.probe_result: Optional[bool] = None  # True if probing passed
        self.program_result: Optional[bool] = None  # True if programming passed
        self.notes: str = ""  # Any additional notes or error messages
    
    def to_dict(self):
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
    
    def __init__(self, position):
        """Initialize board status.
        
        Args:
            position: Tuple (col, row) for this board position
        """
        self.position = position
        self.enabled = True
        self.vision_status = VisionStatus.IDLE
        self.probe_status = ProbeStatus.IDLE
        self.program_status = ProgramStatus.IDLE
        self.qr_code: Optional[str] = None  # Scanned QR code data (deprecated - use board_info)
        self.board_info: Optional[BoardInfo] = None  # Detailed board information
        self.failure_reason: Optional[str] = None  # Why the board failed (if applicable)
    
    @property
    def status_text(self):
        """Return text description of current state.
        
        Returns:
            Tuple of (status_line1, status_line2) for display
        """
        if not self.enabled:
            return ("DISABLED", "")
        
        # Show probe status on first line, program status on second
        probe_text = self.probe_status.value if self.probe_status else "Idle"
        program_text = self.program_status.value if self.program_status else "Idle"
        
        # If there's a failure reason, include it
        if self.probe_status == ProbeStatus.FAILED and self.failure_reason:
            probe_text = f"{probe_text} ({self.failure_reason})"
        if self.program_status == ProgramStatus.FAILED and self.failure_reason:
            program_text = f"{program_text} ({self.failure_reason})"
        
        return (probe_text, program_text)
    
    def __repr__(self):
        return f"BoardStatus({self.position}, enabled={self.enabled}, probe={self.probe_status.name}, prog={self.program_status.name})"



@with_emitters
class ProgBot:
    @emitter
    def phase_changed(self):
        pass

    @emitter
    def panel_changed(self):
        pass
    
    @emitter
    def cell_color_changed(self):
        pass
    
    @emitter
    def board_status_changed(self):
        pass
    
    @emitter
    def error_occurred(self):
        pass
    
    @emitter
    def stats_updated(self):
        """Emitted when cycle statistics are updated."""
        pass
    
    @emitter
    def qr_scan_started(self):
        """Emitted when QR scanning phase begins."""
        pass
    
    @emitter
    def qr_scan_ended(self):
        """Emitted when QR scanning phase ends."""
        pass
       

    def __init__(self, config: Optional[Config] = None, programmer=None, head=None, target=None, motion=None, vision=None, panel_settings=None, gui_port_picker=None):
        print("new progbot")
        self.config = config or Config()
        self.board_statuses = {}
        self.stats = CycleStats()  # Timing statistics
        self.panel_settings = panel_settings  # Store reference for later use
        self.gui_port_picker = gui_port_picker  # Function to show GUI port picker
        self.programmer = programmer or ProgrammerController(
            self.update_phase, 
            network_core_firmware=self.config.network_core_firmware,
            main_core_firmware=self.config.main_core_firmware
        )
        
        # Controllers will be initialized after port resolution
        self.head = head
        self.target = target
        self.motion = motion
        self.vision = vision or (VisionController(
            self.update_phase,
            use_picamera=self.config.use_picamera,
            camera_index=self.config.camera_index
        ) if self.config.use_camera else None)
        debug_log(f"[ProgBot.__init__] Vision initialized: vision={self.vision}, use_camera={self.config.use_camera}")
        print(f"[ProgBot] Vision initialized: vision={self.vision}, use_camera={self.config.use_camera}")
        self.current_board: Optional[Tuple[int, int]] = None
        self._ports_configured = False
        self._selected_port_devices = []  # Track already-selected port device paths
    
    async def discover_devices(self):
        """Stub for device discovery - ports are already configured."""
        pass
    
    async def configure_ports(self):
        """Resolve port IDs and initialize controllers.
        
        This must be called after the Kivy window is visible so dialogs can be shown.
        """
        if self._ports_configured:
            return
        
        try:
            print("[ProgBot] Configuring serial ports...")
            
            # Resolve port IDs to actual device paths (async friendly)
            motion_port = await self._resolve_port_async(self.config.motion_port_id, 'Motion Controller', '/dev/ttyACM0')
            head_port = await self._resolve_port_async(self.config.head_port_id, 'Head Controller', '/dev/ttyUSB0')
            target_port = await self._resolve_port_async(self.config.target_port_id, 'Target Device', '/dev/ttyACM1')
            
            # Initialize controllers with resolved ports
            if not self.head:
                self.head = HeadController(self.update_phase, head_port, self.config.head_baud)
            if not self.target:
                self.target = TargetController(self.update_phase, target_port, self.config.target_baud)
            if not self.motion:
                self.motion = MotionController(self.update_phase, motion_port, self.config.motion_baud)
            
            self._ports_configured = True
            print("[ProgBot] Serial ports configured successfully")
        except Exception as e:
            print(f"[ProgBot] Error configuring ports: {e}")
            raise

    async def initialize_hardware(self):
        """Initialize all hardware connections once at startup.
        
        This should be called once after configure_ports() and kept open
        for the lifetime of the application.
        """
        if hasattr(self, '_hardware_initialized') and self._hardware_initialized:
            debug_log("[initialize_hardware] Hardware already initialized")
            return
        
        debug_log("[initialize_hardware] Starting hardware initialization...")
        
        # Connect to all serial devices
        try:
            debug_log("[initialize_hardware] Connecting to motion controller...")
            await self.motion.connect()
            debug_log("[initialize_hardware] Motion controller connected")
        except Exception as e:
            debug_log(f"[initialize_hardware] Motion connect failed: {e}")
            raise
        
        try:
            debug_log("[initialize_hardware] Connecting to head controller...")
            await self.head.connect()
            debug_log("[initialize_hardware] Head controller connected")
        except Exception as e:
            debug_log(f"[initialize_hardware] Head connect failed: {e}")
            raise
        
        try:
            debug_log("[initialize_hardware] Connecting to target controller...")
            await self.target.connect()
            debug_log("[initialize_hardware] Target controller connected")
        except Exception as e:
            debug_log(f"[initialize_hardware] Target connect failed: {e}")
            raise
        
        # Initialize camera if enabled
        if self.vision and self.config.use_camera:
            try:
                debug_log("[initialize_hardware] Connecting to camera...")
                await asyncio.wait_for(self.vision.connect(), timeout=10.0)
                debug_log("[initialize_hardware] Camera connected")
            except Exception as e:
                debug_log(f"[initialize_hardware] Camera connect failed: {e}")
                print(f"Warning: Camera initialization failed: {e}")
                self.vision = None
        
        self._hardware_initialized = True
        debug_log("[initialize_hardware] Hardware initialization complete")
    
    async def discover_devices(self):
        """Stub for device discovery - no longer needed with persistent connections."""
        pass
    
    def get_board_status(self, col, row):
        """Get or create board status for a position.
        
        Args:
            col: Column index
            row: Row index
            
        Returns:
            BoardStatus object
        """
        position = (col, row)
        if position not in self.board_statuses:
            self.board_statuses[position] = BoardStatus(position)
        return self.board_statuses[position]
    
    def set_skip_board_pos(self, skip_positions):
        """Update the skip positions from the UI.
        
        Args:
            skip_positions: List of [col, row] coordinates to skip
        """
        self.config.skip_board_pos = skip_positions
        print(f"Updated skip_board_pos: {self.config.skip_board_pos}")
    
    def init_panel(self):
        """Call this after listeners are connected to emit panel dimensions."""
        self.panel_changed.emit(self.config.board_num_cols, self.config.board_num_rows)
    
    async def _resolve_port_async(self, port_id, device_type, default_device, is_reconfigure=False):
        """Async version of port resolution for use after window is visible.
        
        Args:
            port_id: Unique port ID string
            device_type: Human-readable device type
            default_device: Default device path (unused)
            is_reconfigure: If True, always prompt for port selection (don't try to find by ID)
            
        Returns:
            Device path string (e.g. /dev/ttyACM0)
        """
        import asyncio
        
        # If reconfiguring, skip the ID lookup and go straight to prompt
        if is_reconfigure:
            print(f"[ProgBot] Reconfiguring {device_type}")
            return await self._prompt_for_port_async(device_type, None, is_reconfigure=True)
        
        # If no port ID configured, prompt user to select
        if not port_id:
            print(f"[ProgBot] No port ID configured for {device_type}")
            return await self._prompt_for_port_async(device_type, None)
        
        # Try to find the port by its unique ID
        device_path = DevicePortManager.find_port_by_unique_id(port_id)
        if device_path:
            print(f"[ProgBot] Found {device_type} at {device_path} (ID: {port_id})")
            return device_path
        else:
            print(f"[ProgBot] Configured port ID '{port_id}' not found for {device_type}")
            return await self._prompt_for_port_async(device_type, None)
    
    async def _prompt_for_port_async(self, device_type, default_device, is_reconfigure=False):
        """Async prompt user to select a port.
        
        Args:
            device_type: Human-readable device type
            default_device: Unused (no longer using defaults)
            is_reconfigure: If True, don't filter out already-selected ports (allow re-selection)
            
        Returns:
            Device path string
        """
        import asyncio
        from concurrent.futures import Future
        
        print(f"\n{'='*60}")
        print(f"Port selection required for: {device_type}")
        print(f"{'='*60}")
        
        try:
            # If GUI picker is available, use it
            if self.gui_port_picker:
                result_future = Future()
                
                def handle_selection(selected_port):
                    """Callback from GUI - stores result in future."""
                    if not result_future.done():
                        result_future.set_result(selected_port)
                
                # Get available ports and filter out already-selected ones (unless reconfiguring)
                all_ports = DevicePortManager.list_ports()
                if is_reconfigure:
                    # When reconfiguring, show all ports
                    ports = all_ports
                else:
                    # During initial config, filter out already-selected ports
                    ports = [p for p in all_ports if p.device not in self._selected_port_devices]
                
                if not ports:
                    print(f"[ProgBot] No available ports remaining for {device_type}")
                    raise RuntimeError(f"No available ports for {device_type}")
                
                # Show GUI picker (this returns immediately)
                self.gui_port_picker(device_type, ports, handle_selection)
                
                # Wait for user selection asynchronously
                timeout = 300  # 5 minutes
                elapsed = 0
                while not result_future.done():
                    await asyncio.sleep(0.05)  # Yield to event loop
                    elapsed += 0.05
                    if elapsed > timeout:
                        raise TimeoutError(f"Port selection timed out for {device_type}")
                
                selected_port = result_future.result()
            else:
                # Console mode (not async)
                DevicePortManager.print_available_ports()
                selected_port = DevicePortManager.prompt_user_for_port(device_type)
            
            if selected_port:
                # Save the unique ID for future use
                self._save_port_id(device_type, selected_port.unique_id)
                # Track this device as selected (unless reconfiguring - no need to track again)
                if not is_reconfigure and selected_port.device not in self._selected_port_devices:
                    self._selected_port_devices.append(selected_port.device)
                print(f"[ProgBot] Selected {selected_port.device} for {device_type}")
                return selected_port.device
            else:
                raise RuntimeError(f"No port selected for {device_type}. Cannot continue.")
        except Exception as e:
            print(f"[ProgBot] ERROR in port selection for {device_type}: {e}")
            import traceback
            traceback.print_exc()
            raise

    
    def _resolve_port(self, port_id, device_type, default_device):
        """Resolve a port unique ID to an actual device path.
        
        Args:
            port_id: Unique port identifier (or empty string)
            device_type: Human-readable device type for prompts
            default_device: Default device path (unused, kept for compatibility)
            
        Returns:
            Device path string (e.g. /dev/ttyACM0)
        """
        # If no port ID configured, prompt user to select
        if not port_id:
            print(f"[ProgBot] No port ID configured for {device_type}")
            return self._prompt_for_port(device_type, None)
        
        # Try to find the port by its unique ID
        device_path = DevicePortManager.find_port_by_unique_id(port_id)
        if device_path:
            print(f"[ProgBot] Found {device_type} at {device_path} (ID: {port_id})")
            return device_path
        else:
            print(f"[ProgBot] Configured port ID '{port_id}' not found for {device_type}")
            return self._prompt_for_port(device_type, None)
    
    def _prompt_for_port(self, device_type, default_device):
        """Prompt user to select a port.
        
        Args:
            device_type: Human-readable device type
            default_device: Unused (no longer using defaults)
            
        Returns:
            Device path string
        """
        print(f"\n{'='*60}")
        print(f"Port selection required for: {device_type}")
        print(f"{'='*60}")
        
        # If GUI picker is available, use it synchronously
        if self.gui_port_picker:
            import time
            from concurrent.futures import Future
            
            result_future = Future()
            
            def handle_selection(selected_port):
                """Callback from GUI - stores result in future."""
                result_future.set_result(selected_port)
            
            # Get available ports
            ports = DevicePortManager.list_ports()
            
            # Show GUI picker (this returns immediately)
            self.gui_port_picker(device_type, ports, handle_selection)
            
            # Wait for user selection while processing Kivy events
            try:
                from kivy.clock import Clock
                timeout = 300  # 5 minutes
                start_time = time.time()
                
                while not result_future.done():
                    if time.time() - start_time > timeout:
                        raise TimeoutError("Port selection timed out")
                    # Process Kivy events to keep UI responsive
                    Clock.tick()
                    time.sleep(0.01)  # Small delay to prevent CPU spinning
                
                selected_port = result_future.result()
            except Exception as e:
                print(f"[ProgBot] Port selection timeout or error: {e}")
                raise RuntimeError(f"Port selection failed for {device_type}")
        else:
            # Console mode
            DevicePortManager.print_available_ports()
            selected_port = DevicePortManager.prompt_user_for_port(device_type)
        
        if selected_port:
            # Save the unique ID for future use
            self._save_port_id(device_type, selected_port.unique_id)
            return selected_port.device
        else:
            raise RuntimeError(f"No port selected for {device_type}. Cannot continue.")
    
    def _save_port_id(self, device_type, unique_id):
        """Save a port unique ID to the settings file.
        
        Args:
            device_type: Device type string
            unique_id: Unique port identifier
        """
        from settings import get_settings
        settings = get_settings()
        
        if device_type == 'Motion Controller':
            self.config.motion_port_id = unique_id
            settings.set('motion_port_id', unique_id)
        elif device_type == 'Head Controller':
            self.config.head_port_id = unique_id
            settings.set('head_port_id', unique_id)
        elif device_type == 'Target Device':
            self.config.target_port_id = unique_id
            settings.set('target_port_id', unique_id)
        
        print(f"[ProgBot] Saved port ID for {device_type}: {unique_id}")

    def _emit_status(self, cell_id, board_status):
        self.board_status_changed.emit(cell_id, board_status)

    def _mark_probe(self, cell_id, board_status, status):
        board_status.probe_status = status
        self._emit_status(cell_id, board_status)

    def _mark_program(self, cell_id, board_status, status):
        board_status.program_status = status
        self._emit_status(cell_id, board_status)
    
    def _mark_vision(self, cell_id, board_status, status):
        board_status.vision_status = status
        self._emit_status(cell_id, board_status)

    def check_device(self):
        res = subprocess.run(["nrfutil", "device", "device-info"])
        if res.returncode != 0:
            return False
        return True
    
    def update_phase(self, phase_str):
        print(f"Phase now: {phase_str}")
        self.phase_changed.emit(phase_str)

    async def _run_board(self, col: int, row: int):
        self.current_board = (col, row)
        board_status = self.get_board_status(col, row)
        cell_id = col * self.config.board_num_rows + row

        if [col, row] in self.config.skip_board_pos:
            print(f"SKIPPING col={col} row={row}")
            self._mark_probe(cell_id, board_status, ProbeStatus.SKIPPED)
            self._mark_program(cell_id, board_status, ProgramStatus.SKIPPED)
            self.current_board = None
            return
        
        # If board was already marked as skipped during QR scan phase, skip it
        if board_status.probe_status == ProbeStatus.SKIPPED:
            debug_log(f"[_run_board] Board [{col},{row}] already skipped (no QR code)")
            print(f"[Board {col},{row}] Skipped (no QR code)")
            self.current_board = None
            return

        # Calculate board position
        board_x = self.config.board_x + (col * self.config.board_col_width)
        board_y = self.config.board_y + (row * self.config.board_row_height)

        # Camera scanning is now done in _scan_all_boards_for_qr() before this method
        # Skip the camera code here - just proceed with probing
        
        # Now proceed with normal probing sequence - track timing
        probe_start = time.time()
        debug_log(f"[_run_board] Starting probe sequence for board [{col},{row}]")
        self._mark_probe(cell_id, board_status, ProbeStatus.PROBING)

        debug_log(f"[_run_board] Moving to board position ({board_x}, {board_y})")
        self.update_phase(f"Move to Board at [{col}, {row}]...")
        await self.motion.rapid_xy_abs(board_x, board_y)
        debug_log(f"[_run_board] Arrived at board position")

        debug_log(f"[_run_board] Starting probe operation")
        self.update_phase("Probing for board height...")
        try:
            dist_to_probe = await self.motion.do_probe()
            debug_log(f"[_run_board] Probe complete: dist_to_probe={dist_to_probe}")
            dist_to_board = dist_to_probe + self.config.probe_plane_to_board
            self._mark_probe(cell_id, board_status, ProbeStatus.COMPLETED)
            
            # Record probe time (movement + probe operation)
            probe_time = time.time() - probe_start
            self.stats.record_board_time(col, row, 'probe', probe_time)
            self.stats_updated.emit(self.stats.get_summary_text())
            debug_log(f"[_run_board] Board [{col},{row}] probe time: {probe_time:.2f}s")
        except Exception as e:
            print(f"Probe failed: {e}")
            debug_log(f"[_run_board] Probe failed: {e}")
            self._mark_probe(cell_id, board_status, ProbeStatus.FAILED)
            self.stats.record_failure()
            self.stats_updated.emit(self.stats.get_summary_text())
            # SAFETY: Return to safe Z height before exiting
            try:
                await self.motion.rapid_z_abs(0.0)
            except Exception:
                pass
            raise

        debug_log(f"[_run_board] Moving to safe height: {-1.0 * dist_to_probe}")
        self.update_phase("Move to safe height above board...")
        await self.motion.rapid_z_abs((-1.0 * dist_to_probe))
        debug_log(f"[_run_board] At safe height")

        debug_log(f"[_run_board] Checking for NO contact")
        self.update_phase("Check board is not contacted...")
        contact = await self.head.check_contact()
        debug_log(f"[_run_board] Contact check result: {contact}")
        if contact:
            error_msg = "Unexpected contact at safe height"
            print(f"[Board {col},{row}] ERROR: {error_msg}")
            debug_log(f"[_run_board] ERROR: {error_msg}")
            board_status.failure_reason = error_msg
            self._mark_probe(cell_id, board_status, ProbeStatus.FAILED)
            self._mark_program(cell_id, board_status, ProgramStatus.SKIPPED)
            # SAFETY: Already at safe height, just return
            return

        debug_log(f"[_run_board] Moving to board at distance: {-1.0 * dist_to_board}")
        self.update_phase("Move to board...")
        await self.motion.move_z_abs((-1.0 * dist_to_board), 200)
        debug_log(f"[_run_board] At board position")

        debug_log(f"[_run_board] Checking for contact WITH board")
        self.update_phase("Check for contact with board header...")
        contact = await self.head.check_contact()
        debug_log(f"[_run_board] Contact check result: {contact}")
        
        # If no contact, try small Y adjustments to improve contact reliability
        if not contact:
            debug_log(f"[_run_board] No contact at nominal position, trying Y adjustments...")
            self.update_phase("Adjusting position for contact...")
            
            # Try small Y movements using configured step: +step, -step, +2*step, -2*step
            step = self.config.contact_adjust_step
            y_adjustments = [step, -step, 2*step, -2*step]
            
            for y_offset in y_adjustments:
                debug_log(f"[_run_board] Trying Y offset: {y_offset}mm")
                # Move relative Y
                await self.motion.rapid_xy_rel(0, y_offset)
                
                # Check contact
                contact = await self.head.check_contact()
                debug_log(f"[_run_board] Contact check with Y offset {y_offset}mm: {contact}")
                
                if contact:
                    print(f"[Board {col},{row}] Contact established with Y offset {y_offset}mm")
                    debug_log(f"[_run_board] Contact successful with Y offset {y_offset}mm")
                    break
            else:
                # All adjustments failed - restore original position and fail
                debug_log(f"[_run_board] All Y adjustments failed, returning to nominal position")
                # Calculate total offset to return to nominal
                total_offset = sum(y_adjustments)
                if total_offset != 0:
                    await self.motion.rapid_xy_rel(0, -total_offset)
        
        if not contact:
            error_msg = "No contact with board header"
            print(f"[Board {col},{row}] ERROR: {error_msg}")
            debug_log(f"[_run_board] ERROR: {error_msg}")
            board_status.failure_reason = error_msg
            self._mark_probe(cell_id, board_status, ProbeStatus.FAILED)
            self._mark_program(cell_id, board_status, ProgramStatus.SKIPPED)
            self.stats.record_failure()
            self.stats_updated.emit(self.stats.get_summary_text())
            # SAFETY: Return to safe Z height before moving to next board
            await self.motion.rapid_z_abs(0.0)
            return

        # Start programming timing
        program_start = time.time()
        
        self.update_phase("Enabling programmer head power...")
        await self.head.set_power(True)
        await asyncio.sleep(1)
        self.update_phase("Enabling programmer head logic...")
        await self.head.set_logic(True)
        await asyncio.sleep(1)

        if self.config.operation_mode == OperationMode.IDENTIFY_ONLY:
            self._mark_program(cell_id, board_status, ProgramStatus.IDENTIFYING)
            self.update_phase("Identifying device...")
            try:
                success = await self.programmer.identify()
                print(f"success={success}")
                self._mark_program(
                    cell_id,
                    board_status,
                    ProgramStatus.IDENTIFIED if success else ProgramStatus.FAILED,
                )
            except Exception as e:
                print(f"Identification failed: {e}")
                self._mark_program(cell_id, board_status, ProgramStatus.FAILED)
                self.stats.record_failure()
                self.stats_updated.emit(self.stats.get_summary_text())
                # SAFETY: Return to safe Z height before re-raising
                await self.head.set_all(False)
                await self.motion.rapid_z_abs(0.0)
                raise

        elif self.config.operation_mode in (OperationMode.PROGRAM, OperationMode.PROGRAM_AND_TEST):
            self._mark_program(cell_id, board_status, ProgramStatus.PROGRAMMING)
            self.update_phase("Programming device...")
            try:
                success = await self.programmer.program()
                print(f"success={success}")
                self._mark_program(
                    cell_id,
                    board_status,
                    ProgramStatus.COMPLETED if success else ProgramStatus.FAILED,
                )
            except Exception as e:
                print(f"Programming failed: {e}")
                self._mark_program(cell_id, board_status, ProgramStatus.FAILED)
                self.stats.record_failure()
                self.stats_updated.emit(self.stats.get_summary_text())
                # SAFETY: Return to safe Z height before re-raising
                await self.head.set_all(False)
                await self.motion.rapid_z_abs(0.0)
                raise

            if success:
                monitor_task = self.target.create_monitor_task()
                await asyncio.sleep(5)
                monitor_task.cancel()

            await self.head.set_all(False)
            await asyncio.sleep(1)
            self.update_phase("Move to safe height...")
            await self.motion.rapid_z_abs(0.0)

        await self.head.set_all(False)
        await asyncio.sleep(1)
        self.update_phase("Move to safe height...")
        await self.motion.rapid_z_abs(0.0)
        
        # Record programming time
        program_time = time.time() - program_start
        self.stats.record_board_time(col, row, 'program', program_time)
        self.stats_updated.emit(self.stats.get_summary_text())
        debug_log(f"[_run_board] Board [{col},{row}] program time: {program_time:.2f}s")

        self._emit_status(cell_id, board_status)
        self.current_board = None

    async def _run_from(self, start_col: int, start_row: int):
        for col in range(start_col, self.config.board_num_cols):
            row_start = start_row if col == start_col else 0
            for row in range(row_start, self.config.board_num_rows):
                await self._run_board(col, row)
    
    async def _scan_all_boards_for_qr(self):
        """Scan all boards with camera and mark those without QR codes as skipped."""
        debug_log("[_scan_all_boards_for_qr] Starting QR scan phase for all boards")
        print("[ProgBot] Starting QR scanning for all boards...")
        
        # Emit signal that QR scanning is starting
        self.qr_scan_started.emit()
        
        # Start preview once at the beginning (camera running at 4 FPS to reduce GIL contention)
        if hasattr(self, 'camera_preview') and self.camera_preview:
            from kivy.clock import Clock
            Clock.schedule_once(lambda dt: self.camera_preview.start_preview(), 0)
            await asyncio.sleep(0.15)
            debug_log("[_scan_all_boards_for_qr] Preview started for entire scan phase")
        
        debug_log(f"[_scan_all_boards_for_qr] board_num_cols={self.config.board_num_cols}, board_num_rows={self.config.board_num_rows}")
        
        try:
            for col in range(self.config.board_num_cols):
                for row in range(self.config.board_num_rows):
                    debug_log(f"[_scan_all_boards_for_qr] Processing board [{col},{row}]")
                    
                    # Skip if already marked to skip
                    if [col, row] in self.config.skip_board_pos:
                        debug_log(f"[_scan_all_boards_for_qr] Board [{col},{row}] is in skip list, skipping")
                        self.stats.record_skip()
                        continue
                    
                    board_status = self.get_board_status(col, row)
                    debug_log(f"[_scan_all_boards_for_qr] Got board_status for [{col},{row}]")
                    
                    cell_id = col * self.config.board_num_rows + row
                    
                    # Mark board as currently being scanned
                    debug_log(f"[_scan_all_boards_for_qr] Marking vision IN_PROGRESS for [{col},{row}]")
                    self._mark_vision(cell_id, board_status, VisionStatus.IN_PROGRESS)
                    debug_log(f"[_scan_all_boards_for_qr] Emitting status for [{col},{row}]")
                    self._emit_status(cell_id, board_status)
                    debug_log(f"[_scan_all_boards_for_qr] Status emitted for [{col},{row}]")
                    
                    # Calculate positions
                    board_x = self.config.board_x + (col * self.config.board_col_width)
                    board_y = self.config.board_y + (row * self.config.board_row_height)
                    # Camera position = board position + QR offset + camera offset
                    camera_x = board_x + self.config.qr_offset_x + self.config.camera_offset_x
                    camera_y = board_y + self.config.qr_offset_y + self.config.camera_offset_y
                    
                    debug_log(f"[_scan_all_boards_for_qr] Board [{col},{row}]: board=({board_x},{board_y}), qr_offset=({self.config.qr_offset_x},{self.config.qr_offset_y}), camera_offset=({self.config.camera_offset_x},{self.config.camera_offset_y}), final_camera=({camera_x},{camera_y})")
                    
                    try:
                        board_scan_start = time.time()
                        self.update_phase(f"Scanning QR for Board [{col}, {row}]...")
                        
                        # Move to camera position
                        await self.motion.rapid_xy_abs(camera_x, camera_y)
                        await self.motion.rapid_z_abs(self.config.camera_z_height)
                        
                        # Camera buffer drain - use async version (no extra delay needed,
                        # scan_qr_code fast-path handles warm camera optimization)
                        if self.vision:
                            await self.vision.drain_camera_buffer_async(max_frames=3)
                        
                        # QR scanning (fast-path will try immediate detection first)
                        qr_data = None
                        if self.vision:
                            preview = self.camera_preview if hasattr(self, 'camera_preview') else None
                            
                            qr_data = await self.vision.scan_qr_code(
                                retries=2, 
                                delay=0.2,  # Reduced from 0.3 
                                camera_preview=preview,
                                motion_controller=self.motion,
                                search_offset=self.config.qr_search_offset,
                                base_x=camera_x,
                                base_y=camera_y
                            )
                        
                        # Record QR scan time
                        qr_scan_time = time.time() - board_scan_start
                        self.stats.record_board_time(col, row, 'qr_scan', qr_scan_time)
                        self.stats_updated.emit(self.stats.get_summary_text())
                        debug_log(f"[_scan_all_boards_for_qr] Board [{col},{row}] QR scan time: {qr_scan_time:.2f}s")
                        
                        if qr_data:
                            board_status.qr_code = qr_data
                            
                            # Create and populate BoardInfo
                            import datetime
                            board_info = BoardInfo(serial_number=qr_data)
                            board_info.timestamp_qr_scan = datetime.datetime.now().isoformat()
                            board_status.board_info = board_info
                            
                            debug_log(f"[_scan_all_boards_for_qr] Board [{col},{row}] QR: {qr_data}")
                            print(f"[Board {col},{row}] Serial Number: {qr_data}")
                            
                            # Mark vision as passed (this emits status with qr_code and board_info)
                            self._mark_vision(cell_id, board_status, VisionStatus.PASSED)
                        else:
                            # No QR code - mark as skipped
                            debug_log(f"[_scan_all_boards_for_qr] Board [{col},{row}] No QR - marking as skipped")
                            print(f"[Board {col},{row}] No QR code - skipping board")
                            board_status.failure_reason = "No QR Code"
                            board_status.vision_status = VisionStatus.FAILED
                            board_status.probe_status = ProbeStatus.SKIPPED
                            board_status.program_status = ProgramStatus.SKIPPED
                            self.stats.record_skip()
                            self._emit_status(cell_id, board_status)
                    
                    except Exception as e:
                        debug_log(f"[_scan_all_boards_for_qr] Board [{col},{row}] Error: {e}")
                        print(f"[Board {col},{row}] QR scan error: {e} - skipping board")
                        import traceback
                        traceback.print_exc()
                        board_status.failure_reason = "QR Scan Error"
                        board_status.vision_status = VisionStatus.FAILED
                        board_status.probe_status = ProbeStatus.SKIPPED
                        board_status.program_status = ProgramStatus.SKIPPED
                        self.stats.record_failure()
                        self._emit_status(cell_id, board_status)
        
        except asyncio.CancelledError:
            # Stop camera preview if it's still active
            if hasattr(self, 'camera_preview') and self.camera_preview:
                self.camera_preview.stop_preview()
            debug_log("[_scan_all_boards_for_qr] Cancelled during QR scan")
            print("[ProgBot] QR scan cancelled")
            self.qr_scan_ended.emit()
            raise
        finally:
            # Ensure preview is stopped even on normal completion
            if hasattr(self, 'camera_preview') and self.camera_preview:
                self.camera_preview.stop_preview()
        
        # Move to safe height after scanning
        await self.motion.rapid_z_abs(0.0)
        
        # Stop preview once at the end
        if hasattr(self, 'camera_preview') and self.camera_preview:
            from kivy.clock import Clock
            Clock.schedule_once(lambda dt: self.camera_preview.stop_preview(), 0)
            await asyncio.sleep(0.1)
        
        # Emit signal that QR scanning has ended
        self.qr_scan_ended.emit()
        
        debug_log("[_scan_all_boards_for_qr] QR scan phase complete")
        print("[ProgBot] QR scanning complete. Starting probe/program cycle...")

    async def full_cycle(self):
        """Execute the complete programming cycle."""
        debug_log("[full_cycle] Starting full cycle")
        print("[ProgBot] Starting full cycle...")
        
        # Start cycle statistics
        self.stats.start_cycle()
        self.stats_updated.emit(self.stats.get_summary_text())
        
        # Configure ports first (in case not done yet)
        await self.configure_ports()
        
        # Initialize hardware connections once (only on first call)
        await self.initialize_hardware()
        
        # REMOVED: No longer opening/closing devices every cycle
        # They stay connected for the lifetime of the application
        
        # Home if needed
        try:
            self.update_phase("Initializing devices...")
            await self.motion.init()
            
            # If camera is enabled, scan all boards first
            if self.vision and self.config.use_camera:
                debug_log("[full_cycle] Starting vision scan phase for all boards")
                await self._scan_all_boards_for_qr()
            
            await self._run_from(0, 0)

            self.update_phase(f"Done with full cycle.")
            await self.motion.rapid_xy_abs(0, 300)
            await self.motion.motors_off()
            
            # Disconnect camera to release resources FIRST
            if hasattr(self, 'vision') and self.vision:
                debug_log("[full_cycle] Disconnecting camera after successful cycle...")
                await self.vision.disconnect()
                debug_log("[full_cycle] Camera disconnected")
            
            # Then cleanup camera preview
            if hasattr(self, 'camera_preview') and self.camera_preview:
                debug_log("[full_cycle] Stopping camera preview...")
                from kivy.clock import Clock
                Clock.schedule_once(lambda dt: self.camera_preview.stop_preview(), 0)
            
            debug_log("[full_cycle] Cycle completed successfully")
            print("[ProgBot] Cycle complete")
            
            # End cycle statistics
            self.stats.end_cycle()
            self.stats_updated.emit(self.stats.get_summary_text())
            
            debug_log("[full_cycle] Cycle complete - cleanup done")

        except asyncio.CancelledError:
            debug_log("[full_cycle] Cycle cancelled")
            
            # End cycle statistics even when cancelled
            self.stats.end_cycle()
            self.stats_updated.emit(self.stats.get_summary_text())
            
            try:
                debug_log("[full_cycle] Moving Z to safe height...")
                await self.motion.rapid_z_abs(0.0)
                debug_log("[full_cycle] Moving XY to home...")
                await self.motion.rapid_xy_abs(0, 300)
                debug_log("[full_cycle] Homing complete")
            except Exception as e:
                debug_log(f"[full_cycle] Error during homing: {e}")
            
            debug_log("[full_cycle] Turning off motors...")
            await self.motion.motors_off()
            debug_log("[full_cycle] Motors off")
            
            # REMOVED: No longer disconnecting devices between cycles
            # Connections stay open for application lifetime
            
            # Stop camera preview (but keep camera subprocess running)
            if hasattr(self, 'camera_preview') and self.camera_preview:
                debug_log("[full_cycle] Stopping camera preview...")
                from kivy.clock import Clock
                Clock.schedule_once(lambda dt: self.camera_preview.stop_preview(), 0)
                debug_log("[full_cycle] Camera preview stop scheduled")
            
            # Force garbage collection to free resources
            gc.collect()
            debug_log("[full_cycle] Cleanup complete")
            print("Canceled.")
            raise
        except Exception as e:
            tb = traceback.format_exc()
            print(f"Exception: {e}")
            print(f"Traceback:\n{tb}")
            debug_log(f"[full_cycle] Exception: {e}")
            debug_log(f"[full_cycle] Traceback:\n{tb}")
            col, row = self.current_board if self.current_board else (None, None)
            
            # End cycle statistics even when exception occurs
            self.stats.end_cycle()
            self.stats_updated.emit(self.stats.get_summary_text())
            
            # Disconnect camera to release resources FIRST
            if hasattr(self, 'vision') and self.vision:
                await self.vision.disconnect()
            
            # Then cleanup camera preview
            if hasattr(self, 'camera_preview') and self.camera_preview:
                from kivy.clock import Clock
                Clock.schedule_once(lambda dt: self.camera_preview.stop_preview(), 0)
            
            self.error_occurred.emit({
                "message": str(e),
                "traceback": tb,
                "col": col,
                "row": row,
            })
            try:
                await self.motion.motors_off()
            except Exception:
                pass
            debug_log("[full_cycle] Exception - cleanup done")
            raise

    async def retry_board(self, col: int, row: int):
        self.update_phase(f"Retry Board [{col}, {row}]")
        await self.motion.connect()
        await self.head.connect()
        await self.target.connect()
        await self.motion.init()

        try:
            await self._run_board(col, row)

            next_col = col
            next_row = row + 1
            if next_row >= self.config.board_num_rows:
                next_col += 1
                next_row = 0

            if next_col < self.config.board_num_cols:
                await self._run_from(next_col, next_row)

            self.update_phase(f"Done with full cycle.")
            await self.motion.rapid_xy_abs(0, 300)
            await self.motion.motors_off()
        except asyncio.CancelledError:
            try:
                await self.motion.rapid_z_abs(0.0)
                await self.motion.rapid_xy_abs(0, 300)
            except Exception:
                pass
            await self.motion.motors_off()
            print(f"Canceled during retry.")
            raise
        except Exception as e:
            tb = traceback.format_exc()
            print(f"Retry exception: {e}")
            self.error_occurred.emit({
                "message": str(e),
                "traceback": tb,
                "col": col,
                "row": row,
            })
            try:
                await self.motion.motors_off()
            except Exception:
                pass
            raise


# This module is imported by kvui.py and not run directly

