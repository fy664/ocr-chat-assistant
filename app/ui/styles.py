"""Global QSS stylesheet - compact desktop-tool look."""
from __future__ import annotations

APP_QSS = """
* {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog {
    background-color: #f5f6f8;
}
QWidget {
    color: #1f2329;
}
QGroupBox {
    border: 1px solid #dde0e4;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 6px;
    background-color: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #5a6472;
    font-weight: bold;
}
QPlainTextEdit, QTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #ffffff;
    border: 1px solid #d0d4da;
    border-radius: 5px;
    padding: 4px 6px;
    selection-background-color: #4c8dff;
}
QPlainTextEdit:focus, QLineEdit:focus {
    border-color: #4c8dff;
}
QPushButton {
    background-color: #ffffff;
    border: 1px solid #c9ced6;
    border-radius: 5px;
    padding: 5px 12px;
}
QPushButton:hover {
    background-color: #eef4ff;
    border-color: #4c8dff;
}
QPushButton:pressed {
    background-color: #dce8ff;
}
QPushButton#primaryButton {
    background-color: #4c8dff;
    border: none;
    color: #ffffff;
    font-weight: bold;
}
QPushButton#primaryButton:hover {
    background-color: #3d7bf0;
}
QPushButton:disabled {
    color: #a6adb8;
    background-color: #f0f1f3;
    border-color: #e0e3e8;
}
QTabWidget::pane {
    border: 1px solid #dde0e4;
    border-radius: 6px;
    background-color: #ffffff;
}
QTabBar::tab {
    padding: 5px 14px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background-color: #ffffff;
    font-weight: bold;
    color: #2b6de0;
}
QStatusBar {
    background-color: #eceef1;
    color: #5a6472;
}
QLabel#cardTitle {
    color: #2b6de0;
    font-weight: bold;
    font-size: 12px;
}
QLabel#cardBody {
    font-size: 13px;
}
QLabel#hintLabel {
    color: #8a93a0;
    font-size: 12px;
}
QLabel#errorLabel {
    color: #d64545;
    font-size: 12px;
}
QLabel#replyStyle {
    color: #2b6de0;
    font-weight: bold;
    font-size: 12px;
}
QFrame#cardFrame {
    background-color: #ffffff;
    border: 1px solid #dde0e4;
    border-radius: 8px;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
}
QScrollBar::handle:vertical {
    background: #c3c9d2;
    border-radius: 4px;
    min-height: 24px;
}
"""
