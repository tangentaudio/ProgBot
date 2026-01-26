from logger import get_logger
log = get_logger(__name__)

"""Settings management for the progbot application."""
import json
import os
from pathlib import Path


class Settings:
    """Handles loading and saving application settings."""
    
    def __init__(self, settings_file=None):
        if settings_file is None:
            # Use settings.json in the same directory as this file
            settings_file = os.path.join(os.path.dirname(__file__), 'settings.json')
        self.settings_file = settings_file
        self.data = self._load_settings()
    
    def _load_settings(self):
        """Load settings from file."""
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f:
                    data = json.load(f)
                    log.info(f"[Settings] Loaded settings from {self.settings_file}")
                    return data
            except Exception as e:
                log.info(f"[Settings] Error loading settings: {e}")
        
        # Return default settings if file doesn't exist
        return self._default_settings()
    
    def _default_settings(self):
        """Return default settings."""
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
            'motion_port_id': '',
            'head_port_id': '',
            'target_port_id': '',
            'camera_offset_x': 50.0,
            'camera_offset_y': 50.0,
            'camera_preview_rotation': 0,  # Camera preview rotation in degrees (0, 90, 180, 270)
            'qr_scan_timeout': 5.0,  # Seconds to wait for QR code (1-10)
            'qr_search_offset': 2.0,  # XY offset in mm to search around QR position (0=disabled)
            'contact_adjust_step': 0.1,  # Y adjustment step in mm when contact fails (0.01-1.0)
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
            with open(self.settings_file, 'w') as f:
                json.dump(self.data, f, indent=2)
            log.info(f"[Settings] Saved settings to {self.settings_file}")
        except Exception as e:
            log.info(f"[Settings] Error saving settings: {e}")
    
    def get_all(self):
        """Get all settings."""
        return self.data.copy()


# Global settings instance
_settings = None

def get_settings():
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

if __name__ == '__main__':
    # This module is imported by kvui.py and not run directly
    pass