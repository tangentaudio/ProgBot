from logger import get_logger
log = get_logger(__name__)

"""Config Settings dialog for configuring global machine settings.

This module provides an interactive dialog for configuring global settings
that apply to all panels: serial ports, camera, probing parameters, etc.
"""
import asyncio
import copy
import json
import cv2
import numpy as np
from kivy.clock import Clock
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.graphics.texture import Texture

from camera_preview_base import CameraPreviewMixin
from jogging_mixin import JoggingMixin

# Load the config settings KV file
Builder.load_file('config_settings.kv')



class ConfigSettingsController(CameraPreviewMixin, JoggingMixin):
    """Controller for the config settings dialog.
    
    This class manages the config settings popup and all related operations
    including serial port configuration, camera settings, and probing parameters.
    
    Attributes:
        app: Reference to the main Kivy App instance
        popup: The ConfigSettingsPopup widget instance
    """
    
    def __init__(self, app):
        """Initialize the config settings controller.
        
        Args:
            app: The main Kivy App instance
        """
        self.app = app
        self.popup = None
        
        # Edit buffer for deferred save/cancel
        self._edit_buffer = {}
        self._original_values = {}
        self._is_dirty = False
        
        # Initialize camera preview state from mixin
        self._init_camera_preview_state()
        
        # Initialize jogging state from mixin
        self._init_jogging_state()
        self._jog_widget_prefix = 'cs'  # Use 'cs_' prefix for widget IDs
    
    @property
    def bot(self):
        """Access the ProgBot instance from the app."""
        return self.app.bot
    
    def get_settings(self):
        """Get the settings module's get_settings function result."""
        from settings import get_settings
        return get_settings()
    
    def _get_camera_preview_widget_ids(self):
        """Return widget ID mappings for camera preview."""
        return {
            'image': 'cs_camera_preview_image',
            'status': 'cs_camera_status_label',
            'qr_type': 'cs_camera_qr_type_label',
            'qr_data': 'cs_camera_qr_data_label',
        }
    
    def open(self):
        """Open the config settings dialog."""
        log.debug("[ConfigSettings] Opening dialog")
        
        # Create popup if needed
        if not self.popup:
            self.popup = Factory.ConfigSettingsPopup()
        
        # Initialize edit buffer from current settings
        self._init_edit_buffer()
        
        # Sync buffer to dialog widgets
        self._sync_buffer_to_dialog()
        
        # Initialize camera preview display
        self._init_camera_preview_display()
        
        # Update save button state
        self._update_save_button()
        
        # Open popup
        self.popup.open()
        
        # Check if Camera tab is already selected and start camera if so
        Clock.schedule_once(self._check_camera_tab_selected, 0.1)
    
    def _init_edit_buffer(self):
        """Initialize the edit buffer with current global settings."""
        settings = self.get_settings()
        
        # Copy relevant settings to buffer
        self._edit_buffer = {
            # Serial ports
            'motion_port_id': settings.get('motion_port_id', ''),
            'head_port_id': settings.get('head_port_id', ''),
            'target_port_id': settings.get('target_port_id', ''),
            # Camera
            'camera_offset_x': float(settings.get('camera_offset_x', 50.0)),
            'camera_offset_y': float(settings.get('camera_offset_y', 50.0)),
            'camera_preview_rotation': int(settings.get('camera_preview_rotation', 0)),
            'qr_scan_timeout': float(settings.get('qr_scan_timeout', 5.0)),
            'qr_search_offset': float(settings.get('qr_search_offset', 2.0)),
            # Probing
            'contact_adjust_step': float(settings.get('contact_adjust_step', 0.1)),
        }
        
        # Keep a copy of original values for dirty detection
        self._original_values = copy.deepcopy(self._edit_buffer)
        self._is_dirty = False
        
        log.debug("[ConfigSettings] Edit buffer initialized")
    
    def _sync_buffer_to_dialog(self):
        """Sync edit buffer values to dialog widgets."""
        if not self.popup:
            return
        
        buf = self._edit_buffer
        
        # Camera settings
        if x_input := self.popup.ids.get('cs_camera_offset_x_input'):
            x_input.text = str(buf.get('camera_offset_x', 50.0))
        if y_input := self.popup.ids.get('cs_camera_offset_y_input'):
            y_input.text = str(buf.get('camera_offset_y', 50.0))
        
        if timeout_input := self.popup.ids.get('cs_qr_scan_timeout_input'):
            timeout_input.text = str(buf.get('qr_scan_timeout', 5.0))
        if search_input := self.popup.ids.get('cs_qr_search_offset_input'):
            search_input.text = str(buf.get('qr_search_offset', 2.0))
        
        # Camera rotation buttons
        rotation = buf.get('camera_preview_rotation', 0)
        self._sync_rotation_buttons(rotation)
        
        # Probing settings
        if step_input := self.popup.ids.get('cs_contact_adjust_step_input'):
            step_input.text = str(buf.get('contact_adjust_step', 0.1))
        
        # Serial port labels (read-only display, configured via separate dialog)
        self._update_serial_port_labels()
        
        log.debug("[ConfigSettings] Buffer synced to dialog")
    
    def _sync_rotation_buttons(self, rotation):
        """Sync rotation toggle buttons to match given rotation value."""
        if not self.popup:
            return
        
        btn_map = {
            0: 'cs_rot_0',
            90: 'cs_rot_90',
            180: 'cs_rot_180',
            270: 'cs_rot_270',
        }
        
        for rot, btn_id in btn_map.items():
            if btn := self.popup.ids.get(btn_id):
                btn.state = 'down' if rot == rotation else 'normal'
    
    def _update_serial_port_labels(self):
        """Update serial port display labels from buffer."""
        if not self.popup:
            return
        
        buf = self._edit_buffer
        
        if motion_label := self.popup.ids.get('cs_motion_port_label'):
            port_id = buf.get('motion_port_id', '')
            motion_label.text = port_id if port_id else 'Not configured'
            motion_label.color = (1, 1, 1, 1) if port_id else (0.7, 0.7, 0.7, 1)
        
        if head_label := self.popup.ids.get('cs_head_port_label'):
            port_id = buf.get('head_port_id', '')
            head_label.text = port_id if port_id else 'Not configured'
            head_label.color = (1, 1, 1, 1) if port_id else (0.7, 0.7, 0.7, 1)
        
        if target_label := self.popup.ids.get('cs_target_port_label'):
            port_id = buf.get('target_port_id', '')
            target_label.text = port_id if port_id else 'Not configured'
            target_label.color = (1, 1, 1, 1) if port_id else (0.7, 0.7, 0.7, 1)
    
    def _set_buffer_value(self, key, value):
        """Set a value in the edit buffer and mark dirty if changed."""
        old_value = self._edit_buffer.get(key)
        if old_value != value:
            self._edit_buffer[key] = value
            self._check_dirty()
            log.debug(f"[ConfigSettings] Buffer: {key} = {value}")
    
    def _get_buffer_value(self, key, default=None):
        """Get a value from the edit buffer."""
        return self._edit_buffer.get(key, default)
    
    def _check_dirty(self):
        """Check if buffer differs from original values and update dirty state."""
        is_dirty = json.dumps(self._edit_buffer, sort_keys=True) != json.dumps(self._original_values, sort_keys=True)
        if is_dirty != self._is_dirty:
            self._is_dirty = is_dirty
            # Schedule UI update on main thread (may be called from async context)
            Clock.schedule_once(lambda dt: self._update_save_button(), 0)
    
    def _update_save_button(self):
        """Update save button appearance based on dirty state."""
        if not self.popup:
            return
        if save_btn := self.popup.ids.get('cs_save_btn'):
            if self._is_dirty:
                save_btn.disabled = False
                save_btn.background_color = (0.2, 0.6, 0.3, 1)  # Green when dirty
                save_btn.text = 'Save *'
            else:
                save_btn.disabled = True
                save_btn.background_color = (0.3, 0.3, 0.3, 1)  # Gray when clean
                save_btn.text = 'Save'
    
    def save_settings(self):
        """Save the edit buffer to global settings."""
        if not self._is_dirty:
            log.debug("[ConfigSettings] No changes to save")
            return
        
        settings = self.get_settings()
        
        # Update settings with buffer values
        for key, value in self._edit_buffer.items():
            settings.set(key, value)
        
        # Update original values and clear dirty state
        self._original_values = copy.deepcopy(self._edit_buffer)
        self._is_dirty = False
        self._update_save_button()
        
        # Update app's cached settings_data if it exists
        if hasattr(self.app, 'settings_data') and self.app.settings_data:
            self.app.settings_data.update(self._edit_buffer)
        
        log.debug("[ConfigSettings] Settings saved")
        log.info("[ConfigSettings] Settings saved")
    
    def cancel(self):
        """Cancel editing and discard changes."""
        if self._is_dirty:
            log.debug("[ConfigSettings] Discarding unsaved changes")
        
        # Stop camera preview if active
        self.stop_camera_preview()
        
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
            self.save_settings()
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
        """Actually close the dialog."""
        log.debug("[ConfigSettings] Closing dialog...")
        
        # Stop camera preview if active
        self.stop_camera_preview()
        
        # Clear buffer
        self._edit_buffer = {}
        self._original_values = {}
        self._is_dirty = False
        
        # Dismiss dialog
        if self.popup:
            self.popup.dismiss()
        
        log.debug("[ConfigSettings] Dialog closed")
    
    def _check_camera_tab_selected(self, dt):
        """Check if Camera tab is selected and start preview if so."""
        if not self.popup:
            return
        
        camera_tab = self.popup.ids.get('cs_camera_tab')
        if camera_tab and camera_tab.state == 'down':
            log.debug("[ConfigSettings] Camera tab already selected, starting preview")
            self.start_camera_preview(move_to_position=False)
    
    # =========================================================================
    # Camera tab handlers
    # =========================================================================
    
    def camera_tab_changed(self, state):
        """Handle Camera tab state changes."""
        log.debug(f"[ConfigSettings] Camera tab state: {state}")
        if state == 'down':
            # Save original offset values for reset functionality
            self._saved_camera_offset_x = float(self._edit_buffer.get('camera_offset_x', 50.0))
            self._saved_camera_offset_y = float(self._edit_buffer.get('camera_offset_y', 50.0))
            log.debug(f"[ConfigSettings] Saved camera offset for reset: "
                     f"({self._saved_camera_offset_x:.2f}, {self._saved_camera_offset_y:.2f})")
            
            # Enable crosshair for camera offset calibration
            self.set_crosshair_enabled(True)
            
            self.start_camera_preview(move_to_position=False)
            # Move to board 0 origin position for camera calibration
            self._move_to_camera_calibration_position()
        else:
            # Disable crosshair when leaving tab
            self.set_crosshair_enabled(False)
            self.stop_camera_preview()
    
    def _move_to_camera_calibration_position(self):
        """Move motion platform to board 0 origin for camera offset calibration.
        
        This moves to the board origin (0,0) so the user can jog the camera
        to center it on a known reference point and capture the offset.
        """
        async def do_move():
            try:
                if not self.bot or not self.bot.motion:
                    log.debug("[ConfigSettings] No motion controller for camera position")
                    return
                
                # Get board origin from panel settings
                ps = self.app.panel_settings
                board_x = float(ps.get('board_x', 0) if ps else 0)
                board_y = float(ps.get('board_y', 0) if ps else 0)
                
                # Get current camera offset from buffer
                camera_offset_x = float(self._edit_buffer.get('camera_offset_x', 50.0))
                camera_offset_y = float(self._edit_buffer.get('camera_offset_y', 50.0))
                
                # Target position: board origin + camera offset
                # This puts the camera over the board origin
                target_x = board_x + camera_offset_x
                target_y = board_y + camera_offset_y
                
                log.debug(f"[ConfigSettings] Moving to camera calibration position: "
                         f"board=({board_x:.2f}, {board_y:.2f}), "
                         f"camera_offset=({camera_offset_x:.2f}, {camera_offset_y:.2f}), "
                         f"target=({target_x:.2f}, {target_y:.2f})")
                
                # Ensure at safe Z first
                await self.bot.motion.rapid_z_abs(0.0)
                await self.bot.motion.send_gcode_wait_ok("M400")
                
                # Move to target position
                await self.bot.motion.rapid_xy_abs(target_x, target_y)
                await self.bot.motion.send_gcode_wait_ok("M400")
                
                # Update position display
                self._refresh_jog_position()
                
            except Exception as e:
                log.debug(f"[ConfigSettings] Error moving to camera position: {e}")
        
        asyncio.ensure_future(do_move())
    
    def reset_camera_offset(self):
        """Reset camera offset values to what they were when entering the Camera tab."""
        saved_x = getattr(self, '_saved_camera_offset_x', 50.0)
        saved_y = getattr(self, '_saved_camera_offset_y', 50.0)
        
        # Restore saved values to buffer and input fields
        self._set_buffer_value('camera_offset_x', saved_x)
        self._set_buffer_value('camera_offset_y', saved_y)
        
        if self.popup:
            if x_input := self.popup.ids.get('cs_camera_offset_x_input'):
                x_input.text = f"{saved_x:.2f}"
            if y_input := self.popup.ids.get('cs_camera_offset_y_input'):
                y_input.text = f"{saved_y:.2f}"
        
        log.debug(f"[ConfigSettings] Reset camera offset to saved values: ({saved_x:.2f}, {saved_y:.2f})")
        
        # Move back to the original calibration position
        async def do_move():
            try:
                if not self.bot or not self.bot.motion:
                    return
                
                ps = self.app.panel_settings
                board_x = float(ps.get('board_x', 0) if ps else 0)
                board_y = float(ps.get('board_y', 0) if ps else 0)
                
                target_x = board_x + saved_x
                target_y = board_y + saved_y
                
                log.debug(f"[ConfigSettings] Moving to reset position: ({target_x:.2f}, {target_y:.2f})")
                
                await self.bot.motion.rapid_xy_abs(target_x, target_y)
                await self.bot.motion.send_gcode_wait_ok("M400")
                
                self._refresh_jog_position()
                
                # Show feedback
                if self.popup:
                    if status := self.popup.ids.get('cs_camera_status_label'):
                        status.text = 'Offset Reset'
                        status.color = (1, 1, 0, 1)  # Yellow
                        
                        def reset_status(dt):
                            if self.popup and status:
                                status.text = 'Camera Preview'
                                status.color = (0.5, 0.5, 0.5, 1)
                        Clock.schedule_once(reset_status, 2.0)
                
            except Exception as e:
                log.debug(f"[ConfigSettings] Reset camera position error: {e}")
        
        asyncio.ensure_future(do_move())
    
    def on_camera_offset_x_change(self, text):
        """Handle camera offset X input change."""
        try:
            value = float(text)
            self._set_buffer_value('camera_offset_x', value)
        except ValueError:
            pass
    
    def on_camera_offset_y_change(self, text):
        """Handle camera offset Y input change."""
        try:
            value = float(text)
            self._set_buffer_value('camera_offset_y', value)
        except ValueError:
            pass
    
    def on_qr_scan_timeout_change(self, text):
        """Handle QR scan timeout input change."""
        try:
            value = float(text)
            if 1.0 <= value <= 30.0:
                self._set_buffer_value('qr_scan_timeout', value)
        except ValueError:
            pass
    
    def on_qr_search_offset_change(self, text):
        """Handle QR search offset input change."""
        try:
            value = float(text)
            if 0.0 <= value <= 10.0:
                self._set_buffer_value('qr_search_offset', value)
        except ValueError:
            pass
    
    def set_rotation(self, rotation):
        """Set camera rotation."""
        log.debug(f"[ConfigSettings] Set rotation: {rotation}")
        self._set_buffer_value('camera_preview_rotation', rotation)
    
    def _get_camera_rotation(self):
        """Get camera rotation from buffer."""
        return self._edit_buffer.get('camera_preview_rotation', 0)
    
    def _save_camera_rotation(self, rotation):
        """Save camera rotation - handled via buffer."""
        self._set_buffer_value('camera_preview_rotation', rotation)
    
    def _refresh_jog_position(self):
        """Override to show position relative to board origin.
        
        The displayed position represents what the camera offset would be
        if 'Capture Offset' was pressed at the current position.
        
        Formula: displayed = machine_pos - board_origin
        """
        async def do_refresh():
            try:
                if not self.bot or not self.bot.motion:
                    return
                
                pos = await self.bot.motion.get_position()
                machine_x, machine_y = pos['x'], pos['y']
                
                # Get board origin from panel settings
                ps = self.app.panel_settings
                board_x = float(ps.get('board_x', 0) if ps else 0)
                board_y = float(ps.get('board_y', 0) if ps else 0)
                
                # Calculate relative position (this is what camera offset would be)
                rel_x = machine_x - board_x
                rel_y = machine_y - board_y
                
                log.debug(f"[ConfigSettings] Position refresh: machine=({machine_x:.2f},{machine_y:.2f}), "
                         f"board_origin=({board_x:.2f},{board_y:.2f}), "
                         f"rel=({rel_x:.2f},{rel_y:.2f})")
                
                def update_labels(dt, rel_x=rel_x, rel_y=rel_y):
                    if not self.popup:
                        return
                    if x_label := self.popup.ids.get('cs_jog_pos_x'):
                        x_label.text = f"X: {rel_x:.2f}"
                    if y_label := self.popup.ids.get('cs_jog_pos_y'):
                        y_label.text = f"Y: {rel_y:.2f}"
                Clock.schedule_once(update_labels, 0)
                
            except Exception as e:
                log.debug(f"[ConfigSettings] Position refresh error: {e}")
        
        asyncio.ensure_future(do_refresh())
    
    def capture_camera_offset(self):
        """Capture current position as camera offset relative to board origin.
        
        The camera offset is the vector from board origin to the current
        machine position when the camera is centered on the board origin marker.
        
        Formula: camera_offset = machine_pos - board_origin
        """
        async def do_capture():
            try:
                if not self.bot or not self.bot.motion:
                    log.debug("[ConfigSettings] No motion controller for offset capture")
                    return
                
                pos = await self.bot.motion.get_position()
                machine_x, machine_y = pos['x'], pos['y']
                
                # Get board origin from panel settings
                ps = self.app.panel_settings
                board_x = float(ps.get('board_x', 0) if ps else 0)
                board_y = float(ps.get('board_y', 0) if ps else 0)
                
                # Calculate camera offset relative to board origin
                offset_x = machine_x - board_x
                offset_y = machine_y - board_y
                
                log.debug(f"[ConfigSettings] Capturing camera offset: machine=({machine_x:.2f},{machine_y:.2f}), "
                         f"board_origin=({board_x:.2f},{board_y:.2f}), "
                         f"offset=({offset_x:.2f},{offset_y:.2f})")
                
                # Call the handler on main thread
                def call_handler(dt, x=offset_x, y=offset_y):
                    self._on_camera_offset_captured(x, y)
                
                Clock.schedule_once(call_handler, 0)
                
            except Exception as e:
                log.debug(f"[ConfigSettings] Offset capture error: {e}")
        
        asyncio.ensure_future(do_capture())
    
    def _on_camera_offset_captured(self, offset_x, offset_y):
        """Handle captured camera offset.
        
        Called when user presses 'Capture Offset' button after jogging
        to center the camera on the board origin reference point.
        
        Args:
            offset_x: Camera X offset relative to board origin in mm
            offset_y: Camera Y offset relative to board origin in mm
        """
        log.debug(f"[ConfigSettings] Camera offset captured: X={offset_x:.2f}, Y={offset_y:.2f}")
        
        # Store in buffer
        self._set_buffer_value('camera_offset_x', offset_x)
        self._set_buffer_value('camera_offset_y', offset_y)
        
        # Update UI input fields
        if self.popup:
            if x_input := self.popup.ids.get('cs_camera_offset_x_input'):
                x_input.text = f"{offset_x:.2f}"
            if y_input := self.popup.ids.get('cs_camera_offset_y_input'):
                y_input.text = f"{offset_y:.2f}"
            
            # Show feedback in status label
            if status := self.popup.ids.get('cs_camera_status_label'):
                status.text = f'Offset Captured: ({offset_x:.2f}, {offset_y:.2f})'
                status.color = (0, 1, 0, 1)  # Green
                
                # Reset status after a delay
                def reset_status(dt):
                    if self.popup and status:
                        status.text = 'Camera Preview'
                        status.color = (0.5, 0.5, 0.5, 1)
                Clock.schedule_once(reset_status, 2.0)
    
    # =========================================================================
    # Probing tab handlers
    # =========================================================================
    
    def on_contact_adjust_step_change(self, text):
        """Handle contact adjust step input change."""
        try:
            value = float(text)
            if 0.01 <= value <= 1.0:
                self._set_buffer_value('contact_adjust_step', value)
        except ValueError:
            pass
    
    # =========================================================================
    # Serial Ports tab handlers
    # =========================================================================
    
    def reconfigure_motion_port(self):
        """Open serial port selector for motion controller."""
        self._reconfigure_port('motion')
    
    def reconfigure_head_port(self):
        """Open serial port selector for head controller."""
        self._reconfigure_port('head')
    
    def reconfigure_target_port(self):
        """Open serial port selector for target device."""
        self._reconfigure_port('target')
    
    def _reconfigure_port(self, port_type):
        """Open serial port selector dialog for specified port type."""
        from device_discovery import DevicePortManager
        from kivy.app import App
        
        # Get available ports
        available_ports = DevicePortManager.list_ports()
        
        if not available_ports:
            log.debug(f"[ConfigSettings] No serial ports available")
            return
        
        # Build device type label
        device_type_labels = {
            'motion': 'Motion Controller',
            'head': 'Head Controller',
            'target': 'Target Device'
        }
        device_type = device_type_labels.get(port_type, port_type.capitalize())
        
        def on_port_selected(port_info):
            """Handle port selection from dialog."""
            if port_info:
                log.debug(f"[ConfigSettings] {port_type} port selected: {port_info.unique_id}")
                key = f'{port_type}_port_id'
                self._set_buffer_value(key, port_info.unique_id)
                self._update_serial_port_labels()
            else:
                log.debug(f"[ConfigSettings] {port_type} port selection cancelled")
        
        # Use the app's serial port selector instance
        app = App.get_running_app()
        app.serial_port_selector.show_dialog(device_type, available_ports, on_port_selected)
