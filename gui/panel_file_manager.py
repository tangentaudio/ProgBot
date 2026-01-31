from logger import get_logger
log = get_logger(__name__)

"""Panel file management for the ProgBot GUI.

This module provides a mixin class that handles loading, saving, and selecting
panel configuration files (.panel files). Also supports general file browsing
with configurable filters for use by other modules (like panel import wizard).
"""
import os
from pathlib import Path
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
    
    # File chooser state
    _file_chooser_path = None
    _file_chooser_filters = None  # e.g., ['.panel'] or ['.kicad_pcb', '.json']
    _file_chooser_callback = None  # Custom callback for non-panel files
    _file_chooser_show_dirs = True  # Whether to show directories for navigation
    
    # ==================== Panel File Loading ====================
    
    def open_panel_file_chooser(self):
        """Open file chooser to load a different panel settings file."""
        self._open_file_chooser(
            title='Select Panel Settings File',
            filters=['.panel'],
            start_path=os.getcwd(),
            show_dirs=True,  # Allow navigating to find panel files
            callback=self.on_panel_file_selected
        )
    
    def open_file_browser(self, title='Select File', filters=None, start_path=None, 
                          callback=None, show_dirs=True):
        """Open file chooser with custom settings.
        
        Args:
            title: Popup title
            filters: List of file extensions to show, e.g., ['.kicad_pcb', '.json']
            start_path: Starting directory (defaults to cwd)
            callback: Function to call with selected path
            show_dirs: Whether to show directories for navigation
        """
        self._open_file_chooser(
            title=title,
            filters=filters or [],
            start_path=start_path or os.getcwd(),
            show_dirs=show_dirs,
            callback=callback
        )
    
    def _open_file_chooser(self, title, filters, start_path, show_dirs, callback):
        """Internal method to open file chooser with given settings."""
        if not self.file_chooser_popup:
            self.file_chooser_popup = Factory.PanelFileChooser()
        
        try:
            # Store settings
            self._file_chooser_path = start_path
            self._file_chooser_filters = filters
            self._file_chooser_callback = callback
            self._file_chooser_show_dirs = show_dirs
            self.selected_panel_path = None
            
            # Update title
            self.file_chooser_popup.title = title
            
            # Update filter label
            if 'filter_label' in self.file_chooser_popup.ids:
                if filters:
                    self.file_chooser_popup.ids.filter_label.text = f"Filter: {', '.join(filters)}"
                else:
                    self.file_chooser_popup.ids.filter_label.text = ''
            
            # Populate files
            self._populate_file_list()
            
            self.file_chooser_popup.open()
        except Exception as e:
            log.info(f"[FileChooser] Error opening file chooser: {e}")
    
    def _populate_file_list(self):
        """Populate the file list with current directory contents."""
        items = []
        path = Path(self._file_chooser_path)
        
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            
            for entry in entries:
                # Skip hidden files
                if entry.name.startswith('.'):
                    continue
                
                is_dir = entry.is_dir()
                
                # Skip directories if not showing them
                if is_dir and not self._file_chooser_show_dirs:
                    continue
                
                # Apply filters to files only
                if not is_dir and self._file_chooser_filters:
                    ext = entry.suffix.lower()
                    if ext not in [f.lower() for f in self._file_chooser_filters]:
                        continue
                
                items.append({
                    'filename': entry.name,
                    'fullpath': str(entry),
                    'is_dir': is_dir,
                    'selected': False
                })
        except PermissionError:
            items.append({
                'filename': '(Permission denied)',
                'fullpath': '',
                'is_dir': False,
                'selected': False
            })
        except Exception as e:
            items.append({
                'filename': f'(Error: {e})',
                'fullpath': '',
                'is_dir': False,
                'selected': False
            })
        
        self.panel_file_data = items
        
        # Update UI
        file_list = self.file_chooser_popup.ids.file_list
        file_list.data = items
        
        if 'path_label' in self.file_chooser_popup.ids:
            self.file_chooser_popup.ids.path_label.text = str(path)
        
        if 'selection_label' in self.file_chooser_popup.ids:
            self.file_chooser_popup.ids.selection_label.text = '(no file selected)'
    
    def on_file_row_pressed(self, fullpath, is_dir=False):
        """Called when a file row is pressed."""
        log.info(f"[FileChooser] Row pressed - fullpath: {fullpath}, is_dir: {is_dir}")
        
        if not fullpath:
            return
        
        try:
            if is_dir:
                # Navigate into directory
                self._file_chooser_path = fullpath
                self._populate_file_list()
            else:
                # Select file
                for item in self.panel_file_data:
                    item['selected'] = (item['fullpath'] == fullpath)
                self.selected_panel_path = fullpath
                
                # Update selection label
                if 'selection_label' in self.file_chooser_popup.ids:
                    self.file_chooser_popup.ids.selection_label.text = os.path.basename(fullpath)
                
                # Force full refresh of RecycleView
                file_list = self.file_chooser_popup.ids.file_list
                file_list.data = []
                Clock.schedule_once(lambda dt: setattr(file_list, 'data', self.panel_file_data), 0.01)
                log.info(f"[FileChooser] Selected: {self.selected_panel_path}")
        except Exception as e:
            log.info(f"[FileChooser] Error on press: {e}")
            import traceback
            traceback.print_exc()
    
    def on_file_chooser_up(self):
        """Navigate to parent directory."""
        if not self._file_chooser_path:
            return
        parent = str(Path(self._file_chooser_path).parent)
        if parent != self._file_chooser_path:
            self._file_chooser_path = parent
            self._populate_file_list()
    
    def on_file_chooser_home(self):
        """Navigate to home directory."""
        self._file_chooser_path = str(Path.home())
        self._populate_file_list()
    
    def on_panel_row_click(self, row_widget):
        """Called when a panel file row is clicked - no longer used."""
        pass
    
    def on_custom_panel_file_selected(self):
        """Called when Select button is pressed in file chooser."""
        if hasattr(self, 'selected_panel_path') and self.selected_panel_path:
            if self._file_chooser_callback:
                self._file_chooser_callback(self.selected_panel_path)
            else:
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
