from __future__ import annotations

APPLE_DARK_STYLE = """
QMainWindow {
    background-color: #1C1C1E;
}

QWidget {
    color: #F2F2F7;
    font-family: "Microsoft YaHei UI", "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}

#sidebar {
    background-color: #151517;
    border-right: 1px solid #2C2C2E;
}

#sidebar QPushButton {
    background-color: transparent;
    border: none;
    border-radius: 10px;
    padding: 12px;
    margin: 6px 14px;
    font-size: 18px;
}

#sidebar QPushButton:hover {
    background-color: #2C2C2E;
}

#sidebar QPushButton:checked {
    background-color: #0A84FF;
    color: #FFFFFF;
}

#workspace {
    background-color: #1C1C1E;
}

#dropzone {
    border: 2px dashed #3A3A3C;
    border-radius: 16px;
    background-color: #2C2C2E;
    font-size: 15px;
    font-weight: 600;
    color: #AEAEB2;
}

#console {
    background-color: #050505;
    border: 1px solid #2C2C2E;
    border-radius: 14px;
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 12px;
    color: #32D74B;
    padding: 12px;
}

#topBar QPushButton {
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 8px 10px;
    color: #AEAEB2;
    font-weight: 600;
    font-size: 14px;
}

#topBar QPushButton:hover {
    background-color: #2C2C2E;
    color: #F2F2F7;
}

QTableWidget {
    background-color: #1C1C1E;
    alternate-background-color: #242426;
    border: 1px solid #3A3A3C;
    border-radius: 14px;
    gridline-color: transparent;
    outline: none;
}

QHeaderView::section {
    background-color: #2C2C2E;
    color: #AEAEB2;
    padding: 10px;
    border: none;
    font-weight: 600;
}

#settingsPane {
    background-color: #151517;
    border-left: 1px solid #2C2C2E;
}

#rightDrawerWrapper {
    background-color: #151517;
    border-left: 1px solid #2C2C2E;
}

QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollArea#rightDrawerScroll {
    background-color: #151517;
}

QScrollArea#rightDrawerScroll > QWidget > QWidget {
    background-color: #151517;
}

QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 6px;
    margin: 4px 0;
}

QScrollBar::handle:vertical {
    background: #4A4A4C;
    border-radius: 3px;
    min-height: 20px;
}

.FluidCard {
    background-color: #2C2C2E;
    border: 1px solid #3A3A3C;
    border-radius: 14px;
}

.FluidCardHeader {
    background-color: transparent;
    border-radius: 14px;
}

.FluidCardHeader QLabel#title {
    font-size: 14px;
    font-weight: 700;
    color: #FFFFFF;
}

.FluidContentBox {
    background-color: rgba(28, 28, 30, 0.45);
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    border-bottom-left-radius: 14px;
    border-bottom-right-radius: 14px;
}

QLineEdit, QComboBox {
    background-color: #1C1C1E;
    border: 1px solid #3A3A3C;
    border-radius: 8px;
    padding: 8px 12px;
    color: #F2F2F7;
    selection-background-color: #0A84FF;
}

QLineEdit:focus, QComboBox:focus {
    border: 2px solid #0A84FF;
    padding: 7px 11px;
}
"""
