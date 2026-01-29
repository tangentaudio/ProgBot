"""GridCell widget - A custom grid cell for the board programming panel.

This module contains the GridCell class which displays individual board status
with visual indicators for each phase, serial number, and pass/fail status.
"""

import time

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.properties import StringProperty, BooleanProperty, ListProperty, NumericProperty
from kivy.clock import Clock
from kivy.lang.builder import Builder

from logger import get_logger
from board_status import (
    status_to_dot, get_status_bg_color, is_processing,
    DOT_PASS, DOT_FAIL, DOT_PENDING, DOT_DISABLED, SPINNER_FRAMES
)

log = get_logger(__name__)

# Load the GridCell KV layout
Builder.load_file('gridcell.kv')


class GridCell(ButtonBehavior, BoxLayout):
    """A custom grid cell button that toggles on long-press, shows details on tap.
    
    Displays:
    - Board number (cell_label)
    - Serial number from QR scan
    - Pass/fail result icon
    - Status dots for each phase (Vision, Contact, Program, Provision, Test)
    - Failure reason text
    - Pulsing animation when actively processing
    """
    
    # Basic properties
    cell_label = StringProperty("")
    cell_checked = BooleanProperty(True)
    cell_bg_color = ListProperty([0.5, 0.5, 0.5, 1])  # Default mid-gray (ON)
    cell_label_color = ListProperty([1, 1, 1, 1])  # Default white
    serial_number = StringProperty("")  # Scanned serial number from QR code
    
    # Result icon (large checkmark or X)
    result_icon = StringProperty("")  # "✓" or "✗" or ""
    result_icon_color = ListProperty([1, 1, 1, 1])  # Green for pass, red for fail
    
    # Status dots for each phase
    vision_dot = StringProperty("·")  # ● ○ ✗ · ◐
    contact_dot = StringProperty("·")  # Probe/contact phase
    program_dot = StringProperty("·")
    provision_dot = StringProperty("·")
    test_dot = StringProperty("·")
    
    # Phase enabled flags - controls whether dots show as disabled
    vision_enabled = BooleanProperty(True)
    contact_enabled = BooleanProperty(True)  # Probe/contact phase
    program_enabled = BooleanProperty(True)
    provision_enabled = BooleanProperty(True)
    test_enabled = BooleanProperty(True)
    
    # Failure reason text (shown when board fails)
    failure_reason = StringProperty("")
    
    # Animation properties
    pulse_alpha = NumericProperty(1.0)
    is_active = BooleanProperty(False)  # True when this board is being processed
    
    # Keep old properties for compatibility during transition
    status_line1 = StringProperty("")
    status_line2 = StringProperty("")
    status_line3 = StringProperty("")
    status_line4 = StringProperty("")
    
    # Track which dots are spinning
    _vision_spinning = BooleanProperty(False)
    _contact_spinning = BooleanProperty(False)
    _program_spinning = BooleanProperty(False)
    _provision_spinning = BooleanProperty(False)
    _test_spinning = BooleanProperty(False)
    _spinner_index = 0
    _spinner_event = None
    
    def __init__(self, cell_label="", cell_checked=True, bg_color=None, on_toggle_callback=None, **kwargs):
        super().__init__(**kwargs)
        self.base_cell_label = cell_label  # Store base label without (SKIPPED)
        self.cell_label = cell_label
        self.cell_checked = cell_checked
        self.always_release = True
        self.on_toggle_callback = on_toggle_callback  # Callback when cell is toggled
        self._pulse_anim = None
        self._long_press_triggered = False
        self._touch_start_time = None
        
        # Bind cell_checked to update background color
        self.bind(cell_checked=self._on_cell_checked_changed)
        self.bind(is_active=self._on_active_changed)
        
        # Bind spinning state changes to start/stop spinner
        self.bind(_vision_spinning=self._on_spinning_changed)
        self.bind(_contact_spinning=self._on_spinning_changed)
        self.bind(_program_spinning=self._on_spinning_changed)
        self.bind(_provision_spinning=self._on_spinning_changed)
        self.bind(_test_spinning=self._on_spinning_changed)
        
        # Set initial background color
        self._update_bg_color()
        
        if bg_color:
            self.cell_bg_color = bg_color
    
    # -------------------------------------------------------------------------
    # Touch handling
    # -------------------------------------------------------------------------
    
    def on_touch_down(self, touch):
        """Handle touch down - start tracking for long press."""
        if self.collide_point(*touch.pos):
            self._touch_start_time = time.time()
            self._long_press_triggered = False
            # Schedule long press check
            Clock.schedule_once(self._check_long_press, 0.5)
            return True
        return super().on_touch_down(touch)
    
    def _check_long_press(self, dt):
        """Check if this is a long press (for skip toggle)."""
        if self._touch_start_time is not None:
            elapsed = time.time() - self._touch_start_time
            if elapsed >= 0.5:
                self._long_press_triggered = True
                # Toggle skip state
                self.cell_checked = not self.cell_checked
    
    def on_touch_up(self, touch):
        """Handle touch up - show details on tap, skip already handled by long press."""
        if self.collide_point(*touch.pos):
            Clock.unschedule(self._check_long_press)
            if not self._long_press_triggered and self._touch_start_time is not None:
                # Short tap - show detail popup
                self._show_detail_popup()
            self._touch_start_time = None
            return True
        return super().on_touch_up(touch)
    
    def _show_detail_popup(self):
        """Show the board detail popup."""
        from kivy.app import App
        app = App.get_running_app()
        if app and hasattr(app, 'show_board_detail_popup'):
            app.show_board_detail_popup(self)
    
    def on_press(self):
        """Override - we handle press in on_touch_down/up now."""
        pass
    
    # -------------------------------------------------------------------------
    # Pulse animation (active board indicator)
    # -------------------------------------------------------------------------
    
    def _on_active_changed(self, instance, value):
        """Start or stop pulse animation when active state changes."""
        if value:
            self._start_pulse()
        else:
            self._stop_pulse()
    
    def _start_pulse(self):
        """Start the pulsing animation."""
        from kivy.animation import Animation
        if self._pulse_anim:
            self._pulse_anim.cancel(self)
        
        # Create repeating pulse animation
        self._pulse_anim = Animation(pulse_alpha=0.7, duration=0.8) + Animation(pulse_alpha=1.0, duration=0.8)
        self._pulse_anim.repeat = True
        self._pulse_anim.start(self)
    
    def _stop_pulse(self):
        """Stop the pulsing animation."""
        if self._pulse_anim:
            self._pulse_anim.cancel(self)
            self._pulse_anim = None
        self.pulse_alpha = 1.0
    
    # -------------------------------------------------------------------------
    # Cell state management
    # -------------------------------------------------------------------------
    
    def _on_cell_checked_changed(self, instance, value):
        """Update background color and label when cell_checked changes."""
        # Skip if in batch update mode
        if getattr(self, '_batch_update', False):
            return
        self._update_bg_color()
        # Update label color based on checked state
        if self.cell_checked:
            self.cell_label_color = [1, 1, 1, 1]  # White when enabled
        else:
            self.cell_label_color = [0.4, 0.4, 0.4, 1]  # Dark gray when skipped
        # Call the callback if provided
        if self.on_toggle_callback:
            self.on_toggle_callback()
    
    def set_state_batch(self, checked, bg_color=None, label=None):
        """Set cell state without triggering callbacks or redundant updates.
        
        Use this for bulk operations to avoid per-cell redraws and settings saves.
        """
        self._batch_update = True
        self.cell_checked = checked
        if bg_color is not None:
            self.cell_bg_color = bg_color
        if label is not None:
            self.cell_label = label
        self._batch_update = False
    
    def _update_bg_color(self):
        """Set background color based on cell_checked state."""
        if self.cell_checked:
            # Mid-gray when ON
            self.cell_bg_color = [0.5, 0.5, 0.5, 1]
        else:
            # Black when OFF
            self.cell_bg_color = [0, 0, 0, 1]
    
    # -------------------------------------------------------------------------
    # Status update from BoardStatus
    # -------------------------------------------------------------------------
    
    def update_status(self, board_status):
        """Update cell status from BoardStatus object.
        
        Args:
            board_status: BoardStatus instance with probe, program, provision, and test status
        """
        try:
            # Keep old status lines for compatibility
            status_line1, status_line2, status_line3, status_line4 = board_status.status_text
            self.status_line1 = status_line1
            self.status_line2 = status_line2
            self.status_line3 = status_line3
            self.status_line4 = status_line4
            
            # Update serial number display based on vision status
            if board_status.board_info and board_status.board_info.serial_number:
                self.serial_number = board_status.board_info.serial_number
            elif board_status.vision_status.name == "FAILED":
                self.serial_number = "FAIL"
            elif board_status.vision_status.name in ("IN_PROGRESS", "IDLE"):
                self.serial_number = ""
            else:
                self.serial_number = ""
            
            # Update status dots
            self._update_dots(board_status)
            
            # Update result icon
            self._update_result_icon(board_status)
            
            # Update is_active for pulsing animation (use centralized function)
            self.is_active = is_processing(board_status)
            
            # Update background color based on status (use centralized function)
            self.cell_bg_color = get_status_bg_color(board_status)
            
        except Exception as e:
            log.error(f"[GridCell] Error updating status: {e}")
    
    # -------------------------------------------------------------------------
    # Status dots
    # -------------------------------------------------------------------------
    
    def _update_dots(self, board_status):
        """Update the status dots based on board status (uses centralized status_to_dot)."""
        # Vision dot
        dot, spinning = status_to_dot(
            board_status.vision_status.name, 
            self.vision_enabled,
            self._spinner_index
        )
        self.vision_dot = dot
        self._vision_spinning = spinning
        
        # Contact dot (probe phase)
        dot, spinning = status_to_dot(
            board_status.probe_status.name, 
            self.contact_enabled,
            self._spinner_index
        )
        self.contact_dot = dot
        self._contact_spinning = spinning
        
        # Program dot (programming only, not probe)
        dot, spinning = status_to_dot(
            board_status.program_status.name, 
            self.program_enabled,
            self._spinner_index
        )
        self.program_dot = dot
        self._program_spinning = spinning
        
        # Provision dot
        dot, spinning = status_to_dot(
            board_status.provision_status.name, 
            self.provision_enabled,
            self._spinner_index
        )
        self.provision_dot = dot
        self._provision_spinning = spinning
        
        # Test dot
        dot, spinning = status_to_dot(
            board_status.test_status.name, 
            self.test_enabled,
            self._spinner_index
        )
        self.test_dot = dot
        self._test_spinning = spinning
    
    # -------------------------------------------------------------------------
    # Spinner animation
    # -------------------------------------------------------------------------
    
    def _on_spinning_changed(self, instance, value):
        """Start or stop spinner animation when any dot starts/stops spinning."""
        any_spinning = (self._vision_spinning or self._contact_spinning or 
                       self._program_spinning or self._provision_spinning or 
                       self._test_spinning)
        if any_spinning and not self._spinner_event:
            self._start_spinner()
        elif not any_spinning and self._spinner_event:
            self._stop_spinner()
    
    def _start_spinner(self):
        """Start the spinner animation timer."""
        if not self._spinner_event:
            self._spinner_event = Clock.schedule_interval(self._update_spinner, 0.1)
    
    def _stop_spinner(self):
        """Stop the spinner animation timer."""
        if self._spinner_event:
            self._spinner_event.cancel()
            self._spinner_event = None
    
    def _update_spinner(self, dt):
        """Advance spinner to next frame and update spinning dots."""
        self._spinner_index = (self._spinner_index + 1) % len(SPINNER_FRAMES)
        frame = SPINNER_FRAMES[self._spinner_index]
        
        if self._vision_spinning:
            self.vision_dot = frame
        if self._contact_spinning:
            self.contact_dot = frame
        if self._program_spinning:
            self.program_dot = frame
        if self._provision_spinning:
            self.provision_dot = frame
        if self._test_spinning:
            self.test_dot = frame
    
    # -------------------------------------------------------------------------
    # Result icon
    # -------------------------------------------------------------------------
    
    def _update_result_icon(self, board_status):
        """Update the large result icon (checkmark or X)."""
        # Check if any phase failed
        has_failure = (
            board_status.vision_status.name == "FAILED" or
            board_status.probe_status.name == "FAILED" or
            board_status.program_status.name == "FAILED" or
            board_status.provision_status.name == "FAILED" or
            board_status.test_status.name == "FAILED"
        )
        
        # Check if all enabled phases passed
        all_passed = True
        if self.vision_enabled and board_status.vision_status.name not in ("PASSED", "COMPLETED"):
            all_passed = False
        if self.program_enabled and board_status.program_status.name not in ("COMPLETED", "IDENTIFIED"):
            all_passed = False
        if self.provision_enabled and board_status.provision_status.name != "COMPLETED":
            all_passed = False
        if self.test_enabled and board_status.test_status.name != "COMPLETED":
            all_passed = False
        
        if has_failure:
            self.result_icon = "✖"
            self.result_icon_color = [1, 0.3, 0.3, 1]  # Red
            # Set failure reason from board status
            self.failure_reason = board_status.failure_reason or ""
        elif all_passed:
            self.result_icon = "✔"
            self.result_icon_color = [0.3, 1, 0.3, 1]  # Green
            self.failure_reason = ""
        else:
            self.result_icon = ""
            self.result_icon_color = [1, 1, 1, 1]
            self.failure_reason = ""
