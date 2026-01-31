"""Panel Import Wizard - Test Harness

A multi-step wizard for importing KiCad/KiKit panel configurations.
Designed for 800x480 touchscreen.

Steps:
1. File Selection & Preview - Pick file, render, orient/flip
2. Grid Detection - Confirm/adjust detected grid parameters
3. Confirm & Apply - Review and apply to panel settings
"""

import os
import sys
from pathlib import Path

# Add parent to path for imports when running standalone
sys.path.insert(0, str(Path(__file__).parent))

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.textinput import TextInput
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.popup import Popup
from kivy.properties import ObjectProperty, StringProperty, NumericProperty, BooleanProperty
from kivy.core.window import Window
from kivy.metrics import dp

from panel_preview import PanelPreviewWidget, PanelData
from kikit_parser import parse_kikit_config, KiKitLayout
from kicad_parser import extract_board_outline, BoardOutline


# Set window size for testing (800x480 touchscreen)
Window.size = (800, 480)


class WizardStep(Screen):
    """Base class for wizard steps."""
    wizard = ObjectProperty(None)
    
    def on_enter(self):
        """Called when this step becomes active."""
        pass
    
    def validate(self) -> bool:
        """Validate this step before proceeding. Override in subclass."""
        return True


class FileSelectStep(WizardStep):
    """Step 1: File selection and orientation."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.selected_kikit_config = None
        self.selected_panel_pcb = None  # The panelized output from KiKit
        self.panel_data = None
        self._last_browse_dir = None  # Track last directory for file browser
        
        # Main layout
        main = BoxLayout(orientation='horizontal', padding=10, spacing=10)
        
        # Left side: File selection
        left = BoxLayout(orientation='vertical', size_hint_x=0.5, spacing=5)
        
        left.add_widget(Label(
            text='Step 1: Select Panel Files',
            size_hint_y=None, height=dp(30),
            font_size='16sp', bold=True
        ))
        
        # KiKit config selection
        left.add_widget(Label(
            text='KiKit Config (.json):',
            size_hint_y=None, height=dp(25),
            halign='left', text_size=(None, None)
        ))
        
        kikit_row = BoxLayout(size_hint_y=None, height=dp(35), spacing=5)
        self.kikit_label = Label(text='(none selected)', halign='left')
        self.kikit_label.bind(size=self.kikit_label.setter('text_size'))
        kikit_row.add_widget(self.kikit_label)
        kikit_btn = Button(text='Browse...', size_hint_x=None, width=dp(80))
        kikit_btn.bind(on_release=lambda x: self._show_file_picker('kikit'))
        kikit_row.add_widget(kikit_btn)
        left.add_widget(kikit_row)
        
        # Panel PCB selection (KiKit output - for preview)
        left.add_widget(Label(
            text='Panel PCB (.kicad_pcb):',
            size_hint_y=None, height=dp(25),
            halign='left'
        ))
        
        panel_row = BoxLayout(size_hint_y=None, height=dp(35), spacing=5)
        self.panel_label = Label(text='(none selected)', halign='left')
        self.panel_label.bind(size=self.panel_label.setter('text_size'))
        panel_row.add_widget(self.panel_label)
        panel_btn = Button(text='Browse...', size_hint_x=None, width=dp(80))
        panel_btn.bind(on_release=lambda x: self._show_file_picker('panel'))
        panel_row.add_widget(panel_btn)
        left.add_widget(panel_row)
        
        # Orientation controls
        left.add_widget(Label(
            text='Orientation:',
            size_hint_y=None, height=dp(25)
        ))
        
        orient_row = BoxLayout(size_hint_y=None, height=dp(45), spacing=10)
        
        ccw_btn = Button(text='CCW', size_hint_x=0.3)
        ccw_btn.bind(on_release=lambda x: self._rotate_ccw())
        orient_row.add_widget(ccw_btn)
        
        self.rotation_label = Label(text='0 deg', size_hint_x=0.2)
        orient_row.add_widget(self.rotation_label)
        
        cw_btn = Button(text='CW', size_hint_x=0.3)
        cw_btn.bind(on_release=lambda x: self._rotate_cw())
        orient_row.add_widget(cw_btn)
        
        left.add_widget(orient_row)
        
        # Side selection (radio button behavior)
        side_row = BoxLayout(size_hint_y=None, height=dp(45), spacing=10)
        self.top_btn = ToggleButton(text='Top Side', group='side', state='down', allow_no_selection=False)
        self.top_btn.bind(state=self._on_side_state)
        side_row.add_widget(self.top_btn)
        
        self.bottom_btn = ToggleButton(text='Bottom Side', group='side', allow_no_selection=False)
        self.bottom_btn.bind(state=self._on_side_state)
        side_row.add_widget(self.bottom_btn)
        left.add_widget(side_row)
        
        # Spacer
        left.add_widget(BoxLayout())
        
        main.add_widget(left)
        
        # Right side: Preview
        right = BoxLayout(orientation='vertical', size_hint_x=0.5)
        right.add_widget(Label(
            text='Preview:',
            size_hint_y=None, height=dp(25)
        ))
        
        self.preview = PanelPreviewWidget()
        right.add_widget(self.preview)
        
        main.add_widget(right)
        self.add_widget(main)
    
    def _show_file_picker(self, file_type: str):
        """Show touch-friendly file picker popup using app's file browser."""
        if file_type == 'kikit':
            filters = ['.json']
            title = 'Select KiKit Config'
        else:
            filters = ['.kicad_pcb']
            title = 'Select KiCad PCB'
        
        app = App.get_running_app()
        app.open_file_browser(
            title=title,
            filters=filters,
            start_path=self._last_browse_dir,
            callback=lambda path: self._on_file_selected(file_type, path)
        )
    
    def _on_file_selected(self, file_type: str, filepath: str):
        """Handle file selection."""
        if not filepath:
            return
        
        # Remember directory for next file picker
        self._last_browse_dir = str(Path(filepath).parent)
        
        filename = Path(filepath).name
        
        if file_type == 'kikit':
            self.selected_kikit_config = filepath
            self.kikit_label.text = filename
        elif file_type == 'panel':
            self.selected_panel_pcb = filepath
            self.panel_label.text = filename
        
        self._update_preview()
    
    def _update_preview(self):
        """Update the preview widget with current selections."""
        # Need at least the panel PCB for preview
        if not self.selected_panel_pcb:
            self.preview.panel_data = None
            self.preview.pcb_file_path = ''
            return
        
        try:
            # Set PCB file path for raster rendering (triggers PNG render)
            self.preview.pcb_file_path = self.selected_panel_pcb
            
            # Get grid layout from KiKit config if available
            cols, rows = 1, 1
            
            if self.selected_kikit_config:
                try:
                    layout = parse_kikit_config(self.selected_kikit_config)
                    cols = layout.cols
                    rows = layout.rows
                except Exception as e:
                    print(f"Warning: Could not parse KiKit config: {e}")
            
            # Detect actual board pitch from repeated footprint patterns
            col_width, row_height = 0.0, 0.0
            if cols > 1 or rows > 1:
                from kicad_parser import detect_board_pitch
                pitch = detect_board_pitch(self.selected_panel_pcb, cols, rows)
                if pitch:
                    col_width = pitch.x_pitch_mm  # X spacing = col_width
                    row_height = pitch.y_pitch_mm  # Y spacing = row_height
            
            # Create panel data with detected pitch
            self.panel_data = PanelData(
                cols=cols,
                rows=rows,
                col_width_mm=col_width,
                row_height_mm=row_height,
            )
            
            self.preview.panel_data = self.panel_data
            
        except Exception as e:
            print(f"Error loading panel data: {e}")
            import traceback
            traceback.print_exc()
            self.preview.panel_data = None
    
    def _rotate_cw(self):
        """Rotate preview clockwise."""
        self.preview.rotate_cw()
        self.rotation_label.text = f"{self.preview.rotation} deg"
    
    def _rotate_ccw(self):
        """Rotate preview counter-clockwise."""
        self.preview.rotate_ccw()
        self.rotation_label.text = f"{self.preview.rotation} deg"
    
    def _on_side_state(self, instance, state):
        """Handle side toggle state change."""
        if state == 'down':
            self.preview.flipped = (instance == self.bottom_btn)
    
    def validate(self) -> bool:
        """Must have either KiKit config or panel PCB selected."""
        return self.selected_kikit_config is not None or self.selected_panel_pcb is not None


class GridDetectStep(WizardStep):
    """Step 2: Grid detection and adjustment."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        main = BoxLayout(orientation='horizontal', padding=10, spacing=10)
        
        # Left side: Preview with board numbers
        left = BoxLayout(orientation='vertical', size_hint_x=0.45)
        left.add_widget(Label(
            text='Step 2: Confirm Grid Layout',
            size_hint_y=None, height=dp(30),
            font_size='16sp', bold=True
        ))
        
        self.preview = PanelPreviewWidget()
        self.preview.show_board_numbers = True  # Enable board numbering
        left.add_widget(self.preview)
        
        main.add_widget(left)
        
        # Right side: Detected values with edit capability
        right = BoxLayout(orientation='vertical', size_hint_x=0.55, spacing=5)
        
        right.add_widget(Label(
            text='Detected Layout (editable):',
            size_hint_y=None, height=dp(30)
        ))
        
        # Grid for parameters
        params = GridLayout(cols=2, spacing=5, size_hint_y=None, height=dp(200))
        params.bind(minimum_height=params.setter('height'))
        
        # Columns
        params.add_widget(Label(text='Columns:', halign='right'))
        self.cols_input = TextInput(
            text='5', multiline=False, input_filter='int',
            size_hint_y=None, height=dp(35)
        )
        self.cols_input.bind(text=self._on_param_change)
        params.add_widget(self.cols_input)
        
        # Rows
        params.add_widget(Label(text='Rows:', halign='right'))
        self.rows_input = TextInput(
            text='2', multiline=False, input_filter='int',
            size_hint_y=None, height=dp(35)
        )
        self.rows_input.bind(text=self._on_param_change)
        params.add_widget(self.rows_input)
        
        # Col Width (center-to-center X spacing) - ProgBot nomenclature
        params.add_widget(Label(text='Col Width (mm):', halign='right'))
        self.col_width_input = TextInput(
            text='48.0', multiline=False,
            size_hint_y=None, height=dp(35)
        )
        self.col_width_input.bind(text=self._on_param_change)
        params.add_widget(self.col_width_input)
        
        # Row Height (center-to-center Y spacing) - ProgBot nomenclature
        params.add_widget(Label(text='Row Height (mm):', halign='right'))
        self.row_height_input = TextInput(
            text='29.0', multiline=False,
            size_hint_y=None, height=dp(35)
        )
        self.row_height_input.bind(text=self._on_param_change)
        params.add_widget(self.row_height_input)
        
        right.add_widget(params)
        
        # Summary
        self.summary_label = Label(
            text='Total: 10 boards',
            size_hint_y=None, height=dp(50)
        )
        right.add_widget(self.summary_label)
        
        # Spacer
        right.add_widget(BoxLayout())
        
        main.add_widget(right)
        self.add_widget(main)
    
    def on_enter(self):
        """Load values from previous step, applying rotation transform."""
        if not self.wizard or not self.wizard.file_step.panel_data:
            return
            
        pd = self.wizard.file_step.panel_data
        rotation = self.wizard.file_step.preview.rotation
        flipped = self.wizard.file_step.preview.flipped
        
        # Copy textures from step 1's preview
        self.preview.copy_textures_from(self.wizard.file_step.preview)
        self.preview.rotation = rotation
        self.preview.flipped = flipped
        
        # Apply rotation to swap cols/rows and pitch as needed
        # Original panel has cols across X, rows across Y
        # At 90/270 rotation, X<->Y swap
        
        if rotation in (90, 270):
            # Rotated: swap columns<->rows and col_width<->row_height
            board_cols = pd.rows
            board_rows = pd.cols
            col_width = pd.row_height_mm  # What was Y pitch is now col_width
            row_height = pd.col_width_mm  # What was X pitch is now row_height
        else:
            # No rotation or 180: keep original orientation
            board_cols = pd.cols
            board_rows = pd.rows
            col_width = pd.col_width_mm
            row_height = pd.row_height_mm
        
        self.cols_input.text = str(board_cols)
        self.rows_input.text = str(board_rows)
        self.col_width_input.text = f"{col_width:.1f}" if col_width > 0 else ""
        self.row_height_input.text = f"{row_height:.1f}" if row_height > 0 else ""
        
        self._update_preview()
    
    def _on_param_change(self, instance, value):
        """Handle parameter changes."""
        self._update_preview()
    
    def _update_preview(self):
        """Update preview with current values."""
        try:
            board_cols = int(self.cols_input.text or 1)
            board_rows = int(self.rows_input.text or 1)
            col_width = float(self.col_width_input.text or 0)
            row_height = float(self.row_height_input.text or 0)
            
            pd = PanelData(
                cols=board_cols,
                rows=board_rows,
                col_width_mm=col_width,
                row_height_mm=row_height,
            )
            
            self.preview.panel_data = pd
            
            # Update summary
            total = board_cols * board_rows
            self.summary_label.text = f"Total: {total} boards"
            
        except (ValueError, TypeError):
            pass
    
    def get_values(self) -> dict:
        """Get current parameter values in ProgBot .panel format."""
        return {
            'board_cols': int(self.cols_input.text or 1),
            'board_rows': int(self.rows_input.text or 1),
            'col_width': float(self.col_width_input.text or 0),
            'row_height': float(self.row_height_input.text or 0),
            'rotation': self.preview.rotation,
            'flipped': self.preview.flipped,
        }


class ConfirmStep(WizardStep):
    """Step 3: Confirm and save panel file."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        main = BoxLayout(orientation='vertical', padding=20, spacing=10)
        
        main.add_widget(Label(
            text='Step 3: Save Panel Configuration',
            size_hint_y=None, height=dp(30),
            font_size='16sp', bold=True
        ))
        
        # Panel name input
        name_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=10)
        name_row.add_widget(Label(
            text='Panel Name:',
            size_hint_x=0.3,
            halign='right'
        ))
        self.name_input = TextInput(
            text='',
            hint_text='Enter a name for this panel',
            multiline=False,
            size_hint_x=0.7
        )
        name_row.add_widget(self.name_input)
        main.add_widget(name_row)
        
        # Summary display
        self.summary = Label(
            text='(loading...)',
            halign='left',
            valign='top',
            font_size='14sp',
            size_hint_y=None,
            height=dp(200)
        )
        self.summary.bind(size=self.summary.setter('text_size'))
        main.add_widget(self.summary)
        
        # Info about what will happen
        info = Label(
            text='Click "Save" to create the .panel file.',
            size_hint_y=None, height=dp(40),
            color=(0.7, 0.7, 0.7, 1)
        )
        main.add_widget(info)
        
        self.add_widget(main)
    
    def on_enter(self):
        """Update summary with final values."""
        if self.wizard:
            values = self.wizard.grid_step.get_values()
            
            side = 'Bottom' if values['flipped'] else 'Top'
            
            # Pre-populate panel name from PCB filename if empty
            if not self.name_input.text and self.wizard.file_step.selected_panel_pcb:
                from pathlib import Path
                pcb_name = Path(self.wizard.file_step.selected_panel_pcb).stem
                # Remove common suffixes like _panelized, -panel, etc.
                for suffix in ['_panelized', '-panelized', '_panel', '-panel']:
                    if pcb_name.lower().endswith(suffix):
                        pcb_name = pcb_name[:-len(suffix)]
                        break
                self.name_input.text = pcb_name
            
            self.summary.text = f"""Panel Layout Configuration:

    Grid:         {values['board_cols']} columns x {values['board_rows']} rows
    Total Boards: {values['board_cols'] * values['board_rows']}
    
    Col Width:    {values['col_width']:.1f} mm (center to center)
    Row Height:   {values['row_height']:.1f} mm (center to center)
    
    Rotation:     {values['rotation']}°
    Side:         {side}
"""
    
    def get_panel_name(self) -> str:
        """Get the panel name entered by the user."""
        return self.name_input.text.strip()
    
    def validate(self) -> bool:
        """Validate that a panel name is entered."""
        if not self.name_input.text.strip():
            self.name_input.hint_text = 'Please enter a panel name!'
            self.name_input.background_color = (1, 0.3, 0.3, 1)
            return False
        self.name_input.background_color = (1, 1, 1, 1)
        return True


class PanelImportWizard(BoxLayout):
    """Main wizard container with navigation."""
    
    def __init__(self, on_complete=None, on_cancel=None, **kwargs):
        super().__init__(orientation='vertical', **kwargs)
        self.on_complete_callback = on_complete
        self.on_cancel_callback = on_cancel
        
        # Screen manager for steps
        self.sm = ScreenManager(transition=SlideTransition())
        
        # Create steps
        self.file_step = FileSelectStep(name='file')
        self.file_step.wizard = self
        self.sm.add_widget(self.file_step)
        
        self.grid_step = GridDetectStep(name='grid')
        self.grid_step.wizard = self
        self.sm.add_widget(self.grid_step)
        
        self.confirm_step = ConfirmStep(name='confirm')
        self.confirm_step.wizard = self
        self.sm.add_widget(self.confirm_step)
        
        self.add_widget(self.sm)
        
        # Navigation bar
        nav = BoxLayout(size_hint_y=None, height=dp(50), padding=10, spacing=10)
        
        self.cancel_btn = Button(text='Cancel', size_hint_x=0.25)
        self.cancel_btn.bind(on_release=self._on_cancel)
        nav.add_widget(self.cancel_btn)
        
        nav.add_widget(BoxLayout())  # Spacer
        
        self.back_btn = Button(text='< Back', size_hint_x=0.25)
        self.back_btn.bind(on_release=self._on_back)
        # Back button starts hidden (not added to layout)
        self.back_btn_placeholder = BoxLayout(size_hint_x=0.25)  # Spacer to keep layout stable
        nav.add_widget(self.back_btn_placeholder)
        
        self.next_btn = Button(text='Next >', size_hint_x=0.25)
        self.next_btn.bind(on_release=self._on_next)
        nav.add_widget(self.next_btn)
        
        self.add_widget(nav)
        
        self.steps = ['file', 'grid', 'confirm']
        self.current_step = 0
    
    def _update_nav(self):
        """Update navigation buttons based on current step."""
        # Swap back button / placeholder based on step
        nav = self.back_btn_placeholder.parent if self.back_btn_placeholder.parent else self.back_btn.parent
        if self.current_step == 0:
            # Show placeholder, hide back button
            if self.back_btn.parent:
                idx = nav.children.index(self.back_btn)
                nav.remove_widget(self.back_btn)
                nav.add_widget(self.back_btn_placeholder, index=idx)
        else:
            # Show back button, hide placeholder
            if self.back_btn_placeholder.parent:
                idx = nav.children.index(self.back_btn_placeholder)
                nav.remove_widget(self.back_btn_placeholder)
                nav.add_widget(self.back_btn, index=idx)
        
        if self.current_step == len(self.steps) - 1:
            self.next_btn.text = 'Save'
        else:
            self.next_btn.text = 'Next >'
    
    def _on_cancel(self, instance):
        """Handle cancel."""
        if self.on_cancel_callback:
            self.on_cancel_callback()
    
    def _on_back(self, instance):
        """Go to previous step."""
        if self.current_step > 0:
            self.current_step -= 1
            self.sm.transition.direction = 'right'
            self.sm.current = self.steps[self.current_step]
            self._update_nav()
    
    def _on_next(self, instance):
        """Go to next step or complete."""
        current_screen = self.sm.current_screen
        
        # Validate current step
        if hasattr(current_screen, 'validate') and not current_screen.validate():
            # Could show error message
            return
        
        if self.current_step < len(self.steps) - 1:
            self.current_step += 1
            self.sm.transition.direction = 'left'
            self.sm.current = self.steps[self.current_step]
            self._update_nav()
        else:
            # Complete - return values with panel name
            if self.on_complete_callback:
                values = self.grid_step.get_values()
                values['panel_name'] = self.confirm_step.get_panel_name()
                self.on_complete_callback(values)


class TestApp(App):
    """Test application for the panel import wizard."""
    
    def build(self):
        self.title = 'Panel Import Wizard Test'
        
        wizard = PanelImportWizard(
            on_complete=self._on_complete,
            on_cancel=self._on_cancel
        )
        return wizard
    
    def _on_complete(self, values):
        """Handle wizard completion."""
        print("\n" + "=" * 50)
        print("WIZARD COMPLETE - Values to apply:")
        print("=" * 50)
        for key, value in values.items():
            print(f"  {key}: {value}")
        print("=" * 50 + "\n")
        
        # In real integration, would pass these to panel setup dialog
        App.get_running_app().stop()
    
    def _on_cancel(self):
        """Handle cancel."""
        print("Wizard cancelled")
        App.get_running_app().stop()


if __name__ == '__main__':
    TestApp().run()
