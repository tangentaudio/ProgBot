from logger import get_logger
log = get_logger(__name__)

"""Panel file management for the ProgBot GUI.

This module provides a mixin class that handles loading, saving, and selecting
panel configuration files (.panel files).
"""
import os
from kivy.clock import Clock
from kivy.factory import Factory
from panel_settings import find_panel_files
from settings import get_settings
from numpad_keyboard import switch_keyboard_layout


class PanelFileManagerMixin:
    """Mixin class providing panel file load/save functionality.
    
    This mixin should be used with AsyncApp and expects the following attributes:
    - self.file_chooser_popup: The file chooser popup widget
    - self.save_panel_dialog: The save panel dialog widget
    - self.panel_settings: PanelSettings instance
    - self.panel_file_label: Label showing current panel filename
    - self.settings_data: Dict of current settings
    - self.root: The Kivy root widget
    - self._apply_settings_to_widgets_now(): Method to refresh widgets
    - self._reload_bot_config(): Method to reload bot configuration
    """
    
    # ==================== Panel File Loading ====================
    
    def open_panel_file_chooser(self):
        """Open file chooser to load a different panel settings file."""
        if not self.file_chooser_popup:
            self.file_chooser_popup = Factory.PanelFileChooser()
        
        try:
            # Populate with .panel files from working directory
            panel_files = find_panel_files()
            items = []
            for fullpath in panel_files:
                items.append({
                    'filename': os.path.basename(fullpath),
                    'fullpath': fullpath,
                    'selected': False
                })
            
            self.panel_file_data = items
            file_list = self.file_chooser_popup.ids.file_list
            file_list.data = self.panel_file_data
            self.selected_panel_path = None
            
            self.file_chooser_popup.open()
        except Exception as e:
            log.info(f"[PanelChooser] Error opening file chooser: {e}")
    
    def on_file_row_pressed(self, fullpath):
        """Called when a file row is pressed."""
        log.info(f"[PanelChooser] Row pressed - fullpath: {fullpath}")
        try:
            # Select file and update all items
            for item in self.panel_file_data:
                item['selected'] = (item['fullpath'] == fullpath)
            self.selected_panel_path = fullpath
            # Force full refresh of RecycleView
            file_list = self.file_chooser_popup.ids.file_list
            file_list.data = []
            Clock.schedule_once(lambda dt: setattr(file_list, 'data', self.panel_file_data), 0.01)
            log.info(f"[PanelChooser] Selected: {self.selected_panel_path}")
        except Exception as e:
            log.info(f"[PanelChooser] Error on press: {e}")
            import traceback
            traceback.print_exc()
    
    def on_panel_row_click(self, row_widget):
        """Called when a panel file row is clicked - no longer used."""
        pass
    
    def on_custom_panel_file_selected(self):
        """Called when Load button is pressed in custom file chooser."""
        if hasattr(self, 'selected_panel_path') and self.selected_panel_path:
            self.on_panel_file_selected(self.selected_panel_path)

    def on_panel_file_selected(self, path):
        """Called when a panel file is selected from the file chooser."""
        if not path or not self.panel_settings:
            return
        
        try:
            self.panel_settings.load_file(path)
            self.settings_data = self.panel_settings.get_all()
            # Update the panel file label
            panel_name = os.path.basename(path)
            if self.panel_file_label:
                self.panel_file_label.text = panel_name
            # Re-apply settings to widgets
            Clock.schedule_once(lambda dt: self._apply_settings_to_widgets_now())
            # Rebuild bot config with new settings
            Clock.schedule_once(lambda dt: self._reload_bot_config())
            log.info(f"[PanelChooser] Loaded panel: {path}")
        except Exception as e:
            log.info(f"[PanelChooser] Error loading panel: {e}")
    
    # ==================== Panel File Saving ====================

    def open_save_panel_dialog(self):
        """Open dialog to save current panel with a new name."""
        if not self.save_panel_dialog:
            self.save_panel_dialog = Factory.SavePanelDialog()
        
        try:
            # Pre-populate with current filename (without .panel extension)
            if hasattr(self.save_panel_dialog, 'ids') and 'panel_name_input' in self.save_panel_dialog.ids:
                panel_input = self.save_panel_dialog.ids.panel_name_input
                if self.panel_settings:
                    current_file = os.path.basename(self.panel_settings.panel_file)
                    # Remove .panel extension if present
                    if current_file.endswith('.panel'):
                        current_file = current_file[:-6]
                    panel_input.text = current_file
            
            self.save_panel_dialog.open()
            
            # Focus and show keyboard after dialog opens
            Clock.schedule_once(lambda dt: self._focus_panel_input(), 0.1)
        except Exception as e:
            log.info(f"[SavePanel] Error opening save dialog: {e}")

    def _focus_panel_input(self):
        """Focus the panel name input and trigger keyboard."""
        try:
            if hasattr(self.save_panel_dialog, 'ids') and 'panel_name_input' in self.save_panel_dialog.ids:
                panel_input = self.save_panel_dialog.ids.panel_name_input
                panel_input.focus = True
                from kivy.core.window import Window
                # Reset to default QWERTY layout for text input
                self.set_keyboard_layout('qwerty.json')
                Window.show_keyboard()
        except Exception as e:
            log.info(f"[SavePanel] Error focusing input: {e}")
    
    def set_keyboard_layout(self, layout):
        """Switch the virtual keyboard layout."""
        switch_keyboard_layout(layout)

    def on_save_panel_confirmed(self, filename: str):
        """Called when user confirms saving panel with new name."""
        if not filename or not self.panel_settings:
            log.info("[SavePanel] No filename provided")
            return
        
        try:
            # Clean up the filename
            filename = filename.strip()
            
            # Remove any existing .panel extension if user added it
            if filename.endswith('.panel'):
                filename = filename[:-6]
            
            # Remove any other extension or dots
            filename = os.path.splitext(filename)[0]
            
            # Validate filename (basic check)
            if not filename or all(c in '._-' for c in filename):
                log.info("[SavePanel] Invalid filename")
                return
            
            # Add .panel extension
            filename = filename + '.panel'
            
            # Build full path in current directory
            filepath = os.path.join(os.getcwd(), filename)
            
            # Save current settings to new file
            self.panel_settings.panel_file = filepath
            self.panel_settings._save_settings()
            
            # Update the display
            if self.panel_file_label:
                self.panel_file_label.text = filename
            
            # Remember this file
            app_settings = get_settings()
            app_settings.set('last_panel_file', filepath)
            
            log.info(f"[SavePanel] Saved panel to: {filepath}")
        except Exception as e:
            log.info(f"[SavePanel] Error saving panel: {e}")
    
    # ==================== Helper Methods ====================
    
    def _apply_settings_to_widgets_now(self):
        """Re-apply current settings to all widgets."""
        if not hasattr(self, 'root') or not self.root:
            return
        self._apply_settings_to_widgets(self.root, self.settings_data)

    def _reload_bot_config(self):
        """Rebuild bot configuration and grid after loading a new panel."""
        if not self.bot:
            return
        
        try:
            # Rebuild config from settings
            new_config = self._config_from_settings()
            
            # Update bot config
            self.bot.config = new_config
            
            # Rebuild the grid with new dimensions
            rows = new_config.board_num_rows
            cols = new_config.board_num_cols
            self.populate_grid(rows, cols)
            
            # Reinitialize panel in bot
            self.bot.init_panel()
            
            log.info(f"[AsyncApp] Reloaded bot config: {rows}x{cols} grid")
        except Exception as e:
            log.info(f"[AsyncApp] Error reloading bot config: {e}")
