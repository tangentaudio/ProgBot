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
    FAILED = "Program Failed"
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
    motion_port: str = '/dev/ttyACM0'
    motion_baud: int = 115200
    head_port: str = '/dev/ttyUSB0'
    head_baud: int = 9600
    target_port: str = '/dev/ttyACM1'
    target_baud: int = 115200


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
       

    def __init__(self, config: Optional[Config] = None, programmer=None, head=None, target=None, motion=None):
        print("new progbot")
        self.config = config or Config()
        self.board_statuses = {}
        self.programmer = programmer or ProgrammerController(self.update_phase)
        self.head = head or HeadController(self.update_phase, self.config.head_port, self.config.head_baud)
        self.target = target or TargetController(self.update_phase, self.config.target_port, self.config.target_baud)
        self.motion = motion or MotionController(self.update_phase, self.config.motion_port, self.config.motion_baud)
        self.current_board: Optional[Tuple[int, int]] = None
    
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

        self.update_phase(f"Move to Board [{col}, {row}]")
        await self.motion.rapid_xy_abs(
            self.config.board_x + (col * self.config.board_col_width),
            self.config.board_y + (row * self.config.board_row_height),
        )

        self.update_phase("Probe Height")
        try:
            dist_to_probe = await self.motion.do_probe()
            dist_to_board = dist_to_probe + self.config.probe_plane_to_board
            self._mark_probe(cell_id, board_status, ProbeStatus.COMPLETED)
        except Exception as e:
            print(f"Probe failed: {e}")
            self._mark_probe(cell_id, board_status, ProbeStatus.FAILED)
            raise

        self.update_phase("Move to safe height")
        await self.motion.rapid_z_abs((-1.0 * dist_to_probe))

        self.update_phase("Check NO contact")
        contact = await self.head.check_contact()
        if contact:
            raise RuntimeError("should not have contact now")

        self.update_phase("Move to board height")
        await self.motion.move_z_abs((-1.0 * dist_to_board), 200)

        self.update_phase("Check for contact")
        contact = await self.head.check_contact()
        if not contact:
            raise RuntimeError("should have contact now")

        self.update_phase("Enabling proghead power")
        await self.head.set_power(True)
        await asyncio.sleep(1)
        self.update_phase("Enabling proghead logic")
        await self.head.set_logic(True)
        await asyncio.sleep(1)

        if self.config.operation_mode == OperationMode.IDENTIFY_ONLY:
            self._mark_program(cell_id, board_status, ProgramStatus.IDENTIFYING)
            self.update_phase("Identifying device")
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
            self.update_phase("Programming device")
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
            self.update_phase("Move to safe height")
            await self.motion.rapid_z_abs(0.0)

        await self.head.set_all(False)
        await asyncio.sleep(1)
        self.update_phase("Move to safe height")
        await self.motion.rapid_z_abs(0.0)

        self._emit_status(cell_id, board_status)
        self.current_board = None

    async def _run_from(self, start_col: int, start_row: int):
        for col in range(start_col, self.config.board_num_cols):
            row_start = start_row if col == start_col else 0
            for row in range(row_start, self.config.board_num_rows):
                await self._run_board(col, row)

    async def full_cycle(self):
        self.update_phase("Opening Devices")
        await self.motion.connect()
        await self.head.connect()
        await self.target.connect()

        try:
            self.update_phase("Initializing Devices")
            await self.head.init()
            await self.motion.init()

            await self._run_from(0, 0)

            self.update_phase(f"Done Cycle")
            await self.motion.rapid_xy_abs(0, 300)
            await self.motion.motors_off()

        except asyncio.CancelledError:
            try:
                await self.motion.rapid_z_abs(0.0)
                await self.motion.rapid_xy_abs(0, 300)
            except Exception:
                pass
            await self.motion.motors_off()
            print(f"Canceled")
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
        await self.head.init()
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

            self.update_phase(f"Done Cycle")
            await self.motion.rapid_xy_abs(0, 300)
            await self.motion.motors_off()
        except asyncio.CancelledError:
            try:
                await self.motion.rapid_z_abs(0.0)
                await self.motion.rapid_xy_abs(0, 300)
            except Exception:
                pass
            await self.motion.motors_off()
            print(f"Canceled during retry")
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

