from logger import get_logger
log = get_logger(__name__)

"""Serial device detection and identification for ProgBot hardware."""
import serial.tools.list_ports


class SerialPortInfo:
    """Information about a serial port with unique identification."""
    
    def __init__(self, port_info):
        """Initialize from pyserial's port info object.
        
        Args:
            port_info: serial.tools.list_ports_common.ListPortInfo object
        """
        self.device = port_info.device
        self.description = port_info.description
        self.hwid = port_info.hwid
        self.vid = port_info.vid
        self.pid = port_info.pid
        self.serial_number = port_info.serial_number
        self.location = port_info.location
        self.manufacturer = port_info.manufacturer
        self.product = port_info.product
        
    @property
    def unique_id(self):
        """Generate a unique identifier for this port.
        
        Priority:
        1. Serial number + location (handles devices with duplicate serial numbers)
        2. Serial number alone (if no location)
        3. VID:PID:Location (USB port location)
        4. VID:PID (least stable, but better than nothing)
        
        Returns:
            Unique identifier string
        """
        if self.serial_number and self.location:
            # Include location to handle devices that share serial numbers
            # (e.g., multi-function USB devices presenting multiple ports)
            return f"SN:{self.serial_number}:{self.location}"
        elif self.serial_number:
            return f"SN:{self.serial_number}"
        elif self.vid and self.pid and self.location:
            return f"USB:{self.vid:04X}:{self.pid:04X}:{self.location}"
        elif self.vid and self.pid:
            return f"USB:{self.vid:04X}:{self.pid:04X}"
        else:
            # Fallback to device name (not ideal)
            return f"DEV:{self.device}"
    
    @property
    def display_name(self):
        """Human-readable display name for UI."""
        parts = [self.device]
        
        if self.description and self.description != 'n/a':
            parts.append(self.description)
        
        if self.vid and self.pid:
            parts.append(f"VID:PID {self.vid:04X}:{self.pid:04X}")
        
        if self.serial_number:
            parts.append(f"S/N: {self.serial_number}")
            
        return " - ".join(parts)
    
    def __repr__(self):
        return f"SerialPortInfo({self.device}, {self.unique_id})"


class DevicePortManager:
    """Manages serial port enumeration and identification."""
    
    @staticmethod
    def list_ports():
        """List all available serial ports.
        
        Returns:
            List of SerialPortInfo objects
        """
        ports = serial.tools.list_ports.comports()
        return [SerialPortInfo(port) for port in ports]
    
    @staticmethod
    def find_port_by_unique_id(unique_id):
        """Find a port by its unique identifier.
        
        Args:
            unique_id: Unique identifier string from SerialPortInfo.unique_id
            
        Returns:
            Device path (e.g. /dev/ttyACM0) if found, None otherwise
        """
        ports = DevicePortManager.list_ports()
        for port in ports:
            if port.unique_id == unique_id:
                return port.device
        return None
    
    @staticmethod
    def find_port_by_device_name(device_name):
        """Find a port by device name and return its unique ID.
        
        Args:
            device_name: Device path (e.g. /dev/ttyACM0)
            
        Returns:
            SerialPortInfo if found, None otherwise
        """
        ports = DevicePortManager.list_ports()
        for port in ports:
            if port.device == device_name:
                return port
        return None
    
    @staticmethod
    def print_available_ports():
        """Print all available ports to console."""
        ports = DevicePortManager.list_ports()
        
        if not ports:
            log.info("[DevicePortManager] No serial ports found")
            return
        
        log.info(f"[DevicePortManager] Found {len(ports)} serial port(s):")
        for i, port in enumerate(ports, 1):
            log.info(f"  {i}. {port.display_name}")
            log.info(f"     Unique ID: {port.unique_id}")
    
    @staticmethod
    def prompt_user_for_port(device_type, gui_callback=None):
        """Prompt user to select a port from available ports.
        
        Args:
            device_type: String description (e.g. "Motion Controller")
            gui_callback: Optional function to show GUI picker. If provided, should be
                         called as gui_callback(device_type, ports, result_callback)
                         where result_callback will be called with the selected port.
            
        Returns:
            Selected SerialPortInfo object, or None if cancelled
            Note: When using GUI mode, returns immediately and selection happens via callback
        """
        ports = DevicePortManager.list_ports()
        
        if not ports:
            log.info(f"[DevicePortManager] No serial ports available for {device_type}")
            return None
        
        # If GUI callback provided, use GUI mode
        if gui_callback:
            log.info(f"[DevicePortManager] Opening GUI port selector for {device_type}")
            return gui_callback(device_type, ports)
        
        # Otherwise use console mode
        log.info(f"\n=== Select Serial Port for {device_type} ===")
        for i, port in enumerate(ports, 1):
            log.info(f"  {i}. {port.display_name}")
        log.info(f"  0. Skip (use default)")
        
        while True:
            try:
                choice = input(f"Select port (1-{len(ports)}, or 0 to skip): ").strip()
                choice_num = int(choice)
                
                if choice_num == 0:
                    return None
                elif 1 <= choice_num <= len(ports):
                    selected = ports[choice_num - 1]
                    log.info(f"Selected: {selected.display_name}")
                    log.info(f"Unique ID: {selected.unique_id}")
                    return selected
                else:
                    log.info(f"Invalid choice. Please enter 1-{len(ports)} or 0.")
            except ValueError:
                log.info("Invalid input. Please enter a number.")
            except (EOFError, KeyboardInterrupt):
                log.info("\nCancelled")
                return None
