"""Settings input handlers for the ProgBot GUI.

This module provides a mixin class that handles all user input changes for
panel and machine settings (grid dimensions, offsets, firmware paths, etc.).
"""
import sequence
from settings import get_settings


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


class SettingsHandlersMixin:
    """Mixin class providing settings input change handlers.
    
    This mixin should be used with AsyncApp and expects the following attributes:
    - self.bot: The ProgBot instance
    - self.panel_settings: PanelSettings instance
    - self.settings_data: Dict of current settings
    - self.root: The Kivy root widget
    - self.populate_grid(): Method to rebuild the grid
    
    All handlers follow the pattern:
    1. Parse and validate the value
    2. Update panel_settings (persistent storage)
    3. Update settings_data (in-memory cache)
    4. Update bot.config (runtime config)
    5. Log the change
    """
    
    # ==================== Grid Dimension Handlers ====================
    
    def on_board_cols_change(self, value):
        """Handle board columns spinner change."""
        try:
            cols = int(value)
            if self.panel_settings:
                self.panel_settings.set('board_cols', value)
            if hasattr(self, 'settings_data'):
                self.settings_data['board_cols'] = value
            print(f"Updated board_num_cols: {cols}")
            # Repopulate grid with new dimensions
            current_rows = self.bot.config.board_num_rows if self.bot else int(get_settings().get('board_rows', '5'))
            self.populate_grid(current_rows, cols)
            # Notify bot of panel change
            if self.bot:
                self.bot.config.board_num_cols = cols
                self.bot.init_panel()
        except ValueError:
            pass
    
    def on_board_rows_change(self, value):
        """Handle board rows spinner change."""
        try:
            rows = int(value)
            if self.panel_settings:
                self.panel_settings.set('board_rows', value)
            if hasattr(self, 'settings_data'):
                self.settings_data['board_rows'] = value
            print(f"Updated board_num_rows: {rows}")
            # Repopulate grid with new dimensions
            current_cols = self.bot.config.board_num_cols if self.bot else int(get_settings().get('board_cols', '2'))
            self.populate_grid(rows, current_cols)
            # Notify bot of panel change
            if self.bot:
                self.bot.config.board_num_rows = rows
                self.bot.init_panel()
        except ValueError:
            pass
    
    def on_col_width_change(self, value):
        """Handle column width text input change."""
        try:
            width = float(value)
            if self.panel_settings:
                self.panel_settings.set('col_width', value)
            if hasattr(self, 'settings_data'):
                self.settings_data['col_width'] = value
            if self.bot:
                self.bot.config.board_col_width = width
            print(f"Updated board_col_width: {width}")
        except ValueError:
            pass
    
    def on_row_height_change(self, value):
        """Handle row height text input change."""
        try:
            height = float(value)
            if self.panel_settings:
                self.panel_settings.set('row_height', value)
            if hasattr(self, 'settings_data'):
                self.settings_data['row_height'] = value
            if self.bot:
                self.bot.config.board_row_height = height
            print(f"Updated board_row_height: {height}")
        except ValueError:
            pass
    
    # ==================== Board Position Handlers ====================
    
    def on_board_x_change(self, value):
        """Handle board X text input change."""
        try:
            board_x = float(value)
            if self.panel_settings:
                self.panel_settings.set('board_x', value)
            if hasattr(self, 'settings_data'):
                self.settings_data['board_x'] = value
            if self.bot:
                self.bot.config.board_x = board_x
            print(f"Updated board_x: {board_x}")
        except ValueError:
            pass
    
    def on_board_y_change(self, value):
        """Handle board Y text input change."""
        try:
            board_y = float(value)
            if self.panel_settings:
                self.panel_settings.set('board_y', value)
            if hasattr(self, 'settings_data'):
                self.settings_data['board_y'] = value
            if self.bot:
                self.bot.config.board_y = board_y
            print(f"Updated board_y: {board_y}")
        except ValueError:
            pass
    
    def on_probe_plane_change(self, value):
        """Handle probe plane to board text input change."""
        try:
            probe_plane = float(value)
            if self.panel_settings:
                self.panel_settings.set('probe_plane', value)
            if hasattr(self, 'settings_data'):
                self.settings_data['probe_plane'] = value
            if self.bot:
                self.bot.config.probe_plane_to_board = probe_plane
        except ValueError:
            pass
    
    def on_contact_adjust_step_change(self, value):
        """Handle contact adjust step text input change."""
        try:
            step = float(value)
            # Validate range (0.01 to 1.0 mm)
            if step < 0.01 or step > 1.0:
                debug_log(f"[on_contact_adjust_step_change] Invalid value {step}, must be 0.01-1.0")
                return
            # Save to main settings (machine config, not panel)
            settings = get_settings()
            settings.set('contact_adjust_step', step)
            debug_log(f"[on_contact_adjust_step_change] Saved step={step} to settings")
            if self.bot:
                self.bot.config.contact_adjust_step = step
                debug_log(f"[on_contact_adjust_step_change] Updated bot.config.contact_adjust_step={step}")
            print(f"Updated contact_adjust_step: {step}")
        except ValueError:
            debug_log(f"[on_contact_adjust_step_change] ValueError for value: {value}")
            pass
    
    # ==================== QR Code Handlers ====================
    
    def on_qr_offset_x_change(self, value):
        """Handle QR offset X text input change."""
        try:
            qr_offset_x = float(value)
            sequence.debug_log(f"[on_qr_offset_x_change] Setting qr_offset_x to {qr_offset_x}")
            if self.panel_settings:
                self.panel_settings.set('qr_offset_x', qr_offset_x)
            if hasattr(self, 'settings_data'):
                self.settings_data['qr_offset_x'] = qr_offset_x
            if self.bot:
                self.bot.config.qr_offset_x = qr_offset_x
                sequence.debug_log(f"[on_qr_offset_x_change] Bot config updated: {self.bot.config.qr_offset_x}")
        except ValueError:
            pass
    
    def on_qr_offset_y_change(self, value):
        """Handle QR offset Y text input change."""
        try:
            qr_offset_y = float(value)
            sequence.debug_log(f"[on_qr_offset_y_change] Setting qr_offset_y to {qr_offset_y}")
            if self.panel_settings:
                self.panel_settings.set('qr_offset_y', qr_offset_y)
            if hasattr(self, 'settings_data'):
                self.settings_data['qr_offset_y'] = qr_offset_y
            if self.bot:
                self.bot.config.qr_offset_y = qr_offset_y
                sequence.debug_log(f"[on_qr_offset_y_change] Bot config updated: {self.bot.config.qr_offset_y}")
            print(f"Updated qr_offset_y: {qr_offset_y}")
        except ValueError:
            pass
    
    def on_qr_scan_timeout_change(self, value):
        """Handle QR scan timeout text input change."""
        try:
            timeout = float(value)
            # Clamp to 1-10 second range
            timeout = max(1.0, min(10.0, timeout))
            # Save to main settings (machine config, not panel)
            settings = get_settings()
            settings.set('qr_scan_timeout', timeout)
            if self.bot:
                self.bot.config.qr_scan_timeout = timeout
            # Update the input field to show clamped value
            if hasattr(self, 'root') and self.root:
                timeout_input = self.root.ids.get('qr_scan_timeout_input')
                if timeout_input and timeout_input.text != str(timeout):
                    timeout_input.text = str(timeout)
            print(f"Updated qr_scan_timeout: {timeout}s")
        except ValueError:
            pass
    
    def on_qr_search_offset_change(self, value):
        """Handle QR search offset text input change."""
        try:
            offset = float(value)
            # Clamp to 0-10mm range (0 = disabled)
            offset = max(0.0, min(10.0, offset))
            # Save to main settings (machine config, not panel)
            settings = get_settings()
            settings.set('qr_search_offset', offset)
            if self.bot:
                self.bot.config.qr_search_offset = offset
            # Update the input field to show clamped value
            if hasattr(self, 'root') and self.root:
                offset_input = self.root.ids.get('qr_search_offset_input')
                if offset_input and offset_input.text != str(offset):
                    offset_input.text = str(offset)
            print(f"Updated qr_search_offset: {offset}mm")
        except ValueError:
            pass
    
    # ==================== Camera Handlers ====================
    
    def on_camera_offset_x_change(self, value):
        """Handle camera offset X text input change."""
        try:
            offset_x = float(value)
            # Save to main settings (machine config, not panel)
            settings = get_settings()
            settings.set('camera_offset_x', offset_x)
            debug_log(f"[on_camera_offset_x_change] Saved offset_x={offset_x} to settings")
            if self.bot:
                self.bot.config.camera_offset_x = offset_x
                debug_log(f"[on_camera_offset_x_change] Updated bot.config.camera_offset_x={offset_x}")
            print(f"Updated camera_offset_x: {offset_x}")
        except ValueError:
            pass
    
    def on_camera_offset_y_change(self, value):
        """Handle camera offset Y text input change."""
        try:
            offset_y = float(value)
            # Save to main settings (machine config, not panel)
            settings = get_settings()
            settings.set('camera_offset_y', offset_y)
            debug_log(f"[on_camera_offset_y_change] Saved offset_y={offset_y} to settings")
            if self.bot:
                self.bot.config.camera_offset_y = offset_y
                debug_log(f"[on_camera_offset_y_change] Updated bot.config.camera_offset_y={offset_y}")
            print(f"Updated camera_offset_y: {offset_y}")
        except ValueError:
            pass

    def on_camera_rotation_change(self, value):
        """Handle camera preview rotation spinner change."""
        try:
            # Parse the rotation value (e.g., "90°" -> 90)
            rotation = int(value.replace('°', ''))
            # Save to main settings (machine config, not panel)
            settings = get_settings()
            settings.set('camera_preview_rotation', rotation)
            debug_log(f"[on_camera_rotation_change] Saved rotation={rotation} to settings")
            print(f"Updated camera_preview_rotation: {rotation}°")
        except ValueError:
            pass

    def on_use_camera_change(self, active):
        """Handle QR code scan checkbox change."""
        if self.bot:
            self.bot.config.use_camera = active
            # Update vision controller availability
            if active and not self.bot.vision:
                # Re-create vision controller if it was disabled
                from vision_controller import VisionController
                self.bot.vision = VisionController(
                    self.bot.update_phase,
                    use_picamera=self.bot.config.use_picamera,
                    camera_index=self.bot.config.camera_index
                )
            elif not active and self.bot.vision:
                # Disable vision controller when camera is turned off
                self.bot.vision = None
        if self.panel_settings:
            self.panel_settings.set('use_camera', active)
        print(f"Updated use_camera: {active}")
    
    # ==================== Operation Mode Handler ====================
    
    def on_operation_change(self, value):
        """Handle operation mode spinner change."""
        # Map display text to OperationMode enum values
        mode_mapping = {
            "Identify Only": sequence.OperationMode.IDENTIFY_ONLY,
            "Program": sequence.OperationMode.PROGRAM,
            "Program & Test": sequence.OperationMode.PROGRAM_AND_TEST,
            "Test Only": sequence.OperationMode.TEST_ONLY,
        }
        selected = mode_mapping.get(value, sequence.OperationMode.PROGRAM)
        if self.bot:
            self.bot.config.operation_mode = selected
        if self.panel_settings:
            self.panel_settings.set('operation_mode', value)
        if hasattr(self, 'settings_data'):
            self.settings_data['operation_mode'] = value
        print(f"Updated operation_mode: {selected}")
    
    # ==================== Firmware Handlers ====================

    def on_network_firmware_change(self, value):
        """Handle network core firmware path change."""
        if self.bot:
            self.bot.config.network_core_firmware = value
            # Update the programmer controller with new path
            if self.bot.programmer:
                self.bot.programmer.network_core_firmware = value
        if self.panel_settings:
            self.panel_settings.set('network_core_firmware', value)
        print(f"Updated network_core_firmware: {value}")

    def on_main_firmware_change(self, value):
        """Handle main core firmware path change."""
        if self.bot:
            self.bot.config.main_core_firmware = value
            # Update the programmer controller with new path
            if self.bot.programmer:
                self.bot.programmer.main_core_firmware = value
        if self.panel_settings:
            self.panel_settings.set('main_core_firmware', value)
        print(f"Updated main_core_firmware: {value}")
    
    # ==================== Helper Methods ====================
    
    def _sync_settings_to_config(self):
        """Sync current panel settings to bot config before operations that need them.
        
        Note: This reads from panel_settings. For reading from UI widgets directly,
        use _sync_panel_settings_to_config in kvui.py instead.
        """
        if not self.bot or not self.panel_settings:
            debug_log("[_sync_settings_to_config] Missing bot or panel_settings")
            return
        
        try:
            # Get QR offsets from panel settings
            qr_offset_x = self.panel_settings.get('qr_offset_x', 0.0)
            qr_offset_y = self.panel_settings.get('qr_offset_y', 0.0)
            
            # Get camera offsets from main settings
            settings = get_settings()
            camera_offset_x = settings.get('camera_offset_x', 0.0)
            camera_offset_y = settings.get('camera_offset_y', 0.0)
            
            # Update bot config
            self.bot.config.qr_offset_x = float(qr_offset_x) if qr_offset_x else 0.0
            self.bot.config.qr_offset_y = float(qr_offset_y) if qr_offset_y else 0.0
            self.bot.config.camera_offset_x = float(camera_offset_x) if camera_offset_x else 0.0
            self.bot.config.camera_offset_y = float(camera_offset_y) if camera_offset_y else 0.0
            
            debug_log(f"[_sync_settings_to_config] Updated config: qr_offset=({self.bot.config.qr_offset_x},{self.bot.config.qr_offset_y}), camera_offset=({self.bot.config.camera_offset_x},{self.bot.config.camera_offset_y})")
        except Exception as e:
            debug_log(f"[_sync_settings_to_config] Error: {e}")
