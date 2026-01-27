from logger import get_logger
log = get_logger(__name__)

"""Provision Step Editor dialog for editing individual provisioning steps.

This module provides a modal dialog for creating and editing provisioning
script steps with fields for send command, expect pattern, timeout, retries,
and other options.
"""
import re
from kivy.clock import Clock
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.core.window import Window


def _escape_for_display(text: str) -> str:
    """Convert actual escape chars to visible escape sequences for editing."""
    if not text:
        return text
    return text.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')


def _unescape_from_display(text: str) -> str:
    """Convert visible escape sequences back to actual escape chars."""
    if not text:
        return text
    # Process in order: handle escaped backslashes last
    result = text.replace('\\n', '\n').replace('\\r', '\r').replace('\\t', '\t').replace('\\\\', '\\')
    return result

# Load the step editor KV file
Builder.load_file('provision_step_editor.kv')


class ProvisionStepEditorController:
    """Controller for the provision step editor dialog.
    
    This class manages the step editor popup for creating/editing
    individual provisioning steps.
    
    Attributes:
        app: Reference to the main Kivy App instance
        popup: The ProvisionStepEditorPopup widget instance
        step_index: Index of step being edited (-1 for new step)
        step_data: Current step data being edited
        on_save_callback: Callback when step is saved
    """
    
    def __init__(self, app):
        """Initialize the step editor controller.
        
        Args:
            app: The main Kivy App instance
        """
        self.app = app
        self.popup = None
        self.step_index = -1
        self.step_data = {}
        self.on_save_callback = None
        self._regex_valid = True
        self._saved_allow_vkeyboard = None  # Track original vkeyboard state
    
    def open(self, step_data=None, step_index=-1, on_save=None):
        """Open the step editor dialog.
        
        Args:
            step_data: Existing step data to edit, or None for new step
            step_index: Index of step being edited (-1 for new)
            on_save: Callback function(step_data, step_index) when saved
        """
        log.debug(f"[StepEditor] Opening for step {step_index}")
        
        # Create popup if needed
        if not self.popup:
            self.popup = Factory.ProvisionStepEditorPopup()
        
        # Disable on-screen keyboard for this dialog
        # Just set allow_vkeyboard=False - don't release keyboards to avoid crash
        self._saved_allow_vkeyboard = Window.allow_vkeyboard
        self._saved_docked_vkeyboard = Window.docked_vkeyboard
        Window.allow_vkeyboard = False
        
        # Reset keyboard toggle if present
        if kbd_toggle := self.popup.ids.get('pse_keyboard_toggle'):
            kbd_toggle.active = False
        
        self.step_index = step_index
        self.step_data = dict(step_data) if step_data else {}
        self.on_save_callback = on_save
        
        # Update title
        if title_label := self.popup.ids.get('pse_title'):
            if step_index >= 0:
                title_label.text = f'Edit Step {step_index + 1}'
            else:
                title_label.text = 'New Step'
        
        # Populate fields from step_data
        self._populate_fields()
        
        # Open popup
        self.popup.open()
    
    def _populate_fields(self):
        """Populate dialog fields from step_data."""
        if not self.popup:
            return
        
        ids = self.popup.ids
        
        # Description
        if desc := ids.get('pse_description'):
            desc.text = self.step_data.get('description', '')
        
        # Send command - convert escape sequences for display
        if send := ids.get('pse_send'):
            send_text = self.step_data.get('send', '')
            # Show actual escape sequences as visible text for editing
            send.text = _escape_for_display(send_text)
        
        # Expect pattern
        if expect := ids.get('pse_expect'):
            expect.text = self.step_data.get('expect', '')
        
        # Timeout - use Spinner with (default) option
        if timeout := ids.get('pse_timeout'):
            val = self.step_data.get('timeout')
            timeout.text = str(val) if val is not None else '(default)'
        
        # Retries - use Spinner with (default) option
        if retries := ids.get('pse_retries'):
            val = self.step_data.get('retries')
            retries.text = str(val) if val is not None else '(default)'
        
        # Retry delay - use Spinner with (default) option
        if retry_delay := ids.get('pse_retry_delay'):
            val = self.step_data.get('retry_delay')
            retry_delay.text = str(val) if val is not None else '(default)'
        
        # On fail
        if on_fail := ids.get('pse_on_fail'):
            val = self.step_data.get('on_fail', '')
            if val and val in ['abort', 'skip', 'continue']:
                on_fail.text = val
            else:
                on_fail.text = '(default)'
        
        # Validate initial regex
        self.validate_regex(self.step_data.get('expect', ''))
    
    def _collect_fields(self):
        """Collect field values into step_data dict."""
        if not self.popup:
            return {}
        
        ids = self.popup.ids
        result = {}
        
        # Description (required)
        if desc := ids.get('pse_description'):
            result['description'] = desc.text.strip()
        
        # Send command - convert visible escape sequences back to actual chars
        if send := ids.get('pse_send'):
            result['send'] = _unescape_from_display(send.text)
        
        # Expect pattern
        if expect := ids.get('pse_expect'):
            text = expect.text.strip()
            if text:
                result['expect'] = text
        
        # Timeout (optional) - from Spinner
        if timeout := ids.get('pse_timeout'):
            text = timeout.text
            if text and text != '(default)':
                try:
                    result['timeout'] = float(text)
                except ValueError:
                    pass
        
        # Retries (optional) - from Spinner
        if retries := ids.get('pse_retries'):
            text = retries.text
            if text and text != '(default)':
                try:
                    result['retries'] = int(text)
                except ValueError:
                    pass
        
        # Retry delay (optional) - from Spinner
        if retry_delay := ids.get('pse_retry_delay'):
            text = retry_delay.text
            if text and text != '(default)':
                try:
                    result['retry_delay'] = float(text)
                except ValueError:
                    pass
        
        # On fail (optional)
        if on_fail := ids.get('pse_on_fail'):
            if on_fail.text and on_fail.text != '(default)':
                result['on_fail'] = on_fail.text
        
        return result
    
    def validate_regex(self, pattern):
        """Validate the expect pattern regex.
        
        Args:
            pattern: The regex pattern to validate
            
        Returns:
            True if valid, False otherwise
        """
        if not self.popup:
            return True
        
        status_label = self.popup.ids.get('pse_regex_status')
        
        if not pattern or not pattern.strip():
            self._regex_valid = True
            if status_label:
                status_label.text = ''
                status_label.color = (0.5, 0.5, 0.5, 1)
            return True
        
        try:
            # Try to compile the regex
            re.compile(pattern)
            self._regex_valid = True
            
            # Check for named groups
            named_groups = re.findall(r'\(\?P<(\w+)>', pattern)
            if named_groups:
                if status_label:
                    status_label.text = f'✓ Captures: {", ".join(named_groups)}'
                    status_label.color = (0.4, 0.8, 0.4, 1)
            else:
                if status_label:
                    status_label.text = '✓ Valid pattern'
                    status_label.color = (0.5, 0.7, 0.5, 1)
            
            return True
            
        except re.error as e:
            self._regex_valid = False
            if status_label:
                status_label.text = f'✗ {str(e)}'
                status_label.color = (0.9, 0.4, 0.4, 1)
            return False
    
    def save_step(self):
        """Save the step and close the dialog."""
        if not self._regex_valid:
            log.warning("[StepEditor] Cannot save - invalid regex")
            return
        
        step_data = self._collect_fields()
        
        # Validate required fields
        if not step_data.get('description'):
            log.warning("[StepEditor] Description is required")
            return
        
        log.debug(f"[StepEditor] Saving step: {step_data}")
        
        # Call the save callback
        if self.on_save_callback:
            self.on_save_callback(step_data, self.step_index)
        
        self.close()
    
    def cancel(self):
        """Cancel editing and close the dialog."""
        log.debug("[StepEditor] Cancelled")
        self.close()
    
    def close(self):
        """Close the dialog."""
        # Restore original keyboard state
        if self._saved_allow_vkeyboard is not None:
            Window.allow_vkeyboard = self._saved_allow_vkeyboard
            self._saved_allow_vkeyboard = None
        if hasattr(self, '_saved_docked_vkeyboard') and self._saved_docked_vkeyboard is not None:
            Window.docked_vkeyboard = self._saved_docked_vkeyboard
            self._saved_docked_vkeyboard = None
        
        if self.popup:
            self.popup.dismiss()
    
    def toggle_keyboard(self, enabled):
        """Toggle the on-screen keyboard.
        
        Args:
            enabled: True to enable keyboard, False to disable
        """
        log.debug(f"[StepEditor] Toggle keyboard: {enabled}")
        if not enabled:
            # Unfocus any focused widget first to properly dismiss the keyboard
            # before we disable it
            from kivy.uix.textinput import TextInput
            if self.popup:
                for widget in self.popup.walk():
                    if isinstance(widget, TextInput) and widget.focus:
                        widget.focus = False
                        break
        Window.allow_vkeyboard = enabled
        if enabled:
            # Make sure keyboard is not docked so it can be dismissed by tapping outside
            Window.docked_vkeyboard = False


# Mixin methods for the main app to delegate to the controller
class ProvisionStepEditorMixin:
    """Mixin providing step editor methods for the main App class."""
    
    def _init_provision_step_editor(self):
        """Initialize the provision step editor controller."""
        self.provision_step_editor = ProvisionStepEditorController(self)
    
    def pse_save_step(self):
        """Save step from step editor dialog."""
        if hasattr(self, 'provision_step_editor') and self.provision_step_editor:
            self.provision_step_editor.save_step()
    
    def pse_cancel(self):
        """Cancel step editor dialog."""
        if hasattr(self, 'provision_step_editor') and self.provision_step_editor:
            self.provision_step_editor.cancel()
    
    def pse_validate_regex(self, pattern):
        """Validate regex pattern in step editor."""
        if hasattr(self, 'provision_step_editor') and self.provision_step_editor:
            self.provision_step_editor.validate_regex(pattern)
    
    def pse_toggle_keyboard(self, enabled):
        """Toggle on-screen keyboard in step editor."""
        if hasattr(self, 'provision_step_editor') and self.provision_step_editor:
            self.provision_step_editor.toggle_keyboard(enabled)
