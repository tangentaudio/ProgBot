import time
import subprocess
import threading
import asyncio
import traceback
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from pynnex import with_emitters, emitter, listener
from programmer_controller import ProgrammerController
from head_controller import HeadController
from target_controller import TargetController
from motion_controller import MotionController
from device_discovery import DevicePortManager

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


class BoardStatus:
    """Tracks the status of a single board position."""
    
    def __init__(self, position):
        """Initialize board status.
        
        Args:
            position: Tuple (col, row) for this board position
        """
        self.position = position
        self.enabled = True
        self.probe_status = ProbeStatus.IDLE
        self.program_status = ProgramStatus.IDLE
    
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
       

    def __init__(self, config: Optional[Config] = None, programmer=None, head=None, target=None, motion=None, panel_settings=None, gui_port_picker=None):
        print("new progbot")
        self.config = config or Config()
        self.board_statuses = {}
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
            print(f"[ProgBot] ERROR during port configuration: {e}")
            import traceback
            traceback.print_exc()
            raise

    
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

        self._mark_probe(cell_id, board_status, ProbeStatus.PROBING)

        self.update_phase(f"Move to Board at [{col}, {row}]...")
        await self.motion.rapid_xy_abs(
            self.config.board_x + (col * self.config.board_col_width),
            self.config.board_y + (row * self.config.board_row_height),
        )

        self.update_phase("Probing for board height...")
        try:
            dist_to_probe = await self.motion.do_probe()
            dist_to_board = dist_to_probe + self.config.probe_plane_to_board
            self._mark_probe(cell_id, board_status, ProbeStatus.COMPLETED)
        except Exception as e:
            print(f"Probe failed: {e}")
            self._mark_probe(cell_id, board_status, ProbeStatus.FAILED)
            raise

        self.update_phase("Move to safe height above board...")
        await self.motion.rapid_z_abs((-1.0 * dist_to_probe))

        self.update_phase("Check board is not contacted...")
        contact = await self.head.check_contact()
        if contact:
            raise RuntimeError("should not have contact now")

        self.update_phase("Move to board...")
        await self.motion.move_z_abs((-1.0 * dist_to_board), 200)

        self.update_phase("Check for contact with board header...")
        contact = await self.head.check_contact()
        if not contact:
            raise RuntimeError("should have contact now")

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

        self._emit_status(cell_id, board_status)
        self.current_board = None

    async def _run_from(self, start_col: int, start_row: int):
        for col in range(start_col, self.config.board_num_cols):
            row_start = start_row if col == start_col else 0
            for row in range(row_start, self.config.board_num_rows):
                await self._run_board(col, row)

    async def full_cycle(self):
        # Configure ports first (in case not done yet)
        await self.configure_ports()
        
        # Discover devices first if enabled
        await self.discover_devices()
        
        self.update_phase("Opening devices...")
        await self.motion.connect()
        await self.head.connect()
        await self.target.connect()

        try:
            self.update_phase("Initializing devices...")
            await self.motion.init()

            await self._run_from(0, 0)

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
            print(f"Canceled.")
            raise
        except Exception as e:
            tb = traceback.format_exc()
            print(f"Exception: {e}")
            col, row = self.current_board if self.current_board else (None, None)
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

