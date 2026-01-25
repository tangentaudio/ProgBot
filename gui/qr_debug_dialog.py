"""QR Code Debug Dialog - Live scanning with board position navigation."""
import asyncio
from kivy.uix.popup import Popup
from device_io import debug_log
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner
from kivy.uix.image import Image
from kivy.graphics.texture import Texture
from kivy.clock import Clock
import cv2


class QRDebugDialog(Popup):
    """Dialog for debugging QR code detection with live preview."""
    
    def __init__(self, vision_controller, motion_controller, config, **kwargs):
        """Initialize QR debug dialog.
        
        Args:
            vision_controller: VisionController instance for camera
            motion_controller: MotionController instance for positioning
            config: Configuration object with board settings
        """
        self.vision_controller = vision_controller
        self.motion_controller = motion_controller
        self.config = config
        self.active = False
        self.update_event = None
        self.current_qr = None
        
        super().__init__(
            title='QR Code Scanner - Debug Mode',
            size_hint=(0.9, 0.9),
            auto_dismiss=False,
            **kwargs
        )
        
        # Build UI
        self._build_ui()
    
    def _build_ui(self):
        """Build the dialog UI."""
        main_layout = BoxLayout(orientation='vertical', padding=10, spacing=10)
        
        # Top controls
        controls_layout = BoxLayout(orientation='horizontal', size_hint_y=0.1, spacing=10)
        
        # Board selector
        board_label = Label(text='Board:', size_hint_x=0.15)
        controls_layout.add_widget(board_label)
        
        # Build board list
        board_options = []
        rows = self.config.board_num_rows
        cols = self.config.board_num_cols
        for col in range(cols):
            for row in range(rows):
                board_options.append(f"[{col},{row}]")
        
        self.board_spinner = Spinner(
            text='Select Board',
            values=board_options,
            size_hint_x=0.3
        )
        self.board_spinner.bind(text=self._on_board_selected)
        controls_layout.add_widget(self.board_spinner)
        
        # Status label
        self.status_label = Label(
            text='Select a board to begin scanning',
            size_hint_x=0.55
        )
        controls_layout.add_widget(self.status_label)
        
        main_layout.add_widget(controls_layout)
        
        # Video preview
        preview_layout = BoxLayout(orientation='vertical', size_hint_y=0.8)
        
        self.preview_image = Image(allow_stretch=True, keep_ratio=True)
        preview_layout.add_widget(self.preview_image)
        
        # QR result label
        self.qr_result_label = Label(
            text='No QR Code Detected',
            size_hint_y=0.1,
            font_size='20sp',
            color=(1, 1, 0, 1)
        )
        preview_layout.add_widget(self.qr_result_label)
        
        main_layout.add_widget(preview_layout)
        
        # Bottom buttons
        button_layout = BoxLayout(orientation='horizontal', size_hint_y=0.1, spacing=10)
        
        quit_button = Button(text='Quit', size_hint_x=0.5)
        quit_button.bind(on_press=self._on_quit)
        button_layout.add_widget(quit_button)
        
        main_layout.add_widget(button_layout)
        
        self.content = main_layout
    
    def _on_board_selected(self, spinner, text):
        """Handle board selection.
        
        Args:
            spinner: Spinner widget
            text: Selected board text like "[0,0]"
        """
        if text == 'Select Board':
            return
        
        # Parse board coordinates
        try:
            text = text.strip('[]')
            col, row = map(int, text.split(','))
            debug_log(f"[QRDebug] Board selected: [{col},{row}]")
            self.status_label.text = f'Moving to board [{col},{row}]...'
            
            # Create async task properly
            import asyncio
            asyncio.ensure_future(self._move_to_board(col, row))
            
        except Exception as e:
            import traceback
            debug_log(f"[QRDebug] Selection error: {e}")
            debug_log(traceback.format_exc())
            self.status_label.text = f'Error: {e}'
    
    async def _move_to_board(self, col, row):
        """Move camera to board position.
        
        Args:
            col: Board column
            row: Board row
        """
        try:
            # Calculate camera position (same logic as sequence.py)
            board_x = self.config.board_x + (col * self.config.board_col_width)
            board_y = self.config.board_y + (row * self.config.board_row_height)
            
            qr_x = board_x + self.config.qr_offset_x
            qr_y = board_y + self.config.qr_offset_y
            
            # Camera offset from QR position
            camera_x = qr_x + self.config.camera_offset_x
            camera_y = qr_y + self.config.camera_offset_y
            
            # Debug: print all intermediate values
            debug_log(f"[QRDebug] Config values: board_origin=({self.config.board_x},{self.config.board_y}), qr_offset=({self.config.qr_offset_x},{self.config.qr_offset_y}), camera_offset=({self.config.camera_offset_x},{self.config.camera_offset_y})")
            debug_log(f"[QRDebug] Board [{col},{row}]: board=({board_x:.1f},{board_y:.1f}), qr=({qr_x:.1f},{qr_y:.1f}), camera=({camera_x:.1f},{camera_y:.1f})")
            self.status_label.text = f'Moving to ({camera_x:.1f}, {camera_y:.1f})...'
            
            # Move to position
            await self.motion_controller.rapid_xy_abs(camera_x, camera_y)
            await self.motion_controller.rapid_z_abs(self.config.camera_z_height)
            
            # Ensure camera is connected
            if not self.vision_controller.picamera2 and not self.vision_controller.camera:
                debug_log("[QRDebug] Camera not connected, connecting...")
                await self.vision_controller.connect()
            
            # Drain camera buffer
            if self.vision_controller:
                self.vision_controller.drain_camera_buffer()
                await asyncio.sleep(0.3)  # Stabilization time
            
            self.status_label.text = f'Scanning board [{col},{row}]...'
            
            # Start continuous scanning if not already active
            if not self.active:
                self.active = True
                self.update_event = Clock.schedule_interval(self._update_preview, 0.3)  # ~3 FPS for better performance
        
        except Exception as e:
            import traceback
            debug_log(f"[QRDebug] Move error: {e}")
            debug_log(traceback.format_exc())
            self.status_label.text = f'Move error: {e}'
    
    def _update_preview(self, dt):
        """Update video preview with QR detection.
        
        Args:
            dt: Delta time from Clock
        """
        if not self.active:
            return
        
        try:
            # Get frame using synchronous method
            import asyncio
            loop = asyncio.get_event_loop()
            
            # Capture frame synchronously for Kivy Clock callback
            if self.vision_controller.use_picamera and self.vision_controller.picamera2:
                try:
                    frame = self.vision_controller.picamera2.capture_array()
                    # picamera2 with RGB888 format returns RGB, need to convert to BGR for OpenCV
                    if len(frame.shape) == 3 and frame.shape[2] == 3:
                        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                except Exception as e:
                    debug_log(f"[QRDebug] Picamera2 capture error: {e}")
                    self.status_label.text = f'Camera error: {e}'
                    return
            elif self.vision_controller.camera:
                ret, frame = self.vision_controller.camera.read()
                if not ret:
                    debug_log(f"[QRDebug] USB camera read failed")
                    self.status_label.text = 'USB camera read failed'
                    return
            else:
                debug_log(f"[QRDebug] No camera available")
                self.status_label.text = 'No camera initialized'
                return
            
            if frame is None:
                debug_log(f"[QRDebug] Frame is None")
                self.status_label.text = 'Frame capture failed'
                return
            
            # Crop to center square and convert to grayscale (same as scan)
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
            
            # Try to detect QR code on grayscale
            try:
                qr_detector = cv2.QRCodeDetector()
                qr_data, bbox, _ = qr_detector.detectAndDecode(frame_gray)
            except Exception as e:
                debug_log(f"[QRDebug] QR detection error: {e}")
                qr_data = None
                bbox = None
            
            # Prepare display frame (convert back to color for drawing)
            display_frame = cv2.cvtColor(frame_gray, cv2.COLOR_GRAY2BGR)
            
            # Draw bounding box if QR detected
            if qr_data and bbox is not None and len(bbox) > 0:
                self.current_qr = qr_data
                self.qr_result_label.text = f'Found: {qr_data}'
                self.qr_result_label.color = (0, 1, 0, 1)  # Green
                
                try:
                    # Draw bounding box on frame - ensure proper format
                    pts = bbox.astype(int).reshape((-1, 1, 2))
                    cv2.polylines(display_frame, [pts], True, (0, 255, 0), 3)
                    
                    # Add text label - ensure tuple of ints
                    text_x = int(bbox[0][0])
                    text_y = int(bbox[0][1]) - 10
                    cv2.putText(display_frame, qr_data, (text_x, text_y),
                               cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                except Exception as e:
                    debug_log(f"[QRDebug] Drawing error: {e}")
            else:
                if self.current_qr:
                    self.qr_result_label.text = f'Last: {self.current_qr}'
                    self.qr_result_label.color = (0.5, 0.5, 0.5, 1)  # Gray
                else:
                    self.qr_result_label.text = 'No QR Code Detected'
                    self.qr_result_label.color = (1, 1, 0, 1)  # Yellow
            
            # Resize for better performance (half size)
            h, w = display_frame.shape[:2]
            display_frame = cv2.resize(display_frame, (w // 2, h // 2), interpolation=cv2.INTER_LINEAR)
            
            # Flip for Kivy display
            display_frame = cv2.flip(display_frame, 0)
            
            # Convert to texture
            self._update_texture(display_frame)
        
        except Exception as e:
            self.status_label.text = f'Preview error: {e}'
    
    def _update_texture(self, frame):
        """Update preview texture with frame.
        
        Args:
            frame: OpenCV frame (flipped for Kivy)
        """
        # Convert to RGB if needed
        if len(frame.shape) == 2:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
        elif frame.shape[2] == 3:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        else:
            frame_rgb = frame
        
        h, w = frame_rgb.shape[:2]
        
        # Create or update texture
        if self.preview_image.texture is None or \
           self.preview_image.texture.size != (w, h):
            self.preview_image.texture = Texture.create(size=(w, h), colorfmt='rgb')
        
        buf = frame_rgb.tobytes()
        self.preview_image.texture.blit_buffer(buf, colorfmt='rgb', bufferfmt='ubyte')
        self.preview_image.canvas.ask_update()
    
    def _on_quit(self, instance):
        """Handle quit button press."""
        self.stop_scanning()
        self.dismiss()
    
    def stop_scanning(self):
        """Stop continuous scanning."""
        debug_log("[QRDebug] Stopping scanning and cleaning up")
        self.active = False
        if self.update_event:
            Clock.unschedule(self._update_preview)
            self.update_event = None
        self.current_qr = None
        
        # Force texture cleanup
        if self.preview_image and self.preview_image.texture:
            self.preview_image.texture = None
        debug_log("[QRDebug] Cleanup complete")
    
    def on_dismiss(self):
        """Called when dialog is dismissed."""
        debug_log("[QRDebug] Dialog dismissed")
        self.stop_scanning()
