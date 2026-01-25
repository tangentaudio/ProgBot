"""Panel-specific settings management."""
import json
import os
from pathlib import Path


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
            'operation_mode': 'Program',
            'skip_board_pos': [],
            'network_core_firmware': '/home/steve/fw/merged_CPUNET.hex',
            'main_core_firmware': '/home/steve/fw/merged.hex',
            'use_camera': True,
            'use_picamera': True,
            'camera_index': 0,
            'camera_z_height': 0.0,
            'qr_offset_x': 0.0,  # X offset from board origin to QR code
            'qr_offset_y': 0.0   # Y offset from board origin to QR code
        }
    
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