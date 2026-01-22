"""GUI Serial Port Selector for Kivy applications."""
from typing import List, Callable, Optional
from concurrent.futures import Future
from kivy.factory import Factory
from kivy.clock import Clock


class SerialPortSelector:
    """Manages GUI-based serial port selection dialogs."""
    
    def __init__(self):
        self.popup = None
        self.port_data = []
        self.selected_index = None
        self.pending_selection = None  # (device_type, callback, available_ports)
        self.result_future = None
    
    def show_dialog(self, device_type: str, available_ports: List, callback: Callable):
        """Show the serial port selection dialog.
        
        Args:
            device_type: Human-readable device type string (e.g., "Motion Controller")
            available_ports: List of SerialPortInfo objects to display
            callback: Function to call with selected port (SerialPortInfo or None)
        """
        try:
            # Create a fresh popup for each selection to avoid state issues
            self.popup = Factory.SerialPortChooser()
            
            # Store context for callback
            self.pending_selection = (device_type, callback, available_ports)
            
            # Update dialog title
            if hasattr(self.popup, 'ids') and 'device_type_label' in self.popup.ids:
                self.popup.ids.device_type_label.text = f'Select port for: {device_type}'
            
            # Build display data for RecycleView
            self.port_data = []
            for idx, port in enumerate(available_ports):
                # Build description line
                desc_parts = []
                if port.description and port.description != 'n/a':
                    desc_parts.append(port.description)
                if port.manufacturer and port.manufacturer != 'n/a':
                    desc_parts.append(port.manufacturer)
                if port.vid is not None and port.pid is not None:
                    desc_parts.append(f"VID:PID {port.vid:04X}:{port.pid:04X}")
                if port.serial_number:
                    desc_parts.append(f"S/N: {port.serial_number}")
                
                description = ' - '.join(desc_parts) if desc_parts else 'Unknown device'
                
                self.port_data.append({
                    'port_device': port.device,
                    'port_description': description,
                    'port_unique_id': f'ID: {port.unique_id}',
                    'port_index': idx,
                    'selected': False
                })
            
            # Set RecycleView data
            port_list = self.popup.ids.port_list
            port_list.data = self.port_data
            self.selected_index = None
            
            # Show the dialog
            self.popup.open()
            print(f"[SerialPortSelector] Opened dialog for {device_type} with {len(available_ports)} ports")
        except Exception as e:
            print(f"[SerialPortSelector] Error opening dialog: {e}")
            import traceback
            traceback.print_exc()
            # Fall back to returning None
            if callback:
                callback(None)
    
    def on_row_pressed(self, port_index: int):
        """Called when a port row is tapped.
        
        Args:
            port_index: Index of the selected port
        """
        print(f"[SerialPortSelector] Row pressed - index: {port_index}")
        try:
            # Select port and update all items
            for item in self.port_data:
                item['selected'] = (item['port_index'] == port_index)
            self.selected_index = port_index
            
            # Force full refresh of RecycleView
            port_list = self.popup.ids.port_list
            port_list.data = []
            Clock.schedule_once(lambda dt: setattr(port_list, 'data', self.port_data), 0.01)
            print(f"[SerialPortSelector] Selected port index: {self.selected_index}")
        except Exception as e:
            print(f"[SerialPortSelector] Error on press: {e}")
            import traceback
            traceback.print_exc()
    
    def on_select_pressed(self):
        """Called when the Select button is pressed."""
        if self.pending_selection is None:
            print("[SerialPortSelector] on_select_pressed: No pending selection")
            return
        
        device_type, callback, available_ports = self.pending_selection
        
        # Clear pending_selection immediately to prevent multiple calls
        self.pending_selection = None
        
        def do_callback():
            """Execute callback after dialog is dismissed."""
            try:
                if self.selected_index is not None:
                    if 0 <= self.selected_index < len(available_ports):
                        selected_port = available_ports[self.selected_index]
                        print(f"[SerialPortSelector] Selected: {selected_port.device} for {device_type}")
                        callback(selected_port)
                    else:
                        print(f"[SerialPortSelector] Invalid index: {self.selected_index}")
                        callback(None)
                else:
                    print(f"[SerialPortSelector] No port selected")
                    callback(None)
            except Exception as e:
                print(f"[SerialPortSelector] Error in callback: {e}")
                import traceback
                traceback.print_exc()
                callback(None)
            finally:
                self.selected_index = None
        
        # Schedule callback to run after dialog dismiss animation completes
        Clock.schedule_once(lambda dt: do_callback(), 0.2)
    
    def show_and_wait_async(self, device_type: str, available_ports: List) -> Future:
        """Show dialog and return a Future that resolves to the selected port.
        
        This is useful for async code that needs to await the selection.
        
        Args:
            device_type: Human-readable device type string
            available_ports: List of SerialPortInfo objects
            
        Returns:
            Future that will contain the selected SerialPortInfo or None
        """
        self.result_future = Future()
        
        def handle_callback(selected_port):
            if not self.result_future.done():
                self.result_future.set_result(selected_port)
        
        self.show_dialog(device_type, available_ports, handle_callback)
        return self.result_future
