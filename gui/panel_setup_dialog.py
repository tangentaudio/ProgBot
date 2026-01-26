"""Panel Setup dialog for setting board origin, probe offset, and QR code offset.

This module provides an interactive dialog for configuring panel parameters,
including XY/Z jogging, probing, setting board origin, probe-to-board offset,
and QR code offset with camera preview.
"""
import asyncio
import cv2
import numpy as np
from kivy.clock import Clock
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.graphics.texture import Texture

# Load the panel setup KV file
Builder.load_file('panel_setup.kv')


def debug_log(msg):
    """Write debug message to /tmp/debug.txt"""
    try:
        with open('/tmp/debug.txt', 'a') as f:
            import datetime
            timestamp = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
            f.write(f"[{timestamp}] {msg}\n")
            f.flush()
    except Exception:
        pass


class PanelSetupController:
    """Controller for the panel setup dialog.
    
    This class manages the panel setup popup and all related operations including
    jogging, homing, probing, and setting panel configuration values.
    
    Attributes:
        app: Reference to the main Kivy App instance
        popup: The PanelSetupPopup widget instance
        xy_step: Current XY jog step size in mm (Origins tab)
        z_step: Current Z jog step size in mm (Origins tab)
        probe_z: Z position after last probe (None if not probed)
        vision_xy_step: Current XY jog step size in mm (Vision tab)
        vision_preview_active: Whether camera preview is active
        vision_preview_event: Scheduled event for camera preview updates
    """
    
    def __init__(self, app):
        """Initialize the calibration controller.
        
        Args:
            app: The main Kivy App instance (must have bot, panel_settings, root)
        """
        self.app = app
        self.popup = None
        self.xy_step = 5.0
        self.z_step = 1.0
        self.probe_z = None
        # Vision tab state
        self.vision_xy_step = 5.0
        self.vision_preview_active = False
        self.vision_preview_event = None
        self._black_texture = None
        self.vision_board_col = 0
        self.vision_board_row = 0
        
        # Edit buffer for deferred save/cancel
        self._edit_buffer = {}
        self._original_values = {}
        self._is_dirty = False
    
    @property
    def bot(self):
        """Access the ProgBot instance from the app."""
        return self.app.bot
    
    @property
    def panel_settings(self):
        """Access panel settings from the app."""
        return self.app.panel_settings
    
    def get_settings(self):
        """Get the settings module's get_settings function result."""
        from settings import get_settings
        return get_settings()
    
    def open(self):
        """Open the calibration dialog."""
        debug_log("[PanelSetup] Opening dialog")
        
        if not self.bot or not self.bot.motion:
            debug_log("[PanelSetup] Bot or motion controller not initialized")
            return
        
        # Create popup if needed
        if not self.popup:
            self.popup = Factory.PanelSetupPopup()
        
        # Initialize panel setup state
        self.xy_step = 5.0
        self.z_step = 1.0
        self.probe_z = None
        
        # Read step values from UI toggle buttons (preserves user's previous selection)
        self._sync_step_selectors_from_ui()
        
        # Initialize edit buffer from current panel settings
        self._init_edit_buffer()
        
        # Sync buffer to dialog widgets
        self._sync_buffer_to_dialog()
        
        # Update panel filename in title bar
        self._update_panel_filename()
        
        # Update current values display
        self._update_origin_label()
        self._update_probe_offset_label()
        self._update_qr_offset_label()
        
        # Initialize Vision tab preview (inactive)
        self._init_vision_preview()
        
        # Query initial position
        self._refresh_position()
        
        # Update save button state
        self._update_save_button()
        
        # Open popup
        self.popup.open()
        
        # Check if Vision tab is already selected and start camera if so
        # (on_state won't fire if tab was already selected from previous session)
        Clock.schedule_once(self._check_vision_tab_selected, 0.1)
    
    def _init_edit_buffer(self):
        """Initialize the edit buffer with current panel settings."""
        import copy
        ps = self.panel_settings
        
        if ps:
            # Copy all panel settings to buffer
            self._edit_buffer = copy.deepcopy(ps.get_all())
        else:
            self._edit_buffer = {}
        
        # Keep a copy of original values for dirty detection
        self._original_values = copy.deepcopy(self._edit_buffer)
        self._is_dirty = False
        
        debug_log("[PanelSetup] Edit buffer initialized")
    
    def _set_buffer_value(self, key, value):
        """Set a value in the edit buffer and mark dirty if changed."""
        old_value = self._edit_buffer.get(key)
        if old_value != value:
            self._edit_buffer[key] = value
            self._check_dirty()
            debug_log(f"[PanelSetup] Buffer: {key} = {value}")
    
    def _set_buffer_nested(self, *keys, value):
        """Set a nested value in the edit buffer (e.g., programmer.steps.identify)."""
        if len(keys) < 2:
            self._set_buffer_value(keys[0], value)
            return
        
        # Navigate to parent, creating dicts as needed
        current = self._edit_buffer
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        
        old_value = current.get(keys[-1])
        if old_value != value:
            current[keys[-1]] = value
            self._check_dirty()
            debug_log(f"[PanelSetup] Buffer: {'.'.join(keys)} = {value}")
    
    def _get_buffer_value(self, key, default=None):
        """Get a value from the edit buffer."""
        return self._edit_buffer.get(key, default)
    
    def _get_buffer_nested(self, *keys, default=None):
        """Get a nested value from the edit buffer."""
        current = self._edit_buffer
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current
    
    def _check_dirty(self):
        """Check if buffer differs from original values and update dirty state."""
        import json
        # Compare JSON representations for deep equality
        is_dirty = json.dumps(self._edit_buffer, sort_keys=True) != json.dumps(self._original_values, sort_keys=True)
        if is_dirty != self._is_dirty:
            self._is_dirty = is_dirty
            # Schedule UI update on main thread (may be called from async context)
            Clock.schedule_once(lambda dt: self._update_save_button(), 0)
    
    def _update_save_button(self):
        """Update save button appearance based on dirty state."""
        if not self.popup:
            return
        if save_btn := self.popup.ids.get('ps_save_btn'):
            if self._is_dirty:
                save_btn.disabled = False
                save_btn.background_color = (0.2, 0.6, 0.3, 1)  # Green when dirty
                save_btn.text = 'Save *'
            else:
                save_btn.disabled = True
                save_btn.background_color = (0.3, 0.3, 0.3, 1)  # Gray when clean
                save_btn.text = 'Save'
    
    def save_panel(self):
        """Save the edit buffer to panel settings and update the system."""
        if not self._is_dirty:
            debug_log("[PanelSetup] No changes to save")
            return
        
        ps = self.panel_settings
        if not ps:
            debug_log("[PanelSetup] No panel settings to save to")
            return
        
        # Update panel settings with buffer values
        for key, value in self._edit_buffer.items():
            ps.data[key] = value
        
        # Save to file
        ps._save_settings()
        
        # Apply settings to running system
        self._apply_settings_to_system()
        
        # Update original values and clear dirty state
        import copy
        self._original_values = copy.deepcopy(self._edit_buffer)
        self._is_dirty = False
        self._update_save_button()
        
        debug_log(f"[PanelSetup] Panel saved to {ps.panel_file}")
        print(f"[PanelSetup] Panel saved to {ps.panel_file}")
    
    def _apply_settings_to_system(self):
        """Apply buffered settings to the running system (bot.config, UI, etc.)."""
        buf = self._edit_buffer
        
        # Update bot config with grid/origin settings
        if self.bot and self.bot.config:
            config = self.bot.config
            
            # Grid parameters
            if 'board_cols' in buf:
                config.board_num_cols = int(buf['board_cols'])
            if 'board_rows' in buf:
                config.board_num_rows = int(buf['board_rows'])
            if 'col_width' in buf:
                config.board_col_width = float(buf['col_width'])
            if 'row_height' in buf:
                config.board_row_height = float(buf['row_height'])
            
            # Origins
            if 'board_x' in buf:
                config.board_x = float(buf['board_x'])
            if 'board_y' in buf:
                config.board_y = float(buf['board_y'])
            if 'probe_plane' in buf:
                config.probe_plane_to_board = float(buf['probe_plane'])
            
            # Vision/QR
            if 'use_camera' in buf:
                config.use_camera = bool(buf['use_camera'])
            if 'qr_offset_x' in buf:
                config.qr_offset_x = float(buf['qr_offset_x'])
            if 'qr_offset_y' in buf:
                config.qr_offset_y = float(buf['qr_offset_y'])
        
        # Recreate programmer with new settings
        if self.bot and 'programmer' in buf:
            self.bot.programmer = self.bot._create_programmer()
        
        # Update main UI grid if dimensions changed
        if hasattr(self.app, 'update_grid_from_settings'):
            self.app.update_grid_from_settings()
        
        debug_log("[PanelSetup] Applied settings to system")
    
    def cancel(self):
        """Cancel editing and discard changes."""
        if self._is_dirty:
            debug_log("[PanelSetup] Discarding unsaved changes")
        
        # Stop camera preview if active
        self._stop_vision_preview()
        
        # Clear buffer
        self._edit_buffer = {}
        self._original_values = {}
        self._is_dirty = False
        
        # Close popup
        if self.popup:
            self.popup.dismiss()
    
    def close(self):
        """Close the dialog, prompting if there are unsaved changes."""
        if self._is_dirty:
            # Show confirmation dialog
            self._show_unsaved_changes_dialog()
        else:
            self._do_close()
    
    def _show_unsaved_changes_dialog(self):
        """Show dialog asking about unsaved changes."""
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        
        content = BoxLayout(orientation='vertical', spacing=15, padding=20)
        content.add_widget(Label(
            text='You have unsaved changes.\nWhat would you like to do?',
            halign='center',
            valign='center',
            font_size='18sp',
            text_size=(350, None),
        ))
        
        btn_layout = BoxLayout(size_hint_y=None, height=60, spacing=15)
        
        save_btn = Button(text='Save & Close', background_color=(0.2, 0.6, 0.3, 1), font_size='16sp')
        discard_btn = Button(text='Discard', background_color=(0.6, 0.3, 0.2, 1), font_size='16sp')
        cancel_btn = Button(text='Cancel', font_size='16sp')
        
        btn_layout.add_widget(save_btn)
        btn_layout.add_widget(discard_btn)
        btn_layout.add_widget(cancel_btn)
        content.add_widget(btn_layout)
        
        dialog = Popup(
            title='Unsaved Changes',
            content=content,
            size_hint=(0.6, 0.4),
            auto_dismiss=False,
        )
        
        def on_save(instance):
            dialog.dismiss()
            self.save_panel()
            self._do_close()
        
        def on_discard(instance):
            dialog.dismiss()
            self._do_close()
        
        def on_cancel(instance):
            dialog.dismiss()
        
        save_btn.bind(on_press=on_save)
        discard_btn.bind(on_press=on_discard)
        cancel_btn.bind(on_press=on_cancel)
        
        dialog.open()
    
    def _do_close(self):
        """Actually close the dialog, moving to safe Z first if needed."""
        async def do_close():
            debug_log("[PanelSetup] Closing dialog...")
            
            # Stop vision preview if active
            self._stop_vision_preview()
            
            try:
                # Check current Z position and move to safe height if needed
                pos = await self.bot.motion.get_position()
                if pos['z'] < -0.5:  # If Z is more than 0.5mm below safe height
                    debug_log(f"[PanelSetup] Z at {pos['z']:.2f}, moving to safe Z before closing...")
                    await self.bot.motion.rapid_z_abs(0.0)
                    await self.bot.motion.send_gcode_wait_ok("M400")
                    debug_log("[PanelSetup] Safe Z reached")
            except Exception as e:
                debug_log(f"[PanelSetup] Error checking/moving Z: {e}")
            
            # Clear buffer
            self._edit_buffer = {}
            self._original_values = {}
            self._is_dirty = False
            
            # Dismiss dialog
            def dismiss(dt):
                if self.popup:
                    self.popup.dismiss()
            Clock.schedule_once(dismiss, 0)
            debug_log("[PanelSetup] Dialog closed")
        
        asyncio.ensure_future(do_close())
    
    def _update_origin_label(self):
        """Update the origin labels with current buffer values."""
        if not self.popup:
            return
        x = float(self._get_buffer_value('board_x', 0))
        y = float(self._get_buffer_value('board_y', 0))
        if x_label := self.popup.ids.get('ps_origin_x_label'):
            x_label.text = f'Origin X: {x:.2f}'
        if y_label := self.popup.ids.get('ps_origin_y_label'):
            y_label.text = f'Origin Y: {y:.2f}'
    
    def _update_probe_offset_label(self):
        """Update the probe offset label with current buffer values."""
        if not self.popup:
            return
        offset_label = self.popup.ids.get('ps_probe_offset_label')
        if offset_label:
            offset = float(self._get_buffer_value('probe_plane', 0))
            offset_label.text = f'Z Offset: {offset:.2f}'
    
    def _sync_buffer_to_dialog(self):
        """Sync edit buffer values to dialog input widgets."""
        if not self.popup:
            return
        
        buf = self._edit_buffer
        
        # Parameters tab
        if cols_spinner := self.popup.ids.get('ps_board_cols_spinner'):
            cols_spinner.text = str(buf.get('board_cols', '2'))
        if rows_spinner := self.popup.ids.get('ps_board_rows_spinner'):
            rows_spinner.text = str(buf.get('board_rows', '5'))
        if col_width := self.popup.ids.get('ps_col_width_input'):
            col_width.text = str(buf.get('col_width', '48.0'))
        if row_height := self.popup.ids.get('ps_row_height_input'):
            row_height.text = str(buf.get('row_height', '29.0'))
        
        # Origin tab
        if board_x := self.popup.ids.get('ps_board_x_input'):
            board_x.text = str(buf.get('board_x', '110.2'))
        if board_y := self.popup.ids.get('ps_board_y_input'):
            board_y.text = str(buf.get('board_y', '121.0'))
        if probe_plane := self.popup.ids.get('ps_probe_plane_input'):
            probe_plane.text = str(buf.get('probe_plane', '4.0'))
        
        # Vision tab
        if qr_offset_x := self.popup.ids.get('ps_qr_offset_x_input'):
            qr_offset_x.text = str(buf.get('qr_offset_x', '0.0'))
        if qr_offset_y := self.popup.ids.get('ps_qr_offset_y_input'):
            qr_offset_y.text = str(buf.get('qr_offset_y', '0.0'))
        if use_camera := self.popup.ids.get('ps_use_camera_checkbox'):
            use_camera.state = 'down' if buf.get('use_camera', True) else 'normal'
        
        # Programming tab - build dynamic UI
        self._build_programmer_ui()
        
        debug_log("[PanelSetup] Synced buffer to dialog")
    
    def _update_panel_filename(self):
        """Update the panel filename display in the title bar."""
        if not self.popup:
            return
        
        import os
        if filename_label := self.popup.ids.get('ps_panel_filename'):
            if self.panel_settings and self.panel_settings.panel_file:
                # Show just the filename, not full path
                basename = os.path.basename(self.panel_settings.panel_file)
                filename_label.text = f"[ {basename} ]"
            else:
                filename_label.text = "[ unsaved ]"
    
    def _build_programmer_ui(self):
        """Build the dynamic programmer UI based on current programmer type."""
        if not self.popup:
            return
        
        from programmers import get_available_programmers, get_programmer_class
        
        # Populate programmer type spinner
        if type_spinner := self.popup.ids.get('ps_programmer_type_spinner'):
            available = get_available_programmers()
            type_spinner.values = list(available.values())
            
            # Get current programmer type from buffer
            prog_config = self._get_buffer_value('programmer', {})
            current_type = prog_config.get('type', 'nordic_nrf')
            
            # Set spinner to current type's display name
            if current_type in available:
                type_spinner.text = available[current_type]
        
        # Build steps and firmware UI for current programmer
        self._rebuild_programmer_steps()
        self._rebuild_programmer_firmware()
    
    def _rebuild_programmer_steps(self):
        """Rebuild the programming steps toggle buttons."""
        if not self.popup:
            return
        
        steps_container = self.popup.ids.get('ps_steps_container')
        if not steps_container:
            return
        
        from kivy.uix.togglebutton import ToggleButton
        from programmers import get_programmer_class
        
        # Clear existing widgets
        steps_container.clear_widgets()
        
        # Get current programmer config from buffer
        prog_config = self._get_buffer_value('programmer', {})
        current_type = prog_config.get('type', 'nordic_nrf')
        enabled_steps = prog_config.get('steps', {})
        
        # Get steps from programmer class
        try:
            programmer_class = get_programmer_class(current_type)
            steps = programmer_class.get_steps()
        except KeyError:
            steps = []
        
        # Create toggle button for each step
        for step in steps:
            step_id = step['id']
            label = step['label']
            default = step.get('default', False)
            description = step.get('description', '')
            
            # Check if enabled (from buffer or default)
            is_enabled = enabled_steps.get(step_id, default)
            
            btn = ToggleButton(
                text=label,
                state='down' if is_enabled else 'normal',
                size_hint_y=None,
                height=40,
            )
            # Store step_id for callback
            btn.step_id = step_id
            btn.bind(state=self._on_step_toggle)
            
            steps_container.add_widget(btn)
        
        debug_log(f"[PanelSetup] Built {len(steps)} step toggles for {current_type}")
    
    def _on_step_toggle(self, instance, state):
        """Handle step toggle button state change."""
        step_id = instance.step_id
        enabled = state == 'down'
        
        # Update buffer
        self._set_buffer_nested('programmer', 'steps', step_id, value=enabled)
        
        debug_log(f"[PanelSetup] Step {step_id} = {enabled}")
    
    def _rebuild_programmer_firmware(self):
        """Rebuild the firmware file input widgets."""
        if not self.popup:
            return
        
        firmware_container = self.popup.ids.get('ps_firmware_container')
        if not firmware_container:
            return
        
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.textinput import TextInput
        from kivy.uix.button import Button
        from programmers import get_programmer_class
        
        # Clear existing widgets
        firmware_container.clear_widgets()
        
        # Get current programmer config from buffer
        prog_config = self._get_buffer_value('programmer', {})
        current_type = prog_config.get('type', 'nordic_nrf')
        firmware_paths = prog_config.get('firmware', {})
        
        # Get firmware slots from programmer class
        try:
            programmer_class = get_programmer_class(current_type)
            slots = programmer_class.get_firmware_slots()
        except KeyError:
            slots = []
        
        # Create row for each firmware slot
        for slot in slots:
            slot_id = slot['id']
            label_text = slot['label']
            default_path = slot.get('default', '')
            file_filter = slot.get('filter', '*.hex')
            
            # Get current path (from buffer or default)
            current_path = firmware_paths.get(slot_id, default_path)
            
            # Row container
            row = BoxLayout(
                orientation='horizontal',
                size_hint_y=None,
                height=40,
                spacing=5,
            )
            
            # Label
            lbl = Label(
                text=f"{label_text}:",
                size_hint_x=0.3,
                halign='right',
                valign='center',
            )
            lbl.bind(size=lbl.setter('text_size'))
            row.add_widget(lbl)
            
            # Text input
            txt = TextInput(
                text=current_path,
                multiline=False,
                font_size='13sp',
                size_hint_x=0.6,
            )
            txt.slot_id = slot_id
            txt.bind(on_text_validate=self._on_firmware_text_change)
            txt.bind(focus=self._on_firmware_focus_change)
            row.add_widget(txt)
            
            # Browse button
            btn = Button(
                text='...',
                size_hint_x=None,
                width=40,
            )
            btn.slot_id = slot_id
            btn.file_filter = file_filter
            btn.text_input = txt
            btn.bind(on_press=self._on_firmware_browse)
            row.add_widget(btn)
            
            firmware_container.add_widget(row)
        
        debug_log(f"[PanelSetup] Built {len(slots)} firmware inputs for {current_type}")
    
    def _on_firmware_text_change(self, instance):
        """Handle firmware path text input validation (Enter key)."""
        self._save_firmware_path(instance.slot_id, instance.text)
    
    def _on_firmware_focus_change(self, instance, focused):
        """Handle firmware path text input focus change (save on blur)."""
        if not focused:
            self._save_firmware_path(instance.slot_id, instance.text)
    
    def _save_firmware_path(self, slot_id, path):
        """Save firmware path to buffer."""
        self._set_buffer_nested('programmer', 'firmware', slot_id, value=path)
        debug_log(f"[PanelSetup] Firmware {slot_id} = {path}")
    
    def _on_firmware_browse(self, instance):
        """Handle firmware browse button press."""
        slot_id = instance.slot_id
        file_filter = instance.file_filter
        text_input = instance.text_input
        
        self._open_firmware_chooser(slot_id, file_filter, text_input)
    
    def _open_firmware_chooser(self, slot_id, file_filter, text_input):
        """Open file chooser for firmware selection."""
        import os
        from kivy.uix.filechooser import FileChooserListView
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.button import Button
        
        layout = BoxLayout(orientation='vertical')
        chooser = FileChooserListView(
            path=os.path.expanduser('~'),
            filters=[file_filter]
        )
        layout.add_widget(chooser)
        
        button_layout = BoxLayout(size_hint_y=0.1, spacing=5)
        select_btn = Button(text='Select')
        cancel_btn = Button(text='Cancel')
        button_layout.add_widget(select_btn)
        button_layout.add_widget(cancel_btn)
        layout.add_widget(button_layout)
        
        popup = Popup(title=f'Select Firmware File', content=layout, size_hint=(0.8, 0.8))
        
        def on_select(btn_instance):
            if chooser.selection:
                path = chooser.selection[0]
                text_input.text = path
                self._save_firmware_path(slot_id, path)
                popup.dismiss()
        
        def on_cancel(btn_instance):
            popup.dismiss()
        
        select_btn.bind(on_press=on_select)
        cancel_btn.bind(on_press=on_cancel)
        popup.open()
    
    def on_programmer_type_change(self, display_name):
        """Handle programmer type spinner change."""
        from programmers import get_available_programmers
        
        # Find type_id from display name
        available = get_available_programmers()
        type_id = None
        for tid, name in available.items():
            if name == display_name:
                type_id = tid
                break
        
        if type_id:
            # Get current programmer config from buffer
            prog_config = self._get_buffer_value('programmer', {})
            prog_config['type'] = type_id
            # Reset steps and firmware for new type
            prog_config['steps'] = {}
            prog_config['firmware'] = {}
            self._set_buffer_value('programmer', prog_config)
            
            # Rebuild the UI for new programmer type
            self._rebuild_programmer_steps()
            self._rebuild_programmer_firmware()
        
        debug_log(f"[PanelSetup] Programmer type changed to {type_id}")

    def _refresh_position(self):
        """Query current position and update display."""
        async def do_refresh():
            try:
                pos = await self.bot.motion.get_position()
                # Check if at safe Z (within 0.5mm of Z=0)
                at_safe_z = pos['z'] >= -0.5
                # Update labels on main thread
                def update_labels(dt, pos=pos, at_safe_z=at_safe_z):
                    if not self.popup:
                        return
                    popup = self.popup
                    if x_label := popup.ids.get('ps_pos_x'):
                        x_label.text = f"X: {pos['x']:.3f}"
                    if y_label := popup.ids.get('ps_pos_y'):
                        y_label.text = f"Y: {pos['y']:.3f}"
                    if z_label := popup.ids.get('ps_pos_z'):
                        z_label.text = f"Z: {pos['z']:.3f}"
                    # Enable/disable probe button based on Z position
                    if probe_btn := popup.ids.get('ps_probe_btn'):
                        probe_btn.disabled = not at_safe_z
                Clock.schedule_once(update_labels, 0)
            except Exception as e:
                debug_log(f"[PanelSetup] Position refresh error: {e}")
                def show_error(dt):
                    if not self.popup:
                        return
                    popup = self.popup
                    if x_label := popup.ids.get('ps_pos_x'):
                        x_label.text = "X: err"
                    if y_label := popup.ids.get('ps_pos_y'):
                        y_label.text = "Y: err"
                    if z_label := popup.ids.get('ps_pos_z'):
                        z_label.text = "Z: err"
                Clock.schedule_once(show_error, 0)
        
        asyncio.ensure_future(do_refresh())

    def set_xy_step(self, step):
        """Set XY jog step size."""
        self.xy_step = step
        debug_log(f"[PanelSetup] XY step set to {step} mm")
    
    def set_z_step(self, step):
        """Set Z jog step size."""
        self.z_step = step
        debug_log(f"[PanelSetup] Z step set to {step} mm")
    
    def home(self):
        """Home the machine from calibration dialog."""
        async def do_home():
            try:
                debug_log("[PanelSetup] Starting homing...")
                # Disable home button during homing
                def disable_btn(dt):
                    if self.popup:
                        btn = self.popup.ids.get('ps_home_btn')
                        if btn:
                            btn.disabled = True
                            btn.text = 'Homing...'
                Clock.schedule_once(disable_btn, 0)
                
                await self.bot.motion.connect()
                
                # Clear alarm
                await self.bot.motion.device.send_command("M999")
                
                # Force homing
                await self.bot.motion.send_gcode_wait_ok("$H", timeout=20)
                
                # Set work coordinates
                await self.bot.motion.send_gcode_wait_ok("G92 X0 Y0 Z0")
                
                debug_log("[PanelSetup] Homing complete")
                
                # Reset probe state since we're now at origin
                self.probe_z = None
            except Exception as e:
                debug_log(f"[PanelSetup] Homing error: {e}")
            finally:
                # Re-enable home button and refresh position
                def enable_btn(dt):
                    if self.popup:
                        btn = self.popup.ids.get('ps_home_btn')
                        if btn:
                            btn.disabled = False
                            btn.text = 'Go Home'
                        # Disable Go Ofs button since probe state is reset
                        goto_ofs_btn = self.popup.ids.get('ps_goto_offset_btn')
                        if goto_ofs_btn:
                            goto_ofs_btn.disabled = True
                        # Disable capture button since probe state is reset
                        capture_btn = self.popup.ids.get('ps_set_probe_offset_btn')
                        if capture_btn:
                            capture_btn.disabled = True
                Clock.schedule_once(enable_btn, 0)
                # Refresh position display
                self._refresh_position()
        
        asyncio.ensure_future(do_home())
    
    def jog(self, axis, direction):
        """Jog the machine in the specified axis and direction."""
        async def do_jog():
            try:
                if axis == 'x':
                    dist = self.xy_step * direction
                    await self.bot.motion.rapid_xy_rel(dist, 0)
                elif axis == 'y':
                    dist = self.xy_step * direction
                    await self.bot.motion.rapid_xy_rel(0, dist)
                elif axis == 'z':
                    dist = self.z_step * direction
                    # Use slower controlled movement for Z
                    await self.bot.motion.move_z_rel(dist, 500)
                # Wait for motion complete and refresh position
                await self.bot.motion.send_gcode_wait_ok("M400")
                self._refresh_position()
            except Exception as e:
                debug_log(f"[PanelSetup] Jog error: {e}")
        
        asyncio.ensure_future(do_jog())
    
    def safe_z(self):
        """Move to safe Z height (Z=0)."""
        async def do_safe_z():
            try:
                debug_log("[PanelSetup] Moving to safe Z...")
                await self.bot.motion.rapid_z_abs(0.0)
                await self.bot.motion.send_gcode_wait_ok("M400")
                debug_log("[PanelSetup] At safe Z")
                # Reset probe state since we're no longer at probe height
                self.probe_z = None
                # Disable Go Ofs and capture buttons, refresh position
                def update_ui(dt):
                    if self.popup:
                        goto_ofs_btn = self.popup.ids.get('ps_goto_offset_btn')
                        if goto_ofs_btn:
                            goto_ofs_btn.disabled = True
                        btn = self.popup.ids.get('ps_set_probe_offset_btn')
                        if btn:
                            btn.disabled = True
                Clock.schedule_once(update_ui, 0)
                self._refresh_position()
            except Exception as e:
                debug_log(f"[PanelSetup] Safe Z error: {e}")
        
        asyncio.ensure_future(do_safe_z())
    
    def do_probe(self):
        """Execute probe operation."""
        async def do_probe_async():
            try:
                debug_log("[PanelSetup] Starting probe...")
                
                # Disable probe button during probe
                def disable_probe_btn(dt):
                    if self.popup:
                        if btn := self.popup.ids.get('ps_probe_btn'):
                            btn.disabled = True
                        result_label = self.popup.ids.get('ps_probe_result')
                        if result_label:
                            result_label.text = 'Probing...'
                Clock.schedule_once(disable_probe_btn, 0)
                
                # Execute probe
                dist = await self.bot.motion.do_probe()
                self.probe_z = -dist  # Store the Z position after probe (negative)
                
                debug_log(f"[PanelSetup] Probe result: {dist} mm, Z position: {self.probe_z}")
                
                # Move to probe height and wait
                await self.bot.motion.rapid_z_abs(self.probe_z)
                await self.bot.motion.send_gcode_wait_ok("M400")
                
                # Refresh position display (probe button will stay disabled since not at safe Z)
                self._refresh_position()
                
                # Update UI
                def update_ui(dt):
                    if self.popup:
                        result_label = self.popup.ids.get('ps_probe_result')
                        if result_label:
                            result_label.text = f'Probe: {dist:.3f} mm'
                        # Enable Go Ofs button now that we've probed and are at probe height
                        goto_ofs_btn = self.popup.ids.get('ps_goto_offset_btn')
                        if goto_ofs_btn:
                            goto_ofs_btn.disabled = False
                        # Enable capture button now that we've probed
                        btn = self.popup.ids.get('ps_set_probe_offset_btn')
                        if btn:
                            btn.disabled = False
                Clock.schedule_once(update_ui, 0)
                
            except Exception as e:
                import traceback
                debug_log(f"[PanelSetup] Probe error: {e}")
                debug_log(traceback.format_exc())
                # Refresh position on error too
                self._refresh_position()
                def show_error(dt, err=str(e)):
                    if self.popup:
                        result_label = self.popup.ids.get('ps_probe_result')
                        if result_label:
                            result_label.text = f'FAILED: {err[:20]}'
                Clock.schedule_once(show_error, 0)
        
        asyncio.ensure_future(do_probe_async())
    
    def goto_origin(self):
        """Move to the currently configured board origin."""
        async def do_goto():
            try:
                # Read origin from the input fields (user may have edited without pressing Enter)
                ps = self.panel_settings
                x = float(ps.get('board_x', 0) if ps else 0)
                y = float(ps.get('board_y', 0) if ps else 0)
                
                if self.popup:
                    if x_input := self.popup.ids.get('ps_board_x_input'):
                        try:
                            x = float(x_input.text)
                        except ValueError:
                            pass
                    if y_input := self.popup.ids.get('ps_board_y_input'):
                        try:
                            y = float(y_input.text)
                        except ValueError:
                            pass
                
                debug_log(f"[PanelSetup] Moving to origin X={x:.2f}, Y={y:.2f}")
                
                # Move to origin position
                await self.bot.motion.rapid_xy_abs(x, y)
                await self.bot.motion.send_gcode_wait_ok("M400")
                
                debug_log("[PanelSetup] Arrived at origin")
                self._refresh_position()
                
            except Exception as e:
                debug_log(f"[PanelSetup] Go to origin error: {e}")
        
        asyncio.ensure_future(do_goto())
    
    def goto_offset(self):
        """Move Z down by the configured offset from probe position to board surface."""
        async def do_goto_offset():
            try:
                if self.probe_z is None:
                    debug_log("[PanelSetup] Must probe first!")
                    return
                
                # Read probe-to-board offset from input field (user may have edited without pressing Enter)
                ps = self.panel_settings
                offset = float(ps.get('probe_plane', 0) if ps else 0)
                
                if self.popup:
                    if probe_input := self.popup.ids.get('ps_probe_plane_input'):
                        try:
                            offset = float(probe_input.text)
                        except ValueError:
                            pass
                
                # Target Z is probe_z minus the offset (going further down)
                target_z = self.probe_z - offset
                
                debug_log(f"[PanelSetup] Moving to offset: probe_z={self.probe_z:.3f}, offset={offset:.3f}, target_z={target_z:.3f}")
                
                # Move Z to target position slowly (same speed as full_cycle)
                await self.bot.motion.move_z_abs(target_z, 200)
                
                debug_log("[PanelSetup] Arrived at offset position")
                self._refresh_position()
                
                # Disable Go Ofs button since we're no longer at probe height
                def update_ui(dt):
                    if self.popup:
                        btn = self.popup.ids.get('ps_goto_offset_btn')
                        if btn:
                            btn.disabled = True
                Clock.schedule_once(update_ui, 0)
                
            except Exception as e:
                debug_log(f"[PanelSetup] Go to offset error: {e}")
        
        asyncio.ensure_future(do_goto_offset())
    
    def set_board_origin(self):
        """Set board origin from current XY position."""
        async def do_set_origin():
            try:
                pos = await self.bot.motion.get_position()
                x, y = pos['x'], pos['y']
                
                # Update edit buffer (will be saved to panel_settings on Save)
                self._set_buffer_value('board_x', str(x))
                self._set_buffer_value('board_y', str(y))
                debug_log(f"[PanelSetup] Buffer: board_x={x}, board_y={y}")
                
                # Update UI widgets
                def update_ui(dt):
                    # Update calibration dialog inputs
                    if x_input := self.popup.ids.get('ps_board_x_input'):
                        x_input.text = f"{x:.2f}"
                    if y_input := self.popup.ids.get('ps_board_y_input'):
                        y_input.text = f"{y:.2f}"
                    # Update calibration dialog label
                    self._update_origin_label()
                Clock.schedule_once(update_ui, 0)
                
                debug_log(f"[PanelSetup] Board origin set to X={x:.2f}, Y={y:.2f}")
                
            except Exception as e:
                debug_log(f"[PanelSetup] Set origin error: {e}")
        
        asyncio.ensure_future(do_set_origin())
    
    def capture_probe_offset(self):
        """Capture probe-to-board offset from current Z position vs probe position."""
        async def do_capture():
            try:
                if self.probe_z is None:
                    debug_log("[PanelSetup] Must probe first!")
                    return
                
                # Get current Z position
                pos = await self.bot.motion.get_position()
                current_z = pos['z']
                
                # Offset = distance traveled from probe height to board surface
                # probe_z is negative (below zero), current_z is also negative (further down)
                # offset = probe_z - current_z (should be positive)
                offset = self.probe_z - current_z
                
                debug_log(f"[PanelSetup] Probe Z: {self.probe_z:.3f}, Current Z: {current_z:.3f}, Offset: {offset:.3f}")
                
                # Update edit buffer (will be saved to panel_settings on Save)
                self._set_buffer_value('probe_plane', str(offset))
                debug_log(f"[PanelSetup] Buffer: probe_plane={offset}")
                
                # Update UI widgets
                def update_ui(dt):
                    # Update calibration dialog input
                    if probe_input := self.popup.ids.get('ps_probe_plane_input'):
                        probe_input.text = f"{offset:.2f}"
                    # Update calibration dialog label
                    self._update_probe_offset_label()
                Clock.schedule_once(update_ui, 0)
                
                debug_log(f"[PanelSetup] Probe-to-board offset set to {offset:.2f} mm")
                
            except Exception as e:
                debug_log(f"[PanelSetup] Capture offset error: {e}")
        
        asyncio.ensure_future(do_capture())

    # ==================== Vision Tab Methods ====================
    
    def _sync_step_selectors_from_ui(self):
        """Read step selector values from UI toggle buttons to sync internal state."""
        if not self.popup:
            self.xy_step = 5.0
            self.z_step = 1.0
            self.vision_xy_step = 5.0
            return
        
        # Origins tab XY step selector
        xy_step_map = {
            'ps_xy_step_20': 20,
            'ps_xy_step_10': 10,
            'ps_xy_step_5': 5,
            'ps_xy_step_1': 1,
            'ps_xy_step_05': 0.5,
            'ps_xy_step_02': 0.2,
            'ps_xy_step_01': 0.1,
        }
        self.xy_step = 5.0  # Default
        for widget_id, step_val in xy_step_map.items():
            if btn := self.popup.ids.get(widget_id):
                if btn.state == 'down':
                    self.xy_step = step_val
                    break
        
        # Origins tab Z step selector
        z_step_map = {
            'ps_z_step_5': 5,
            'ps_z_step_1': 1,
            'ps_z_step_05': 0.5,
            'ps_z_step_02': 0.2,
            'ps_z_step_01': 0.1,
        }
        self.z_step = 1.0  # Default
        for widget_id, step_val in z_step_map.items():
            if btn := self.popup.ids.get(widget_id):
                if btn.state == 'down':
                    self.z_step = step_val
                    break
        
        # Vision tab XY step selector
        vision_step_map = {
            'vision_xy_step_20': 20,
            'vision_xy_step_10': 10,
            'vision_xy_step_5': 5,
            'vision_xy_step_1': 1,
            'vision_xy_step_05': 0.5,
            'vision_xy_step_02': 0.2,
            'vision_xy_step_01': 0.1,
        }
        self.vision_xy_step = 5.0  # Default
        for widget_id, step_val in vision_step_map.items():
            if btn := self.popup.ids.get(widget_id):
                if btn.state == 'down':
                    self.vision_xy_step = step_val
                    break
        
        debug_log(f"[PanelSetup] Step selectors synced: xy={self.xy_step}, z={self.z_step}, vision_xy={self.vision_xy_step}")
    
    def _check_vision_tab_selected(self, dt):
        """Check if Vision tab is already selected and start camera if so."""
        if not self.popup:
            return
        
        vision_tab = self.popup.ids.get('vision_tab')
        if vision_tab and vision_tab.state == 'down':
            debug_log("[PanelSetup] Vision tab already selected on open, starting camera")
            self._start_vision_preview()
    
    def _init_vision_preview(self):
        """Initialize Vision tab preview to inactive state."""
        if not self.popup:
            return
        
        # Set initial inactive display
        status_label = self.popup.ids.get('vision_status_label')
        if status_label:
            status_label.text = 'Camera Preview'
            status_label.color = (0.5, 0.5, 0.5, 1)
        
        image_widget = self.popup.ids.get('vision_preview_image')
        if image_widget:
            image_widget.color = (0, 0, 0, 1)
            # Create black texture
            if not self._black_texture:
                self._black_texture = Texture.create(size=(1, 1))
                self._black_texture.blit_buffer(bytes([0, 0, 0]), colorfmt='rgb', bufferfmt='ubyte')
            image_widget.texture = self._black_texture
        
        # Reset QR detection display
        type_label = self.popup.ids.get('vision_qr_type_label')
        if type_label:
            type_label.text = 'No code detected'
            type_label.color = (0.5, 0.5, 0.5, 1)
        qr_label = self.popup.ids.get('vision_qr_detected_label')
        if qr_label:
            qr_label.text = ''
            qr_label.color = (0.5, 0.5, 0.5, 1)
        
        # Set rotation toggle to match current setting
        settings = self.get_settings()
        rotation = settings.get('camera_preview_rotation', 0)
        rotation_map = {0: 'vision_rot_0', 90: 'vision_rot_90', 180: 'vision_rot_180', 270: 'vision_rot_270'}
        toggle_id = rotation_map.get(rotation, 'vision_rot_0')
        if toggle_btn := self.popup.ids.get(toggle_id):
            toggle_btn.state = 'down'
        
        # Initialize board selector to 0,0
        self._update_board_selector_display()
    
    def _update_board_selector_display(self):
        """Update the board selector display with current col,row."""
        if not self.popup:
            return
        label = self.popup.ids.get('vision_board_pos_label')
        if label:
            label.text = f'{self.vision_board_col},{self.vision_board_row}'
    
    def vision_board_change(self, axis, delta):
        """Change the selected board col or row and move to that position."""
        # Get grid dimensions from input fields if available
        ps = self.panel_settings
        max_cols = int(ps.get('board_cols', 2) if ps else 2)
        max_rows = int(ps.get('board_rows', 5) if ps else 5)
        
        if self.popup:
            if cols_spinner := self.popup.ids.get('ps_board_cols_spinner'):
                try:
                    max_cols = int(cols_spinner.text)
                except ValueError:
                    pass
            if rows_spinner := self.popup.ids.get('ps_board_rows_spinner'):
                try:
                    max_rows = int(rows_spinner.text)
                except ValueError:
                    pass
        
        if axis == 'col':
            new_col = self.vision_board_col + delta
            if 0 <= new_col < max_cols:
                self.vision_board_col = new_col
        elif axis == 'row':
            new_row = self.vision_board_row + delta
            if 0 <= new_row < max_rows:
                self.vision_board_row = new_row
        
        self._update_board_selector_display()
        # Move to the new board position
        self.vision_goto_board()
    
    def vision_goto_board(self):
        """Move camera to the currently selected board's QR position."""
        self.vision_goto_board_qr(self.vision_board_col, self.vision_board_row)
    
    def vision_goto_board_qr(self, col, row):
        """Move camera to a specific board's QR position."""
        if not self.bot or not self.bot.motion:
            return
        
        async def do_move():
            try:
                # Read values from input fields where available, fallback to panel_settings
                ps = self.panel_settings
                
                # Get default values from settings
                board_x = float(ps.get('board_x', 0) if ps else 0)
                board_y = float(ps.get('board_y', 0) if ps else 0)
                col_width = float(ps.get('col_width', 48.0) if ps else 48.0)
                row_height = float(ps.get('row_height', 29.0) if ps else 29.0)
                qr_offset_x = float(ps.get('qr_offset_x', 0) if ps else 0)
                qr_offset_y = float(ps.get('qr_offset_y', 0) if ps else 0)
                
                # Override with input field values if available
                if self.popup:
                    if x_input := self.popup.ids.get('ps_board_x_input'):
                        try:
                            board_x = float(x_input.text)
                        except ValueError:
                            pass
                    if y_input := self.popup.ids.get('ps_board_y_input'):
                        try:
                            board_y = float(y_input.text)
                        except ValueError:
                            pass
                    if cw_input := self.popup.ids.get('ps_col_width_input'):
                        try:
                            col_width = float(cw_input.text)
                        except ValueError:
                            pass
                    if rh_input := self.popup.ids.get('ps_row_height_input'):
                        try:
                            row_height = float(rh_input.text)
                        except ValueError:
                            pass
                    if qr_x_input := self.popup.ids.get('ps_qr_offset_x_input'):
                        try:
                            qr_offset_x = float(qr_x_input.text)
                        except ValueError:
                            pass
                    if qr_y_input := self.popup.ids.get('ps_qr_offset_y_input'):
                        try:
                            qr_offset_y = float(qr_y_input.text)
                        except ValueError:
                            pass
                
                # Camera offsets are global settings (same for all panels)
                settings = self.get_settings()
                camera_offset_x = float(settings.get('camera_offset_x', 50.0))
                camera_offset_y = float(settings.get('camera_offset_y', 50.0))
                
                # Calculate board position
                target_board_x = board_x + (col * col_width)
                target_board_y = board_y + (row * row_height)
                
                # Calculate machine position to put camera over QR
                # (board + QR offset + camera offset, matching sequence.py)
                target_x = target_board_x + qr_offset_x + camera_offset_x
                target_y = target_board_y + qr_offset_y + camera_offset_y
                
                debug_log(f"[PanelSetup] Moving to board [{col},{row}] QR position: "
                         f"board=({target_board_x:.2f}, {target_board_y:.2f}), "
                         f"qr_offset=({qr_offset_x:.2f}, {qr_offset_y:.2f}), "
                         f"camera_offset=({camera_offset_x:.2f}, {camera_offset_y:.2f}), "
                         f"target=({target_x:.2f}, {target_y:.2f})")
                
                # Ensure at safe Z first
                await self.bot.motion.rapid_z_abs(0.0)
                await self.bot.motion.send_gcode_wait_ok("M400")
                
                # Move to target position
                await self.bot.motion.rapid_xy_abs(target_x, target_y)
                await self.bot.motion.send_gcode_wait_ok("M400")
                
                # Update position display
                self._refresh_vision_position()
                
            except Exception as e:
                debug_log(f"[PanelSetup] Error moving to board QR: {e}")
        
        asyncio.ensure_future(do_move())
    
    def _update_qr_offset_label(self):
        """Update the QR offset input fields with current panel settings."""
        if not self.popup:
            return
        # Update input fields with current values
        ps = self.panel_settings
        x = float(ps.get('qr_offset_x', 0) if ps else 0)
        y = float(ps.get('qr_offset_y', 0) if ps else 0)
        
        if qr_x_input := self.popup.ids.get('ps_qr_offset_x_input'):
            qr_x_input.text = f'{x:.1f}'
        if qr_y_input := self.popup.ids.get('ps_qr_offset_y_input'):
            qr_y_input.text = f'{y:.1f}'
    
    def vision_tab_changed(self, state):
        """Handle Vision tab state changes."""
        debug_log(f"[PanelSetup] Vision tab state: {state}")
        if state == 'down':
            # Tab selected - start camera preview
            self._start_vision_preview()
        else:
            # Tab deselected - stop camera preview
            self._stop_vision_preview()
    
    def _start_vision_preview(self):
        """Start camera preview on Vision tab."""
        if self.vision_preview_active:
            return
        
        debug_log("[PanelSetup] Starting vision preview")
        self.vision_preview_active = True
        
        # Reset board selector to 0,0
        self.vision_board_col = 0
        self.vision_board_row = 0
        self._update_board_selector_display()
        
        # Store original QR offset values for reset functionality
        ps = self.panel_settings
        self._saved_qr_offset_x = float(ps.get('qr_offset_x', 0) if ps else 0)
        self._saved_qr_offset_y = float(ps.get('qr_offset_y', 0) if ps else 0)
        debug_log(f"[PanelSetup] Saved QR offset for reset: ({self._saved_qr_offset_x:.2f}, {self._saved_qr_offset_y:.2f})")
        
        # Update status
        if self.popup:
            status_label = self.popup.ids.get('vision_status_label')
            if status_label:
                status_label.text = 'Connecting camera...'
                status_label.color = (1, 1, 0, 1)  # Yellow
        
        # Connect camera and start preview
        async def start_camera():
            try:
                # Ensure camera is connected via bot.vision
                if self.bot and self.bot.vision:
                    await self.bot.vision.connect()
                    debug_log("[PanelSetup] Camera connected")
                    
                    # Move to safe Z for camera focus
                    debug_log("[PanelSetup] Moving to safe Z for camera")
                    await self.bot.motion.rapid_z_abs(0.0)
                    await self.bot.motion.send_gcode_wait_ok("M400")
                    
                    # Move camera to board 0,0 QR position
                    # Get board origin from input fields
                    ps = self.panel_settings
                    board_x = float(ps.get('board_x', 0) if ps else 0)
                    board_y = float(ps.get('board_y', 0) if ps else 0)
                    qr_offset_x = float(ps.get('qr_offset_x', 0) if ps else 0)
                    qr_offset_y = float(ps.get('qr_offset_y', 0) if ps else 0)
                    
                    if self.popup:
                        if x_input := self.popup.ids.get('ps_board_x_input'):
                            try:
                                board_x = float(x_input.text)
                            except ValueError:
                                pass
                        if y_input := self.popup.ids.get('ps_board_y_input'):
                            try:
                                board_y = float(y_input.text)
                            except ValueError:
                                pass
                        if qr_x_input := self.popup.ids.get('ps_qr_offset_x_input'):
                            try:
                                qr_offset_x = float(qr_x_input.text)
                            except ValueError:
                                pass
                        if qr_y_input := self.popup.ids.get('ps_qr_offset_y_input'):
                            try:
                                qr_offset_y = float(qr_y_input.text)
                            except ValueError:
                                pass
                    
                    # Get camera offset from global settings
                    settings = self.get_settings()
                    camera_offset_x = float(settings.get('camera_offset_x', 50.0))
                    camera_offset_y = float(settings.get('camera_offset_y', 50.0))
                    
                    # Move to camera position over board 0,0 QR code
                    # (board_origin + qr_offset + camera_offset puts camera over QR)
                    target_x = board_x + qr_offset_x + camera_offset_x
                    target_y = board_y + qr_offset_y + camera_offset_y
                    
                    debug_log(f"[PanelSetup] Moving camera to board 0,0 QR: origin=({board_x:.2f},{board_y:.2f}), "
                             f"qr_offset=({qr_offset_x:.2f},{qr_offset_y:.2f}), "
                             f"camera_offset=({camera_offset_x:.2f},{camera_offset_y:.2f}), target=({target_x:.2f},{target_y:.2f})")
                    
                    def update_moving_status(dt):
                        if self.popup:
                            status_label = self.popup.ids.get('vision_status_label')
                            if status_label:
                                status_label.text = 'Moving to board 0,0...'
                                status_label.color = (1, 1, 0, 1)  # Yellow
                    Clock.schedule_once(update_moving_status, 0)
                    
                    await self.bot.motion.rapid_xy_abs(target_x, target_y)
                    await self.bot.motion.send_gcode_wait_ok("M400")
                    
                    debug_log("[PanelSetup] Camera positioned over board 0,0")
                    
                    # Start preview updates at 2 FPS
                    def schedule_preview(dt):
                        if self.vision_preview_active:
                            self.vision_preview_event = Clock.schedule_interval(
                                self._update_vision_preview, 0.5  # 2 FPS
                            )
                            # Update position display
                            self._refresh_vision_position()
                    Clock.schedule_once(schedule_preview, 0)
                    
                    # Update status
                    def update_status(dt):
                        if self.popup:
                            status_label = self.popup.ids.get('vision_status_label')
                            if status_label:
                                status_label.text = 'Camera Active'
                                status_label.color = (0, 1, 0, 1)  # Green
                    Clock.schedule_once(update_status, 0)
                else:
                    debug_log("[PanelSetup] No vision controller available")
                    def show_error(dt):
                        if self.popup:
                            status_label = self.popup.ids.get('vision_status_label')
                            if status_label:
                                status_label.text = 'No camera available'
                                status_label.color = (1, 0, 0, 1)  # Red
                    Clock.schedule_once(show_error, 0)
                    
            except Exception as e:
                debug_log(f"[PanelSetup] Camera connect error: {e}")
                def show_error(dt, err=str(e)):
                    if self.popup:
                        status_label = self.popup.ids.get('vision_status_label')
                        if status_label:
                            status_label.text = f'Camera error: {err[:30]}'
                            status_label.color = (1, 0, 0, 1)  # Red
                Clock.schedule_once(show_error, 0)
        
        asyncio.ensure_future(start_camera())
    
    def _stop_vision_preview(self):
        """Stop camera preview on Vision tab."""
        if not self.vision_preview_active:
            return
        
        debug_log("[PanelSetup] Stopping vision preview")
        self.vision_preview_active = False
        
        # Cancel preview updates
        if self.vision_preview_event:
            self.vision_preview_event.cancel()
            self.vision_preview_event = None
        
        # Reset display to inactive
        self._init_vision_preview()
    
    def _update_vision_preview(self, dt):
        """Update camera preview frame and scan for QR codes (called by Clock at 4 FPS)."""
        if not self.vision_preview_active or not self.popup:
            return
        
        if not self.bot or not self.bot.vision or not self.bot.vision.camera_process:
            return
        
        try:
            # Capture frame asynchronously
            async def capture_and_display():
                try:
                    frame = await self.bot.vision.capture_frame()
                    if frame is None:
                        return
                    
                    # Apply preprocessing (crop to square, convert to grayscale)
                    height, width = frame.shape[:2]
                    if width > height:
                        left = (width - height) // 2
                        right = left + height
                        frame = frame[:, left:right]
                    
                    # Convert to grayscale
                    if len(frame.shape) == 3:
                        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    else:
                        frame_gray = frame
                    
                    # Attempt QR code detection
                    qr_data = None
                    qr_type = None
                    
                    # Try standard QR detection first (fast)
                    try:
                        loop = asyncio.get_event_loop()
                        qr_data = await loop.run_in_executor(
                            None, self.bot.vision._detect_qr_single, frame_gray
                        )
                        if qr_data:
                            qr_type = 'Standard QR'
                    except Exception as e:
                        debug_log(f"[PanelSetup] Standard QR detection error: {e}")
                    
                    # If no standard QR found, try zxing detection (handles Micro QR and can also detect standard QR)
                    if not qr_data:
                        try:
                            loop = asyncio.get_event_loop()
                            result = await loop.run_in_executor(
                                None, self.bot.vision._detect_micro_qr_with_rotation, frame_gray, None
                            )
                            if result:
                                qr_data, qr_type = result
                        except Exception as e:
                            debug_log(f"[PanelSetup] Micro QR detection error: {e}")
                    
                    # Apply user-configured rotation for display
                    settings = self.get_settings()
                    rotation = settings.get('camera_preview_rotation', 0)
                    if rotation == 90:
                        frame_display = cv2.rotate(frame_gray, cv2.ROTATE_90_CLOCKWISE)
                    elif rotation == 180:
                        frame_display = cv2.rotate(frame_gray, cv2.ROTATE_180)
                    elif rotation == 270:
                        frame_display = cv2.rotate(frame_gray, cv2.ROTATE_90_COUNTERCLOCKWISE)
                    else:
                        frame_display = frame_gray
                    
                    # Flip for Kivy display
                    frame_flipped = cv2.flip(frame_display, 0)
                    
                    # Update texture and QR display on main thread
                    def update_ui(dt, frame=frame_flipped, qr_data=qr_data, qr_type=qr_type):
                        if not self.popup or not self.vision_preview_active:
                            return
                        
                        # Update camera preview
                        image_widget = self.popup.ids.get('vision_preview_image')
                        if image_widget:
                            # Convert grayscale to RGB for Kivy
                            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                            h, w = frame_rgb.shape[:2]
                            
                            # Reset color filter for normal display
                            image_widget.color = (1, 1, 1, 1)
                            
                            # Create or reuse texture
                            if image_widget.texture is None or image_widget.texture.size != (w, h):
                                image_widget.texture = Texture.create(size=(w, h), colorfmt='rgb')
                            
                            # Update texture
                            buf = frame_rgb.tobytes()
                            image_widget.texture.blit_buffer(buf, colorfmt='rgb', bufferfmt='ubyte')
                            image_widget.canvas.ask_update()
                        
                        # Update QR type label
                        type_label = self.popup.ids.get('vision_qr_type_label')
                        qr_label = self.popup.ids.get('vision_qr_detected_label')
                        if type_label:
                            if qr_type:
                                type_label.text = f'{qr_type}:'
                                type_label.color = (0, 1, 0, 1)  # Green for detected
                                type_label.halign = 'right'
                                type_label.size_hint_x = 0.5
                            else:
                                type_label.text = 'No code detected'
                                type_label.color = (0.5, 0.5, 0.5, 1)  # Gray for none
                                type_label.halign = 'center'
                                type_label.size_hint_x = 1.0  # Full width when no code
                        
                        # Update QR detection display
                        if qr_label:
                            if qr_data:
                                qr_label.text = qr_data
                                qr_label.color = (0, 1, 0, 1)  # Green for detected
                                qr_label.size_hint_x = 0.5
                            else:
                                qr_label.text = ''
                                qr_label.color = (0.5, 0.5, 0.5, 1)  # Gray for none
                                qr_label.size_hint_x = 0  # Hide when no code
                    
                    Clock.schedule_once(update_ui, 0)
                    
                except Exception as e:
                    debug_log(f"[PanelSetup] Preview frame error: {e}")
            
            asyncio.ensure_future(capture_and_display())
            
        except Exception as e:
            debug_log(f"[PanelSetup] Vision preview error: {e}")
    
    def _refresh_vision_position(self):
        """Query current position and update Vision tab display with relative coordinates.
        
        Shows position relative to the currently selected board's expected QR position.
        When at the correct QR position, this will show values matching the QR offset inputs.
        
        Formula: displayed = (machine_pos - camera_offset) - board_origin
        Where board_origin = board_x + (col * col_width), board_y + (row * row_height)
        """
        async def do_refresh():
            try:
                pos = await self.bot.motion.get_position()
                machine_x, machine_y = pos['x'], pos['y']
                
                # Get values from input fields where available
                ps = self.panel_settings
                board_x = float(ps.get('board_x', 0) if ps else 0)
                board_y = float(ps.get('board_y', 0) if ps else 0)
                col_width = float(ps.get('col_width', 48.0) if ps else 48.0)
                row_height = float(ps.get('row_height', 29.0) if ps else 29.0)
                
                if self.popup:
                    if x_input := self.popup.ids.get('ps_board_x_input'):
                        try:
                            board_x = float(x_input.text)
                        except ValueError:
                            pass
                    if y_input := self.popup.ids.get('ps_board_y_input'):
                        try:
                            board_y = float(y_input.text)
                        except ValueError:
                            pass
                    if cw_input := self.popup.ids.get('ps_col_width_input'):
                        try:
                            col_width = float(cw_input.text)
                        except ValueError:
                            pass
                    if rh_input := self.popup.ids.get('ps_row_height_input'):
                        try:
                            row_height = float(rh_input.text)
                        except ValueError:
                            pass
                
                # Camera offsets are global settings (use 50.0 as default to match sequence.py)
                settings = self.get_settings()
                camera_offset_x = float(settings.get('camera_offset_x', 50.0))
                camera_offset_y = float(settings.get('camera_offset_y', 50.0))
                
                # Calculate current board's origin
                current_board_x = board_x + (self.vision_board_col * col_width)
                current_board_y = board_y + (self.vision_board_row * row_height)
                
                # Calculate relative position (what QR offset would be if Set was pressed)
                # Camera views (machine_pos - camera_offset), so:
                # relative = (machine_pos - camera_offset) - board_origin
                rel_x = (machine_x - camera_offset_x) - current_board_x
                rel_y = (machine_y - camera_offset_y) - current_board_y
                
                debug_log(f"[Vision] Position refresh: machine=({machine_x:.2f},{machine_y:.2f}), "
                         f"camera_offset=({camera_offset_x:.2f},{camera_offset_y:.2f}), "
                         f"board_origin=({current_board_x:.2f},{current_board_y:.2f}), "
                         f"board_sel=({self.vision_board_col},{self.vision_board_row}), "
                         f"rel=({rel_x:.2f},{rel_y:.2f})")
                
                def update_labels(dt, rel_x=rel_x, rel_y=rel_y):
                    if not self.popup:
                        return
                    if x_label := self.popup.ids.get('vision_pos_x'):
                        x_label.text = f"X: {rel_x:.2f}"
                    if y_label := self.popup.ids.get('vision_pos_y'):
                        y_label.text = f"Y: {rel_y:.2f}"
                Clock.schedule_once(update_labels, 0)
            except Exception as e:
                debug_log(f"[PanelSetup] Vision position refresh error: {e}")
        
        asyncio.ensure_future(do_refresh())
    
    def vision_set_rotation(self, rotation):
        """Set camera preview rotation and save to settings."""
        settings = self.get_settings()
        settings.set('camera_preview_rotation', rotation)
        debug_log(f"[PanelSetup] Camera preview rotation set to {rotation}°")
        
        # Also update the Config tab spinner if it exists
        def update_config_spinner(dt):
            if self.app.root:
                spinner = self.app.root.ids.get('camera_rotation_spinner')
                if spinner:
                    spinner.text = f"{rotation}°"
        Clock.schedule_once(update_config_spinner, 0)
    
    def vision_set_xy_step(self, step):
        """Set XY jog step size for Vision tab."""
        self.vision_xy_step = step
        debug_log(f"[PanelSetup] Vision XY step set to {step} mm")
    
    def vision_jog(self, axis, direction):
        """Jog the machine in the specified axis and direction (Vision tab - XY only)."""
        async def do_jog():
            try:
                if axis == 'x':
                    dist = self.vision_xy_step * direction
                    await self.bot.motion.rapid_xy_rel(dist, 0)
                elif axis == 'y':
                    dist = self.vision_xy_step * direction
                    await self.bot.motion.rapid_xy_rel(0, dist)
                # Wait for motion complete and refresh position
                await self.bot.motion.send_gcode_wait_ok("M400")
                self._refresh_vision_position()
            except Exception as e:
                debug_log(f"[PanelSetup] Vision jog error: {e}")
        
        asyncio.ensure_future(do_jog())
    
    def vision_reset_qr_offset(self):
        """Reset QR offset values to what they were when entering the Vision tab."""
        # Restore saved values to input fields
        saved_x = getattr(self, '_saved_qr_offset_x', 0.0)
        saved_y = getattr(self, '_saved_qr_offset_y', 0.0)
        
        if self.popup:
            if qr_x_input := self.popup.ids.get('ps_qr_offset_x_input'):
                qr_x_input.text = f"{saved_x:.2f}"
            if qr_y_input := self.popup.ids.get('ps_qr_offset_y_input'):
                qr_y_input.text = f"{saved_y:.2f}"
        
        debug_log(f"[PanelSetup] Reset QR offset to saved values: ({saved_x:.2f}, {saved_y:.2f})")
        
        # Move back to the original QR position
        async def do_move():
            try:
                ps = self.panel_settings
                origin_x = float(ps.get('board_x', 0) if ps else 0)
                origin_y = float(ps.get('board_y', 0) if ps else 0)
                
                settings = self.get_settings()
                camera_offset_x = float(settings.get('camera_offset_x', 50.0))
                camera_offset_y = float(settings.get('camera_offset_y', 50.0))
                
                target_x = origin_x + saved_x + camera_offset_x
                target_y = origin_y + saved_y + camera_offset_y
                
                debug_log(f"[PanelSetup] Moving to reset QR position: ({target_x:.2f}, {target_y:.2f})")
                
                await self.bot.motion.rapid_xy_abs(target_x, target_y)
                await self.bot.motion.send_gcode_wait_ok("M400")
                
                self._refresh_vision_position()
                
            except Exception as e:
                debug_log(f"[PanelSetup] Reset QR position error: {e}")
        
        asyncio.ensure_future(do_move())
    
    def vision_set_qr_offset(self):
        """Set QR offset from current XY position relative to board origin."""
        async def do_set_offset():
            try:
                pos = await self.bot.motion.get_position()
                x, y = pos['x'], pos['y']
                
                # Read panel-specific values from panel_settings
                ps = self.panel_settings
                origin_x = float(ps.get('board_x', 0) if ps else 0)
                origin_y = float(ps.get('board_y', 0) if ps else 0)
                
                # Camera offsets are global settings (same for all panels)
                settings = self.get_settings()
                camera_offset_x = float(settings.get('camera_offset_x', 50.0))
                camera_offset_y = float(settings.get('camera_offset_y', 50.0))
                
                # QR offset: The camera views (machine_pos - camera_offset),
                # so QR physical location = current_pos - camera_offset
                # QR offset = QR location - board origin
                qr_offset_x = (x - camera_offset_x) - origin_x
                qr_offset_y = (y - camera_offset_y) - origin_y
                
                debug_log(f"[PanelSetup] Setting QR offset: pos=({x:.2f}, {y:.2f}), camera_offset=({camera_offset_x:.2f}, {camera_offset_y:.2f}), origin=({origin_x:.2f}, {origin_y:.2f}), offset=({qr_offset_x:.2f}, {qr_offset_y:.2f})")
                
                # Update edit buffer (will be saved to panel_settings on Save)
                self._set_buffer_value('qr_offset_x', str(qr_offset_x))
                self._set_buffer_value('qr_offset_y', str(qr_offset_y))
                debug_log(f"[PanelSetup] Buffer: qr_offset_x={qr_offset_x}, qr_offset_y={qr_offset_y}")
                
                # Update UI widgets
                def update_ui(dt):
                    # Update calibration dialog input fields
                    self._update_qr_offset_label()
                    # Flash status to indicate success
                    if self.popup:
                        status_label = self.popup.ids.get('vision_status_label')
                        if status_label:
                            status_label.text = f'QR Offset Set: ({qr_offset_x:.2f}, {qr_offset_y:.2f})'
                            status_label.color = (0, 1, 0, 1)  # Green
                Clock.schedule_once(update_ui, 0)
                
                debug_log(f"[PanelSetup] QR offset set to X={qr_offset_x:.2f}, Y={qr_offset_y:.2f}")
                
            except Exception as e:
                debug_log(f"[PanelSetup] Set QR offset error: {e}")
                def show_error(dt, err=str(e)):
                    if self.popup:
                        status_label = self.popup.ids.get('vision_status_label')
                        if status_label:
                            status_label.text = f'Error: {err[:30]}'
                            status_label.color = (1, 0, 0, 1)  # Red
                Clock.schedule_once(show_error, 0)
        
        asyncio.ensure_future(do_set_offset())
