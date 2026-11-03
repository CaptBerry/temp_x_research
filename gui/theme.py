"""Application-wide Qt colors for the two supported themes."""

from PyQt6.QtGui import QColor, QPalette


THEMES = {
    "light": {
        "window": "#f4f6f8", "text": "#1b2430", "base": "#ffffff",
        "alternate": "#edf1f5", "button": "#e5ebf2", "highlight": "#2867bd",
        "highlight_text": "#ffffff", "link": "#155bb3", "disabled": "#89939e",
        "tooltip": "#fffbe8", "scene": "#ffffff",
    },
    "dark": {
        "window": "#20252d", "text": "#edf1f6", "base": "#151a21",
        "alternate": "#29313c", "button": "#303a46", "highlight": "#377dca",
        "highlight_text": "#ffffff", "link": "#82bbff", "disabled": "#8c97a5",
        "tooltip": "#303a46", "scene": "#1a2028",
    },
}


def apply_theme(app, theme):
    if theme not in THEMES:
        raise ValueError("Неизвестная тема приложения.")
    colors = THEMES[theme]
    app.setStyle("Fusion")
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: colors["window"],
        QPalette.ColorRole.WindowText: colors["text"],
        QPalette.ColorRole.Base: colors["base"],
        QPalette.ColorRole.AlternateBase: colors["alternate"],
        QPalette.ColorRole.Text: colors["text"],
        QPalette.ColorRole.Button: colors["button"],
        QPalette.ColorRole.ButtonText: colors["text"],
        QPalette.ColorRole.Highlight: colors["highlight"],
        QPalette.ColorRole.HighlightedText: colors["highlight_text"],
        QPalette.ColorRole.ToolTipBase: colors["tooltip"],
        QPalette.ColorRole.ToolTipText: colors["text"],
        QPalette.ColorRole.Link: colors["link"],
        QPalette.ColorRole.BrightText: "#ffffff",
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText, QPalette.ColorRole.ToolTipText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors["disabled"]))
    app.setPalette(palette)
    return colors["scene"]
