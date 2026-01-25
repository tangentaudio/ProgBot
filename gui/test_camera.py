#!/usr/bin/env python3
"""
Test script for VisionController - validates camera and QR code scanning.

Usage:
    ./test_camera.py              # Test with auto-detected camera
    ./test_camera.py --usb        # Force USB camera mode
    ./test_camera.py --picamera   # Force Raspberry Pi camera mode
"""

import asyncio
import sys
import argparse
from vision_controller import VisionController


def update_phase(phase):
    """Dummy phase update callback."""
    print(f"[PHASE] {phase}")


async def test_camera_basic(use_picamera=True):
    """Test basic camera initialization and frame capture."""
    print("\n" + "="*60)
    print("Testing Basic Camera Operations")
    print("="*60)
    
    vision = VisionController(update_phase, use_picamera=use_picamera, camera_index=0)
    
    try:
        # Test connection
        print("\n1. Testing camera connection...")
        await vision.connect()
        print("   ✓ Camera connected successfully")
        
        # Test frame capture
        print("\n2. Testing frame capture...")
        frame = await vision.capture_frame()
        if frame is not None:
            print(f"   ✓ Captured frame: {frame.shape}, dtype={frame.dtype}")
        else:
            print("   ✗ Failed to capture frame")
            return False
        
        # Test multiple captures
        print("\n3. Testing multiple captures (5 frames)...")
        await vision.test_camera(num_frames=5)
        print("   ✓ Multiple captures successful")
        
        return True
        
    except Exception as e:
        print(f"   ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await vision.close()
        print("\n   Camera closed")


async def test_qr_scanning(use_picamera=True):
    """Test QR code scanning."""
    print("\n" + "="*60)
    print("Testing QR Code Scanning")
    print("="*60)
    print("\nInstructions:")
    print("  - Place a QR code in view of the camera")
    print("  - The system will attempt to scan it")
    print()
    
    vision = VisionController(update_phase, use_picamera=use_picamera, camera_index=0)
    
    try:
        await vision.connect()
        
        print("1. Attempting QR code scan (3 retries)...")
        qr_data = await vision.scan_qr_code(retries=3, delay=1.0)
        
        if qr_data:
            print(f"   ✓ QR Code detected: '{qr_data}'")
            return True
        else:
            print("   ✗ No QR code detected")
            print("   (Make sure a QR code is visible to the camera)")
            return False
            
    except Exception as e:
        print(f"   ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await vision.close()


async def test_qr_with_save(use_picamera=True):
    """Test QR code scanning with image saving."""
    print("\n" + "="*60)
    print("Testing QR Code Scanning with Image Save")
    print("="*60)
    
    vision = VisionController(update_phase, use_picamera=use_picamera, camera_index=0)
    save_path = "/tmp/test_qr_scan.jpg"
    
    try:
        await vision.connect()
        
        print(f"1. Scanning QR code and saving to: {save_path}")
        qr_data = await vision.scan_qr_with_image_save(save_path, retries=3)
        
        if qr_data:
            print(f"   ✓ QR Code detected: '{qr_data}'")
            print(f"   ✓ Image saved to: {save_path}")
            return True
        else:
            print("   ✗ No QR code detected")
            print(f"   ℹ Image of failed scan saved to: {save_path}")
            return False
            
    except Exception as e:
        print(f"   ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await vision.close()


async def main():
    """Run all camera tests."""
    parser = argparse.ArgumentParser(description='Test VisionController camera and QR scanning')
    parser.add_argument('--usb', action='store_true', help='Force USB camera mode')
    parser.add_argument('--picamera', action='store_true', help='Force Raspberry Pi camera mode')
    parser.add_argument('--qr-only', action='store_true', help='Only test QR scanning')
    parser.add_argument('--basic-only', action='store_true', help='Only test basic camera')
    args = parser.parse_args()
    
    # Determine camera type
    if args.usb:
        use_picamera = False
        print("Using USB camera mode")
    elif args.picamera:
        use_picamera = True
        print("Using Raspberry Pi camera mode")
    else:
        # Auto-detect
        use_picamera = True
        print("Auto-detecting camera type (will try picamera first, then USB)")
    
    print("\n" + "="*60)
    print("VisionController Test Suite")
    print("="*60)
    
    results = []
    
    # Run tests
    if not args.qr_only:
        result = await test_camera_basic(use_picamera)
        results.append(("Basic Camera", result))
        # Small delay between tests to ensure cleanup
        await asyncio.sleep(0.5)
    
    if not args.basic_only:
        result = await test_qr_scanning(use_picamera)
        results.append(("QR Scanning", result))
        await asyncio.sleep(0.5)
        
        result = await test_qr_with_save(use_picamera)
        results.append(("QR with Image Save", result))
    
    # Print summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status} - {test_name}")
    
    all_passed = all(result for _, result in results)
    print()
    if all_passed:
        print("All tests passed! ✓")
        return 0
    else:
        print("Some tests failed. ✗")
        return 1


if __name__ == '__main__':
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
