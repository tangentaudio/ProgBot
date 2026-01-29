"""Cycle summary data classes and popup widget.

This module provides:
- CycleSummary and BoardResult dataclasses for collecting cycle results
- CycleSummaryPopup widget for displaying results after cycle completes
- CycleResultHandler ABC for future integration hooks

NOTE: Unicode/emoji characters require special font handling in Kivy.
The default font doesn't support most Unicode symbols. Either:
1. Use plain text instead of symbols (preferred for compatibility)
2. Use Kivy markup with explicit font path: [font=/path/to/font.ttf]symbol[/font]
See board_detail_popup.py for examples of font handling.
"""

import csv
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any

from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.graphics import Color, RoundedRectangle

log = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class BoardResult:
    """Result for a single board."""
    serial: str                           # QR serial (primary identifier)
    position: tuple                       # (col, row)
    cell_id: int                          # Grid cell index
    result: str                           # "PASSED", "FAILED", "SKIPPED"
    failure_reason: Optional[str] = None  # If failed
    failure_phase: Optional[str] = None   # Which phase failed
    captured_data: Dict[str, Any] = field(default_factory=dict)  # mac, bt_addr, etc.
    phase_times: Dict[str, float] = field(default_factory=dict)  # Timing per phase
    
    @property
    def total_time(self) -> float:
        """Total time across all phases."""
        return sum(self.phase_times.values())
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON export."""
        return {
            'serial': self.serial,
            'position': list(self.position),
            'result': self.result,
            'failure_reason': self.failure_reason,
            'failure_phase': self.failure_phase,
            'captured_data': self.captured_data,
            'phase_times': self.phase_times,
            'total_time': self.total_time,
        }


@dataclass
class CycleSummary:
    """Results from a completed programming cycle."""
    
    timestamp: datetime
    panel_name: str
    duration_seconds: float
    
    # Counts
    total_boards: int
    passed_count: int
    failed_count: int
    skipped_count: int
    
    # Per-board results
    boards: List[BoardResult] = field(default_factory=list)
    
    @property
    def yield_percent(self) -> float:
        """Calculate yield percentage."""
        if self.total_boards == 0:
            return 0.0
        return (self.passed_count / self.total_boards) * 100
    
    @property
    def failed_boards(self) -> List[BoardResult]:
        """Get list of failed boards."""
        return [b for b in self.boards if b.result == "FAILED"]
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON export."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'panel_name': self.panel_name,
            'duration_seconds': self.duration_seconds,
            'summary': {
                'total': self.total_boards,
                'passed': self.passed_count,
                'failed': self.failed_count,
                'skipped': self.skipped_count,
                'yield_percent': round(self.yield_percent, 1),
            },
            'boards': [b.to_dict() for b in self.boards],
        }
    
    def to_csv_rows(self) -> List[List[str]]:
        """Convert to CSV rows (header + data rows)."""
        # Collect all captured data keys across all boards
        all_keys = set()
        for b in self.boards:
            all_keys.update(b.captured_data.keys())
        all_keys = sorted(all_keys)
        
        # Header
        header = ['serial', 'position', 'result', 'failure_phase', 'failure_reason']
        header.extend(all_keys)
        
        # Data rows
        rows = [header]
        for b in self.boards:
            row = [
                b.serial,
                f"{b.position[0]},{b.position[1]}",
                b.result,
                b.failure_phase or '',
                b.failure_reason or '',
            ]
            for key in all_keys:
                row.append(str(b.captured_data.get(key, '')))
            rows.append(row)
        
        return rows


# =============================================================================
# Result Handlers (Integration Hooks)
# =============================================================================

class CycleResultHandler(ABC):
    """Base class for handling cycle results.
    
    Subclass this to integrate with external systems:
    - HTTP API
    - Database
    - Message queue
    """
    
    @abstractmethod
    async def on_cycle_complete(self, summary: CycleSummary) -> None:
        """Called when a cycle finishes."""
        pass
    
    @abstractmethod
    async def on_board_complete(self, result: BoardResult) -> None:
        """Called when each board finishes (for real-time updates)."""
        pass


class NullHandler(CycleResultHandler):
    """Default no-op handler."""
    
    async def on_cycle_complete(self, summary: CycleSummary) -> None:
        pass
    
    async def on_board_complete(self, result: BoardResult) -> None:
        pass


class FileExportHandler(CycleResultHandler):
    """Export cycle results to CSV/JSON files."""
    
    def __init__(self, export_dir: str, format: str = 'csv'):
        """
        Args:
            export_dir: Directory to save export files
            format: 'csv', 'json', or 'both'
        """
        self.export_dir = export_dir
        self.format = format
        os.makedirs(export_dir, exist_ok=True)
    
    async def on_cycle_complete(self, summary: CycleSummary) -> None:
        """Export cycle results to file(s)."""
        timestamp_str = summary.timestamp.strftime('%Y%m%d_%H%M%S')
        
        if self.format in ('csv', 'both'):
            csv_path = os.path.join(self.export_dir, f"{timestamp_str}_cycle.csv")
            self._write_csv(csv_path, summary)
            log.info(f"[FileExport] Wrote CSV: {csv_path}")
        
        if self.format in ('json', 'both'):
            json_path = os.path.join(self.export_dir, f"{timestamp_str}_cycle.json")
            self._write_json(json_path, summary)
            log.info(f"[FileExport] Wrote JSON: {json_path}")
    
    async def on_board_complete(self, result: BoardResult) -> None:
        """Not used for file export - only export at cycle end."""
        pass
    
    def _write_csv(self, path: str, summary: CycleSummary) -> None:
        """Write summary to CSV file."""
        rows = summary.to_csv_rows()
        with open(path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerows(rows)
    
    def _write_json(self, path: str, summary: CycleSummary) -> None:
        """Write summary to JSON file."""
        with open(path, 'w') as f:
            json.dump(summary.to_dict(), f, indent=2)


# =============================================================================
# Summary Popup Widget
# =============================================================================

class CycleSummaryPopup:
    """Popup widget displaying cycle results."""
    
    def __init__(self, on_rerun_failed=None, on_export=None):
        """
        Args:
            on_rerun_failed: Callback when "Re-run Failed" is clicked
            on_export: Callback when "Export" is clicked, receives format string
        """
        self.popup = None
        self.summary = None
        self.on_rerun_failed = on_rerun_failed
        self.on_export = on_export
    
    def show(self, summary: CycleSummary):
        """Show the summary popup."""
        self.summary = summary
        
        content = BoxLayout(orientation='vertical', spacing=10, padding=15)
        
        # Title
        title = Label(
            text="[b]CYCLE COMPLETE[/b]",
            markup=True,
            font_size='20sp',
            size_hint_y=None,
            height=40,
            color=[0.9, 0.9, 0.9, 1]
        )
        content.add_widget(title)
        
        # Stats row
        stats_row = self._build_stats_row(summary)
        content.add_widget(stats_row)
        
        # Duration and yield
        duration_mins = int(summary.duration_seconds // 60)
        duration_secs = int(summary.duration_seconds % 60)
        info_label = Label(
            text=f"Duration: {duration_mins}m {duration_secs}s    Yield: {summary.yield_percent:.1f}%",
            font_size='14sp',
            size_hint_y=None,
            height=30,
            color=[0.7, 0.7, 0.7, 1]
        )
        content.add_widget(info_label)
        
        # Failed boards section
        if summary.failed_boards:
            failed_section = self._build_failed_section(summary.failed_boards)
            content.add_widget(failed_section)
        else:
            # All passed message
            all_passed = Label(
                text="[color=#66FF66]All boards passed![/color]",
                markup=True,
                font_size='16sp',
                size_hint_y=None,
                height=50
            )
            content.add_widget(all_passed)
        
        # Spacer
        content.add_widget(BoxLayout(size_hint_y=1))
        
        # Action buttons
        buttons = self._build_buttons(summary)
        content.add_widget(buttons)
        
        # Create popup
        self.popup = Popup(
            title='',
            content=content,
            size_hint=(0.85, 0.75),
            auto_dismiss=True,
            separator_height=0
        )
        self.popup.open()
    
    def _build_stats_row(self, summary: CycleSummary) -> BoxLayout:
        """Build the pass/fail/skip stats row."""
        stats = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=80,
            spacing=15,
            padding=[20, 10]
        )
        
        # Passed box - use text instead of unicode checkmark
        passed_box = self._stat_box(
            "PASSED",
            str(summary.passed_count),
            [0.3, 0.6, 0.3, 1],  # Green
            [0.2, 0.4, 0.2, 1]
        )
        stats.add_widget(passed_box)
        
        # Failed box - use text instead of unicode X
        failed_box = self._stat_box(
            "FAILED",
            str(summary.failed_count),
            [0.6, 0.3, 0.3, 1],  # Red
            [0.4, 0.2, 0.2, 1]
        )
        stats.add_widget(failed_box)
        
        # Skipped box - use text instead of unicode circle
        skipped_box = self._stat_box(
            "SKIPPED",
            str(summary.skipped_count),
            [0.4, 0.4, 0.4, 1],  # Gray
            [0.25, 0.25, 0.25, 1]
        )
        stats.add_widget(skipped_box)
        
        return stats
    
    def _stat_box(self, label: str, value: str, text_color: list, bg_color: list) -> BoxLayout:
        """Create a stat display box."""
        box = BoxLayout(orientation='vertical', padding=5)
        
        with box.canvas.before:
            Color(*bg_color)
            box._rect = RoundedRectangle(pos=box.pos, size=box.size, radius=[8])
        box.bind(pos=lambda w, p: setattr(w._rect, 'pos', p))
        box.bind(size=lambda w, s: setattr(w._rect, 'size', s))
        
        value_label = Label(
            text=value,
            font_size='28sp',
            bold=True,
            color=text_color,
            size_hint_y=0.6
        )
        box.add_widget(value_label)
        
        name_label = Label(
            text=label,
            font_size='12sp',
            color=[0.7, 0.7, 0.7, 1],
            size_hint_y=0.4
        )
        box.add_widget(name_label)
        
        return box
    
    def _build_failed_section(self, failed_boards: List[BoardResult]) -> BoxLayout:
        """Build the failed boards list section."""
        section = BoxLayout(orientation='vertical', size_hint_y=None)
        section.bind(minimum_height=section.setter('height'))
        
        # Header
        header = Label(
            text="[b]FAILED BOARDS:[/b]",
            markup=True,
            font_size='14sp',
            halign='left',
            valign='middle',
            size_hint_y=None,
            height=30,
            color=[0.8, 0.5, 0.5, 1]
        )
        header.bind(size=header.setter('text_size'))
        section.add_widget(header)
        
        # Scrollable list
        scroll = ScrollView(size_hint_y=None, height=min(150, len(failed_boards) * 50))
        
        failed_list = BoxLayout(orientation='vertical', size_hint_y=None, spacing=5)
        failed_list.bind(minimum_height=failed_list.setter('height'))
        
        for board in failed_boards:
            item = self._build_failed_item(board)
            failed_list.add_widget(item)
        
        scroll.add_widget(failed_list)
        section.add_widget(scroll)
        
        return section
    
    def _build_failed_item(self, board: BoardResult) -> BoxLayout:
        """Build a single failed board item."""
        item = BoxLayout(orientation='vertical', size_hint_y=None, height=45, padding=[10, 2])
        
        with item.canvas.before:
            Color(0.25, 0.15, 0.15, 1)
            item._rect = RoundedRectangle(pos=item.pos, size=item.size, radius=[4])
        item.bind(pos=lambda w, p: setattr(w._rect, 'pos', p))
        item.bind(size=lambda w, s: setattr(w._rect, 'size', s))
        
        # Board identifier
        col, row = board.position
        board_text = f"Board {board.cell_id} [{col},{row}]"
        if board.serial:
            board_text += f" - {board.serial}"
        
        board_label = Label(
            text=board_text,
            font_size='13sp',
            halign='left',
            valign='middle',
            size_hint_y=0.5,
            color=[0.9, 0.7, 0.7, 1]
        )
        board_label.bind(size=board_label.setter('text_size'))
        item.add_widget(board_label)
        
        # Failure reason
        reason_text = f"{board.failure_phase}: {board.failure_reason}" if board.failure_phase else board.failure_reason
        reason_label = Label(
            text=reason_text or "Unknown error",
            font_size='11sp',
            halign='left',
            valign='middle',
            size_hint_y=0.5,
            color=[0.6, 0.5, 0.5, 1]
        )
        reason_label.bind(size=reason_label.setter('text_size'))
        item.add_widget(reason_label)
        
        return item
    
    def _build_buttons(self, summary: CycleSummary) -> BoxLayout:
        """Build action buttons row."""
        buttons = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=50,
            spacing=10
        )
        
        # Re-run Failed button (only if there are failures)
        if summary.failed_count > 0 and self.on_rerun_failed:
            rerun_btn = Button(
                text='Re-run Failed',
                font_size='14sp',
                size_hint_x=0.35,
                background_color=[0.3, 0.4, 0.5, 1]
            )
            rerun_btn.bind(on_press=self._on_rerun_failed)
            buttons.add_widget(rerun_btn)
        
        # Export CSV button
        export_btn = Button(
            text='Export CSV',
            font_size='14sp',
            size_hint_x=0.3,
            background_color=[0.3, 0.3, 0.4, 1]
        )
        export_btn.bind(on_press=self._on_export_csv)
        buttons.add_widget(export_btn)
        
        # Done button
        done_btn = Button(
            text='Done',
            font_size='14sp',
            size_hint_x=0.35,
            background_color=[0.25, 0.25, 0.3, 1]
        )
        done_btn.bind(on_release=self._on_done)
        buttons.add_widget(done_btn)
        log.info(f"[CycleSummary] Done button created and bound")
        
        return buttons
    
    def _on_rerun_failed(self, instance):
        """Handle Re-run Failed button click."""
        if self.popup:
            self.popup.dismiss()
        if self.on_rerun_failed and self.summary:
            failed_cell_ids = [b.cell_id for b in self.summary.failed_boards]
            self.on_rerun_failed(failed_cell_ids)
    
    def _on_export_csv(self, instance):
        """Handle Export CSV button click."""
        if self.on_export and self.summary:
            self.on_export(self.summary, 'csv')
    
    def _on_done(self, instance):
        """Handle Done button click."""
        log.info(f"[CycleSummary] Done button pressed, popup={self.popup}")
        if self.popup:
            self.popup.dismiss()
            log.info("[CycleSummary] Popup dismissed")
        else:
            log.warning("[CycleSummary] No popup to dismiss!")


# =============================================================================
# Helper Functions
# =============================================================================

def build_cycle_summary(
    board_statuses: dict,
    panel_name: str,
    start_time: datetime,
    end_time: datetime,
    board_times: dict,
    grid_rows: int,
    skipped_positions: list = None,
) -> CycleSummary:
    """Build a CycleSummary from the current board statuses.
    
    Args:
        board_statuses: Dict of (col, row) -> BoardStatus
        panel_name: Name of the panel configuration
        start_time: When the cycle started
        end_time: When the cycle ended
        board_times: Dict of (col, row) -> {phase: time}
        grid_rows: Number of rows in grid (for cell_id calculation)
        skipped_positions: List of [col, row] positions that were skipped/disabled
    
    Returns:
        CycleSummary with all results
    """
    from board_status import ProvisionStatus, TestStatus, ProgramStatus, ProbeStatus, VisionStatus
    
    boards = []
    passed = 0
    failed = 0
    skipped = 0
    
    # Count skipped positions (boards that were disabled before cycle)
    skipped_positions = skipped_positions or []
    skipped = len(skipped_positions)
    
    for (col, row), status in board_statuses.items():
        cell_id = col * grid_rows + row
        
        # Skip boards that were disabled (already counted in skipped_positions)
        if not status.enabled:
            continue
        
        # Skip boards that were never touched (all IDLE means they weren't processed)
        all_idle = (
            status.vision_status == VisionStatus.IDLE and
            status.probe_status == ProbeStatus.IDLE and
            status.program_status == ProgramStatus.IDLE and
            status.provision_status == ProvisionStatus.IDLE and
            status.test_status == TestStatus.IDLE
        )
        if all_idle:
            continue
        
        # Determine overall result
        result = "PASSED"
        failure_phase = None
        failure_reason = status.failure_reason
        
        # Check each phase for failures (in order)
        if status.vision_status == VisionStatus.FAILED:
            result = "FAILED"
            failure_phase = "Vision"
        elif status.probe_status == ProbeStatus.FAILED:
            result = "FAILED"
            failure_phase = "Contact"
        elif status.program_status == ProgramStatus.FAILED:
            result = "FAILED"
            failure_phase = "Program"
        elif status.provision_status == ProvisionStatus.FAILED:
            result = "FAILED"
            failure_phase = "Provisioning"
        elif status.test_status == TestStatus.FAILED:
            result = "FAILED"
            failure_phase = "Test"
        elif status.vision_status == VisionStatus.SKIPPED:
            result = "SKIPPED"
        
        # Get serial and captured data
        serial = ""
        captured_data = {}
        if status.board_info:
            serial = status.board_info.serial_number or ""
            captured_data = dict(status.board_info.test_data) if status.board_info.test_data else {}
            if status.board_info.device_id:
                captured_data['device_id'] = status.board_info.device_id
            if status.board_info.firmware_version:
                captured_data['firmware_version'] = status.board_info.firmware_version
        
        # Get timing
        phase_times = board_times.get((col, row), {})
        
        board_result = BoardResult(
            serial=serial,
            position=(col, row),
            cell_id=cell_id,
            result=result,
            failure_reason=failure_reason,
            failure_phase=failure_phase,
            captured_data=captured_data,
            phase_times=phase_times,
        )
        boards.append(board_result)
        
        # Count results
        if result == "PASSED":
            passed += 1
        elif result == "FAILED":
            failed += 1
        else:
            skipped += 1
    
    return CycleSummary(
        timestamp=end_time,
        panel_name=panel_name,
        duration_seconds=(end_time - start_time).total_seconds(),
        total_boards=len(boards),
        passed_count=passed,
        failed_count=failed,
        skipped_count=skipped,
        boards=boards,
    )
