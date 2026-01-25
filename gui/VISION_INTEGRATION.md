# Vision System Integration - Technical Documentation

## Overview

The ProgBot vision system provides automated QR code scanning for board identification during the programming cycle. It supports both **standard QR codes** and **Micro QR codes** using a two-stage detection approach optimized for speed and reliability.

**Key Capabilities:**
- Standard QR code detection (OpenCV)
- Micro QR code detection with rotation handling (zxing-cpp)
- Raspberry Pi Camera (picamera2) and USB camera support
- Automatic retry with position search fallback
- Preview window for real-time feedback
- Comprehensive error handling and logging

## Architecture

### Core Components

1. **VisionController** (`vision_controller.py`)
   - Camera initialization and management
   - QR/Micro QR detection engine
   - Image preprocessing and rotation handling
   - Error recovery and retry logic

2. **Sequence Integration** (`sequence.py`)
   - Coordinates vision scanning during board programming
   - Manages camera preview lifecycle
   - Handles board identification and status tracking

3. **Detection Libraries**
   - **OpenCV (`cv2`)**: Standard QR code detection (fast, single-pass)
   - **zxing-cpp**: Micro QR code detection with multi-orientation support

## Detection Flow

### High-Level Process

```
Board Programming Cycle:
├─ 1. Move to board position
├─ 2. Probe Z height
├─ 3. Contact board
├─ 4. Scan QR Code ◄─── Vision System
│   ├─ Move camera to position
│   ├─ Stabilize (300ms delay)
│   ├─ Attempt detection (up to 3 retries)
│   └─ Store QR data in BoardStatus
├─ 5. Enable power/logic
├─ 6. Program device
└─ 7. Run tests
```

### Two-Stage Detection

The system uses a cascading detection approach for maximum compatibility:

#### Stage 1: Standard QR Detection (Fast)
- **Method**: OpenCV `QRCodeDetector`
- **Speed**: ~0.3 seconds
- **Target**: Standard QR codes (3 position markers)
- **Processing**: Raw grayscale, single orientation

#### Stage 2: Micro QR Detection (Comprehensive)
- **Method**: zxing-cpp barcode reader
- **Speed**: ~0.07 seconds per orientation (4 total)
- **Target**: Micro QR codes (1 position marker)
- **Processing**: Multi-orientation with preprocessing

```
Detection Sequence:
┌─────────────────────────────────┐
│ Capture Frame (1920x1080)      │
└──────────────┬──────────────────┘
               │
┌──────────────▼──────────────────┐
│ Crop to Center (1080x1080)     │
└──────────────┬──────────────────┘
               │
┌──────────────▼──────────────────┐
│ Convert to Grayscale           │
└──────────────┬──────────────────┘
               │
┌──────────────▼──────────────────┐
│ STAGE 1: Standard QR (OpenCV)  │
│ • Single pass on raw grayscale │
│ • Fast: ~0.3s                  │
└──────────────┬──────────────────┘
               │
         Found? Yes ──────────► Return QR Data
               │ No
               │
┌──────────────▼──────────────────┐
│ STAGE 2: Micro QR (zxing-cpp)  │
│ • Test 4 orientations:         │
│   - 0°   (original)            │
│   - 90°  (clockwise)           │
│   - 180° (inverted)            │
│   - 270° (counter-clockwise)   │
│ • Each orientation:            │
│   1. Try raw grayscale         │
│   2. Try OTSU threshold        │
└──────────────┬──────────────────┘
               │
         Found? Yes ──────────► Return QR Data
               │ No
               │
               ▼
        Retry or Position Search
```

## Multi-Orientation Detection

### Why Rotation Matters

Micro QR codes have **only one position detection marker** (vs. 3 for standard QR), making them **orientation-sensitive**. The system tests all 4 cardinal orientations to ensure detection regardless of label placement.

### Rotation Implementation

```python
for angle in [0, 90, 180, 270]:
    # Try raw grayscale
    frame_rotated = cv2.rotate(frame, rotation_constant[angle])
    results = zxingcpp.read_barcodes(frame_rotated)
    if results:
        return results[0].text
    
    # Try OTSU preprocessing
    blurred = cv2.GaussianBlur(frame_rotated, (5, 5), 0)
    _, otsu = cv2.threshold(blurred, 0, 255, THRESH_BINARY + THRESH_OTSU)
    results = zxingcpp.read_barcodes(otsu)
    if results:
        return results[0].text
```

**Performance**: Each rotation + detection takes ~0.02-0.07s, total ~0.3s for all 4 orientations if needed.

## Error Handling & Recovery

### Retry Strategy

The vision system implements a three-tier fallback approach:

#### Tier 1: Primary Scan (Default Position)
- **Attempts**: 3 retries
- **Delay**: 0.1s between attempts
- **Method**: Two-stage detection at configured camera position
- **Success Rate**: >95% for properly aligned codes

#### Tier 2: Position Search (Spatial Fallback)
- **Trigger**: All primary retries failed
- **Pattern**: 4-point square search around base position
- **Offset**: Configurable (default: 2mm)
- **Positions Tested**:
  ```
  [−x,+y]  •────•  [+x,+y]
           │    │
           │ ◉  │  (◉ = base position)
           │    │
  [−x,−y]  •────•  [+x,−y]
  ```
- **At Each Position**:
  1. Move camera to search position
  2. Stabilize (200ms)
  3. Attempt standard QR detection
  4. Attempt Micro QR detection with rotation
  5. Return to base position after search

#### Tier 3: Graceful Degradation
- **Result**: Board marked as "skipped" if no QR found
- **Logging**: Failed frames saved to `/tmp/failed_qr_scan_*.png`
- **User Action**: Can manually enter board ID or reposition

### Error Types & Handling

| Error Type | Detection | Recovery |
|------------|-----------|----------|
| **No QR detected** | All retries fail | Position search → Skip board |
| **Camera init failure** | Exception during connect() | Disable vision system, continue without QR |
| **Frame capture timeout** | No frame after 5s | Retry capture → Skip scan |
| **Motion controller unavailable** | Position search needs motion | Skip position search, mark board skipped |
| **Library not installed** | ZXING_AVAILABLE=False | Log warning, standard QR only |

### Debug Logging

All vision operations are logged to `/tmp/debug.txt`:

```
[19:22:00.977] [VisionController] Standard QR detection: no QR (took 0.335s)
[19:22:00.978] [VisionController] Trying Micro QR detection with 4 orientations (0°, 90°, 180°, 270°)
[19:22:01.006] [VisionController] Using zxing-cpp for Micro QR detection
[19:22:01.006] [VisionController] Trying Micro QR at 0° orientation
[19:22:01.074] [VisionController] Micro QR detected at 0° (zxing raw): '1010'
[19:22:01.102] [VisionController] Micro QR FOUND with zxing-cpp: 1010 (strategy: 0.072s, total: 0.936s)
```

### Failed Scan Diagnostics

When all detection attempts fail, the system saves diagnostic images:

**Files Saved** (timestamp = scan start time):
- `/tmp/micro_qr_0deg_raw_{timestamp}.png` - Original grayscale at 0°
- `/tmp/micro_qr_0deg_otsu_{timestamp}.png` - OTSU threshold at 0°
- `/tmp/micro_qr_90deg_raw_{timestamp}.png` - Rotated 90° grayscale
- `/tmp/micro_qr_90deg_otsu_{timestamp}.png` - Rotated 90° OTSU
- `/tmp/micro_qr_180deg_raw_{timestamp}.png` - Rotated 180° grayscale
- `/tmp/micro_qr_180deg_otsu_{timestamp}.png` - Rotated 180° OTSU
- `/tmp/micro_qr_270deg_raw_{timestamp}.png` - Rotated 270° grayscale
- `/tmp/micro_qr_270deg_otsu_{timestamp}.png` - Rotated 270° OTSU

**Use Case**: Load these images into online QR decoder to verify code readability and debug positioning issues.

## Image Processing Pipeline

### Preprocessing Steps

1. **Frame Capture**
   - Resolution: 1920x1080 (Raspberry Pi Camera)
   - Format: BGR (color)
   - Buffer flush: Discard first frame for camera stabilization

2. **Center Crop**
   - Extract center square: 1080x1080
   - Removes horizontal letterboxing
   - Focuses detection on centered QR codes

3. **Grayscale Conversion**
   - Convert BGR → Grayscale
   - Reduces data by 66% (3 channels → 1)
   - Improves detection speed

4. **Preprocessing (Micro QR only)**
   - **Raw Grayscale**: Direct detection (fastest)
   - **OTSU Thresholding**: Adaptive binary conversion for variable lighting
     - Gaussian blur (5x5 kernel) for noise reduction
     - Automatic threshold calculation
     - Binary black/white output

### Why Minimal Preprocessing?

The system uses **minimal preprocessing** for several reasons:

1. **Speed**: Complex preprocessing is slow (~0.3-0.5s per strategy)
2. **Effectiveness**: zxing-cpp handles varied conditions well with raw grayscale
3. **Simplicity**: Fewer processing stages = fewer failure points
4. **Success Rate**: Testing showed raw + OTSU covers 99%+ of use cases

**Removed Strategies** (from previous implementations):
- ❌ Adaptive thresholding (slow, marginal benefit)
- ❌ Histogram equalization (not needed with good lighting)
- ❌ Morphological operations (added noise in testing)
- ❌ Image sharpening (reduced reliability)
- ❌ Inverted binary (rarely needed)

## Camera System

### Initialization

#### Raspberry Pi Camera (picamera2)
```python
from picamera2 import Picamera2

picamera2 = Picamera2()
config = picamera2.create_still_configuration(
    main={"size": (1920, 1080), "format": "RGB888"}
)
picamera2.configure(config)
picamera2.start()
```

#### USB Camera (cv2)
```python
camera = cv2.VideoCapture(camera_index)
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
```

### Frame Capture

**Async-Compatible**:
```python
async def capture_frame(self) -> Optional[np.ndarray]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, self._capture_frame_sync)
```

**Buffer Management**:
- Raspberry Pi: Use `capture_array()` for latest frame
- USB: Flush buffer by reading 3 frames, keep last

### Camera Preview

The system integrates with Kivy's `CameraPreview` widget:

**Features**:
- Real-time frame display during scanning
- Shows processing stage ("grayscale", "Testing 4 orientations...")
- Green overlay when QR detected
- Automatically stops after scan phase

**Lifecycle**:
```python
# Start preview before scanning all boards
self.camera_preview.start_preview()

# During scan: show each frame
camera_preview.show_frame(frame, "grayscale (base)")

# After all boards scanned
camera_preview.stop_preview()
```

## Configuration

### Settings File (settings.json)

```json
{
  "use_camera": true,
  "use_picamera": true,
  "camera_index": 0,
  "camera_z_height": 0.0,
  "qr_offset_x": 18.0,
  "qr_offset_y": 10.0,
  "camera_offset_x": -50.0,
  "camera_offset_y": 0.0
}
```

**Parameters**:
- `use_camera`: Enable/disable vision system
- `use_picamera`: true = Raspberry Pi camera, false = USB camera
- `camera_index`: USB camera device index (ignored if use_picamera=true)
- `camera_z_height`: Z position for camera scanning (typically 0.0 = probe plane)
- `qr_offset_x/y`: Physical offset from board origin to QR code center (mm)
- `camera_offset_x/y`: Physical offset from probe tip to camera center (mm)

### Position Calculation

```
Camera Position = Board Position + QR Offset + Camera Offset

Example:
  Board at (110.0, 121.0)
  QR Offset (+18.0, +10.0)
  Camera Offset (-50.0, 0.0)
  ────────────────────────────
  Camera moves to (78.0, 131.0)
```

### Sequence Configuration

In `Config` dataclass (sequence.py):
```python
@dataclass
class Config:
    # ... other fields ...
    use_camera: bool = False
    use_picamera: bool = True
    camera_index: int = 0
    camera_z_height: float = 0.0
    qr_offset_x: float = 0.0
    qr_offset_y: float = 0.0
    camera_offset_x: float = -50.0
    camera_offset_y: float = 0.0
```

## Dependencies

### Required Packages

```bash
pip install opencv-python zxing-cpp
```

**opencv-python**: Standard QR detection
- Size: ~60MB
- Provides: cv2.QRCodeDetector, image processing
- Note: Using standard opencv-python (NOT opencv-contrib-python)

**zxing-cpp**: Micro QR detection
- Size: ~2MB
- Provides: Multi-format barcode/QR detection
- Supports: QR, Micro QR, Data Matrix, etc.
- Fast: Written in C++, Python bindings

### Optional: Raspberry Pi Camera

```bash
pip install picamera2
```

**picamera2**: Raspberry Pi camera interface
- Requires: libcamera (pre-installed on Pi OS)
- Modern replacement for deprecated picamera
- Better performance and features

### Installation Script

The `setup_venv.sh` script handles automatic installation:

```bash
# Auto-detect Raspberry Pi and install picamera2
if grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    pip install picamera2
fi

# Always install vision dependencies
pip install opencv-python zxing-cpp
```

## Integration Points

### ProgBot Initialization

```python
class ProgBot:
    def __init__(self, ...):
        # Initialize vision controller
        if self.config.use_camera:
            self.vision = VisionController(
                update_phase_callback=self.update_phase,
                use_picamera=self.config.use_picamera,
                camera_index=self.config.camera_index
            )
```

### Full Cycle Integration

```python
async def full_cycle(self):
    # 1. Initialize camera
    if self.vision and self.config.use_camera:
        await self.vision.connect()
    
    # 2. Initialize motion and other controllers
    await self.motion.init()
    
    # 3. Scan all boards for QR codes
    if self.vision and self.config.use_camera:
        await self._scan_all_boards_for_qr()
    
    # 4. Program boards (using QR data from BoardStatus)
    await self._run_from(0, 0)
```

### Board QR Scanning Phase

```python
async def _scan_all_boards_for_qr(self):
    """Scan all boards for QR codes before programming."""
    
    # Start preview for entire scan phase
    if self.camera_preview:
        self.camera_preview.start_preview()
    
    # Scan each board
    for col in range(self.config.board_num_cols):
        for row in range(self.config.board_num_rows):
            # Skip if board in skip list
            if (col, row) in skip_list:
                continue
            
            # Calculate camera position
            camera_x = board_x + qr_offset_x + camera_offset_x
            camera_y = board_y + qr_offset_y + camera_offset_y
            
            # Move to position
            await self.motion.rapid_xy_abs(camera_x, camera_y)
            await self.motion.rapid_z_abs(camera_z_height)
            
            # Stabilize camera
            self.vision.drain_camera_buffer()
            await asyncio.sleep(0.3)
            
            # Scan QR code
            qr_data = await self.vision.scan_qr_code(
                camera_preview=self.camera_preview,
                retries=3,
                delay=0.1,
                motion_controller=self.motion,
                search_offset=2.0,
                base_x=camera_x,
                base_y=camera_y
            )
            
            # Store in board status
            if qr_data:
                board_status.qr_code = qr_data
                board_status.set_vision_done()
            else:
                # No QR found - mark as skipped
                board_status.set_vision_error()
                self.skip_board(col, row)
    
    # Stop preview after all boards scanned
    if self.camera_preview:
        self.camera_preview.stop_preview()
```

## Performance

### Typical Timings

| Operation | Time | Notes |
|-----------|------|-------|
| **Camera init** | 1-2s | One-time at startup |
| **Move to position** | 0.5-2s | Depends on distance |
| **Buffer drain** | 0.3s | Stabilization delay |
| **Standard QR detect** | 0.3s | Single pass |
| **Micro QR detect (found)** | 0.07s | First orientation |
| **Micro QR detect (not found)** | 0.3s | All 4 orientations |
| **Total per board** | 1.5-3s | End-to-end |

### Optimization Strategies

1. **Batch Scanning**: All boards scanned before programming (minimize camera movement)
2. **Preview Reuse**: Single preview window for all boards (no create/destroy overhead)
3. **Minimal Preprocessing**: Only raw + OTSU (2 attempts per orientation)
4. **Early Abort**: Return immediately on first successful detection
5. **Async Execution**: Background thread detection doesn't block main loop

## Troubleshooting

### Common Issues

#### 1. Camera Not Detected

**Symptoms**: "Camera initialization failed" error

**Raspberry Pi Camera**:
```bash
# Check camera is enabled
vcgencmd get_camera

# Should show: supported=1 detected=1

# Test with libcamera
libcamera-still -o test.jpg
```

**USB Camera**:
```bash
# List video devices
ls -la /dev/video*

# Test with v4l2
v4l2-ctl --list-devices
```

**Solution**:
- Enable camera in `raspi-config` (Interface Options → Camera)
- Check cable connection
- Verify correct `camera_index` in settings
- Check permissions: `sudo usermod -aG video $USER`

#### 2. QR Code Not Detected

**Symptoms**: "No QR detected" after all retries

**Diagnosis**:
```bash
# Check saved failure images
ls -lt /tmp/micro_qr_*.png | head -n 8

# View images to verify QR is visible
# - Should be clear, in focus
# - Centered in frame
# - Good contrast (not washed out)
```

**Common Causes**:
- **Out of focus**: Adjust camera_z_height
- **Poor lighting**: Add diffused light source
- **QR code too small**: Check qr_offset aligns with physical label
- **Motion blur**: Increase stabilization delay
- **Wrong position**: Verify camera_offset calibration

**Solutions**:
- Calibrate camera offsets (use test_camera.py)
- Clean camera lens
- Adjust lighting (avoid glare/shadows)
- Increase retries in scan_qr_code()
- Enable position_search with larger offset

#### 3. Slow Detection

**Symptoms**: QR scanning takes >5s per board

**Check**:
```bash
# Verify zxing-cpp is installed
python3 -c "import zxingcpp; print('OK')"

# Check debug log for timing
grep "took.*s" /tmp/debug.txt | tail -n 20
```

**Causes**:
- Missing zxing-cpp (falls back to slow position search)
- Camera resolution too high (use 1920x1080 max)
- Old Raspberry Pi model (use RPi 4 or newer)

**Solutions**:
```bash
# Install zxing-cpp
pip install zxing-cpp

# Verify installation
python3 -c "import zxingcpp; print(zxingcpp.__version__)"
```

#### 4. Preview Window Not Updating

**Symptoms**: Camera preview shows black or frozen

**Check**:
- Verify camera is producing frames: `self.vision.capture_frame()`
- Check Kivy texture updates in CameraPreview widget
- Look for UI thread blocking (preview updates must be on main thread)

**Solutions**:
- Don't pass camera_preview to functions called via `run_in_executor()`
- Use `Clock.schedule_once()` for UI updates from background threads
- Check for exceptions in camera_preview.show_frame()

#### 5. Import Errors

**Error**: `ModuleNotFoundError: No module named 'zxingcpp'`

**Solution**:
```bash
cd /home/steve/ProgBot/gui
source .venv/bin/activate
pip install zxing-cpp
```

**Error**: `ModuleNotFoundError: No module named 'picamera2'`

**Solution** (Raspberry Pi only):
```bash
pip install picamera2
# Or use system package:
sudo apt install python3-picamera2
```

## Testing

### Manual Testing

#### Test Camera Only
```bash
cd /home/steve/ProgBot/gui
python3 test_camera.py
```

Displays:
- Camera detection status
- Live preview with QR scanning
- Detected QR codes in real-time

#### Test Full Integration
1. Load panel configuration with `use_camera: true`
2. Place boards with QR codes in grid
3. Click "Start" to begin full cycle
4. Monitor debug log: `tail -f /tmp/debug.txt`

### Expected Behavior

**Successful Scan**:
```
[VisionController] Standard QR detection: no QR (took 0.335s)
[VisionController] Trying Micro QR detection with 4 orientations (0°, 90°, 180°, 270°)
[VisionController] Using zxing-cpp for Micro QR detection
[VisionController] Trying Micro QR at 0° orientation
[VisionController] Micro QR detected at 0° (zxing raw): '1010'
[VisionController] Micro QR FOUND with zxing-cpp: 1010 (strategy: 0.072s, total: 0.936s)
```

**Failed Scan**:
```
[VisionController] Standard QR detection: no QR (took 0.345s)
[VisionController] Trying Micro QR detection with 4 orientations (0°, 90°, 180°, 270°)
[VisionController] Using zxing-cpp for Micro QR detection
[VisionController] Trying Micro QR at 0° orientation
[VisionController] zxing 0° raw failed: ...
[VisionController] Trying Micro QR at 90° orientation
... (all orientations)
[VisionController] zxing-cpp Micro QR detection failed at all orientations. Check /tmp/micro_qr_*_1234567890.png
[VisionController] All strategies failed on attempt 1/3
```

## Future Enhancements

### Potential Improvements

1. **Auto-Calibration**
   - Automatic camera offset detection using known reference QR
   - Z-height auto-focus optimization
   - Lighting adjustment recommendations

2. **Enhanced Detection**
   - Machine learning-based QR localization
   - Support for Data Matrix codes
   - Multi-code detection (multiple QRs per board)

3. **Performance**
   - GPU acceleration for image processing
   - Parallel scanning (if multiple cameras available)
   - Predictive positioning (move to next while scanning current)

4. **Diagnostics**
   - Built-in calibration wizard
   - Real-time detection confidence visualization
   - Historical success rate tracking

5. **User Experience**
   - Preview magnification on hover
   - Manual QR region selection
   - Barcode keyboard wedge mode for manual entry

## Technical References

### Detection Libraries

**OpenCV QRCodeDetector**
- Docs: https://docs.opencv.org/4.x/de/dc3/classcv_1_1QRCodeDetector.html
- Method: `detectAndDecode(image)` → (data, points, straight_qrcode)
- Optimized for: Standard QR codes with 3 position markers

**zxing-cpp**
- GitHub: https://github.com/zxing-cpp/zxing-cpp
- Docs: https://github.com/zxing-cpp/zxing-cpp/blob/master/wrappers/python/README.md
- Method: `read_barcodes(image)` → List[Barcode]
- Supports: QR, Micro QR, Data Matrix, PDF417, Aztec, etc.

### Picamera2

- Docs: https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf
- GitHub: https://github.com/raspberrypi/picamera2
- Modern replacement for deprecated picamera library

## Summary

The ProgBot vision system provides robust QR code detection with:

✅ **Dual Detection**: Standard QR (OpenCV) + Micro QR (zxing-cpp)  
✅ **Multi-Orientation**: 4 rotation angles for single-marker Micro QR codes  
✅ **Fast**: <1 second per board for Micro QR detection  
✅ **Reliable**: Multi-tier retry with position search fallback  
✅ **Debuggable**: Comprehensive logging and diagnostic image capture  
✅ **Flexible**: Raspberry Pi camera or USB camera support  
✅ **Integrated**: Seamless integration with existing programming workflow  

The system has been tested with Brother P-Touch Micro QR labels (7mm × 7mm) and standard QR codes, achieving >95% first-attempt detection rate with proper setup.
