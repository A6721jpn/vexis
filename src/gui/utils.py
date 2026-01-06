"""
Icon and UI utilities for VEXIS-CAE GUI.
"""

import os
import sys
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QStyle

# Icon cache for performance
_icon_cache = {}


def load_icon(name: str, fallback_standard, style: QStyle = None) -> QIcon:
    """
    Load an icon by name with SVG color replacement and caching.
    
    Args:
        name: Icon name without extension (e.g., 'start', 'pause')
        fallback_standard: Qt standard icon to use if custom icon not found (e.g., QStyle.SP_MediaPlay)
        style: QStyle instance for fallback (optional, uses app style if None)
    
    Returns:
        QIcon: The loaded or cached icon
    """
    cache_key = name
    if cache_key in _icon_cache:
        return _icon_cache[cache_key]
    
    # Determine icon directory
    if getattr(sys, "frozen", False):
        icon_dir = os.path.join(os.path.dirname(sys.executable), "src", "icons")
    else:
        # Dev: src/gui/utils.py -> src/gui -> src -> src/icons
        icon_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")
    
    # Priority 1: SVG with dynamic recoloring
    svg_path = os.path.join(icon_dir, f"{name}.svg")
    if os.path.exists(svg_path):
        try:
            with open(svg_path, "r", encoding="utf-8") as f:
                svg_content = f.read()
            
            # Normal State: Theme White
            normal_pixmap = _create_colored_pixmap(svg_content, "#EAF2FF")
            # Disabled State: Darker Gray
            disabled_pixmap = _create_colored_pixmap(svg_content, "#353D4A")
            
            if not normal_pixmap.isNull():
                icon = QIcon()
                icon.addPixmap(normal_pixmap, QIcon.Normal)
                icon.addPixmap(disabled_pixmap, QIcon.Disabled)
                _icon_cache[cache_key] = icon
                return icon
        except Exception as e:
            print(f"SVG load error for {name}: {e}")
    
    # Priority 2: ICO (Legacy)
    ico_path = os.path.join(icon_dir, f"{name}.ico")
    if os.path.exists(ico_path):
        icon = QIcon(ico_path)
        _icon_cache[cache_key] = icon
        return icon
    
    # Fallback to standard icon
    if style is None:
        from PySide6.QtWidgets import QApplication
        style = QApplication.instance().style() if QApplication.instance() else None
    
    if style:
        icon = style.standardIcon(fallback_standard)
        _icon_cache[cache_key] = icon
        return icon
    
    return QIcon()


def _create_colored_pixmap(svg_content: str, color: str) -> QPixmap:
    """
    Create a QPixmap from SVG content with color replacement.
    
    Args:
        svg_content: SVG file content as string
        color: Target color in hex format (e.g., '#EAF2FF')
    
    Returns:
        QPixmap: The rendered pixmap
    """
    recolored = (svg_content
                 .replace('"#000000"', f'"{color}"')
                 .replace('"black"', f'"{color}"')
                 .replace("'#000000'", f"'{color}'")
                 .replace("'black'", f"'{color}'"))
    data = bytearray(recolored, encoding='utf-8')
    pm = QPixmap()
    pm.loadFromData(data, "SVG")
    return pm


def clear_icon_cache():
    """Clear the icon cache to free memory."""
    global _icon_cache
    _icon_cache.clear()
