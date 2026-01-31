"""Panel preview widget - raster rendering with loading indicator."""

import io
import threading
from kivy.uix.widget import Widget
from kivy.uix.label import Label
from kivy.graphics import Color, Rectangle, PushMatrix, PopMatrix, Rotate, Translate, Line
from kivy.properties import (
    NumericProperty, ObjectProperty, 
    BooleanProperty, StringProperty
)
from kivy.core.image import Image as CoreImage
from kivy.clock import Clock
from dataclasses import dataclass

# Import raster renderer
try:
    from board_renderer import render_pcb_to_png, HAS_CAIRO
    HAS_RENDERER = HAS_CAIRO
except ImportError:
    HAS_RENDERER = False
    render_pcb_to_png = None


@dataclass
class PanelData:
    """Data for panel preview rendering.
    
    Uses ProgBot .panel file nomenclature:
    - cols/rows: board_cols/board_rows in .panel file
    - col_width_mm: center-to-center X spacing between columns
    - row_height_mm: center-to-center Y spacing between rows
    """
    cols: int
    rows: int
    col_width_mm: float  # Center-to-center X spacing (col_width in .panel)
    row_height_mm: float  # Center-to-center Y spacing (row_height in .panel)
    
    @property
    def total_boards(self) -> int:
        return self.cols * self.rows


class PanelPreviewWidget(Widget):
    """Widget that renders a panel preview with loading indicator."""
    
    panel_data = ObjectProperty(None, allownone=True)
    rotation = NumericProperty(0)  # 0, 90, 180, 270
    flipped = BooleanProperty(False)  # Show bottom side
    pcb_file_path = StringProperty('')
    loading = BooleanProperty(False)  # True while rendering
    show_board_numbers = BooleanProperty(False)  # Show numbered grid overlay
    
    # Internal - separate textures for top and bottom
    _top_texture = None
    _bottom_texture = None
    _texture_size = (0, 0)
    _loading_angle = 0
    _loading_event = None
    _board_labels = []  # Labels for board numbers
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(
            pos=self._trigger_redraw,
            size=self._trigger_redraw,
            rotation=self._trigger_redraw,
            flipped=self._trigger_redraw,
            pcb_file_path=self._on_pcb_file_changed,
            panel_data=self._trigger_redraw,
            loading=self._on_loading_changed,
            show_board_numbers=self._trigger_redraw,
        )
    
    def _on_loading_changed(self, *args):
        """Start/stop loading animation."""
        if self.loading:
            self._loading_angle = 0
            self._loading_event = Clock.schedule_interval(self._animate_loading, 1/30)
        else:
            if self._loading_event:
                self._loading_event.cancel()
                self._loading_event = None
        self._trigger_redraw()
    
    def _animate_loading(self, dt):
        """Animate loading spinner."""
        self._loading_angle = (self._loading_angle + 10) % 360
        self._trigger_redraw()
    
    def _on_pcb_file_changed(self, *args):
        """Render both sides of PCB when file changes (in background thread)."""
        self._top_texture = None
        self._bottom_texture = None
        
        if not self.pcb_file_path or not HAS_RENDERER or not render_pcb_to_png:
            self._trigger_redraw()
            return
        
        # Start loading indicator
        self.loading = True
        
        # Render in background thread
        def render_thread():
            try:
                import time
                start = time.perf_counter()
                
                # Render top side
                top_path, size = render_pcb_to_png(self.pcb_file_path, width_px=800, side='top')
                
                # Render bottom side
                bottom_path, _ = render_pcb_to_png(self.pcb_file_path, width_px=800, side='bottom')
                
                elapsed = (time.perf_counter() - start) * 1000
                
                # Update UI on main thread - create textures here
                def update_ui(dt):
                    try:
                        if top_path:
                            with open(top_path, 'rb') as f:
                                self._top_texture = CoreImage(io.BytesIO(f.read()), ext='png').texture
                            self._texture_size = size
                        
                        if bottom_path:
                            with open(bottom_path, 'rb') as f:
                                self._bottom_texture = CoreImage(io.BytesIO(f.read()), ext='png').texture
                        
                    except Exception:
                        pass  # Texture creation failed
                    finally:
                        self.loading = False
                
                Clock.schedule_once(update_ui, 0)
                
            except Exception:
                Clock.schedule_once(lambda dt: setattr(self, 'loading', False), 0)
        
        thread = threading.Thread(target=render_thread, daemon=True)
        thread.start()
    
    def _trigger_redraw(self, *args):
        self.canvas.clear()
        self._draw_panel()
    
    def _draw_panel(self):
        """Draw the panel preview."""
        # Show loading spinner if rendering
        if self.loading:
            with self.canvas:
                Color(0.15, 0.15, 0.15, 1)
                Rectangle(pos=self.pos, size=self.size)
                
                # Draw loading spinner
                cx = self.x + self.width / 2
                cy = self.y + self.height / 2
                radius = 30
                
                # Spinner arc
                import math
                Color(0, 0.8, 0, 1)  # Green
                PushMatrix()
                Translate(cx, cy)
                Rotate(angle=self._loading_angle, origin=(0, 0))
                
                # Draw arc segments
                for i in range(8):
                    angle = i * 45 * math.pi / 180
                    alpha = 0.3 + 0.7 * (i / 8)
                    Color(0, 0.8, 0, alpha)
                    x1 = radius * math.cos(angle)
                    y1 = radius * math.sin(angle)
                    x2 = radius * math.cos(angle + 0.3)
                    y2 = radius * math.sin(angle + 0.3)
                    Line(points=[x1, y1, x2, y2], width=3, cap='round')
                
                PopMatrix()
                
                # Loading text
                Color(0.6, 0.6, 0.6, 1)
            return
        
        # Select texture based on flip state
        tex = self._bottom_texture if self.flipped else self._top_texture
        
        if not tex:
            # Show placeholder
            with self.canvas:
                Color(0.15, 0.15, 0.15, 1)
                Rectangle(pos=self.pos, size=self.size)
                Color(0.4, 0.4, 0.4, 1)
                Line(rectangle=(self.x + 10, self.y + 10, self.width - 20, self.height - 20), width=1)
            return
        
        tex_w, tex_h = self._texture_size
        
        # Calculate effective size based on rotation
        if self.rotation in (90, 270):
            eff_w, eff_h = tex_h, tex_w
        else:
            eff_w, eff_h = tex_w, tex_h
        
        # Scale to fit widget with padding
        padding = 20
        available_w = self.width - 2 * padding
        available_h = self.height - 2 * padding
        
        if available_w <= 0 or available_h <= 0:
            return
        
        scale = min(available_w / eff_w, available_h / eff_h)
        
        # Final display size
        disp_w = eff_w * scale
        disp_h = eff_h * scale
        
        # Center in widget
        cx = self.x + self.width / 2
        cy = self.y + self.height / 2
        
        with self.canvas:
            # Background
            Color(0.15, 0.15, 0.15, 1)
            bg_x = cx - disp_w / 2
            bg_y = cy - disp_h / 2
            Rectangle(pos=(bg_x, bg_y), size=(disp_w, disp_h))
            
            # Apply transforms
            PushMatrix()
            Translate(cx, cy)
            Rotate(angle=-self.rotation, origin=(0, 0))
            
            # Draw texture
            Color(1, 1, 1, 1)
            rect_w = tex_w * scale
            rect_h = tex_h * scale
            Rectangle(
                texture=tex,
                pos=(-rect_w / 2, -rect_h / 2),
                size=(rect_w, rect_h)
            )
            
            PopMatrix()
            
            # Draw board numbers if enabled
            if self.show_board_numbers and self.panel_data:
                self._draw_board_numbers(bg_x, bg_y, disp_w, disp_h)
    
    def _draw_board_numbers(self, bg_x, bg_y, disp_w, disp_h):
        """Draw numbered board positions on the preview.
        
        Board numbering follows ProgBot convention:
        - Start at 0 in lower-left corner (in display coordinates)
        - Go up the column (increasing row = higher on screen)
        - Then to bottom of next column to the right
        """
        pd = self.panel_data
        if not pd or pd.cols < 1 or pd.rows < 1:
            return
        
        # Clear old labels
        for lbl in self._board_labels:
            if lbl.parent:
                self.remove_widget(lbl)
        self._board_labels = []
        
        # Calculate board cell size in display coordinates
        cell_w = disp_w / pd.cols
        cell_h = disp_h / pd.rows
        
        # Draw board numbers - column first, bottom to top
        # In Kivy: y=0 is at bottom, y increases upward
        board_num = 0
        for col in range(pd.cols):
            for row in range(pd.rows):
                # Board center in display coordinates
                # row 0 is at bottom, row (rows-1) is at top
                dx = bg_x + (col + 0.5) * cell_w
                dy = bg_y + (row + 0.5) * cell_h
                
                # Draw number label background
                with self.canvas:
                    Color(0, 0, 0, 0.6)
                    rect_size = 20
                    Rectangle(pos=(dx - rect_size/2, dy - rect_size/2), size=(rect_size, rect_size))
                
                # Create label widget for the number
                lbl = Label(
                    text=str(board_num),
                    pos=(dx - 15, dy - 10),
                    size=(30, 20),
                    font_size='11sp',
                    color=(1, 1, 0, 1),  # Yellow
                )
                self.add_widget(lbl)
                self._board_labels.append(lbl)
                
                board_num += 1
    
    def copy_textures_from(self, other_preview):
        """Copy rendered textures from another preview widget."""
        self._top_texture = other_preview._top_texture
        self._bottom_texture = other_preview._bottom_texture
        self._texture_size = other_preview._texture_size
        self._trigger_redraw()
    
    def rotate_cw(self):
        self.rotation = (self.rotation + 90) % 360
    
    def rotate_ccw(self):
        self.rotation = (self.rotation - 90) % 360
    
    def toggle_flip(self):
        self.flipped = not self.flipped
