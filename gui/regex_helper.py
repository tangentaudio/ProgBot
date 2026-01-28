from logger import get_logger
log = get_logger(__name__)

"""Regex Helper popup for building and testing regex patterns.

Provides a pattern palette with common regex expressions and a testing
area to validate patterns against sample text.
"""
import re
from kivy.clock import Clock
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button


# Load the regex helper KV file
Builder.load_file('regex_helper.kv')


# Pattern palette entries: (pattern, name, description)
REGEX_PATTERNS = [
    # Capture groups
    ('(?P<name>\\w+)', 'Named capture (word)', 'Captures alphanumeric + underscore as "name"'),
    ('(?P<name>\\d+)', 'Named capture (digits)', 'Captures digits only as "name"'),
    ('(?P<name>.+?)', 'Named capture (any, non-greedy)', 'Captures any chars, minimal match'),
    ('(?P<name>.*)', 'Named capture (any, greedy)', 'Captures any chars, maximal match'),
    
    # Common data formats
    ('(?P<version>[\\w.+-]+)', 'Version string', 'Matches versions like 1.2.3, v2.0-beta'),
    ('(?P<hex>[0-9A-Fa-f]+)', 'Hex string', 'Matches hexadecimal characters'),
    ('(?P<mac>[0-9A-Fa-f:]+)', 'MAC address', 'Matches AA:BB:CC:DD:EE:FF format'),
    ('(?P<ip>\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3})', 'IP address', 'Matches IPv4 addresses'),
    ('(?P<uuid>[0-9a-fA-F-]{36})', 'UUID', 'Matches standard UUID format'),
    
    # Whitespace and structure
    ('[\\s\\S]*?', 'Any (across lines)', 'Matches anything including newlines, non-greedy'),
    ('[\\s\\S]*', 'Any (across lines, greedy)', 'Matches anything including newlines, greedy'),
    ('\\s+', 'Whitespace', 'One or more whitespace chars'),
    ('\\s*', 'Optional whitespace', 'Zero or more whitespace chars'),
    ('\\r?\\n', 'Line ending', 'Matches CRLF or LF'),
    ('.*', 'Rest of line', 'Matches to end of line'),
    
    # Anchors and boundaries
    ('^', 'Start of line', 'Anchor at line start (use with MULTILINE)'),
    ('$', 'End of line', 'Anchor at line end (use with MULTILINE)'),
    ('\\b', 'Word boundary', 'Matches position between word and non-word'),
    
    # Character classes
    ('[A-Za-z]+', 'Letters only', 'One or more alphabetic characters'),
    ('[A-Za-z0-9]+', 'Alphanumeric', 'Letters and digits'),
    ('[^\\s]+', 'Non-whitespace', 'One or more non-whitespace chars'),
    ('[^\\n]+', 'To end of line', 'Any chars except newline'),
    
    # Quantifiers
    ('+', 'One or more', 'Matches previous element 1+ times'),
    ('*', 'Zero or more', 'Matches previous element 0+ times'),
    ('?', 'Optional', 'Matches previous element 0 or 1 time'),
    ('{n}', 'Exactly n', 'Matches previous element exactly n times'),
    ('{n,m}', 'Range n to m', 'Matches previous element n to m times'),
]


class RegexHelperController:
    """Controller for the regex helper popup.
    
    Provides regex pattern building assistance with a palette of
    common patterns and live testing against sample text.
    """
    
    def __init__(self, app):
        """Initialize the regex helper controller.
        
        Args:
            app: The main Kivy App instance
        """
        self.app = app
        self.popup = None
        self.on_apply_callback = None
        self._palette_built = False
    
    def open(self, initial_pattern='', on_apply=None):
        """Open the regex helper dialog.
        
        Args:
            initial_pattern: Starting pattern to edit
            on_apply: Callback function(pattern) when applied
        """
        log.debug(f"[RegexHelper] Opening with pattern: '{initial_pattern[:50] if initial_pattern else '(empty)'}...'")
        
        # Create popup if needed
        if not self.popup:
            self.popup = Factory.RegexHelperPopup()
            self._build_palette()
        
        self.on_apply_callback = on_apply
        self._initial_pattern = initial_pattern
        
        # Clear sample text and results immediately
        if sample := self.popup.ids.get('rh_sample_text'):
            sample.text = ''
        if results := self.popup.ids.get('rh_match_results'):
            results.text = 'Enter pattern and sample text to test'
            results.color = (0.6, 0.6, 0.6, 1)
        
        # Open popup first, then set pattern after layout (fixes display issue)
        self.popup.open()
        
        # Schedule pattern setting after widget is laid out
        Clock.schedule_once(self._set_initial_pattern, 0.1)
    
    def _set_initial_pattern(self, dt):
        """Set initial pattern after popup is laid out."""
        if not self.popup:
            return
        
        pattern_input = self.popup.ids.get('rh_pattern')
        if pattern_input:
            pattern_input.text = self._initial_pattern if hasattr(self, '_initial_pattern') else ''
            # Validate after setting
            self._validate_and_test()
    
    def _build_palette(self):
        """Build the pattern palette UI."""
        if self._palette_built or not self.popup:
            return
        
        palette = self.popup.ids.get('rh_palette')
        if not palette:
            return
        
        for pattern, name, description in REGEX_PATTERNS:
            row = BoxLayout(
                orientation='horizontal',
                size_hint_y=None,
                height=50,
                spacing=5
            )
            
            # Insert button with pattern preview
            btn = Button(
                text=pattern[:20] + ('...' if len(pattern) > 20 else ''),
                size_hint_x=None,
                width=140,
                font_size='11sp',
                font_name='/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
                background_color=(0.25, 0.25, 0.3, 1),
                halign='left',
                valign='center',
            )
            btn.text_size = (btn.width - 10, None)
            btn.bind(on_press=lambda b, p=pattern: self._insert_pattern(p))
            
            # Description label
            desc_box = BoxLayout(orientation='vertical', spacing=0)
            name_label = Label(
                text=name,
                font_size='11sp',
                bold=True,
                halign='left',
                valign='bottom',
                text_size=(None, None),
                size_hint_y=0.45,
                color=(0.9, 0.9, 0.9, 1)
            )
            name_label.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
            
            desc_label = Label(
                text=description,
                font_size='10sp',
                halign='left',
                valign='top',
                text_size=(None, None),
                size_hint_y=0.55,
                color=(0.6, 0.6, 0.6, 1)
            )
            desc_label.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
            
            desc_box.add_widget(name_label)
            desc_box.add_widget(desc_label)
            
            row.add_widget(btn)
            row.add_widget(desc_box)
            palette.add_widget(row)
        
        self._palette_built = True
    
    def _insert_pattern(self, pattern):
        """Insert a pattern at cursor position in the pattern field."""
        if not self.popup:
            return
        
        pattern_input = self.popup.ids.get('rh_pattern')
        if not pattern_input:
            return
        
        # Get cursor position
        cursor_pos = pattern_input.cursor_index()
        current_text = pattern_input.text
        
        # Insert pattern at cursor
        new_text = current_text[:cursor_pos] + pattern + current_text[cursor_pos:]
        pattern_input.text = new_text
        
        # Move cursor after inserted text
        Clock.schedule_once(lambda dt: setattr(pattern_input, 'cursor', 
            pattern_input.get_cursor_from_index(cursor_pos + len(pattern))), 0.1)
        
        # Re-validate
        self._validate_and_test()
    
    def _validate_and_test(self):
        """Validate pattern and test against sample text."""
        if not self.popup:
            return
        
        pattern_input = self.popup.ids.get('rh_pattern')
        sample_input = self.popup.ids.get('rh_sample_text')
        status_label = self.popup.ids.get('rh_pattern_status')
        results_label = self.popup.ids.get('rh_match_results')
        
        if not all([pattern_input, sample_input, status_label, results_label]):
            return
        
        pattern = pattern_input.text
        sample = sample_input.text
        
        # Empty pattern
        if not pattern or not pattern.strip():
            status_label.text = ''
            status_label.color = (0.5, 0.5, 0.5, 1)
            results_label.text = 'Enter a pattern to test'
            results_label.color = (0.6, 0.6, 0.6, 1)
            return
        
        # Try to compile regex
        try:
            compiled = re.compile(pattern)
        except re.error as e:
            status_label.text = f'✗ Invalid regex: {str(e)}'
            status_label.color = (0.9, 0.4, 0.4, 1)
            results_label.text = 'Fix pattern errors first'
            results_label.color = (0.9, 0.4, 0.4, 1)
            return
        
        # Valid regex - show named groups
        named_groups = re.findall(r'\(\?P<(\w+)>', pattern)
        if named_groups:
            status_label.text = f'✓ Captures: {", ".join(named_groups)}'
            status_label.color = (0.4, 0.8, 0.4, 1)
        else:
            status_label.text = '✓ Valid pattern (no named captures)'
            status_label.color = (0.5, 0.7, 0.5, 1)
        
        # Test against sample
        if not sample or not sample.strip():
            results_label.text = 'Paste sample text to test matching'
            results_label.color = (0.6, 0.6, 0.6, 1)
            return
        
        # Debug: log what we're matching
        log.debug(f"[RegexHelper] Pattern: {pattern[:80]}...")
        log.debug(f"[RegexHelper] Sample ({len(sample)} chars): {repr(sample[:100])}...")
        
        # Try to match
        match = compiled.search(sample)
        log.debug(f"[RegexHelper] Match result: {match}")
        if not match:
            results_label.text = '✗ No match found in sample text'
            results_label.color = (0.9, 0.6, 0.4, 1)
            return
        
        # Show match results
        results_lines = ['✓ Match found!', '']
        
        # Show full match
        full_match = match.group(0)
        if len(full_match) > 100:
            full_match = full_match[:100] + '...'
        results_lines.append(f'Full match: "{full_match}"')
        results_lines.append('')
        
        # Show named groups
        groupdict = match.groupdict()
        if groupdict:
            results_lines.append('Captured values:')
            for name, value in groupdict.items():
                if value is not None:
                    display_val = value if len(value) <= 50 else value[:50] + '...'
                    results_lines.append(f'  {name} = "{display_val}"')
        else:
            results_lines.append('(No named captures)')
        
        results_label.text = '\n'.join(results_lines)
        results_label.color = (0.4, 0.9, 0.4, 1)
    
    def apply(self):
        """Apply the pattern and close dialog."""
        if not self.popup:
            return
        
        pattern_input = self.popup.ids.get('rh_pattern')
        if not pattern_input:
            return
        
        pattern = pattern_input.text
        
        # Validate before applying
        try:
            re.compile(pattern)
        except re.error:
            log.warning("[RegexHelper] Cannot apply invalid pattern")
            return
        
        # Call callback with pattern
        if self.on_apply_callback:
            self.on_apply_callback(pattern)
        
        self.popup.dismiss()
    
    def cancel(self):
        """Cancel and close dialog."""
        if self.popup:
            self.popup.dismiss()


class RegexHelperMixin:
    """Mixin providing regex helper methods for the main App class."""
    
    def _init_regex_helper(self):
        """Initialize the regex helper controller."""
        self.regex_helper = RegexHelperController(self)
    
    def rh_apply(self):
        """Apply pattern from regex helper."""
        if hasattr(self, 'regex_helper') and self.regex_helper:
            self.regex_helper.apply()
    
    def rh_cancel(self):
        """Cancel regex helper dialog."""
        if hasattr(self, 'regex_helper') and self.regex_helper:
            self.regex_helper.cancel()
    
    def rh_validate_and_test(self):
        """Validate and test pattern in regex helper."""
        if hasattr(self, 'regex_helper') and self.regex_helper:
            self.regex_helper._validate_and_test()
