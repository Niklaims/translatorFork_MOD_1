import typing
from PyQt6 import QtWidgets, QtCore, QtGui
from gemini_translator.api import config as api_config
from gemini_translator.ui.widgets.toggle_switch_widget import ToggleSwitchWidget
from gemini_translator.ui.widgets.model_settings_widget import CustomModelDialog
from gemini_translator.ui import theme_manager

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
        self.load_models_btn = QtWidgets.QPushButton("Загрузить модели")
        self.load_models_btn.setToolTip("Загрузить список моделей из API")
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
            
            item_layout.addWidget(label)
            item_layout.addStretch()
            item_layout.addWidget(toggle)
            
            self.models_layout.addWidget(item_widget)
            
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
        self.load_models_btn.setText("Загрузить модели")
        
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
        self.load_models_btn.setText("Загрузить модели")
        QtWidgets.QMessageBox.warning(self, "Ошибка загрузки", f"Не удалось загрузить модели:\n{error_msg}")
        
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
            
        self.settings_manager.add_custom_provider_model(self._current_provider_id, display_name, model_config)
        api_config.add_custom_provider_model(self._current_provider_id, display_name, model_config)
        
        active_models = self.settings_manager.get_active_models_for_provider(self._current_provider_id)
        if display_name not in active_models:
            active_models.append(display_name)
            self.settings_manager.save_active_models_for_provider(self._current_provider_id, active_models)
            
        self.refresh_models_list()
        self.active_models_changed.emit()
