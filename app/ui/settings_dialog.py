"""Settings dialog: LLM / Realtime / UI.

The connection test runs on a background thread (HTTP must never block the
GUI thread). The API key is shown masked and never printed to logs.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.llm.provider import LLMConfig, OpenAICompatibleClient

logger = logging.getLogger("ocr_chat.ui.settings")


class _TestConnectionThread(QThread):
    finished_test = Signal(bool, str)  # ok, message

    def __init__(self, config: LLMConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config

    def run(self) -> None:
        client = OpenAICompatibleClient(self._config, max_retries=0)
        result = client.test_connection()
        self.finished_test.emit(result.ok, result.message)


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._test_thread: _TestConnectionThread | None = None
        self._result: dict | None = None

        self.setWindowTitle("设置")
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)
        self._tabs = QTabWidget()
        root.addWidget(self._tabs)

        # ---- LLM tab -------------------------------------------------------
        llm_tab = QWidget()
        llm_form = QFormLayout(llm_tab)
        llm_form.setContentsMargins(12, 12, 12, 12)

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
        llm_form.addRow("Temperature", self._temperature_spin)

        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(5, 300)
        self._timeout_spin.setValue(int(settings.llm_timeout))
        self._timeout_spin.setSuffix(" 秒")
        llm_form.addRow("Timeout", self._timeout_spin)

        test_row = QVBoxLayout()
        self._test_button = QPushButton("测试连接")
        self._test_button.clicked.connect(self._on_test_connection)
        test_row.addWidget(self._test_button)
        self._test_result_label = QLabel("")
        self._test_result_label.setWordWrap(True)
        test_row.addWidget(self._test_result_label)
        llm_form.addRow("", test_row)

        self._tabs.addTab(llm_tab, "LLM")

        # ---- Realtime tab -----------------------------------------------------
        rt_tab = QWidget()
        rt_form = QFormLayout(rt_tab)
        rt_form.setContentsMargins(12, 12, 12, 12)

        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(500, 3000)
        self._interval_spin.setSingleStep(100)
        self._interval_spin.setValue(int(settings.capture_interval_ms))
        self._interval_spin.setSuffix(" ms")
        rt_form.addRow("OCR 采样间隔", self._interval_spin)

        self._debounce_spin = QSpinBox()
        self._debounce_spin.setRange(300, 1500)
        self._debounce_spin.setSingleStep(100)
        self._debounce_spin.setValue(int(settings.debounce_ms))
        self._debounce_spin.setSuffix(" ms")
        rt_form.addRow("防抖等待", self._debounce_spin)

        self._max_messages_spin = QSpinBox()
        self._max_messages_spin.setRange(5, 100)
        self._max_messages_spin.setValue(int(settings.max_context_messages))
        rt_form.addRow("最大上下文条数", self._max_messages_spin)

        self._max_chars_spin = QSpinBox()
        self._max_chars_spin.setRange(1000, 50000)
        self._max_chars_spin.setSingleStep(500)
        self._max_chars_spin.setValue(int(settings.max_context_chars))
        rt_form.addRow("最大上下文字符", self._max_chars_spin)

        self._tabs.addTab(rt_tab, "实时")

        # ---- UI tab -----------------------------------------------------------
        ui_tab = QWidget()
        ui_form = QFormLayout(ui_tab)
        ui_form.setContentsMargins(12, 12, 12, 12)

        self._always_on_top_check = QCheckBox("窗口始终置顶")
        self._always_on_top_check.setChecked(bool(settings.always_on_top))
        ui_form.addRow("", self._always_on_top_check)

        self._auto_start_check = QCheckBox("启动时自动开始监控（需要已保存的区域）")
        self._auto_start_check.setChecked(bool(settings.auto_start_monitoring))
        ui_form.addRow("", self._auto_start_check)

        self._tabs.addTab(ui_tab, "界面")

        # ---- buttons -----------------------------------------------------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ---- handlers --------------------------------------------------------------

    def _current_llm_config(self) -> LLMConfig:
        return LLMConfig(
            provider_name=self._provider_edit.text().strip() or "custom",
            api_key=self._api_key_edit.text().strip(),
            base_url=self._base_url_edit.text().strip(),
            model=self._model_edit.text().strip(),
            temperature=float(self._temperature_spin.value()),
            timeout=float(self._timeout_spin.value()),
        )

    def _on_test_connection(self) -> None:
        config = self._current_llm_config()
        if not config.api_key:
            self._test_result_label.setText("请先填写 API Key")
            return
        if not config.base_url:
            self._test_result_label.setText("请先填写 Base URL")
            return
        if not config.model:
            self._test_result_label.setText("请先填写 Model")
            return
        self._test_button.setEnabled(False)
        self._test_result_label.setText("测试中…")
        self._test_thread = _TestConnectionThread(config, self)
        self._test_thread.finished_test.connect(self._on_test_finished)
        self._test_thread.start()

    def _on_test_finished(self, ok: bool, message: str) -> None:
        self._test_button.setEnabled(True)
        self._test_result_label.setText(message)

    def _on_save(self) -> None:
        s = self._settings
        s.llm_provider = self._provider_edit.text().strip() or "custom"
        api_key = self._api_key_edit.text().strip()
        if api_key:
            s.llm_api_key = api_key  # saving an empty field keeps the old key
        s.llm_base_url = self._base_url_edit.text().strip()
        s.llm_model = self._model_edit.text().strip()
        s.llm_temperature = float(self._temperature_spin.value())
        s.llm_timeout = float(self._timeout_spin.value())
        s.capture_interval_ms = int(self._interval_spin.value())
        s.debounce_ms = int(self._debounce_spin.value())
        s.max_context_messages = int(self._max_messages_spin.value())
        s.max_context_chars = int(self._max_chars_spin.value())
        s.always_on_top = self._always_on_top_check.isChecked()
        s.auto_start_monitoring = self._auto_start_check.isChecked()
        try:
            s.save()
        except Exception as exc:
            logger.warning("settings save failed: %s", exc)
        self._result = {
            "settings": s,
            "always_on_top": s.always_on_top,
        }
        self.accept()

    def get_result(self):
        return self._result
