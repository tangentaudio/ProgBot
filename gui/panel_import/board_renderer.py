"""Render KiCad PCB to raster image for fast preview.

Parses Edge.Cuts and silkscreen layers, renders as line art.
No external dependencies beyond cairosvg and PIL.
"""

import re
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional

try:
    import cairosvg
    from PIL import Image, ImageOps
    HAS_CAIRO = True
except ImportError:
    HAS_CAIRO = False


def parse_kicad_for_render(pcb_path: str, side: str = 'top') -> dict:
    """Parse KiCad PCB file for rendering.
    
    Args:
        pcb_path: Path to .kicad_pcb file
        side: 'top' or 'bottom' - which silkscreen layer to include
    
    Returns:
        dict with 'bounds', 'edge_lines', 'silkscreen_lines', 'arcs'
    """
    silk_layer = 'F.SilkS' if side == 'top' else 'B.SilkS'
    silk_alt = 'F.Silkscreen' if side == 'top' else 'B.Silkscreen'
    
    with open(pcb_path, 'r') as f:
        content = f.read()
    
    result = {
        'edge_lines': [],       # (x1, y1, x2, y2)
        'edge_arcs': [],        # (cx, cy, radius, start_angle, end_angle)
        'silkscreen_lines': [], # (x1, y1, x2, y2, width)
        'silkscreen_arcs': [],  # (cx, cy, radius, start_angle, end_angle, width)
        'silkscreen_circles': [], # (cx, cy, radius, width)
    }
    
    # Parse gr_line (graphic lines)
    for m in re.finditer(
        r'\(gr_line\s+\(start\s+([\d.-]+)\s+([\d.-]+)\)\s*\(end\s+([\d.-]+)\s+([\d.-]+)\).*?\(layer\s+"([^"]+)"\)',
        content, re.DOTALL):
        x1, y1, x2, y2, layer = float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)), m.group(5)
        if layer == 'Edge.Cuts':
            result['edge_lines'].append((x1, y1, x2, y2))
        elif layer in (silk_layer, silk_alt):
            result['silkscreen_lines'].append((x1, y1, x2, y2, 0.15))
    
    # Parse gr_rect (graphic rectangles) - convert to 4 lines
    for m in re.finditer(
        r'\(gr_rect\s+\(start\s+([\d.-]+)\s+([\d.-]+)\)\s*\(end\s+([\d.-]+)\s+([\d.-]+)\).*?\(layer\s+"([^"]+)"\)',
        content, re.DOTALL):
        x1, y1, x2, y2, layer = float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)), m.group(5)
        lines = [(x1, y1, x2, y1), (x2, y1, x2, y2), (x2, y2, x1, y2), (x1, y2, x1, y1)]
        if layer == 'Edge.Cuts':
            result['edge_lines'].extend(lines)
        elif layer in (silk_layer, silk_alt):
            result['silkscreen_lines'].extend([(l[0], l[1], l[2], l[3], 0.15) for l in lines])
    
    # Parse gr_circle
    for m in re.finditer(
        r'\(gr_circle\s+\(center\s+([\d.-]+)\s+([\d.-]+)\)\s*\(end\s+([\d.-]+)\s+([\d.-]+)\).*?\(layer\s+"([^"]+)"\)',
        content, re.DOTALL):
        cx, cy, ex, ey, layer = float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)), m.group(5)
        radius = ((ex - cx)**2 + (ey - cy)**2) ** 0.5
        if layer in (silk_layer, silk_alt):
            result['silkscreen_circles'].append((cx, cy, radius, 0.15))
    
    # Parse fp_line (footprint lines) - these are in footprint-local coordinates
    # We need to find fp_line within footprint blocks and transform them
    # For simplicity, parse the already-transformed coordinates from the file
    for m in re.finditer(
        r'\(fp_line\s+\(start\s+([\d.-]+)\s+([\d.-]+)\)\s*\(end\s+([\d.-]+)\s+([\d.-]+)\).*?\(layer\s+"([^"]+)"\)',
        content, re.DOTALL):
        x1, y1, x2, y2, layer = float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)), m.group(5)
        if layer in (silk_layer, silk_alt):
            result['silkscreen_lines'].append((x1, y1, x2, y2, 0.12))
    
    # Parse fp_circle
    for m in re.finditer(
        r'\(fp_circle\s+\(center\s+([\d.-]+)\s+([\d.-]+)\)\s*\(end\s+([\d.-]+)\s+([\d.-]+)\).*?\(layer\s+"([^"]+)"\)',
        content, re.DOTALL):
        cx, cy, ex, ey, layer = float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)), m.group(5)
        radius = ((ex - cx)**2 + (ey - cy)**2) ** 0.5
        if layer in (silk_layer, silk_alt):
            result['silkscreen_circles'].append((cx, cy, radius, 0.12))
    
    # Calculate bounds from edge cuts
    all_x, all_y = [], []
    for line in result['edge_lines']:
        all_x.extend([line[0], line[2]])
        all_y.extend([line[1], line[3]])
    
    if all_x and all_y:
        result['bounds'] = (min(all_x), min(all_y), max(all_x), max(all_y))
    else:
        result['bounds'] = (0, 0, 100, 100)
    
    return result


def render_to_svg(pcb_data: dict, width_px: int = 800, mirror: bool = False) -> Tuple[str, Tuple[int, int]]:
    """Render parsed PCB data to SVG string.
    
    Args:
        pcb_data: Parsed data from parse_kicad_for_render
        width_px: Target width in pixels
        mirror: If True, mirror horizontally (for bottom view)
    
    Returns:
        Tuple of (svg_string, (width, height))
    """
    bounds = pcb_data['bounds']
    min_x, min_y, max_x, max_y = bounds
    
    # Margin to ensure edge strokes are fully visible (not clipped)
    # Need enough margin for the stroke width when scaled
    margin = 1.0  # mm - ensures 2px stroke is fully visible at typical scales
    min_x -= margin
    min_y -= margin
    max_x += margin
    max_y += margin
    
    pcb_width = max_x - min_x
    pcb_height = max_y - min_y
    
    scale = width_px / pcb_width if pcb_width > 0 else 1
    height_px = int(pcb_height * scale)
    
    # Colors - bright green on black
    bg_color = '#000000'
    edge_color = '#00ff00'      # Bright green for edges
    silk_color = '#00cc00'      # Slightly dimmer green for silkscreen
    
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px}" height="{height_px}">',
        f'<rect width="100%" height="100%" fill="{bg_color}"/>',
    ]
    
    def transform(x, y):
        tx = (x - min_x) * scale
        ty = (y - min_y) * scale
        if mirror:
            tx = width_px - tx
        return tx, ty
    
    # Draw edge lines (thicker for visibility when scaled down)
    for line in pcb_data['edge_lines']:
        x1, y1, x2, y2 = line
        sx1, sy1 = transform(x1, y1)
        sx2, sy2 = transform(x2, y2)
        svg_parts.append(
            f'<line x1="{sx1:.1f}" y1="{sy1:.1f}" x2="{sx2:.1f}" y2="{sy2:.1f}" '
            f'stroke="{edge_color}" stroke-width="2" stroke-linecap="round"/>'
        )
    
    # Draw silkscreen lines
    for line in pcb_data['silkscreen_lines']:
        x1, y1, x2, y2, width = line
        sx1, sy1 = transform(x1, y1)
        sx2, sy2 = transform(x2, y2)
        stroke_width = max(width * scale, 0.5)
        svg_parts.append(
            f'<line x1="{sx1:.1f}" y1="{sy1:.1f}" x2="{sx2:.1f}" y2="{sy2:.1f}" '
            f'stroke="{silk_color}" stroke-width="{stroke_width:.1f}" stroke-linecap="round"/>'
        )
    
    # Draw silkscreen circles
    for circle in pcb_data['silkscreen_circles']:
        cx, cy, radius, width = circle
        scx, scy = transform(cx, cy)
        sr = radius * scale
        stroke_width = max(width * scale, 0.5)
        svg_parts.append(
            f'<circle cx="{scx:.1f}" cy="{scy:.1f}" r="{sr:.1f}" '
            f'fill="none" stroke="{silk_color}" stroke-width="{stroke_width:.1f}"/>'
        )
    
    svg_parts.append('</svg>')
    return '\n'.join(svg_parts), (width_px, height_px)


def render_pcb_to_png(pcb_path: str, width_px: int = 800, 
                      side: str = 'top') -> Tuple[Optional[str], Tuple[int, int]]:
    """Render KiCad PCB to PNG image.
    
    Args:
        pcb_path: Path to .kicad_pcb file
        width_px: Desired image width
        side: 'top' or 'bottom'
    
    Returns:
        Tuple of (png_path, (width, height)) or (None, (0, 0)) on failure
    """
    if not HAS_CAIRO:
        return None, (0, 0)
    
    try:
        pcb_data = parse_kicad_for_render(pcb_path, side=side)
        mirror = (side == 'bottom')
        svg_str, size = render_to_svg(pcb_data, width_px, mirror=mirror)
        
        # Convert SVG to PNG
        png_bytes = cairosvg.svg2png(bytestring=svg_str.encode('utf-8'))
        
        # Save to temp file
        output_path = f'{tempfile.gettempdir()}/pcb_render_{side}.png'
        with open(output_path, 'wb') as f:
            f.write(png_bytes)
        
        return output_path, size
        
    except Exception:
        return None, (0, 0)


def get_pcb_dimensions(pcb_path: str) -> Tuple[float, float]:
    """Get PCB dimensions in mm."""
    data = parse_kicad_for_render(pcb_path)
    bounds = data['bounds']
    return bounds[2] - bounds[0], bounds[3] - bounds[1]
