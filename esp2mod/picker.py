# SPDX-FileCopyrightText: 2026 Petri Hoskonen
# SPDX-License-Identifier: GPL-3.0-only

"""PyQt presentation for plugin selection, confirmation, and transfer feedback."""

import logging

import mobase
from PyQt6.QtCore import QSignalBlocker, QTimer, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolTip,
)

from .preview import PreviewError, build_preview, destination_for, discover, picker_view, suggest_mod_name
from .transfer import Transfer

_LOG = logging.getLogger(__name__)


def show_result(parent, title, text, *, error=False):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Warning if error else QMessageBox.Icon.Information)
    box.exec()


class OverwritePicker(QDialog):
    def __init__(self, parent, organizer):
        super().__init__(parent)
        self.setWindowTitle("Move to New Mod...")
        self.setMinimumWidth(400)
        self._organizer = organizer
        self._candidates = discover(organizer)
        self._show_all = False
        self._transfer = None
        self._edited_names = {}

        layout = QFormLayout(self)
        self._plugins = QComboBox(self)
        self._plugins.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._plugins.setMinimumContentsLength(24)
        self._plugins.setPlaceholderText("Select an Overwrite plugin")
        layout.addRow("&Plugin", self._plugins)

        self._toggle_view = QPushButton("Show all", self)
        if picker_view(self._candidates, False)[0] != self._candidates:
            layout.addRow(self._toggle_view)
            self._toggle_view.clicked.connect(self._toggle_plugins)
        else:
            self._toggle_view.hide()

        self._mod_name = QLineEdit(self)
        layout.addRow("&Mod name", self._mod_name)

        self._destination = QLabel(self)
        self._destination.setTextFormat(Qt.TextFormat.PlainText)
        self._destination.setWordWrap(True)
        self._destination.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addRow("Destination", self._destination)

        self._status = QLabel(self)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setWordWrap(True)
        layout.addRow(self._status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        self._move = buttons.addButton("Create Mod and Move", QDialogButtonBox.ButtonRole.ActionRole)
        self._move.setAutoDefault(False)
        self._move.clicked.connect(self._start_move)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self._plugins.currentIndexChanged.connect(self._selection_changed)
        self._mod_name.textChanged.connect(self._name_changed)
        self._plugins.setEnabled(bool(self._candidates))
        self._populate()

    def _populate(self, selected=None):
        self._visible, index = picker_view(self._candidates, self._show_all, selected)
        with QSignalBlocker(self._plugins):
            self._plugins.clear()
            self._plugins.addItems([candidate.filename for candidate in self._visible])
            self._plugins.setCurrentIndex(index)
        if selected is None or index < 0 or self._visible[index] != selected:
            self._selection_changed(index)

    def _toggle_plugins(self):
        index = self._plugins.currentIndex()
        selected = self._visible[index] if index >= 0 else None
        self._show_all = not self._show_all
        self._toggle_view.setText("Show recent" if self._show_all else "Show all")
        self._populate(selected)

    def _selection_changed(self, index):
        selected = index >= 0
        filename = self._visible[index].filename if selected else ""
        self._plugins.setToolTip(filename)
        self._mod_name.setEnabled(selected)
        with QSignalBlocker(self._mod_name):
            self._mod_name.setText(self._edited_names.get(filename, suggest_mod_name(filename)))
        self._validate_destination()

    def _name_changed(self, name):
        index = self._plugins.currentIndex()
        if index >= 0:
            self._edited_names[self._visible[index].filename] = name
        self._validate_destination()

    def _validate_destination(self):
        index = self._plugins.currentIndex()
        self._move.setEnabled(False)
        self._destination.clear()
        self._destination.setToolTip("")
        if index < 0:
            self._status.setText("No eligible plugins were found in Overwrite.")
            return
        try:
            destination = destination_for(
                self._organizer, self._visible[index].source.parent, self._mod_name.text(),
            )
        except PreviewError as error:
            self._status.setText(str(error))
            return
        except Exception:
            _LOG.exception("Could not check the destination")
            self._status.setText("Could not check the destination. See the MO2 log.")
            return
        self._destination.setText(f"{destination.parent.name} / {destination.name}")
        self._destination.setToolTip(str(destination))
        self._status.setText("Only the selected plugin moves. The new mod is enabled for this profile.")
        self._move.setEnabled(True)

    def _start_move(self):
        index = self._plugins.currentIndex()
        if index < 0:
            return
        try:
            preview = build_preview(self._organizer, self._visible[index], self._mod_name.text())
        except PreviewError as error:
            self._status.setText(str(error))
            self._move.setEnabled(False)
            return
        except Exception:
            _LOG.exception("Could not build the Overwrite operation preview")
            self._status.setText("Could not verify the operation. See the MO2 log for details.")
            return

        self._status.setText("Creating the mod and waiting for MO2 to refresh…")
        self._transfer = Transfer(
            self._organizer, preview, mobase.ModState.ACTIVE, QTimer.singleShot, self._transfer_finished,
        )
        self.setEnabled(False)
        self._transfer.start()

    def reject(self):
        if self._transfer is None:
            super().reject()

    def closeEvent(self, event):
        if self._transfer is not None:
            event.ignore()
        else:
            super().closeEvent(event)

    def _transfer_finished(self, result):
        self._transfer = None
        self.setEnabled(True)
        if result.level in {"warning", "failure"}:
            show_result(self, result.title, result.message, error=True)
        position = self.mapToGlobal(self.rect().center())
        self.accept()
        if result.level == "information":
            QToolTip.showText(position, f"Plugin moved. {result.message}")
