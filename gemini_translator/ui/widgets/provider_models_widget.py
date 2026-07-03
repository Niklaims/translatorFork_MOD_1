from PyQt6 import QtWidgets, QtCore
from gemini_translator.api import config as api_config
from gemini_translator.ui.widgets.toggle_switch_widget import ToggleSwitchWidget
from gemini_translator.ui.widgets.model_settings_widget import CustomModelDialog
import json
from copy import deepcopy

class ModelInfoDialog(QtWidgets.QDialog):
    def __init__(self, model_name: str, model_config: dict, provider_id: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Инфо модели: {model_name}")
        self.setMinimumSize(450, 400)
        self.deleted = False
        self.model_name = model_name
        self.model_config = deepcopy(model_config)
        self.provider_id = provider_id
        
        layout = QtWidgets.QVBoxLayout(self)
        
        # Проверка отсутствующих данных
        has_context = "context_length" in self.model_config and self.model_config["context_length"] > 0
        has_max_out = "max_output_tokens" in self.model_config and self.model_config["max_output_tokens"] > 0
        
        if not has_context or not has_max_out:
            warning_lbl = QtWidgets.QLabel("⚠️ Ошибка: нехватает данных (context_length / max_output_tokens), нужно прописать самому!")
            warning_lbl.setStyleSheet("color: #ffaa00; font-weight: bold;")
            warning_lbl.setWordWrap(True)
            layout.addWidget(warning_lbl)
            
        form_layout = QtWidgets.QFormLayout()
        
        # Model Name Field (Read only)
        self.name_edit = QtWidgets.QLineEdit(self.model_name)
        self.name_edit.setReadOnly(True)
        form_layout.addRow("Имя модели:", self.name_edit)
        
        # ID Field (Read only)
        self.id_edit = QtWidgets.QLineEdit(str(self.model_config.get("id", "")))
        self.id_edit.setReadOnly(True)
        form_layout.addRow("ID:", self.id_edit)
        
        # Editable Context Length
        self.ctx_spin = QtWidgets.QSpinBox()
        self.ctx_spin.setRange(0, 10000000)
        self.ctx_spin.setSingleStep(1000)
        self.ctx_spin.setValue(self.model_config.get("context_length", 0))
        form_layout.addRow("Context Length:", self.ctx_spin)
        
        # Editable Max Output Tokens
        self.max_out_spin = QtWidgets.QSpinBox()
        self.max_out_spin.setRange(0, 10000000)
        self.max_out_spin.setSingleStep(1000)
        self.max_out_spin.setValue(self.model_config.get("max_output_tokens", 0))
        form_layout.addRow("Max Output Tokens:", self.max_out_spin)
        
        # Editable RPM
        self.rpm_spin = QtWidgets.QSpinBox()
        self.rpm_spin.setRange(0, 100000)
        self.rpm_spin.setSingleStep(5)
        self.rpm_spin.setValue(self.model_config.get("rpm", 0))
        form_layout.addRow("RPM (Запросов в мин):", self.rpm_spin)
        
        # Editable Max Concurrent Requests
        self.concurrent_spin = QtWidgets.QSpinBox()
        self.concurrent_spin.setRange(0, 1000)
        self.concurrent_spin.setSingleStep(1)
        self.concurrent_spin.setValue(self.model_config.get("max_concurrent_requests", 0))
        form_layout.addRow("Параллельные запросы:", self.concurrent_spin)
        
        layout.addLayout(form_layout)
        
        # Full config properties read-only json dump
        self.other_edit = QtWidgets.QTextEdit()
        self.other_edit.setReadOnly(True)
        layout.addWidget(QtWidgets.QLabel("Конфигурация модели (JSON):"))
        layout.addWidget(self.other_edit)
        
        # Connect signals for dynamic JSON updating
        self.ctx_spin.valueChanged.connect(self._update_json_preview)
        self.max_out_spin.valueChanged.connect(self._update_json_preview)
        self.rpm_spin.valueChanged.connect(self._update_json_preview)
        self.concurrent_spin.valueChanged.connect(self._update_json_preview)
        self._update_json_preview()
        
        btn_layout = QtWidgets.QHBoxLayout()
        self.delete_btn = QtWidgets.QPushButton("Удалить модель")
        self.delete_btn.setStyleSheet("color: red;")
        self.delete_btn.clicked.connect(self._on_delete)
        
        self.save_btn = QtWidgets.QPushButton("Сохранить")
        self.save_btn.clicked.connect(self._on_save)
        
        close_btn = QtWidgets.QPushButton("Закрыть")
        close_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        
    def _update_json_preview(self):
        ctx = self.ctx_spin.value()
        max_out = self.max_out_spin.value()
        rpm = self.rpm_spin.value()
        conc = self.concurrent_spin.value()
        preview_config = deepcopy(self.model_config)
        
        if ctx > 0:
            preview_config["context_length"] = ctx
        else:
            preview_config.pop("context_length", None)
            
        if max_out > 0:
            preview_config["max_output_tokens"] = max_out
        else:
            preview_config.pop("max_output_tokens", None)
            
        if rpm > 0:
            preview_config["rpm"] = rpm
        else:
            preview_config.pop("rpm", None)
            
        if conc > 0:
            preview_config["max_concurrent_requests"] = conc
        else:
            preview_config.pop("max_concurrent_requests", None)
            
        # Strip out these editable fields from the "other" config text? 
        # Actually, let's keep showing the full JSON like user wanted.
        self.other_edit.setText(json.dumps(preview_config, ensure_ascii=False, indent=4))
        
    def _on_delete(self):
        reply = QtWidgets.QMessageBox.question(
            self, "Удаление", "Вы уверены, что хотите удалить эту модель?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self.deleted = True
            self.accept()
            
    def _on_save(self):
        ctx = self.ctx_spin.value()
        max_out = self.max_out_spin.value()
        rpm = self.rpm_spin.value()
        conc = self.concurrent_spin.value()
        
        if ctx > 0:
            self.model_config["context_length"] = ctx
        else:
            self.model_config.pop("context_length", None)
            
        if max_out > 0:
            self.model_config["max_output_tokens"] = max_out
        else:
            self.model_config.pop("max_output_tokens", None)
            
        if rpm > 0:
            self.model_config["rpm"] = rpm
        else:
            self.model_config.pop("rpm", None)
            
        if conc > 0:
            self.model_config["max_concurrent_requests"] = conc
        else:
            self.model_config.pop("max_concurrent_requests", None)
            
        success = api_config._save_models_to_json(self.provider_id, {self.model_name: self.model_config})
        if success:
            QtWidgets.QMessageBox.information(self, "Сохранено", "Параметры модели успешно сохранены.")
            self.accept()
        else:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Не удалось сохранить настройки модели.")


class ModelLoaderWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(str)

    def __init__(self, provider_id, api_key=None):
        super().__init__()
        self.provider_id = provider_id
        self.api_key = api_key

    @QtCore.pyqtSlot()
    def run(self):
        try:
            print(f"[ModelLoaderWorker] Запуск обновления моделей для провайдера: {self.provider_id}")
            api_config.refresh_dynamic_models(self.provider_id, api_key=self.api_key)
            print(f"[ModelLoaderWorker] Обновление завершено для: {self.provider_id}")
            self.finished.emit()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))

class ProviderModelsWidget(QtWidgets.QWidget):
    active_models_changed = QtCore.pyqtSignal()

    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self._current_provider_id = None
        
        self.setup_ui()
        
    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Provider Selection
        provider_layout = QtWidgets.QHBoxLayout()
        provider_label = QtWidgets.QLabel("Провайдер ИИ:")
        self.provider_combo = QtWidgets.QComboBox()
        self.provider_combo.setMinimumWidth(200)
        
        for provider_id, provider_data in api_config.api_providers().items():
            self.provider_combo.addItem(provider_data.get("display_name", provider_id), provider_id)
            
        self.provider_combo.currentIndexChanged.connect(self._on_provider_combo_changed)
        
        provider_layout.addWidget(provider_label)
        provider_layout.addWidget(self.provider_combo)
        provider_layout.addStretch()
        layout.addLayout(provider_layout)
        
        # Debounce timer для уменьшения лагов UI при быстром переключении тумблеров
        self._debounce_timer = QtCore.QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(400)
        self._debounce_timer.timeout.connect(self._on_debounce_timeout)

        # Models Group
        models_group = QtWidgets.QGroupBox("Управление моделями")
        models_group_layout = QtWidgets.QVBoxLayout(models_group)
        
        controls_layout = QtWidgets.QHBoxLayout()
        self.load_models_btn = QtWidgets.QPushButton("Обновить")
        self.load_models_btn.setToolTip("Загрузить или обновить список моделей с сервера провайдера")
        self.load_models_btn.clicked.connect(self._on_load_models_clicked)
        
        self.add_custom_model_btn = QtWidgets.QPushButton("+ своя")
        self.add_custom_model_btn.setToolTip("Добавить модель вручную")
        self.add_custom_model_btn.clicked.connect(self._on_add_custom_model_clicked)
        
        controls_layout.addWidget(self.load_models_btn)
        controls_layout.addWidget(self.add_custom_model_btn)
        controls_layout.addStretch()
        
        models_group_layout.addLayout(controls_layout)
        
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll_widget = QtWidgets.QWidget()
        self.models_layout = QtWidgets.QVBoxLayout(self.scroll_widget)
        self.models_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.scroll_widget)
        
        models_group_layout.addWidget(self.scroll_area)
        layout.addWidget(models_group)
        
        if self.provider_combo.count() > 0:
            self._on_provider_combo_changed()
            
    @QtCore.pyqtSlot()
    def _on_provider_combo_changed(self):
        provider_id = self.provider_combo.currentData()
        self._current_provider_id = provider_id
        # Очищаем кеш ожидающих изменений при смене провайдера
        if hasattr(self, '_pending_active_models'):
            delattr(self, '_pending_active_models')
        self.refresh_models_list()
        
    def refresh_models_list(self):
        while self.models_layout.count():
            item = self.models_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
                
        if not self._current_provider_id:
            return
            
        provider_config = api_config.api_providers().get(self._current_provider_id, {})
        models = provider_config.get("models", {})
        
        active_models = self.settings_manager.get_active_models_for_provider(self._current_provider_id)
        if active_models is None:
            # Инициализируем только статичными/неоткрытыми сервером моделями по умолчанию
            active_models = [m_name for m_name, m_cfg in models.items() if not m_cfg.get("server_discovered", False)]
            self.settings_manager.save_active_models_for_provider(self._current_provider_id, active_models)
            
        for model_name, model_cfg in models.items():
            item_widget = QtWidgets.QWidget()
            item_layout = QtWidgets.QHBoxLayout(item_widget)
            item_layout.setContentsMargins(0, 4, 0, 4)
            
            label = QtWidgets.QLabel(model_name)
            toggle = ToggleSwitchWidget()
            toggle.setChecked(model_name in active_models)
            toggle.toggled.connect(lambda checked, name=model_name: self._on_model_toggled(name, checked))
            
            info_btn = QtWidgets.QPushButton("ℹ️")
            info_btn.setToolTip("Инфо модели")
            # Привязываем лямбду без передачи checked как позиционного аргумента от clicked
            info_btn.clicked.connect(lambda _, n=model_name, c=model_cfg: self._on_info_clicked(n, c))
            
            item_layout.addWidget(label)
            item_layout.addStretch()
            item_layout.addWidget(info_btn)
            item_layout.addWidget(toggle)
            
            self.models_layout.addWidget(item_widget)
            
    @QtCore.pyqtSlot(str, dict)
    def _on_info_clicked(self, model_name: str, model_config: dict):
        if not self._current_provider_id: return
        dialog = ModelInfoDialog(model_name, model_config, self._current_provider_id, parent=self)
        result = dialog.exec()
        
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            if dialog.deleted:
                success = api_config.delete_model_from_json(self._current_provider_id, model_name)
                if success:
                    active_models = self.settings_manager.get_active_models_for_provider(self._current_provider_id) or []
                    if model_name in active_models:
                        active_models.remove(model_name)
                        self.settings_manager.save_active_models_for_provider(self._current_provider_id, active_models)
                    self.refresh_models_list()
                    self.active_models_changed.emit()
                else:
                    QtWidgets.QMessageBox.warning(self, "Ошибка", "Не удалось удалить модель.")
            else:
                # Если модель была просто сохранена, обновляем список для актуализации конфигов в виджетах
                self.refresh_models_list()

            
    def _on_model_toggled(self, model_name: str, checked: bool):
        if not self._current_provider_id: return
        
        # Мы кешируем состояние локально, а сохраняем с задержкой, чтобы избежать лагов.
        if not hasattr(self, '_pending_active_models'):
            self._pending_active_models = self.settings_manager.get_active_models_for_provider(self._current_provider_id)
            if self._pending_active_models is None: self._pending_active_models = []
            
        active_models = self._pending_active_models
        
        if checked and model_name not in active_models:
            active_models.append(model_name)
        elif not checked and model_name in active_models:
            active_models.remove(model_name)
            
        self._debounce_timer.start()
        
    @QtCore.pyqtSlot()
    def _on_debounce_timeout(self):
        if not self._current_provider_id or not hasattr(self, '_pending_active_models'):
            return
        
        self.settings_manager.save_active_models_for_provider(
            self._current_provider_id, 
            self._pending_active_models
        )
        delattr(self, '_pending_active_models')
        self.active_models_changed.emit()
        
    @QtCore.pyqtSlot()
    def _on_load_models_clicked(self):
        if not self._current_provider_id:
            return
            
        # Запоминаем текущие модели провайдера до загрузки, чтобы новые модели включить автоматически
        provider_config = api_config.api_providers().get(self._current_provider_id, {})
        self._models_before_load = set(provider_config.get("models", {}).keys())
        
        # Получаем ключи для провайдера
        api_keys = self.settings_manager.get_api_keys_for_provider(self._current_provider_id)
        api_key = api_keys[0] if api_keys else None
        
        # Если провайдер требует ключ, а ключа нет - показываем ошибку
        if api_config.provider_requires_api_key(self._current_provider_id) and not api_key:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Нет ни одного подключенного ключа для этого провайдера.\nПожалуйста, добавьте API-ключ в настройках управления ключами.")
            return
            
        self.load_models_btn.setEnabled(False)
        self.load_models_btn.setText("Загрузка...")
        
        self.loader_thread = QtCore.QThread()
        self.loader_worker = ModelLoaderWorker(self._current_provider_id, api_key=api_key)
        self.loader_worker.moveToThread(self.loader_thread)
        
        self.loader_thread.started.connect(self.loader_worker.run)
        self.loader_worker.finished.connect(self._finish_loading_models)
        self.loader_worker.error.connect(self._handle_loading_error)
        
        self.loader_worker.finished.connect(self.loader_thread.quit)
        self.loader_worker.error.connect(self.loader_thread.quit)
        self.loader_worker.finished.connect(self.loader_worker.deleteLater)
        self.loader_thread.finished.connect(self.loader_thread.deleteLater)
        
        self.loader_thread.start()
        
    @QtCore.pyqtSlot()
    def _finish_loading_models(self):
        self.load_models_btn.setEnabled(True)
        self.load_models_btn.setText("Обновить")
        
        # Новые загруженные модели не активируются автоматически, 
        # чтобы они появились отключенными по умолчанию.
        
        # Очищаем кеш ожидающих изменений, чтобы он перезагрузился из актуального состояния
        if hasattr(self, '_pending_active_models'):
            delattr(self, '_pending_active_models')
        
        self.refresh_models_list()
        self.active_models_changed.emit()
        
    @QtCore.pyqtSlot(str)
    def _handle_loading_error(self, error_msg):
        self.load_models_btn.setEnabled(True)
        self.load_models_btn.setText("Обновить")
        QtWidgets.QMessageBox.warning(self, "Ошибка загрузки", f"Не удалось загрузить модели:\n{error_msg}")
        
    @QtCore.pyqtSlot()
    def _on_clear_models_clicked(self):
        if not self._current_provider_id: return
        
        success = api_config.clear_dynamic_models(self._current_provider_id)
        if success:
            active_models = self.settings_manager.get_active_models_for_provider(self._current_provider_id) or []
            provider_config = api_config.api_providers().get(self._current_provider_id, {})
            static_models = provider_config.get("models", {})
            
            new_active = [m for m in active_models if m in static_models]
            if new_active != active_models:
                self.settings_manager.save_active_models_for_provider(self._current_provider_id, new_active)
                if hasattr(self, '_pending_active_models'):
                    delattr(self, '_pending_active_models')
                    
            self.refresh_models_list()
            self.active_models_changed.emit()
            QtWidgets.QMessageBox.information(self, "Очистка", "Динамически загруженные модели очищены!")
        else:
            QtWidgets.QMessageBox.information(self, "Очистка", "Нет моделей для очистки или произошла ошибка.")

    @QtCore.pyqtSlot()
    def _on_add_custom_model_clicked(self):
        if not self._current_provider_id: return
        provider_config = api_config.api_providers().get(self._current_provider_id, {})
        provider_display_name = provider_config.get("display_name") or self._current_provider_id
        
        dialog = CustomModelDialog(
            provider_display_name,
            defaults={},
            parent=self
        )
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
            
        display_name, model_config = dialog.get_model_entry()
        if display_name in provider_config.get("models", {}):
            QtWidgets.QMessageBox.warning(self, "Своя модель", "Модель с таким названием уже есть в текущем сервисе.")
            return
            
        api_config.add_custom_provider_model(self._current_provider_id, display_name, model_config)
        
        active_models = self.settings_manager.get_active_models_for_provider(self._current_provider_id)
        if display_name not in active_models:
            active_models.append(display_name)
            self.settings_manager.save_active_models_for_provider(self._current_provider_id, active_models)
            
        self.refresh_models_list()
        self.active_models_changed.emit()
