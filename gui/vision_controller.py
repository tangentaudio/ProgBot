"""Vision controller for camera operations and QR code scanning."""
import asyncio
import cv2
import numpy as np
import time
from typing import Optional, Tuple
import os

# Import camera process for GIL isolation
from camera_process import CameraProcess

# Try to import zxing-cpp for Micro QR support (still used in main process for some operations)
ZXING_AVAILABLE = False
try:
    import zxingcpp
    ZXING_AVAILABLE = True
    print("[VisionController] zxing-cpp available (excellent Micro QR support)")
except ImportError:
    print("[VisionController] Note: zxing-cpp not available. Install with: pip install zxing-cpp")


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


class VisionController:
    """Handles camera operations and QR code scanning for board identification."""
    
    def __init__(self, update_phase_callback, use_picamera=True, camera_index=0):
        """Initialize vision controller.
        
        Args:
            update_phase_callback: Function to call to update phase display
            use_picamera: If True, use Raspberry Pi camera, else use USB/webcam
            camera_index: Camera index for USB camera (ignored if use_picamera=True)
        """
        self.update_phase = update_phase_callback
        self.use_picamera = use_picamera
        self.camera_index = camera_index
        self.camera = None
        self.qr_detector = None
        self.picamera2 = None
        self._picamera_started = False
        self._connecting = False
        self._last_capture_time = 0  # Track last capture for fast-path optimization
        
        # Camera process for GIL isolation
        self.camera_process = None
    
    async def connect(self):
        """Initialize camera connection using separate process for GIL isolation."""
        # Check if already connecting or connected
        if self._connecting:
            debug_log("[VisionController.connect] Already connecting/connected, skipping")
            print("[VisionController.connect] Already connecting, skipping...")
            return
        
        self._connecting = True
        try:
            import threading, gc
            debug_log(f"[VisionController.connect] Starting... use_picamera={self.use_picamera}")
            debug_log(f"[VisionController.connect] Active threads: {threading.active_count()}, GC tracked objects: {len(gc.get_objects())}")
            print(f"[VisionController] Active threads: {threading.active_count()}")
            print(f"[VisionController.connect] Starting camera in separate process...")
            
            # If camera process exists, stop it directly (don't call disconnect() - deadlock risk)
            if self.camera_process is not None:
                print("[VisionController.connect] Camera process already exists, stopping it...")
                debug_log("[VisionController.connect] Camera process already exists, stopping it")
                try:
                    self.camera_process.stop()
                except:
                    pass
                self.camera_process = None
            
            # Delay before starting camera to let hardware fully release from previous process
            # Previous process was force-killed, need time for hardware to reset
            debug_log("[VisionController.connect] Waiting for camera hardware to release...")
            await asyncio.sleep(0.5)
            
            # Create and start camera process
            self.camera_process = CameraProcess(
                use_picamera=self.use_picamera,
                camera_index=self.camera_index
            )
            self.camera_process.start()
            
            # Give process time to start
            await asyncio.sleep(0.1)
            
            # Initialize camera in the subprocess
            debug_log("[VisionController.connect] Sending init command to camera process...")
            print("[VisionController.connect] Initializing camera in subprocess...")
            
            # Send init command (non-blocking)
            self.camera_process.command_queue.put(('init', ()), timeout=1.0)
            
            # Poll result queue without blocking event loop
            result = None
            timeout = 10.0
            start_time = time.time()
            
            while (time.time() - start_time) < timeout:
                try:
                    result = self.camera_process.result_queue.get(block=True, timeout=0.05)
                    break
                except:
                    await asyncio.sleep(0.01)
            
            if not result:
                raise RuntimeError("Camera initialization timed out")
            
            if result and result.get('success'):
                camera_type = result.get('camera_type', 'unknown')
                debug_log(f"[VisionController.connect] Camera initialized: {camera_type}")
                print(f"[VisionController] Camera initialized in subprocess ({camera_type})")
                print("[VisionController] QR detection: Standard QR + Micro QR")
                self._picamera_started = True
            else:
                error = result.get('error', 'Unknown error') if result else 'No response'
                # Cleanup on failure
                if self.camera_process:
                    self.camera_process.stop()
                    self.camera_process = None
                raise RuntimeError(f"Camera initialization failed: {error}")
        except Exception as e:
            self._connecting = False
            debug_log(f"[VisionController.connect] ERROR: {e}")
            print(f"[VisionController.connect] ERROR: {e}")
            raise
        finally:
            self._connecting = False
    
    async def disconnect(self):
        """Disconnect and cleanup camera resources."""
        if not self._connecting and self.camera_process is None:
            debug_log("[VisionController.disconnect] Nothing to disconnect")
            return
        
        self._connecting = False
        try:
            debug_log("[VisionController.disconnect] Starting cleanup...")
            print("[VisionController.disconnect] Starting cleanup...")
            if self.camera_process:
                debug_log("[VisionController.disconnect] Stopping camera process...")
                
                # Try to send cleanup command with very short timeout (expected to fail/timeout)
                loop = asyncio.get_event_loop()
                try:
                    cleanup_task = loop.run_in_executor(
                        None,
                        self.camera_process.send_command,
                        'cleanup',
                        0.3  # very short timeout for cleanup command
                    )
                    result = await asyncio.wait_for(cleanup_task, timeout=0.5)
                    if result and result.get('success'):
                        debug_log("[VisionController.disconnect] Camera cleanup successful")
                except asyncio.TimeoutError:
                    debug_log("[VisionController.disconnect] Cleanup command timed out (expected)")
                except Exception as e:
                    debug_log(f"[VisionController.disconnect] Cleanup error: {e}")
                
                # Stop the camera process - should be fast with instant signal handler
                try:
                    stop_task = loop.run_in_executor(None, self.camera_process.stop)
                    await asyncio.wait_for(stop_task, timeout=0.7)
                    debug_log("[VisionController.disconnect] Camera process stopped cleanly")
                except asyncio.TimeoutError:
                    debug_log("[VisionController.disconnect] Stop timeout, force killing")
                    # Force kill
                    if self.camera_process and self.camera_process.process:
                        try:
                            self.camera_process.process.kill()
                            self.camera_process.process.join(timeout=0.3)
                            debug_log("[VisionController.disconnect] Process force killed")
                        except:
                            pass
                
                self.camera_process = None
                self._picamera_started = False
                debug_log("[VisionController.disconnect] Camera process stopped")
            
            # Legacy cleanup (in case old camera objects exist)
        except Exception as e:
            debug_log(f"[VisionController.disconnect] ERROR: {e}")
            print(f"[VisionController.disconnect] ERROR: {e}")
            if self.picamera2:
                debug_log("[VisionController.disconnect] Cleaning up orphaned picamera2 object...")
                try:
                    self.picamera2.close()
                except:
                    pass
                self.picamera2 = None
                self._picamera_started = False
            
            if self.camera:
                debug_log("[VisionController.disconnect] Cleaning up orphaned USB camera object...")
                try:
                    self.camera.release()
                except:
                    pass
                self.camera = None
            
            # Close any OpenCV windows that might be open
            try:
                cv2.destroyAllWindows()
                debug_log("[VisionController.disconnect] Closed any OpenCV windows")
            except Exception as e:
                debug_log(f"[VisionController.disconnect] Error closing OpenCV windows: {e}")
            
            # Skip garbage collection - it causes stop-the-world pause that breaks serial connections!
            # gc.collect() pauses ALL threads including serial reader, making motion controller
            # think connection is dead and reconnect (causing slow first read)
            # Python's automatic GC will clean up when needed
            debug_log("[VisionController.disconnect] Skipping gc.collect() to avoid breaking serial")
            
            debug_log("[VisionController.disconnect] Camera cleanup complete")
            print("[VisionController.disconnect] Camera cleanup complete")
    
    def _gc_collect(self):
        import gc
        gc.collect()
    
    async def _init_picamera(self):
        """Initialize Raspberry Pi camera using picamera2."""
        try:
            from picamera2 import Picamera2
            
            debug_log("[VisionController] _init_picamera starting...")
            print("[VisionController] _init_picamera starting...")
            
            # Run camera initialization directly (not in executor)
            # picamera2 has its own threading and doesn't play well with executors
            print("[VisionController] Calling Picamera2.global_camera_info()...")
            cameras = Picamera2.global_camera_info()
            debug_log(f"[VisionController] Found {len(cameras) if cameras else 0} cameras")
            print(f"[VisionController] Found {len(cameras) if cameras else 0} cameras")
            
            if not cameras or len(cameras) == 0:
                raise RuntimeError("No Raspberry Pi cameras detected")
            
            # Small delay to ensure previous instances are cleaned up
            await asyncio.sleep(0.1)
            
            print("[VisionController] Creating Picamera2 instance...")
            self.picamera2 = Picamera2()
            
            print("[VisionController] Configuring camera for still/on-demand mode...")
            # Reduced resolution to 640x480 to minimize GIL contention
            # Frame size: 640x480x3 = 921,600 bytes (~0.9MB vs 6MB at 1920x1080)
            config = self.picamera2.create_still_configuration(
                main={"format": "RGB888", "size": (640, 480)}
            )
            self.picamera2.configure(config)
            debug_log("[VisionController] Camera configured for still/on-demand capture at 640x480")
            
            print("[VisionController] Starting camera in still mode...")
            self.picamera2.start()
            # Still mode: camera is ready but only captures on explicit request
            # No continuous frame generation = no background GIL contention
            
            debug_log("[VisionController] Raspberry Pi camera initialized in still/on-demand mode")
            print("[VisionController] Raspberry Pi camera initialized in still/on-demand mode")
            self._picamera_started = True
            
        except ImportError:
            print("[VisionController] picamera2 not available, falling back to USB camera")
            self.use_picamera = False
            await self._init_usb_camera()
        except Exception as e:
            print(f"[VisionController] Raspberry Pi camera failed: {e}")
            import traceback
            traceback.print_exc()
            print("[VisionController] Falling back to USB camera")
            # Clean up the failed picamera2 object
            if self.picamera2:
                try:
                    self.picamera2.close()
                except:
                    pass
                self.picamera2 = None
            self.use_picamera = False
            await self._init_usb_camera()
    
    async def _init_usb_camera(self):
        """Initialize USB/webcam using OpenCV."""
        def open_camera():
            cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                raise RuntimeError(f"Failed to open camera {self.camera_index}")
            # Set resolution
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            return cap
        
        loop = asyncio.get_event_loop()
        self.camera = await loop.run_in_executor(None, open_camera)
        print(f"[VisionController] USB camera {self.camera_index} initialized")
    
    async def capture_frame(self) -> Optional[np.ndarray]:
        """Capture a single frame from the camera via camera process.
        
        Returns:
            numpy array (BGR format) or None if capture failed
        """
        if not self.camera_process:
            debug_log("[VisionController] No camera process available")
            return None
        
        try:
            # Send capture command and get result (all in one blocking call in thread)
            def _do_capture():
                self.camera_process.command_queue.put(('capture', ()), timeout=1.0)
                return self.camera_process.result_queue.get(timeout=5.0)
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _do_capture)
            
            if result and 'frame_bytes' in result:
                # Reconstruct frame from bytes
                frame_bytes = result['frame_bytes']
                shape = result['shape']
                dtype = np.dtype(result['dtype'])
                
                frame = np.frombuffer(frame_bytes, dtype=dtype).reshape(shape)
                # Track capture time for fast-path optimization
                self._last_capture_time = time.time()
                return frame
            else:
                error = result.get('error', 'Unknown error') if result else 'No response'
                debug_log(f"[VisionController] Frame capture failed: {error}")
                return None
            
        except Exception as e:
            print(f"[VisionController] Error capturing frame: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def scan_qr_code(self, retries=3, delay=0.5, camera_preview=None, motion_controller=None, search_offset=0.0, base_x=None, base_y=None) -> Optional[str]:
        """Scan for QR code in camera view.
        
        Uses a fast-path approach: try immediate detection first without delays,
        then fall back to retry logic only if needed.
        
        Args:
            retries: Number of capture attempts (after fast-path fails)
            delay: Delay between retries in seconds
            camera_preview: Optional CameraPreview to display preprocessed frames
            motion_controller: Optional MotionController for position search
            search_offset: XY offset in mm to search around base position (0=disabled)
            base_x: Base X position for position search
            base_y: Base Y position for position search
            
        Returns:
            Decoded QR code string or None if not found
        """
        scan_start = time.time()
        self.update_phase("Scanning QR")
        
        # Check if camera was recently active (within last 2 seconds)
        # If so, skip throwaway frame - camera is already warmed up
        camera_warm = (time.time() - self._last_capture_time) < 2.0
        
        # === FAST PATH: Try immediate detection without delays ===
        try:
            frame = await self.capture_frame()
            if frame is not None:
                # Preprocess frame
                loop = asyncio.get_event_loop()
                frame_gray, orig_size = await loop.run_in_executor(None, self._preprocess_frame, frame)
                
                if camera_preview:
                    camera_preview.show_frame(frame_gray, "fast-path")
                
                # Try standard QR detection (very fast)
                data = await loop.run_in_executor(None, self._detect_qr_single, frame_gray)
                if data:
                    total_time = time.time() - scan_start
                    if camera_preview:
                        camera_preview.show_frame(frame_gray, "QR detected (fast)", qr_found=data)
                    debug_log(f"[VisionController] FAST PATH: Standard QR FOUND: {data} (total: {total_time:.3f}s)")
                    return data
                
                # Try Micro QR detection
                data = await loop.run_in_executor(None, self._detect_micro_qr_with_rotation, frame_gray, None)
                if data:
                    total_time = time.time() - scan_start
                    if camera_preview:
                        camera_preview.show_frame(frame_gray, "QR detected (fast)", qr_found=data)
                    debug_log(f"[VisionController] FAST PATH: Micro QR FOUND: {data} (total: {total_time:.3f}s)")
                    return data
                
                debug_log(f"[VisionController] Fast path failed, falling back to retry logic")
        except Exception as e:
            debug_log(f"[VisionController] Fast path exception: {e}")
        
        # === RETRY PATH: Only if fast path failed ===
        for attempt in range(retries):
            try:
                # Only do throwaway frame on first attempt if camera wasn't recently active
                if attempt == 0 and not camera_warm:
                    throwaway = await self.capture_frame()
                    if throwaway is not None:
                        await asyncio.sleep(0.05)  # Reduced from 0.1s
                        debug_log(f"[VisionController] Captured throwaway frame for camera adjustment")
                
                frame = await self.capture_frame()
                if frame is None:
                    print(f"[VisionController] Capture failed on attempt {attempt + 1}")
                    if attempt < retries - 1:
                        await asyncio.sleep(delay * 0.5)  # Reduced delay
                    continue
                
                loop = asyncio.get_event_loop()
                frame_gray, orig_size = await loop.run_in_executor(None, self._preprocess_frame, frame)
                debug_log(f"[VisionController] Preprocessed frame from {orig_size[0]}x{orig_size[1]} to {frame_gray.shape[1]}x{frame_gray.shape[0]}, grayscale")
                
                if camera_preview:
                    camera_preview.show_frame(frame_gray, f"retry {attempt+1}")
                
                # Try standard QR detection first (fast)
                strategy_start = time.time()
                data = await loop.run_in_executor(None, self._detect_qr_single, frame_gray)
                strategy_time = time.time() - strategy_start
                if data:
                    total_time = time.time() - scan_start
                    if camera_preview:
                        camera_preview.show_frame(frame_gray, "QR detected", qr_found=data)
                    debug_log(f"[VisionController] Standard QR FOUND: {data} (strategy: {strategy_time:.3f}s, total: {total_time:.3f}s)")
                    return data
                
                # Try Micro QR detection
                strategy_start = time.time()
                data = await loop.run_in_executor(None, self._detect_micro_qr_with_rotation, frame_gray, None)
                strategy_time = time.time() - strategy_start
                if data:
                    total_time = time.time() - scan_start
                    if camera_preview:
                        camera_preview.show_frame(frame_gray, "QR detected", qr_found=data)
                    debug_log(f"[VisionController] Micro QR FOUND: {data} (strategy: {strategy_time:.3f}s, total: {total_time:.3f}s)")
                    return data
                
                debug_log(f"[VisionController] Attempt {attempt + 1}/{retries} failed")
                
                # Save failed frame on last attempt
                if attempt == retries - 1:
                    try:
                        save_path = f"/tmp/failed_qr_scan_{int(scan_start)}.png"
                        cv2.imwrite(save_path, frame_gray)
                        debug_log(f"[VisionController] Saved failed scan frame to {save_path}")
                    except Exception as e:
                        debug_log(f"[VisionController] Could not save frame: {e}")
                
                if attempt < retries - 1:
                    await asyncio.sleep(delay * 0.5)  # Reduced delay
                        
            except Exception as e:
                print(f"[VisionController] Error scanning QR code: {e}")
                debug_log(f"[VisionController] Exception in scan_qr_code: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(delay * 0.5)
        
        # === POSITION SEARCH: Only if all retries exhausted ===
        if motion_controller and search_offset > 0 and base_x is not None and base_y is not None:
            debug_log(f"[VisionController] All retries failed. Trying position search with offset={search_offset}mm")
            
            search_positions = [
                (base_x - search_offset, base_y + search_offset),  # Top-left
                (base_x + search_offset, base_y + search_offset),  # Top-right
                (base_x + search_offset, base_y - search_offset),  # Bottom-right
                (base_x - search_offset, base_y - search_offset),  # Bottom-left
            ]
            
            for idx, (search_x, search_y) in enumerate(search_positions, 1):
                debug_log(f"[VisionController] Position search {idx}/4: moving to ({search_x:.1f}, {search_y:.1f})") 
                try:
                    await motion_controller.rapid_xy_abs(search_x, search_y)
                    await asyncio.sleep(0.1)  # Reduced from 0.2s
                    
                    self.drain_camera_buffer()
                    await asyncio.sleep(0.1)  # Reduced from 0.2s
                    
                    frame_search = await self.capture_frame()
                    if frame_search is None:
                        debug_log(f"[VisionController] Position search {idx}/4: capture failed")
                        continue
                    
                    loop = asyncio.get_event_loop()
                    frame_gray, _ = await loop.run_in_executor(None, self._preprocess_frame, frame_search)
                    
                    if camera_preview:
                        camera_preview.show_frame(frame_gray, f"pos{idx}")
                    
                    # Try both detection methods
                    data = await loop.run_in_executor(None, self._detect_qr_single, frame_gray)
                    if data:
                        debug_log(f"[VisionController] QR FOUND at position {idx}/4: {data}")
                        return data
                    
                    data = await loop.run_in_executor(None, self._detect_micro_qr_with_rotation, frame_gray, None)
                    if data:
                        debug_log(f"[VisionController] Micro QR FOUND at position {idx}/4: {data}")
                        return data
                    
                    debug_log(f"[VisionController] Position search {idx}/4: no QR detected")
                    
                except Exception as e:
                    debug_log(f"[VisionController] Position search {idx}/4 error: {e}")
                    continue
            
            # Return to base position
            try:
                debug_log(f"[VisionController] Returning to base position ({base_x:.1f}, {base_y:.1f})")
                await motion_controller.rapid_xy_abs(base_x, base_y)
            except Exception as e:
                debug_log(f"[VisionController] Error returning to base position: {e}")
        
        total_time = time.time() - scan_start
        debug_log(f"[VisionController] QR code scan FAILED (total time: {total_time:.3f}s)")
        return None
    
    def _preprocess_frame(self, img):
        """Crop to square and convert to grayscale."""
        height, width = img.shape[:2]
        if width > height:
            left = (width - height) // 2
            right = left + height
            img = img[:, left:right]
        
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        return img, (width, height)
        
        total_time = time.time() - scan_start
        debug_log(f"[VisionController] QR code scan FAILED after all retries and position search (total time: {total_time:.3f}s)")
        return None
    
    def _detect_qr_single(self, frame: np.ndarray) -> Optional[str]:
        """Attempt standard QR detection on a single preprocessed frame.
        
        Uses OpenCV's QRCodeDetector for standard QR codes (fast).
        For Micro QR codes, use _detect_micro_qr_with_rotation() instead.
        
        Args:
            frame: Preprocessed grayscale frame
            
        Returns:
            Decoded QR string or None
        """
        try:
            # Try OpenCV (fast for standard QR codes)
            data, bbox, _ = self.qr_detector.detectAndDecode(frame)
            if data:
                debug_log(f"[VisionController] Standard QR detected (OpenCV): '{data}'")
                return data
            
            return None
        except Exception as e:
            debug_log(f"[VisionController] QR detection error: {e}")
            return None
    
    def _detect_micro_qr_with_rotation(self, frame: np.ndarray, camera_preview=None) -> Optional[Tuple[str, str]]:
        """Try QR/Micro QR detection at multiple rotations using zxing-cpp.
        
        Micro QR codes have only one position marker, making them more sensitive
        to orientation than standard QR codes with three markers.
        
        Args:
            frame: Preprocessed grayscale frame
            camera_preview: Optional CameraPreview to update with rotated images
            
        Returns:
            Tuple of (decoded string, barcode format name) or None
        """
        import time
        timestamp = int(time.time())
        
        # Try zxing-cpp first if available (best Micro QR support)
        if ZXING_AVAILABLE:
            debug_log("[VisionController] Using zxing-cpp for Micro QR detection")
            
            # Try original orientation (0°)
            debug_log("[VisionController] Trying Micro QR at 0° orientation")
            
            # Try with raw grayscale
            try:
                results = zxingcpp.read_barcodes(frame)
                if results:
                    data = results[0].text
                    fmt = str(results[0].format).replace('BarcodeFormat.', '')
                    debug_log(f"[VisionController] {fmt} detected at 0° (zxing raw): '{data}'")
                    return (data, fmt)
            except Exception as e:
                debug_log(f"[VisionController] zxing 0° raw failed: {e}")
            
            # Try with OTSU threshold preprocessing
            try:
                blurred = cv2.GaussianBlur(frame, (5, 5), 0)
                _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                results = zxingcpp.read_barcodes(otsu)
                if results:
                    data = results[0].text
                    fmt = str(results[0].format).replace('BarcodeFormat.', '')
                    debug_log(f"[VisionController] {fmt} detected at 0° (zxing OTSU): '{data}'")
                    return (data, fmt)
                    
                # Save 0° images for debugging
                cv2.imwrite(f"/tmp/micro_qr_0deg_raw_{timestamp}.png", frame)
                cv2.imwrite(f"/tmp/micro_qr_0deg_otsu_{timestamp}.png", otsu)
            except Exception as e:
                debug_log(f"[VisionController] zxing 0° OTSU failed: {e}")
            
            # Try 90° rotations
            for angle in [90, 180, 270]:
                try:
                    debug_log(f"[VisionController] Trying Micro QR at {angle}° orientation")
                    rotated = cv2.rotate(frame, {
                        90: cv2.ROTATE_90_CLOCKWISE,
                        180: cv2.ROTATE_180,
                        270: cv2.ROTATE_90_COUNTERCLOCKWISE
                    }[angle])
                    
                    # Try raw
                    results = zxingcpp.read_barcodes(rotated)
                    if results:
                        data = results[0].text
                        fmt = str(results[0].format).replace('BarcodeFormat.', '')
                        debug_log(f"[VisionController] {fmt} detected at {angle}° (zxing raw): '{data}'")
                        return (data, fmt)
                    
                    # Try OTSU
                    rotated_blurred = cv2.GaussianBlur(rotated, (5, 5), 0)
                    _, rotated_otsu = cv2.threshold(rotated_blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                    results = zxingcpp.read_barcodes(rotated_otsu)
                    if results:
                        data = results[0].text
                        fmt = str(results[0].format).replace('BarcodeFormat.', '')
                        debug_log(f"[VisionController] {fmt} detected at {angle}° (zxing OTSU): '{data}'")
                        return (data, fmt)
                    
                    # Save for debugging
                    cv2.imwrite(f"/tmp/micro_qr_{angle}deg_raw_{timestamp}.png", rotated)
                    cv2.imwrite(f"/tmp/micro_qr_{angle}deg_otsu_{timestamp}.png", rotated_otsu)
                        
                except Exception as e:
                    debug_log(f"[VisionController] zxing rotation {angle}° failed: {e}")
                    continue
            
            debug_log(f"[VisionController] zxing-cpp Micro QR detection failed at all orientations. Check /tmp/micro_qr_*_{timestamp}.png")
            return None
        
        # No Micro QR detector available
        debug_log("[VisionController] No Micro QR detector available. Install zxing-cpp: pip install zxing-cpp")
        return None
    
    async def scan_qr_with_preview(self, camera_preview, timeout=10.0) -> Optional[str]:
        """Scan for QR code while showing live preview.
        
        Args:
            camera_preview: CameraPreview instance to display preview
            timeout: Maximum time to wait for QR code in seconds
            
        Returns:
            Decoded QR code string or None if not found
        """
        self.update_phase("Scanning QR")
        
        start_time = time.time()
        qr_data = None
        
        try:
            # The preview updates itself via Clock, we just wait for a result
            # Use larger sleep interval to reduce CPU overhead
            while time.time() - start_time < timeout:
                # Check if QR was detected by preview
                if camera_preview.qr_data:
                    qr_data = camera_preview.qr_data
                    print(f"[VisionController] QR code detected: {qr_data}")
                    break
                
                # Sleep longer to reduce CPU overhead (check 10 times per second)
                await asyncio.sleep(0.1)
            
            if not qr_data:
                print(f"[VisionController] QR scan timed out after {timeout}s")
        
        except asyncio.CancelledError:
            print("[VisionController] QR scan cancelled")
            raise
                
        except Exception as e:
            print(f"[VisionController] Error during QR scan with preview: {e}")
        
        return qr_data
    
    def get_frame_with_qr_sync(self) -> Tuple[Optional[np.ndarray], Optional[str], Optional[np.ndarray]]:
        """Synchronously get a frame with QR code detection (for UI updates).
        
        Returns:
            Tuple of (frame with QR overlay, qr_data, bbox)
        """
        try:
            if self.use_picamera and self.picamera2:
                # Capture from picamera (despite RGB888 config, seems to return BGR)
                frame = self.picamera2.capture_array()
                # Note: treating as BGR for OpenCV compatibility
            elif self.camera:
                # Capture from USB camera (returns BGR)
                ret, frame = self.camera.read()
                if not ret:
                    return None, None, None
            else:
                return None, None, None
            
            # Make a copy to avoid modifying camera buffer
            frame = frame.copy()
            
            # Detect QR code
            data, bbox, _ = self.qr_detector.detectAndDecode(frame)
            
            # Draw bounding box if QR detected
            if bbox is not None:
                bbox = bbox.astype(int)
                # Draw polygon around QR code (green in RGB)
                cv2.polylines(frame, [bbox], True, (0, 255, 0), 3)
                
                # Add text with decoded data
                if data:
                    # Position text above the QR code
                    text_pos = (bbox[0][0][0], max(bbox[0][0][1] - 10, 30))
                    cv2.putText(frame, data, text_pos,
                               cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            return frame, data if data else None, bbox
            
        except Exception as e:
            print(f"[VisionController] Error in get_frame_with_qr_sync: {e}")
            return None, None, None
    
    def get_frame_simple(self) -> Optional[np.ndarray]:
        """Synchronously get a frame without QR detection (faster for preview).
        
        Returns:
            Frame as numpy array (BGR format) or None, cropped to square and grayscale
        """
        try:
            frame = None
            if self.use_picamera and self.picamera2:
                # Capture frame - make a copy to avoid holding camera buffer
                frame = self.picamera2.capture_array()
                frame = frame.copy()
            elif self.camera:
                ret, frame_read = self.camera.read()
                if not ret:
                    return None
                frame = frame_read
            else:
                return None
            
            if frame is None:
                return None
            
            # Apply same preprocessing as scan_qr_code for consistent preview
            # 1. Crop to center square (full height, centered horizontally)
            height, width = frame.shape[:2]
            if width > height:
                # Crop left and right to make square
                left = (width - height) // 2
                right = left + height
                frame = frame[:, left:right]
            
            # 2. Convert to grayscale (black and white)
            if len(frame.shape) == 3:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            return frame
            
        except Exception as e:
            print(f"[VisionController] Error in get_frame_simple: {e}")
            return None
    
    async def drain_camera_buffer_async(self, max_frames=5):
        """Asynchronously drain accumulated frames from camera buffer.
        
        Args:
            max_frames: Maximum number of frames to drain
        """
        try:
            for _ in range(max_frames):
                frame = await self.capture_frame()
                if frame is not None:
                    del frame  # Explicitly free frame memory
        except Exception as e:
            debug_log(f"[VisionController] Error draining buffer: {e}")
    
    def drain_camera_buffer(self, max_frames=5):
        """Drain accumulated frames from camera buffer to prevent slowdown.
        DEPRECATED: Use drain_camera_buffer_async() instead to avoid blocking.
        
        Args:
            max_frames: Maximum number of frames to drain
        """
        if self.use_picamera and self.picamera2:
            try:
                # Capture and discard a few frames to clear the buffer
                for _ in range(max_frames):
                    frame = self.picamera2.capture_array()
                    del frame  # Explicitly free
            except Exception as e:
                print(f"[VisionController] Error draining buffer: {e}")
        elif self.camera:
            try:
                # For USB camera, read and discard frames
                for _ in range(max_frames):
                    ret, frame = self.camera.read()
                    if ret:
                        del frame  # Explicitly free
            except Exception as e:
                print(f"[VisionController] Error draining buffer: {e}")
    
    def detect_qr_in_frame(self, frame: np.ndarray) -> Tuple[Optional[str], Optional[np.ndarray]]:
        """Detect QR code in an existing frame.
        
        Args:
            frame: OpenCV frame (BGR format)
            
        Returns:
            Tuple of (qr_data, bbox)
        """
        try:
            # Detect QR code
            data, bbox, _ = self.qr_detector.detectAndDecode(frame)
            return (data if data else None, bbox)
        except Exception as e:
            print(f"[VisionController] Error in detect_qr_in_frame: {e}")
            return None, None
    
    async def scan_qr_with_image_save(self, save_path: str, retries=3) -> Optional[str]:
        """Scan QR code and save the captured image.
        
        Args:
            save_path: Path to save the captured image
            retries: Number of capture attempts
            
        Returns:
            Decoded QR code string or None if not found
        """
        for attempt in range(retries):
            frame = await self.capture_frame()
            if frame is None:
                continue
            
            # Try to decode
            loop = asyncio.get_event_loop()
            data, bbox, _ = await loop.run_in_executor(
                None,
                self.qr_detector.detectAndDecode,
                frame
            )
            
            if data:
                # Draw bounding box on frame
                if bbox is not None:
                    bbox = bbox.astype(int)
                    cv2.polylines(frame, [bbox], True, (0, 255, 0), 3)
                    # Add text with decoded data
                    cv2.putText(frame, data, (bbox[0][0][0], bbox[0][0][1] - 10),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                
                # Save image
                await loop.run_in_executor(None, cv2.imwrite, save_path, frame)
                print(f"[VisionController] Saved scan image to {save_path}")
                return data
            
            if attempt < retries - 1:
                await asyncio.sleep(0.5)
        
        # Save last frame even if QR not found (for debugging)
        if frame is not None:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, cv2.imwrite, save_path, frame)
            print(f"[VisionController] Saved failed scan image to {save_path}")
        
        return None
    
    async def test_camera(self, num_frames=5):
        """Test camera by capturing multiple frames.
        
        Args:
            num_frames: Number of test frames to capture
        """
        self.update_phase("Testing Camera")
        print(f"[VisionController] Testing camera with {num_frames} captures...")
        
        for i in range(num_frames):
            frame = await self.capture_frame()
            if frame is not None:
                print(f"  Frame {i+1}: {frame.shape} dtype={frame.dtype}")
            else:
                print(f"  Frame {i+1}: FAILED")
            await asyncio.sleep(0.2)
        
        print("[VisionController] Camera test complete")
    
    async def close(self):
        """Release camera resources."""
        try:
            if self.picamera2:
                def stop_camera():
                    try:
                        if self._picamera_started:
                            self.picamera2.stop()
                            self._picamera_started = False
                        self.picamera2.close()
                        # Small delay to ensure cleanup completes
                        time.sleep(0.1)
                    except Exception as e:
                        print(f"[VisionController] Error during picamera2 cleanup: {e}")
                
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, stop_camera)
                self.picamera2 = None
                print("[VisionController] Closed Raspberry Pi camera")
            
            if self.camera:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.camera.release)
                self.camera = None
                print("[VisionController] Closed USB camera")
                
        except Exception as e:
            print(f"[VisionController] Error closing camera: {e}")
    
    def __del__(self):
        """Cleanup on deletion."""
        # Note: This is not async-safe, just a safety net
        if hasattr(self, 'camera') and self.camera:
            try:
                self.camera.release()
            except:
                pass
