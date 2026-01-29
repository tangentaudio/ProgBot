"""Board Detail Popup - Shows detailed status for a single board.

This module contains the BoardDetailPopup class which displays comprehensive
information about a board including:
- Board number and serial number
- Status of each phase (Vision, Contact, Program, Provisioning, Test)
- Failure reason if any
- Captured variables from provisioning
- QR image thumbnail
- Action buttons (Clear Status, Re-run, Close)
"""

from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.image import Image
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.clock import Clock

from logger import get_logger
from board_status import get_phase_color, has_failure, DOT_PENDING, DOT_DISABLED

log = get_logger(__name__)


class BoardDetailPopup:
    """Popup to show detailed status for a single board.
    
    Shows comprehensive information about a board including:
    - Board number and serial number
    - Status of each phase (Vision, Contact, Program, Provisioning, Test)
    - Failure reason if any
    - Action buttons (Clear Status, Re-run, Close)
    """
    
    # Phase information mapping: (label, dot_attr, enabled_attr, status_attr, timing_key)
    PHASE_DEFINITIONS = [
        ("Vision", "vision_dot", "vision_enabled", "vision_status", "qr_scan"),
        ("Contact", "contact_dot", "contact_enabled", "probe_status", "probe"),
        ("Program", "program_dot", "program_enabled", "program_status", "program"),
        ("Provisioning", "provision_dot", "provision_enabled", "provision_status", "provision"),
        ("Test", "test_dot", "test_enabled", "test_status", "test"),
    ]
    
    # Status attr to timing key mapping
    PHASE_INFO = {
        'Vision': ('vision_status', 'qr_scan'),
        'Contact': ('probe_status', 'probe'),
        'Program': ('program_status', 'program'),
        'Provisioning': ('provision_status', 'provision'),
        'Test': ('test_status', 'test'),
    }
    
    def __init__(self, app):
        """Initialize the board detail popup.
        
        Args:
            app: The main Kivy App instance
        """
        self.app = app
        self.popup = None
        self.current_cell = None
        self.current_cell_id = None
        self._update_event = None
        # References to updateable widgets
        self._status_badge = None
        self._failure_box = None
        self._failure_label = None
        self._phase_widgets = {}  # {phase_name: {dot_label, timing_label, ...}}
        self._phase_cards = {}  # {phase_name: card_widget}
        self._selected_phase = None
        self._clear_btn = None
        self._rerun_btn = None
        self._serial_label = None
        self._detail_header = None
        self._detail_content = None
        self._detail_image = None
        self._captures_label = None
    
    def _is_cycle_running(self):
        """Check if a cycle is currently running."""
        if hasattr(self.app, 'bot_task') and self.app.bot_task and not self.app.bot_task.done():
            return True
        return False
    
    def _get_board_status(self, cell_id):
        """Get the BoardStatus for a cell ID."""
        if not self.app.bot:
            log.debug(f"[BoardDetail] _get_board_status: app.bot is None/False")
            return None
        if not hasattr(self.app.bot, 'board_statuses'):
            log.debug(f"[BoardDetail] _get_board_status: bot has no board_statuses attr")
            return None
        position = self._cell_id_to_position(cell_id)
        result = self.app.bot.board_statuses.get(position)
        log.debug(f"[BoardDetail] _get_board_status: cell_id={cell_id}, position={position}, found={result is not None}")
        return result
    
    def _cell_id_to_position(self, cell_id):
        """Convert cell_id to (col, row) position tuple."""
        grid_rows = getattr(self.app, 'grid_rows', 1)
        col = cell_id // grid_rows
        row = cell_id % grid_rows
        return (col, row)
    
    def _get_board_times(self, position):
        """Get timing data for a board position."""
        if self.app.bot and hasattr(self.app.bot, 'stats') and self.app.bot.stats:
            return self.app.bot.stats.board_times.get(position, {})
        return {}
    
    def _get_phase_status_text(self, status_enum):
        """Convert a phase status enum to display text."""
        if status_enum is None:
            return "Unknown"
        name = status_enum.name
        return name.replace("_", " ").title()
    
    def _get_phase_color(self, status_name):
        """Get color for a phase status (delegates to centralized function)."""
        return get_phase_color(status_name)
    
    def show(self, cell, cell_id):
        """Show the detail popup for a board.
        
        Args:
            cell: The GridCell widget
            cell_id: The cell index in the grid
        """
        self.current_cell = cell
        self.current_cell_id = cell_id
        self._phase_widgets = {}
        self._selected_phase = None
        self._phase_cards = {}
        
        # Build popup content
        content = BoxLayout(orientation='vertical', spacing=10, padding=10)
        
        # Header section
        header = self._build_header(cell)
        content.add_widget(header)
        
        # Failure reason box
        self._build_failure_box()
        content.add_widget(self._failure_box)
        
        # Two-column layout: phase list (left) and detail panel (right)
        main_area = self._build_main_area(cell)
        content.add_widget(main_area)
        
        # Action buttons
        buttons = self._build_action_buttons()
        content.add_widget(buttons)
        
        # Create and show popup
        self.popup = Popup(
            title='',
            content=content,
            size_hint=(0.95, 0.85),
            auto_dismiss=True,
            separator_height=0
        )
        self.popup.bind(on_dismiss=self._on_popup_dismiss)
        self.popup.open()
        
        # Initial update
        self._update_content()
        
        # Schedule periodic updates while popup is open
        self._update_event = Clock.schedule_interval(self._update_content, 0.25)
    
    def _build_header(self, cell):
        """Build the header section with board info, captures, and status."""
        header = BoxLayout(orientation='horizontal', size_hint_y=None, height=70, spacing=10)
        
        # Board number and serial (left side)
        board_info = BoxLayout(orientation='vertical', size_hint_x=0.35)
        
        # Get col,row from cell_id
        position = self._cell_id_to_position(self.current_cell_id)
        col, row = position if position else (0, 0)
        
        board_label = Label(
            text=f"[b]Board {cell.cell_label}[/b]  [size=14sp][color=#888888][{col},{row}][/color][/size]",
            markup=True,
            font_size='24sp',
            halign='left',
            valign='middle',
            size_hint_y=0.5
        )
        board_label.bind(size=board_label.setter('text_size'))
        board_info.add_widget(board_label)
        
        self._serial_label = Label(
            text=f"Serial: {cell.serial_number or 'Not scanned'}",
            font_size='14sp',
            halign='left',
            valign='middle',
            size_hint_y=0.5,
            color=[0.7, 0.7, 0.7, 1]
        )
        self._serial_label.bind(size=self._serial_label.setter('text_size'))
        board_info.add_widget(self._serial_label)
        header.add_widget(board_info)
        
        # Captured variables (middle section)
        self._captures_label = Label(
            text="",
            markup=True,
            font_size='11sp',
            halign='left',
            valign='top',
            size_hint_x=0.45,
            color=[0.6, 0.8, 0.6, 1]
        )
        self._captures_label.bind(size=self._captures_label.setter('text_size'))
        header.add_widget(self._captures_label)
        
        # Overall status indicator (right side)
        self._status_badge = Label(
            text="Pending",
            font_size='16sp',
            bold=True,
            halign='center',
            valign='middle',
            size_hint_x=0.2,
            color=[0.5, 0.5, 0.5, 1]
        )
        header.add_widget(self._status_badge)
        
        return header
    
    def _build_failure_box(self):
        """Build the failure reason box (always create, hide if no error)."""
        self._failure_box = BoxLayout(size_hint_y=None, height=50, padding=[10, 5])
        with self._failure_box.canvas.before:
            Color(0.6, 0.2, 0.2, 1)
            self._failure_box._rect = RoundedRectangle(
                pos=self._failure_box.pos, 
                size=self._failure_box.size, 
                radius=[5]
            )
        self._failure_box.bind(pos=lambda w, p: setattr(w._rect, 'pos', p))
        self._failure_box.bind(size=lambda w, s: setattr(w._rect, 'size', s))
        
        self._failure_label = Label(
            text="",
            markup=True,
            font_size='13sp',
            halign='left',
            valign='middle',
            color=[1, 0.8, 0.8, 1]
        )
        self._failure_label.bind(size=self._failure_label.setter('text_size'))
        self._failure_box.add_widget(self._failure_label)
    
    def _build_main_area(self, cell):
        """Build the two-column main area with phases and detail panel."""
        main_area = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=1)
        
        # Left column - Phase status list
        left_col = self._build_phase_list(cell)
        main_area.add_widget(left_col)
        
        # Right column - Detail panel
        right_col = self._build_detail_panel()
        main_area.add_widget(right_col)
        
        return main_area
    
    def _build_phase_list(self, cell):
        """Build the left column with phase status cards."""
        left_col = BoxLayout(orientation='vertical', size_hint_x=0.45, spacing=4)
        
        phases_box = BoxLayout(orientation='vertical', spacing=4, size_hint_y=None, padding=[0, 3])
        phases_box.bind(minimum_height=phases_box.setter('height'))
        
        # Create a clickable phase card class
        class ClickablePhaseCard(ButtonBehavior, BoxLayout):
            pass
        
        for phase_name, dot_attr, enabled_attr, status_attr, timing_key in self.PHASE_DEFINITIONS:
            enabled = getattr(cell, enabled_attr, True)
            
            # Create clickable phase card (or non-clickable for disabled)
            if enabled:
                phase_card = ClickablePhaseCard(
                    orientation='horizontal', 
                    size_hint_y=None, 
                    height=32, 
                    spacing=4, 
                    padding=[6, 2]
                )
            else:
                phase_card = BoxLayout(
                    orientation='horizontal', 
                    size_hint_y=None, 
                    height=32, 
                    spacing=4, 
                    padding=[6, 2]
                )
            
            # Background color - dimmer for disabled phases
            bg_color = [0.2, 0.2, 0.25, 1] if enabled else [0.15, 0.15, 0.18, 0.6]
            with phase_card.canvas.before:
                phase_card._bg_color = Color(*bg_color)
                phase_card._rect = RoundedRectangle(
                    pos=phase_card.pos, 
                    size=phase_card.size, 
                    radius=[5]
                )
            phase_card.bind(pos=lambda w, p: setattr(w._rect, 'pos', p))
            phase_card.bind(size=lambda w, s: setattr(w._rect, 'size', s))
            
            # Bind click to select this phase (only if enabled)
            if enabled:
                phase_card.bind(on_release=lambda inst, pn=phase_name: self._select_phase(pn))
            
            # Status dot - use DejaVuSans for Unicode support
            dot_text = "·" if enabled else "—"
            dot_color = [1, 1, 1, 1] if enabled else [0.4, 0.4, 0.4, 1]
            dot_label = Label(
                text=dot_text,
                font_size='14sp',
                font_name='DejaVuSans',
                halign='center',
                valign='middle',
                size_hint_x=None,
                width=20,
                color=dot_color
            )
            phase_card.add_widget(dot_label)
            
            # Phase name
            name_color = [1, 1, 1, 1] if enabled else [0.4, 0.4, 0.4, 1]
            name_label = Label(
                text=phase_name,
                font_size='12sp',
                bold=True,
                halign='left',
                valign='middle',
                size_hint_x=0.5,
                color=name_color
            )
            name_label.bind(size=name_label.setter('text_size'))
            phase_card.add_widget(name_label)
            
            # Timing label - show "disabled" for disabled phases
            timing_text = "" if enabled else "disabled"
            timing_color = [0.6, 0.6, 0.6, 1] if enabled else [0.35, 0.35, 0.35, 1]
            timing_label = Label(
                text=timing_text,
                font_size='11sp',
                halign='right',
                valign='middle',
                size_hint_x=0.4,
                color=timing_color
            )
            timing_label.bind(size=timing_label.setter('text_size'))
            phase_card.add_widget(timing_label)
            
            # Store references for updates (only for enabled phases)
            if enabled:
                self._phase_widgets[phase_name] = {
                    'dot_label': dot_label,
                    'timing_label': timing_label,
                    'dot_attr': dot_attr,
                    'status_attr': status_attr,
                    'timing_key': timing_key,
                }
                self._phase_cards[phase_name] = phase_card
            
            phases_box.add_widget(phase_card)
        
        left_col.add_widget(phases_box)
        # Add spacer to push phases to top
        left_col.add_widget(BoxLayout())
        
        return left_col
    
    def _build_detail_panel(self):
        """Build the right column detail panel."""
        right_col = BoxLayout(orientation='vertical', size_hint_x=0.55, spacing=5)
        
        # Detail panel with background
        detail_panel = BoxLayout(orientation='vertical', padding=[10, 8], spacing=5)
        with detail_panel.canvas.before:
            Color(0.15, 0.15, 0.18, 1)
            detail_panel._rect = RoundedRectangle(
                pos=detail_panel.pos, 
                size=detail_panel.size, 
                radius=[8]
            )
        detail_panel.bind(pos=lambda w, p: setattr(w._rect, 'pos', p))
        detail_panel.bind(size=lambda w, s: setattr(w._rect, 'size', s))
        
        # Detail header
        self._detail_header = Label(
            text="Select a phase",
            font_size='14sp',
            bold=True,
            halign='left',
            valign='top',
            size_hint_y=None,
            height=25,
            color=[0.9, 0.9, 0.9, 1]
        )
        self._detail_header.bind(size=self._detail_header.setter('text_size'))
        detail_panel.add_widget(self._detail_header)
        
        # Detail content area - just a scrollview with text
        # Image will be shown inline via a separate widget when needed
        self._detail_scroll = ScrollView(size_hint=(1, 1))
        
        # Use a BoxLayout inside scroll for text + optional image
        self._detail_box = BoxLayout(orientation='vertical', size_hint_y=None, spacing=10)
        self._detail_box.bind(minimum_height=self._detail_box.setter('height'))
        
        self._detail_content = Label(
            text="Tap a phase on the left to see details",
            font_size='12sp',
            font_name='DejaVuSans',  # Unicode support for checkmarks and arrows
            markup=True,
            halign='left',
            valign='top',
            size_hint_y=None,
            color=[0.7, 0.7, 0.7, 1]
        )
        # For scrollable labels: bind width to scroll width, height to texture
        def update_text_width(scroll, value):
            self._detail_content.text_size = (value, None)
        self._detail_scroll.bind(width=update_text_width)
        self._detail_content.bind(texture_size=lambda w, ts: setattr(w, 'height', ts[1]))
        self._detail_box.add_widget(self._detail_content)
        
        # Image widget - added/removed dynamically, not always present
        self._detail_image = None  # Will be created when needed
        
        self._detail_scroll.add_widget(self._detail_box)
        detail_panel.add_widget(self._detail_scroll)
        right_col.add_widget(detail_panel)
        
        return right_col
    
    def _build_action_buttons(self):
        """Build the action buttons row."""
        buttons = BoxLayout(orientation='horizontal', size_hint_y=None, height=50, spacing=10)
        
        self._clear_btn = Button(
            text='Clear Status',
            font_size='14sp',
            size_hint_x=0.35,
            background_color=[0.3, 0.3, 0.4, 1]
        )
        self._clear_btn.bind(on_press=self._on_clear_status)
        buttons.add_widget(self._clear_btn)
        
        self._rerun_btn = Button(
            text='Re-run',
            font_size='14sp',
            size_hint_x=0.3,
            background_color=[0.2, 0.4, 0.6, 1]
        )
        self._rerun_btn.bind(on_press=self._on_rerun)
        buttons.add_widget(self._rerun_btn)
        
        close_btn = Button(
            text='Close',
            font_size='14sp',
            size_hint_x=0.35,
            background_color=[0.4, 0.3, 0.3, 1]
        )
        close_btn.bind(on_press=self._on_close)
        buttons.add_widget(close_btn)
        
        return buttons
    
    def _select_phase(self, phase_name):
        """Select a phase to show its details."""
        log.info(f"[BoardDetail] Phase selected: {phase_name}")
        self._selected_phase = phase_name
        
        # Update card highlighting
        for name, card in self._phase_cards.items():
            if name == phase_name:
                card._bg_color.rgba = [0.3, 0.4, 0.5, 1]  # Highlight selected
            else:
                card._bg_color.rgba = [0.2, 0.2, 0.25, 1]  # Normal
        
        # Update detail panel
        self._update_detail_panel()
    
    def _update_content(self, dt=None):
        """Update popup content with current status."""
        if not self.popup or not self.current_cell:
            return
        
        cell = self.current_cell
        board_status = self._get_board_status(self.current_cell_id)
        position = self._cell_id_to_position(self.current_cell_id)
        board_times = self._get_board_times(position)
        
        # Update serial number
        if self._serial_label:
            self._serial_label.text = f"Serial: {cell.serial_number or 'Not scanned'}"
        
        # Determine overall status
        self._update_overall_status(cell, board_status)
        
        # Update captured variables from provisioning
        self._update_captures_label(board_status)
        
        # Update failure reason
        self._update_failure_display(cell)
        
        # Update phase status cards
        self._update_phase_cards(cell, board_status, board_times)
        
        # Update detail panel if phase is selected
        self._update_detail_panel()
        
        # Update button states based on cycle running
        self._update_button_states()
    
    def _update_overall_status(self, cell, board_status):
        """Update the overall status badge."""
        overall_status = "Pending"
        status_color = [0.5, 0.5, 0.5, 1]
        
        if board_status:
            if has_failure(board_status):
                overall_status = "Failed"
                status_color = [0.9, 0.3, 0.3, 1]
            elif cell.result_icon == "✔":
                overall_status = "Passed"
                status_color = [0.3, 0.8, 0.3, 1]
            elif any(getattr(cell, f'_{p}_spinning', False) for p in ['vision', 'contact', 'program', 'provision', 'test']):
                overall_status = "In Progress"
                status_color = [0.3, 0.6, 1, 1]
        
        if self._status_badge:
            self._status_badge.text = overall_status
            self._status_badge.color = status_color
    
    def _update_captures_label(self, board_status):
        """Update the captured variables display."""
        if not self._captures_label:
            return
        
        captures_text = ""
        if board_status and hasattr(board_status, 'board_info') and board_status.board_info:
            test_data = getattr(board_status.board_info, 'test_data', {})
            if test_data:
                lines = ["[b]Captured:[/b]"]
                for key, value in test_data.items():
                    val_str = str(value)
                    if len(val_str) > 20:
                        val_str = val_str[:17] + "..."
                    lines.append(f"  {key}: {val_str}")
                captures_text = "\n".join(lines)
        self._captures_label.text = captures_text
    
    def _update_failure_display(self, cell):
        """Update the failure reason box."""
        if not self._failure_box or not self._failure_label:
            return
        
        if cell.failure_reason:
            self._failure_label.text = f"[b]Error:[/b] {cell.failure_reason}"
            self._failure_box.height = 50
            self._failure_box.opacity = 1
        else:
            self._failure_label.text = ""
            self._failure_box.height = 0
            self._failure_box.opacity = 0
    
    def _update_phase_cards(self, cell, board_status, board_times):
        """Update phase status cards with current state."""
        for phase_name, widgets in self._phase_widgets.items():
            dot_label = widgets['dot_label']
            timing_label = widgets['timing_label']
            dot_attr = widgets['dot_attr']
            status_attr = widgets['status_attr']
            timing_key = widgets['timing_key']
            
            # Get current dot value from cell
            dot_value = getattr(cell, dot_attr, "·")
            dot_label.text = dot_value
            
            # Color the dot based on status
            status_name = "IDLE"
            if board_status:
                status_enum = getattr(board_status, status_attr, None)
                if status_enum:
                    status_name = status_enum.name
            dot_label.color = self._get_phase_color(status_name)
            
            # Update timing text
            if timing_key in board_times:
                timing_label.text = f"{board_times[timing_key]:.1f}s"
                timing_label.color = [0.7, 0.7, 0.7, 1]
            else:
                timing_label.text = ""
    
    def _update_button_states(self):
        """Update button enabled/disabled states based on cycle running."""
        cycle_running = self._is_cycle_running()
        if self._clear_btn:
            self._clear_btn.disabled = cycle_running
            self._clear_btn.opacity = 0.5 if cycle_running else 1.0
        if self._rerun_btn:
            self._rerun_btn.disabled = cycle_running
            self._rerun_btn.opacity = 0.5 if cycle_running else 1.0
    
    def _update_detail_panel(self):
        """Update the detail panel based on selected phase."""
        if not self._detail_header or not self._detail_content:
            return
        
        if not self._selected_phase:
            self._detail_header.text = "Select a phase"
            self._detail_content.text = "Tap a phase on the left to see details"
            self._hide_detail_image()
            return
        
        phase_name = self._selected_phase
        cell = self.current_cell
        board_status = self._get_board_status(self.current_cell_id)
        position = self._cell_id_to_position(self.current_cell_id)
        board_times = self._get_board_times(position)
        
        if phase_name not in self.PHASE_INFO:
            return
        
        status_attr, timing_key = self.PHASE_INFO[phase_name]
        
        # Get status
        status_text = "Not started"
        status_name = "IDLE"
        if board_status:
            status_enum = getattr(board_status, status_attr, None)
            if status_enum:
                status_name = status_enum.name
                status_text = self._get_phase_status_text(status_enum)
            # Debug: log board_info availability
            if board_status.board_info:
                log.debug(f"[BoardDetail] board_info exists, test_data={board_status.board_info.test_data}")
            else:
                log.debug(f"[BoardDetail] board_info is None")
        
        # Get timing
        timing_text = "Not recorded"
        if timing_key in board_times:
            timing_text = f"{board_times[timing_key]:.2f} seconds"
        
        # Build detail content
        self._detail_header.text = f"{phase_name} Details"
        
        # Color codes for markup
        C_HEADER = '#88CCFF'  # Light blue for section headers
        C_KEY = '#FFCC66'     # Yellow/gold for keys
        C_OK = '#66FF66'      # Green for success
        C_FAIL = '#FF6666'    # Red for failure
        C_LOG = '#AAAAAA'     # Gray for log entries
        C_VAL = '#CCCCCC'     # Light gray for values
        
        # Color the status based on result
        if 'PASS' in status_name or 'COMPLETE' in status_name or 'IDENTIFIED' in status_name:
            status_color = C_OK
        elif 'FAIL' in status_name:
            status_color = C_FAIL
        else:
            status_color = C_VAL
        
        lines = []
        lines.append(f"[b]Status:[/b] [color={status_color}]{status_text}[/color]")
        lines.append(f"[b]Duration:[/b] [color={C_VAL}]{timing_text}[/color]")
        
        # Phase-specific details
        if phase_name == "Vision":
            self._build_vision_details(lines, cell, board_status)
        elif phase_name == "Contact":
            self._build_contact_details(lines, status_name, cell)
        elif phase_name == "Program":
            self._build_program_details(lines, status_name, cell)
        elif phase_name == "Provisioning":
            self._build_provisioning_details(lines, status_name, cell)
        elif phase_name == "Test":
            self._build_test_details(lines, status_name, cell)
        
        final_text = "\n".join(lines)
        log.info(f"[BoardDetail] Setting detail text ({len(lines)} lines): {final_text[:200]}...")
        self._detail_content.text = final_text
    
    def _build_vision_details(self, lines, cell, board_status):
        """Build Vision phase detail content."""
        C_HEADER = '#88CCFF'
        C_KEY = '#FFCC66'
        C_VAL = '#CCCCCC'
        C_LOG = '#AAAAAA'
        
        if cell.serial_number:
            lines.append(f"\n[color={C_HEADER}][b]QR Data[/b][/color]")
            lines.append(f"  [color={C_KEY}]Serial:[/color] [color={C_VAL}]{cell.serial_number}[/color]")
        if board_status and hasattr(board_status, 'board_info') and board_status.board_info:
            info = board_status.board_info
            if hasattr(info, 'serial') and info.serial:
                lines.append(f"  [color={C_KEY}]Board Serial:[/color] [color={C_VAL}]{info.serial}[/color]")
            if hasattr(info, 'model') and info.model:
                lines.append(f"  [color={C_KEY}]Model:[/color] [color={C_VAL}]{info.model}[/color]")
            
            # Show vision log if available
            if hasattr(info, 'vision_log') and info.vision_log:
                lines.append(f"\n[color={C_HEADER}][b]Scan Log[/b][/color]")
                for entry in info.vision_log[-10:]:  # Last 10 entries
                    lines.append(f"  [color={C_LOG}]{entry}[/color]")
            
            # Show QR image if available (image widget is created dynamically)
            if hasattr(info, 'qr_image') and info.qr_image:
                log.debug(f"[BoardDetail] Showing QR image: {len(info.qr_image)} bytes")
                self._show_qr_image(info.qr_image)
            else:
                self._hide_detail_image()
        else:
            self._hide_detail_image()
    
    def _build_contact_details(self, lines, status_name, cell):
        """Build Contact phase detail content."""
        self._hide_detail_image()
        C_HEADER = '#88CCFF'
        C_OK = '#66FF66'
        C_FAIL = '#FF6666'
        C_LOG = '#AAAAAA'
        
        lines.append(f"\n[color={C_HEADER}][b]Probe Test[/b][/color]")
        if status_name == "PASSED":
            lines.append(f"  [color={C_OK}]✓ Contact verified OK[/color]")
        elif status_name == "FAILED":
            lines.append(f"  [color={C_FAIL}]✗ Contact test failed[/color]")
            if cell.failure_reason:
                lines.append(f"  [color={C_FAIL}]Reason: {cell.failure_reason}[/color]")
        
        # Show probe log if available
        board_status = self._get_board_status(self.current_cell_id)
        if board_status and board_status.board_info:
            info = board_status.board_info
            if hasattr(info, 'probe_log') and info.probe_log:
                lines.append(f"\n[color={C_HEADER}][b]Probe Log[/b][/color]")
                for entry in info.probe_log[-10:]:
                    lines.append(f"  [color={C_LOG}]{entry}[/color]")
    
    def _build_program_details(self, lines, status_name, cell):
        """Build Program phase detail content."""
        self._hide_detail_image()
        board_status = self._get_board_status(self.current_cell_id)
        C_HEADER = '#88CCFF'
        C_KEY = '#FFCC66'
        C_VAL = '#CCCCCC'
        C_OK = '#66FF66'
        C_FAIL = '#FF6666'
        C_LOG = '#AAAAAA'
        
        lines.append(f"\n[color={C_HEADER}][b]Programming[/b][/color]")
        if status_name == "COMPLETED":
            lines.append(f"  [color={C_OK}]✓ Firmware flashed successfully[/color]")
        elif status_name == "IDENTIFIED":
            lines.append(f"  [color={C_OK}]✓ Device identified (no programming)[/color]")
        elif status_name == "FAILED":
            lines.append(f"  [color={C_FAIL}]✗ Programming failed[/color]")
            if cell.failure_reason:
                lines.append(f"  [color={C_FAIL}]Reason: {cell.failure_reason}[/color]")
        
        # Show device info if available
        if board_status and board_status.board_info:
            info = board_status.board_info
            if hasattr(info, 'device_id') and info.device_id:
                lines.append(f"\n[color={C_HEADER}][b]Device Info[/b][/color]")
                lines.append(f"  [color={C_KEY}]Device ID:[/color] [font=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf][color={C_VAL}]{info.device_id}[/color][/font]")
            if hasattr(info, 'firmware_version') and info.firmware_version:
                lines.append(f"  [color={C_KEY}]Firmware:[/color] [font=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf][color={C_VAL}]{info.firmware_version}[/color][/font]")
            
            # Show programming log if available
            if hasattr(info, 'program_log') and info.program_log:
                lines.append(f"\n[color={C_HEADER}][b]Programmer Output[/b][/color]")
                for entry in info.program_log[-15:]:  # Last 15 entries
                    # Truncate long lines
                    if len(entry) > 60:
                        entry = entry[:57] + "..."
                    # Use monospace font for log entries
                    lines.append(f"  [font=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf][color={C_LOG}]{entry}[/color][/font]")
    
    def _build_provisioning_details(self, lines, status_name, cell):
        """Build Provisioning phase detail content."""
        self._hide_detail_image()
        board_status = self._get_board_status(self.current_cell_id)
        C_HEADER = '#88CCFF'
        C_KEY = '#FFCC66'
        C_VAL = '#CCCCCC'
        C_OK = '#66FF66'
        C_FAIL = '#FF6666'
        C_LOG = '#AAAAAA'
        
        lines.append(f"\n[color={C_HEADER}][b]Provisioning[/b][/color]")
        if status_name in ("PASSED", "COMPLETED"):
            lines.append(f"  [color={C_OK}]✓ Device configured successfully[/color]")
        elif status_name == "FAILED":
            lines.append(f"  [color={C_FAIL}]✗ Provisioning failed[/color]")
            if cell.failure_reason:
                lines.append(f"  [color={C_FAIL}]Reason: {cell.failure_reason}[/color]")
        
        # Show captured variables
        log.debug(f"[BoardDetail] _build_provisioning_details: board_status={board_status}")
        if board_status and board_status.board_info:
            info = board_status.board_info
            log.debug(f"[BoardDetail] board_info.test_data={info.test_data}")
            log.debug(f"[BoardDetail] board_info.provision_log={getattr(info, 'provision_log', None)}")
            if hasattr(info, 'test_data') and info.test_data:
                lines.append(f"\n[color={C_HEADER}][b]Captured Variables[/b][/color]")
                for key, value in info.test_data.items():
                    val_str = str(value)
                    if len(val_str) > 50:
                        val_str = val_str[:47] + "..."
                    # Use monospace font for values
                    lines.append(f"  [color={C_KEY}]{key}:[/color] [font=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf][color={C_VAL}]{val_str}[/color][/font]")
            
            # Show provisioning log if available
            if hasattr(info, 'provision_log') and info.provision_log:
                lines.append(f"\n[color={C_HEADER}][b]Provisioning Log[/b][/color]")
                for entry in info.provision_log[-15:]:
                    if len(entry) > 60:
                        entry = entry[:57] + "..."
                    # Use monospace font for log entries, color based on content
                    if '✓' in entry or 'OK' in entry or 'PASS' in entry.upper():
                        lines.append(f"  [font=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf][color={C_OK}]{entry}[/color][/font]")
                    elif '✗' in entry or 'FAIL' in entry.upper() or 'ERROR' in entry.upper():
                        lines.append(f"  [font=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf][color={C_FAIL}]{entry}[/color][/font]")
                    else:
                        lines.append(f"  [font=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf][color={C_LOG}]{entry}[/color][/font]")
    
    def _build_test_details(self, lines, status_name, cell):
        """Build Test phase detail content."""
        self._hide_detail_image()
        board_status = self._get_board_status(self.current_cell_id)
        C_HEADER = '#88CCFF'
        C_KEY = '#FFCC66'
        C_VAL = '#CCCCCC'
        C_OK = '#66FF66'
        C_FAIL = '#FF6666'
        C_LOG = '#AAAAAA'
        
        lines.append(f"\n[color={C_HEADER}][b]Final Test[/b][/color]")
        if status_name == "PASSED" or status_name == "COMPLETED":
            lines.append(f"  [color={C_OK}]✓ All tests passed[/color]")
        elif status_name == "FAILED":
            lines.append(f"  [color={C_FAIL}]✗ Test failed[/color]")
            if cell.failure_reason:
                lines.append(f"  [color={C_FAIL}]Reason: {cell.failure_reason}[/color]")
        
        # Show test results if available
        if board_status and board_status.board_info:
            info = board_status.board_info
            
            # Show test data as results
            if hasattr(info, 'test_data') and info.test_data:
                lines.append(f"\n[color={C_HEADER}][b]Test Results[/b][/color]")
                for key, value in info.test_data.items():
                    val_str = str(value)
                    if len(val_str) > 50:
                        val_str = val_str[:47] + "..."
                    # Use monospace font for values
                    lines.append(f"  [color={C_KEY}]{key}:[/color] [font=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf][color={C_VAL}]{val_str}[/color][/font]")
            
            # Show test log if available  
            if hasattr(info, 'test_log') and info.test_log:
                lines.append(f"\n[color={C_HEADER}][b]Test Log[/b][/color]")
                for entry in info.test_log[-15:]:
                    if len(entry) > 60:
                        entry = entry[:57] + "..."
                    # Use monospace font for log entries, color based on content
                    if '✓' in entry or 'OK' in entry or 'PASS' in entry.upper():
                        lines.append(f"  [font=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf][color={C_OK}]{entry}[/color][/font]")
                    elif '✗' in entry or 'FAIL' in entry.upper() or 'ERROR' in entry.upper():
                        lines.append(f"  [font=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf][color={C_FAIL}]{entry}[/color][/font]")
                    else:
                        lines.append(f"  [font=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf][color={C_LOG}]{entry}[/color][/font]")
    
    def _show_qr_image(self, image_bytes):
        """Display QR image in detail panel from PNG bytes."""
        if not image_bytes or not self._detail_box:
            return
        try:
            from kivy.core.image import Image as CoreImage
            from io import BytesIO
            
            # Remove existing image if present
            self._hide_detail_image()
            
            data = BytesIO(image_bytes)
            img = CoreImage(data, ext='png')
            
            # Create image widget
            self._detail_image = Image(
                texture=img.texture,
                size_hint_y=None,
                height=200,
                allow_stretch=True,
                keep_ratio=True
            )
            self._detail_box.add_widget(self._detail_image)
        except Exception as e:
            log.debug(f"[BoardDetail] Error loading QR image: {e}")
    
    def _hide_detail_image(self):
        """Remove the detail image widget if present."""
        if self._detail_image and self._detail_box:
            try:
                self._detail_box.remove_widget(self._detail_image)
            except:
                pass
            self._detail_image = None
    
    def _on_popup_dismiss(self, instance):
        """Called when popup is dismissed."""
        if self._update_event:
            self._update_event.cancel()
            self._update_event = None
    
    def _on_clear_status(self, instance):
        """Clear the status for this board."""
        if self._is_cycle_running():
            log.warning("[BoardDetail] Cannot clear status while cycle is running")
            return
        
        if self.current_cell and self.current_cell_id is not None:
            # Reset cell visual state using centralized constants
            self.current_cell.vision_dot = DOT_PENDING if self.current_cell.vision_enabled else DOT_DISABLED
            self.current_cell.contact_dot = DOT_PENDING if self.current_cell.contact_enabled else DOT_DISABLED
            self.current_cell.program_dot = DOT_PENDING if self.current_cell.program_enabled else DOT_DISABLED
            self.current_cell.provision_dot = DOT_PENDING if self.current_cell.provision_enabled else DOT_DISABLED
            self.current_cell.test_dot = DOT_PENDING if self.current_cell.test_enabled else DOT_DISABLED
            self.current_cell.result_icon = ""
            self.current_cell.failure_reason = ""
            self.current_cell.serial_number = ""
            self.current_cell._stop_spinner()
            self.current_cell._stop_pulse()
            
            # Reset color to pending gray
            self.current_cell.cell_bg_color = [0.5, 0.5, 0.5, 1]
            
            # Clear board status in bot using correct position key
            if self.app.bot and hasattr(self.app.bot, 'board_statuses'):
                position = self._cell_id_to_position(self.current_cell_id)
                if position in self.app.bot.board_statuses:
                    del self.app.bot.board_statuses[position]
            
            log.info(f"[BoardDetail] Cleared status for cell {self.current_cell_id}")
        
        self.dismiss()
    
    def _on_rerun(self, instance):
        """Re-run the cycle for just this board."""
        if self._is_cycle_running():
            log.warning("[BoardDetail] Cannot re-run while cycle is running")
            return
        
        if self.current_cell_id is None:
            self.dismiss()
            return
        
        position = self._cell_id_to_position(self.current_cell_id)
        log.info(f"[BoardDetail] Re-run requested for cell {self.current_cell_id} at position {position}")
        
        # Clear current status first
        self._on_clear_status(None)
        
        # Schedule single board run
        import asyncio
        def do_rerun(dt):
            if self.app.bot:
                asyncio.ensure_future(self.app._run_single_board(position))
        
        Clock.schedule_once(do_rerun, 0.1)
    
    def _on_close(self, instance):
        """Close the popup."""
        self.dismiss()
    
    def dismiss(self):
        """Dismiss the popup."""
        if self._update_event:
            self._update_event.cancel()
            self._update_event = None
        
        if self.popup:
            self.popup.dismiss()
            self.popup = None
        
        self.current_cell = None
        self.current_cell_id = None
        self._phase_widgets = {}
        self._phase_cards = {}
        self._selected_phase = None
        self._status_badge = None
        self._failure_box = None
        self._failure_label = None
        self._clear_btn = None
        self._rerun_btn = None
        self._serial_label = None
        self._detail_header = None
        self._detail_content = None
        self._detail_image = None
        self._captures_label = None
