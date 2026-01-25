"""Camera preview with QR code detection overlay."""
from kivy.graphics.texture import Texture
from kivy.clock import Clock
import cv2
import numpy as np


class CameraPreview:
    """Manages live camera feed with QR code overlay in fixed UI widgets."""
    
    def __init__(self, vision_controller, image_widget, status_label):
        """Initialize camera preview.
        
        Args:
            vision_controller: VisionController instance (not used in new design)
            image_widget: Kivy Image widget to display processed frames
            status_label: Kivy Label widget to display status text
        """
        self.image_widget = image_widget
        self.status_label = status_label
        self.active = False
        
        # Set initial inactive state
        self._set_inactive_display()
        
    def start_preview(self):
        """Activate preview display for showing scan results."""
        print(f"[CameraPreview] Activating preview window")
        self.active = True
        # Clear inactive display
        self.image_widget.color = (1, 1, 1, 1)  # Reset to white for normal display
        self.status_label.color = (1, 1, 1, 1)  # White
        self.status_label.text = 'Ready for scanning...'
        
    def stop_preview(self):
        """Deactivate preview display."""
        print(f"[CameraPreview] Deactivating preview window")
        self.active = False
        
        # Force texture cleanup to prevent memory accumulation
        if self.image_widget.texture is not None:
            if not hasattr(self, '_black_texture') or self.image_widget.texture != self._black_texture:
                # Release the texture reference
                old_texture = self.image_widget.texture
                self.image_widget.texture = None
                # Delete texture explicitly
                del old_texture
        
        # Set inactive display
        self._set_inactive_display()
        

        print(f"[CameraPreview] Preview deactivated and textures cleaned up")
    
    def _set_inactive_display(self):
        """Set the display to show inactive state with black background and gray text."""
        self.status_label.text = 'Camera Preview'
        self.status_label.color = (0.5, 0.5, 0.5, 1)  # Gray
        self.image_widget.color = (0, 0, 0, 1)  # Black color filter
        # Reuse or create a simple black texture
        if not hasattr(self, '_black_texture') or self._black_texture is None:
            self._black_texture = Texture.create(size=(1, 1))
            self._black_texture.blit_buffer(bytes([0, 0, 0]), colorfmt='rgb', bufferfmt='ubyte')
        self.image_widget.texture = self._black_texture
    
    def show_frame(self, frame, strategy_name, qr_found=None):
        """Display a processed frame from scanning.
        
        Args:
            frame: OpenCV frame (BGR or grayscale) to display
            strategy_name: Name of the preprocessing strategy used
            qr_found: QR code data if found, None otherwise
        """
        if not self.active:
            return
            
        try:
            # Apply user-configured rotation for display
            from settings import get_settings
            settings = get_settings()
            rotation = settings.get('camera_preview_rotation', 0)
            if rotation == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            elif rotation == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif rotation == 270:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            
            # Flip frame for Kivy display
            frame_flipped = cv2.flip(frame, 0)
            
            # Update status
            if qr_found:
                self.status_label.text = f'Found: {qr_found} ({strategy_name})'
                self.status_label.color = (0, 1, 0, 1)  # Green
            else:
                self.status_label.text = f'Trying: {strategy_name}'
                self.status_label.color = (1, 1, 0, 1)  # Yellow
            
            # Convert frame to Kivy texture
            self._update_texture(frame_flipped)
                
        except Exception as e:
            print(f"[CameraPreview] Error showing frame: {e}")
    
    def _update_texture(self, frame):
        """Convert OpenCV frame to Kivy texture and display.
        
        Args:
            frame: OpenCV frame (BGR or grayscale format), already flipped for Kivy
        """
        # Handle grayscale images - convert to RGB for Kivy display
        if len(frame.shape) == 2:
            # Grayscale image - convert to RGB by repeating channel
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
        else:
            # Color image - OpenCV uses BGR, Kivy expects RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Get dimensions
        h, w = frame_rgb.shape[:2]
        
        # Reuse texture if dimensions match, otherwise create new
        if self.image_widget.texture is None or \
           self.image_widget.texture.size != (w, h):
            # Clear old texture if it exists
            if self.image_widget.texture is not None:
                # Force texture cleanup
                self.image_widget.texture = None
            # Create new texture
            self.image_widget.texture = Texture.create(size=(w, h), colorfmt='rgb')
        
        # Update texture with new data
        buf = frame_rgb.tobytes()
        self.image_widget.texture.blit_buffer(buf, colorfmt='rgb', bufferfmt='ubyte')
        self.image_widget.canvas.ask_update()
