"""Camera Preview Base Class for reusable camera preview functionality.

This module provides a base class for camera preview widgets that can be used
by multiple dialogs (Panel Setup Vision tab, Config Settings Camera tab, etc.).
"""
import asyncio
import cv2
import numpy as np
from kivy.clock import Clock
from kivy.graphics.texture import Texture


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


class CameraPreviewMixin:
    """Mixin class providing camera preview functionality.
    
    This class provides the core camera preview loop, frame capture, QR detection,
    and UI updates that can be used by any dialog with a camera preview.
    
    Required attributes from subclass:
        - app: Reference to the main Kivy App instance
        - popup: Reference to the popup widget containing preview elements
    
    Required widget IDs in popup.ids:
        - camera_preview_image: Image widget for displaying camera frames
        - camera_status_label: Label for camera status text
        
    Optional widget IDs:
        - camera_qr_type_label: Label for QR code type
        - camera_qr_data_label: Label for QR code data
    
    Attributes:
        camera_preview_active: Whether camera preview is currently running
        camera_preview_event: Clock event for preview updates
        _black_texture: Cached black texture for inactive state
    """
    
    def _init_camera_preview_state(self):
        """Initialize camera preview state variables. Call from __init__."""
        self.camera_preview_active = False
        self.camera_preview_event = None
        self._black_texture = None
        self._camera_rotation = 0  # Degrees (0, 90, 180, 270)
        self._crosshair_enabled = False  # Whether to draw crosshair on preview
    
    def set_crosshair_enabled(self, enabled):
        """Enable or disable crosshair drawing on camera preview.
        
        Args:
            enabled: True to show crosshair, False to hide
        """
        self._crosshair_enabled = enabled
        debug_log(f"[CameraPreview] Crosshair enabled: {enabled}")
    
    def _should_draw_crosshair(self):
        """Check if crosshair should be drawn. Override to customize.
        
        Returns:
            bool: True if crosshair should be drawn
        """
        return getattr(self, '_crosshair_enabled', False)
    
    def _draw_crosshair(self, frame_rgb, width, height):
        """Draw a bright cyan crosshair at the center of the frame.
        
        Args:
            frame_rgb: RGB numpy array to draw on (modified in place)
            width: Frame width
            height: Frame height
        """
        # Bright cyan color in BGR for OpenCV (which we'll use on RGB frame)
        # Cyan = (0, 255, 255) in RGB
        cyan = (0, 255, 255)
        
        center_x = width // 2
        center_y = height // 2
        
        # Line thickness and length
        thickness = 2
        line_length = min(width, height) // 6  # 1/6 of smaller dimension
        gap = 8  # Gap at center for better visibility
        
        # Draw horizontal lines (with gap in center)
        cv2.line(frame_rgb, (center_x - line_length, center_y), (center_x - gap, center_y), cyan, thickness)
        cv2.line(frame_rgb, (center_x + gap, center_y), (center_x + line_length, center_y), cyan, thickness)
        
        # Draw vertical lines (with gap in center)
        cv2.line(frame_rgb, (center_x, center_y - line_length), (center_x, center_y - gap), cyan, thickness)
        cv2.line(frame_rgb, (center_x, center_y + gap), (center_x, center_y + line_length), cyan, thickness)
        
        # Draw small center dot
        cv2.circle(frame_rgb, (center_x, center_y), 3, cyan, -1)
    
    @property
    def bot(self):
        """Access the ProgBot instance from the app. Override if needed."""
        return self.app.bot
    
    def get_settings(self):
        """Get the global settings dict. Override if needed."""
        from settings import get_settings
        return get_settings()
    
    def _get_camera_preview_widget_ids(self):
        """Return dict mapping logical names to widget IDs.
        
        Override this to customize widget ID names for your dialog.
        
        Returns:
            dict with keys: 'image', 'status', 'qr_type' (optional), 'qr_data' (optional)
        """
        return {
            'image': 'camera_preview_image',
            'status': 'camera_status_label',
            'qr_type': 'camera_qr_type_label',
            'qr_data': 'camera_qr_data_label',
        }
    
    def _init_camera_preview_display(self):
        """Initialize camera preview display to inactive state."""
        if not self.popup:
            return
        
        ids = self._get_camera_preview_widget_ids()
        
        # Set status to inactive
        if status_label := self.popup.ids.get(ids['status']):
            status_label.text = 'Camera Preview (Inactive)'
            status_label.color = (0.5, 0.5, 0.5, 1)
        
        # Set preview to black
        if image_widget := self.popup.ids.get(ids['image']):
            if not self._black_texture:
                self._black_texture = Texture.create(size=(1, 1))
                self._black_texture.blit_buffer(bytes([0, 0, 0]), colorfmt='rgb', bufferfmt='ubyte')
            image_widget.texture = self._black_texture
            image_widget.color = (0, 0, 0, 1)
        
        # Clear QR display
        if qr_type := self.popup.ids.get(ids.get('qr_type', '')):
            qr_type.text = 'No code detected'
            qr_type.color = (0.5, 0.5, 0.5, 1)
        if qr_data := self.popup.ids.get(ids.get('qr_data', '')):
            qr_data.text = ''
    
    def start_camera_preview(self, move_to_position=True, target_x=None, target_y=None):
        """Start camera preview.
        
        Args:
            move_to_position: If True, move to target position before starting
            target_x: X position to move to (if move_to_position is True)
            target_y: Y position to move to (if move_to_position is True)
        """
        if self.camera_preview_active:
            return
        
        debug_log("[CameraPreview] Starting camera preview")
        self.camera_preview_active = True
        
        ids = self._get_camera_preview_widget_ids()
        
        # Update status
        if self.popup:
            if status_label := self.popup.ids.get(ids['status']):
                status_label.text = 'Connecting camera...'
                status_label.color = (1, 1, 0, 1)  # Yellow
        
        # Connect camera and start preview
        async def start_camera():
            try:
                # Ensure camera is connected via bot.vision
                if self.bot and self.bot.vision:
                    await self.bot.vision.connect()
                    debug_log("[CameraPreview] Camera connected")
                    
                    # Move to position if requested
                    if move_to_position and target_x is not None and target_y is not None:
                        debug_log(f"[CameraPreview] Moving to ({target_x:.2f}, {target_y:.2f})")
                        
                        # Move to safe Z first
                        await self.bot.motion.rapid_z_abs(0.0)
                        await self.bot.motion.send_gcode_wait_ok("M400")
                        
                        # Move to target XY
                        await self.bot.motion.rapid_xy_abs(target_x, target_y)
                        await self.bot.motion.send_gcode_wait_ok("M400")
                        
                        debug_log("[CameraPreview] Position reached")
                    
                    # Start preview updates at 2 FPS
                    def schedule_preview(dt):
                        if self.camera_preview_active:
                            self.camera_preview_event = Clock.schedule_interval(
                                self._update_camera_preview, 0.5  # 2 FPS
                            )
                    Clock.schedule_once(schedule_preview, 0)
                    
                    # Update status
                    def update_status(dt):
                        if self.popup:
                            if status_label := self.popup.ids.get(ids['status']):
                                status_label.text = 'Camera Active'
                                status_label.color = (0, 1, 0, 1)  # Green
                    Clock.schedule_once(update_status, 0)
                else:
                    debug_log("[CameraPreview] No vision controller available")
                    def show_error(dt):
                        if self.popup:
                            if status_label := self.popup.ids.get(ids['status']):
                                status_label.text = 'No camera available'
                                status_label.color = (1, 0, 0, 1)  # Red
                    Clock.schedule_once(show_error, 0)
                    
            except Exception as e:
                debug_log(f"[CameraPreview] Camera connect error: {e}")
                def show_error(dt, err=str(e)):
                    if self.popup:
                        if status_label := self.popup.ids.get(ids['status']):
                            status_label.text = f'Camera error: {err[:30]}'
                            status_label.color = (1, 0, 0, 1)  # Red
                Clock.schedule_once(show_error, 0)
        
        asyncio.ensure_future(start_camera())
    
    def stop_camera_preview(self):
        """Stop camera preview."""
        if not self.camera_preview_active:
            return
        
        debug_log("[CameraPreview] Stopping camera preview")
        self.camera_preview_active = False
        
        # Cancel preview updates
        if self.camera_preview_event:
            self.camera_preview_event.cancel()
            self.camera_preview_event = None
        
        # Reset display to inactive
        self._init_camera_preview_display()
    
    def _update_camera_preview(self, dt):
        """Update camera preview frame and scan for QR codes (called by Clock)."""
        if not self.camera_preview_active or not self.popup:
            return
        
        if not self.bot or not self.bot.vision or not self.bot.vision.camera_process:
            return
        
        ids = self._get_camera_preview_widget_ids()
        
        try:
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
                    
                    # Attempt QR code detection (can be overridden in subclass)
                    qr_data, qr_type = await self._detect_qr_codes(frame_gray)
                    
                    # Apply user-configured rotation for display
                    rotation = self._get_camera_rotation()
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
                        if not self.popup or not self.camera_preview_active:
                            return
                        
                        # Update camera preview
                        image_widget = self.popup.ids.get(ids['image'])
                        if image_widget:
                            # Convert grayscale to RGB for Kivy
                            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                            h, w = frame_rgb.shape[:2]
                            
                            # Draw crosshair at center if enabled
                            if self._should_draw_crosshair():
                                self._draw_crosshair(frame_rgb, w, h)
                            
                            # Reset color filter for normal display
                            image_widget.color = (1, 1, 1, 1)
                            
                            # Create or reuse texture
                            if image_widget.texture is None or image_widget.texture.size != (w, h):
                                image_widget.texture = Texture.create(size=(w, h), colorfmt='rgb')
                            
                            # Update texture
                            buf = frame_rgb.tobytes()
                            image_widget.texture.blit_buffer(buf, colorfmt='rgb', bufferfmt='ubyte')
                            image_widget.canvas.ask_update()
                        
                        # Update QR display (if widgets exist)
                        self._update_qr_display(qr_data, qr_type)
                    
                    Clock.schedule_once(update_ui, 0)
                    
                except Exception as e:
                    debug_log(f"[CameraPreview] Preview frame error: {e}")
            
            asyncio.ensure_future(capture_and_display())
            
        except Exception as e:
            debug_log(f"[CameraPreview] Vision preview error: {e}")
    
    async def _detect_qr_codes(self, frame_gray):
        """Detect QR codes in frame. Override for custom behavior.
        
        Args:
            frame_gray: Grayscale frame to scan
            
        Returns:
            Tuple of (qr_data, qr_type) or (None, None) if not found
        """
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
            debug_log(f"[CameraPreview] Standard QR detection error: {e}")
        
        # If no standard QR found, try zxing detection (handles Micro QR)
        if not qr_data:
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, self.bot.vision._detect_micro_qr_with_rotation, frame_gray, None
                )
                if result:
                    qr_data, qr_type = result
            except Exception as e:
                debug_log(f"[CameraPreview] Micro QR detection error: {e}")
        
        return qr_data, qr_type
    
    def _get_camera_rotation(self):
        """Get camera rotation setting. Override if needed."""
        settings = self.get_settings()
        return settings.get('camera_preview_rotation', 0)
    
    def set_camera_rotation(self, rotation):
        """Set camera rotation and save to settings.
        
        Args:
            rotation: Rotation in degrees (0, 90, 180, 270)
        """
        self._camera_rotation = rotation
        # Save to settings - subclass should override to save appropriately
        self._save_camera_rotation(rotation)
    
    def _save_camera_rotation(self, rotation):
        """Save camera rotation to settings. Override in subclass."""
        pass  # Subclass should implement
    
    def _update_qr_display(self, qr_data, qr_type):
        """Update QR detection display. Override for custom behavior."""
        if not self.popup:
            return
        
        ids = self._get_camera_preview_widget_ids()
        
        # Update QR type label
        type_label = self.popup.ids.get(ids.get('qr_type', ''))
        data_label = self.popup.ids.get(ids.get('qr_data', ''))
        
        if type_label:
            if qr_type:
                type_label.text = f'{qr_type}:'
                type_label.color = (0, 1, 0, 1)  # Green for detected
                type_label.halign = 'right'
                if hasattr(type_label, 'size_hint_x'):
                    type_label.size_hint_x = 0.5
            else:
                type_label.text = 'No code detected'
                type_label.color = (0.5, 0.5, 0.5, 1)  # Gray for none
                type_label.halign = 'center'
                if hasattr(type_label, 'size_hint_x'):
                    type_label.size_hint_x = 1.0
        
        if data_label:
            if qr_data:
                data_label.text = qr_data
                data_label.color = (0, 1, 0, 1)  # Green for detected
                if hasattr(data_label, 'size_hint_x'):
                    data_label.size_hint_x = 0.5
            else:
                data_label.text = ''
                if hasattr(data_label, 'size_hint_x'):
                    data_label.size_hint_x = 0
