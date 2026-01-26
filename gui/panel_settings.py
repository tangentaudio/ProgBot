"""Panel-specific settings management."""
import json
import os
from pathlib import Path


def _get_default_programmer_config():
    """Get default programmer configuration.
    
    Imported lazily to avoid circular imports.
    """
    from programmers import get_default_programmer_config
    return get_default_programmer_config('nordic_nrf')


class PanelSettings:
    """Handles loading and saving panel-specific settings."""
    
    def __init__(self, panel_file=None):
        if panel_file is None:
            # Try to load the most recently used panel file from app settings
            from settings import get_settings
            app_settings = get_settings()
            panel_file = app_settings.get('last_panel_file')
            if panel_file and os.path.exists(panel_file):
                pass  # Use the saved file
            else:
                # Default to default.panel in the same directory
                panel_file = os.path.join(os.path.dirname(__file__), 'default.panel')
        
        self.panel_file = panel_file
        self.data = self._load_settings()
    
    def _load_settings(self):
        """Load panel settings from file."""
        if os.path.exists(self.panel_file):
            try:
                with open(self.panel_file, 'r') as f:
                    data = json.load(f)
                    print(f"[PanelSettings] Loaded panel from {self.panel_file}")
                    # Migrate old format if needed
                    data = self._migrate_settings(data)
                    return data
            except Exception as e:
                print(f"[PanelSettings] Error loading panel: {e}")
        
        # Return default settings if file doesn't exist
        return self._default_settings()
    
    def _default_settings(self):
        """Return default panel settings."""
        return {
            'board_cols': '2',
            'board_rows': '5',
            'col_width': '48.0',
            'row_height': '29.0',
            'board_x': '110.2',
            'board_y': '121.0',
            'probe_plane': '4.0',
            'skip_board_pos': [],
            'use_camera': True,
            'use_picamera': True,
            'camera_index': 0,
            'camera_z_height': 0.0,
            'qr_offset_x': 0.0,  # X offset from board origin to QR code
            'qr_offset_y': 0.0,  # Y offset from board origin to QR code
            # Phase enable flags
            'vision_enabled': True,  # Enable vision/QR scanning phase
            'programming_enabled': True,  # Enable programming phase
            'provision_enabled': False,  # Enable provisioning phase
            'test_enabled': False,  # Enable testing phase
            # Programmer configuration (nested)
            'programmer': _get_default_programmer_config(),
        }
    
    def _migrate_settings(self, data):
        """Migrate old settings format to new format."""
        # Migrate legacy firmware paths to programmer node
        if 'programmer' not in data:
            data['programmer'] = _get_default_programmer_config()
            
            # Migrate old firmware paths if they exist
            if 'network_core_firmware' in data:
                data['programmer']['firmware']['network_core'] = data.pop('network_core_firmware')
            if 'main_core_firmware' in data:
                data['programmer']['firmware']['main_core'] = data.pop('main_core_firmware')
            
            # Migrate old operation_mode to programmer steps
            if 'operation_mode' in data:
                mode = data.pop('operation_mode')
                if mode == 'Identify Only':
                    data['programmer']['steps'] = {
                        'identify': True,
                        'recover': False,
                        'erase': False,
                        'program': False,
                        'lock': False,
                    }
                # Other modes use default steps
        
        return data
    
    def get(self, key, default=None):
        """Get a setting value."""
        return self.data.get(key, default)
    
    def set(self, key, value):
        """Set a setting value and save to file."""
        self.data[key] = value
        self._save_settings()
    
    def set_multiple(self, updates):
        """Set multiple settings at once and save."""
        self.data.update(updates)
        self._save_settings()
    
    def _save_settings(self):
        """Save settings to file."""
        try:
            with open(self.panel_file, 'w') as f:
                json.dump(self.data, f, indent=2)
            
            # Remember this file in app settings
            from settings import get_settings
            app_settings = get_settings()
            app_settings.set('last_panel_file', self.panel_file)
        except Exception as e:
            print(f"[PanelSettings] Error saving panel: {e}")
    
    def get_all(self):
        """Get all panel settings."""
        return self.data.copy()
    
    # ==================== Programmer Config Helpers ====================
    
    def get_programmer_type(self):
        """Get the programmer type ID."""
        return self.data.get('programmer', {}).get('type', 'nordic_nrf')
    
    def set_programmer_type(self, type_id):
        """Set the programmer type and reset to defaults for that type."""
        from programmers import get_default_programmer_config
        self.data['programmer'] = get_default_programmer_config(type_id)
        self._save_settings()
    
    def get_programmer_steps(self):
        """Get programmer step enable states."""
        return self.data.get('programmer', {}).get('steps', {})
    
    def set_programmer_step(self, step_id, enabled):
        """Set a programmer step enable state."""
        if 'programmer' not in self.data:
            self.data['programmer'] = _get_default_programmer_config()
        if 'steps' not in self.data['programmer']:
            self.data['programmer']['steps'] = {}
        self.data['programmer']['steps'][step_id] = enabled
        self._save_settings()
    
    def get_programmer_firmware(self):
        """Get programmer firmware paths."""
        return self.data.get('programmer', {}).get('firmware', {})
    
    def set_programmer_firmware(self, slot_id, path):
        """Set a programmer firmware path."""
        if 'programmer' not in self.data:
            self.data['programmer'] = _get_default_programmer_config()
        if 'firmware' not in self.data['programmer']:
            self.data['programmer']['firmware'] = {}
        self.data['programmer']['firmware'][slot_id] = path
        self._save_settings()
    
    def get_programmer_config(self):
        """Get full programmer configuration node."""
        if 'programmer' not in self.data:
            self.data['programmer'] = _get_default_programmer_config()
        return self.data['programmer']
    
    # ==================== End Programmer Config Helpers ====================
    
    def load_file(self, filepath: str):
        """Load settings from a different panel file."""
        if os.path.exists(filepath):
            self.panel_file = filepath
            self.data = self._load_settings()
            # Save the filename in app settings
            from settings import get_settings
            app_settings = get_settings()
            app_settings.set('last_panel_file', filepath)
        else:
            print(f"[PanelSettings] File not found: {filepath}")


# Global panel settings instance
_panel_settings = None

def get_panel_settings():
    """Get the global panel settings instance."""
    global _panel_settings
    if _panel_settings is None:
        _panel_settings = PanelSettings()
    return _panel_settings


def find_panel_files(directory=None):
    """Find all .panel files in a directory."""
    if directory is None:
        directory = os.path.dirname(__file__)
    
    panel_files = []
    try:
        for file in Path(directory).glob('*.panel'):
            panel_files.append(str(file))
    except Exception as e:
        print(f"[PanelSettings] Error searching for panel files: {e}")
    
    return sorted(panel_files)

if __name__ == '__main__':
    # This module is imported by kvui.py and not run directly
    pass