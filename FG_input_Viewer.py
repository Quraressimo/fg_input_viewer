import sys
import time
import math
import json
import os
from collections import deque

import pygame
from PySide6.QtCore import Qt, QTimer, QPoint, QSize
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame,
    QMenu, QMenuBar, QSlider, QCheckBox, QSpinBox, QComboBox, QFormLayout,
    QDialog, QDialogButtonBox, QPushButton, QMessageBox, QSizePolicy, QScrollArea, QLineEdit, QTextEdit, QColorDialog, QTableWidget, QTableWidgetItem, QHeaderView, QGridLayout
)

APP_NAME = "FG Input Viewer"

# SDL/pygame controller button names are not identical for every device.
# These are readable fallbacks; SDL's mapping database handles many common pads.
COMMON_BUTTON_NAMES = {
    0: "A / Cross", 1: "B / Circle", 2: "X / Square", 3: "Y / Triangle",
    4: "LB / L1", 5: "RB / R1", 6: "Back / Share", 7: "Start / Options",
    8: "L3", 9: "R3", 10: "Guide", 11: "D-pad Up", 12: "D-pad Down",
    13: "D-pad Left", 14: "D-pad Right",
}

# Fight-game numpad notation:
# 7 8 9
# 4 5 6
# 1 2 3
def direction_from_axes(x, y, deadzone=0.45):
    dx = -1 if x < -deadzone else (1 if x > deadzone else 0)
    dy = -1 if y < -deadzone else (1 if y > deadzone else 0)
    # SDL stick Y is positive downward; map it to screen/game directions.
    if dx == 0 and dy == 0:
        return 5, "•"
    table = {
        (-1, -1): (7, "↖"), (0, -1): (8, "↑"), (1, -1): (9, "↗"),
        (-1, 0): (4, "←"),                    (1, 0): (6, "→"),
        (-1, 1): (1, "↙"),  (0, 1): (2, "↓"), (1, 1): (3, "↘"),
    }
    return table[(dx, dy)]

def direction_from_dpad(x, y):
    # pygame hat: x left/right, y down/up
    dx = -1 if x < 0 else (1 if x > 0 else 0)
    dy = -1 if y > 0 else (1 if y < 0 else 0)
    if dx == 0 and dy == 0:
        return None
    table = {
        (-1, -1): (7, "↖"), (0, -1): (8, "↑"), (1, -1): (9, "↗"),
        (-1, 0): (4, "←"),                    (1, 0): (6, "→"),
        (-1, 1): (1, "↙"),  (0, 1): (2, "↓"), (1, 1): (3, "↘"),
    }
    return table[(dx, dy)]

class SettingsDialog(QDialog):
    def __init__(self, parent):
        # Store the overlay owner separately. The dialog itself is made a top-level
        # window by open_settings(), so it can be raised above the always-on-top overlay.
        self.overlay_owner = parent
        super().__init__(None)
        self.setWindowTitle("Overlay Settings")
        self.setMinimumWidth(330)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.orientation = QComboBox()
        self.orientation.addItem("위 → 아래", "top_to_bottom")
        self.orientation.addItem("아래 → 위", "bottom_to_top")
        self.orientation.addItem("왼쪽 → 오른쪽", "left_to_right")
        self.orientation.addItem("오른쪽 → 왼쪽", "right_to_left")
        current_direction = getattr(self.overlay_owner, "flow_direction", "top_to_bottom")
        current_index = self.orientation.findData(current_direction)
        self.orientation.setCurrentIndex(max(0, current_index))
        form.addRow("입력 표시 방향", self.orientation)

        self.max_entries = QSpinBox()
        self.max_entries.setRange(4, 40)
        self.max_entries.setValue(self.overlay_owner.max_entries)
        form.addRow("History entries", self.max_entries)

        self.hold_seconds = QSpinBox()
        self.hold_seconds.setRange(1, 60)
        self.hold_seconds.setValue(self.overlay_owner.hold_seconds)
        form.addRow("History lifetime (seconds)", self.hold_seconds)

        self.deadzone = QSlider(Qt.Orientation.Horizontal)
        self.deadzone.setRange(10, 90)
        self.deadzone.setValue(int(self.overlay_owner.deadzone * 100))
        self.deadzone_label = QLabel(f"{self.deadzone.value()}%")
        self.deadzone.valueChanged.connect(lambda v: self.deadzone_label.setText(f"{v}%"))
        deadzone_row = QHBoxLayout()
        deadzone_row.addWidget(self.deadzone, 1)
        deadzone_row.addWidget(self.deadzone_label)
        deadzone_widget = QWidget()
        deadzone_widget.setLayout(deadzone_row)
        form.addRow("Stick deadzone", deadzone_widget)

        self.click_through = QCheckBox("Mouse clicks pass through overlay")
        self.click_through.setChecked(self.overlay_owner.click_through)
        form.addRow("", self.click_through)

        self.always_on_top = QCheckBox("Always on top")
        self.always_on_top.setChecked(self.overlay_owner.always_on_top)
        form.addRow("", self.always_on_top)

        # Keep the global shortcuts visible in Settings so users can discover them.
        self.shortcuts_info = QLabel(
            "<b>프로그램 단축키</b><br>"
            "<code>Ctrl + Shift + T</code> — 클릭 통과 모드 켜기/끄기<br>"
            "<code>Ctrl + Shift + C</code> — 입력 기록 지우기<br>"
            "<code>Ctrl + Shift + S</code> — 설정 창 열기"
        )
        self.shortcuts_info.setWordWrap(True)
        self.shortcuts_info.setTextFormat(Qt.TextFormat.RichText)
        self.shortcuts_info.setStyleSheet(
            "padding:8px; border:1px solid #555; border-radius:4px;"
        )
        form.addRow("단축키", self.shortcuts_info)

        self.borderless = QCheckBox("Borderless mode (hide window frame)")
        self.borderless.setChecked(self.overlay_owner.borderless)
        form.addRow("", self.borderless)

        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(20, 100)
        self.opacity.setValue(int(self.overlay_owner.overlay_opacity * 100))
        self.opacity_label = QLabel(f"{self.opacity.value()}%")
        self.opacity.valueChanged.connect(self._on_opacity_changed)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self.opacity, 1)
        opacity_row.addWidget(self.opacity_label)
        opacity_widget = QWidget()
        opacity_widget.setLayout(opacity_row)
        form.addRow("Overlay opacity", opacity_widget)

        self.controller_status = QLabel()
        self.controller_status.setWordWrap(True)
        self.controller_status.setStyleSheet(
            "padding:6px; border:1px solid #555; border-radius:4px;"
        )
        form.addRow("Connected controller", self.controller_status)
        self.refresh_controller_status()
        self.controller_status_timer = QTimer(self)
        self.controller_status_timer.timeout.connect(self.refresh_controller_status)
        self.controller_status_timer.start(1000)

        profile_row = QHBoxLayout()
        self.profile_name = QComboBox()
        self.profile_name.setEditable(True)
        self.profile_name.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        saved_profiles = list(self.overlay_owner.button_profiles.keys())
        if not saved_profiles:
            saved_profiles = ["Default"]
        self.profile_name.addItems(saved_profiles)
        self.profile_name.setCurrentText(self.overlay_owner.active_profile)
        self.profile_name.setPlaceholderText("Select or enter profile name")
        self.profile_name.currentTextChanged.connect(self.on_profile_selection_changed)
        profile_row.addWidget(self.profile_name, 1)
        self.profile_save_button = QPushButton("Save")
        self.profile_save_button.clicked.connect(self.save_profile_from_table)
        profile_row.addWidget(self.profile_save_button)
        self.profile_delete_button = QPushButton("Delete")
        self.profile_delete_button.clicked.connect(self.delete_selected_profile)
        profile_row.addWidget(self.profile_delete_button)
        profile_widget = QWidget()
        profile_widget.setLayout(profile_row)
        form.addRow("Game / profile", profile_widget)

        # Editable mapping table: input key, label, background, foreground.
        self.mapping_table = QTableWidget(0, 4)
        self.mapping_table.setHorizontalHeaderLabels(["Input", "Display name", "Background", "Text"])
        self.mapping_table.setMinimumHeight(180)
        self.mapping_table.setAlternatingRowColors(True)
        self.mapping_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.mapping_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.mapping_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.mapping_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.mapping_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.mapping_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        for index, label in sorted(self.overlay_owner.button_mapping.items(), key=lambda item: str(item[0])):
            self.add_mapping_row(
                str(index), label,
                self.overlay_owner.button_colors.get(str(index), "#d6cf36"),
                self.overlay_owner.button_text_colors.get(str(index), "#ffffff")
            )
        form.addRow("Button mappings", self.mapping_table)

        mapping_actions = QHBoxLayout()
        self.add_row_button = QPushButton("Add row")
        self.add_row_button.clicked.connect(self.add_empty_mapping_row)
        self.delete_row_button = QPushButton("Delete selected")
        self.delete_row_button.clicked.connect(self.delete_selected_mapping_row)
        mapping_actions.addWidget(self.add_row_button)
        mapping_actions.addWidget(self.delete_row_button)
        mapping_actions.addStretch(1)
        mapping_actions_widget = QWidget()
        mapping_actions_widget.setLayout(mapping_actions)
        form.addRow("", mapping_actions_widget)

        # Let the user discover raw button indexes by pressing a controller button.
        capture_row = QHBoxLayout()
        self.detected_button_index = QLineEdit()
        self.detected_button_index.setReadOnly(True)
        self.detected_button_index.setPlaceholderText("Not detected")
        self.capture_button = QPushButton("Listen for next press")
        self.capture_button.clicked.connect(self.begin_button_capture)
        capture_row.addWidget(self.detected_button_index, 1)
        capture_row.addWidget(self.capture_button)
        capture_widget = QWidget()
        capture_widget.setLayout(capture_row)
        form.addRow("Detect button index", capture_widget)

        self.capture_status = QLabel("Press “Listen for next press”, then press a controller button.")
        self.capture_status.setWordWrap(True)
        layout.addLayout(form)
        layout.addWidget(self.capture_status)
        note = QLabel("Select a row and detect an input to assign it to that row. Or detect an input first to create a row. Edit names and colors directly in the table.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#aab2c0;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        # Apply should close with Accepted so the owner applies the new settings.
        # Cancel must close with Rejected; avoid wiring dialog lifecycle to app shutdown.
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.accept)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).clicked.connect(self.reject)
        self.finished.connect(self._cleanup_settings)
        layout.addWidget(buttons)

    def _on_opacity_changed(self, value):
        self.opacity_label.setText(f"{value}%")
        # Preview transparency immediately while the settings window is open.
        self.overlay_owner.set_overlay_opacity(value / 100.0)

    def _cleanup_settings(self, result):
        if hasattr(self, "controller_status_timer"):
            self.controller_status_timer.stop()
        self.overlay_owner.cancel_button_capture()

    def refresh_controller_status(self):
        owner = self.overlay_owner
        try:
            controllers = list(owner.joysticks.values())
            if not controllers:
                self.controller_status.setText(
                    "No controller detected. Connect a controller and wait a moment."
                )
                return
            lines = []
            for joy in controllers:
                try:
                    name = joy.get_name()
                    buttons = joy.get_numbuttons()
                    axes = joy.get_numaxes()
                    hats = joy.get_numhats()
                    lines.append(
                        f"{name}\\nButtons: {buttons}  |  Axes: {axes}  |  D-pads: {hats}"
                    )
                except Exception:
                    continue
            self.controller_status.setText(
                "\\n\\n".join(lines) if lines else "Controller connected, but details are unavailable."
            )
        except Exception:
            self.controller_status.setText("Could not read controller information.")

    def begin_button_capture(self):
        self.detected_button_index.clear()
        self.capture_status.setText("Waiting for a controller button press…")
        self.overlay_owner.capture_next_button(
            self.on_button_detected
        )

    def delete_selected_profile(self):
        name = self.profile_name.currentText().strip()
        if not name or name not in self.overlay_owner.button_profiles:
            self.capture_status.setText("Select a saved profile to delete.")
            return
        if QMessageBox.question(
            self,
            "Delete profile",
            f"Delete profile '{name}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return

        owner = self.overlay_owner
        owner.button_profiles.pop(name, None)
        owner.button_profile_colors.pop(name, None)
        owner.button_profile_text_colors.pop(name, None)

        # Keep at least one usable profile and switch away from the deleted profile.
        if not owner.button_profiles:
            owner.button_profiles["Default"] = {}
            owner.button_profile_colors["Default"] = {}
            owner.button_profile_text_colors["Default"] = {}
        if owner.active_profile == name:
            owner.active_profile = next(iter(owner.button_profiles))
            owner.button_mapping = dict(owner.button_profiles[owner.active_profile])
            owner.button_colors = dict(owner.button_profile_colors.get(owner.active_profile, {}))
            owner.button_text_colors = dict(owner.button_profile_text_colors.get(owner.active_profile, {}))

        try:
            with open(owner.profile_path, "w", encoding="utf-8") as f:
                json.dump({
                    "active_profile": owner.active_profile,
                    "profiles": owner.button_profiles,
                    "colors": owner.button_profile_colors,
                    "text_colors": owner.button_profile_text_colors,
                }, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            QMessageBox.warning(self, "Profile save failed", f"Could not save profile changes.\\n{exc}")
            return

        self.profile_name.blockSignals(True)
        self.profile_name.clear()
        self.profile_name.addItems(list(owner.button_profiles.keys()))
        self.profile_name.setCurrentText(owner.active_profile)
        self.profile_name.blockSignals(False)
        self.load_selected_profile_into_table()
        owner.update_ui()
        self.capture_status.setText(f"Deleted profile: {name}")

    def on_profile_selection_changed(self, name):
        name = name.strip()
        if name in self.overlay_owner.button_profiles:
            self.load_selected_profile_into_table(name)

    def load_selected_profile_into_table(self, name=None):
        name = (name if isinstance(name, str) else self.profile_name.currentText()).strip()
        if not name or name not in self.overlay_owner.button_profiles:
            return
        mapping = self.overlay_owner.button_profiles.get(name, {})
        colors = self.overlay_owner.button_profile_colors.get(name, {})
        text_colors = self.overlay_owner.button_profile_text_colors.get(name, {})
        self.mapping_table.setRowCount(0)
        # Preserve saved insertion order.
        for key, label in mapping.items():
            self.add_mapping_row(
                str(key), label,
                colors.get(str(key), "#d6cf36"),
                text_colors.get(str(key), "#ffffff")
            )
        self.capture_status.setText(f"Loaded profile: {name}")

    def save_profile_from_table(self):
        name = self.profile_name.currentText().strip()
        if not name:
            name = "Default"
            self.profile_name.setCurrentText(name)

        mapping = {}
        colors = {}
        text_colors = {}
        for row in range(self.mapping_table.rowCount()):
            key_item = self.mapping_table.item(row, 0)
            label_item = self.mapping_table.item(row, 1)
            if key_item is None or label_item is None:
                continue
            key = key_item.text().strip().lower()
            label = label_item.text().strip()
            if not key or not label:
                continue
            try:
                if key.startswith("axis"):
                    axis_index = int(key[4:])
                    if axis_index < 0:
                        continue
                    mapping_key = f"axis{axis_index}"
                else:
                    mapping_key = int(key)
                    if mapping_key < 0:
                        continue
            except ValueError:
                continue
            mapping[mapping_key] = label[:24]
            bg_button = self.mapping_table.cellWidget(row, 2)
            fg_combo = self.mapping_table.cellWidget(row, 3)
            if bg_button is not None:
                colors[str(mapping_key)] = str(bg_button.property("mapping_color") or "#d6cf36")
            if fg_combo is not None:
                text_colors[str(mapping_key)] = str(fg_combo.currentData() or "#ffffff")

        self.overlay_owner.save_button_profile(name, mapping, colors, text_colors)
        if self.profile_name.findText(name) < 0:
            self.profile_name.addItem(name)
        self.overlay_owner.update_ui()
        self.capture_status.setText(f"Saved profile: {name}")

    def add_mapping_row(self, input_key="", label="", bg="#d6cf36", fg="#ffffff"):
        row = self.mapping_table.rowCount()
        self.mapping_table.insertRow(row)
        key_item = QTableWidgetItem(str(input_key))
        label_item = QTableWidgetItem(str(label))
        self.mapping_table.setItem(row, 0, key_item)
        self.mapping_table.setItem(row, 1, label_item)

        color_button = QPushButton(bg or "#d6cf36")
        color_button.setProperty("mapping_color", bg or "#d6cf36")
        color_button.setStyleSheet(
            f"background:{bg or '#d6cf36'}; color:#ffffff; padding:4px;"
        )
        color_button.clicked.connect(lambda checked=False, b=color_button: self.choose_row_bg(b))
        self.mapping_table.setCellWidget(row, 2, color_button)

        text_combo = QComboBox()
        text_combo.addItem("White", "#ffffff")
        text_combo.addItem("Black", "#000000")
        target_fg = (fg or "#ffffff").lower()
        text_combo.setCurrentIndex(1 if target_fg in ("#000000", "black") else 0)
        self.mapping_table.setCellWidget(row, 3, text_combo)

    def choose_row_bg(self, button):
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            button.setProperty("mapping_color", color.name())
            button.setText(color.name())
            button.setStyleSheet(f"background:{color.name()}; color:#ffffff; padding:4px;")

    def add_empty_mapping_row(self):
        detected = self.detected_button_index.text().strip()
        self.add_mapping_row(detected, "")
        self.mapping_table.selectRow(self.mapping_table.rowCount() - 1)
        self.capture_status.setText("Added a row. Edit the display name and colors in the table.")

    def delete_selected_mapping_row(self):
        row = self.mapping_table.currentRow()
        if row >= 0:
            self.mapping_table.removeRow(row)
            self.capture_status.setText("Selected mapping deleted.")

    def on_button_detected(self, index):
        index = str(index)
        self.detected_button_index.setText(index)
        row = self.mapping_table.currentRow()
        if row >= 0:
            key_item = self.mapping_table.item(row, 0)
            if key_item is None:
                key_item = QTableWidgetItem("")
                self.mapping_table.setItem(row, 0, key_item)
            key_item.setText(index)
            self.capture_status.setText(f"Assigned detected input {index} to row {row + 1}.")
            # Automatically move to the next row for rapid batch mapping.
            next_row = row + 1
            if next_row >= self.mapping_table.rowCount():
                self.add_mapping_row()
            self.mapping_table.selectRow(next_row)
            self.mapping_table.setCurrentCell(next_row, 0)
            self.mapping_table.scrollToItem(self.mapping_table.item(next_row, 0))
        else:
            self.add_mapping_row(index, "")
            self.mapping_table.selectRow(self.mapping_table.rowCount() - 1)
            self.mapping_table.setCurrentCell(self.mapping_table.rowCount() - 1, 0)
            self.capture_status.setText(f"Detected input {index} and created a row. Edit its name and colors.")

    def apply_to_parent(self, parent):
        if hasattr(self, "controller_status_timer"):
            self.controller_status_timer.stop()
        parent.cancel_button_capture()
        parent.set_flow_direction(self.orientation.currentData())
        parent.max_entries = self.max_entries.value()
        parent.hold_seconds = self.hold_seconds.value()
        parent.deadzone = self.deadzone.value() / 100.0
        parent.click_through = self.click_through.isChecked()
        parent.always_on_top = self.always_on_top.isChecked()
        parent.borderless = self.borderless.isChecked()
        parent.set_overlay_opacity(self.opacity.value() / 100.0)
        profile_name = self.profile_name.currentText().strip() or "Default"
        self.save_profile_from_table()
        parent.set_flow_direction(self.orientation.currentData())
        parent.max_entries = self.max_entries.value()
        parent.hold_seconds = self.hold_seconds.value()
        parent.deadzone = self.deadzone.value() / 100.0
        parent.click_through = self.click_through.isChecked()
        parent.always_on_top = self.always_on_top.isChecked()
        parent.borderless = self.borderless.isChecked()
        parent.set_overlay_opacity(self.opacity.value() / 100.0)
        parent.apply_window_flags()
        parent.update_ui()
        parent.save_app_settings()

class ControllerOverlay(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        # Keep JSON files in the same folder as the running script or packaged EXE.
        # PyInstaller builds use the EXE's directory; normal Python runs use this .py file's directory.
        if getattr(sys, "frozen", False):
            app_dir = os.path.dirname(os.path.abspath(sys.executable))
        else:
            app_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_dir = app_dir
        os.makedirs(self.config_dir, exist_ok=True)
        self.settings_path = os.path.join(self.config_dir, "overlay_settings.json")
        saved_settings = {}
        try:
            with open(self.settings_path, "r", encoding="utf-8") as settings_file:
                loaded = json.load(settings_file)
                if isinstance(loaded, dict):
                    saved_settings = loaded
        except (OSError, ValueError, TypeError):
            pass

        self.orientation = "vertical"
        # Default display direction is top-to-bottom; use saved choice when available.
        self.flow_direction = saved_settings.get("flow_direction", "top_to_bottom")
        if self.flow_direction not in {"top_to_bottom", "bottom_to_top", "left_to_right", "right_to_left"}:
            self.flow_direction = "top_to_bottom"
        # Save an independent window size for each of the four display directions.
        self._direction_sizes = {
            "top_to_bottom": None,
            "bottom_to_top": None,
            "left_to_right": None,
            "right_to_left": None,
        }
        # Retained for compatibility with older orientation-based logic.
        self._orientation_sizes = {"vertical": None, "horizontal": None}
        self.max_entries = max(4, min(40, int(saved_settings.get("max_entries", 20))))
        self.hold_seconds = max(1, min(60, int(saved_settings.get("hold_seconds", 10))))
        self.profile_path = os.path.join(self.config_dir, "button_profiles.json")
        self.button_profiles = {"Default": {}}
        self.button_profile_colors = {"Default": {}}
        self.button_profile_text_colors = {"Default": {}}
        self.active_profile = "Default"
        self.button_mapping = {}
        self.button_colors = {}
        self.button_text_colors = {}
        self.load_button_profiles()
        self.deadzone = 0.45
        self.click_through = False
        self.always_on_top = True
        self.borderless = False
        try:
            saved_opacity = float(saved_settings.get("opacity", 0.90))
        except (TypeError, ValueError):
            saved_opacity = 0.90
        self.overlay_opacity = max(0.20, min(1.0, saved_opacity))
        self.history = deque(maxlen=self.max_entries)
        # Persistent rows prevent flicker from rebuilding the whole overlay.
        self._history_widgets = {}
        self._empty_history_label = None
        self.held_buttons = {}
        self._previous_raw_buttons = {}
        self._previous_trigger_states = {}
        self._capture_button_callback = None
        self.current_input_key = None
        self._ui_frame_counter = 0
        self.last_direction = None
        self.last_direction_change = 0.0
        self.connected = {}
        self.joysticks = {}
        self.drag_pos = None
        # Custom edge-resize state for frameless/borderless mode.
        self._resize_edges = set()
        self._resize_start_pos = None
        self._resize_start_geometry = None
        self._resize_margin = 8
        self.setMouseTracking(True)
        self._last_prune = 0.0

        # No fixed minimum window dimensions; allow free resizing in either mode.
        self.setMinimumSize(1, 1)
        # Give the vertical command history enough room for many entries by default.
        # Keep the window within the current screen's usable area.
        screen = QApplication.primaryScreen()
        default_height = 800
        if screen is not None:
            default_height = min(default_height, int(screen.availableGeometry().height() * 0.90))
        self.resize(430, max(420, default_height))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.root = QWidget()
        self.root.setObjectName("root")
        self.setCentralWidget(self.root)
        self.root_layout = QVBoxLayout(self.root)
        self.root_layout.setContentsMargins(4, 4, 4, 4)
        self.root_layout.setSpacing(0)

        top = QHBoxLayout()
        self.title_label = QLabel("INPUT HISTORY")
        self.title_label.setStyleSheet("font-weight:800; letter-spacing:1px; color:#f4f6fb;")
        self.status_label = QLabel("Searching for controllers…")
        self.status_label.setStyleSheet("color:#9ca5b5;")
        self.settings_button = QPushButton("⚙")
        self.settings_button.setFixedWidth(34)
        self.settings_button.clicked.connect(self.open_settings)
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_history)
        top.addWidget(self.title_label)
        top.addStretch(1)
        top.addWidget(self.status_label)
        top.addWidget(self.clear_button)
        top.addWidget(self.settings_button)
        # Controls are deliberately not placed on the overlay; use the separate
        # Settings window (Ctrl+Shift+S or right-click) for all configuration.

        self.direction_label = QLabel("Direction: 5 •")
        self.direction_label.setStyleSheet(
            "background:#252b36; color:#e9edf5; border-radius:8px; padding:8px; font-size:16px; font-weight:700;"
        )
        # Keep live status widgets available internally, but off the overlay.
        self.held_label = QLabel("Held: —")
        self.held_label.setWordWrap(True)
        self.held_label.setStyleSheet(
            "background:#252b36; color:#f6c76b; border-radius:8px; padding:8px; font-size:13px;"
        )
        # History sits inside a scroll area. The overlay grows with the log until
        # it reaches the available screen height; after that, older rows scroll.
        self.history_scroll = QScrollArea()
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.history_scroll.setStyleSheet("QScrollArea { background: transparent; border: 0; }")
        self.history_host = QWidget()
        self.history_layout = QVBoxLayout(self.history_host)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        self.history_layout.setSpacing(0)
        self.history_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.history_scroll.setWidget(self.history_host)
        self.root_layout.addWidget(self.history_scroll, 1)

        self.hint_label = QLabel("")
        # The overlay shows input history only; hints and controls live elsewhere.

        self.setStyleSheet("""
            QMainWindow { background: transparent; }
            QWidget#root {
                background: rgba(15, 18, 25, 225);
                border: 1px solid rgba(160, 174, 198, 120);
                border-radius: 12px;
            }
            QLabel { background: transparent; }
            QPushButton {
                color:#f0f3f9; background:rgba(55,63,78,220);
                border:1px solid rgba(160,174,198,100); border-radius:6px;
                padding:4px 7px;
            }
            QPushButton:hover { background:rgba(78,90,110,240); }
        """)

        self.build_menus()
        self.setup_shortcuts()
        self.init_pygame()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_controllers)
        self.timer.start(16)  # ~60 Hz
        self.apply_window_flags()
        self.set_overlay_opacity(self.overlay_opacity)
        self.register_global_hotkeys()
        self.update_ui()
        # Create the settings JSON on first launch as well, not only after changes.
        self.save_app_settings()

    def build_menus(self):
        # No visible Overlay menu bar; use right-click for navigation/settings.
        return

    def setup_shortcuts(self):
        # Qt shortcuts are a fallback; RegisterHotKey below also works while a game is focused.
        self._shortcuts = []
        for sequence, callback in [
            ("Ctrl+Shift+T", self.toggle_click_through),
            ("Ctrl+Shift+C", self.clear_history),
            ("Ctrl+Shift+S", self.open_settings),
        ]:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def register_global_hotkeys(self):
        self._global_hotkeys = {}
        if sys.platform != "win32":
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            MOD_CONTROL, MOD_SHIFT = 0x0002, 0x0004
            registrations = {
                2: (ord("T"), self.toggle_click_through),
                3: (ord("C"), self.clear_history),
                4: (ord("S"), self.open_settings),
            }
            hwnd = int(self.winId())
            for hotkey_id, (key, callback) in registrations.items():
                if user32.RegisterHotKey(hwnd, hotkey_id, MOD_CONTROL | MOD_SHIFT, key):
                    self._global_hotkeys[hotkey_id] = callback
            if len(self._global_hotkeys) < len(registrations):
                self.status_label.setText("Some hotkeys unavailable")
        except Exception as exc:
            print(f"Global hotkeys unavailable: {exc}", file=sys.stderr)

    def nativeEvent(self, eventType, message):
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes
                msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
                if msg.message == 0x0312:  # WM_HOTKEY
                    callback = self._global_hotkeys.get(int(msg.wParam))
                    if callback:
                        callback()
                        return True, 0
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

    def init_pygame(self):
        try:
            pygame.init()
            pygame.joystick.init()
            # Initialize already-connected devices once and retain their objects.
            # Recreating Joystick wrappers every poll can be unreliable on some devices.
            self.joysticks = {}
            for index in range(pygame.joystick.get_count()):
                joystick = pygame.joystick.Joystick(index)
                joystick.init()
                self.joysticks[joystick.get_instance_id()] = joystick
            self.pygame_ok = True
        except Exception as exc:
            self.pygame_ok = False
            QMessageBox.warning(self, "Controller initialization", f"pygame could not initialize:\n{exc}")

    def apply_window_flags(self):
        # Use a normal top-level window so Windows shows it on the taskbar
        # and OBS can identify it as a regular window source.
        flags = Qt.WindowType.Window
        if self.borderless:
            flags |= Qt.WindowType.FramelessWindowHint
        if self.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.show()
        self.set_click_through_native(self.click_through)

    def save_app_settings(self):
        """Persist the display direction and key overlay settings between runs."""
        try:
            data = {
                "flow_direction": self.flow_direction,
                "max_entries": int(self.max_entries),
                "hold_seconds": int(self.hold_seconds),
                "opacity": float(self.overlay_opacity),
            }
            with open(self.settings_path, "w", encoding="utf-8") as settings_file:
                json.dump(data, settings_file, ensure_ascii=False, indent=2)
        except (OSError, TypeError, ValueError) as exc:
            print(f"Could not save overlay settings: {exc}", file=sys.stderr)

    def set_overlay_opacity(self, opacity):
        """Set whole-window opacity (0.20–1.00) for the overlay."""
        self.overlay_opacity = max(0.20, min(1.0, float(opacity)))
        self.setWindowOpacity(self.overlay_opacity)
        # The slider previews opacity live; persist it even if the dialog is closed later.
        if hasattr(self, "settings_path"):
            self.save_app_settings()

    def set_click_through_native(self, enabled):
        # Windows-only WS_EX_TRANSPARENT lets mouse input pass to the game.
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            get_long = ctypes.windll.user32.GetWindowLongW
            set_long = ctypes.windll.user32.SetWindowLongW
            style = get_long(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED
            if enabled:
                style |= WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT
            set_long(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def set_flow_direction(self, direction):
        valid_directions = {"top_to_bottom", "bottom_to_top", "left_to_right", "right_to_left"}
        if direction not in valid_directions:
            direction = "bottom_to_top"

        old_direction = getattr(self, "flow_direction", "bottom_to_top")
        old_orientation = self.orientation
        old_size = (self.width(), self.height())
        # Store the size for the direction being left before changing the active key.
        self._direction_sizes[old_direction] = old_size
        self._orientation_sizes[old_orientation] = old_size

        new_orientation = "horizontal" if direction in ("left_to_right", "right_to_left") else "vertical"
        self.flow_direction = direction

        if new_orientation != old_orientation:
            self.orientation = new_orientation
            self._rebuild_history_widgets()
            self.setMinimumSize(1, 1)

        # Restore this exact direction's previous size. If it has never been used,
        # initialize it from the current size (swapping dimensions across orientations).
        saved_size = self._direction_sizes.get(direction)
        if saved_size is not None:
            target_width, target_height = saved_size
        elif new_orientation != old_orientation:
            target_width, target_height = old_size[1], old_size[0]
        else:
            target_width, target_height = old_size

        target_size = (max(1, target_width), max(1, target_height))
        self.resize(*target_size)
        self._direction_sizes[direction] = target_size
        self._orientation_sizes[new_orientation] = target_size

        self.update_ui()
        self.history_host.updateGeometry()
        self.history_scroll.updateGeometry()
        self.save_app_settings()

    def set_orientation(self, value):
        # Compatibility helper for older calls: select a direction matching the
        # requested orientation while preserving the per-direction size behavior.
        new_orientation = "horizontal" if value == "horizontal" else "vertical"
        if new_orientation == "horizontal":
            direction = self.flow_direction if self.flow_direction in ("left_to_right", "right_to_left") else "left_to_right"
        else:
            direction = self.flow_direction if self.flow_direction in ("top_to_bottom", "bottom_to_top") else "bottom_to_top"
        self.set_flow_direction(direction)

    def _rebuild_history_widgets(self):
        for info in list(self._history_widgets.values()):
            widget = info["widget"]
            self.history_layout.removeWidget(widget)
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        self._history_widgets.clear()
        if self._empty_history_label is not None:
            self.history_layout.removeWidget(self._empty_history_label)
            self._empty_history_label.hide()
            self._empty_history_label.setParent(None)
            self._empty_history_label.deleteLater()
            self._empty_history_label = None

    def toggle_orientation(self):
        self.set_orientation(
            "horizontal" if self.orientation == "vertical" else "vertical"
        )

    def toggle_click_through(self):
        self.click_through = not self.click_through
        self.set_click_through_native(self.click_through)
        self.update_ui()

    def load_button_profiles(self):
        try:
            with open(self.profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            profiles = data.get("profiles", {})
            colors_data = data.get("colors", {})
            text_colors_data = data.get("text_colors", {})
            if isinstance(profiles, dict) and profiles:
                self.button_profiles = {}
                self.button_profile_colors = {
                    str(name): {str(k): str(v) for k, v in colors.items()}
                    for name, colors in colors_data.items() if isinstance(colors, dict)
                } if isinstance(colors_data, dict) else {}
                self.button_profile_text_colors = {
                    str(name): {str(k): str(v) for k, v in colors.items()}
                    for name, colors in text_colors_data.items() if isinstance(colors, dict)
                } if isinstance(text_colors_data, dict) else {}
                for name, mapping in profiles.items():
                    if not isinstance(mapping, dict):
                        continue
                    normalized = {}
                    for key, value in mapping.items():
                        key_text = str(key).lower()
                        if key_text.startswith("axis"):
                            try:
                                normalized[f"axis{int(key_text[4:])}"] = str(value)
                            except ValueError:
                                continue
                        else:
                            try:
                                normalized[int(key_text)] = str(value)
                            except ValueError:
                                continue
                    self.button_profiles[str(name)] = normalized
                self.active_profile = data.get("active_profile", "Default")
                if self.active_profile not in self.button_profiles:
                    self.active_profile = next(iter(self.button_profiles), "Default")
                self.button_mapping = self.button_profiles.get(self.active_profile, {})
                self.button_colors = self.button_profile_colors.get(self.active_profile, {})
                self.button_text_colors = self.button_profile_text_colors.get(self.active_profile, {})
        except (OSError, ValueError, TypeError):
            pass

    def capture_next_button(self, callback):
        self._capture_button_callback = callback

    def cancel_button_capture(self):
        self._capture_button_callback = None

    def save_button_profile(self, name, mapping, colors=None, text_colors=None):
        self.active_profile = name
        self.button_profiles[name] = dict(mapping)
        self.button_mapping = dict(mapping)
        self.button_profile_colors[name] = dict(colors or {})
        self.button_colors = dict(colors or {})
        self.button_profile_text_colors[name] = dict(text_colors or {})
        self.button_text_colors = dict(text_colors or {})
        try:
            with open(self.profile_path, "w", encoding="utf-8") as f:
                json.dump({
                    "active_profile": self.active_profile,
                    "profiles": self.button_profiles,
                    "colors": self.button_profile_colors,
                    "text_colors": self.button_profile_text_colors,
                }, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            QMessageBox.warning(
                self, "Profile save failed",
                f"Could not save button profiles next to the application.\\n{exc}"
            )

    def open_settings(self):
        # Keep settings as a separate, non-modal top-level window. The key viewer
        # remains usable and visible while settings are open.
        dialog = getattr(self, "settings_dialog", None)
        if dialog is None:
            dialog = SettingsDialog(self)
            dialog.setWindowFlags(
                Qt.WindowType.Window
                | Qt.WindowType.WindowTitleHint
                | Qt.WindowType.WindowSystemMenuHint
                | Qt.WindowType.WindowMinimizeButtonHint
            )
            dialog.setWindowModality(Qt.WindowModality.NonModal)
            dialog.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
            dialog.setWindowTitle("Controller Overlay — Settings")
            dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
            dialog.finished.connect(
                lambda result, d=dialog: d.apply_to_parent(self)
                if result == QDialog.DialogCode.Accepted else None
            )
            self.settings_dialog = dialog
        else:
            # Refresh controls from the current viewer state each time it opens.
            dialog.orientation.setCurrentIndex(
                max(0, dialog.orientation.findData(self.flow_direction))
            )
            dialog.max_entries.setValue(self.max_entries)
            dialog.hold_seconds.setValue(self.hold_seconds)
            dialog.deadzone.setValue(int(self.deadzone * 100))
            dialog.click_through.setChecked(self.click_through)
            dialog.always_on_top.setChecked(self.always_on_top)
            dialog.borderless.setChecked(self.borderless)
            dialog.opacity.setValue(int(self.overlay_opacity * 100))

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def clear_history(self):
        self.history.clear()
        self.current_input_key = None
        self.update_ui()

    def add_event(self, text, kind="button"):
        self.history.appendleft({"time": time.time(), "text": text, "kind": kind})
        while len(self.history) > self.max_entries:
            self.history.pop()
        self.update_ui()

    def record_input_frame(self, direction, attack_buttons):
        """Group consecutive identical input states into frame-counted history rows."""
        movement = f"{direction[0]} {direction[1]}"
        attack = " + ".join(attack_buttons) if attack_buttons else "—"
        state_key = (movement, attack)
        now = time.time()

        if self.history and self.current_input_key == state_key:
            # Cap the displayed duration at 999 frames.
            self.history[0]["frames"] = min(600, self.history[0].get("frames", 1) + 1)
            self.history[0]["time"] = now
        else:
            self.history.appendleft({
                "time": now,
                "frames": 1,
                "movement": movement,
                "attack": attack,
                "text": f"1F  |  {movement}  |  {attack}",
                "kind": "input",
            })
            self.current_input_key = state_key
            while len(self.history) > self.max_entries:
                self.history.pop()

        self._ui_frame_counter += 1
        if self._ui_frame_counter >= 4:
            self._ui_frame_counter = 0
            self.update_ui()

    def poll_controllers(self):
        if not getattr(self, "pygame_ok", False):
            return
        try:
            # Process SDL device add/remove events and refresh live device handles.
            for event in pygame.event.get():
                if event.type == pygame.JOYDEVICEADDED:
                    try:
                        joystick = pygame.joystick.Joystick(event.device_index)
                        joystick.init()
                        self.joysticks[joystick.get_instance_id()] = joystick
                    except Exception as exc:
                        print(f"Could not open controller: {exc}", file=sys.stderr)
                elif event.type == pygame.JOYDEVICEREMOVED:
                    instance_id = getattr(event, "instance_id", None)
                    if instance_id in self.joysticks:
                        try:
                            self.joysticks[instance_id].quit()
                        except Exception:
                            pass
                        self.joysticks.pop(instance_id, None)
                    self.connected.pop(instance_id, None)

            # Pump SDL once, then poll persistent joystick handles.
            pygame.event.pump()
            new_held = {}
            directions = []
            connected_now = {}

            for instance_id, joy in list(self.joysticks.items()):
                try:
                    if not joy.get_init():
                        joy.init()
                    connected_now[instance_id] = joy.get_name()

                    # D-pad hats are read separately from normal buttons.
                    dpad = None
                    for hat_idx in range(joy.get_numhats()):
                        mapped = direction_from_dpad(*joy.get_hat(hat_idx))
                        if mapped is not None:
                            dpad = mapped
                            break

                    # Read left stick, if available.
                    axis_direction = None
                    if joy.get_numaxes() >= 2:
                        axis_direction = direction_from_axes(
                            joy.get_axis(0), joy.get_axis(1), self.deadzone
                        )
                        if axis_direction[0] == 5:
                            axis_direction = None

                    direction = dpad if dpad is not None else axis_direction
                    if direction is not None:
                        directions.append((instance_id, direction))

                    # Poll every raw button; detect rising edges so the settings
                    # dialog can learn an index from the next physical button press.
                    previous = self._previous_raw_buttons.get(instance_id, set())
                    currently_pressed = set()
                    for button_index in range(joy.get_numbuttons()):
                        pressed = bool(joy.get_button(button_index))
                        if pressed:
                            currently_pressed.add(button_index)
                            if button_index not in previous and self._capture_button_callback:
                                callback = self._capture_button_callback
                                self._capture_button_callback = None
                                try:
                                    callback(button_index)
                                except RuntimeError:
                                    pass
                            label = self.button_mapping.get(
                                button_index,
                                COMMON_BUTTON_NAMES.get(button_index, f"Button {button_index + 1}")
                            )
                            new_held[(instance_id, button_index)] = label
                    self._previous_raw_buttons[instance_id] = currently_pressed

                    # Some controllers expose triggers as axes rather than buttons.
                    # Learn the axis index when it crosses the press threshold.
                    previous_trigger_states = self._previous_trigger_states.get(instance_id, {})
                    current_trigger_states = {}
                    for axis_index in range(2, joy.get_numaxes()):
                        value = joy.get_axis(axis_index)
                        active = value > 0.65
                        current_trigger_states[axis_index] = active
                        if active:
                            axis_key = f"axis{axis_index}"
                            axis_label = self.button_mapping.get(
                                axis_key, f"Trigger/Axis {axis_index + 1}"
                            )
                            new_held[(instance_id, axis_key)] = axis_label
                        if active and not previous_trigger_states.get(axis_index, False) and self._capture_button_callback:
                            callback = self._capture_button_callback
                            self._capture_button_callback = None
                            try:
                                callback(f"axis{axis_index}")
                            except RuntimeError:
                                pass
                    self._previous_trigger_states[instance_id] = current_trigger_states

                except Exception as exc:
                    print(f"Controller poll failed ({instance_id}): {exc}", file=sys.stderr)

            self.connected = connected_now

            # Current movement state: neutral is represented as numpad 5.
            chosen = directions[0][1] if directions else (5, "•")
            self.last_direction = None if chosen[0] == 5 else chosen
            self.held_buttons = new_held

            # Record frame-counted states, including currently held attack buttons.
            self.record_input_frame(chosen, list(new_held.values()))

            if connected_now:
                names = list(connected_now.values())
                self.status_label.setText(
                    f"{len(names)} controller(s): {', '.join(names)[:48]}"
                )
            else:
                self.status_label.setText("No controller")

            self.update_live_labels()
            now = time.time()
            if now - self._last_prune > 0.25:
                self._last_prune = now
                cutoff = now - self.hold_seconds
                self.history = deque(
                    (entry for entry in self.history if entry["time"] >= cutoff),
                    maxlen=self.max_entries,
                )
                self.update_ui()
        except Exception as exc:
            self.status_label.setText("Input error")
            print(f"Controller polling error: {exc}", file=sys.stderr)

    def update_live_labels(self):
        if self.last_direction is None:
            self.direction_label.setText("Direction: 5  •  Neutral")
        else:
            num, arrow = self.last_direction
            self.direction_label.setText(f"Direction: {num}   {arrow}")
        if self.held_buttons:
            labels = list(self.held_buttons.values())
            elapsed = max(0.0, time.time() - min(self.last_direction_change, time.time()))
            self.held_label.setText("Held: " + "  ·  ".join(labels))
        else:
            self.held_label.setText("Held: —")

    def adjust_overlay_height(self, entry_count):
        # Keep the overlay window at its current size. History rows fade/expire
        # independently; an empty history must not collapse the whole window.
        return

    @staticmethod
    def attack_display_name(name):
        """Short controller labels that stay readable in a command-history row."""
        text = str(name).strip()
        replacements = {
            "A / Cross": "✕", "B / Circle": "○", "X / Square": "□",
            "Y / Triangle": "△", "LB / L1": "L1", "RB / R1": "R1",
            "Back / Share": "SH", "Start / Options": "ST",
            "L3": "L3", "R3": "R3",
        }
        return replacements.get(text, text)

    def update_ui(self):
        """Update persistent input rows instead of recreating the whole history."""
        horizontal = self.orientation == "horizontal"
        direction_map = {
            "top_to_bottom": QVBoxLayout.Direction.TopToBottom,
            "bottom_to_top": QVBoxLayout.Direction.BottomToTop,
            "left_to_right": QVBoxLayout.Direction.LeftToRight,
            "right_to_left": QVBoxLayout.Direction.RightToLeft,
        }
        self.history_layout.setDirection(
            direction_map.get(self.flow_direction, QVBoxLayout.Direction.BottomToTop)
        )
        self.history_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if horizontal
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.history_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff if horizontal
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        # Reverse the visual flow: newest entries appear at the bottom in vertical
        # mode and at the right in horizontal mode.
        entries = list(self.history)
        active_keys = {id(entry) for entry in entries}

        # Remove only expired or evicted rows.
        for key in list(self._history_widgets):
            if key not in active_keys:
                info = self._history_widgets.pop(key)
                widget = info["widget"]
                self.history_layout.removeWidget(widget)
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        if not entries:
            if self._empty_history_label is None:
                self._empty_history_label = QLabel("Waiting for input…")
                self._empty_history_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._empty_history_label.setStyleSheet("color:#8791a2; padding:12px;")
                self.history_layout.addWidget(self._empty_history_label)
        elif self._empty_history_label is not None:
            self.history_layout.removeWidget(self._empty_history_label)
            self._empty_history_label.hide()
            self._empty_history_label.setParent(None)
            self._empty_history_label.deleteLater()
            self._empty_history_label = None

        for entry in entries:
            key = id(entry)
            info = self._history_widgets.get(key)
            if info is None:
                row = QWidget()
                row.setStyleSheet("background:transparent; border:0;")
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(6, 1, 6, 1)
                row_layout.setSpacing(7)

                frame_label = QLabel()
                frame_label.setFixedWidth(42)
                frame_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                frame_label.setStyleSheet("color:#f5f7fc; font-size:16px; font-weight:800; border:0;")

                movement_text = entry.get("movement", entry.get("text", ""))
                parts = movement_text.split(" ", 1)
                direction_text = parts[-1] if len(parts) > 1 else movement_text
                direction_label = QLabel(direction_text)
                direction_label.setFixedWidth(40)
                direction_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                direction_label.setStyleSheet("color:#f5f7fc; font-size:22px; font-weight:800; border:0;")

                row_layout.addWidget(frame_label)
                row_layout.addWidget(direction_label)

                attack_text = entry.get("attack", "")
                if attack_text and attack_text != "—":
                    # Vertical mode: keep every attack button on one line.
                    # Horizontal mode: retain the two-column grid for readability.
                    attack_host = QWidget()
                    attack_host.setStyleSheet("background:transparent; border:0;")
                    if horizontal:
                        attack_grid = QGridLayout(attack_host)
                        attack_grid.setContentsMargins(0, 0, 0, 0)
                        attack_grid.setHorizontalSpacing(5)
                        attack_grid.setVerticalSpacing(12)
                    else:
                        attack_grid = QHBoxLayout(attack_host)
                        attack_grid.setContentsMargins(0, 0, 0, 0)
                        attack_grid.setSpacing(5)

                    for button_index, raw_name in enumerate(attack_text.split(" + ")):
                        short_name = self.attack_display_name(raw_name)
                        button_label = QLabel(short_name)
                        button_label.setFixedSize(29, 29)
                        button_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        raw_key = next(
                            (str(k) for k, v in self.button_mapping.items() if v == raw_name),
                            ""
                        )
                        bg = self.button_colors.get(raw_key)
                        if not bg:
                            is_first_color = short_name in ("✕", "□", "L1", "SH", "ST")
                            bg = "#36b9d0" if is_first_color else "#d6cf36"
                        fg = self.button_text_colors.get(raw_key, "#ffffff")
                        button_label.setStyleSheet(
                            f"color:{fg}; background:{bg}; border:2px solid rgba(255,255,255,180); "
                            "border-radius:14px; font-size:13px; font-weight:900;"
                        )
                        if horizontal:
                            attack_grid.addWidget(button_label, button_index // 2, button_index % 2)
                        else:
                            attack_grid.addWidget(button_label)
                    row_layout.addWidget(attack_host)
                row_layout.addStretch(1)

                separator = QFrame()
                separator.setFixedHeight(1)
                separator.setStyleSheet("background:rgba(220,225,235,35); border:0;")
                line_wrap = QWidget()
                line_layout = QVBoxLayout(line_wrap)
                line_layout.setContentsMargins(0, 0, 0, 0)
                line_layout.setSpacing(0)
                if horizontal:
                    row_layout.setDirection(QHBoxLayout.Direction.TopToBottom)
                    row_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                    row_layout.setContentsMargins(5, 5, 5, 5)
                    row_layout.setSpacing(18)
                    frame_label.setFixedWidth(48)
                    direction_label.setFixedWidth(42)
                    row.setFixedSize(110, 250)
                    line_layout.addWidget(row)
                    line_wrap.setFixedSize(112, 252)
                else:
                    row_height = 42
                    row.setMinimumHeight(row_height)
                    row.setMaximumHeight(row_height)
                    line_layout.addWidget(row)
                    line_layout.addWidget(separator)
                    line_wrap.setMinimumHeight(row_height + 1)
                    line_wrap.setMaximumHeight(row_height + 1)

                info = {"widget": line_wrap, "frame_label": frame_label}
                self._history_widgets[key] = info

            info["frame_label"].setText(str(min(600, entry.get("frames", 1))))
            age = max(0.0, time.time() - entry["time"])
            alpha = max(75, int(255 * (1 - age / max(1, self.hold_seconds))))
            info["frame_label"].setStyleSheet(
                f"color:rgba(245,247,252,{alpha}); font-size:16px; font-weight:800; border:0;"
            )

        # Reorder the existing row widgets; do not destroy and recreate them.
        for index, entry in enumerate(entries):
            widget = self._history_widgets[id(entry)]["widget"]
            self.history_layout.removeWidget(widget)
            self.history_layout.insertWidget(index, widget)

        if horizontal:
            # Each history item is a fixed-width card; force the scroll area's
            # content to grow horizontally instead of squeezing cards into the viewport.
            card_width = 112
            self.history_host.setMinimumWidth(max(
                self.history_scroll.viewport().width(),
                len(entries) * card_width
            ))
            self.history_host.setMinimumHeight(0)
            # In right-to-left mode, newest entries are placed at the far right.
            # Keep that edge in view as the content grows, otherwise the newest
            # input can sit outside the viewport while older entries remain visible.
            if self.flow_direction == "right_to_left":
                QTimer.singleShot(
                    0,
                    lambda: self.history_scroll.horizontalScrollBar().setValue(
                        self.history_scroll.horizontalScrollBar().maximum()
                    )
                )
            # Do not enlarge the window to fit the cards; the user controls
            # the overlay window height independently from card height.
        else:
            self.history_host.setMinimumWidth(0)
            self.history_host.setMinimumHeight(0)
        self.update_live_labels()
        self.adjust_overlay_height(len(entries))
        self.hint_label.setText("")

    @staticmethod
    def hex_rgb(value):
        value = value.lstrip("#")
        return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))

    def contextMenuEvent(self, event):
        # The navigation menu is intentionally hidden until the user right-clicks
        # the overlay, keeping the key viewer itself input-only.
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background:#202632; color:#eef2f8; border:1px solid #586273; padding:5px; }
            QMenu::item { padding:7px 24px; border-radius:4px; }
            QMenu::item:selected { background:#3b4658; }
            QMenu::separator { height:1px; background:#586273; margin:4px 8px; }
        """)
        settings = menu.addAction("Settings…")
        click = menu.addAction(
            "Disable click-through" if self.click_through else "Enable click-through"
        )
        clear = menu.addAction("Clear input history")
        menu.addSeparator()
        quit_action = menu.addAction("Exit")
        chosen = menu.exec(event.globalPos())
        if chosen == settings:
            self.open_settings()
        elif chosen == click:
            self.toggle_click_through()
        elif chosen == clear:
            self.clear_history()
        elif chosen == quit_action:
            self.close()

    def _borderless_resize_edges_at(self, pos):
        """Return the border edges under a local mouse position."""
        if not self.borderless or self.click_through:
            return set()
        margin = self._resize_margin
        edges = set()
        if pos.x() <= margin:
            edges.add("left")
        elif pos.x() >= self.width() - margin:
            edges.add("right")
        if pos.y() <= margin:
            edges.add("top")
        elif pos.y() >= self.height() - margin:
            edges.add("bottom")
        return edges

    def _set_resize_cursor(self, edges):
        if ("left" in edges and "top" in edges) or ("right" in edges and "bottom" in edges):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif ("right" in edges and "top" in edges) or ("left" in edges and "bottom" in edges):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif "left" in edges or "right" in edges:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif "top" in edges or "bottom" in edges:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.click_through:
            edges = self._borderless_resize_edges_at(event.position().toPoint())
            if edges:
                self._resize_edges = edges
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geometry = self.geometry()
                self.drag_pos = None
                event.accept()
                return
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resize_edges and self._resize_start_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            rect = self._resize_start_geometry
            left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
            min_w = max(1, self.minimumWidth())
            min_h = max(1, self.minimumHeight())
            if "left" in self._resize_edges:
                left = min(right - min_w + 1, left + delta.x())
            if "right" in self._resize_edges:
                right = max(left + min_w - 1, right + delta.x())
            if "top" in self._resize_edges:
                top = min(bottom - min_h + 1, top + delta.y())
            if "bottom" in self._resize_edges:
                bottom = max(top + min_h - 1, bottom + delta.y())
            self.setGeometry(left, top, right - left + 1, bottom - top + 1)
            event.accept()
            return
        if self.drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton and not self.click_through:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()
        else:
            self._set_resize_cursor(self._borderless_resize_edges_at(event.position().toPoint()))
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_pos = None
        self._resize_edges = set()
        self._resize_start_pos = None
        self._resize_start_geometry = None
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        # Keep the latest size for each layout orientation, including manual
        # borderless resizing, so switching orientation restores its own size.
        if hasattr(self, "_orientation_sizes") and hasattr(self, "orientation"):
            size = (self.width(), self.height())
            self._orientation_sizes[self.orientation] = size
            direction = getattr(self, "flow_direction", None)
            if hasattr(self, "_direction_sizes") and direction in self._direction_sizes:
                self._direction_sizes[direction] = size
        super().resizeEvent(event)

    def closeEvent(self, event):
        if sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = int(self.winId())
                for hotkey_id in getattr(self, "_global_hotkeys", {}):
                    user32.UnregisterHotKey(hwnd, hotkey_id)
            except Exception:
                pass
        try:
            pygame.quit()
        except Exception:
            pass
        self.save_app_settings()
        event.accept()
        # Since quitOnLastWindowClosed is disabled to protect the settings dialog,
        # explicitly quit when the main overlay itself is closed.
        QApplication.instance().quit()

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # The settings dialog is a separate top-level window. Do not terminate the
    # application merely because that dialog is closed.
    app.setQuitOnLastWindowClosed(False)
    window = ControllerOverlay()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
