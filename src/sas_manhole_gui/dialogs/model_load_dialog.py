from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from sas_manhole_gui.model_manager import CLASS_PRESETS, LoadedModel, load_model, parse_data_yaml

_PRESET_LABELS = [("single", "Single-class"), ("3class", "3-class"), ("6class", "6-class")]


class ModelLoadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Load Model")
        self.resize(560, 500)

        self.model_path: Optional[Path] = None
        self.loaded_model: Optional[LoadedModel] = None
        self.classes: dict[int, str] = {}
        self._model_names: dict[int, str] = {}

        layout = QVBoxLayout(self)

        model_row = QHBoxLayout()
        self.model_path_edit = QLineEdit()
        self.model_path_edit.setReadOnly(True)
        self.model_path_edit.setPlaceholderText("No model selected yet...")
        browse_btn = QPushButton("Select model file (.pt)...")
        browse_btn.clicked.connect(self._browse_model)
        model_row.addWidget(self.model_path_edit, 1)
        model_row.addWidget(browse_btn)
        layout.addLayout(model_row)

        yaml_row = QHBoxLayout()
        self.use_yaml_checkbox = QCheckBox("Use data.yaml")
        self.use_yaml_checkbox.toggled.connect(self._on_yaml_toggle)
        self.yaml_path_edit = QLineEdit()
        self.yaml_path_edit.setReadOnly(True)
        self.yaml_path_edit.setEnabled(False)
        self.yaml_browse_btn = QPushButton("Select...")
        self.yaml_browse_btn.setEnabled(False)
        self.yaml_browse_btn.clicked.connect(self._browse_yaml)
        yaml_row.addWidget(self.use_yaml_checkbox)
        yaml_row.addWidget(self.yaml_path_edit, 1)
        yaml_row.addWidget(self.yaml_browse_btn)
        layout.addLayout(yaml_row)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset (paper):"))
        for key, label in _PRESET_LABELS:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, k=key: self._apply_preset(k))
            preset_row.addWidget(btn)
        preset_row.addStretch(1)
        layout.addLayout(preset_row)

        layout.addWidget(QLabel("Classes (editable):"))
        self.class_table = QTableWidget(0, 2)
        self.class_table.setHorizontalHeaderLabels(["ID", "Name"])
        self.class_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.class_table, 1)

        class_btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add Class")
        add_btn.clicked.connect(self._add_class_row)
        remove_btn = QPushButton("Delete Selected")
        remove_btn.clicked.connect(self._remove_selected_rows)
        class_btn_row.addWidget(add_btn)
        class_btn_row.addWidget(remove_btn)
        class_btn_row.addStretch(1)
        layout.addLayout(class_btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_model(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(self, "Select model file", "", "YOLO Model (*.pt)")
        if not path_str:
            return
        path = Path(path_str)
        self.model_path_edit.setText(str(path))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            loaded = load_model(path)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Error", f"Could not load model:\n{exc}")
            return
        QApplication.restoreOverrideCursor()

        self.model_path = path
        self.loaded_model = loaded
        self._model_names = loaded.names
        if not self.use_yaml_checkbox.isChecked():
            self._set_classes(loaded.names)

    def _browse_yaml(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(self, "Select data.yaml", "", "YAML (*.yaml *.yml)")
        if not path_str:
            return
        path = Path(path_str)
        self.yaml_path_edit.setText(str(path))
        try:
            names = parse_data_yaml(path)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Could not read data.yaml:\n{exc}")
            return
        self._set_classes(names)

    def _on_yaml_toggle(self, checked: bool) -> None:
        self.yaml_path_edit.setEnabled(checked)
        self.yaml_browse_btn.setEnabled(checked)
        if not checked and self._model_names:
            self._set_classes(self._model_names)

    def _apply_preset(self, key: str) -> None:
        self._set_classes(CLASS_PRESETS[key])

    def _set_classes(self, names: dict[int, str]) -> None:
        self.class_table.setRowCount(0)
        for class_id, name in sorted(names.items()):
            self._append_row(class_id, name)

    def _append_row(self, class_id: int, name: str) -> None:
        row = self.class_table.rowCount()
        self.class_table.insertRow(row)
        self.class_table.setItem(row, 0, QTableWidgetItem(str(class_id)))
        self.class_table.setItem(row, 1, QTableWidgetItem(name))

    def _add_class_row(self) -> None:
        self._append_row(self.class_table.rowCount(), f"class_{self.class_table.rowCount()}")

    def _remove_selected_rows(self) -> None:
        rows = sorted({idx.row() for idx in self.class_table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.class_table.removeRow(r)

    def _on_accept(self) -> None:
        if self.model_path is None or self.loaded_model is None:
            QMessageBox.warning(self, "Missing information", "Please select a model (.pt) file.")
            return
        classes: dict[int, str] = {}
        for row in range(self.class_table.rowCount()):
            id_item = self.class_table.item(row, 0)
            name_item = self.class_table.item(row, 1)
            if id_item is None or name_item is None:
                continue
            try:
                class_id = int(id_item.text())
            except ValueError:
                continue
            classes[class_id] = name_item.text().strip() or f"class_{class_id}"
        if not classes:
            QMessageBox.warning(self, "Missing information", "At least one class must be defined.")
            return
        self.classes = classes
        self.accept()
