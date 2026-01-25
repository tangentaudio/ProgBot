"""Calibration dialog for setting board origin, probe offset, and QR code offset.

This module provides an interactive dialog for calibrating the ProgBot machine,
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

# Load the calibration KV file
Builder.load_file('calibration.kv')


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


class CalibrationController:
    """Controller for the calibration dialog.
    
    This class manages the calibration popup and all related operations including
    jogging, homing, probing, and setting calibration values.
    
    Attributes:
        app: Reference to the main Kivy App instance
        popup: The CalibrationPopup widget instance
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
        debug_log("[Calibration] Opening dialog")
        
        if not self.bot or not self.bot.motion:
            debug_log("[Calibration] Bot or motion controller not initialized")
            return
        
        # Create popup if needed
        if not self.popup:
            self.popup = Factory.CalibrationPopup()
        
        # Initialize calibration state
        self.xy_step = 5.0
        self.z_step = 1.0
        self.probe_z = None
        self.vision_xy_step = 5.0
        
        # Sync panel settings to dialog widgets
        self._sync_panel_settings_to_dialog()
        
        # Update current values display
        self._update_origin_label()
        self._update_probe_offset_label()
        self._update_qr_offset_label()
        
        # Initialize Vision tab preview (inactive)
        self._init_vision_preview()
        
        # Query initial position
        self._refresh_position()
        
        # Open popup
        self.popup.open()
    
    def _update_origin_label(self):
        """Update the origin label with current panel settings."""
        if not self.popup:
            return
        origin_label = self.popup.ids.get('cal_origin_label')
        if origin_label:
            # Read from panel settings (panel-specific values)
            ps = self.panel_settings
            x = float(ps.get('board_x', 0) if ps else 0)
            y = float(ps.get('board_y', 0) if ps else 0)
            origin_label.text = f'Origin: X={x:.2f}, Y={y:.2f}'
    
    def _update_probe_offset_label(self):
        """Update the probe offset label with current panel settings."""
        if not self.popup:
            return
        offset_label = self.popup.ids.get('cal_probe_offset_label')
        if offset_label:
            # Read from panel settings (panel-specific values)
            ps = self.panel_settings
            offset = float(ps.get('probe_plane', 0) if ps else 0)
            offset_label.text = f'Z Offset: {offset:.2f} mm'
    
    def _sync_panel_settings_to_dialog(self):
        """Sync current panel settings values to dialog input widgets."""
        if not self.popup:
            return
        
        ps = self.panel_settings
        settings = self.get_settings()
        
        # Parameters tab
        if cols_spinner := self.popup.ids.get('cal_board_cols_spinner'):
            cols_spinner.text = str(ps.get('board_cols', '2') if ps else settings.get('board_cols', '2'))
        if rows_spinner := self.popup.ids.get('cal_board_rows_spinner'):
            rows_spinner.text = str(ps.get('board_rows', '5') if ps else settings.get('board_rows', '5'))
        if col_width := self.popup.ids.get('cal_col_width_input'):
            col_width.text = str(ps.get('col_width', '48.0') if ps else settings.get('col_width', '48.0'))
        if row_height := self.popup.ids.get('cal_row_height_input'):
            row_height.text = str(ps.get('row_height', '29.0') if ps else settings.get('row_height', '29.0'))
        
        # Origin tab
        if board_x := self.popup.ids.get('cal_board_x_input'):
            board_x.text = str(ps.get('board_x', '110.2') if ps else settings.get('board_x', '110.2'))
        if board_y := self.popup.ids.get('cal_board_y_input'):
            board_y.text = str(ps.get('board_y', '121.0') if ps else settings.get('board_y', '121.0'))
        if probe_plane := self.popup.ids.get('cal_probe_plane_input'):
            probe_plane.text = str(ps.get('probe_plane', '4.0') if ps else settings.get('probe_plane', '4.0'))
        
        # Vision tab
        if qr_offset_x := self.popup.ids.get('cal_qr_offset_x_input'):
            qr_offset_x.text = str(ps.get('qr_offset_x', '0.0') if ps else settings.get('qr_offset_x', '0.0'))
        if qr_offset_y := self.popup.ids.get('cal_qr_offset_y_input'):
            qr_offset_y.text = str(ps.get('qr_offset_y', '0.0') if ps else settings.get('qr_offset_y', '0.0'))
        if use_camera := self.popup.ids.get('cal_use_camera_checkbox'):
            use_camera.state = 'down' if settings.get('use_camera', True) else 'normal'
        
        debug_log("[Calibration] Synced panel settings to dialog")
    
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
                    if x_label := popup.ids.get('cal_pos_x'):
                        x_label.text = f"X: {pos['x']:.3f}"
                    if y_label := popup.ids.get('cal_pos_y'):
                        y_label.text = f"Y: {pos['y']:.3f}"
                    if z_label := popup.ids.get('cal_pos_z'):
                        z_label.text = f"Z: {pos['z']:.3f}"
                    # Enable/disable probe button based on Z position
                    if probe_btn := popup.ids.get('cal_probe_btn'):
                        probe_btn.disabled = not at_safe_z
                Clock.schedule_once(update_labels, 0)
            except Exception as e:
                debug_log(f"[Calibration] Position refresh error: {e}")
                def show_error(dt):
                    if not self.popup:
                        return
                    popup = self.popup
                    if x_label := popup.ids.get('cal_pos_x'):
                        x_label.text = "X: err"
                    if y_label := popup.ids.get('cal_pos_y'):
                        y_label.text = "Y: err"
                    if z_label := popup.ids.get('cal_pos_z'):
                        z_label.text = "Z: err"
                Clock.schedule_once(show_error, 0)
        
        asyncio.ensure_future(do_refresh())

    def set_xy_step(self, step):
        """Set XY jog step size."""
        self.xy_step = step
        debug_log(f"[Calibration] XY step set to {step} mm")
    
    def set_z_step(self, step):
        """Set Z jog step size."""
        self.z_step = step
        debug_log(f"[Calibration] Z step set to {step} mm")
    
    def home(self):
        """Home the machine from calibration dialog."""
        async def do_home():
            try:
                debug_log("[Calibration] Starting homing...")
                # Disable home button during homing
                def disable_btn(dt):
                    if self.popup:
                        btn = self.popup.ids.get('cal_home_btn')
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
                
                debug_log("[Calibration] Homing complete")
                
                # Reset probe state since we're now at origin
                self.probe_z = None
            except Exception as e:
                debug_log(f"[Calibration] Homing error: {e}")
            finally:
                # Re-enable home button and refresh position
                def enable_btn(dt):
                    if self.popup:
                        btn = self.popup.ids.get('cal_home_btn')
                        if btn:
                            btn.disabled = False
                            btn.text = 'Go Home'
                        # Disable Go Ofs button since probe state is reset
                        goto_ofs_btn = self.popup.ids.get('cal_goto_offset_btn')
                        if goto_ofs_btn:
                            goto_ofs_btn.disabled = True
                        # Disable capture button since probe state is reset
                        capture_btn = self.popup.ids.get('cal_set_probe_offset_btn')
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
                debug_log(f"[Calibration] Jog error: {e}")
        
        asyncio.ensure_future(do_jog())
    
    def safe_z(self):
        """Move to safe Z height (Z=0)."""
        async def do_safe_z():
            try:
                debug_log("[Calibration] Moving to safe Z...")
                await self.bot.motion.rapid_z_abs(0.0)
                await self.bot.motion.send_gcode_wait_ok("M400")
                debug_log("[Calibration] At safe Z")
                # Reset probe state since we're no longer at probe height
                self.probe_z = None
                # Disable Go Ofs and capture buttons, refresh position
                def update_ui(dt):
                    if self.popup:
                        goto_ofs_btn = self.popup.ids.get('cal_goto_offset_btn')
                        if goto_ofs_btn:
                            goto_ofs_btn.disabled = True
                        btn = self.popup.ids.get('cal_set_probe_offset_btn')
                        if btn:
                            btn.disabled = True
                Clock.schedule_once(update_ui, 0)
                self._refresh_position()
            except Exception as e:
                debug_log(f"[Calibration] Safe Z error: {e}")
        
        asyncio.ensure_future(do_safe_z())
    
    def do_probe(self):
        """Execute probe operation."""
        async def do_probe_async():
            try:
                debug_log("[Calibration] Starting probe...")
                
                # Disable probe button during probe
                def disable_probe_btn(dt):
                    if self.popup:
                        if btn := self.popup.ids.get('cal_probe_btn'):
                            btn.disabled = True
                        result_label = self.popup.ids.get('cal_probe_result')
                        if result_label:
                            result_label.text = 'Probing...'
                Clock.schedule_once(disable_probe_btn, 0)
                
                # Execute probe
                dist = await self.bot.motion.do_probe()
                self.probe_z = -dist  # Store the Z position after probe (negative)
                
                debug_log(f"[Calibration] Probe result: {dist} mm, Z position: {self.probe_z}")
                
                # Move to probe height and wait
                await self.bot.motion.rapid_z_abs(self.probe_z)
                await self.bot.motion.send_gcode_wait_ok("M400")
                
                # Refresh position display (probe button will stay disabled since not at safe Z)
                self._refresh_position()
                
                # Update UI
                def update_ui(dt):
                    if self.popup:
                        result_label = self.popup.ids.get('cal_probe_result')
                        if result_label:
                            result_label.text = f'Probe: {dist:.3f} mm'
                        # Enable Go Ofs button now that we've probed and are at probe height
                        goto_ofs_btn = self.popup.ids.get('cal_goto_offset_btn')
                        if goto_ofs_btn:
                            goto_ofs_btn.disabled = False
                        # Enable capture button now that we've probed
                        btn = self.popup.ids.get('cal_set_probe_offset_btn')
                        if btn:
                            btn.disabled = False
                Clock.schedule_once(update_ui, 0)
                
            except Exception as e:
                import traceback
                debug_log(f"[Calibration] Probe error: {e}")
                debug_log(traceback.format_exc())
                # Refresh position on error too
                self._refresh_position()
                def show_error(dt, err=str(e)):
                    if self.popup:
                        result_label = self.popup.ids.get('cal_probe_result')
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
                    if x_input := self.popup.ids.get('cal_board_x_input'):
                        try:
                            x = float(x_input.text)
                        except ValueError:
                            pass
                    if y_input := self.popup.ids.get('cal_board_y_input'):
                        try:
                            y = float(y_input.text)
                        except ValueError:
                            pass
                
                debug_log(f"[Calibration] Moving to origin X={x:.2f}, Y={y:.2f}")
                
                # Move to origin position
                await self.bot.motion.rapid_xy_abs(x, y)
                await self.bot.motion.send_gcode_wait_ok("M400")
                
                debug_log("[Calibration] Arrived at origin")
                self._refresh_position()
                
            except Exception as e:
                debug_log(f"[Calibration] Go to origin error: {e}")
        
        asyncio.ensure_future(do_goto())
    
    def goto_offset(self):
        """Move Z down by the configured offset from probe position to board surface."""
        async def do_goto_offset():
            try:
                if self.probe_z is None:
                    debug_log("[Calibration] Must probe first!")
                    return
                
                # Read probe-to-board offset from input field (user may have edited without pressing Enter)
                ps = self.panel_settings
                offset = float(ps.get('probe_plane', 0) if ps else 0)
                
                if self.popup:
                    if probe_input := self.popup.ids.get('cal_probe_plane_input'):
                        try:
                            offset = float(probe_input.text)
                        except ValueError:
                            pass
                
                # Target Z is probe_z minus the offset (going further down)
                target_z = self.probe_z - offset
                
                debug_log(f"[Calibration] Moving to offset: probe_z={self.probe_z:.3f}, offset={offset:.3f}, target_z={target_z:.3f}")
                
                # Move Z to target position slowly (same speed as full_cycle)
                await self.bot.motion.move_z_abs(target_z, 200)
                
                debug_log("[Calibration] Arrived at offset position")
                self._refresh_position()
                
                # Disable Go Ofs button since we're no longer at probe height
                def update_ui(dt):
                    if self.popup:
                        btn = self.popup.ids.get('cal_goto_offset_btn')
                        if btn:
                            btn.disabled = True
                Clock.schedule_once(update_ui, 0)
                
            except Exception as e:
                debug_log(f"[Calibration] Go to offset error: {e}")
        
        asyncio.ensure_future(do_goto_offset())
    
    def set_board_origin(self):
        """Set board origin from current XY position."""
        async def do_set_origin():
            try:
                pos = await self.bot.motion.get_position()
                x, y = pos['x'], pos['y']
                
                # Update panel settings (panel-specific values - this is the source of truth)
                if self.panel_settings:
                    self.panel_settings.set('board_x', x)
                    self.panel_settings.set('board_y', y)
                    debug_log(f"[Calibration] Saved origin to panel file")
                
                # Update app's settings_data cache to stay in sync
                if hasattr(self.app, 'settings_data'):
                    self.app.settings_data['board_x'] = x
                    self.app.settings_data['board_y'] = y
                
                # Update bot config for runtime
                if self.bot and self.bot.config:
                    self.bot.config.board_x = x
                    self.bot.config.board_y = y
                
                # Update UI widgets
                def update_ui(dt):
                    # Update calibration dialog inputs
                    if x_input := self.popup.ids.get('cal_board_x_input'):
                        x_input.text = f"{x:.2f}"
                    if y_input := self.popup.ids.get('cal_board_y_input'):
                        y_input.text = f"{y:.2f}"
                    # Update calibration dialog label
                    self._update_origin_label()
                Clock.schedule_once(update_ui, 0)
                
                debug_log(f"[Calibration] Board origin set to X={x:.2f}, Y={y:.2f}")
                
            except Exception as e:
                debug_log(f"[Calibration] Set origin error: {e}")
        
        asyncio.ensure_future(do_set_origin())
    
    def capture_probe_offset(self):
        """Capture probe-to-board offset from current Z position vs probe position."""
        async def do_capture():
            try:
                if self.probe_z is None:
                    debug_log("[Calibration] Must probe first!")
                    return
                
                # Get current Z position
                pos = await self.bot.motion.get_position()
                current_z = pos['z']
                
                # Offset = distance traveled from probe height to board surface
                # probe_z is negative (below zero), current_z is also negative (further down)
                # offset = probe_z - current_z (should be positive)
                offset = self.probe_z - current_z
                
                debug_log(f"[Calibration] Probe Z: {self.probe_z:.3f}, Current Z: {current_z:.3f}, Offset: {offset:.3f}")
                
                # Update panel settings (panel-specific value - this is the source of truth)
                if self.panel_settings:
                    self.panel_settings.set('probe_plane', offset)
                    debug_log(f"[Calibration] Saved probe offset to panel file")
                
                # Update app's settings_data cache to stay in sync
                if hasattr(self.app, 'settings_data'):
                    self.app.settings_data['probe_plane'] = offset
                
                # Update bot config for runtime
                if self.bot and self.bot.config:
                    self.bot.config.probe_plane_to_board = offset
                
                # Update UI widgets
                def update_ui(dt):
                    # Update calibration dialog input
                    if probe_input := self.popup.ids.get('cal_probe_plane_input'):
                        probe_input.text = f"{offset:.2f}"
                    # Update calibration dialog label
                    self._update_probe_offset_label()
                Clock.schedule_once(update_ui, 0)
                
                debug_log(f"[Calibration] Probe-to-board offset set to {offset:.2f} mm")
                
            except Exception as e:
                debug_log(f"[Calibration] Capture offset error: {e}")
        
        asyncio.ensure_future(do_capture())
    
    def close(self):
        """Close calibration dialog, moving to safe Z first if needed."""
        async def do_close():
            debug_log("[Calibration] Closing dialog...")
            
            # Stop vision preview if active
            self._stop_vision_preview()
            
            try:
                # Check current Z position and move to safe height if needed
                pos = await self.bot.motion.get_position()
                if pos['z'] < -0.5:  # If Z is more than 0.5mm below safe height
                    debug_log(f"[Calibration] Z at {pos['z']:.2f}, moving to safe Z before closing...")
                    await self.bot.motion.rapid_z_abs(0.0)
                    await self.bot.motion.send_gcode_wait_ok("M400")
                    debug_log("[Calibration] Safe Z reached")
            except Exception as e:
                debug_log(f"[Calibration] Error checking/moving Z: {e}")
            
            # Dismiss dialog
            def dismiss(dt):
                if self.popup:
                    self.popup.dismiss()
            Clock.schedule_once(dismiss, 0)
            debug_log("[Calibration] Dialog closed")
        
        asyncio.ensure_future(do_close())

    # ==================== Vision Tab Methods ====================
    
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
            if cols_spinner := self.popup.ids.get('cal_board_cols_spinner'):
                try:
                    max_cols = int(cols_spinner.text)
                except ValueError:
                    pass
            if rows_spinner := self.popup.ids.get('cal_board_rows_spinner'):
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
                    if x_input := self.popup.ids.get('cal_board_x_input'):
                        try:
                            board_x = float(x_input.text)
                        except ValueError:
                            pass
                    if y_input := self.popup.ids.get('cal_board_y_input'):
                        try:
                            board_y = float(y_input.text)
                        except ValueError:
                            pass
                    if cw_input := self.popup.ids.get('cal_col_width_input'):
                        try:
                            col_width = float(cw_input.text)
                        except ValueError:
                            pass
                    if rh_input := self.popup.ids.get('cal_row_height_input'):
                        try:
                            row_height = float(rh_input.text)
                        except ValueError:
                            pass
                    if qr_x_input := self.popup.ids.get('cal_qr_offset_x_input'):
                        try:
                            qr_offset_x = float(qr_x_input.text)
                        except ValueError:
                            pass
                    if qr_y_input := self.popup.ids.get('cal_qr_offset_y_input'):
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
                
                debug_log(f"[Calibration] Moving to board [{col},{row}] QR position: "
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
                debug_log(f"[Calibration] Error moving to board QR: {e}")
        
        asyncio.ensure_future(do_move())
    
    def _update_qr_offset_label(self):
        """Update the QR offset input fields with current panel settings."""
        if not self.popup:
            return
        # Update input fields with current values
        ps = self.panel_settings
        x = float(ps.get('qr_offset_x', 0) if ps else 0)
        y = float(ps.get('qr_offset_y', 0) if ps else 0)
        
        if qr_x_input := self.popup.ids.get('cal_qr_offset_x_input'):
            qr_x_input.text = f'{x:.1f}'
        if qr_y_input := self.popup.ids.get('cal_qr_offset_y_input'):
            qr_y_input.text = f'{y:.1f}'
    
    def vision_tab_changed(self, state):
        """Handle Vision tab state changes."""
        debug_log(f"[Calibration] Vision tab state: {state}")
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
        
        debug_log("[Calibration] Starting vision preview")
        self.vision_preview_active = True
        
        # Reset board selector to 0,0
        self.vision_board_col = 0
        self.vision_board_row = 0
        self._update_board_selector_display()
        
        # Store original QR offset values for reset functionality
        ps = self.panel_settings
        self._saved_qr_offset_x = float(ps.get('qr_offset_x', 0) if ps else 0)
        self._saved_qr_offset_y = float(ps.get('qr_offset_y', 0) if ps else 0)
        debug_log(f"[Calibration] Saved QR offset for reset: ({self._saved_qr_offset_x:.2f}, {self._saved_qr_offset_y:.2f})")
        
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
                    debug_log("[Calibration] Camera connected")
                    
                    # Move to safe Z for camera focus
                    debug_log("[Calibration] Moving to safe Z for camera")
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
                        if x_input := self.popup.ids.get('cal_board_x_input'):
                            try:
                                board_x = float(x_input.text)
                            except ValueError:
                                pass
                        if y_input := self.popup.ids.get('cal_board_y_input'):
                            try:
                                board_y = float(y_input.text)
                            except ValueError:
                                pass
                        if qr_x_input := self.popup.ids.get('cal_qr_offset_x_input'):
                            try:
                                qr_offset_x = float(qr_x_input.text)
                            except ValueError:
                                pass
                        if qr_y_input := self.popup.ids.get('cal_qr_offset_y_input'):
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
                    
                    debug_log(f"[Calibration] Moving camera to board 0,0 QR: origin=({board_x:.2f},{board_y:.2f}), "
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
                    
                    debug_log("[Calibration] Camera positioned over board 0,0")
                    
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
                    debug_log("[Calibration] No vision controller available")
                    def show_error(dt):
                        if self.popup:
                            status_label = self.popup.ids.get('vision_status_label')
                            if status_label:
                                status_label.text = 'No camera available'
                                status_label.color = (1, 0, 0, 1)  # Red
                    Clock.schedule_once(show_error, 0)
                    
            except Exception as e:
                debug_log(f"[Calibration] Camera connect error: {e}")
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
        
        debug_log("[Calibration] Stopping vision preview")
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
                        debug_log(f"[Calibration] Standard QR detection error: {e}")
                    
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
                            debug_log(f"[Calibration] Micro QR detection error: {e}")
                    
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
                    debug_log(f"[Calibration] Preview frame error: {e}")
            
            asyncio.ensure_future(capture_and_display())
            
        except Exception as e:
            debug_log(f"[Calibration] Vision preview error: {e}")
    
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
                    if x_input := self.popup.ids.get('cal_board_x_input'):
                        try:
                            board_x = float(x_input.text)
                        except ValueError:
                            pass
                    if y_input := self.popup.ids.get('cal_board_y_input'):
                        try:
                            board_y = float(y_input.text)
                        except ValueError:
                            pass
                    if cw_input := self.popup.ids.get('cal_col_width_input'):
                        try:
                            col_width = float(cw_input.text)
                        except ValueError:
                            pass
                    if rh_input := self.popup.ids.get('cal_row_height_input'):
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
                debug_log(f"[Calibration] Vision position refresh error: {e}")
        
        asyncio.ensure_future(do_refresh())
    
    def vision_set_rotation(self, rotation):
        """Set camera preview rotation and save to settings."""
        settings = self.get_settings()
        settings.set('camera_preview_rotation', rotation)
        debug_log(f"[Calibration] Camera preview rotation set to {rotation}°")
        
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
        debug_log(f"[Calibration] Vision XY step set to {step} mm")
    
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
                debug_log(f"[Calibration] Vision jog error: {e}")
        
        asyncio.ensure_future(do_jog())
    
    def vision_reset_qr_offset(self):
        """Reset QR offset values to what they were when entering the Vision tab."""
        # Restore saved values to input fields
        saved_x = getattr(self, '_saved_qr_offset_x', 0.0)
        saved_y = getattr(self, '_saved_qr_offset_y', 0.0)
        
        if self.popup:
            if qr_x_input := self.popup.ids.get('cal_qr_offset_x_input'):
                qr_x_input.text = f"{saved_x:.2f}"
            if qr_y_input := self.popup.ids.get('cal_qr_offset_y_input'):
                qr_y_input.text = f"{saved_y:.2f}"
        
        debug_log(f"[Calibration] Reset QR offset to saved values: ({saved_x:.2f}, {saved_y:.2f})")
        
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
                
                debug_log(f"[Calibration] Moving to reset QR position: ({target_x:.2f}, {target_y:.2f})")
                
                await self.bot.motion.rapid_xy_abs(target_x, target_y)
                await self.bot.motion.send_gcode_wait_ok("M400")
                
                self._refresh_vision_position()
                
            except Exception as e:
                debug_log(f"[Calibration] Reset QR position error: {e}")
        
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
                
                debug_log(f"[Calibration] Setting QR offset: pos=({x:.2f}, {y:.2f}), camera_offset=({camera_offset_x:.2f}, {camera_offset_y:.2f}), origin=({origin_x:.2f}, {origin_y:.2f}), offset=({qr_offset_x:.2f}, {qr_offset_y:.2f})")
                
                # Update panel settings (panel-specific - this is the source of truth)
                if self.panel_settings:
                    self.panel_settings.set('qr_offset_x', qr_offset_x)
                    self.panel_settings.set('qr_offset_y', qr_offset_y)
                    debug_log(f"[Calibration] Saved QR offset to panel file")
                
                # Update app's settings_data cache to stay in sync
                if hasattr(self.app, 'settings_data'):
                    self.app.settings_data['qr_offset_x'] = qr_offset_x
                    self.app.settings_data['qr_offset_y'] = qr_offset_y
                
                # Update bot config for runtime
                if self.bot and self.bot.config:
                    self.bot.config.qr_offset_x = qr_offset_x
                    self.bot.config.qr_offset_y = qr_offset_y
                
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
                
                debug_log(f"[Calibration] QR offset set to X={qr_offset_x:.2f}, Y={qr_offset_y:.2f}")
                
            except Exception as e:
                debug_log(f"[Calibration] Set QR offset error: {e}")
                def show_error(dt, err=str(e)):
                    if self.popup:
                        status_label = self.popup.ids.get('vision_status_label')
                        if status_label:
                            status_label.text = f'Error: {err[:30]}'
                            status_label.color = (1, 0, 0, 1)  # Red
                Clock.schedule_once(show_error, 0)
        
        asyncio.ensure_future(do_set_offset())
