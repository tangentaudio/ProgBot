import os
os.environ['KCFG_INPUT_MOUSE'] = 'mouse,disable_on_activity'

from kivy.config import Config

#Config.set('graphics', 'width', 800)
#Config.set('graphics', 'height', 415)
#Config.set('graphics', 'resizable', 0)
Config.set('graphics', 'fullscreen', 'auto')
Config.set('kivy', 'keyboard_mode', 'systemanddock') 

import sys
import asyncio
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
import os

import sequence
from panel_settings import get_panel_settings, find_panel_files
from numpad_keyboard import switch_keyboard_layout

class OutputCapture:
    """Captures print/stderr output and stores it until LogViewer is ready."""
    def __init__(self):
        self.buffer = []
        self.log_viewer = None
        self.original_stdout = sys.__stdout__
        self.original_stderr = sys.__stderr__
    
    def write(self, text):
        """Write text to buffer and to LogViewer if available."""
        self.buffer.append(text)
        if self.log_viewer:
            try:
                self.log_viewer.write(text)
            except Exception:
                pass
        else:
            # If no LogViewer yet, write to original stdout for debugging
            self.original_stdout.write(text)
            self.original_stdout.flush()
    
    def set_log_viewer(self, log_viewer):
        """Set the LogViewer and flush buffered output."""
        self.log_viewer = log_viewer
        # Flush buffer to the LogViewer
        for text in self.buffer:
            try:
                log_viewer.write(text)
            except Exception:
                pass
    
    def flush(self):
        pass


# Create a global output capture instance
output_capture = OutputCapture()
sys.stdout = output_capture
sys.stderr = output_capture


class GridCell(ButtonBehavior, BoxLayout):
    """A custom grid cell button that toggles on press."""
    cell_label = StringProperty("")
    cell_checked = BooleanProperty(True)
    cell_bg_color = ListProperty([0, 0.5, 0.5, 1])  # Default dark cyan (ON)
    status_line1 = StringProperty("")  # First line of status (probe status)
    status_line2 = StringProperty("")  # Second line of status (program status)
    
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
        self._update_bg_color()
        # Update label to show/hide SKIPPED
        if self.cell_checked:
            self.cell_label = self.base_cell_label
        else:
            self.cell_label = "SKIPPED"
        # Call the callback if provided
        if self.on_toggle_callback:
            self.on_toggle_callback()
    
    def _update_bg_color(self):
        """Set background color based on cell_checked state."""
        if self.cell_checked:
            # Dark cyan when ON
            self.cell_bg_color = [0, 0.5, 0.5, 1]
        else:
            # Black when OFF
            self.cell_bg_color = [0, 0, 0, 1]
    
    def update_status(self, board_status):
        """Update cell status from BoardStatus object.
        
        Args:
            board_status: BoardStatus instance with probe and program status
        """
        try:
            status_line1, status_line2 = board_status.status_text
            self.status_line1 = status_line1
            self.status_line2 = status_line2
            
            # Update background color based on status
            if not board_status.enabled:
                self.cell_bg_color = [0.2, 0.2, 0.2, 1]  # Dark gray for disabled
            elif board_status.program_status.name == "IDENTIFIED":
                self.cell_bg_color = [1, 0, 1, 1]  # Purple when identified
            elif board_status.program_status.name == "COMPLETED":
                self.cell_bg_color = [0, 1, 0, 1]  # Green when programmed
            elif board_status.program_status.name == "FAILED":
                self.cell_bg_color = [1, 0, 0, 1]  # Red on failure
            elif board_status.program_status.name == "SKIPPED":
                self.cell_bg_color = [0, 0, 0, 1]  # Black when skipped
            elif board_status.program_status.name in ("PROGRAMMING", "IDENTIFYING"):
                self.cell_bg_color = [1, 1, 0, 1]  # Yellow while programming or identifying
            elif board_status.probe_status.name == "PROBING":
                self.cell_bg_color = [0, 1, 1, 1]  # Cyan while probing
        except Exception as e:
            print(f"[GridCell] Error updating status: {e}")

class LogViewer(ScrollView):
    def __init__(self, **kwargs):
        kwargs.setdefault('effect_cls', ScrollEffect)
        super().__init__(**kwargs)
        self.log_text = None
        # Find log_text TextInput in children after build
        Clock.schedule_once(self._setup_log_text, 0)

    def _setup_log_text(self, dt):
        """Find the log_text TextInput widget."""
        # First check direct children of this ScrollView
        for child in self.children:
            if isinstance(child, TextInput):
                self.log_text = child
                print(f"[LogViewer] Found TextInput in children: {self.log_text}")
                break
        
        # Fallback: check ids
        if not self.log_text:
            self.log_text = self.ids.get('log_text')
            if self.log_text:
                print(f"[LogViewer] Found TextInput in ids: {self.log_text}")
        
        if self.log_text:
            self.log_text.bind(minimum_height=self.log_text.setter('height'))
            print(f"[LogViewer] TextInput setup complete, ready for logging")
        else:
            print(f"[LogViewer] Warning: TextInput not found")

    def write(self, text):
        try:
            if self.log_text:
                self.log_text.text += text
                Clock.schedule_once(lambda dt: self.scroll_to_bottom())
            else:
                # Try to find it if it wasn't found earlier
                for child in self.children:
                    if isinstance(child, TextInput):
                        self.log_text = child
                        self.log_text.text += text
                        Clock.schedule_once(lambda dt: self.scroll_to_bottom())
                        break
        except Exception as e:
            print(f"[LogViewer] Error writing to log: {e}")

    def scroll_to_bottom(self):
        self.scroll_y = 0

    def flush(self):
        pass


class AsyncApp(App):
    
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
    
    def toggle_log_popup(self):
        """Toggle the log viewer popup."""
        try:
            if not self.log_popup:
                # Create popup if it doesn't exist
                self.log_popup = Factory.LogPopup()
                # Give the popup time to initialize, then set up redirection
                Clock.schedule_once(lambda dt: self._setup_popup_output_redirection(), 0.2)
            
            # Check if popup is open using the internal _is_open attribute
            if hasattr(self.log_popup, '_is_open') and self.log_popup._is_open:
                self.log_popup.dismiss()
            else:
                self.log_popup.open()
        except Exception as e:
            print(f"Error toggling log popup: {e}")
            import traceback
            traceback.print_exc()
    
    def _setup_popup_output_redirection(self):
        """Redirect stdout/stderr to the popup's LogViewer once it's ready."""
        if self.log_popup and hasattr(self.log_popup, 'ids'):
            log_viewer = self.log_popup.ids.get('log_viewer_widget')
            if log_viewer:
                output_capture.set_log_viewer(log_viewer)
                output_capture.write("[App] Redirecting stdout to popup LogViewer\n")
            else:
                output_capture.write("[App] Warning: Could not find log_viewer_widget in popup\n")

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
            print(f"[ErrorPopup] Failed to open: {e}")
    
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
            print("Error: panel_grid not found")
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
            label_text = labels[cell_index] if labels and cell_index < len(labels) else f"Board {cell_index}"
            
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
                    print(f"[GridCell] Saved skip_board_pos: {skip_pos_updated}")
                return on_toggle
            
            # Create cell with appropriate checked state and callback
            cell = GridCell(cell_label=label_text, cell_checked=not is_skipped, on_toggle_callback=make_callback())
            
            # If skipped, update the label to show SKIPPED (binding may not fire during init)
            if is_skipped:
                cell.cell_label = "SKIPPED"
            
            grid.add_widget(cell)            
            # Store cell reference by ID
            self.grid_cells[cell_index] = cell
    
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
    
    def on_board_cols_change(self, value):
        """Handle board columns spinner change."""
        try:
            cols = int(value)
            if self.panel_settings:
                self.panel_settings.set('board_cols', value)
            if hasattr(self, 'settings_data'):
                self.settings_data['board_cols'] = value
            print(f"Updated board_num_cols: {cols}")
            # Repopulate grid with new dimensions
            current_rows = self.bot.config.board_num_rows if self.bot else int(get_settings().get('board_rows', '5'))
            self.populate_grid(current_rows, cols)
            # Notify bot of panel change
            if self.bot:
                self.bot.config.board_num_cols = cols
                self.bot.init_panel()
        except ValueError:
            pass
    
    def on_board_rows_change(self, value):
        """Handle board rows spinner change."""
        try:
            rows = int(value)
            if self.panel_settings:
                self.panel_settings.set('board_rows', value)
            if hasattr(self, 'settings_data'):
                self.settings_data['board_rows'] = value
            print(f"Updated board_num_rows: {rows}")
            # Repopulate grid with new dimensions
            current_cols = self.bot.config.board_num_cols if self.bot else int(get_settings().get('board_cols', '2'))
            self.populate_grid(rows, current_cols)
            # Notify bot of panel change
            if self.bot:
                self.bot.config.board_num_rows = rows
                self.bot.init_panel()
        except ValueError:
            pass
    
    def on_col_width_change(self, value):
        """Handle column width text input change."""
        try:
            width = float(value)
            if self.panel_settings:
                self.panel_settings.set('col_width', value)
            if hasattr(self, 'settings_data'):
                self.settings_data['col_width'] = value
            if self.bot:
                self.bot.config.board_col_width = width
            print(f"Updated board_col_width: {width}")
        except ValueError:
            pass
    
    def on_row_height_change(self, value):
        """Handle row height text input change."""
        try:
            height = float(value)
            if self.panel_settings:
                self.panel_settings.set('row_height', value)
            if hasattr(self, 'settings_data'):
                self.settings_data['row_height'] = value
            if self.bot:
                self.bot.config.board_row_height = height
            print(f"Updated board_row_height: {height}")
        except ValueError:
            pass
    
    def on_board_x_change(self, value):
        """Handle board X text input change."""
        try:
            board_x = float(value)
            if self.panel_settings:
                self.panel_settings.set('board_x', value)
            if hasattr(self, 'settings_data'):
                self.settings_data['board_x'] = value
            if self.bot:
                self.bot.config.board_x = board_x
            print(f"Updated board_x: {board_x}")
        except ValueError:
            pass
    
    def on_board_y_change(self, value):
        """Handle board Y text input change."""
        try:
            board_y = float(value)
            if self.panel_settings:
                self.panel_settings.set('board_y', value)
            if hasattr(self, 'settings_data'):
                self.settings_data['board_y'] = value
            if self.bot:
                self.bot.config.board_y = board_y
            print(f"Updated board_y: {board_y}")
        except ValueError:
            pass
    
    def on_probe_plane_change(self, value):
        """Handle probe plane to board text input change."""
        try:
            probe_plane = float(value)
            if self.panel_settings:
                self.panel_settings.set('probe_plane', value)
            if hasattr(self, 'settings_data'):
                self.settings_data['probe_plane'] = value
            if self.bot:
                self.bot.config.probe_plane_to_board = probe_plane
            print(f"Updated probe_plane_to_board: {probe_plane}")
        except ValueError:
            pass

    def on_operation_change(self, value):
        """Handle operation mode spinner change."""
        # Map display text to OperationMode enum values
        mode_mapping = {
            "Identify Only": sequence.OperationMode.IDENTIFY_ONLY,
            "Program": sequence.OperationMode.PROGRAM,
            "Program & Test": sequence.OperationMode.PROGRAM_AND_TEST,
            "Test Only": sequence.OperationMode.TEST_ONLY,
        }
        selected = mode_mapping.get(value, sequence.OperationMode.PROGRAM)
        if self.bot:
            self.bot.config.operation_mode = selected
        if self.panel_settings:
            self.panel_settings.set('operation_mode', value)
        if hasattr(self, 'settings_data'):
            self.settings_data['operation_mode'] = value
        print(f"Updated operation_mode: {selected}")
    
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
            print(f"[AsyncApp.build] Loaded settings from file")
        except Exception as e:
            print(f"[AsyncApp.build] Error loading settings: {e}")
        
        # Load the KV file which defines the AppRoot template
        kv_file = os.path.join(os.path.dirname(__file__), 'progbot.kv')
        Builder.load_file(kv_file)
        
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
        
        # Set panel file label to current file
        if self.panel_file_label and self.panel_settings:
            import os as os_module
            panel_name = os_module.path.basename(self.panel_settings.panel_file)
            self.panel_file_label.text = panel_name
        
        # Store references to config widgets for enable/disable
        self.config_widgets = [
            root.ids.get('board_cols_spinner'),
            root.ids.get('board_rows_spinner'),
            root.ids.get('col_width_input'),
            root.ids.get('row_height_input'),
            root.ids.get('board_x_input'),
            root.ids.get('board_y_input'),
            root.ids.get('probe_plane_input'),
            root.ids.get('operation_spinner')
        ]
        
        # Create and store the log popup
        self.log_popup = Factory.LogPopup()
        self.error_popup = Factory.ErrorPopup()
        
        # Redirect stdout/stderr to the popup's LogViewer so all messages are captured
        Clock.schedule_once(lambda dt: self._setup_initial_redirection(), 0.2)
        
        # Update widget values from settings
        Clock.schedule_once(lambda dt: self._apply_settings_to_widgets(root, settings_data), 0.3)

        return root

    def _config_from_settings(self):
        """Build a ProgBot config from the loaded settings."""
        # Load panel-specific settings
        settings_data = getattr(self, 'settings_data', None) or (self.panel_settings.get_all() if self.panel_settings else {})
        
        # Load hardware settings (port IDs) from main settings file
        hardware_settings = get_settings().get_all()
        
        defaults = sequence.Config()

        def _get(key, cast, fallback):
            try:
                return cast(settings_data.get(key, fallback))
            except Exception:
                return fallback

        mode_mapping = {
            "Identify Only": sequence.OperationMode.IDENTIFY_ONLY,
            "Program": sequence.OperationMode.PROGRAM,
            "Program & Test": sequence.OperationMode.PROGRAM_AND_TEST,
            "Test Only": sequence.OperationMode.TEST_ONLY,
        }

        mode_text = settings_data.get('operation_mode', defaults.operation_mode.value)
        skip_positions = settings_data.get('skip_board_pos', []) or []

        return sequence.Config(
            board_x=_get('board_x', float, defaults.board_x),
            board_y=_get('board_y', float, defaults.board_y),
            board_col_width=_get('col_width', float, defaults.board_col_width),
            board_row_height=_get('row_height', float, defaults.board_row_height),
            board_num_rows=_get('board_rows', int, defaults.board_num_rows),
            board_num_cols=_get('board_cols', int, defaults.board_num_cols),
            probe_plane_to_board=_get('probe_plane', float, defaults.probe_plane_to_board),
            operation_mode=mode_mapping.get(mode_text, defaults.operation_mode),
            skip_board_pos=skip_positions,
            motion_port_id=hardware_settings.get('motion_port_id', ''),
            motion_baud=defaults.motion_baud,
            head_port_id=hardware_settings.get('head_port_id', ''),
            head_baud=defaults.head_baud,
            target_port_id=hardware_settings.get('target_port_id', ''),
            target_baud=defaults.target_baud,
        )
    
    def _apply_settings_to_widgets(self, root, settings_data):
        """Apply loaded settings to UI widgets."""
        try:
            # Update spinner values
            cols_spinner = root.ids.get('board_cols_spinner')
            if cols_spinner:
                cols_spinner.text = settings_data.get('board_cols', '2')
            
            rows_spinner = root.ids.get('board_rows_spinner')
            if rows_spinner:
                rows_spinner.text = settings_data.get('board_rows', '5')
            
            # Update text input values
            col_width_input = root.ids.get('col_width_input')
            if col_width_input:
                col_width_input.text = settings_data.get('col_width', '48.0')
            
            row_height_input = root.ids.get('row_height_input')
            if row_height_input:
                row_height_input.text = settings_data.get('row_height', '29.0')
            
            board_x_input = root.ids.get('board_x_input')
            if board_x_input:
                board_x_input.text = settings_data.get('board_x', '110.2')
            
            board_y_input = root.ids.get('board_y_input')
            if board_y_input:
                board_y_input.text = settings_data.get('board_y', '121.0')
            
            probe_plane_input = root.ids.get('probe_plane_input')
            if probe_plane_input:
                probe_plane_input.text = settings_data.get('probe_plane', '4.0')
            
            operation_spinner = root.ids.get('operation_spinner')
            if operation_spinner:
                operation_spinner.text = settings_data.get('operation_mode', 'Program')
            
            print(f"[AsyncApp] Applied settings to widgets")
        except Exception as e:
            print(f"[AsyncApp] Error applying settings to widgets: {e}")
    
    def _setup_initial_redirection(self):
        """Set up initial stdout/stderr redirection to popup's LogViewer."""
        if self.log_popup and hasattr(self.log_popup, 'ids'):
            log_viewer = self.log_popup.ids.get('log_viewer_widget')
            if log_viewer:
                # Flush all buffered output to the LogViewer
                output_capture.set_log_viewer(log_viewer)
                output_capture.write("[App] Initial redirection complete, flushing buffered output\n")
    
    def _set_config_widgets_enabled(self, enabled):
        """Enable or disable all configuration widgets.
        
        Args:
            enabled: True to enable, False to disable
        """
        if not hasattr(self, 'config_widgets'):
            print("[Config] Warning: config_widgets not initialized")
            return
        for widget in self.config_widgets:
            if widget:
                try:
                    widget.disabled = not enabled
                except Exception as e:
                    print(f"[Config] Error setting widget disabled state: {e}")

    def _set_grid_cells_enabled(self, enabled: bool):
        """Enable or disable all grid cells."""
        for cell in self.grid_cells.values():
            try:
                cell.disabled = not enabled
            except Exception as e:
                print(f"[Grid] Error setting cell enabled state: {e}")

    def stop(self, instance):
        # concise stops using helper
        print(f"[Stop] Button pressed")
        try:
            self._set_widget('start_button', disabled=False)
            self._set_widget('stop_button', disabled=True)
            self._set_widget('phase_label', text="Stopped")
            # Re-enable config widgets
            self._set_config_widgets_enabled(True)
            self._set_grid_cells_enabled(True)
            
            # Mark all incomplete cells as failed
            for cell in self.grid_cells.values():
                # Only update cells that haven't completed or been skipped
                if cell.cell_bg_color not in (
                    [0, 1, 0, 1],      # Green (COMPLETED)
                    [1, 0, 1, 1],      # Purple (IDENTIFIED)
                    [0, 0, 0, 1],      # Black (SKIPPED)
                    [0.2, 0.2, 0.2, 1] # Dark gray (DISABLED)
                ):
                    cell.cell_bg_color = [1, 0, 0, 1]  # Red (FAILED)
                    cell.status_line1 = "Stopped"
                    cell.status_line2 = "(incomplete)"
        except Exception as e:
            print(f"[Stop] Error in widget updates: {e}")
        
        if (bot := getattr(self, 'bot_task', None)):
            try:
                print(f"[Stop] Cancelling bot task")
                bot.cancel()
                print(f"[Stop] Bot task cancelled")
            except Exception as e:
                print(f"[Stop] Error cancelling bot task: {e}")
        
        
    def start(self, instance):
        # concise widget updates using helper
        print(f"[Start] Button pressed")
        self._set_widget('start_button', disabled=True)
        self._set_widget('stop_button', disabled=False)
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
            print(f"[Start] Bot found, updating skip positions")
            b.set_skip_board_pos(skip_pos)
        else:
            print(f"[Start] Warning: Bot not found")
        
        loop = asyncio.get_event_loop()
        if (b := getattr(self, 'bot', None)):
            print(f"[Start] Creating bot task")
            self.bot_task = loop.create_task(b.full_cycle())
            # Add callback to re-enable config widgets when task completes
            self.bot_task.add_done_callback(self._on_task_complete)
            print(f"[Start] Bot task created")
        else:
            print(f"[Start] Error: Bot not available to create task")
    
    def _on_task_complete(self, task):
        """Called when the bot task completes or is cancelled."""
        try:
            task.exception()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[BotTask] Completed with error: {e}")

        # Re-enable start button and config widgets
        Clock.schedule_once(lambda dt: self._set_widget('start_button', disabled=False))
        Clock.schedule_once(lambda dt: self._set_widget('stop_button', disabled=True))
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
        print(f"Board status change: cell_id={cell_id}, status={board_status}")
        if cell := self.grid_cells.get(cell_id):
            Clock.schedule_once(lambda dt: cell.update_status(board_status))
        else:
            print(f"Warning: Cell {cell_id} not found in grid_cells")

    @listener
    async def on_phase_change(self, value):
        print(f"Phase is now {value}")
        if (lbl := getattr(self, 'phase_label', None)):
            Clock.schedule_once(lambda dt: setattr(lbl, 'text', str(value)))

    @listener
    async def on_panel_change(self, cols, rows):
        print(f"Panel changed: cols={cols}, rows={rows}")
        Clock.schedule_once(lambda dt: self.populate_grid(rows, cols))

    @listener
    async def on_cell_color_change(self, cell_id, color_rgba):
        """Update a cell's background color by ID.
        
        Args:
            cell_id: The cell ID (0-indexed from bottom-left)
            color_rgba: List or tuple [r, g, b, a] with values 0-1
        """
        print(f"Cell color change: cell_id={cell_id}, color={color_rgba}")
        if cell := self.grid_cells.get(cell_id):
            Clock.schedule_once(lambda dt: setattr(cell, 'cell_bg_color', color_rgba))
        else:
            print(f"Warning: Cell {cell_id} not found in grid_cells")

    @listener
    async def on_error_occurred(self, error_info):
        self.last_error_info = error_info
        Clock.schedule_once(lambda dt: self._open_error_popup(error_info))

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
            print("[ErrorPopup] No board info for retry; restarting full cycle")
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
        print(f"[ErrorPopup] Retrying board [{col}, {row}]")
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
            print("[ErrorPopup] Grid dimensions not initialized; cannot skip")
            return

        try:
            cell_id = col * self.grid_rows + row
            if (cell := self.grid_cells.get(cell_id)):
                cell.cell_checked = False
            skip_positions = self.get_skip_board_pos()
            get_settings().set('skip_board_pos', skip_positions)
            if self.bot:
                self.bot.set_skip_board_pos(skip_positions)
            print(f"[ErrorPopup] Skipped board [{col}, {row}]")
        except Exception as e:
            print(f"[ErrorPopup] Failed to skip board: {e}")

    def open_panel_file_chooser(self):
        """Open file chooser to load a different panel settings file."""
        if not self.file_chooser_popup:
            self.file_chooser_popup = Factory.PanelFileChooser()
        
        try:
            # Populate with .panel files from working directory
            panel_files = find_panel_files()
            items = []
            for fullpath in panel_files:
                items.append({
                    'filename': os.path.basename(fullpath),
                    'fullpath': fullpath,
                    'selected': False
                })
            
            self.panel_file_data = items
            file_list = self.file_chooser_popup.ids.file_list
            file_list.data = self.panel_file_data
            self.selected_panel_path = None
            
            self.file_chooser_popup.open()
        except Exception as e:
            print(f"[PanelChooser] Error opening file chooser: {e}")
    
    def on_file_row_pressed(self, fullpath):
        """Called when a file row is pressed."""
        print(f"[PanelChooser] Row pressed - fullpath: {fullpath}")
        try:
            # Select file and update all items
            for item in self.panel_file_data:
                item['selected'] = (item['fullpath'] == fullpath)
            self.selected_panel_path = fullpath
            # Force full refresh of RecycleView
            file_list = self.file_chooser_popup.ids.file_list
            file_list.data = []
            Clock.schedule_once(lambda dt: setattr(file_list, 'data', self.panel_file_data), 0.01)
            print(f"[PanelChooser] Selected: {self.selected_panel_path}")
        except Exception as e:
            print(f"[PanelChooser] Error on press: {e}")
            import traceback
            traceback.print_exc()
    
    def on_panel_row_click(self, row_widget):
        """Called when a panel file row is clicked - no longer used."""
        pass
    
    def on_custom_panel_file_selected(self):
        """Called when Load button is pressed in custom file chooser."""
        if hasattr(self, 'selected_panel_path') and self.selected_panel_path:
            self.on_panel_file_selected(self.selected_panel_path)

    def on_panel_file_selected(self, path):
        """Called when a panel file is selected from the file chooser."""
        if not path or not self.panel_settings:
            return
        
        try:
            self.panel_settings.load_file(path)
            self.settings_data = self.panel_settings.get_all()
            # Update the panel file label
            import os
            panel_name = os.path.basename(path)
            if self.panel_file_label:
                self.panel_file_label.text = panel_name
            # Re-apply settings to widgets
            Clock.schedule_once(lambda dt: self._apply_settings_to_widgets_now())
            print(f"[PanelChooser] Loaded panel: {path}")
        except Exception as e:
            print(f"[PanelChooser] Error loading panel: {e}")

    def _apply_settings_to_widgets_now(self):
        """Re-apply current settings to all widgets."""
        if not hasattr(self, 'phase_label'):
            return
        root = self.phase_label.parent.parent.parent
        self._apply_settings_to_widgets(root, self.settings_data)

    def open_save_panel_dialog(self):
        """Open dialog to save current panel with a new name."""
        if not self.save_panel_dialog:
            self.save_panel_dialog = Factory.SavePanelDialog()
        
        try:
            # Pre-populate with current filename (without .panel extension)
            if hasattr(self.save_panel_dialog, 'ids') and 'panel_name_input' in self.save_panel_dialog.ids:
                panel_input = self.save_panel_dialog.ids.panel_name_input
                if self.panel_settings:
                    import os
                    current_file = os.path.basename(self.panel_settings.panel_file)
                    # Remove .panel extension if present
                    if current_file.endswith('.panel'):
                        current_file = current_file[:-6]
                    panel_input.text = current_file
            
            self.save_panel_dialog.open()
            
            # Focus and show keyboard after dialog opens
            Clock.schedule_once(lambda dt: self._focus_panel_input(), 0.1)
        except Exception as e:
            print(f"[SavePanel] Error opening save dialog: {e}")

    def _focus_panel_input(self):
        """Focus the panel name input and trigger keyboard."""
        try:
            if hasattr(self.save_panel_dialog, 'ids') and 'panel_name_input' in self.save_panel_dialog.ids:
                panel_input = self.save_panel_dialog.ids.panel_name_input
                panel_input.focus = True
                from kivy.core.window import Window
                # Reset to default QWERTY layout for text input
                self.set_keyboard_layout('qwerty.json')
                Window.show_keyboard()
        except Exception as e:
            print(f"[SavePanel] Error focusing input: {e}")
    
    def set_keyboard_layout(self, layout):
        """Switch the virtual keyboard layout."""
        switch_keyboard_layout(layout)

    def on_save_panel_confirmed(self, filename: str):
        """Called when user confirms saving panel with new name."""
        if not filename or not self.panel_settings:
            print("[SavePanel] No filename provided")
            return
        
        try:
            import os
            # Clean up the filename
            filename = filename.strip()
            
            # Remove any existing .panel extension if user added it
            if filename.endswith('.panel'):
                filename = filename[:-6]
            
            # Remove any other extension or dots
            filename = os.path.splitext(filename)[0]
            
            # Validate filename (basic check)
            if not filename or all(c in '._-' for c in filename):
                print("[SavePanel] Invalid filename")
                return
            
            # Add .panel extension
            filename = filename + '.panel'
            
            # Build full path in current directory
            filepath = os.path.join(os.getcwd(), filename)
            
            # Save current settings to new file
            self.panel_settings.panel_file = filepath
            self.panel_settings._save_settings()
            
            # Update the display
            if self.panel_file_label:
                self.panel_file_label.text = filename
            
            # Remember this file
            from settings import get_settings
            app_settings = get_settings()
            app_settings.set('last_panel_file', filepath)
            
            print(f"[SavePanel] Saved panel to: {filepath}")
        except Exception as e:
            print(f"[SavePanel] Error saving panel: {e}")


    def app_func(self):
        async def run_wrapper():
            config = self._config_from_settings()
            self.bot = sequence.ProgBot(config=config, panel_settings=self.panel_settings)
            
            self.bot.phase_changed.connect(self.on_phase_change)
            self.bot.panel_changed.connect(self.on_panel_change)
            self.bot.cell_color_changed.connect(self.on_cell_color_change)
            self.bot.board_status_changed.connect(self.on_board_status_change)
            self.bot.error_occurred.connect(self.on_error_occurred)
            
            # Now emit panel dimensions after listeners are connected
            self.bot.init_panel()
            await self.async_run(async_lib='asyncio')
            print('App done')
            if self.bot_task:
                self.bot_task.cancel()

        return asyncio.gather(run_wrapper())
