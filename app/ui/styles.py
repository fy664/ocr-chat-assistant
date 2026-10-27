"""Global dark-glass stylesheet.

The palette intentionally mirrors the product’s intro page: near-black navy
background, translucent white surfaces, cyan → indigo → violet accents.
Custom-painted details (gradients, glows, rings) live in ``app/ui/widgets.py``;
this file styles the regular Qt widgets around them.
"""
from __future__ import annotations

APP_QSS = """
/* ---------- base ---------- */
QMainWindow, QDialog {
    background-color: #070910;
}
QDialog {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #0c1120, stop:0.55 #080b13, stop:1 #06080e);
}
QWidget {
    color: #d6dfee;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 12px;
}
QWidget#backdrop, QWidget#sectionBody, QWidget#statusContent,
QWidget#cardsInner, QWidget#dialogBody {
    background: transparent;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QLabel {
    background: transparent;
}
QToolTip {
    background-color: #0b111c;
    color: #dce6f5;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 10px;
}

/* ---------- header ---------- */
QLabel#appTitle {
    color: #f2f6ff;
    font-size: 18px;
    font-weight: 600;
}
QLabel#appSubtitle {
    color: #6d7a90;
    font-size: 10px;
}
QFrame#livePill {
    background-color: rgba(255, 255, 255, 0.035);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 11px;
}
QLabel#liveText {
    color: #94a1b7;
    font-size: 10px;
    font-weight: 600;
}
QLabel#liveText[tone="green"] { color: #86efac; }
QLabel#liveText[tone="cyan"] { color: #a5e9f5; }
QLabel#liveText[tone="amber"] { color: #fcd34d; }
QLabel#liveText[tone="red"] { color: #fca5a5; }
QLabel#liveText[tone="gray"] { color: #94a1b7; }

QFrame#regionStrip {
    background-color: rgba(103, 232, 249, 0.045);
    border: 1px solid rgba(103, 232, 249, 0.13);
    border-radius: 10px;
}
QLabel#regionText {
    color: #9fb0c8;
    font-size: 10px;
}
QLabel#shortcutHint {
    color: #5f6d83;
    background-color: rgba(255, 255, 255, 0.035);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 5px;
    padding: 2px 6px;
    font-size: 9px;
}

/* ---------- section cards ---------- */
QFrame#sectionCard {
    background-color: rgba(255, 255, 255, 0.034);
    border: 1px solid rgba(255, 255, 255, 0.075);
    border-radius: 14px;
}
QLabel#sectionTitle {
    color: #e2eaf7;
    font-size: 13px;
    font-weight: 600;
}
QLabel#sectionHint {
    color: #6c7a91;
    font-size: 9px;
}

/* ---------- buttons ---------- */
QPushButton {
    background-color: rgba(255, 255, 255, 0.045);
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 9px;
    color: #c9d4e5;
    padding: 8px 14px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: rgba(255, 255, 255, 0.08);
    border-color: rgba(255, 255, 255, 0.18);
    color: #eef4ff;
}
QPushButton:pressed {
    background-color: rgba(255, 255, 255, 0.03);
}
QPushButton:disabled {
    color: #56627a;
    background-color: rgba(255, 255, 255, 0.02);
    border-color: rgba(255, 255, 255, 0.05);
}
QPushButton#primaryButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #67e8f9, stop:0.52 #818cf8, stop:1 #c084fc);
    border: 1px solid rgba(255, 255, 255, 0.2);
    color: #05070c;
    font-weight: 700;
}
QPushButton#primaryButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #8df2ff, stop:0.52 #9da6ff, stop:1 #d6a5ff);
    color: #04060b;
}
QPushButton#primaryButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #4fd6e8, stop:0.52 #6f7ae6, stop:1 #a973e0);
}
QPushButton#primaryButton:disabled {
    background: rgba(255, 255, 255, 0.05);
    border-color: rgba(255, 255, 255, 0.06);
    color: #59657c;
}
QPushButton#quietButton {
    background: transparent;
    border: 1px solid transparent;
    color: #8c99af;
    padding: 7px 10px;
}
QPushButton#quietButton:hover {
    background-color: rgba(255, 255, 255, 0.055);
    border-color: rgba(255, 255, 255, 0.07);
    color: #e2ebf8;
}
QPushButton#iconButton {
    min-width: 30px;
    max-width: 30px;
    min-height: 30px;
    max-height: 30px;
    padding: 0;
    border-radius: 9px;
    background-color: rgba(255, 255, 255, 0.035);
    border: 1px solid rgba(255, 255, 255, 0.08);
    color: #9fadc3;
    font-size: 14px;
}
QPushButton#iconButton:hover {
    background-color: rgba(255, 255, 255, 0.075);
    border-color: rgba(103, 232, 249, 0.32);
    color: #c9f6ff;
}
QPushButton#copyButton {
    padding: 3px 9px;
    border-radius: 6px;
    font-size: 10px;
    color: #9db0c9;
    background-color: rgba(255, 255, 255, 0.035);
}
QPushButton#copyButton:hover {
    color: #bff3fb;
    border-color: rgba(103, 232, 249, 0.34);
    background-color: rgba(103, 232, 249, 0.08);
}
QPushButton#copyButton[copied="true"] {
    color: #86efac;
    border-color: rgba(52, 211, 153, 0.4);
    background-color: rgba(52, 211, 153, 0.1);
}

/* ---------- analysis cards ---------- */
QFrame#analysisCard {
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 12px;
}
QFrame#analysisCard[tone="cyan"] {
    background-color: rgba(103, 232, 249, 0.035);
    border-color: rgba(103, 232, 249, 0.17);
}
QFrame#analysisCard[tone="indigo"] {
    background-color: rgba(129, 140, 248, 0.035);
    border-color: rgba(129, 140, 248, 0.17);
}
QFrame#analysisCard[tone="violet"] {
    background-color: rgba(192, 132, 252, 0.032);
    border-color: rgba(192, 132, 252, 0.16);
}
QFrame#analysisCard[tone="amber"] {
    background-color: rgba(251, 191, 36, 0.03);
    border-color: rgba(251, 191, 36, 0.15);
}
QFrame#analysisCard[tone="green"] {
    background-color: rgba(52, 211, 153, 0.03);
    border-color: rgba(52, 211, 153, 0.15);
}
QFrame#analysisCard[tone="muted"] {
    background-color: transparent;
    border: 1px dashed rgba(255, 255, 255, 0.13);
}
QLabel#cardTitle {
    color: #8fa3c4;
    font-size: 10px;
    font-weight: 600;
}
QLabel#cardBody {
    color: #cbd6e7;
    font-size: 12px;
}
QLabel#chipItem {
    background-color: rgba(129, 140, 248, 0.08);
    border: 1px solid rgba(129, 140, 248, 0.16);
    border-radius: 7px;
    padding: 3px 8px;
    color: #c7d2fe;
    font-size: 11px;
}
QLabel#emotionLabel {
    color: #eef3ff;
    font-size: 13px;
    font-weight: 600;
}
QLabel#mutedText {
    color: #7c8aa0;
    font-size: 10px;
}
QLabel#hintLabel {
    color: #6f7c93;
    font-size: 10px;
}
QLabel#errorLabel {
    background-color: rgba(248, 113, 113, 0.08);
    border: 1px solid rgba(248, 113, 113, 0.22);
    border-radius: 8px;
    padding: 6px 9px;
    color: #fca5a5;
    font-size: 10px;
}
QLabel#emptyState {
    color: #6c7a91;
    background-color: rgba(255, 255, 255, 0.015);
    border: 1px dashed rgba(255, 255, 255, 0.12);
    border-radius: 10px;
    padding: 24px 14px;
    font-size: 11px;
}
QFrame#updatingPill {
    background-color: rgba(103, 232, 249, 0.06);
    border: 1px solid rgba(103, 232, 249, 0.16);
    border-radius: 8px;
}
QLabel#updatingText {
    color: #8fdcef;
    font-size: 10px;
}

/* ---------- replies ---------- */
QFrame#replyRow {
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 9px;
}
QFrame#replyRow:hover {
    background-color: rgba(103, 232, 249, 0.04);
    border-color: rgba(103, 232, 249, 0.26);
}
QLabel#replyStyle {
    background-color: rgba(251, 191, 36, 0.08);
    border: 1px solid rgba(251, 191, 36, 0.18);
    border-radius: 5px;
    padding: 2px 5px;
    color: #fcd34d;
    font-size: 9px;
}
QLabel#replyText {
    color: #d2dcec;
    font-size: 11px;
}

/* ---------- tabs ---------- */
QTabWidget::pane {
    border: none;
    background: transparent;
    margin-top: 2px;
}
QTabWidget::tab-bar {
    alignment: left;
}
QTabBar {
    background: transparent;
    qproperty-drawBase: 0;
}
QTabBar::tab {
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 7px;
    color: #93a0b6;
    padding: 5px 11px;
    margin-right: 5px;
    font-size: 11px;
}
QTabBar::tab:hover {
    background-color: rgba(255, 255, 255, 0.06);
    color: #cfdaea;
}
QTabBar::tab:selected {
    background-color: rgba(103, 232, 249, 0.1);
    border-color: rgba(103, 232, 249, 0.28);
    color: #d9f6fd;
    font-weight: 600;
}
QTabBar::tab:disabled {
    color: #4c576b;
}

/* ---------- text views & inputs ---------- */
QPlainTextEdit, QTextEdit {
    background-color: rgba(3, 6, 12, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 10px;
    padding: 7px 9px;
    color: #c6d1e3;
    font-size: 11px;
    selection-background-color: rgba(99, 102, 241, 0.5);
    selection-color: #ffffff;
}
QPlainTextEdit:focus, QTextEdit:focus {
    border-color: rgba(103, 232, 249, 0.34);
}
QPlainTextEdit:read-only, QTextEdit:read-only {
    color: #b3c0d5;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: rgba(3, 6, 12, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    padding: 6px 9px;
    color: #dbe5f4;
    font-size: 11px;
    selection-background-color: rgba(99, 102, 241, 0.5);
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: rgba(103, 232, 249, 0.4);
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: #5b677d;
    background-color: rgba(255, 255, 255, 0.015);
}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    width: 16px;
    background-color: rgba(255, 255, 255, 0.035);
    border-left: 1px solid rgba(255, 255, 255, 0.06);
}
QSpinBox::up-button {
    border-top-right-radius: 7px;
}
QSpinBox::down-button {
    border-bottom-right-radius: 7px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: rgba(103, 232, 249, 0.1);
}
QComboBox QAbstractItemView {
    background-color: #0b111c;
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: #d6dfee;
    selection-background-color: rgba(99, 102, 241, 0.35);
    outline: none;
}
QCheckBox {
    color: #b9c6d8;
    font-size: 11px;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border-radius: 4px;
    border: 1px solid rgba(255, 255, 255, 0.18);
    background-color: rgba(255, 255, 255, 0.04);
}
QCheckBox::indicator:hover {
    border-color: rgba(103, 232, 249, 0.5);
}
QCheckBox::indicator:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #67e8f9, stop:1 #818cf8);
    border-color: rgba(103, 232, 249, 0.7);
}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px 1px 2px 0;
}
QScrollBar::handle:vertical {
    background-color: rgba(255, 255, 255, 0.14);
    border-radius: 3px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background-color: rgba(255, 255, 255, 0.26);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
    background: transparent;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 0 2px 1px 2px;
}
QScrollBar::handle:horizontal {
    background-color: rgba(255, 255, 255, 0.14);
    border-radius: 3px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover {
    background-color: rgba(255, 255, 255, 0.26);
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
    background: transparent;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}

/* ---------- status bar ---------- */
QStatusBar {
    background-color: rgba(255, 255, 255, 0.018);
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    color: #8b97ad;
}
QStatusBar::item {
    border: none;
}
QLabel#statusState {
    color: #dbe6f6;
    font-size: 11px;
    font-weight: 600;
}
QLabel#statusState[tone="green"] { color: #86efac; }
QLabel#statusState[tone="cyan"] { color: #a5e9f5; }
QLabel#statusState[tone="amber"] { color: #fcd34d; }
QLabel#statusState[tone="red"] { color: #fca5a5; }
QLabel#statusState[tone="gray"] { color: #8b97ad; }
QFrame#statusChip {
    background-color: rgba(255, 255, 255, 0.028);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 7px;
}
QLabel#statusChipText {
    color: #7f8ca2;
    font-size: 9px;
}
QLabel#statusChipText[tone="busy"] { color: #fcd34d; }
QLabel#statusChipText[tone="ok"] { color: #7f8ca2; }
QLabel#statusChipText[tone="error"] { color: #fca5a5; }
QLabel#statusMessage {
    color: #9fe8f5;
    font-size: 10px;
}
QLabel#statusClock {
    color: #647187;
    font-size: 9px;
}

/* ---------- thinking / pipeline / vision ---------- */
QFrame#thinkingPanel {
    background-color: rgba(129, 140, 248, 0.045);
    border: 1px solid rgba(129, 140, 248, 0.18);
    border-radius: 14px;
}
QToolButton#thinkingToggle {
    background: transparent;
    border: none;
    padding: 0;
    color: #e5ecf9;
    font-size: 12px;
    font-weight: 600;
}
QToolButton#thinkingToggle:hover {
    color: #bff3fb;
}
QLabel#thinkingStatus {
    color: #7f8ca2;
    font-size: 9px;
}
QLabel#thinkingStatus[tone="cyan"] { color: #a5e9f5; }
QLabel#thinkingStatus[tone="amber"] { color: #fcd34d; }
QLabel#thinkingStatus[tone="muted"] { color: #7f8ca2; }
QLabel#thinkingHint {
    color: #5f6d83;
    font-size: 9px;
}
QPlainTextEdit#thinkingView {
    background-color: rgba(3, 6, 12, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-left: 2px solid rgba(103, 232, 249, 0.4);
    border-radius: 8px;
    padding: 7px 9px;
    color: #b8c5d8;
    font-size: 11px;
}
QLabel#logTitle {
    color: #9aa7bd;
    font-family: "Cascadia Code", Consolas, monospace;
    font-size: 9.5px;
}
QLabel#logMeta {
    color: #5f6d83;
    font-family: "Cascadia Code", Consolas, monospace;
    font-size: 8.5px;
}
QPlainTextEdit#pipelineLog {
    background-color: rgba(3, 6, 12, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 8px;
    padding: 6px 8px;
    color: #93a1b7;
    font-family: "Cascadia Code", Consolas, monospace;
    font-size: 9px;
}
QLabel#visionCaption {
    color: #86efac;
    font-size: 9.5px;
}
QLabel#visionCaption[tone="safe"] { color: #86efac; }
QLabel#visionCaption[tone="warn"] { color: #fcd34d; }
QLabel#visionHint {
    color: #5f6d83;
    font-size: 9px;
}
QLabel#replyWhy {
    color: #7a879c;
    font-size: 9px;
}

/* ---------- dialogs ---------- */
QLabel#dialogTitle {
    color: #f2f6ff;
    font-size: 16px;
    font-weight: 600;
}
QLabel#dialogSubtitle {
    color: #6d7a90;
    font-size: 9px;
}
QLabel#dialogHint {
    color: #6d7a90;
    font-size: 9px;
}
QLabel#editBadge {
    color: #fcd34d;
    font-size: 9px;
}
QLabel#testResult {
    color: #8b97ad;
    font-size: 10px;
}
QLabel#testResult[tone="ok"] { color: #86efac; }
QLabel#testResult[tone="error"] { color: #fca5a5; }
QPushButton#testButton {
    background-color: rgba(103, 232, 249, 0.08);
    border-color: rgba(103, 232, 249, 0.24);
    color: #bff3fb;
}
QPushButton#testButton:hover {
    background-color: rgba(103, 232, 249, 0.14);
    border-color: rgba(103, 232, 249, 0.38);
}
QFrame#infoCard {
    background-color: rgba(255, 255, 255, 0.025);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 10px;
}
QLabel#infoTitle {
    color: #aab8cd;
    font-size: 10px;
    font-weight: 600;
}
QLabel#infoLine {
    color: #7f8ca2;
    font-size: 10px;
}
QDialogButtonBox QPushButton {
    min-width: 84px;
    padding: 7px 16px;
}

/* ---------- legacy group boxes (kept for future panels) ---------- */
QGroupBox {
    background-color: rgba(255, 255, 255, 0.025);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 12px;
    margin-top: 12px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #93a0b5;
    font-weight: 600;
}

/* ---- v2 on-demand decoder ---- */
QPlainTextEdit#conversationEditor {
    background: rgba(6, 10, 18, 0.82);
    border: 1px solid rgba(255, 255, 255, 0.075);
    border-radius: 10px;
    padding: 10px 11px;
    color: #dbe5f3;
    selection-background-color: rgba(103, 232, 249, 0.25);
    font-size: 10.5pt;
    line-height: 1.5;
}
QPlainTextEdit#conversationEditor:focus {
    border: 1px solid rgba(103, 232, 249, 0.42);
}
QLabel#charCount {
    color: #8fa1b8;
    font-size: 9.5px;
}
QLabel#charHint {
    color: #5d6b82;
    font-size: 9.5px;
}
QPushButton#linkButton {
    background: transparent;
    border: none;
    color: #8fa1b8;
    font-size: 9.5px;
    padding: 2px 4px;
}
QPushButton#linkButton:hover {
    color: #c7d6e8;
}
QCheckBox#deepCheck {
    color: #93a1b8;
    font-size: 10px;
    spacing: 6px;
}
QCheckBox#deepCheck:hover {
    color: #c7d6e8;
}
QCheckBox#deepCheck::indicator {
    width: 14px;
    height: 14px;
    border-radius: 4px;
    border: 1px solid rgba(255, 255, 255, 0.18);
    background: rgba(255, 255, 255, 0.045);
}
QCheckBox#deepCheck::indicator:checked {
    background: #67e8f9;
    border-color: #67e8f9;
}
"""