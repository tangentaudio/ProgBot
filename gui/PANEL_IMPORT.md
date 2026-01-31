# Panel Import from KiCad/Gerber Files

## Goal

Automatically detect panel layout parameters from PCB design files:
- Individual board dimensions (width, height)
- Board spacing (X and Y gaps)
- Grid layout (columns, rows)
- Board positions within panel

This would replace manual entry of panel settings and reduce setup errors.

**Extended goals:**
- Visual preview with measurement overlay for user confirmation
- Interactive selection of programmer pad/pogo pin locations
- Panel fiducial detection for camera alignment calibration

---

## Hardware Constraints

- **Target display: 800×480 touchscreen** on Raspberry Pi
- All dialogs/popups must fit within this resolution
- Touch-friendly UI elements (larger buttons, adequate spacing)
- Preview widget should maximize use of available space

---

## Scope Decisions

- **Initial implementation: KiKit panels only**
- KiKit has predictable structure - simplifies detection significantly
- Architecture should allow expanding to generic panels later
- Visual preview: Yes - critical for user confirmation

---

## Why KiKit-First Makes Sense

KiKit panels have consistent, well-defined structure:

1. **Grid-based layout** - KiKit uses explicit grid configuration
2. **Tab markers** - Consistent tab/mousebite patterns between boards  
3. **Frame** - Optional but common panel frame with tooling holes
4. **Annotations** - KiKit can add board identifiers, fiducials at known positions
5. **Config file** - `.kikit.json` or preset file may be present with exact parameters

### What KiKit gives us:

```
Panel structure:
┌─────────────────────────────────────────┐
│  ◎ (tooling)              ◎ (tooling)  │  ← Frame (optional)
│  ┌───────┐  ┌───────┐  ┌───────┐       │
│  │ Board │──│ Board │──│ Board │       │  ← Tabs between boards
│  │   1   │  │   2   │  │   3   │       │
│  └───────┘  └───────┘  └───────┘       │
│  ┌───────┐  ┌───────┐  ┌───────┐       │
│  │ Board │──│ Board │──│ Board │       │
│  │   4   │  │   5   │  │   6   │       │
│  └───────┘  └───────┘  └───────┘       │
│  ◎                              ◎      │
└─────────────────────────────────────────┘
```

### Simplified Detection for KiKit:

Instead of complex polygon matching, we can:

1. **Look for KiKit footprints** - KiKit adds specific footprints for tabs, frame corners
2. **Find board boundaries** - Edge.Cuts polygons that repeat
3. **Use grid symmetry** - KiKit grids are perfectly aligned by definition
4. **Parse annotations** - KiKit can add text labels identifying board positions

### Even Simpler: Parse KiKit Config

If user has the `.kikit.json` or can provide it:

```json
{
  "layout": {
    "type": "grid",
    "rows": 2,
    "cols": 3,
    "hspace": "2mm",
    "vspace": "2mm"
  },
  "source": {
    "file": "board.kicad_pcb"
  }
}
```

This gives us exact parameters without any detection!

**Detection priority:**
1. If `.kikit.json` exists alongside panel → parse it directly
2. Otherwise → detect from panel geometry (still simpler than generic)

---

## KiKit vs Raw Panel Detection

### If panel was made with KiKit:

KiKit adds metadata and uses consistent patterns:
- Tab/mousebite markers
- Panel frame with tooling holes
- Consistent spacing via its grid configuration
- Sometimes includes `.kikit.json` config file alongside

**Advantage:** If we detect KiKit patterns, we can be more confident in our detection.

### If panel was made manually or with other tools:

User may have:
- Copy/pasted board multiple times in KiCad
- Used array tool
- Manual placement with varying precision
- Different panelization tools (Panelizer, fab house tools)

**Detection approach must work regardless:**

The core algorithm should detect repeated board outlines by:
1. Finding all closed polygons on Edge.Cuts
2. Grouping by geometry (size + shape hash)
3. Finding the most common repeated shape = individual board
4. Detecting grid pattern from positions

This works whether KiKit was used or not. KiKit detection would just be a "confidence booster."

### Recommendation:

**Don't require KiKit.** Design detection to work on any panel with repeated identical boards. If we detect KiKit-specific patterns (frame, tabs), we can note it but it shouldn't be required.

---

## Input File Options

### Option 1: KiCad PCB File (.kicad_pcb)

**Pros:**
- Single file contains full board definition
- S-expression format is easy to parse (text-based, well-documented)
- Contains board outline, mounting holes, fiducials
- KiPython library exists for parsing
- Can identify individual board boundaries via Edge.Cuts layer

**Cons:**
- Requires user to have KiCad project (not always available from fab)
- Panel may be created in separate panelization tool (KiKit, etc.)
- Version differences between KiCad 5/6/7/8

**Key elements to parse:**
- `gr_line`, `gr_arc`, `gr_rect` on Edge.Cuts layer → board outlines
- `fp_text` with "JLCJLCJLCJLC" or similar → board identifiers
- `module` footprints for fiducials
- `general` section → overall board size

### Option 2: Gerber Files (.gbr, .gtl, .gbl, etc.)

**Pros:**
- Universal format - every PCB fab accepts/provides these
- Always matches what was actually manufactured
- Board outline layer (*.GKO, *-Edge_Cuts.gbr) defines boundaries

**Cons:**
- Multiple files to handle (need at least outline layer)
- RS-274X format is more complex to parse
- No semantic information (just graphics primitives)
- Need to detect repeated patterns algorithmically

**Key files:**
- Edge cuts / board outline: `*.GKO`, `*-Edge_Cuts.gbr`, `*.GM1`
- Drill file: `*.DRL`, `*.XLN` (for mounting holes)

### Option 3: KiKit Panel Config (.json, .yaml)

**Pros:**
- Explicitly defines panel layout
- Already structured as grid with spacing

**Cons:**
- Only if user used KiKit for panelization
- Not universal

---

## Detection Strategy

### For KiCad Files:

1. Parse Edge.Cuts layer to find all closed polygons
2. Group polygons by size (tolerance for manufacturing variations)
3. Largest repeated polygon = individual board outline
4. Analyze positions to detect grid pattern:
   - Sort by X coordinate → find column spacing
   - Sort by Y coordinate → find row spacing
   - Count unique X positions = columns
   - Count unique Y positions = rows

### For Gerber Files:

1. Parse board outline gerber (Edge_Cuts)
2. Convert draw commands to polygon paths
3. Find repeated rectangular regions
4. Same grid detection as above

### Pattern Detection Algorithm:

```python
def detect_grid(board_positions: List[Tuple[float, float]]) -> GridLayout:
    """
    Given list of board center positions, detect grid layout.
    
    Returns:
        GridLayout with cols, rows, x_spacing, y_spacing, origin
    """
    # Sort positions
    xs = sorted(set(p[0] for p in board_positions))
    ys = sorted(set(p[1] for p in board_positions))
    
    # Calculate spacing (median of differences for robustness)
    x_gaps = [xs[i+1] - xs[i] for i in range(len(xs)-1)]
    y_gaps = [ys[i+1] - ys[i] for i in range(len(ys)-1)]
    
    x_spacing = median(x_gaps) if x_gaps else 0
    y_spacing = median(y_gaps) if y_gaps else 0
    
    return GridLayout(
        cols=len(xs),
        rows=len(ys),
        x_spacing=x_spacing,
        y_spacing=y_spacing,
        board_width=detected_width,
        board_height=detected_height,
        origin=(min(xs), min(ys))
    )
```

---

## Libraries/Dependencies

### Python Options:

1. **kicad-skip** - Parse KiCad files
   - `pip install kicad-skip`
   - Handles .kicad_pcb, .kicad_sch

2. **kiutils** - Another KiCad parser
   - `pip install kiutils`
   - Good for KiCad 6+ files

3. **gerber-parser** / **pcb-tools**
   - `pip install pcb-tools`
   - Parse Gerber RS-274X files

4. **shapely** - Geometry operations
   - `pip install shapely`
   - Find closed polygons, calculate areas, detect patterns

### Minimal Approach:

KiCad S-expression files can be parsed with just Python stdlib:
- Tokenize as nested lists
- Extract Edge.Cuts primitives
- Basic geometry math for pattern detection

---

## UI Integration

### Import Flow:

1. User clicks "Import Panel Layout" button (in Panel Setup dialog)
2. File picker: "Select KiCad PCB file (.kicad_pcb)"
3. Parse file, detect boards
4. Show interactive preview dialog (see below)
5. User confirms or adjusts
6. Values populate panel settings

### Visual Preview Dialog:

Designed for 800×480 touchscreen - compact layout with controls on right:

```
┌────────────────────────────────────────────────────────────────┐
│  Import Panel Layout                                    [X]    │
├────────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────┐  Orientation: [⟲] [⟳]        │
│ │                              │  Side: (•)Top ( )Bottom       │
│ │   ┌───┐ ┌───┐ ┌───┐ ┌───┐   │  ─────────────────────────    │
│ │   │ 1 │ │ 2 │ │ 3 │ │ 4 │   │  Detected:                    │
│ │   └───┘ └───┘ └───┘ └───┘   │    Cols: [4]  Rows: [2]       │
│ │      ↔ 2.5mm                │    Board: 26.5 × 40.0 mm      │
│ │   ┌───┐ ┌───┐ ┌───┐ ┌───┐   │    H-Space: [2.5] mm          │
│ │   │ 5 │ │ 6 │ │ 7 │ │ 8 │   │    V-Space: [2.5] mm          │
│ │   └───┘ └───┘ └───┘ └───┘   │  ─────────────────────────    │
│ │      26.5 × 40.0 mm         │  ☑ Set origin from panel      │
│ └──────────────────────────────┘                               │
│                           [Cancel]  [Apply]                    │
└────────────────────────────────────────────────────────────────┘
```
~780×440 pixels, leaves margin for window chrome

Key features:
- **Rendered preview** of actual board geometry from KiCad
- **Measurement overlays** showing detected spacing/sizes
- **Board numbering** matching ProgBot's grid cell order
- **Editable fields** in case detection needs adjustment
- **Fiducial markers** highlighted if detected

### Orientation & Side Controls:

**Rotation:**
- Panel orientation in KiCad may not match physical placement in programmer
- Rotate buttons: 90° CW, 90° CCW (or dropdown: 0°, 90°, 180°, 270°)
- Preview updates live to show board numbering in rotated orientation
- Rotation affects which edge is "bottom-left" origin for grid numbering

**Top/Bottom Side:**
- Programmer pads may be on top or bottom copper layer
- Selecting "Bottom" mirrors the preview horizontally (like flipping a board)
- Layer visibility changes: show F.Cu vs B.Cu, F.Silkscreen vs B.Silkscreen
- Critical for correct pad selection - user sees what they'll actually be probing

```
Top Side View:          Bottom Side View (mirrored):
┌─────────────┐         ┌─────────────┐
│  1   2   3  │         │  3   2   1  │
│  4   5   6  │         │  6   5   4  │
│ [pads here] │         │ [pads here] │
└─────────────┘         └─────────────┘
    F.Cu                    B.Cu
```

**Storage:**
Panel config should store:
- `panel_rotation`: 0, 90, 180, or 270 degrees
- `programming_side`: "top" or "bottom"

These affect coordinate transforms when mapping grid positions to physical locations.

---

## Interactive Feature Selection (Future)

After basic import works, extend the preview to allow clicking to select:

### 1. Programmer Pad Locations

User clicks on the preview to mark where pogo pins should contact:

```
┌─────────────────────────────────────┐
│  Select Pogo Pin Locations          │
│                                     │
│  Click on the board image to mark   │
│  programmer contact points.         │
│                                     │
│  ┌───────────────────────────────┐  │
│  │    [PCB preview with pads]    │  │
│  │                               │  │
│  │      •──┐                     │  │
│  │      VCC│   Click a pad to    │  │
│  │      GND│   add to list       │  │
│  │      SWD│                     │  │
│  │      •──┘                     │  │
│  └───────────────────────────────┘  │
│                                     │
│  Selected pads:                     │
│    1. VCC (x=2.54, y=5.08)         │
│    2. GND (x=2.54, y=7.62)         │
│    3. SWDIO (x=2.54, y=10.16)      │
│                                     │
│  [Clear] [Done]                     │
└─────────────────────────────────────┘
```

This could:
- Snap to actual pads in the KiCad file
- Show pad names/nets from the design
- Generate probe head layout or validate against known config

### 2. Panel Fiducial Selection

User clicks to identify fiducials for camera calibration:

```
┌─────────────────────────────────────┐
│  Select Panel Fiducials             │
│                                     │
│  Click on fiducial markers.         │
│  Select 2-4 for best calibration.   │
│                                     │
│  ┌───────────────────────────────┐  │
│  │ ◎                          ◎ │  │
│  │   ┌───┐ ┌───┐ ┌───┐ ┌───┐   │  │
│  │   │   │ │   │ │   │ │   │   │  │
│  │   └───┘ └───┘ └───┘ └───┘   │  │
│  │   ┌───┐ ┌───┐ ┌───┐ ┌───┐   │  │
│  │   │   │ │   │ │   │ │   │   │  │
│  │   └───┘ └───┘ └───┘ └───┘   │  │
│  │ ◎                          ◎ │  │
│  └───────────────────────────────┘  │
│                                     │
│  Selected fiducials: 4              │
│    (0.0, 0.0), (120.0, 0.0)        │
│    (0.0, 80.0), (120.0, 80.0)      │
│                                     │
│  [Clear] [Done]                     │
└─────────────────────────────────────┘
```

Benefits:
- Camera can locate fiducials to determine panel position/rotation
- Auto-correct for panel placement variation
- Could enable "find panel" feature for automatic alignment

---

## Architecture for Extensibility

```
panel_import/
    __init__.py
    parser_base.py      # Abstract base class for file parsers
    kicad_parser.py     # KiCad .kicad_pcb parser
    gerber_parser.py    # Future: Gerber parser
    grid_detector.py    # Algorithm to detect grid from board positions
    preview_widget.py   # Kivy widget for visual preview
    
# parser_base.py
class PanelParser(ABC):
    @abstractmethod
    def parse(self, filepath: str) -> PanelData:
        """Parse file and return extracted data."""
        pass
    
    @abstractmethod
    def get_preview_image(self) -> Image:
        """Render preview image of panel."""
        pass

@dataclass
class PanelData:
    """Extracted panel information."""
    board_outlines: List[Polygon]      # Individual board shapes
    board_positions: List[Point]       # Center of each board
    panel_outline: Optional[Polygon]   # Overall panel boundary
    fiducials: List[Point]             # Detected fiducial positions
    pads: List[PadInfo]                # All pads (for pin selection)
    
    # Computed from detection
    grid: Optional[GridLayout]         # Detected grid parameters

@dataclass
class GridLayout:
    cols: int
    rows: int
    board_width: float
    board_height: float
    x_spacing: float
    y_spacing: float
    origin: Tuple[float, float]
```

This structure allows:
- Adding new parsers (Gerber, ODB++, etc.) without changing detection logic
- Sharing grid detection algorithm across all parsers
- Preview widget works with any parser's output

---

## Challenges / Edge Cases

1. **Non-rectangular boards** - Detection assumes rectangular, may need convex hull
2. **Mixed board sizes** - Panels with different board types
3. **V-groove vs tab routing** - Affects actual board boundaries
4. **Fiducials outside boards** - Panel-level vs board-level fiducials
5. **Rotation** - Boards may be rotated 90° for better nesting
6. **Partial panels** - Not all grid positions filled

---

## Implementation Phases

### Phase 1: KiCad .kicad_pcb (Simplest)
- Parse S-expression format
- Extract Edge.Cuts layer
- Detect rectangular boards
- Calculate grid from positions

### Phase 2: Gerber Outline
- Parse RS-274X format
- Convert to polygons
- Same detection algorithm

### Phase 3: Visual Preview
- Render detected layout
- Allow manual adjustment
- Integration with panel settings

### Phase 4: Advanced Detection
- Non-rectangular boards
- Rotation detection
- Confidence scoring

---

## Questions to Answer

1. ~~What file formats do you typically receive from fab houses?~~ → KiCad files available
2. ~~Do you use KiKit or another panelization tool?~~ → KiKit used, but don't require it
3. ~~How important is the visual preview vs just the numbers?~~ → Visual preview important
4. Should fiducial detection auto-populate calibration settings?
5. For pogo pin selection, should we try to match against known pad names (VCC, GND, SWDIO)?
6. Should we store the import source file path in the panel config for re-import?

---

## Implementation Phases

| Phase | Description | Effort | Priority |
|-------|-------------|--------|----------|
| **1a** | KiKit config parser (if .kikit.json available) | 0.5 day | High |
| **1b** | KiCad parser - extract Edge.Cuts + board size | 1 day | High |
| **1c** | Basic preview dialog with rotation/side controls | 1 day | High |
| **2** | Render actual PCB preview (copper, silkscreen) | 1-2 days | Medium |
| **3** | Fiducial detection and selection | 1 day | Medium |
| **4** | Pogo pin / pad selection UI | 1-2 days | Medium |
| **5** | Generic panel support (non-KiKit) | 2 days | Low |
| **6** | Gerber parser (future) | 2-3 days | Low |

**Recommendation:** Start with Phase 1 - if KiKit config exists, parsing is trivial. Even without it, KiKit panel geometry is predictable enough to detect reliably.

---

## Effort Estimate (Revised)

| Phase | Effort | Value |
|-------|--------|-------|
| Phase 1 (KiKit config + KiCad parse + preview) | 2-2.5 days | **High** - core functionality |
| Phase 2 (Rich PCB rendering) | 1-2 days | Medium - nice polish |
| Phase 3 (Fiducial selection) | 1 day | Medium - enables auto-alignment |
| Phase 4 (Pad selection) | 1-2 days | Medium - probe head setup |
| Phase 5 (Generic panels) | 2 days | Low - if KiKit doesn't cover all cases |
| Phase 6 (Gerber support) | 2-3 days | Low - backup option |

**Total for MVP (Phase 1):** ~2.5 days
**Total with fiducials + pads:** ~6 days

---

## Next Steps

1. Create `panel_import/` module structure
2. Implement KiKit JSON config parser (trivial if file exists)
3. Implement KiCad S-expression tokenizer for .kicad_pcb
4. Extract board outline from Edge.Cuts layer
5. Build preview Kivy widget with rotation/side controls
6. Integrate with Panel Setup dialog
