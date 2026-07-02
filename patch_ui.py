import re

with open('gemini_reader_v3.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Pattern to find the start of controls
start_marker = "# Контролы"
end_marker = "self._on_engine_changed()"

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx == -1 or end_idx == -1:
    print('Markers not found')
    exit(1)

old_controls = content[start_idx:end_idx]

new_controls = '''# Контролы
        controls_split = QHBoxLayout()
        controls_split.setSpacing(12)
        
        workflow_group = QGroupBox("Настройки генерации и перевода")
        workflow_controls = QVBoxLayout(workflow_group)
        workflow_controls.setSpacing(8)
        
        grid_layout = QGridLayout()
        grid_layout.setSpacing(8)
        
        self.live_models_map = dict(LIVE_AUDIO_MODELS)
        self.flash_tts_models_map = dict(FLASH_TTS_MODELS)
        self.models_map = {}

        self.combo_engine = QComboBox()
        for label, mode_id in ENGINE_MODES.items():
            self.combo_engine.addItem(label, mode_id)
        self.combo_engine.currentIndexChanged.connect(self._on_engine_changed)
        self.combo_engine.currentIndexChanged.connect(self._update_worker_spinbox_limit)
        self.combo_engine.currentIndexChanged.connect(self._update_key_state_ui)
        self.combo_engine.currentIndexChanged.connect(self._schedule_save_settings)
        grid_layout.addWidget(QLabel("Движок:"), 0, 0)
        grid_layout.addWidget(self.combo_engine, 0, 1)

        self.combo_model = QComboBox()
        self.combo_model.currentIndexChanged.connect(self._update_worker_spinbox_limit)
        self.combo_model.currentIndexChanged.connect(self._update_key_state_ui)
        self.combo_model.currentIndexChanged.connect(self._refresh_live_segment_controls)
        self.combo_model.currentTextChanged.connect(self._schedule_save_settings)
        grid_layout.addWidget(QLabel("Модель TTS:"), 0, 2)
        grid_layout.addWidget(self.combo_model, 0, 3)

        self.combo_voice_mode = QComboBox()
        for label, mode_id in VOICE_MODE_OPTIONS.items():
            self.combo_voice_mode.addItem(label, mode_id)
        self.combo_voice_mode.currentIndexChanged.connect(self._on_voice_mode_changed)
        self.combo_voice_mode.currentIndexChanged.connect(self._schedule_save_settings)
        grid_layout.addWidget(QLabel("Голоса:"), 0, 4)
        grid_layout.addWidget(self.combo_voice_mode, 0, 5)

        self.combo_voices = QComboBox()
        self.combo_voice_secondary = QComboBox()
        self.combo_voice_tertiary = QComboBox()
        for voice_id, gender in VOICES_MAP.items():
            display_text = f"{voice_id} ({gender})"
            self.combo_voices.addItem(display_text, voice_id)
            self.combo_voice_secondary.addItem(display_text, voice_id)
            self.combo_voice_tertiary.addItem(display_text, voice_id)

        self.combo_voices.currentIndexChanged.connect(self._schedule_save_settings)
        self.combo_voice_secondary.currentIndexChanged.connect(self._schedule_save_settings)
        self.combo_voice_tertiary.currentIndexChanged.connect(self._schedule_save_settings)
        
        self.lbl_voice_primary = QLabel("Voice A:")
        grid_layout.addWidget(self.lbl_voice_primary, 1, 0)
        grid_layout.addWidget(self.combo_voices, 1, 1)
        
        self.lbl_voice_secondary = QLabel("Voice B:")
        grid_layout.addWidget(self.lbl_voice_secondary, 1, 2)
        grid_layout.addWidget(self.combo_voice_secondary, 1, 3)
        
        self.lbl_voice_tertiary = QLabel("Voice C:")
        grid_layout.addWidget(self.lbl_voice_tertiary, 1, 4)
        grid_layout.addWidget(self.combo_voice_tertiary, 1, 5)

        self.btn_test_voice = QPushButton("🔊 Плей")
        self.btn_test_voice.setFixedSize(90, 28)
        self.btn_test_voice.clicked.connect(self.test_voice_sample)
        grid_layout.addWidget(self.btn_test_voice, 2, 0, 1, 2)

        self.combo_speed = QComboBox()
        self.combo_speed.addItems(list(SPEED_PROMPTS.keys()))
        self.combo_speed.setCurrentText("Normal")
        self.combo_speed.currentTextChanged.connect(self._schedule_save_settings)
        grid_layout.addWidget(QLabel("Скорость:"), 2, 2)
        grid_layout.addWidget(self.combo_speed, 2, 3)

        self.combo_live_segment_mode = QComboBox()
        for label, mode_id in LIVE_SEGMENT_OPTIONS.items():
            self.combo_live_segment_mode.addItem(label, mode_id)
        self.combo_live_segment_mode.currentIndexChanged.connect(self._refresh_live_segment_controls)
        self.combo_live_segment_mode.currentIndexChanged.connect(self._schedule_save_settings)
        self.lbl_live_segment_mode = QLabel("Live:")
        grid_layout.addWidget(self.lbl_live_segment_mode, 2, 4)
        grid_layout.addWidget(self.combo_live_segment_mode, 2, 5)

        self.spin_chunk = QDoubleSpinBox()
        self.spin_chunk.setDecimals(1)
        self.spin_chunk.setRange(0.5, 50.0)
        self.spin_chunk.setSingleStep(0.5)
        self.spin_chunk.setValue(FLASH_TTS_DEFAULT_BLOCK_UNITS)
        self.spin_chunk.valueChanged.connect(self._schedule_save_settings)
        self.lbl_chunk = QLabel("Блок:")
        grid_layout.addWidget(self.lbl_chunk, 3, 0)
        grid_layout.addWidget(self.spin_chunk, 3, 1)

        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(1, 1)
        self.spin_workers.setValue(1)
        self.spin_workers.setToolTip(
            "Максимальное число параллельных воркеров. "
            "Фактический запуск дополнительно ограничивается доступными ключами и числом глав."
        )
        self.spin_workers.valueChanged.connect(self._schedule_save_settings)
        grid_layout.addWidget(QLabel("Воркеры:"), 3, 2)
        grid_layout.addWidget(self.spin_workers, 3, 3)

        self.btn_play = QPushButton("▶ СТАРТ")
        self.btn_play.setFixedSize(110, 38)
        self.btn_play.clicked.connect(self.toggle_play)
        grid_layout.addWidget(self.btn_play, 3, 4)

        self.btn_stop = QPushButton("⏹ СТОП")
        self.btn_stop.setFixedSize(110, 38)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.force_stop)
        grid_layout.addWidget(self.btn_stop, 3, 5)

        self.combo_preprocess_model = QComboBox()
        for display_name, model_id in self.preprocess_models_map.items():
            self.combo_preprocess_model.addItem(display_name, model_id)
        self.combo_preprocess_model.currentIndexChanged.connect(self._update_worker_spinbox_limit)
        self.combo_preprocess_model.currentIndexChanged.connect(self._update_key_state_ui)
        self.combo_preprocess_model.currentIndexChanged.connect(self._schedule_save_settings)
        grid_layout.addWidget(QLabel("AI сценарий:"), 4, 0)
        grid_layout.addWidget(self.combo_preprocess_model, 4, 1)

        self.combo_preprocess_profile = QComboBox()
        for label, profile_prompt in PREPROCESS_PROFILE_OPTIONS.items():
            self.combo_preprocess_profile.addItem(label, profile_prompt)
        self.combo_preprocess_profile.currentIndexChanged.connect(self._schedule_save_settings)
        grid_layout.addWidget(QLabel("Профиль:"), 4, 2)
        grid_layout.addWidget(self.combo_preprocess_profile, 4, 3)

        self.combo_pipeline_mode = QComboBox()
        for label, mode_id in PIPELINE_MODE_OPTIONS.items():
            self.combo_pipeline_mode.addItem(label, mode_id)
        self.combo_pipeline_mode.currentIndexChanged.connect(self._update_worker_spinbox_limit)
        self.combo_pipeline_mode.currentIndexChanged.connect(self._update_key_state_ui)
        self.combo_pipeline_mode.currentIndexChanged.connect(self._schedule_save_settings)
        grid_layout.addWidget(QLabel("Pipeline:"), 4, 4)
        grid_layout.addWidget(self.combo_pipeline_mode, 4, 5)

        self.btn_prepare_script = QPushButton("🪄 AI сценарий")
        self.btn_prepare_script.setFixedSize(125, 30)
        self.btn_prepare_script.clicked.connect(self.prepare_selected_scripts)
        grid_layout.addWidget(self.btn_prepare_script, 5, 0, 1, 2)

        self.btn_prepare_missing_script = QPushButton("AI где нет")
        self.btn_prepare_missing_script.setFixedSize(105, 30)
        self.btn_prepare_missing_script.clicked.connect(self.prepare_missing_scripts)
        grid_layout.addWidget(self.btn_prepare_missing_script, 5, 2, 1, 2)

        self.btn_manual_script = QPushButton("✍ Вручную")
        self.btn_manual_script.setFixedSize(110, 30)
        self.btn_manual_script.clicked.connect(self.add_manual_script)
        grid_layout.addWidget(self.btn_manual_script, 5, 4)

        self.btn_save_script = QPushButton("💾 Сохранить сценарий")
        self.btn_save_script.setFixedSize(160, 30)
        self.btn_save_script.clicked.connect(self.save_current_script)
        grid_layout.addWidget(self.btn_save_script, 5, 5)

        self.chk_mp3 = QCheckBox("Запись MP3")
        self.chk_mp3.setChecked(True)
        self.chk_mp3.stateChanged.connect(self._schedule_save_settings)
        self.chk_fast = QCheckBox("Только экспорт")
        self.chk_fast.stateChanged.connect(self._schedule_save_settings)
        self.chk_edge_fallback = QCheckBox("Edge fallback")
        self.chk_edge_fallback.setChecked(True)
        self.chk_edge_fallback.setToolTip("Если отключено, reader не будет использовать Microsoft Edge TTS как аварийную озвучку.")
        self.chk_edge_fallback.stateChanged.connect(self._schedule_save_settings)
        self.chk_selected_only = QCheckBox("Только отмеченные главы")
        self.chk_selected_only.stateChanged.connect(self._schedule_save_settings)
        self.chk_selected_only.stateChanged.connect(self._on_chapter_selection_changed)
        self.chk_parallel_single_chapter = QCheckBox("1 глава = много воркеров")
        self.chk_parallel_single_chapter.setToolTip(
            "Только для Live API. Если выбрана одна глава, reader разделит её на блоки и "
            "раздаст их нескольким воркерам с последующей автоматической сборкой."
        )
        self.chk_parallel_single_chapter.stateChanged.connect(self._schedule_save_settings)
        
        options_layout = QHBoxLayout()
        options_layout.addWidget(self.chk_mp3)
        options_layout.addWidget(self.chk_fast)
        options_layout.addWidget(self.chk_edge_fallback)
        options_layout.addWidget(self.chk_selected_only)
        options_layout.addWidget(self.chk_parallel_single_chapter)
        options_layout.addStretch(1)
        grid_layout.addLayout(options_layout, 6, 0, 1, 6)

        workflow_controls.addLayout(grid_layout)

        actions_group = QGroupBox("Действия проекта")
        actions_group.setMinimumWidth(210)
        actions_group.setMaximumWidth(230)
        actions_panel = QVBoxLayout(actions_group)
        actions_panel.setSpacing(6)

        lbl_project_actions = QLabel("Проект")
        actions_panel.addWidget(lbl_project_actions)

        self.lbl_chapter_scope = QLabel("Главы: все")
        self.lbl_chapter_scope.setToolTip("Область обработки для кнопок Старт и AI сценарий.")
        self.lbl_chapter_scope.setWordWrap(True)
        actions_panel.addWidget(self.lbl_chapter_scope)

        self.lbl_key_state = QLabel("Ключи: 0")
        self.lbl_key_state.setToolTip("Сводка по состоянию ключей для текущих моделей reader.")
        self.lbl_key_state.setWordWrap(True)
        actions_panel.addWidget(self.lbl_key_state)

        self.btn_key_status = QPushButton("Статус ключей")
        self.btn_key_status.setFixedHeight(30)
        self.btn_key_status.clicked.connect(self.show_key_status_dialog)
        actions_panel.addWidget(self.btn_key_status)

        self.btn_pick_chapters = QPushButton("Выбрать главы")
        self.btn_pick_chapters.setFixedHeight(30)
        self.btn_pick_chapters.clicked.connect(self.pick_chapters_dialog)
        actions_panel.addWidget(self.btn_pick_chapters)

        self.btn_clear_chapter_selection = QPushButton("Сбросить отметки")
        self.btn_clear_chapter_selection.setFixedHeight(30)
        self.btn_clear_chapter_selection.clicked.connect(self.clear_chapter_selection)
        actions_panel.addWidget(self.btn_clear_chapter_selection)

        self.btn_clean_stuck = QPushButton("🧹 Очистить зависшие")
        self.btn_clean_stuck.setFixedHeight(30)
        self.btn_clean_stuck.setStyleSheet("background-color: #ffe0b2;")
        self.btn_clean_stuck.clicked.connect(self.clean_stuck_files)
        actions_panel.addWidget(self.btn_clean_stuck)

        actions_panel.addSpacing(4)
        lbl_export_actions = QLabel("Экспорт")
        actions_panel.addWidget(lbl_export_actions)

        self.lbl_export_folder = QLabel("Экспорт: откройте книгу")
        self.lbl_export_folder.setToolTip("Папка текущей книги, куда сохраняются MP3 и видео.")
        self.lbl_export_folder.setWordWrap(True)
        actions_panel.addWidget(self.lbl_export_folder)

        self.btn_open_export_folder = QPushButton("📁 Папка экспорта")
        self.btn_open_export_folder.setFixedHeight(30)
        self.btn_open_export_folder.clicked.connect(self.open_export_folder)
        actions_panel.addWidget(self.btn_open_export_folder)

        self.btn_combine = QPushButton("🧩 Склеить MP3")
        self.btn_combine.setFixedHeight(30)
        self.btn_combine.clicked.connect(self.run_combine)
        actions_panel.addWidget(self.btn_combine)

        actions_panel.addSpacing(4)
        lbl_video_actions = QLabel("Видео")
        actions_panel.addWidget(lbl_video_actions)

        self.lbl_video_cover = QLabel("Видео: картинка не выбрана")
        self.lbl_video_cover.setToolTip("Выбранная картинка будет скопирована в папку книги и использована для экспорта видео.")
        self.lbl_video_cover.setWordWrap(True)
        actions_panel.addWidget(self.lbl_video_cover)

        self.btn_select_video_cover = QPushButton("Картинка видео")
        self.btn_select_video_cover.setFixedHeight(30)
        self.btn_select_video_cover.clicked.connect(self.select_video_cover)
        actions_panel.addWidget(self.btn_select_video_cover)

        self.btn_export_video = QPushButton("Экспорт видео")
        self.btn_export_video.setFixedHeight(30)
        self.btn_export_video.clicked.connect(self.run_export_video)
        actions_panel.addWidget(self.btn_export_video)
        actions_panel.addStretch(1)

        controls_split.addWidget(workflow_group, 1)
        controls_split.addWidget(actions_group, 0)
        main_layout.addLayout(controls_split)

        '''

content = content[:start_idx] + new_controls + content[end_idx:]

with open('gemini_reader_v3.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Replaced successfully')
