import os
os.environ['KCFG_INPUT_MOUSE'] = 'mouse,disable_on_activity'

# Initialize logging FIRST before any other imports that might log
from logger import setup_logging, get_logger, LOG_FILE_PATH
setup_logging()
log = get_logger(__name__)

def dump_diagnostics(label=""):
    """Dump system diagnostics to debug log."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        tasks = asyncio.all_tasks(loop)
        pending = [t for t in tasks if not t.done()]
        log.debug(f"[DIAG {label}] Asyncio tasks: {len(tasks)} total, {len(pending)} pending")
        for t in pending[:10]:  # Log first 10 pending tasks
            log.debug(f"[DIAG {label}]   Task: {t.get_name()} - {t.get_coro().__qualname__ if t.get_coro() else 'no coro'}")
    except Exception as e:
        log.debug(f"[DIAG {label}] Error getting tasks: {e}")
    
    try:
        from kivy.clock import Clock
        # Count scheduled events
        events = Clock.get_events()
        log.debug(f"[DIAG {label}] Clock events scheduled: {len(events)}")
    except Exception as e:
        log.debug(f"[DIAG {label}] Error getting clock events: {e}")

from kivy.config import Config

#Config.set('graphics', 'width', 800)
#Config.set('graphics', 'height', 415)
#Config.set('graphics', 'resizable', 0)
Config.set('graphics', 'fullscreen', 'auto')
Config.set('graphics', 'maxfps', 30)  # 30 FPS for smooth UI updates
Config.set('graphics', 'multisamples', 4)  # Enable 4x MSAA for smooth rounded corners
Config.set('graphics', 'vsync', 0)  # Disable vsync to reduce frame timing overhead
Config.set('kivy', 'keyboard_mode', 'systemanddock') 

# Enable font anti-aliasing application-wide by patching CoreLabel
from kivy.core.text import Label as CoreLabel
_original_label_init = CoreLabel.__init__
def _patched_label_init(self, *args, **kwargs):
    kwargs.setdefault('font_blended', True)
    kwargs.setdefault('font_hinting', 'normal')
    _original_label_init(self, *args, **kwargs)
CoreLabel.__init__ = _patched_label_init

# Register Noto Sans as default font with Symbol fallback for Unicode support
from kivy.core.text import LabelBase
NOTO_SANS_FONT = '/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf'
NOTO_SYMBOLS_FONT = '/usr/share/fonts/truetype/noto/NotoSansSymbols-Regular.ttf'
NOTO_SYMBOLS2_FONT = '/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf'
DEJAVU_SANS_FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'

# Try Noto Sans first (modern, looks like Roboto), with fallbacks for symbols
if os.path.exists(NOTO_SANS_FONT):
    log.info(f"Font: Primary font found: {NOTO_SANS_FONT}")
    
    # Register Noto Sans as primary font
    LabelBase.register(name='NotoSans', fn_regular=NOTO_SANS_FONT)
    LabelBase.register(name='Roboto', fn_regular=NOTO_SANS_FONT)
    log.info("Font: Registered 'Roboto' (app-wide default) -> Noto Sans")
    
    # Register symbol fonts separately so Kivy can find glyphs
    # Note: Kivy doesn't support explicit fallback chains, but registered fonts
    # with missing glyphs will automatically fall back to system fonts
    symbol_fonts_registered = 0
    if os.path.exists(NOTO_SYMBOLS_FONT):
        try:
            LabelBase.register(name='NotoSansSymbols', fn_regular=NOTO_SYMBOLS_FONT)
            log.info(f"Font: Registered symbol font 1: {NOTO_SYMBOLS_FONT}")
            symbol_fonts_registered += 1
        except Exception as e:
            log.debug(f"Font: Could not register {NOTO_SYMBOLS_FONT}: {e}")
    if os.path.exists(NOTO_SYMBOLS2_FONT):
        try:
            LabelBase.register(name='NotoSansSymbols2', fn_regular=NOTO_SYMBOLS2_FONT)
            log.info(f"Font: Registered symbol font 2: {NOTO_SYMBOLS2_FONT}")
            symbol_fonts_registered += 1
        except Exception as e:
            log.debug(f"Font: Could not register {NOTO_SYMBOLS2_FONT}: {e}")
    
    log.info(f"Font: Noto Sans active with {symbol_fonts_registered} symbol fonts available")
    
elif os.path.exists(DEJAVU_SANS_FONT):
    # Fallback to DejaVu Sans if Noto not available
    log.info(f"Font: Primary font (Noto Sans) not found, using fallback: {DEJAVU_SANS_FONT}")
    LabelBase.register(name='DejaVuSans', fn_regular=DEJAVU_SANS_FONT)
    LabelBase.register(name='Roboto', fn_regular=DEJAVU_SANS_FONT)
    log.info("Font: Registered 'Roboto' (app-wide default) -> DejaVu Sans")
else:
    log.warning("Font: No custom fonts found, using Kivy defaults")

import sys
import asyncio
import logging

# Suppress pynnex debug/trace logging which creates significant overhead
# Set before importing pynnex to ensure it takes effect
logging.getLogger('pynnex').setLevel(logging.WARNING)
logging.getLogger('pynnex.emitter').setLevel(logging.WARNING)
logging.getLogger('pynnex.listener').setLevel(logging.WARNING)
logging.getLogger('pynnex.emitter.trace').setLevel(logging.WARNING)
logging.getLogger('pynnex.listener.trace').setLevel(logging.WARNING)

from pynnex import with_emitters, emitter, listener
from kivy.app import App
from kivy.lang.builder import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.behaviors.focus import FocusBehavior
from kivy.uix.recycleview.layout import LayoutSelectionBehavior
from kivy.properties import StringProperty, BooleanProperty, ListProperty
from settings import get_settings
from kivy.factory import Factory
from kivy.uix.textinput import TextInput
from kivy.logger import Logger
from kivy.effects.scroll import ScrollEffect
from kivy.clock import Clock
from kivy.properties import StringProperty, BooleanProperty, ListProperty
from serial_port_selector import SerialPortSelector
import os

import sequence
from panel_settings import get_panel_settings, find_panel_files
from numpad_keyboard import switch_keyboard_layout
from panel_setup_dialog import PanelSetupController
from config_settings_dialog import ConfigSettingsController
from settings_handlers import SettingsHandlersMixin
from panel_file_manager import PanelFileManagerMixin

class OutputCapture:
    """Captures print/stderr output and routes to the logging system.
    
    This intercepts print() calls and routes them through Python logging
    so they appear in the log file with proper formatting.
    """
    def __init__(self):
        self.original_stdout = sys.__stdout__
        self.original_stderr = sys.__stderr__
        self._print_logger = get_logger('print')
    
    def write(self, text):
        """Route print output to logging system."""
        # Skip empty or whitespace-only text
        text = text.rstrip('\n\r')
        if not text or not text.strip():
            return
        # Route through logging (will go to file and console)
        self._print_logger.info(text)
    
    def flush(self):
        pass


# Capture print() statements and route to logging
output_capture = OutputCapture()
sys.stdout = output_capture
sys.stderr = output_capture


class GridCell(ButtonBehavior, BoxLayout):
    """A custom grid cell button that toggles on press."""
    cell_label = StringProperty("")
    cell_checked = BooleanProperty(True)
    cell_bg_color = ListProperty([0.5, 0.5, 0.5, 1])  # Default mid-gray (ON)
    cell_label_color = ListProperty([1, 1, 1, 1])  # Default white
    status_line1 = StringProperty("")  # First line of status (probe status)
    status_line2 = StringProperty("")  # Second line of status (program status)
    status_line3 = StringProperty("")  # Third line of status (provision status)
    status_line4 = StringProperty("")  # Fourth line of status (test status)
    serial_number = StringProperty("")  # Scanned serial number from QR code
    
    # Phase enabled flags - controls dimming of labels when phase is disabled
    vision_enabled = BooleanProperty(True)
    probe_enabled = BooleanProperty(True)  # Probe follows vision
    program_enabled = BooleanProperty(True)
    provision_enabled = BooleanProperty(True)
    test_enabled = BooleanProperty(True)
    
    def __init__(self, cell_label="", cell_checked=True, bg_color=None, on_toggle_callback=None, **kwargs):
        super().__init__(**kwargs)
        self.base_cell_label = cell_label  # Store base label without (SKIPPED)
        self.cell_label = cell_label
        self.cell_checked = cell_checked
        self.always_release = True
        self.on_toggle_callback = on_toggle_callback  # Callback when cell is toggled
        
        # Bind cell_checked to update background color
        self.bind(cell_checked=self._on_cell_checked_changed)
        
        # Set initial background color
        self._update_bg_color()
        
        if bg_color:
            self.cell_bg_color = bg_color
    
    def on_press(self):
        """Toggle cell_checked when pressed."""
        self.cell_checked = not self.cell_checked
    
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
    
    def update_status(self, board_status):
        """Update cell status from BoardStatus object.
        
        Args:
            board_status: BoardStatus instance with probe, program, provision, and test status
        """
        try:
            status_line1, status_line2, status_line3, status_line4 = board_status.status_text
            self.status_line1 = status_line1
            self.status_line2 = status_line2
            self.status_line3 = status_line3
            self.status_line4 = status_line4
            
            # Update serial number display based on vision status
            if board_status.board_info and board_status.board_info.serial_number:
                # We have a scanned serial number
                self.serial_number = board_status.board_info.serial_number
            elif board_status.vision_status.name == "FAILED":
                # Vision scan failed - show shortened failure message
                self.serial_number = "FAIL"
            elif board_status.vision_status.name in ("IN_PROGRESS", "IDLE"):
                # Not yet scanned or currently scanning
                self.serial_number = ""
            else:
                # Other states (PASSED but no serial number somehow)
                self.serial_number = ""
            
            # Update background color based on status
            # Priority order: disabled > active operations > failures > interrupted > skipped > default
            if not board_status.enabled:
                # Hard skip - user disabled this board
                self.cell_bg_color = [0, 0, 0, 1]  # Black for hard skip (user disabled)
            elif (board_status.program_status.name == "INTERRUPTED" or 
                  board_status.probe_status.name == "INTERRUPTED" or
                  board_status.provision_status.name == "INTERRUPTED" or
                  board_status.test_status.name == "INTERRUPTED"):
                # Cycle was stopped/cancelled while this board was pending or in progress
                self.cell_bg_color = [1, 0.5, 0, 1]  # Orange for interrupted
            elif board_status.test_status.name == "COMPLETED":
                self.cell_bg_color = [0, 0.8, 0, 1]  # Bright green when fully tested
            elif board_status.provision_status.name == "COMPLETED":
                self.cell_bg_color = [0, 0.6, 0, 1]  # Medium green when provisioned
            elif board_status.program_status.name == "IDENTIFIED":
                self.cell_bg_color = [1, 0, 1, 1]  # Purple when identified
            elif board_status.program_status.name == "COMPLETED":
                self.cell_bg_color = [0, 0.5, 0, 1]  # Dark green when programmed (not yet provisioned)
            elif board_status.test_status.name == "FAILED":
                self.cell_bg_color = [1, 0, 0, 1]  # Red on test failure
            elif board_status.provision_status.name == "FAILED":
                self.cell_bg_color = [1, 0, 0, 1]  # Red on provision failure
            elif board_status.program_status.name == "FAILED":
                self.cell_bg_color = [1, 0, 0, 1]  # Red on programming failure
            elif board_status.probe_status.name == "FAILED":
                self.cell_bg_color = [1, 0, 0, 1]  # Red on probe failure
            elif board_status.vision_status.name == "FAILED":
                self.cell_bg_color = [0.5, 0, 0, 1]  # Dark red when QR failed
            elif (board_status.program_status.name == "SKIPPED" or 
                  board_status.probe_status.name == "SKIPPED" or
                  board_status.provision_status.name == "SKIPPED" or
                  board_status.test_status.name == "SKIPPED"):
                # Soft skip - failed at an earlier step, marked skipped for remaining steps
                # Keep red to indicate there was a failure
                self.cell_bg_color = [1, 0, 0, 1]  # Red for soft skip (error occurred)
            elif board_status.test_status.name == "TESTING":
                self.cell_bg_color = [0, 1, 1, 1]  # Cyan while testing
            elif board_status.provision_status.name == "PROVISIONING":
                self.cell_bg_color = [0.5, 1, 0.5, 1]  # Light green while provisioning
            elif board_status.program_status.name in ("PROGRAMMING", "IDENTIFYING"):
                self.cell_bg_color = [1, 1, 0, 1]  # Yellow while programming or identifying
            elif board_status.probe_status.name == "PROBING":
                self.cell_bg_color = [0, 1, 1, 1]  # Cyan while probing
            elif board_status.vision_status.name == "IN_PROGRESS":
                self.cell_bg_color = [0.5, 0.5, 1, 1]  # Light blue while scanning
            elif board_status.vision_status.name == "PASSED":
                self.cell_bg_color = [0, 0.7, 0.7, 1]  # Teal when QR detected
            else:
                self.cell_bg_color = [0.5, 0.5, 0.5, 1]  # Default mid-gray
        except Exception as e:
            log.error(f"[GridCell] Error updating status: {e}")

class LogViewer(ScrollView):
    """Log viewer that tails a log file when visible (tail -f style).
    
    Supports filtering by log level (DEBUG, INFO, WARNING, ERROR).
    """
    
    # Log level filter - show this level and above
    LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR']
    
    def __init__(self, **kwargs):
        kwargs.setdefault('effect_cls', ScrollEffect)
        super().__init__(**kwargs)
        self.log_text = None
        self._tail_event = None
        self._file_pos = 0  # Track position in file for incremental reads
        self._is_tailing = False
        self._filter_level = 'INFO'  # Default to INFO and above
        self._all_lines = []  # Store all lines for filtering
        # Find log_text TextInput in children after build
        Clock.schedule_once(self._setup_log_text, 0)

    def _setup_log_text(self, dt):
        """Find the log_text TextInput widget."""
        # First check direct children of this ScrollView
        for child in self.children:
            if isinstance(child, TextInput):
                self.log_text = child
                break
        
        # Fallback: check ids
        if not self.log_text:
            self.log_text = self.ids.get('log_text')
        
        if self.log_text:
            self.log_text.bind(minimum_height=self.log_text.setter('height'))

    def set_filter_level(self, level: str):
        """Set the minimum log level to display.
        
        Args:
            level: One of 'DEBUG', 'INFO', 'WARNING', 'ERROR'
        """
        if level in self.LOG_LEVELS:
            self._filter_level = level
            self._apply_filter()
    
    def _should_show_line(self, line: str) -> bool:
        """Check if a log line should be shown based on current filter."""
        filter_idx = self.LOG_LEVELS.index(self._filter_level)
        for i, level in enumerate(self.LOG_LEVELS):
            if f'[{level}]' in line:
                return i >= filter_idx
        # Lines without a level marker are always shown
        return True
    
    def _apply_filter(self):
        """Apply the current filter to all stored lines."""
        if not self.log_text:
            return
        filtered = [line for line in self._all_lines if self._should_show_line(line)]
        # Keep last 300 filtered lines
        if len(filtered) > 300:
            filtered = filtered[-300:]
        self.log_text.text = '\n'.join(filtered)
        self.scroll_to_bottom()

    def start_tailing(self):
        """Start tailing the log file (call when log viewer becomes visible)."""
        if self._is_tailing:
            return
        self._is_tailing = True
        
        # Load existing content first (last 500 lines, filter to 300)
        self._load_initial_content()
        
        # Schedule periodic tail updates
        self._tail_event = Clock.schedule_interval(self._tail_update, 0.5)  # Update every 500ms
    
    def stop_tailing(self):
        """Stop tailing the log file (call when log viewer is hidden)."""
        self._is_tailing = False
        if self._tail_event:
            self._tail_event.cancel()
            self._tail_event = None
    
    def _load_initial_content(self):
        """Load the last N lines from the log file."""
        if not self.log_text:
            return
        try:
            with open(LOG_FILE_PATH, 'r') as f:
                # Read all and get last 500 lines
                content = f.read()
                lines = content.split('\n')
                if len(lines) > 500:
                    lines = lines[-500:]
                self._all_lines = lines
                # Apply filter
                self._apply_filter()
                # Remember file position for incremental reads
                f.seek(0, 2)  # Seek to end
                self._file_pos = f.tell()
        except FileNotFoundError:
            self.log_text.text = "[Log file not found yet]\n"
            self._all_lines = []
            self._file_pos = 0
        except Exception as e:
            self.log_text.text = f"[Error loading log: {e}]\n"
            self._all_lines = []
            self._file_pos = 0
    
    def _tail_update(self, dt):
        """Read new content from the log file (incremental tail)."""
        if not self.log_text or not self._is_tailing:
            return
        try:
            with open(LOG_FILE_PATH, 'r') as f:
                f.seek(self._file_pos)
                new_content = f.read()
                if new_content:
                    new_lines = new_content.split('\n')
                    self._all_lines.extend(new_lines)
                    # Keep last 500 lines in memory
                    if len(self._all_lines) > 500:
                        self._all_lines = self._all_lines[-500:]
                    self._file_pos = f.tell()
                    self._apply_filter()
        except Exception:
            pass  # Silently ignore errors during tailing
    
    def write(self, text):
        """Legacy write method - no longer used but kept for compatibility."""
        pass

    def scroll_to_bottom(self):
        self.scroll_y = 0

    def flush(self):
        pass


class AsyncApp(SettingsHandlersMixin, PanelFileManagerMixin, App):
    """Main application class with settings and panel file handlers mixed in."""
    
    other_task = None
    bot_task = None
    grid_cells = {}  # Dictionary to store cells by ID for easy access
    log_popup = None
    error_popup = None
    file_chooser_popup = None
    save_panel_dialog = None
    last_error_info = None
    config_widgets = []  # List of config widgets for enable/disable
    bot = None  # Bot instance
    panel_settings = None
    panel_setup_controller = None  # Panel setup dialog controller
    config_settings_controller = None  # Config settings dialog controller
    main_menu_dropdown = None  # Main hamburger menu dropdown
    cycle_timer_event = None  # Clock event for cycle timer updates
    cycle_start_time = None  # Start time of current cycle
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Load KV file early so Factory classes are available
        kv_file = os.path.join(os.path.dirname(__file__), 'progbot.kv')
        Builder.load_file(kv_file)
        # Initialize panel setup controller
        self.panel_setup_controller = PanelSetupController(self)
        # Initialize config settings controller
        self.config_settings_controller = ConfigSettingsController(self)
    
    # ==================== Main Menu ====================
    
    def show_main_menu(self):
        """Show the main dropdown menu."""
        if not self.main_menu_dropdown:
            self.main_menu_dropdown = Factory.MainMenuDropDown()
        
        # Open dropdown attached to menu button
        if self.root:
            menu_btn = self.root.ids.get('menu_btn')
            if menu_btn:
                self.main_menu_dropdown.open(menu_btn)
    
    def _close_main_menu(self):
        """Close the main menu dropdown if open."""
        if self.main_menu_dropdown:
            self.main_menu_dropdown.dismiss()
    
    def menu_load_panel(self):
        """Menu action: Load Panel."""
        self._close_main_menu()
        self.open_panel_file_chooser()
    
    def menu_panel_setup(self):
        """Menu action: Panel Setup."""
        self._close_main_menu()
        self.open_panel_setup_dialog()
    
    def menu_config_settings(self):
        """Menu action: Config Settings."""
        self._close_main_menu()
        self.open_config_settings_dialog()
    
    def menu_exit(self):
        """Menu action: Clean up and exit the application."""
        self._close_main_menu()
        # Use Kivy App's stop method to cleanly exit
        from kivy.app import App
        App.get_running_app().stop()
    
    # ==================== End Main Menu ====================
    
    def toggle_log_popup(self):
        """Toggle the log viewer popup."""
        try:
            if not self.log_popup:
                # Create popup if it doesn't exist
                self.log_popup = Factory.LogPopup()
            
            # Check if popup is open using the internal _is_open attribute
            if hasattr(self.log_popup, '_is_open') and self.log_popup._is_open:
                # Stop tailing when closing
                log_viewer = self.log_popup.ids.get('log_viewer_widget')
                if log_viewer:
                    log_viewer.stop_tailing()
                self.log_popup.dismiss()
            else:
                self.log_popup.open()
                # Start tailing when opening (after a brief delay for UI setup)
                def start_tail(dt):
                    log_viewer = self.log_popup.ids.get('log_viewer_widget')
                    if log_viewer:
                        log_viewer.start_tailing()
                Clock.schedule_once(start_tail, 0.1)
        except Exception as e:
            log.error(f"Error toggling log popup: {e}")
            import traceback
            traceback.print_exc()
    
    def toggle_stats_popup(self):
        """Toggle the statistics popup."""
        try:
            if not hasattr(self, 'stats_popup') or not self.stats_popup:
                # Create popup if it doesn't exist
                self.stats_popup = Factory.StatsPopup()
            
            # Check if popup is open using the internal _is_open attribute
            if hasattr(self.stats_popup, '_is_open') and self.stats_popup._is_open:
                self.stats_popup.dismiss()
            else:
                # Populate with last stats text before opening
                if hasattr(self, '_last_stats_text'):
                    stats_label = self.stats_popup.ids.get('stats_label')
                    if stats_label:
                        stats_label.text = self._last_stats_text
                self.stats_popup.open()
        except Exception as e:
            log.error(f"Error toggling stats popup: {e}")
            import traceback
            traceback.print_exc()
    
    def _start_cycle_timer(self):
        """Start the cycle timer display."""
        import time
        self.cycle_start_time = time.time()
        # Update immediately, then every second
        self._update_cycle_timer(0)
        self.cycle_timer_event = Clock.schedule_interval(self._update_cycle_timer, 1.0)
    
    def _stop_cycle_timer(self):
        """Stop the cycle timer display."""
        if self.cycle_timer_event:
            self.cycle_timer_event.cancel()
            self.cycle_timer_event = None
        self.cycle_start_time = None
        # Hide the timer label
        timer_label = self.root.ids.get('cycle_timer_label')
        if timer_label:
            timer_label.text = ""
    
    def _update_cycle_timer(self, dt):
        """Update the cycle timer label."""
        import time
        if self.cycle_start_time is None:
            return
        elapsed = time.time() - self.cycle_start_time
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        timer_label = self.root.ids.get('cycle_timer_label')
        if timer_label:
            timer_label.text = f"{minutes}:{seconds:02d}"

    def _open_error_popup(self, error_info):
        message = error_info.get('message', 'Unknown error') if isinstance(error_info, dict) else str(error_info)
        col = error_info.get('col') if isinstance(error_info, dict) else None
        row = error_info.get('row') if isinstance(error_info, dict) else None
        trace = error_info.get('traceback', '') if isinstance(error_info, dict) else ''
        location = f"Board [{col}, {row}]" if col is not None and row is not None else ""
        display = f"{location}: {message}" if location else message

        if not self.error_popup:
            self.error_popup = Factory.ErrorPopup()

        if hasattr(self.error_popup, 'ids'):
            if (lbl := self.error_popup.ids.get('error_message')):
                lbl.text = display
            if (txt := self.error_popup.ids.get('error_trace')):
                txt.text = trace

        try:
            self.error_popup.open()
        except Exception as e:
            log.error(f"[ErrorPopup] Failed to open: {e}")
    
    def _set_widget(self, widget_name: str, **props):
        """Set properties on a widget if it exists."""
        if (w := getattr(self, widget_name, None)):
            for key, val in props.items():
                setattr(w, key, val)
    
    def populate_grid(self, rows, cols, labels=None):
        """Programmatically populate the grid with GridCell widgets.
        
        Cell numbering: bottom-left is 0, incrementing up within a column,
        then moving to the next column (column-major from bottom-left).
        
        Args:
            rows: Number of rows
            cols: Number of columns
            labels: Optional list of labels for cells (column-major from bottom-left)
        """
        if not (grid := getattr(self, 'panel_grid', None)):
            log.error("Error: panel_grid not found")
            return
        
        # Clear existing cells
        grid.clear_widgets()
        
        # Set grid dimensions
        grid.cols = cols
        grid.rows = rows
        grid.size_hint_y = 0.7
        
        # Store grid dimensions for later use
        self.grid_rows = rows
        self.grid_cols = cols
        
        # Load skip board positions from settings
        skip_pos = get_settings().get('skip_board_pos', [])
        
        # Create mapping from grid add order (row-major from top) to cell number (column-major from bottom-left)
        # For cell number i (column-major, bottom-left = 0):
        # - col = i // rows
        # - row_from_bottom = i % rows
        # - row_from_top = rows - 1 - row_from_bottom
        # - grid_position = row_from_top * cols + col
        
        cell_mapping = {}
        for cell_index in range(rows * cols):
            col = cell_index // rows
            row_from_bottom = cell_index % rows
            row_from_top = rows - 1 - row_from_bottom
            grid_position = row_from_top * cols + col
            cell_mapping[grid_position] = cell_index
        
        # Add cells in grid position order
        for grid_position in range(rows * cols):
            cell_index = cell_mapping[grid_position]
            label_text = labels[cell_index] if labels and cell_index < len(labels) else str(cell_index)
            
            # Convert cell index to [col, row] to check if it's in skip list
            col = cell_index // rows
            row_from_bottom = cell_index % rows
            is_skipped = [col, row_from_bottom] in skip_pos
            
            # Create callback for this cell
            def make_callback():
                """Create a closure to capture current state."""
                def on_toggle():
                    skip_pos_updated = self.get_skip_board_pos()
                    get_settings().set('skip_board_pos', skip_pos_updated)
                    log.debug(f"[GridCell] Saved skip_board_pos: {skip_pos_updated}")
                return on_toggle
            
            # Create cell with appropriate checked state and callback
            cell = GridCell(cell_label=label_text, cell_checked=not is_skipped, on_toggle_callback=make_callback())
            
            grid.add_widget(cell)            
            # Store cell reference by ID
            self.grid_cells[cell_index] = cell
        
        # Update grid cells with current phase enabled states
        self.update_grid_phase_states()
    
    def get_skip_board_pos(self):
        """Get list of unchecked board positions in [col, row] format.
        
        Converts from column-major grid IDs to [col, row] format used by ProgBot.
        
        Returns:
            List of [col, row] coordinates for unchecked cells
        """
        skip_positions = []
        for cell_id, cell in self.grid_cells.items():
            # If checkbox is NOT checked, add to skip list
            if not cell.cell_checked:
                # Convert from column-major ID to [col, row]
                # cell_id is column-major from bottom-left:
                # col = cell_id // grid_rows
                # row_from_bottom = cell_id % grid_rows
                col = cell_id // self.grid_rows
                row_from_bottom = cell_id % self.grid_rows
                skip_positions.append([col, row_from_bottom])
        return skip_positions
    
    # Settings handlers (on_board_cols_change, on_board_rows_change, etc.)
    # are provided by SettingsHandlersMixin
    
    # Camera, operation mode, and firmware handlers are provided by SettingsHandlersMixin

    def open_network_firmware_chooser(self):
        """Open file chooser to select network core firmware."""
        from kivy.uix.filechooser import FileChooserListView
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.button import Button
        
        layout = BoxLayout(orientation='vertical')
        chooser = FileChooserListView(
            path=os.path.expanduser('~'),
            filters=['*.hex']
        )
        layout.add_widget(chooser)
        
        button_layout = BoxLayout(size_hint_y=0.1, spacing=5)
        select_btn = Button(text='Select')
        cancel_btn = Button(text='Cancel')
        button_layout.add_widget(select_btn)
        button_layout.add_widget(cancel_btn)
        layout.add_widget(button_layout)
        
        popup = Popup(title='Select Network Core Firmware', content=layout, size_hint=(0.8, 0.8))
        
        def on_select(instance):
            if chooser.selection:
                path = chooser.selection[0]
                if network_input := self.root.ids.get('network_firmware_input'):
                    network_input.text = path
                self.on_network_firmware_change(path)
                popup.dismiss()
        
        def on_cancel(instance):
            popup.dismiss()
        
        select_btn.bind(on_press=on_select)
        cancel_btn.bind(on_press=on_cancel)
        popup.open()

    def open_main_firmware_chooser(self):
        """Open file chooser to select main core firmware."""
        from kivy.uix.filechooser import FileChooserListView
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.button import Button
        
        layout = BoxLayout(orientation='vertical')
        chooser = FileChooserListView(
            path=os.path.expanduser('~'),
            filters=['*.hex']
        )
        layout.add_widget(chooser)
        
        button_layout = BoxLayout(size_hint_y=0.1, spacing=5)
        select_btn = Button(text='Select')
        cancel_btn = Button(text='Cancel')
        button_layout.add_widget(select_btn)
        button_layout.add_widget(cancel_btn)
        layout.add_widget(button_layout)
        
        popup = Popup(title='Select Main Core Firmware', content=layout, size_hint=(0.8, 0.8))
        
        def on_select(instance):
            if chooser.selection:
                path = chooser.selection[0]
                if main_input := self.root.ids.get('main_firmware_input'):
                    main_input.text = path
                self.on_main_firmware_change(path)
                popup.dismiss()
        
        def on_cancel(instance):
            popup.dismiss()
        
        select_btn.bind(on_press=on_select)
        cancel_btn.bind(on_press=on_cancel)
        popup.open()
    
    def build(self):
        # Load panel settings first
        self.panel_settings = get_panel_settings()
        settings_data = self.panel_settings.get_all()
        self.settings_data = settings_data
        
        # Apply settings to progbot module
        try:
            mode_text = settings_data.get('operation_mode', 'Program')
            mode_mapping = {
                "Identify Only": sequence.OperationMode.IDENTIFY_ONLY,
                "Program": sequence.OperationMode.PROGRAM,
                "Program & Test": sequence.OperationMode.PROGRAM_AND_TEST,
                "Test Only": sequence.OperationMode.TEST_ONLY,
            }
            self.loaded_operation_mode = mode_mapping.get(mode_text, sequence.OperationMode.PROGRAM)
            log.info(f"[AsyncApp.build] Loaded settings from file")
        except Exception as e:
            log.error(f"[AsyncApp.build] Error loading settings: {e}")
        
        # Create file chooser popup for panel files
        self.file_chooser_popup = Factory.PanelFileChooser()
        self.save_panel_dialog = Factory.SavePanelDialog()
        
        # Instantiate the AppRoot template via Factory
        root = Factory.AppRoot()

        # The label id was renamed to 'phase_label' in the KV file
        self.phase_label = root.ids.get('phase_label')
        self.panel_file_label = root.ids.get('panel_file_label')
        self.log_viewer = root.ids.get('log_viewer_widget')
        self.start_button = root.ids.get('start_btn')
        self.stop_button = root.ids.get('stop_btn')
        self.panel_grid = root.ids.get('panel_grid')
        # Store references to HOME and grid manipulation buttons
        self.home_btn = root.ids.get('home_btn')
        self.reset_grid_btn = root.ids.get('reset_grid_btn')
        self.skip_all_btn = root.ids.get('skip_all_btn')
        self.enable_all_btn = root.ids.get('enable_all_btn')
        self.calibrate_btn = root.ids.get('calibrate_btn')
        
        # Set panel file label to current file
        if self.panel_file_label and self.panel_settings:
            import os as os_module
            panel_name = os_module.path.basename(self.panel_settings.panel_file)
            self.panel_file_label.text = panel_name
        
        # Store references to config widgets for enable/disable
        self.config_widgets = [
            root.ids.get('operation_spinner'),
            root.ids.get('network_firmware_input'),
            root.ids.get('main_firmware_input'),
            root.ids.get('config_tab_content')  # Add Config tab to disabled widgets
        ]
        
        # Disable all controls initially until ports are configured
        self._set_controls_enabled(False)
        
        # Create and store the log popup
        self.log_popup = Factory.LogPopup()
        self.error_popup = Factory.ErrorPopup()
        
        # Create serial port chooser
        self.serial_port_selector = SerialPortSelector()
        
        # Update widget values from settings
        Clock.schedule_once(lambda dt: self._apply_settings_to_widgets(root, settings_data), 0.3)

        return root

    def _config_from_settings(self):
        """Build a ProgBot config from the loaded settings."""
        # Always load fresh panel-specific settings from panel_settings (the source of truth)
        settings_data = self.panel_settings.get_all() if self.panel_settings else {}
        
        # Load hardware settings (port IDs) from main settings file
        hardware_settings = get_settings().get_all()
        
        defaults = sequence.Config()

        def _get(key, cast, fallback):
            try:
                value = settings_data.get(key, fallback)
                # Handle boolean strings properly (bool('False') == True is wrong!)
                if cast is bool and isinstance(value, str):
                    return value.lower() in ('true', '1', 'yes')
                return cast(value)
            except Exception as e:
                log.debug(f"[_config_from_settings] Cast failed for {key}: {e}")
                return fallback

        mode_mapping = {
            "Identify Only": sequence.OperationMode.IDENTIFY_ONLY,
            "Program": sequence.OperationMode.PROGRAM,
            "Program & Test": sequence.OperationMode.PROGRAM_AND_TEST,
            "Test Only": sequence.OperationMode.TEST_ONLY,
        }

        mode_text = settings_data.get('operation_mode', defaults.operation_mode.value)
        skip_positions = settings_data.get('skip_board_pos', []) or []

        # Camera offsets and probing settings come from main settings (machine config), not panel settings
        camera_offset_x = hardware_settings.get('camera_offset_x', defaults.camera_offset_x)
        camera_offset_y = hardware_settings.get('camera_offset_y', defaults.camera_offset_y)
        qr_scan_timeout = hardware_settings.get('qr_scan_timeout', defaults.qr_scan_timeout)
        qr_search_offset = hardware_settings.get('qr_search_offset', defaults.qr_search_offset)
        contact_adjust_step = hardware_settings.get('contact_adjust_step', 0.1)

        return sequence.Config(
            board_x=_get('board_x', float, defaults.board_x),
            board_y=_get('board_y', float, defaults.board_y),
            board_col_width=_get('col_width', float, defaults.board_col_width),
            board_row_height=_get('row_height', float, defaults.board_row_height),
            board_num_rows=_get('board_rows', int, defaults.board_num_rows),
            board_num_cols=_get('board_cols', int, defaults.board_num_cols),
            probe_plane_to_board=_get('probe_plane', float, defaults.probe_plane_to_board),
            contact_adjust_step=contact_adjust_step,
            operation_mode=mode_mapping.get(mode_text, defaults.operation_mode),
            skip_board_pos=skip_positions,
            motion_port_id=hardware_settings.get('motion_port_id', ''),
            motion_baud=defaults.motion_baud,
            head_port_id=hardware_settings.get('head_port_id', ''),
            head_baud=defaults.head_baud,
            target_port_id=hardware_settings.get('target_port_id', ''),
            target_baud=defaults.target_baud,
            network_core_firmware=settings_data.get('network_core_firmware', defaults.network_core_firmware),
            main_core_firmware=settings_data.get('main_core_firmware', defaults.main_core_firmware),
            # Phase enable flags
            vision_enabled=_get('vision_enabled', bool, defaults.vision_enabled),
            programming_enabled=_get('programming_enabled', bool, defaults.programming_enabled),
            provision_enabled=_get('provision_enabled', bool, defaults.provision_enabled),
            test_enabled=_get('test_enabled', bool, defaults.test_enabled),
            # Camera settings
            use_camera=_get('use_camera', bool, defaults.use_camera),
            use_picamera=_get('use_picamera', bool, defaults.use_picamera),
            camera_index=_get('camera_index', int, defaults.camera_index),
            camera_offset_x=camera_offset_x,
            camera_offset_y=camera_offset_y,
            camera_z_height=_get('camera_z_height', float, defaults.camera_z_height),
            qr_offset_x=_get('qr_offset_x', float, defaults.qr_offset_x),
            qr_offset_y=_get('qr_offset_y', float, defaults.qr_offset_y),
            qr_scan_timeout=qr_scan_timeout,
            qr_search_offset=qr_search_offset,
        )
    
    def _debug_phase_flags(self, config):
        """Log phase flags for debugging."""
        log.debug(f"[Config] Phase flags: vision={config.vision_enabled}, programming={config.programming_enabled}, provision={config.provision_enabled}, test={config.test_enabled}")
    
    def _apply_settings_to_widgets(self, root, settings_data):
        """Apply loaded settings to UI widgets."""
        try:
            # Grid/origin/QR settings are now in the Panel Setup dialog and synced on open
            
            # Load contact_adjust_step from main settings (not panel settings)
            from settings import get_settings
            main_settings = get_settings()
            
            contact_adjust_step_input = root.ids.get('contact_adjust_step_input')
            if contact_adjust_step_input:
                contact_adjust_step_input.text = str(float(main_settings.get('contact_adjust_step', 0.1)))
            
            # Load camera offsets and QR timeout from main settings (not panel settings)
            from settings import get_settings
            main_settings = get_settings()
            
            qr_scan_timeout_input = root.ids.get('qr_scan_timeout_input')
            if qr_scan_timeout_input:
                qr_scan_timeout_input.text = str(float(main_settings.get('qr_scan_timeout', 5.0)))
            
            qr_search_offset_input = root.ids.get('qr_search_offset_input')
            if qr_search_offset_input:
                qr_search_offset_input.text = str(float(main_settings.get('qr_search_offset', 2.0)))
            
            camera_offset_x_input = root.ids.get('camera_offset_x_input')
            if camera_offset_x_input:
                camera_offset_x_input.text = str(main_settings.get('camera_offset_x', 50.0))
            
            camera_offset_y_input = root.ids.get('camera_offset_y_input')
            if camera_offset_y_input:
                camera_offset_y_input.text = str(main_settings.get('camera_offset_y', 50.0))
            
            camera_rotation_spinner = root.ids.get('camera_rotation_spinner')
            if camera_rotation_spinner:
                rotation = main_settings.get('camera_preview_rotation', 0)
                camera_rotation_spinner.text = f"{rotation}°"
            
            operation_spinner = root.ids.get('operation_spinner')
            if operation_spinner:
                operation_spinner.text = settings_data.get('operation_mode', 'Program')
            
            use_camera_checkbox = root.ids.get('use_camera_checkbox')
            if use_camera_checkbox:
                camera_setting = settings_data.get('use_camera', True)
                use_camera_checkbox.active = camera_setting
            
            network_firmware_input = root.ids.get('network_firmware_input')
            if network_firmware_input:
                network_firmware_input.text = settings_data.get('network_core_firmware', '/home/steve/fw/merged_CPUNET.hex')
            
            main_firmware_input = root.ids.get('main_firmware_input')
            if main_firmware_input:
                main_firmware_input.text = settings_data.get('main_core_firmware', '/home/steve/fw/merged.hex')
            
            log.info(f"[AsyncApp] Applied settings to widgets")
        except Exception as e:
            log.error(f"[AsyncApp] Error applying settings to widgets: {e}")

    def _set_config_widgets_enabled(self, enabled):
        """Enable or disable all configuration widgets.
        
        Args:
            enabled: True to enable, False to disable
        """
        if not hasattr(self, 'config_widgets'):
            log.warning("[Config] Warning: config_widgets not initialized")
            return
        for widget in self.config_widgets:
            if widget:
                try:
                    widget.disabled = not enabled
                except Exception as e:
                    log.error(f"[Config] Error setting widget disabled state: {e}")
    
    def _set_controls_enabled(self, enabled):
        """Enable or disable all controls (config widgets, grid cells, and buttons).
        
        Args:
            enabled: True to enable, False to disable
        """
        self._set_config_widgets_enabled(enabled)
        self._set_grid_cells_enabled(enabled)
        
        # Also disable start/stop buttons if disabling
        if not enabled:
            self._set_widget('start_button', disabled=True)
            self._set_widget('stop_button', disabled=True)
        else:
            self._set_widget('start_button', disabled=False)
            self._set_widget('stop_button', disabled=True)

    def _set_grid_cells_enabled(self, enabled: bool):
        """Enable or disable all grid cells."""
        for cell in self.grid_cells.values():
            try:
                cell.disabled = not enabled
            except Exception as e:
                log.error(f"[Grid] Error setting cell enabled state: {e}")
    
    def update_grid_phase_states(self):
        """Update all grid cells with current phase enabled states from panel settings."""
        if not self.panel_settings:
            return
        
        # Get phase enabled states from panel settings
        vision_enabled = self.panel_settings.get('vision_enabled', True)
        program_enabled = self.panel_settings.get('programming_enabled', True)
        provision_enabled = self.panel_settings.get('provision_enabled', False)
        test_enabled = self.panel_settings.get('test_enabled', False)
        
        # Probe follows vision
        probe_enabled = vision_enabled
        
        # Update all grid cells
        for cell in self.grid_cells.values():
            try:
                cell.vision_enabled = vision_enabled
                cell.probe_enabled = probe_enabled
                cell.program_enabled = program_enabled
                cell.provision_enabled = provision_enabled
                cell.test_enabled = test_enabled
            except Exception as e:
                log.error(f"[Grid] Error updating cell phase states: {e}")

    def update_grid_from_settings(self):
        """Update grid display from current panel settings.
        
        Called after panel settings are saved to refresh the grid display
        with new phase enabled states and other settings.
        """
        self.update_grid_phase_states()

    def home_machine(self, instance):
        """Force machine homing."""
        log.info(f"[HomeMachine] Button pressed")
        
        if not self.bot or not self.bot.motion:
            log.warning(f"[HomeMachine] Bot or motion controller not initialized")
            return
        
        # Disable buttons during homing
        self._set_widget('home_btn', disabled=True)
        self._set_widget('start_btn', disabled=True)
        
        async def do_homing():
            try:
                log.info("[HomeMachine] Starting forced homing...")
                await self.bot.motion.connect()
                
                # Clear alarm
                await self.bot.motion.device.send_command("M999")
                
                # Force homing
                log.info("[HomeMachine] Homing...")
                await self.bot.motion.send_gcode_wait_ok("$H", timeout=20)
                
                # Set work coordinates
                log.info("[HomeMachine] Setting work coordinates...")
                await self.bot.motion.send_gcode_wait_ok("G92 X0 Y0 Z0")
                
                log.info("[HomeMachine] Homing complete")
            except Exception as e:
                log.error(f"[HomeMachine] Error: {e}")
                import traceback
                traceback.print_exc()
            finally:
                # Re-enable buttons
                self._set_widget('home_btn', disabled=False)
                self._set_widget('start_btn', disabled=False)
        
        # Run homing in async context
        import asyncio
        asyncio.ensure_future(do_homing())
    
    # ==================== Panel Setup Dialog ====================
    # Thin wrapper methods that delegate to PanelSetupController
    # These methods are called from the KV file (app.ps_*)
    
    def open_panel_setup_dialog(self):
        """Open the panel setup dialog for setting board origin and probe offset."""
        self.panel_setup_controller.open()
    
    @property
    def panel_setup_popup(self):
        """Access the panel setup popup from the controller."""
        return self.panel_setup_controller.popup if self.panel_setup_controller else None
    
    def ps_set_xy_step(self, step):
        """Set XY jog step size."""
        self.panel_setup_controller.set_xy_step(step)
    
    def ps_set_z_step(self, step):
        """Set Z jog step size."""
        self.panel_setup_controller.set_z_step(step)
    
    def ps_home(self):
        """Home the machine from panel setup dialog."""
        self.panel_setup_controller.home()
    
    def ps_jog(self, axis, direction):
        """Jog the machine in the specified axis and direction."""
        self.panel_setup_controller.jog(axis, direction)
    
    def ps_safe_z(self):
        """Move to safe Z height (Z=0)."""
        self.panel_setup_controller.safe_z()
    
    def ps_do_probe(self):
        """Execute probe operation."""
        self.panel_setup_controller.do_probe()
    
    def ps_goto_origin(self):
        """Move to the currently configured board origin."""
        self.panel_setup_controller.goto_origin()
    
    def ps_goto_offset(self):
        """Move Z down by the configured offset from probe position to board surface."""
        self.panel_setup_controller.goto_offset()
    
    def ps_set_board_origin(self):
        """Set board origin from current XY position."""
        self.panel_setup_controller.set_board_origin()
    
    def ps_capture_probe_offset(self):
        """Capture probe-to-board offset from current Z position vs probe position."""
        self.panel_setup_controller.capture_probe_offset()
    
    def ps_close(self):
        """Close panel setup dialog, moving to safe Z first if needed."""
        self.panel_setup_controller.close()
    
    # Vision tab wrapper methods
    def ps_vision_tab_changed(self, state):
        """Handle Vision tab state changes."""
        self.panel_setup_controller.vision_tab_changed(state)
    
    def ps_vision_set_xy_step(self, step):
        """Set XY jog step size for Vision tab."""
        self.panel_setup_controller.vision_set_xy_step(step)
    
    def ps_vision_jog(self, axis, direction):
        """Jog the machine in the specified axis and direction (Vision tab)."""
        self.panel_setup_controller.vision_jog(axis, direction)
    
    def ps_vision_reset_qr_offset(self):
        """Reset QR offset values to what they were when entering the Vision tab."""
        self.panel_setup_controller.vision_reset_qr_offset()
    
    def ps_vision_set_qr_offset(self):
        """Set QR offset from current XY position relative to board origin."""
        self.panel_setup_controller.vision_set_qr_offset()
    
    def ps_vision_set_rotation(self, rotation):
        """Set camera preview rotation."""
        self.panel_setup_controller.vision_set_rotation(rotation)
    
    def ps_vision_board_change(self, axis, delta):
        """Change the selected board col or row and move to that position."""
        self.panel_setup_controller.vision_board_change(axis, delta)
    
    # ==================== Panel Setup Parameters Tab ====================
    
    def ps_on_board_cols_change(self, value):
        """Handle board columns change from Panel Setup dialog."""
        if self.panel_setup_controller:
            self.panel_setup_controller._set_buffer_value('board_cols', value)
    
    def ps_on_board_rows_change(self, value):
        """Handle board rows change from Panel Setup dialog."""
        if self.panel_setup_controller:
            self.panel_setup_controller._set_buffer_value('board_rows', value)
    
    def ps_on_col_width_change(self, value):
        """Handle column width change from Panel Setup dialog."""
        if self.panel_setup_controller:
            self.panel_setup_controller._set_buffer_value('col_width', value)
    
    def ps_on_row_height_change(self, value):
        """Handle row height change from Panel Setup dialog."""
        if self.panel_setup_controller:
            self.panel_setup_controller._set_buffer_value('row_height', value)
    
    def ps_on_board_x_change(self, value):
        """Handle board X change from Panel Setup dialog."""
        if self.panel_setup_controller:
            self.panel_setup_controller._set_buffer_value('board_x', value)
    
    def ps_on_board_y_change(self, value):
        """Handle board Y change from Panel Setup dialog."""
        if self.panel_setup_controller:
            self.panel_setup_controller._set_buffer_value('board_y', value)
    
    def ps_on_probe_plane_change(self, value):
        """Handle probe-to-board offset change from Panel Setup dialog."""
        if self.panel_setup_controller:
            self.panel_setup_controller._set_buffer_value('probe_plane', value)
    
    def ps_on_qr_offset_x_change(self, value):
        """Handle QR offset X change from Panel Setup dialog."""
        if self.panel_setup_controller:
            self.panel_setup_controller._set_buffer_value('qr_offset_x', value)
    
    def ps_on_qr_offset_y_change(self, value):
        """Handle QR offset Y change from Panel Setup dialog."""
        if self.panel_setup_controller:
            self.panel_setup_controller._set_buffer_value('qr_offset_y', value)
    
    def ps_on_use_camera_change(self, active):
        """Handle QR Code Scan checkbox change from Panel Setup dialog."""
        if self.panel_setup_controller:
            self.panel_setup_controller._set_buffer_value('use_camera', str(active).lower())
    
    def ps_programming_tab_changed(self, state):
        """Handle Programming tab state change."""
        if state == 'down':
            # Tab selected - rebuild dynamic UI in case settings changed
            if self.panel_setup_controller:
                self.panel_setup_controller._build_programmer_ui()
    
    def ps_on_programmer_type_change(self, display_name):
        """Handle programmer type spinner change from Panel Setup dialog."""
        if self.panel_setup_controller:
            self.panel_setup_controller.on_programmer_type_change(display_name)
    
    def ps_vision_enabled_changed(self, state):
        """Handle vision enabled toggle change from Panel Setup dialog."""
        if self.panel_setup_controller:
            enabled = (state == 'down')
            self.panel_setup_controller._set_buffer_value('vision_enabled', enabled)
            # Also update camera checkbox state for backwards compatibility
            self.ps_on_use_camera_change(enabled)
    
    def ps_programming_enabled_changed(self, state):
        """Handle programming enabled toggle change from Panel Setup dialog."""
        if self.panel_setup_controller:
            enabled = (state == 'down')
            self.panel_setup_controller._set_buffer_value('programming_enabled', enabled)
    
    def ps_provision_enabled_changed(self, state):
        """Handle provision enabled toggle change from Panel Setup dialog."""
        if self.panel_setup_controller:
            enabled = (state == 'down')
            self.panel_setup_controller._set_buffer_value('provision_enabled', enabled)
    
    def ps_test_enabled_changed(self, state):
        """Handle test enabled toggle change from Panel Setup dialog."""
        if self.panel_setup_controller:
            enabled = (state == 'down')
            self.panel_setup_controller._set_buffer_value('test_enabled', enabled)
    
    def ps_save_panel(self):
        """Save panel from Panel Setup dialog."""
        if self.panel_setup_controller:
            self.panel_setup_controller.save_panel()
    
    # ==================== End Panel Setup Dialog ====================
    
    # ==================== Config Settings Dialog ====================
    # Thin wrapper methods that delegate to ConfigSettingsController
    # These methods are called from the KV file (app.cs_*)
    
    def open_config_settings_dialog(self):
        """Open the config settings dialog for global machine configuration."""
        self.config_settings_controller.open()
    
    @property
    def config_settings_popup(self):
        """Access the config settings popup from the controller."""
        return self.config_settings_controller.popup if self.config_settings_controller else None
    
    def cs_save_settings(self):
        """Save settings from Config Settings dialog."""
        if self.config_settings_controller:
            self.config_settings_controller.save_settings()
    
    def cs_close(self):
        """Close Config Settings dialog."""
        if self.config_settings_controller:
            self.config_settings_controller.close()
    
    def cs_camera_tab_changed(self, state):
        """Handle Camera tab state changes."""
        if self.config_settings_controller:
            self.config_settings_controller.camera_tab_changed(state)
    
    def cs_on_camera_offset_x_change(self, text):
        """Handle camera offset X change."""
        if self.config_settings_controller:
            self.config_settings_controller.on_camera_offset_x_change(text)
    
    def cs_on_camera_offset_y_change(self, text):
        """Handle camera offset Y change."""
        if self.config_settings_controller:
            self.config_settings_controller.on_camera_offset_y_change(text)
    
    def cs_on_qr_scan_timeout_change(self, text):
        """Handle QR scan timeout change."""
        if self.config_settings_controller:
            self.config_settings_controller.on_qr_scan_timeout_change(text)
    
    def cs_on_qr_search_offset_change(self, text):
        """Handle QR search offset change."""
        if self.config_settings_controller:
            self.config_settings_controller.on_qr_search_offset_change(text)
    
    def cs_set_rotation(self, rotation):
        """Set camera rotation."""
        if self.config_settings_controller:
            self.config_settings_controller.set_rotation(rotation)
    
    def cs_on_contact_adjust_step_change(self, text):
        """Handle contact adjust step change."""
        if self.config_settings_controller:
            self.config_settings_controller.on_contact_adjust_step_change(text)
    
    def cs_reconfigure_motion_port(self):
        """Open serial port selector for motion controller."""
        if self.config_settings_controller:
            self.config_settings_controller.reconfigure_motion_port()
    
    def cs_reconfigure_head_port(self):
        """Open serial port selector for head controller."""
        if self.config_settings_controller:
            self.config_settings_controller.reconfigure_head_port()
    
    def cs_reconfigure_target_port(self):
        """Open serial port selector for target device."""
        if self.config_settings_controller:
            self.config_settings_controller.reconfigure_target_port()
    
    def cs_jog_xy(self, axis, direction):
        """Jog XY in the camera tab."""
        if self.config_settings_controller:
            self.config_settings_controller.jog_xy(axis, direction)
    
    def cs_set_jog_xy_step(self, step):
        """Set XY jog step size."""
        if self.config_settings_controller:
            self.config_settings_controller.set_jog_xy_step(step)
    
    def cs_capture_camera_offset(self):
        """Capture current position as camera offset."""
        if self.config_settings_controller:
            self.config_settings_controller.capture_camera_offset()
    
    def cs_reset_camera_offset(self):
        """Reset camera offset to values from when tab was entered."""
        if self.config_settings_controller:
            self.config_settings_controller.reset_camera_offset()
    
    # ==================== End Config Settings Dialog ====================

    def reset_grid(self, instance):
        """Reset all grid cells to their default state as if panel was just loaded."""
        log.info(f"[ResetGrid] Button pressed")
        
        def do_reset(dt):
            # Get skip positions from current panel settings
            skip_pos = get_settings().get('skip_board_pos', [])
            
            # Reset all cells using batch update to avoid per-cell redraws
            for cell_id, cell in self.grid_cells.items():
                # Convert cell_id to [col, row]
                col = cell_id // self.grid_rows
                row_from_bottom = cell_id % self.grid_rows
                
                # Check if this cell is in skip list
                is_skipped = [col, row_from_bottom] in skip_pos
                
                # Reset cell properties (status fields don't trigger redraws)
                cell.status_line1 = ""
                cell.status_line2 = ""
                cell.status_line3 = ""
                cell.status_line4 = ""
                cell.serial_number = ""
                
                # Reset checked state and appearance in one batch
                # Label should always remain as the board number (base_cell_label)
                if is_skipped:
                    cell.set_state_batch(False, [0, 0, 0, 1], cell.base_cell_label)
                else:
                    cell.set_state_batch(True, [0.5, 0.5, 0.5, 1], cell.base_cell_label)
            
            # Reset phase label and stats display
            self._set_widget('phase_label', text="Ready")
            # Reset stats in popup if it exists
            self._last_stats_text = 'Ready'
            if hasattr(self, 'stats_popup') and self.stats_popup:
                stats_label = self.stats_popup.ids.get('stats_label')
                if stats_label:
                    stats_label.text = 'Ready'
            
            # Clear board statuses and stats in bot
            if self.bot:
                self.bot.board_statuses = {}
                self.bot.stats.reset()
            
            log.info(f"[ResetGrid] Grid reset complete")
        
        # Schedule to run after button release completes
        Clock.schedule_once(do_reset, 0)
    
    def skip_all_boards(self, instance):
        """Set all grid cells to skipped state."""
        log.info(f"[SkipAll] Button pressed")
        
        def do_skip(dt):
            for cell_id, cell in self.grid_cells.items():
                # Keep board number label, just change checked state and color
                cell.set_state_batch(False, [0, 0, 0, 1], cell.base_cell_label)
            
            # Save skip positions to settings and update bot
            skip_pos = self.get_skip_board_pos()
            get_settings().set('skip_board_pos', skip_pos)
            if self.bot:
                self.bot.set_skip_board_pos(skip_pos)
            log.info(f"[SkipAll] All boards skipped")
        
        Clock.schedule_once(do_skip, 0)
    
    def enable_all_boards(self, instance):
        """Set all grid cells to enabled state."""
        log.info(f"[EnableAll] Button pressed")
        
        def do_enable(dt):
            for cell_id, cell in self.grid_cells.items():
                cell.set_state_batch(True, [0.5, 0.5, 0.5, 1], cell.base_cell_label)
            
            # Save skip positions to settings and update bot (empty list = all enabled)
            skip_pos = self.get_skip_board_pos()
            get_settings().set('skip_board_pos', skip_pos)
            if self.bot:
                self.bot.set_skip_board_pos(skip_pos)
            log.info(f"[EnableAll] All boards enabled")
        
        Clock.schedule_once(do_enable, 0)
    
    def stop(self, instance):
        # concise stops using helper
        log.info("[Stop] Button pressed")
        try:
            self._set_widget('start_button', disabled=False)
            self._set_widget('stop_button', disabled=True)
            self._set_widget('phase_label', text="Stopped")
            # Re-enable config widgets
            self._set_config_widgets_enabled(True)
            self._set_grid_cells_enabled(True)
            
            # Note: Board statuses are updated via BoardStatus.INTERRUPTED in sequence.py
            # No need to manually update cell colors/text here - the status updates will handle it
        except Exception as e:
            log.error(f"[Stop] Error in widget updates: {e}")
        
        # Ensure camera preview is stopped and popup closed
        if hasattr(self, 'bot') and self.bot and hasattr(self.bot, 'camera_preview'):
            if self.bot.camera_preview:
                try:
                    self.bot.camera_preview.stop_preview()
                    log.info("[Stop] Camera preview stopped")
                except Exception as e:
                    log.error(f"[Stop] Error stopping camera preview: {e}")
        
        # Switch back to idle view if camera was showing
        manager = self.root.ids.get('stats_camera_manager')
        if manager and manager.current == 'camera':
            manager.current = 'idle'
        
        # Cancel the running task
        if (bot := getattr(self, 'bot_task', None)):
            try:
                log.info("[Stop] Cancelling bot task")
                bot.cancel()
                log.info("[Stop] Bot task cancelled")
            except Exception as e:
                log.error(f"[Stop] Error cancelling bot task: {e}")
        
        # Camera cleanup happens automatically in full_cycle cleanup
        # Don't schedule it here - causes race condition with next start
        log.info("[Stop] Waiting for task cleanup to complete...")
        
        
    def start(self, instance):
        # concise widget updates using helper
        log.info(f"[Start] Button pressed")
        
        # If there's a previous task still cleaning up, wait for it
        if hasattr(self, 'bot_task') and self.bot_task and not self.bot_task.done():
            log.info(f"[Start] Previous task still running, waiting for cleanup...")
            async def wait_and_start():
                try:
                    # Wait up to 3 seconds for previous task to finish
                    await asyncio.wait_for(asyncio.shield(self.bot_task), timeout=3.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                except Exception as e:
                    log.error(f"[Start] Error waiting for previous task: {e}")
                
                # Small delay to ensure cleanup is complete
                await asyncio.sleep(0.5)
                
                # Now actually start
                await self._do_start()
            
            loop = asyncio.get_event_loop()
            loop.create_task(wait_and_start())
            return
        
        # No previous task, start immediately
        async def start_now():
            await self._do_start()
        
        loop = asyncio.get_event_loop()
        loop.create_task(start_now())
    
    async def _do_start(self):
        """Actually start the bot cycle."""
        log.info(f"[Start] Starting bot cycle")
        self._set_widget('start_button', disabled=True)
        self._set_widget('stop_button', disabled=False)
        # Disable HOME and grid manipulation buttons during cycle
        self._set_widget('home_btn', disabled=True)
        self._set_widget('reset_grid_btn', disabled=True)
        self._set_widget('skip_all_btn', disabled=True)
        self._set_widget('enable_all_btn', disabled=True)
        self._set_widget('calibrate_btn', disabled=True)
        # Disable config widgets during operation
        self._set_config_widgets_enabled(False)
        self._set_grid_cells_enabled(False)
        
        # Get skip positions
        skip_pos = self.get_skip_board_pos()
        
        # Reset only active cells (not skipped) to neutral state
        for cell_id, cell in self.grid_cells.items():
            # Convert cell_id to [col, row]
            col = cell_id // self.grid_rows
            row_from_bottom = cell_id % self.grid_rows
            
            # Only reset active cells (not in skip list)
            if [col, row_from_bottom] not in skip_pos:
                cell.cell_bg_color = [0.3, 0.3, 0.3, 1]  # Medium gray for waiting
                cell.status_line1 = ""
                cell.status_line2 = ""
            # Skipped cells stay black
        
        # Update skip board positions from unchecked cells
        if (b := getattr(self, 'bot', None)):
            # Reload the entire config from current settings
            new_config = self._config_from_settings()
            self._debug_phase_flags(new_config)  # Log phase flags for debugging
            b.config = new_config
            b.set_skip_board_pos(skip_pos)
        else:
            log.warning(f"[Start] Warning: Bot not found")
        
        if (b := getattr(self, 'bot', None)):
            log.info(f"[Start] Creating bot task")
            
            # Reconnect stats_updated signal (in case it was disconnected after previous cycle)
            try:
                # First disconnect any existing connection to avoid duplicates
                b.stats_updated.disconnect(listener=self.on_stats_updated)
            except:
                pass  # Ignore if not connected
            b.stats_updated.connect(self.on_stats_updated)
            log.info(f"[Start] Reconnected stats_updated signal")
            
            self.bot_task = asyncio.create_task(b.full_cycle())
            # Add callback to re-enable config widgets when task completes
            self.bot_task.add_done_callback(self._on_task_complete)
            # Start the cycle timer
            self._start_cycle_timer()
            log.info(f"[Start] Bot task created")
        else:
            log.error(f"[Start] Error: Bot not available to create task")
    
    def _on_task_complete(self, task):
        """Called when the bot task completes or is cancelled."""
        # Dump diagnostics to see system state
        dump_diagnostics("TASK_COMPLETE")
        
        try:
            task.exception()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error(f"[BotTask] Completed with error: {e}")

        # Disconnect frequent signal emitters to prevent orphaned tasks
        # These signals fire during cycles and can cause issues if emitted after completion
        # Note: We don't disconnect all signals since some are needed for UI updates
        if hasattr(self, 'bot') and self.bot:
            try:
                # Disconnect stats_updated since it's emitted frequently and can pile up
                if hasattr(self.bot, 'stats_updated'):
                    self.bot.stats_updated.disconnect(listener=self.on_stats_updated)
                    log.info("[Task Complete] Disconnected stats_updated signal")
            except Exception as e:
                log.error(f"[Task Complete] Error disconnecting signals: {e}")

        # Re-enable start button and config widgets
        Clock.schedule_once(lambda dt: self._set_widget('start_button', disabled=False))
        Clock.schedule_once(lambda dt: self._set_widget('stop_button', disabled=True))
        # Stop the cycle timer
        Clock.schedule_once(lambda dt: self._stop_cycle_timer())
        # Re-enable HOME and grid manipulation buttons
        Clock.schedule_once(lambda dt: self._set_widget('home_btn', disabled=False))
        Clock.schedule_once(lambda dt: self._set_widget('reset_grid_btn', disabled=False))
        Clock.schedule_once(lambda dt: self._set_widget('skip_all_btn', disabled=False))
        Clock.schedule_once(lambda dt: self._set_widget('enable_all_btn', disabled=False))
        Clock.schedule_once(lambda dt: self._set_widget('calibrate_btn', disabled=False))
        Clock.schedule_once(lambda dt: self._set_config_widgets_enabled(True))
        Clock.schedule_once(lambda dt: self._set_grid_cells_enabled(True))
        self.bot_task = None
        
    @listener
    async def on_board_status_change(self, cell_id, board_status):
        """Update a cell's status from BoardStatus object.
        
        Args:
            cell_id: The cell ID (0-indexed from bottom-left)
            board_status: BoardStatus object with status information
        """
        if cell := self.grid_cells.get(cell_id):
            Clock.schedule_once(lambda dt: cell.update_status(board_status))

    @listener
    async def on_phase_change(self, value):
        if (lbl := getattr(self, 'phase_label', None)):
            Clock.schedule_once(lambda dt: setattr(lbl, 'text', str(value)))

    @listener
    async def on_panel_change(self, cols, rows):
        Clock.schedule_once(lambda dt: self.populate_grid(rows, cols))

    @listener
    async def on_cell_color_change(self, cell_id, color_rgba):
        """Update a cell's background color by ID.
        
        Args:
            cell_id: The cell ID (0-indexed from bottom-left)
            color_rgba: List or tuple [r, g, b, a] with values 0-1
        """
        if cell := self.grid_cells.get(cell_id):
            Clock.schedule_once(lambda dt: setattr(cell, 'cell_bg_color', color_rgba))

    @listener
    async def on_error_occurred(self, error_info):
        self.last_error_info = error_info
        Clock.schedule_once(lambda dt: self._open_error_popup(error_info))

    @listener
    async def on_stats_updated(self, stats_text):
        """Update the cycle statistics display."""
        def do_update(dt):
            # Update stats in the popup if it exists
            if hasattr(self, 'stats_popup') and self.stats_popup:
                stats_label = self.stats_popup.ids.get('stats_label')
                if stats_label:
                    stats_label.text = stats_text
            # Also store the latest stats text for when popup is opened
            self._last_stats_text = stats_text
        Clock.schedule_once(do_update)
    
    @listener
    async def on_qr_scan_started(self):
        """Switch to camera preview when QR scanning begins."""
        def do_show(dt):
            manager = self.root.ids.get('stats_camera_manager')
            if manager:
                manager.current = 'camera'
        Clock.schedule_once(do_show)
    
    @listener
    async def on_qr_scan_ended(self):
        """Switch back to idle display when QR scanning ends."""
        def do_hide(dt):
            manager = self.root.ids.get('stats_camera_manager')
            if manager:
                manager.current = 'idle'
        Clock.schedule_once(do_hide)
    def on_error_abort(self):
        if self.error_popup:
            self.error_popup.dismiss()
        if self.bot_task and not self.bot_task.done():
            self.bot_task.cancel()
        self._set_widget('start_button', disabled=False)
        self._set_widget('stop_button', disabled=True)
        self._set_config_widgets_enabled(True)
        self._set_grid_cells_enabled(True)

    def on_error_retry(self):
        if self.error_popup:
            self.error_popup.dismiss()
        if self.bot_task and not self.bot_task.done():
            self.bot_task.cancel()

        info = self.last_error_info or {}
        col = info.get('col') if isinstance(info, dict) else None
        row = info.get('row') if isinstance(info, dict) else None
        if col is None or row is None or not self.bot:
            log.info("[ErrorPopup] No board info for retry; restarting full cycle")
            Clock.schedule_once(lambda dt: self.start(self.start_button))
            return

        # Prep cell visual state for retry
        cell_id = col * self.grid_rows + row if hasattr(self, 'grid_rows') else None
        if cell_id is not None and (cell := self.grid_cells.get(cell_id)):
            cell.cell_bg_color = [0.3, 0.3, 0.3, 1]
            cell.status_line1 = ""
            cell.status_line2 = ""

        loop = asyncio.get_event_loop()
        self._set_widget('start_button', disabled=True)
        self._set_widget('stop_button', disabled=False)
        self._set_config_widgets_enabled(False)
        self._set_grid_cells_enabled(False)
        log.info(f"[ErrorPopup] Retrying board [{col}, {row}]")
        self.bot_task = loop.create_task(self.bot.retry_board(col, row))
        self.bot_task.add_done_callback(self._on_task_complete)

    def on_error_skip(self):
        if self.error_popup:
            self.error_popup.dismiss()

        info = self.last_error_info or {}
        col = info.get('col') if isinstance(info, dict) else None
        row = info.get('row') if isinstance(info, dict) else None
        if col is None or row is None:
            return
        if not hasattr(self, 'grid_rows') or not hasattr(self, 'grid_cols'):
            log.warning("[ErrorPopup] Grid dimensions not initialized; cannot skip")
            return

        try:
            cell_id = col * self.grid_rows + row
            if (cell := self.grid_cells.get(cell_id)):
                cell.cell_checked = False
            skip_positions = self.get_skip_board_pos()
            get_settings().set('skip_board_pos', skip_positions)
            if self.bot:
                self.bot.set_skip_board_pos(skip_positions)
            log.info(f"[ErrorPopup] Skipped board [{col}, {row}]")
        except Exception as e:
            log.error(f"[ErrorPopup] Failed to skip board: {e}")

    # Panel file management (open_panel_file_chooser, on_panel_file_selected, 
    # open_save_panel_dialog, on_save_panel_confirmed, etc.) 
    # are provided by PanelFileManagerMixin

    def show_serial_port_chooser(self, device_type, available_ports, callback):
        """Show the serial port chooser dialog.
        
        Delegates to SerialPortSelector for GUI implementation.
        
        Args:
            device_type: Human-readable device type string
            available_ports: List of SerialPortInfo objects
            callback: Function to call with selected port (SerialPortInfo or None)
        """
        self.serial_port_selector.show_dialog(device_type, available_ports, callback)
    
    def on_serial_port_row_pressed(self, port_index):
        """Called when a serial port row is pressed.
        
        Delegates to SerialPortSelector.
        """
        self.serial_port_selector.on_row_pressed(port_index)
    
    def on_serial_port_selected(self):
        """Called when Select button is pressed in serial port chooser.
        
        Delegates to SerialPortSelector.
        """
        self.serial_port_selector.on_select_pressed()

    # _apply_settings_to_widgets_now, _reload_bot_config, open_save_panel_dialog,
    # _focus_panel_input, set_keyboard_layout, on_save_panel_confirmed
    # are provided by PanelFileManagerMixin

    def update_port_labels(self):
        """Update the Config tab port labels with current device information."""
        try:
            root = self.root
            if not root:
                return
            
            motion_label = root.ids.get('motion_port_label')
            head_label = root.ids.get('head_port_label')
            target_label = root.ids.get('target_port_label')
            
            if self.bot:
                if hasattr(self.bot, 'motion') and self.bot.motion and hasattr(self.bot.motion, 'port'):
                    if motion_label:
                        motion_label.text = self.bot.motion.port or "Not configured"
                if hasattr(self.bot, 'head') and self.bot.head and hasattr(self.bot.head, 'port'):
                    if head_label:
                        head_label.text = self.bot.head.port or "Not configured"
                if hasattr(self.bot, 'target') and self.bot.target and hasattr(self.bot.target, 'port'):
                    if target_label:
                        target_label.text = self.bot.target.port or "Not configured"
        except Exception as e:
            log.error(f"[Config] Error updating port labels: {e}")

    async def _reconfigure_port_async(self, device_type):
        """Async helper to reconfigure a specific port."""
        try:
            if not self.bot:
                log.warning(f"[Config] Cannot reconfigure {device_type}: bot not initialized")
                return
            
            # Clear the selected port ID so it will prompt for selection
            from settings import get_settings
            settings = get_settings()
            
            port = None
            if device_type == "Motion Controller":
                settings.set('motion_port_id', '')
                port = await self.bot._resolve_port_async('', "Motion Controller", None, is_reconfigure=True)
                # Reinitialize motion controller with new port
                from motion_controller import MotionController
                self.bot.motion = MotionController(self.bot.update_phase, port, self.bot.config.motion_baud)
                # Connect and initialize the new controller
                await self.bot.motion.connect()
                await self.bot.motion.init()
            elif device_type == "Head Controller":
                settings.set('head_port_id', '')
                port = await self.bot._resolve_port_async('', "Head Controller", None, is_reconfigure=True)
                # Reinitialize head controller with new port
                from head_controller import HeadController
                self.bot.head = HeadController(self.bot.update_phase, port, self.bot.config.head_baud)
                # Connect the new controller
                await self.bot.head.connect()
            elif device_type == "Target Device":
                settings.set('target_port_id', '')
                port = await self.bot._resolve_port_async('', "Target Device", None, is_reconfigure=True)
                # Reinitialize target controller with new port
                from target_controller import TargetController
                self.bot.target = TargetController(self.bot.update_phase, port, self.bot.config.target_baud)
                # Connect and initialize the new controller
                await self.bot.target.connect()
            
            # Update the labels after reconfiguration
            self.update_port_labels()
            log.info(f"[Config] Successfully reconfigured {device_type} to {port}")
        except Exception as e:
            log.error(f"[Config] Error reconfiguring {device_type}: {e}")
            import traceback
            traceback.print_exc()

    def reconfigure_motion_port(self):
        """Reconfigure the Motion Controller port."""
        asyncio.create_task(self._reconfigure_port_async("Motion Controller"))

    def reconfigure_head_port(self):
        """Reconfigure the Head Controller port."""
        asyncio.create_task(self._reconfigure_port_async("Head Controller"))

    def reconfigure_target_port(self):
        """Reconfigure the Target Device port."""
        asyncio.create_task(self._reconfigure_port_async("Target Device"))


    def app_func(self):
        async def run_wrapper():
            # Ensure panel_settings is loaded (build() may not have run yet)
            if not hasattr(self, 'panel_settings') or self.panel_settings is None:
                self.panel_settings = get_panel_settings()
            
            config = self._config_from_settings()
            
            self.bot = sequence.ProgBot(
                config=config, 
                panel_settings=self.panel_settings,
                gui_port_picker=self.show_serial_port_chooser
            )
            
            self.bot.phase_changed.connect(self.on_phase_change)
            self.bot.panel_changed.connect(self.on_panel_change)
            self.bot.cell_color_changed.connect(self.on_cell_color_change)
            self.bot.board_status_changed.connect(self.on_board_status_change)
            self.bot.error_occurred.connect(self.on_error_occurred)
            self.bot.stats_updated.connect(self.on_stats_updated)
            self.bot.qr_scan_started.connect(self.on_qr_scan_started)
            self.bot.qr_scan_ended.connect(self.on_qr_scan_ended)
            
            # Now emit panel dimensions after listeners are connected
            self.bot.init_panel()
            
            # Schedule port configuration and camera setup after window is visible
            async def configure_ports_delayed():
                await asyncio.sleep(1.0)  # Wait for window to fully render
                
                # Set up camera preview if camera is enabled
                if self.bot.vision:
                    from camera_preview import CameraPreview
                    # Get camera preview widgets from the CameraScreen
                    camera_screen = self.root.ids.get('camera_screen')
                    if camera_screen:
                        camera_image = camera_screen.ids.get('camera_preview_image')
                        camera_status = camera_screen.ids.get('camera_status_label')
                        if camera_image and camera_status:
                            self.bot.camera_preview = CameraPreview(
                                self.bot.vision,
                                camera_image,
                                camera_status
                            )
                            log.info("[AsyncApp] Camera preview initialized in stats pane")
                        else:
                            log.warning("[AsyncApp] Warning: Camera screen widgets not found")
                    else:
                        log.warning("[AsyncApp] Warning: Camera screen not found")
                
                log.info("[AsyncApp] Starting port configuration...")
                await self.bot.configure_ports()
                log.info("[AsyncApp] Port configuration complete")
                # Update port labels in Config tab
                self.update_port_labels()
                # Enable controls now that ports are configured
                self._set_controls_enabled(True)
            
            asyncio.create_task(configure_ports_delayed())
            
            await self.async_run(async_lib='asyncio')
            log.info('App done')
            if self.bot_task:
                self.bot_task.cancel()

        return asyncio.gather(run_wrapper())
