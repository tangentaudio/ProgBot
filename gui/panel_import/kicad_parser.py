"""Parse KiCad PCB files for board dimensions and layout."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Point:
    """A 2D point in mm."""
    x: float
    y: float


@dataclass 
class BoardOutline:
    """Extracted board outline from KiCad PCB."""
    width_mm: float
    height_mm: float
    origin: Point  # Top-left corner
    
    # Raw edge segments for complex shapes
    edge_segments: list = field(default_factory=list)


@dataclass
class PanelInfo:
    """Information about a panelized KiCad PCB."""
    # Overall panel dimensions
    panel_width_mm: float
    panel_height_mm: float
    
    # Individual board dimensions (estimated)
    board_width_mm: Optional[float] = None
    board_height_mm: Optional[float] = None
    
    # Detected grid (if detectable from repeated patterns)
    detected_cols: Optional[int] = None
    detected_rows: Optional[int] = None
    detected_hspace_mm: Optional[float] = None
    detected_vspace_mm: Optional[float] = None
    
    # Component positions that might indicate boards
    board_origins: list = field(default_factory=list)


class SExpressionParser:
    """Simple S-expression parser for KiCad files."""
    
    def __init__(self, text: str):
        self.text = text
        self.pos = 0
    
    def parse(self):
        """Parse the entire S-expression."""
        self._skip_whitespace()
        return self._parse_expr()
    
    def _skip_whitespace(self):
        """Skip whitespace and comments."""
        while self.pos < len(self.text):
            if self.text[self.pos].isspace():
                self.pos += 1
            else:
                break
    
    def _parse_expr(self):
        """Parse a single expression (atom or list)."""
        self._skip_whitespace()
        
        if self.pos >= len(self.text):
            return None
        
        if self.text[self.pos] == '(':
            return self._parse_list()
        elif self.text[self.pos] == '"':
            return self._parse_string()
        else:
            return self._parse_atom()
    
    def _parse_list(self):
        """Parse a list: (item item ...)"""
        assert self.text[self.pos] == '('
        self.pos += 1
        
        result = []
        while True:
            self._skip_whitespace()
            if self.pos >= len(self.text):
                break
            if self.text[self.pos] == ')':
                self.pos += 1
                break
            
            item = self._parse_expr()
            if item is not None:
                result.append(item)
        
        return result
    
    def _parse_string(self):
        """Parse a quoted string."""
        assert self.text[self.pos] == '"'
        self.pos += 1
        
        result = []
        while self.pos < len(self.text) and self.text[self.pos] != '"':
            if self.text[self.pos] == '\\' and self.pos + 1 < len(self.text):
                self.pos += 1
            result.append(self.text[self.pos])
            self.pos += 1
        
        if self.pos < len(self.text):
            self.pos += 1  # Skip closing quote
        
        return ''.join(result)
    
    def _parse_atom(self):
        """Parse an atom (symbol or number)."""
        result = []
        while self.pos < len(self.text):
            c = self.text[self.pos]
            if c.isspace() or c in '()':
                break
            result.append(c)
            self.pos += 1
        
        atom = ''.join(result)
        
        # Try to convert to number
        try:
            return int(atom)
        except ValueError:
            try:
                return float(atom)
            except ValueError:
                return atom


def find_elements(expr, name: str) -> list:
    """Recursively find all elements with given name in S-expression."""
    results = []
    
    if isinstance(expr, list) and len(expr) > 0:
        if expr[0] == name:
            results.append(expr)
        for item in expr:
            results.extend(find_elements(item, name))
    
    return results


def get_element_value(expr, name: str):
    """Get the value following a named element like (name value)."""
    if isinstance(expr, list):
        for i, item in enumerate(expr):
            if item == name and i + 1 < len(expr):
                return expr[i + 1]
            if isinstance(item, list) and len(item) >= 2 and item[0] == name:
                return item[1]
    return None


def extract_board_outline(pcb_path: str | Path) -> BoardOutline:
    """Extract the board outline from Edge.Cuts layer.
    
    Args:
        pcb_path: Path to .kicad_pcb file
        
    Returns:
        BoardOutline with dimensions and origin
    """
    pcb_path = Path(pcb_path)
    
    if not pcb_path.exists():
        raise FileNotFoundError(f"KiCad PCB not found: {pcb_path}")
    
    with open(pcb_path, 'r') as f:
        content = f.read()
    
    parser = SExpressionParser(content)
    pcb = parser.parse()
    
    # Find all graphic elements on Edge.Cuts layer
    edge_points = []
    edge_segments = []
    
    # Find gr_line elements (lines on Edge.Cuts)
    for line in find_elements(pcb, 'gr_line'):
        layer = get_element_value(line, 'layer')
        if layer == 'Edge.Cuts':
            start = None
            end = None
            for item in line:
                if isinstance(item, list):
                    if item[0] == 'start' and len(item) >= 3:
                        start = Point(float(item[1]), float(item[2]))
                        edge_points.append(start)
                    elif item[0] == 'end' and len(item) >= 3:
                        end = Point(float(item[1]), float(item[2]))
                        edge_points.append(end)
            if start and end:
                edge_segments.append(('line', start, end))
    
    # Find gr_rect elements (rectangles on Edge.Cuts)  
    for rect in find_elements(pcb, 'gr_rect'):
        layer = get_element_value(rect, 'layer')
        if layer == 'Edge.Cuts':
            start = None
            end = None
            for item in rect:
                if isinstance(item, list):
                    if item[0] == 'start' and len(item) >= 3:
                        start = Point(float(item[1]), float(item[2]))
                        edge_points.append(start)
                    elif item[0] == 'end' and len(item) >= 3:
                        end = Point(float(item[1]), float(item[2]))
                        edge_points.append(end)
            if start and end:
                edge_segments.append(('rect', start, end))
    
    # Find gr_arc elements (arcs on Edge.Cuts)
    for arc in find_elements(pcb, 'gr_arc'):
        layer = get_element_value(arc, 'layer')
        if layer == 'Edge.Cuts':
            for item in arc:
                if isinstance(item, list):
                    if item[0] in ('start', 'end', 'mid') and len(item) >= 3:
                        edge_points.append(Point(float(item[1]), float(item[2])))
    
    if not edge_points:
        raise ValueError(f"No Edge.Cuts geometry found in {pcb_path}")
    
    # Calculate bounding box
    min_x = min(p.x for p in edge_points)
    max_x = max(p.x for p in edge_points)
    min_y = min(p.y for p in edge_points)
    max_y = max(p.y for p in edge_points)
    
    return BoardOutline(
        width_mm=max_x - min_x,
        height_mm=max_y - min_y,
        origin=Point(min_x, min_y),
        edge_segments=edge_segments,
    )


@dataclass
class GridPitch:
    """Detected grid pitch from panelized PCB."""
    x_pitch_mm: float  # Center-to-center spacing in X (between columns)
    y_pitch_mm: float  # Center-to-center spacing in Y (between rows)
    cols: int          # Number of columns detected
    rows: int          # Number of rows detected
    confidence: float  # 0-1, how consistent the spacing is


def detect_board_pitch(pcb_path: str | Path, expected_cols: int, expected_rows: int) -> Optional[GridPitch]:
    """Detect board pitch by finding repeated footprint patterns.
    
    Looks for footprints that appear exactly (cols * rows) times and
    validates that they form a regular grid pattern.
    
    Args:
        pcb_path: Path to panelized .kicad_pcb file
        expected_cols: Expected number of columns from KiKit config
        expected_rows: Expected number of rows from KiKit config
        
    Returns:
        GridPitch if a valid pattern is found, None otherwise
    """
    from collections import Counter
    
    pcb_path = Path(pcb_path)
    with open(pcb_path, 'r') as f:
        content = f.read()
    
    expected_count = expected_cols * expected_rows
    
    # Find all footprint positions
    footprints = []
    for m in re.finditer(
        r'\(footprint\s+"([^"]+)".*?\(at\s+([\d.-]+)\s+([\d.-]+)',
        content, re.DOTALL
    ):
        name = m.group(1)
        x, y = float(m.group(2)), float(m.group(3))
        footprints.append((name, x, y))
    
    # Count footprint types
    fp_counts = Counter(fp[0] for fp in footprints)
    
    # Find candidates: footprints appearing exactly expected_count times
    candidates = [name for name, count in fp_counts.items() if count == expected_count]
    
    if not candidates:
        return None
    
    best_result = None
    best_confidence = 0.0
    
    for candidate in candidates:
        positions = [(x, y) for name, x, y in footprints if name == candidate]
        result = _analyze_grid_pattern(positions, expected_cols, expected_rows)
        if result and result.confidence > best_confidence:
            best_result = result
            best_confidence = result.confidence
    
    return best_result


def _analyze_grid_pattern(positions: list, expected_cols: int, expected_rows: int) -> Optional[GridPitch]:
    """Analyze if positions form a regular grid and extract pitch.
    
    Args:
        positions: List of (x, y) tuples
        expected_cols: Expected columns
        expected_rows: Expected rows
        
    Returns:
        GridPitch if valid pattern, None otherwise
    """
    if len(positions) != expected_cols * expected_rows:
        return None
    
    # Cluster X coordinates (tolerance for minor variations)
    tolerance = 0.5  # mm
    xs = sorted(p[0] for p in positions)
    ys = sorted(p[1] for p in positions)
    
    x_groups = _cluster_values(xs, tolerance)
    y_groups = _cluster_values(ys, tolerance)
    
    # Check we got the expected number of groups
    if len(x_groups) != expected_cols or len(y_groups) != expected_rows:
        return None
    
    # Calculate pitch from group centers
    x_centers = sorted(sum(g) / len(g) for g in x_groups)
    y_centers = sorted(sum(g) / len(g) for g in y_groups)
    
    if len(x_centers) < 2 or len(y_centers) < 2:
        # Single column or row - can't calculate pitch in that direction
        x_pitch = 0.0 if len(x_centers) < 2 else x_centers[1] - x_centers[0]
        y_pitch = 0.0 if len(y_centers) < 2 else y_centers[1] - y_centers[0]
        return GridPitch(
            x_pitch_mm=x_pitch,
            y_pitch_mm=y_pitch,
            cols=expected_cols,
            rows=expected_rows,
            confidence=0.8  # Lower confidence for single row/col
        )
    
    # Calculate all adjacent pitches
    x_pitches = [x_centers[i+1] - x_centers[i] for i in range(len(x_centers)-1)]
    y_pitches = [y_centers[i+1] - y_centers[i] for i in range(len(y_centers)-1)]
    
    # Check consistency (all pitches should be similar)
    x_pitch = sum(x_pitches) / len(x_pitches)
    y_pitch = sum(y_pitches) / len(y_pitches)
    
    x_variance = max(abs(p - x_pitch) for p in x_pitches) if x_pitches else 0
    y_variance = max(abs(p - y_pitch) for p in y_pitches) if y_pitches else 0
    
    # Confidence based on consistency (lower variance = higher confidence)
    max_acceptable_variance = 0.5  # mm
    x_conf = max(0, 1 - x_variance / max_acceptable_variance) if x_pitches else 1.0
    y_conf = max(0, 1 - y_variance / max_acceptable_variance) if y_pitches else 1.0
    confidence = (x_conf + y_conf) / 2
    
    if confidence < 0.5:
        return None
    
    return GridPitch(
        x_pitch_mm=round(x_pitch, 2),
        y_pitch_mm=round(y_pitch, 2),
        cols=expected_cols,
        rows=expected_rows,
        confidence=confidence
    )


def _cluster_values(values: list, tolerance: float) -> list:
    """Cluster nearby values together.
    
    Args:
        values: Sorted list of float values
        tolerance: Max distance to consider same cluster
        
    Returns:
        List of clusters, each cluster is a list of values
    """
    if not values:
        return []
    
    clusters = [[values[0]]]
    for v in values[1:]:
        if v - clusters[-1][-1] <= tolerance:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return clusters


def parse_kicad_pcb(pcb_path: str | Path) -> PanelInfo:
    """Parse a KiCad PCB file for panel information.
    
    This attempts to detect:
    - Overall panel dimensions from Edge.Cuts
    - Repeated board patterns (if panelized)
    - Individual board dimensions
    
    Args:
        pcb_path: Path to .kicad_pcb file
        
    Returns:
        PanelInfo with extracted dimensions
    """
    outline = extract_board_outline(pcb_path)
    
    return PanelInfo(
        panel_width_mm=outline.width_mm,
        panel_height_mm=outline.height_mm,
    )
