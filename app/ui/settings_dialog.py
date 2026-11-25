"""Settings dialog for model, capture, analysis and display.

The connection test runs on a background thread (HTTP must never block the
GUI thread). The API key is shown masked and never printed to logs.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.llm.provider import LLMConfig, OpenAICompatibleClient
from app.ui.widgets import BrandMark, set_tone

logger = logging.getLogger("ocr_chat.ui.settings")


class _TestConnectionThread(QThread):
    finished_test = Signal(bool, str)  # ok, message

    def __init__(self, config: LLMConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config

    def run(self) -> None:
        client = OpenAICompatibleClient(self._config, max_retries=0)
        try:
            result = client.test_connection()
        finally:
            client.close()
        self.finished_test.emit(result.ok, result.message)


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._test_thread: _TestConnectionThread | None = None
        self._result: dict | None = None

        self.setWindowTitle("设置")
        self.resize(560, 650)
        self.setMinimumWidth(500)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        # ---- header -----------------------------------------------------------
        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(BrandMark(32))
        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel("设置")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("模型连接 · 按需解读 · 界面")
        subtitle.setObjectName("dialogSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        root.addLayout(header)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        root.addWidget(self._tabs, 1)

        # ---- LLM tab -------------------------------------------------------
        llm_tab = QWidget()
        llm_form = self._make_form(llm_tab)

        self._provider_edit = QLineEdit(settings.llm_provider)
        self._provider_edit.setPlaceholderText("自定义 / 厂商名（仅作标记）")
        llm_form.addRow("Provider 名称", self._provider_edit)

        self._api_key_edit = QLineEdit(settings.llm_api_key)
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("sk-…（保存到 Windows 凭据管理器）")
        llm_form.addRow("API Key", self._api_key_edit)

        self._base_url_edit = QLineEdit(settings.llm_base_url)
        self._base_url_edit.setPlaceholderText("https://api.example.com/v1")
        llm_form.addRow("Base URL", self._base_url_edit)

        self._model_edit = QLineEdit(settings.llm_model)
        self._model_edit.setPlaceholderText("model-name")
        llm_form.addRow("Model", self._model_edit)

        self._temperature_spin = QDoubleSpinBox()
        self._temperature_spin.setRange(0.0, 2.0)
        self._temperature_spin.setSingleStep(0.1)
        self._temperature_spin.setValue(float(settings.llm_temperature))
        self._tidy_spin(self._temperature_spin)
        llm_form.addRow("Temperature", self._temperature_spin)

        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(5, 300)
        self._timeout_spin.setValue(int(settings.llm_timeout))
        self._timeout_spin.setSuffix(" 秒")
        self._tidy_spin(self._timeout_spin)
        llm_form.addRow("Timeout", self._timeout_spin)

        test_row = QVBoxLayout()
        test_row.setSpacing(5)
        self._test_button = QPushButton("测试连接")
        self._test_button.setObjectName("testButton")
        self._test_button.setMinimumHeight(32)
        self._test_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._test_button.clicked.connect(self._on_test_connection)
        test_row.addWidget(self._test_button)
        self._test_result_label = QLabel("")
        self._test_result_label.setObjectName("testResult")
        self._test_result_label.setWordWrap(True)
        test_row.addWidget(self._test_result_label)
        llm_form.addRow("", test_row)

        key_hint = QLabel("API Key 仅保存在本机凭据管理器，不会写入配置文件或日志。")
        key_hint.setObjectName("dialogHint")
        key_hint.setWordWrap(True)
        llm_form.addRow("", key_hint)

        self._tabs.addTab(llm_tab, "LLM")

        capture_tab = QWidget()
        capture_form = self._make_form(capture_tab)
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(300, 2000)
        self._interval_spin.setSingleStep(100)
        self._interval_spin.setValue(settings.scroll_capture_interval_ms)
        self._interval_spin.setSuffix(" ms")
        self._tidy_spin(self._interval_spin)
        capture_form.addRow("滚动 OCR 采样间隔", self._interval_spin)

        self._queue_spin = QSpinBox()
        self._queue_spin.setRange(2, 16)
        self._queue_spin.setValue(settings.scroll_max_queue)
        self._queue_spin.setSuffix(" 帧")
        self._tidy_spin(self._queue_spin)
        capture_form.addRow("OCR 等待队列", self._queue_spin)

        interval_hint = QLabel("实时预览独立刷新。OCR 跟不上滚动时，可放慢滚动或增加采样间隔。")
        interval_hint.setObjectName("dialogHint")
        interval_hint.setWordWrap(True)
        capture_form.addRow("", interval_hint)
        self._tabs.addTab(capture_tab, "采集")

        # ---- Analysis tab -----------------------------------------------------
        an_tab = QWidget()
        an_layout = QVBoxLayout(an_tab)
        an_layout.setContentsMargins(14, 14, 14, 12)
        an_layout.setSpacing(10)

        vision_card = QFrame()
        vision_card.setObjectName("infoCard")
        vision_layout = QVBoxLayout(vision_card)
        vision_layout.setContentsMargins(12, 10, 12, 10)
        vision_layout.setSpacing(6)
        vision_title = QLabel("多模态视觉")
        vision_title.setObjectName("infoTitle")
        vision_layout.addWidget(vision_title)
        self._vision_check = QCheckBox("将框选区域的截图随请求发送给模型")
        self._vision_check.setChecked(bool(settings.vision_enabled))
        self._vision_check.toggled.connect(self._set_vision_controls_enabled)
        vision_layout.addWidget(self._vision_check)
        vision_warning = QLabel(
            "开启后，截图不再只留在本机：会将当前框选区域压缩为 JPEG 后随请求发送给你配置的 LLM 服务商。"
        )
        vision_warning.setObjectName("dialogHint")
        vision_warning.setWordWrap(True)
        vision_layout.addWidget(vision_warning)

        vision_row = QHBoxLayout()
        vision_row.setSpacing(8)
        max_side_label = QLabel("最大边")
        max_side_label.setObjectName("dialogHint")
        self._vision_max_spin = QSpinBox()
        self._vision_max_spin.setRange(384, 1600)
        self._vision_max_spin.setSingleStep(128)
        self._vision_max_spin.setValue(int(settings.vision_max_side))
        self._vision_max_spin.setSuffix(" px")
        self._tidy_spin(self._vision_max_spin)
        quality_label = QLabel("JPEG 画质")
        quality_label.setObjectName("dialogHint")
        self._vision_quality_spin = QSpinBox()
        self._vision_quality_spin.setRange(50, 95)
        self._vision_quality_spin.setSingleStep(5)
        self._vision_quality_spin.setValue(int(settings.vision_quality))
        self._vision_quality_spin.setSuffix(" %")
        self._tidy_spin(self._vision_quality_spin)
        vision_row.addWidget(max_side_label)
        vision_row.addWidget(self._vision_max_spin)
        vision_row.addWidget(quality_label)
        vision_row.addWidget(self._vision_quality_spin)
        vision_row.addStretch(1)
        vision_layout.addLayout(vision_row)
        self._set_vision_controls_enabled(bool(settings.vision_enabled))
        an_layout.addWidget(vision_card)

        thinking_card = QFrame()
        thinking_card.setObjectName("infoCard")
        thinking_layout = QVBoxLayout(thinking_card)
        thinking_layout.setContentsMargins(12, 10, 12, 10)
        thinking_layout.setSpacing(6)
        thinking_title = QLabel("思考路径")
        thinking_title.setObjectName("infoTitle")
        thinking_layout.addWidget(thinking_title)
        self._thinking_check = QCheckBox("深度思考（推理模型实时返回，通常较慢）")
        self._thinking_check.setChecked(bool(settings.thinking_enabled))
        thinking_layout.addWidget(self._thinking_check)
        self._thinking_collapse_check = QCheckBox("解读完成后自动折叠，点击标题可展开")
        self._thinking_collapse_check.setChecked(bool(settings.thinking_auto_collapse))
        thinking_layout.addWidget(self._thinking_collapse_check)
        an_layout.addWidget(thinking_card)

        perf_card = QFrame()
        perf_card.setObjectName("infoCard")
        perf_layout = QVBoxLayout(perf_card)
        perf_layout.setContentsMargins(12, 10, 12, 10)
        perf_layout.setSpacing(6)
        perf_title = QLabel("长文与输出")
        perf_title.setObjectName("infoTitle")
        perf_layout.addWidget(perf_title)

        long_row = QHBoxLayout()
        long_row.setSpacing(8)
        long_label = QLabel("单次上下文")
        long_label.setObjectName("dialogHint")
        self._long_text_spin = QSpinBox()
        self._long_text_spin.setRange(5000, 100000)
        self._long_text_spin.setSingleStep(5000)
        self._long_text_spin.setValue(int(settings.long_text_max_chars))
        self._long_text_spin.setSuffix(" 字")
        self._tidy_spin(self._long_text_spin)
        shots_label = QLabel("画面张数")
        shots_label.setObjectName("dialogHint")
        self._max_shots_spin = QSpinBox()
        self._max_shots_spin.setRange(1, 6)
        self._max_shots_spin.setValue(int(settings.max_screenshots))
        self._max_shots_spin.setSuffix(" 张")
        self._tidy_spin(self._max_shots_spin)
        tokens_label = QLabel("输出上限")
        tokens_label.setObjectName("dialogHint")
        self._max_tokens_spin = QSpinBox()
        self._max_tokens_spin.setRange(512, 16000)
        self._max_tokens_spin.setSingleStep(256)
        self._max_tokens_spin.setValue(int(settings.llm_max_tokens))
        self._max_tokens_spin.setSuffix(" tok")
        self._tidy_spin(self._max_tokens_spin)
        long_row.addWidget(long_label)
        long_row.addWidget(self._long_text_spin)
        long_row.addWidget(shots_label)
        long_row.addWidget(self._max_shots_spin)
        long_row.addWidget(tokens_label)
        long_row.addWidget(self._max_tokens_spin)
        long_row.addStretch(1)
        perf_layout.addLayout(long_row)
        perf_hint = QLabel(
            "深度思考默认关闭；关闭时仍在结果里给出简短思考摘要，速度明显更快。"
            "长文超出上限会保留最近部分，画面张数越多请求越大。"
        )
        perf_hint.setObjectName("dialogHint")
        perf_hint.setWordWrap(True)
        perf_layout.addWidget(perf_hint)
        an_layout.addWidget(perf_card)
        an_layout.addStretch(1)

        self._tabs.addTab(an_tab, "解读")

        # ---- UI tab -----------------------------------------------------------
        ui_tab = QWidget()
        ui_layout = QVBoxLayout(ui_tab)
        ui_layout.setContentsMargins(14, 14, 14, 12)
        ui_layout.setSpacing(10)

        behavior = QFrame()
        behavior.setObjectName("infoCard")
        behavior_layout = QVBoxLayout(behavior)
        behavior_layout.setContentsMargins(12, 10, 12, 10)
        behavior_layout.setSpacing(8)
        behavior_title = QLabel("窗口行为")
        behavior_title.setObjectName("infoTitle")
        behavior_layout.addWidget(behavior_title)

        self._always_on_top_check = QCheckBox("窗口始终置顶")
        self._always_on_top_check.setChecked(bool(settings.always_on_top))
        behavior_layout.addWidget(self._always_on_top_check)

        ui_layout.addWidget(behavior)

        ui_layout.addWidget(
            self._info_card(
                "使用要点",
                [
                    "Ctrl + Shift + S   重新框选聊天区域 · Enter 确认 · Esc 取消",
                    "截图只存在内存，回复建议只复制到剪贴板，程序不会自动发送。",
                    "API Key 保存于 Windows 凭据管理器，不写入配置文件。",
                ],
            )
        )
        ui_layout.addWidget(
            self._info_card(
                "关于",
                [
                    "言外 V2 · Windows 10 / 11 · 按需解读",
                    "PySide6 6.11 · PaddleOCR 3.7 · Pydantic v2",
                ],
            )
        )
        ui_layout.addStretch(1)

        self._tabs.addTab(ui_tab, "界面")

        # ---- buttons -----------------------------------------------------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        save_button.setText("保存")
        save_button.setObjectName("primaryButton")
        cancel_button.setText("取消")
        cancel_button.setObjectName("quietButton")
        for button in (save_button, cancel_button):
            button.setMinimumHeight(32)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ---- helpers ---------------------------------------------------------------

    @staticmethod
    def _make_form(container: QWidget) -> QFormLayout:
        form = QFormLayout(container)
        form.setContentsMargins(14, 14, 14, 12)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(11)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        return form

    @staticmethod
    def _info_card(title: str, lines: list[str]) -> QFrame:
        card = QFrame()
        card.setObjectName("infoCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)
        title_label = QLabel(title)
        title_label.setObjectName("infoTitle")
        layout.addWidget(title_label)
        for line in lines:
            label = QLabel(line)
            label.setObjectName("infoLine")
            label.setWordWrap(True)
            layout.addWidget(label)
        return card

    @staticmethod
    def _tidy_spin(spin: QAbstractSpinBox) -> QAbstractSpinBox:
        # Fusion draws the arrow sub-controls as light blocks on a dark field;
        # typing and the wheel remain fully functional without them.
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        spin.setToolTip("可直接输入，或用鼠标滚轮 / ↑ ↓ 调整")
        return spin

    def _set_vision_controls_enabled(self, enabled: bool) -> None:
        self._vision_max_spin.setEnabled(bool(enabled))
        self._vision_quality_spin.setEnabled(bool(enabled))

    def _set_test_message(self, text: str, tone: str = "gray") -> None:
        self._test_result_label.setText(text)
        set_tone(self._test_result_label, tone)

    # ---- handlers --------------------------------------------------------------

    def _current_llm_config(self) -> LLMConfig:
        return LLMConfig(
            provider_name=self._provider_edit.text().strip() or "custom",
            api_key=self._api_key_edit.text().strip(),
            base_url=self._base_url_edit.text().strip(),
            model=self._model_edit.text().strip(),
            temperature=float(self._temperature_spin.value()),
            timeout=min(15, self._timeout_spin.value()),
        )

    def _on_test_connection(self) -> None:
        config = self._current_llm_config()
        if not config.api_key:
            self._set_test_message("请先填写 API Key", "error")
            return
        if not config.base_url:
            self._set_test_message("请先填写 Base URL", "error")
            return
        if not config.model:
            self._set_test_message("请先填写 Model", "error")
            return
        self._test_button.setEnabled(False)
        self._set_test_message("正在测试连接…", "gray")
        self._test_thread = _TestConnectionThread(config, self)
        self._test_thread.finished_test.connect(self._on_test_finished)
        self._test_thread.finished.connect(self._release_test_thread)
        self._test_thread.start()

    def _on_test_finished(self, ok: bool, message: str) -> None:
        self._set_test_message(message, "ok" if ok else "error")

    def _release_test_thread(self) -> None:
        thread, self._test_thread = self._test_thread, None
        if thread is not None:
            thread.deleteLater()
        self._test_button.setEnabled(True)

    def done(self, result: int) -> None:
        if self._test_thread is not None and self._test_thread.isRunning():
            self._tabs.setCurrentIndex(0)
            self._set_test_message("正在完成连接测试，请稍候。", "gray")
            return
        super().done(result)

    def _on_save(self) -> None:
        if self._test_thread is not None and self._test_thread.isRunning():
            self._tabs.setCurrentIndex(0)
            self._set_test_message("请等连接测试结束后再保存。", "gray")
            return
        s = self._settings.model_copy(deep=True)
        s.llm_provider = self._provider_edit.text().strip() or "custom"
        api_key = self._api_key_edit.text().strip()
        if api_key:
            s.llm_api_key = api_key  # saving an empty field keeps the old key
        s.llm_base_url = self._base_url_edit.text().strip()
        s.llm_model = self._model_edit.text().strip()
        s.llm_temperature = float(self._temperature_spin.value())
        s.llm_timeout = float(self._timeout_spin.value())
        s.scroll_capture_interval_ms = self._interval_spin.value()
        s.scroll_max_queue = self._queue_spin.value()
        s.thinking_enabled = self._thinking_check.isChecked()
        s.thinking_auto_collapse = self._thinking_collapse_check.isChecked()
        s.vision_enabled = self._vision_check.isChecked()
        s.vision_max_side = int(self._vision_max_spin.value())
        s.vision_quality = int(self._vision_quality_spin.value())
        s.long_text_max_chars = int(self._long_text_spin.value())
        s.max_screenshots = int(self._max_shots_spin.value())
        s.llm_max_tokens = int(self._max_tokens_spin.value())
        s.always_on_top = self._always_on_top_check.isChecked()
        try:
            s.save(write_api_key=s.llm_api_key != self._settings.llm_api_key)
        except OSError as exc:
            logger.warning("settings save failed (%s)", type(exc).__name__)
            self._tabs.setCurrentIndex(0)
            self._set_test_message(f"保存失败。{exc}", "error")
            return
        self._result = {
            "settings": s,
            "always_on_top": s.always_on_top,
        }
        self.accept()

    def get_result(self):
        return self._result
