"""Custom numpad keyboard layout for Kivy."""

from kivy.logger import Logger
from kivy.clock import Clock
from kivy.core.window import Window


NUMPAD_LAYOUT = {
    'title': 'Numpad',
    'description': 'Numeric keypad for number entry',
    'cols': 4,
    'rows': 4,
    'normal_1': [
        ['7', '7', '7', 1],
        ['8', '8', '8', 1],
        ['9', '9', '9', 1],
        ['⌫', None, 'backspace', 1]
    ],
    'normal_2': [
        ['4', '4', '4', 1],
        ['5', '5', '5', 1],
        ['6', '6', '6', 1],
        ['-', '-', '-', 1]
    ],
    'normal_3': [
        ['1', '1', '1', 1],
        ['2', '2', '2', 1],
        ['3', '3', '3', 1],
        ['.', '.', '.', 1]
    ],
    'normal_4': [
        ['0', '0', '0', 2],
        ['⏎', None, 'enter', 1],
        ['⨯', None, 'escape', 1]
    ]
}


def switch_keyboard_layout(layout_name):
    """Switch the virtual keyboard to the specified layout.
    
    Args:
        layout_name: Name of the layout ('numpad', 'qwerty', etc.)
    """
    Logger.info(f"[Numpad] Switching to layout: {layout_name}")
    
    def change_layout(dt):
        try:
            # Find VKeyboard in Window children
            vkeyboard = None
            for child in Window.children:
                if child.__class__.__name__ == 'VKeyboard':
                    vkeyboard = child
                    break
            
            if not vkeyboard:
                Logger.warning(f"[Numpad] VKeyboard not found in Window children")
                return
            
            # Add custom numpad layout if it doesn't exist
            if 'numpad' not in vkeyboard.available_layouts:
                vkeyboard.available_layouts['numpad'] = NUMPAD_LAYOUT
                Logger.info(f"[Numpad] Registered custom numpad layout")
            
            Logger.info(f"[Numpad] Current layout: {vkeyboard.layout}")
            
            # Check if the layout exists
            if layout_name not in vkeyboard.available_layouts:
                Logger.warning(f"[Numpad] Layout '{layout_name}' not available")
                return
            
            # Get layout data
            layout_data = vkeyboard.available_layouts[layout_name]
            
            if isinstance(layout_data, dict):
                # Programmatically added layout (dict)
                vkeyboard.layout = layout_name
                vkeyboard.refresh(True)
                Logger.info(f"[Numpad] Changed to layout: {layout_name}")
            else:
                # File-based layout (path string)
                vkeyboard.layout_path = layout_data
                vkeyboard.refresh(True)
                Logger.info(f"[Numpad] Changed to layout: {layout_name}")
                
        except Exception as e:
            Logger.error(f"[Numpad] Error changing layout: {e}")
            import traceback
            traceback.print_exc()
    
    # Give keyboard time to appear before switching
    Clock.schedule_once(change_layout, 0.2)


if __name__ == '__main__':
    # This module is imported by kvui.py and not run directly
    pass