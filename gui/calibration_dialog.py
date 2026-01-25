"""Calibration dialog for setting board origin and probe offset.

This module provides an interactive dialog for calibrating the ProgBot machine,
including XY/Z jogging, probing, and setting board origin and probe-to-board offset.
"""
import asyncio
from kivy.clock import Clock
from kivy.factory import Factory
from kivy.lang import Builder

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
        xy_step: Current XY jog step size in mm
        z_step: Current Z jog step size in mm
        probe_z: Z position after last probe (None if not probed)
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
        
        # Update current values display
        self._update_origin_label()
        self._update_probe_offset_label()
        
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
            settings = self.get_settings()
            x = settings.get('board_first_x', 0)
            y = settings.get('board_first_y', 0)
            origin_label.text = f'Origin: X={x:.2f}, Y={y:.2f}'
    
    def _update_probe_offset_label(self):
        """Update the probe offset label with current panel settings."""
        if not self.popup:
            return
        offset_label = self.popup.ids.get('cal_probe_offset_label')
        if offset_label:
            settings = self.get_settings()
            offset = settings.get('probe_plane_to_board', 0)
            offset_label.text = f'Z Offset: {offset:.2f} mm'
    
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
                settings = self.get_settings()
                x = settings.get('board_first_x', 0)
                y = settings.get('board_first_y', 0)
                
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
                
                settings = self.get_settings()
                offset = settings.get('probe_plane_to_board', 0)
                
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
                
                # Update settings
                settings = self.get_settings()
                settings.set('board_first_x', x)
                settings.set('board_first_y', y)
                
                # Update panel settings object
                if self.panel_settings:
                    self.panel_settings.board_first_x = x
                    self.panel_settings.board_first_y = y
                
                # Update bot config
                if self.bot and self.bot.config:
                    self.bot.config.board_first_x = x
                    self.bot.config.board_first_y = y
                
                # Save to panel file
                if self.panel_settings:
                    try:
                        self.panel_settings._save_settings()
                        debug_log(f"[Calibration] Saved origin to panel file")
                    except Exception as e:
                        debug_log(f"[Calibration] Error saving panel file: {e}")
                
                # Update UI widgets
                def update_ui(dt):
                    # Update Panel tab inputs
                    if x_input := self.app.root.ids.get('board_x_input'):
                        x_input.text = f"{x:.2f}"
                    if y_input := self.app.root.ids.get('board_y_input'):
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
                
                # Update settings
                settings = self.get_settings()
                settings.set('probe_plane_to_board', offset)
                
                # Update panel settings object
                if self.panel_settings:
                    self.panel_settings.probe_plane_to_board = offset
                
                # Update bot config
                if self.bot and self.bot.config:
                    self.bot.config.probe_plane_to_board = offset
                
                # Save to panel file
                if self.panel_settings:
                    try:
                        self.panel_settings._save_settings()
                        debug_log(f"[Calibration] Saved probe offset to panel file")
                    except Exception as e:
                        debug_log(f"[Calibration] Error saving panel file: {e}")
                
                # Update UI widgets
                def update_ui(dt):
                    # Update Panel tab input
                    if probe_input := self.app.root.ids.get('probe_plane_input'):
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
