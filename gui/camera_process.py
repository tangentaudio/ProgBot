from logger import get_logger
log = get_logger(__name__)

"""
Camera operations in a separate process to avoid GIL contention.

This module runs all camera operations (picamera2, opencv, QR detection)
in an independent process with its own GIL, preventing interference with
the main process's serial communication.
"""

import multiprocessing as mp
from multiprocessing import Process, Queue, Event
import time
import sys
import traceback
import atexit
import signal



# Global process tracker for cleanup
_active_processes = []


def _cleanup_all_processes():
    """Emergency cleanup of all camera processes."""
    for proc in _active_processes:
        if proc and proc.is_alive():
            try:
                proc.kill()
            except:
                pass


# Register cleanup handlers
atexit.register(_cleanup_all_processes)


class CameraProcess:
    """Manages camera operations in a separate process."""
    
    def __init__(self, use_picamera=True, camera_index=0):
        self.use_picamera = use_picamera
        self.camera_index = camera_index
        
        # IPC queues
        self.command_queue = mp.Queue(maxsize=10)
        self.result_queue = mp.Queue(maxsize=10)
        self.stop_event = mp.Event()
        
        # Process handle
        self.process = None
        self._started = False
    
    def start(self):
        """Start the camera worker process."""
        if self._started and self.process and self.process.is_alive():
            log.debug("Process already started and running")
            return
        
        # If process exists but not alive, clean up first
        if self.process and not self.process.is_alive():
            log.debug("Found dead process, cleaning up...")
            self.stop()
        
        log.debug(f"Starting camera worker process (use_picamera={self.use_picamera})...")
        self.process = Process(
            target=self._camera_worker,
            args=(self.command_queue, self.result_queue, self.stop_event, 
                  self.use_picamera, self.camera_index),
            daemon=True
        )
        self.process.start()
        self._started = True
        
        # Track for emergency cleanup
        global _active_processes
        _active_processes.append(self.process)
        
        log.debug(f"Camera worker process started (PID: {self.process.pid})")
    
    def stop(self):
        """Stop the camera worker process."""
        if not self._started:
            return
        
        log.debug("Stopping camera worker process...")
        
        # First, signal the process to stop via event
        self.stop_event.set()
        
        if self.process and self.process.is_alive():
            # Give it 200ms to finish current command and exit (should be quick with 0.1s timeout)
            self.process.join(timeout=0.2)
            
            if self.process.is_alive():
                log.debug("Process didn't stop gracefully, sending SIGTERM...")
                self.process.terminate()  # SIGTERM - triggers immediate exit in signal handler
                self.process.join(timeout=0.2)
                
                if self.process.is_alive():
                    log.debug("Process still alive after SIGTERM, killing...")
                    self.process.kill()  # SIGKILL - force kill
                    self.process.join(timeout=0.2)
        
        # Remove from global tracker
        global _active_processes
        if self.process in _active_processes:
            _active_processes.remove(self.process)
        
        # Clear queues to prevent stale data in next cycle
        while not self.command_queue.empty():
            try:
                self.command_queue.get_nowait()
            except:
                break
        
        while not self.result_queue.empty():
            try:
                self.result_queue.get_nowait()
            except:
                break
        
        # Reset stop event for next start
        self.stop_event.clear()
        
        self._started = False
        self.process = None
        log.debug("Camera worker process stopped and cleaned up")
    
    def send_command(self, command, *args, timeout=10.0):
        """
        Send command to camera process and wait for result.
        
        Args:
            command: Command string ('init', 'capture', 'scan_qr', 'cleanup')
            *args: Command arguments
            timeout: Timeout in seconds
            
        Returns:
            Result from camera process or None on timeout/error
        """
        if not self._started:
            log.debug(f"ERROR: Process not started, cannot execute: {command}")
            return None
        
        try:
            # Send command
            self.command_queue.put((command, args), timeout=1.0)
            
            # Wait for result
            result = self.result_queue.get(timeout=timeout)
            
            # Check for error response
            if isinstance(result, dict) and result.get('error'):
                log.debug(f"Command '{command}' returned error: {result['error']}")
                return None
            
            return result
            
        except mp.queues.Full:
            log.debug(f"ERROR: Command queue full for: {command}")
            return None
        except mp.queues.Empty:
            log.debug(f"ERROR: Timeout waiting for result: {command}")
            return None
        except Exception as e:
            log.debug(f"ERROR: Exception during command '{command}': {e}")
            return None
    
    @staticmethod
    def _camera_worker(command_queue, result_queue, stop_event, use_picamera, camera_index):
        """
        Camera worker process main loop.
        Runs in separate process with independent GIL.
        """
        log.debug("Worker process starting...")
        
        # Import heavy libraries inside worker process
        import numpy as np
        import cv2
        import signal
        
        camera = None
        picamera2 = None
        qr_detector = None
        zxing_detector = None
        
        # Signal handler for IMMEDIATE shutdown (no cleanup - it blocks!)
        # picamera2.stop()/close() BLOCK when camera is in bad state or mid-operation
        # Just exit immediately to unblock parent process
        def signal_handler(signum, frame):
            log.debug(f"Worker received signal {signum}, exiting immediately (no cleanup)")
            import sys
            sys.exit(0)
        
        # Register signal handlers
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        try:
            # Initialize QR detectors once
            log.debug("Initializing QR detectors...")
            qr_detector = cv2.QRCodeDetector()
            
            try:
                import zxingcpp
                zxing_detector = True
                log.debug("zxing-cpp available for Micro QR detection")
            except ImportError:
                log.debug("zxing-cpp not available, Micro QR detection disabled")
            
            # Main command processing loop
            log.debug("Worker ready, waiting for commands...")
            
            while not stop_event.is_set():
                try:
                    # Check for commands with short timeout for responsive shutdown
                    command, args = command_queue.get(timeout=0.1)
                    log.debug(f"Received command: {command}")
                    
                    if command == 'init':
                        # Initialize camera
                        try:
                            if use_picamera:
                                from picamera2 import Picamera2
                                
                                picamera2 = Picamera2()
                                config = picamera2.create_still_configuration(
                                    main={"format": "RGB888", "size": (640, 480)}
                                )
                                picamera2.configure(config)
                                picamera2.start()
                                
                                log.debug("Picamera2 initialized at 640x480")
                                result_queue.put({'success': True, 'camera_type': 'picamera2'})
                            else:
                                camera = cv2.VideoCapture(camera_index)
                                camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                                camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                                
                                log.debug("USB camera initialized")
                                result_queue.put({'success': True, 'camera_type': 'usb'})
                                
                        except Exception as e:
                            log.debug(f"Camera init failed: {e}")
                            result_queue.put({'error': str(e)})
                    
                    elif command == 'capture':
                        # Capture a frame
                        try:
                            frame = None
                            
                            if picamera2:
                                frame = picamera2.capture_array()
                            elif camera:
                                ret, frame = camera.read()
                                if not ret or frame is None:
                                    raise RuntimeError("USB camera read failed")
                            else:
                                raise RuntimeError("No camera initialized")
                            
                            if frame is not None:
                                # Send frame as bytes to avoid pickle overhead
                                frame_bytes = frame.tobytes()
                                shape = frame.shape
                                dtype_str = str(frame.dtype)
                                
                                result_queue.put({
                                    'frame_bytes': frame_bytes,
                                    'shape': shape,
                                    'dtype': dtype_str
                                })
                            else:
                                result_queue.put({'error': 'Frame capture returned None'})
                                
                        except Exception as e:
                            log.debug(f"Capture failed: {e}")
                            result_queue.put({'error': str(e)})
                    
                    elif command == 'scan_qr':
                        # Capture and scan for QR code
                        retries = args[0] if args else 3
                        
                        try:
                            qr_result = None
                            
                            for attempt in range(retries):
                                # Capture frame
                                if picamera2:
                                    frame = picamera2.capture_array()
                                elif camera:
                                    ret, frame = camera.read()
                                    if not ret:
                                        continue
                                else:
                                    raise RuntimeError("No camera initialized")
                                
                                if frame is None:
                                    continue
                                
                                # Preprocess: crop to center square and grayscale
                                height, width = frame.shape[:2]
                                if width > height:
                                    left = (width - height) // 2
                                    frame = frame[:, left:left+height]
                                
                                if len(frame.shape) == 3:
                                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                                
                                # Try standard QR detection
                                data, bbox, _ = qr_detector.detectAndDecode(frame)
                                if data:
                                    qr_result = {
                                        'data': data,
                                        'type': 'standard',
                                        'attempt': attempt + 1
                                    }
                                    break
                                
                                # Try Micro QR with zxing-cpp
                                if zxing_detector and not data:
                                    try:
                                        import zxingcpp
                                        results = zxingcpp.read_barcodes(frame)
                                        if results:
                                            qr_result = {
                                                'data': results[0].text,
                                                'type': 'micro',
                                                'attempt': attempt + 1
                                            }
                                            break
                                    except Exception as e:
                                        log.debug(f"zxing detection error: {e}")
                            
                            if qr_result:
                                result_queue.put(qr_result)
                            else:
                                result_queue.put({'error': 'No QR code found'})
                                
                        except Exception as e:
                            log.debug(f"QR scan failed: {e}")
                            result_queue.put({'error': str(e)})
                    
                    elif command == 'cleanup':
                        # Clean up camera resources and exit
                        try:
                            if picamera2:
                                picamera2.stop()
                                picamera2.close()
                                picamera2 = None
                                log.debug("Picamera2 cleaned up")
                            
                            if camera:
                                camera.release()
                                camera = None
                                log.debug("USB camera cleaned up")
                            
                            cv2.destroyAllWindows()
                            
                            result_queue.put({'success': True})
                            
                            # Exit the worker loop after cleanup
                            log.debug("Worker process shutting down...")
                            break
                            
                        except Exception as e:
                            log.debug(f"Cleanup error: {e}")
                            result_queue.put({'error': str(e)})
                            break
                    
                    else:
                        log.debug(f"Unknown command: {command}")
                        result_queue.put({'error': f'Unknown command: {command}'})
                
                except mp.queues.Empty:
                    # Timeout waiting for command, check stop event again
                    continue
                except Exception as e:
                    log.debug(f"Error processing command: {e}")
                    traceback.print_exc()
                    result_queue.put({'error': str(e)})
        
        except Exception as e:
            log.debug(f"FATAL: Worker process error: {e}")
            traceback.print_exc()
        
        finally:
            # Final cleanup
            log.debug("Worker process shutting down...")
            try:
                if picamera2:
                    picamera2.stop()
                    picamera2.close()
                if camera:
                    camera.release()
                cv2.destroyAllWindows()
            except:
                pass
            
            log.debug("Worker process terminated")
    
    def __del__(self):
        """Cleanup on deletion."""
        self.stop()
