import time
import subprocess
import threading
import asyncio
import traceback
import os
import cv2
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
from pynnex import with_emitters, emitter, listener

# Import status classes from centralized module
from board_status import (
    VisionStatus, ProbeStatus, ProgramStatus, ProvisionStatus, TestStatus,
    BoardStatus, BoardInfo
)
from head_controller import HeadController
from target_controller import TargetController
from motion_controller import MotionController
from vision_controller import VisionController
from device_discovery import DevicePortManager
from provisioning import ProvisioningEngine, ProvisionScript, VariableContext
from logger import get_logger

log = get_logger(__name__)


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


class OperationMode(Enum):
    """Operating modes for the programming cycle.
    
    DEPRECATED: Use individual step flags (do_identify, do_recover, do_erase, 
    do_program, do_lock) instead. This enum is kept for backward compatibility.
    """
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
    # Programming step flags (replaces operation_mode enum)
    do_identify: bool = True   # Run identification step
    do_recover: bool = False   # Run recovery step (if needed)
    do_erase: bool = False     # Run erase step
    do_program: bool = True    # Run programming step
    do_lock: bool = False      # Set protection/lock bits
    # Phase enable flags
    vision_enabled: bool = True  # Enable vision/QR scanning phase
    programming_enabled: bool = True  # Enable programming phase
    provision_enabled: bool = False  # Enable provisioning phase
    test_enabled: bool = False  # Enable testing phase
    # Legacy field - kept for backward compatibility
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
        log.info("ProgBot initialized")
        self.config = config or Config()
        self.board_statuses = {}
        self.stats = CycleStats()  # Timing statistics
        self.panel_settings = panel_settings  # Store reference for later use
        self.gui_port_picker = gui_port_picker  # Function to show GUI port picker
        self._cycle_active = False  # Flag to prevent signal emissions after cycle ends
        
        # Initialize programmer from plugin system
        self.programmer = programmer or self._create_programmer()
        
        # Controllers will be initialized after port resolution
        self.head = head
        self.target = target
        self.motion = motion
        self.vision = vision or (VisionController(
            self.update_phase,
            use_picamera=self.config.use_picamera,
            camera_index=self.config.camera_index
        ) if self.config.use_camera else None)
        log.debug(f"[ProgBot.__init__] Vision initialized: vision={self.vision}, use_camera={self.config.use_camera}")
        log.info(f"[ProgBot] Vision initialized: vision={self.vision}, use_camera={self.config.use_camera}")
        self.current_board: Optional[Tuple[int, int]] = None
        self._ports_configured = False
        self._selected_port_devices = []  # Track already-selected port device paths
    
    def _create_programmer(self):
        """Create programmer instance from panel settings or defaults."""
        from programmers import create_programmer, get_default_programmer_config
        
        # Get programmer config from panel settings
        if self.panel_settings:
            prog_config = self.panel_settings.get_programmer_config()
        else:
            prog_config = get_default_programmer_config('nordic_nrf')
        
        type_id = prog_config.get('type', 'nordic_nrf')
        firmware_paths = prog_config.get('firmware', {})
        
        programmer = create_programmer(type_id, self.update_phase, firmware_paths)
        log.info(f"[ProgBot] Created programmer: {type(programmer).__name__} (type={type_id})")
        return programmer
    
    def _get_enabled_programmer_steps(self) -> list:
        """Get list of enabled programmer step IDs from panel settings."""
        try:
            if self.panel_settings:
                prog_config = self.panel_settings.get_programmer_config()
                steps = prog_config.get('steps', {})
                
                # Return list of enabled step IDs in the order defined by the programmer
                from programmers import get_programmer_class
                type_id = prog_config.get('type', 'nordic_nrf')
                programmer_class = get_programmer_class(type_id)
                all_step_defs = programmer_class.get_steps()
                
                # Use configured value if present, otherwise fall back to step default
                enabled = []
                for step_def in all_step_defs:
                    step_id = step_def['id']
                    step_default = step_def.get('default', False)
                    is_enabled = steps.get(step_id, step_default)
                    if is_enabled:
                        enabled.append(step_id)
                
                return enabled
        except Exception as e:
            log.error(f"[ProgBot] Error getting enabled steps: {e}")
            import traceback
            traceback.print_exc()
        
        # Default: identify and program
        return ['identify', 'program']

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
            log.info("[ProgBot] Configuring serial ports...")
            
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
            log.info("[ProgBot] Serial ports configured successfully")
        except Exception as e:
            log.error(f"[ProgBot] Error configuring ports: {e}")
            raise

    async def initialize_hardware(self):
        """Initialize all hardware connections once at startup.
        
        This should be called once after configure_ports() and kept open
        for the lifetime of the application.
        """
        if hasattr(self, '_hardware_initialized') and self._hardware_initialized:
            log.debug("[initialize_hardware] Hardware already initialized")
            return
        
        log.debug("[initialize_hardware] Starting hardware initialization...")
        
        # Connect to all serial devices
        try:
            log.debug("[initialize_hardware] Connecting to motion controller...")
            await self.motion.connect()
            log.debug("[initialize_hardware] Motion controller connected")
        except Exception as e:
            log.debug(f"[initialize_hardware] Motion connect failed: {e}")
            raise
        
        try:
            log.debug("[initialize_hardware] Connecting to head controller...")
            await self.head.connect()
            log.debug("[initialize_hardware] Head controller connected")
        except Exception as e:
            log.debug(f"[initialize_hardware] Head connect failed: {e}")
            raise
        
        try:
            log.debug("[initialize_hardware] Connecting to target controller...")
            await self.target.connect()
            log.debug("[initialize_hardware] Target controller connected")
        except Exception as e:
            log.debug(f"[initialize_hardware] Target connect failed: {e}")
            raise
        
        # Initialize camera if enabled
        if self.vision and self.config.use_camera:
            try:
                log.debug("[initialize_hardware] Connecting to camera...")
                await asyncio.wait_for(self.vision.connect(), timeout=10.0)
                log.debug("[initialize_hardware] Camera connected")
            except Exception as e:
                log.debug(f"[initialize_hardware] Camera connect failed: {e}")
                log.warning(f"Warning: Camera initialization failed: {e}")
                self.vision = None
        
        self._hardware_initialized = True
        log.debug("[initialize_hardware] Hardware initialization complete")
    
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
            board_status = BoardStatus(position)
            # Set enabled=False if position is in skip list
            if [col, row] in self.config.skip_board_pos:
                board_status.enabled = False
            self.board_statuses[position] = board_status
        return self.board_statuses[position]
    
    def set_skip_board_pos(self, skip_positions):
        """Update the skip positions from the UI.
        
        Args:
            skip_positions: List of [col, row] coordinates to skip
        """
        self.config.skip_board_pos = skip_positions
        log.debug(f"Updated skip_board_pos: {self.config.skip_board_pos}")
        
        # Update enabled field for all existing board statuses
        for position, board_status in self.board_statuses.items():
            col, row = position
            board_status.enabled = [col, row] not in skip_positions
    
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
            log.info(f"[ProgBot] Reconfiguring {device_type}")
            return await self._prompt_for_port_async(device_type, None, is_reconfigure=True)
        
        # If no port ID configured, prompt user to select
        if not port_id:
            log.info(f"[ProgBot] No port ID configured for {device_type}")
            return await self._prompt_for_port_async(device_type, None)
        
        # Try to find the port by its unique ID
        device_path = DevicePortManager.find_port_by_unique_id(port_id)
        if device_path:
            log.info(f"[ProgBot] Found {device_type} at {device_path} (ID: {port_id})")
            return device_path
        else:
            log.info(f"[ProgBot] Configured port ID '{port_id}' not found for {device_type}")
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
        
        log.info(f"{'='*60}")
        log.info(f"Port selection required for: {device_type}")
        log.info(f"{'='*60}")
        
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
                    log.info(f"[ProgBot] No available ports remaining for {device_type}")
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
                log.info(f"[ProgBot] Selected {selected_port.device} for {device_type}")
                return selected_port.device
            else:
                raise RuntimeError(f"No port selected for {device_type}. Cannot continue.")
        except Exception as e:
            log.info(f"[ProgBot] ERROR in port selection for {device_type}: {e}")
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
            log.info(f"[ProgBot] No port ID configured for {device_type}")
            return self._prompt_for_port(device_type, None)
        
        # Try to find the port by its unique ID
        device_path = DevicePortManager.find_port_by_unique_id(port_id)
        if device_path:
            log.info(f"[ProgBot] Found {device_type} at {device_path} (ID: {port_id})")
            return device_path
        else:
            log.info(f"[ProgBot] Configured port ID '{port_id}' not found for {device_type}")
            return self._prompt_for_port(device_type, None)
    
    def _prompt_for_port(self, device_type, default_device):
        """Prompt user to select a port.
        
        Args:
            device_type: Human-readable device type
            default_device: Unused (no longer using defaults)
            
        Returns:
            Device path string
        """
        log.info(f"{'='*60}")
        log.info(f"Port selection required for: {device_type}")
        log.info(f"{'='*60}")
        
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
                log.info(f"[ProgBot] Port selection timeout or error: {e}")
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
        
        log.info(f"[ProgBot] Saved port ID for {device_type}: {unique_id}")

    def _emit_status(self, cell_id, board_status):
        """Emit board status change only if cycle is active."""
        if self._cycle_active:
            self.board_status_changed.emit(cell_id, board_status)

    def _mark_probe(self, cell_id, board_status, status):
        board_status.probe_status = status
        self._emit_status(cell_id, board_status)

    def _mark_program(self, cell_id, board_status, status):
        board_status.program_status = status
        self._emit_status(cell_id, board_status)
    
    def _mark_provision(self, cell_id, board_status, status):
        board_status.provision_status = status
        self._emit_status(cell_id, board_status)
    
    def _mark_test(self, cell_id, board_status, status):
        board_status.test_status = status
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
        """Update phase display - only emit if cycle is active."""
        log.info(f"Phase now: {phase_str}")
        if self._cycle_active:
            self.phase_changed.emit(phase_str)

    def _safe_emit_stats(self):
        """Emit stats_updated only if cycle is still active.
        
        This prevents orphaned asyncio tasks when the cycle has ended but
        emissions are still queued up.
        """
        if self._cycle_active:
            self.stats_updated.emit(self.stats.get_summary_text())

    async def _provision_board(self, col: int, row: int, board_status, cell_id):
        """Provision a board with unique identifiers and configuration.
        
        Executes the provisioning script defined in panel settings, sending
        commands to the target device and capturing responses.
        
        Args:
            col: Board column index
            row: Board row index
            board_status: BoardStatus object for this board
            cell_id: Cell ID for status updates
        """
        import time as time_module
        provision_start = time_module.perf_counter()
        log.debug(f"[_provision_board] Provisioning board [{col},{row}]")
        self.update_phase(f"Provisioning Board [{col}, {row}]...")
        
        # Get provisioning configuration from panel settings
        provision_config = self.panel_settings.get('provision', {})
        script_data = provision_config.get('script', {})
        custom_vars = provision_config.get('custom_variables', {})
        
        # Check if there's a script to execute
        if not script_data.get('steps'):
            log.debug(f"[_provision_board] No provisioning steps configured, skipping")
            self._mark_provision(cell_id, board_status, ProvisionStatus.SKIPPED)
            return
        
        # Mark as provisioning in progress
        self._mark_provision(cell_id, board_status, ProvisionStatus.PROVISIONING)
        
        # Build the provisioning script
        script = ProvisionScript.from_dict(script_data)
        
        # Build vision variables from QR scan if available
        vision_vars = {}
        if board_status.board_info and board_status.board_info.serial_number:
            vision_vars['serial_number'] = board_status.board_info.serial_number
        if board_status.qr_code:
            vision_vars['qr_raw'] = board_status.qr_code
        
        # Create variable context
        panel_name = self.panel_settings.get('name', 'unknown')
        context = VariableContext(
            row=row,
            col=col,
            panel_name=panel_name,
            vision_vars=vision_vars,
            custom_vars=custom_vars,
        )
        
        # Ensure target device is connected
        await self.target.connect()
        
        # Execute the provisioning script
        engine = ProvisioningEngine(verbose=True)
        result = await engine.execute(script, self.target.device, context)
        
        # Record provision time
        provision_time = time_module.perf_counter() - provision_start
        self.stats.record_board_time(col, row, 'provision', provision_time)
        
        # Build provision log from step results
        # Match step results to their definitions using step_index
        provision_log = []
        for sr in result.step_results:
            status = "✓" if sr.success else "✗"
            
            # Get step description from script definition
            step_idx = sr.step_index
            if step_idx < len(script.steps):
                step_def = script.steps[step_idx]
                # Use description if available, otherwise use send command or step number
                if step_def.description:
                    step_name = step_def.description
                elif step_def.send:
                    # Use the send command (truncated) as name
                    step_name = step_def.send[:40]
                    if len(step_def.send) > 40:
                        step_name += "..."
                else:
                    step_name = f"Step {step_idx + 1}"
            else:
                step_name = f"Step {step_idx + 1}"
            
            provision_log.append(f"[{status}] {step_name} ({sr.elapsed:.2f}s)")
            
            # Show captured variables on success
            if sr.captures:
                for k, v in sr.captures.items():
                    provision_log.append(f"  → {k}={v}")
            
            # Show error on failure
            if sr.error:
                provision_log.append(f"  ERROR: {sr.error}")
        
        # Ensure board_info exists (may not if vision was disabled)
        if not board_status.board_info:
            board_status.board_info = BoardInfo()
        
        if result.success:
            log.info(f"[_provision_board] Board [{col},{row}] provisioning complete in {provision_time:.2f}s")
            log.info(f"[_provision_board] Captures: {result.captures}")
            
            # Store captured data in board_info
            board_status.board_info.test_data.update(result.captures)
            board_status.board_info.provision_log = provision_log
            
            # Mark as completed
            self._mark_provision(cell_id, board_status, ProvisionStatus.COMPLETED)
        else:
            log.warning(f"[_provision_board] Board [{col},{row}] provisioning failed: {result.error}")
            # Store provisioning log even on failure
            board_status.board_info.provision_log = provision_log
            # Mark board as failed
            board_status.failure_reason = result.error
            self._mark_provision(cell_id, board_status, ProvisionStatus.FAILED)

    async def _test_board(self, col: int, row: int, board_status, cell_id):
        """Run automated tests on a board.
        
        This is a stub for future testing functionality.
        
        Args:
            col: Board column index
            row: Board row index
            board_status: BoardStatus object for this board
            cell_id: Cell ID for status updates
        """
        log.debug(f"[_test_board] Testing board [{col},{row}] (stub)")
        self.update_phase(f"Testing Board [{col}, {row}]...")
        
        # TODO: Implement test logic
        # - Run functional tests
        # - Validate board operation
        # - Record test results
        
        await asyncio.sleep(0.1)  # Placeholder
        log.debug(f"[_test_board] Board [{col},{row}] testing complete (stub)")

    async def _run_board(self, col: int, row: int):
        self.current_board = (col, row)
        board_status = self.get_board_status(col, row)
        cell_id = col * self.config.board_num_rows + row

        if [col, row] in self.config.skip_board_pos:
            log.info(f"SKIPPING col={col} row={row}")
            self._mark_probe(cell_id, board_status, ProbeStatus.SKIPPED)
            self._mark_program(cell_id, board_status, ProgramStatus.SKIPPED)
            self.current_board = None
            return
        
        # If board was already marked as skipped during QR scan phase, skip it
        if board_status.probe_status == ProbeStatus.SKIPPED:
            log.debug(f"[_run_board] Board [{col},{row}] already skipped (no QR code)")
            log.info(f"[Board {col},{row}] Skipped (no QR code)")
            self.current_board = None
            return

        # Calculate board position
        board_x = self.config.board_x + (col * self.config.board_col_width)
        board_y = self.config.board_y + (row * self.config.board_row_height)

        # Camera scanning is now done in _scan_all_boards_for_qr() before this method
        # Skip the camera code here - just proceed with probing
        
        # Now proceed with normal probing sequence - track timing
        probe_start = time.time()
        log.debug(f"[_run_board] Starting probe sequence for board [{col},{row}]")
        self._mark_probe(cell_id, board_status, ProbeStatus.PROBING)

        log.debug(f"[_run_board] Moving to board position ({board_x}, {board_y})")
        self.update_phase(f"Move to Board at [{col}, {row}]...")
        await self.motion.rapid_xy_abs(board_x, board_y)
        log.debug(f"[_run_board] Arrived at board position")

        log.debug(f"[_run_board] Starting probe operation")
        self.update_phase("Probing for board height...")
        try:
            dist_to_probe = await self.motion.do_probe()
            log.debug(f"[_run_board] Probe complete: dist_to_probe={dist_to_probe}")
            dist_to_board = dist_to_probe + self.config.probe_plane_to_board
            # Don't mark COMPLETED yet - wait until contact is verified
            
            # Record probe time (movement + probe operation)
            probe_time = time.time() - probe_start
            self.stats.record_board_time(col, row, 'probe', probe_time)
            self._safe_emit_stats()
            log.debug(f"[_run_board] Board [{col},{row}] probe time: {probe_time:.2f}s")
        except Exception as e:
            log.error(f"Probe failed: {e}")
            log.debug(f"[_run_board] Probe failed: {e}")
            board_status.failure_reason = f"Probe error: {e}"
            self._mark_probe(cell_id, board_status, ProbeStatus.FAILED)
            self._mark_program(cell_id, board_status, ProgramStatus.SKIPPED)
            self.stats.record_failure()
            self._safe_emit_stats()
            # SAFETY: Return to safe Z height before continuing to next board
            try:
                await self.motion.rapid_z_abs(0.0)
            except Exception:
                pass
            self.current_board = None
            return  # Soft-skip this board, continue cycle

        log.debug(f"[_run_board] Moving to safe height: {-1.0 * dist_to_probe}")
        self.update_phase("Move to safe height above board...")
        await self.motion.rapid_z_abs((-1.0 * dist_to_probe))
        log.debug(f"[_run_board] At safe height")

        log.debug(f"[_run_board] Checking for NO contact")
        self.update_phase("Check board is not contacted...")
        contact = await self.head.check_contact()
        log.debug(f"[_run_board] Contact check result: {contact}")
        if contact:
            error_msg = "Unexpected contact at safe height"
            log.info(f"[Board {col},{row}] ERROR: {error_msg}")
            log.debug(f"[_run_board] ERROR: {error_msg}")
            board_status.failure_reason = error_msg
            self._mark_probe(cell_id, board_status, ProbeStatus.FAILED)
            self._mark_program(cell_id, board_status, ProgramStatus.SKIPPED)
            # SAFETY: Already at safe height, just return
            return

        log.debug(f"[_run_board] Moving to board at distance: {-1.0 * dist_to_board}")
        self.update_phase("Move to board...")
        await self.motion.move_z_abs((-1.0 * dist_to_board), 200)
        log.debug(f"[_run_board] At board position")

        log.debug(f"[_run_board] Checking for contact WITH board")
        self.update_phase("Check for contact with board header...")
        contact = await self.head.check_contact()
        log.debug(f"[_run_board] Contact check result: {contact}")
        
        # If no contact, try small Y adjustments to improve contact reliability
        if not contact:
            log.debug(f"[_run_board] No contact at nominal position, trying Y adjustments...")
            self.update_phase("Adjusting position for contact...")
            
            # Try small Y movements using configured step: +step, -step, +2*step, -2*step
            step = self.config.contact_adjust_step
            y_adjustments = [step, -step, 2*step, -2*step]
            
            for y_offset in y_adjustments:
                log.debug(f"[_run_board] Trying Y offset: {y_offset}mm")
                # Move relative Y
                await self.motion.rapid_xy_rel(0, y_offset)
                
                # Check contact
                contact = await self.head.check_contact()
                log.debug(f"[_run_board] Contact check with Y offset {y_offset}mm: {contact}")
                
                if contact:
                    log.info(f"[Board {col},{row}] Contact established with Y offset {y_offset}mm")
                    log.debug(f"[_run_board] Contact successful with Y offset {y_offset}mm")
                    break
            else:
                # All adjustments failed - restore original position and fail
                log.debug(f"[_run_board] All Y adjustments failed, returning to nominal position")
                # Calculate total offset to return to nominal
                total_offset = sum(y_adjustments)
                if total_offset != 0:
                    await self.motion.rapid_xy_rel(0, -total_offset)
        
        if not contact:
            error_msg = "No contact with board header"
            log.info(f"[Board {col},{row}] ERROR: {error_msg}")
            log.debug(f"[_run_board] ERROR: {error_msg}")
            board_status.failure_reason = error_msg
            self._mark_probe(cell_id, board_status, ProbeStatus.FAILED)
            self._mark_program(cell_id, board_status, ProgramStatus.SKIPPED)
            self.stats.record_failure()
            self._safe_emit_stats()
            # SAFETY: Return to safe Z height before moving to next board
            await self.motion.rapid_z_abs(0.0)
            return

        # Contact verified - mark probe as completed
        self._mark_probe(cell_id, board_status, ProbeStatus.PASSED)

        # Start timing for this board (covers all phases)
        program_start = time.time()

        # Programming phase (if enabled)
        if self.config.programming_enabled:
            self.update_phase("Enabling programmer head power...")
            await self.head.set_power(True)
            await asyncio.sleep(1)
            self.update_phase("Enabling programmer head logic...")
            await self.head.set_logic(True)
            await asyncio.sleep(1)

            # Get enabled programming steps from panel settings
            enabled_steps = self._get_enabled_programmer_steps()
            log.debug(f"[_run_board] Enabled programmer steps: {enabled_steps}")
            
            if not enabled_steps:
                # No steps enabled - just mark as completed
                self._mark_program(cell_id, board_status, ProgramStatus.COMPLETED)
            else:
                # Determine status based on what steps are enabled
                if 'program' in enabled_steps:
                    self._mark_program(cell_id, board_status, ProgramStatus.PROGRAMMING)
                elif 'identify' in enabled_steps:
                    self._mark_program(cell_id, board_status, ProgramStatus.IDENTIFYING)
                else:
                    self._mark_program(cell_id, board_status, ProgramStatus.PROGRAMMING)
                
                try:
                    # Execute all enabled steps through the programmer plugin
                    success = await self.programmer.execute_sequence(enabled_steps)
                    log.debug(f"success={success}")
                    
                    # Determine final status
                    if success:
                        if 'program' in enabled_steps:
                            final_status = ProgramStatus.COMPLETED
                        elif 'identify' in enabled_steps and len(enabled_steps) == 1:
                            final_status = ProgramStatus.IDENTIFIED
                        else:
                            final_status = ProgramStatus.COMPLETED
                    else:
                        final_status = ProgramStatus.FAILED
                        board_status.failure_reason = "Programming failed"
                    
                    self._mark_program(cell_id, board_status, final_status)
                    
                    # If programming failed, skip remaining phases and return
                    if final_status == ProgramStatus.FAILED:
                        self._mark_provision(cell_id, board_status, ProvisionStatus.SKIPPED)
                        self._mark_test(cell_id, board_status, TestStatus.SKIPPED)
                        self.stats.record_failure()
                        self._safe_emit_stats()
                        # SAFETY: Return to safe Z height before continuing
                        await self.head.set_all(False)
                        await self.motion.rapid_z_abs(0.0)
                        self.current_board = None
                        return
                    
                except Exception as e:
                    log.error(f"Programming sequence failed: {e}")
                    board_status.failure_reason = f"Programming error: {e}"
                    self._mark_program(cell_id, board_status, ProgramStatus.FAILED)
                    self.stats.record_failure()
                    self._safe_emit_stats()
                    # SAFETY: Return to safe Z height before continuing to next board
                    await self.head.set_all(False)
                    await self.motion.rapid_z_abs(0.0)
                    self.current_board = None
                    return  # Soft-skip this board, continue cycle

                if success and 'program' in enabled_steps:
                    monitor_task = self.target.create_monitor_task()
                    await asyncio.sleep(5)
                    monitor_task.cancel()
        else:
            # Programming disabled - mark as skipped
            self._mark_program(cell_id, board_status, ProgramStatus.SKIPPED)

        # Provisioning phase (if enabled)
        if self.config.provision_enabled:
            await self._provision_board(col, row, board_status, cell_id)
        else:
            # Provisioning disabled - mark as skipped
            self._mark_provision(cell_id, board_status, ProvisionStatus.SKIPPED)
        
        # Test phase (if enabled)
        if self.config.test_enabled:
            await self._test_board(col, row, board_status, cell_id)

        await self.head.set_all(False)
        await asyncio.sleep(1)
        self.update_phase("Move to safe height...")
        await self.motion.rapid_z_abs(0.0)
        
        # Record programming time
        program_time = time.time() - program_start
        self.stats.record_board_time(col, row, 'program', program_time)
        self._safe_emit_stats()
        log.debug(f"[_run_board] Board [{col},{row}] program time: {program_time:.2f}s")

        self._emit_status(cell_id, board_status)
        self.current_board = None

    async def _run_from(self, start_col: int, start_row: int):
        for col in range(start_col, self.config.board_num_cols):
            row_start = start_row if col == start_col else 0
            for row in range(row_start, self.config.board_num_rows):
                await self._run_board(col, row)
    
    async def _scan_all_boards_for_qr(self):
        """Scan all boards with camera and mark those without QR codes as skipped."""
        log.debug("[_scan_all_boards_for_qr] Starting QR scan phase for all boards")
        log.info("[ProgBot] Starting QR scanning for all boards...")
        
        # Emit signal that QR scanning is starting
        self.qr_scan_started.emit()
        
        # Start preview once at the beginning (camera running at 4 FPS to reduce GIL contention)
        if hasattr(self, 'camera_preview') and self.camera_preview:
            from kivy.clock import Clock
            Clock.schedule_once(lambda dt: self.camera_preview.start_preview(), 0)
            await asyncio.sleep(0.15)
            log.debug("[_scan_all_boards_for_qr] Preview started for entire scan phase")
        
        log.debug(f"[_scan_all_boards_for_qr] board_num_cols={self.config.board_num_cols}, board_num_rows={self.config.board_num_rows}")
        
        try:
            for col in range(self.config.board_num_cols):
                for row in range(self.config.board_num_rows):
                    log.debug(f"[_scan_all_boards_for_qr] Processing board [{col},{row}]")
                    
                    # Skip if already marked to skip
                    if [col, row] in self.config.skip_board_pos:
                        log.debug(f"[_scan_all_boards_for_qr] Board [{col},{row}] is in skip list, skipping")
                        self.stats.record_skip()
                        continue
                    
                    board_status = self.get_board_status(col, row)
                    log.debug(f"[_scan_all_boards_for_qr] Got board_status for [{col},{row}]")
                    
                    cell_id = col * self.config.board_num_rows + row
                    
                    # Mark board as currently being scanned
                    log.debug(f"[_scan_all_boards_for_qr] Marking vision IN_PROGRESS for [{col},{row}]")
                    self._mark_vision(cell_id, board_status, VisionStatus.IN_PROGRESS)
                    log.debug(f"[_scan_all_boards_for_qr] Emitting status for [{col},{row}]")
                    self._emit_status(cell_id, board_status)
                    log.debug(f"[_scan_all_boards_for_qr] Status emitted for [{col},{row}]")
                    
                    # Calculate positions
                    board_x = self.config.board_x + (col * self.config.board_col_width)
                    board_y = self.config.board_y + (row * self.config.board_row_height)
                    # Camera position = board position + QR offset + camera offset
                    camera_x = board_x + self.config.qr_offset_x + self.config.camera_offset_x
                    camera_y = board_y + self.config.qr_offset_y + self.config.camera_offset_y
                    
                    log.debug(f"[_scan_all_boards_for_qr] Board [{col},{row}]: board=({board_x},{board_y}), qr_offset=({self.config.qr_offset_x},{self.config.qr_offset_y}), camera_offset=({self.config.camera_offset_x},{self.config.camera_offset_y}), final_camera=({camera_x},{camera_y})")
                    
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
                        self._safe_emit_stats()
                        log.debug(f"[_scan_all_boards_for_qr] Board [{col},{row}] QR scan time: {qr_scan_time:.2f}s")
                        
                        if qr_data:
                            # qr_data is now a tuple (data, image_bytes) from scan_qr_code
                            qr_serial = qr_data[0] if isinstance(qr_data, tuple) else qr_data
                            qr_image = qr_data[1] if isinstance(qr_data, tuple) and len(qr_data) > 1 else None
                            board_status.qr_code = qr_serial
                            
                            # Create and populate BoardInfo
                            import datetime
                            board_info = BoardInfo(serial_number=qr_serial)
                            board_info.qr_image = qr_image  # Store cropped QR image
                            board_info.timestamp_qr_scan = datetime.datetime.now().isoformat()
                            board_status.board_info = board_info
                            
                            log.debug(f"[_scan_all_boards_for_qr] Board [{col},{row}] QR: {qr_serial}, image: {len(qr_image) if qr_image else 0} bytes")
                            log.info(f"[Board {col},{row}] Serial Number: {qr_serial}")
                            
                            # Mark vision as passed (this emits status with qr_code and board_info)
                            self._mark_vision(cell_id, board_status, VisionStatus.PASSED)
                        else:
                            # No QR code - mark as skipped
                            log.debug(f"[_scan_all_boards_for_qr] Board [{col},{row}] No QR - marking as skipped")
                            log.info(f"[Board {col},{row}] No QR code - skipping board")
                            board_status.failure_reason = "No QR Code"
                            board_status.vision_status = VisionStatus.FAILED
                            board_status.probe_status = ProbeStatus.SKIPPED
                            board_status.program_status = ProgramStatus.SKIPPED
                            board_status.provision_status = ProvisionStatus.SKIPPED
                            board_status.test_status = TestStatus.SKIPPED
                            self.stats.record_skip()
                            self._emit_status(cell_id, board_status)
                    
                    except Exception as e:
                        log.debug(f"[_scan_all_boards_for_qr] Board [{col},{row}] Error: {e}")
                        log.info(f"[Board {col},{row}] QR scan error: {e} - skipping board")
                        import traceback
                        traceback.print_exc()
                        board_status.failure_reason = "QR Scan Error"
                        board_status.vision_status = VisionStatus.FAILED
                        board_status.probe_status = ProbeStatus.SKIPPED
                        board_status.program_status = ProgramStatus.SKIPPED
                        board_status.provision_status = ProvisionStatus.SKIPPED
                        board_status.test_status = TestStatus.SKIPPED
                        self.stats.record_failure()
                        self._emit_status(cell_id, board_status)
        
        except asyncio.CancelledError:
            # Stop camera preview if it's still active
            if hasattr(self, 'camera_preview') and self.camera_preview:
                self.camera_preview.stop_preview()
            log.debug("[_scan_all_boards_for_qr] Cancelled during QR scan")
            log.info("[ProgBot] QR scan cancelled")
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
        
        log.debug("[_scan_all_boards_for_qr] QR scan phase complete")
        log.info("[ProgBot] QR scanning complete. Starting probe/program cycle...")

    async def full_cycle(self):
        """Execute the complete programming cycle."""
        log.debug("[full_cycle] Starting full cycle")
        log.info("[ProgBot] Starting full cycle...")
        
        # Mark cycle as active to enable signal emissions
        self._cycle_active = True
        
        # Start cycle statistics
        self.stats.start_cycle()
        self._safe_emit_stats()
        
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
            
            # If vision phase is enabled and camera is available, scan all boards first
            if self.config.vision_enabled and self.vision and self.config.use_camera:
                # Reconnect camera if it was disconnected from previous cycle
                if self.vision.camera_process is None:
                    log.debug("[full_cycle] Camera was disconnected, reconnecting...")
                    try:
                        await asyncio.wait_for(self.vision.connect(), timeout=10.0)
                        log.debug("[full_cycle] Camera reconnected")
                    except Exception as e:
                        log.debug(f"[full_cycle] Camera reconnect failed: {e}")
                        log.warning(f"Warning: Camera reconnection failed: {e}")
                
                log.debug("[full_cycle] Starting vision scan phase for all boards")
                await self._scan_all_boards_for_qr()
            elif not self.config.vision_enabled:
                log.debug("[full_cycle] Vision phase disabled in panel settings")
            
            await self._run_from(0, 0)

            self.update_phase(f"Done with full cycle.")
            await self.motion.rapid_xy_abs(0, 300)
            await self.motion.motors_off()
            
            # Disconnect camera to release resources FIRST
            if hasattr(self, 'vision') and self.vision:
                log.debug("[full_cycle] Disconnecting camera after successful cycle...")
                await self.vision.disconnect()
                log.debug("[full_cycle] Camera disconnected")
            
            # Then cleanup camera preview
            if hasattr(self, 'camera_preview') and self.camera_preview:
                log.debug("[full_cycle] Stopping camera preview...")
                from kivy.clock import Clock
                Clock.schedule_once(lambda dt: self.camera_preview.stop_preview(), 0)
            
            log.debug("[full_cycle] Cycle completed successfully")
            log.info("[ProgBot] Cycle complete")
            
            # End cycle statistics - emit final stats then disable emissions
            self.stats.end_cycle()
            self._safe_emit_stats()
            self._cycle_active = False  # Prevent further emissions
            
            log.debug("[full_cycle] Cycle complete - cleanup done")

        except asyncio.CancelledError:
            log.debug("[full_cycle] Cycle cancelled")
            
            # Mark remaining boards as interrupted or skipped
            for col in range(self.config.board_num_cols):
                for row in range(self.config.board_num_rows):
                    board_status = self.get_board_status(col, row)
                    # Skip disabled boards
                    if not board_status.enabled:
                        continue
                    
                    # Skip boards that have already failed at any stage
                    if (board_status.vision_status.name == "FAILED" or
                        board_status.probe_status.name == "FAILED" or
                        board_status.program_status.name == "FAILED" or
                        board_status.provision_status.name == "FAILED" or
                        board_status.test_status.name == "FAILED"):
                        continue
                    
                    cell_id = col * self.config.board_num_rows + row
                    
                    # Terminal states that should not be modified
                    terminal_states = ("FAILED", "COMPLETED", "SKIPPED")
                    # Active states are: PROBING, PROGRAMMING, IDENTIFYING, PROVISIONING, TESTING
                    active_probe_states = ("PROBING",)
                    active_program_states = ("PROGRAMMING", "IDENTIFYING")
                    active_provision_states = ("PROVISIONING",)
                    active_test_states = ("TESTING",)
                    
                    # Only modify non-terminal states
                    if board_status.probe_status.name not in terminal_states:
                        if board_status.probe_status.name in active_probe_states:
                            self._mark_probe(cell_id, board_status, ProbeStatus.INTERRUPTED)
                        elif board_status.probe_status.name == "IDLE":
                            # Never started probing - mark as skipped
                            self._mark_probe(cell_id, board_status, ProbeStatus.SKIPPED)
                    
                    if board_status.program_status.name not in terminal_states:
                        if board_status.program_status.name in active_program_states:
                            self._mark_program(cell_id, board_status, ProgramStatus.INTERRUPTED)
                        elif board_status.program_status.name == "IDLE":
                            # Never started programming - mark as skipped
                            self._mark_program(cell_id, board_status, ProgramStatus.SKIPPED)
                    
                    if board_status.provision_status.name not in terminal_states:
                        if board_status.provision_status.name in active_provision_states:
                            self._mark_provision(cell_id, board_status, ProvisionStatus.INTERRUPTED)
                        elif board_status.provision_status.name == "IDLE":
                            # Never started provisioning - mark as skipped
                            self._mark_provision(cell_id, board_status, ProvisionStatus.SKIPPED)
                    
                    if board_status.test_status.name not in terminal_states:
                        if board_status.test_status.name in active_test_states:
                            self._mark_test(cell_id, board_status, TestStatus.INTERRUPTED)
                        elif board_status.test_status.name == "IDLE":
                            # Never started testing - mark as skipped
                            self._mark_test(cell_id, board_status, TestStatus.SKIPPED)
            
            # End cycle statistics even when cancelled - emit final stats then disable emissions
            self.stats.end_cycle()
            self._safe_emit_stats()
            self._cycle_active = False  # Prevent further emissions
            
            # Shield cleanup motions from cancellation - we must move the platform
            # to the accessible position even if the user is spamming stop
            try:
                log.debug("[full_cycle] Moving Z to safe height...")
                await asyncio.shield(self.motion.rapid_z_abs(0.0))
                log.debug("[full_cycle] Moving Y to accessible position...")
                await asyncio.shield(self.motion.rapid_xy_abs(0, 300))
                log.debug("[full_cycle] Platform moved to accessible position")
            except asyncio.CancelledError:
                # Cancellation during shielded operation - ignore and continue cleanup
                log.debug("[full_cycle] Cancellation during cleanup motion (shielded)")
            except Exception as e:
                log.debug(f"[full_cycle] Error during cleanup motion: {e}")
            
            log.debug("[full_cycle] Turning off motors...")
            await self.motion.motors_off()
            log.debug("[full_cycle] Motors off")
            
            # REMOVED: No longer disconnecting devices between cycles
            # Connections stay open for application lifetime
            
            # Stop camera preview (but keep camera subprocess running)
            if hasattr(self, 'camera_preview') and self.camera_preview:
                log.debug("[full_cycle] Stopping camera preview...")
                from kivy.clock import Clock
                Clock.schedule_once(lambda dt: self.camera_preview.stop_preview(), 0)
                log.debug("[full_cycle] Camera preview stop scheduled")
            
            # NOTE: Removed gc.collect() - it causes stop-the-world pause that breaks serial
            # connections and freezes the UI. Python's automatic GC will clean up when needed.
            log.debug("[full_cycle] Cleanup complete")
            log.info("Cycle canceled.")
            raise
        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"Exception: {e}")
            log.error(f"Traceback:\n{tb}")
            log.debug(f"[full_cycle] Exception: {e}")
            log.debug(f"[full_cycle] Traceback:\n{tb}")
            col, row = self.current_board if self.current_board else (None, None)
            
            # End cycle statistics even when exception occurs - emit final stats then disable emissions
            self.stats.end_cycle()
            self._safe_emit_stats()
            self._cycle_active = False  # Prevent further emissions
            
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
            log.debug("[full_cycle] Exception - cleanup done")
            raise

    async def process_single_board(self, position):
        """Process a single board at the given position.
        
        Args:
            position: (col, row) tuple for the board to process
        """
        col, row = position
        self.update_phase(f"Processing Board [{col}, {row}]")
        log.info(f"[process_single_board] Starting for position {position}")
        
        await self.motion.connect()
        await self.head.connect()
        await self.target.connect()
        await self.motion.init()
        
        try:
            await self._run_board(col, row)
            self.update_phase(f"Board [{col}, {row}] complete")
            
            # Return to safe position
            await self.motion.rapid_z_abs(0.0)
            await self.motion.rapid_xy_abs(0, 300)
            await self.motion.motors_off()
            
        except asyncio.CancelledError:
            log.info(f"[process_single_board] Cancelled for {position}")
            try:
                await asyncio.shield(self.motion.rapid_z_abs(0.0))
                await asyncio.shield(self.motion.rapid_xy_abs(0, 300))
            except:
                pass
            await self.motion.motors_off()
            raise
        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"[process_single_board] Error: {e}")
            self.error_occurred.emit({
                "message": str(e),
                "traceback": tb,
                "col": col,
                "row": row,
            })
            try:
                await self.motion.motors_off()
            except:
                pass
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
            # Shield cleanup motions from cancellation
            try:
                await asyncio.shield(self.motion.rapid_z_abs(0.0))
                await asyncio.shield(self.motion.rapid_xy_abs(0, 300))
            except asyncio.CancelledError:
                log.debug("[retry_board] Cancellation during cleanup motion (shielded)")
            except Exception:
                pass
            await self.motion.motors_off()
            log.info("Canceled during retry.")
            raise
        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"Retry exception: {e}")
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

