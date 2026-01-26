"""Jogging controls mixin for dialogs with motion platform control.

This module provides a reusable mixin class that adds XY jogging functionality
to dialog controllers. Used by Panel Setup (Vision tab) and Config Settings (Camera tab).
"""
import asyncio
from kivy.clock import Clock


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


class JoggingMixin:
    """Mixin providing XY jogging controls for dialog controllers.
    
    Subclasses must implement:
        - bot property: Returns the ProgBot instance
        - popup property/attribute: The dialog popup with jogging control widgets
        
    Subclasses should call:
        - _init_jogging_state() in __init__
        - _update_position_display() after motion completes
        
    Widget IDs expected (with configurable prefix):
        - {prefix}_pos_x: Label showing current X position
        - {prefix}_pos_y: Label showing current Y position
        - {prefix}_xy_step_*: ToggleButtons for step size selection
    """
    
    def _init_jogging_state(self):
        """Initialize jogging state variables. Call from __init__."""
        self._jog_xy_step = 5.0
        self._jog_widget_prefix = 'cs'  # Default prefix, can be overridden
    
    def _get_jogging_widget_ids(self):
        """Get widget IDs for jogging controls.
        
        Override to customize widget ID prefix.
        
        Returns:
            dict: Mapping of widget roles to widget IDs
        """
        prefix = getattr(self, '_jog_widget_prefix', 'cs')
        return {
            'pos_x': f'{prefix}_jog_pos_x',
            'pos_y': f'{prefix}_jog_pos_y',
            'status': f'{prefix}_jog_status',
        }
    
    def set_jog_xy_step(self, step):
        """Set XY jog step size.
        
        Args:
            step: Step size in mm (0.1, 0.2, 0.5, 1, 5, 10, 20)
        """
        self._jog_xy_step = step
        debug_log(f"[JoggingMixin] XY step set to {step} mm")
    
    def jog_xy(self, axis, direction):
        """Jog the machine in the specified axis and direction.
        
        Args:
            axis: 'x' or 'y'
            direction: 1 for positive, -1 for negative
        """
        async def do_jog():
            try:
                if not self.bot or not self.bot.motion:
                    debug_log("[JoggingMixin] No motion controller available")
                    return
                
                step = self._jog_xy_step
                if axis == 'x':
                    await self.bot.motion.rapid_xy_rel(step * direction, 0)
                elif axis == 'y':
                    await self.bot.motion.rapid_xy_rel(0, step * direction)
                
                # Wait for motion to complete
                await self.bot.motion.send_gcode_wait_ok("M400")
                
                # Update position display
                self._refresh_jog_position()
                
            except Exception as e:
                debug_log(f"[JoggingMixin] Jog error: {e}")
        
        asyncio.ensure_future(do_jog())
    
    def _refresh_jog_position(self):
        """Refresh and display current machine position."""
        async def do_refresh():
            try:
                if not self.bot or not self.bot.motion:
                    return
                
                pos = await self.bot.motion.get_position()
                x, y = pos['x'], pos['y']
                
                debug_log(f"[JoggingMixin] Position: X={x:.2f}, Y={y:.2f}")
                
                # Update position labels
                def update_labels(dt, x=x, y=y):
                    if not self.popup:
                        return
                    widget_ids = self._get_jogging_widget_ids()
                    if x_label := self.popup.ids.get(widget_ids['pos_x']):
                        x_label.text = f"X: {x:.2f}"
                    if y_label := self.popup.ids.get(widget_ids['pos_y']):
                        y_label.text = f"Y: {y:.2f}"
                
                Clock.schedule_once(update_labels, 0)
                
            except Exception as e:
                debug_log(f"[JoggingMixin] Position refresh error: {e}")
        
        asyncio.ensure_future(do_refresh())
    
    def capture_current_position(self):
        """Capture current machine position and return it.
        
        This is typically called by subclasses to implement offset capture.
        
        Returns:
            tuple: (x, y) position, or None if unavailable
        """
        async def do_capture():
            try:
                if not self.bot or not self.bot.motion:
                    debug_log("[JoggingMixin] No motion controller for capture")
                    return None
                
                pos = await self.bot.motion.get_position()
                x, y = pos['x'], pos['y']
                debug_log(f"[JoggingMixin] Captured position: X={x:.2f}, Y={y:.2f}")
                return (x, y)
                
            except Exception as e:
                debug_log(f"[JoggingMixin] Capture error: {e}")
                return None
        
        return asyncio.ensure_future(do_capture())
    
    def capture_camera_offset(self):
        """Capture current position as camera offset.
        
        This calculates the camera offset based on the assumption that:
        - The user has jogged the machine so the camera is centered on a known reference point
        - The current machine position represents where the tool would need to be
          for the camera to view the reference point
          
        The camera offset is the vector from tool position to camera position.
        
        Override _on_camera_offset_captured() to handle the result.
        """
        async def do_capture():
            try:
                if not self.bot or not self.bot.motion:
                    debug_log("[JoggingMixin] No motion controller for offset capture")
                    return
                
                pos = await self.bot.motion.get_position()
                offset_x, offset_y = pos['x'], pos['y']
                
                debug_log(f"[JoggingMixin] Camera offset captured: X={offset_x:.2f}, Y={offset_y:.2f}")
                
                # Call the handler on main thread
                def call_handler(dt, x=offset_x, y=offset_y):
                    self._on_camera_offset_captured(x, y)
                
                Clock.schedule_once(call_handler, 0)
                
            except Exception as e:
                debug_log(f"[JoggingMixin] Offset capture error: {e}")
        
        asyncio.ensure_future(do_capture())
    
    def _on_camera_offset_captured(self, offset_x, offset_y):
        """Handle captured camera offset.
        
        Override in subclass to save the offset values.
        
        Args:
            offset_x: Camera X offset in mm
            offset_y: Camera Y offset in mm
        """
        debug_log(f"[JoggingMixin] _on_camera_offset_captured not implemented: ({offset_x}, {offset_y})")
