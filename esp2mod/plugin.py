# SPDX-FileCopyrightText: 2026 Petri Hoskonen
# SPDX-License-Identifier: GPL-3.0-only

"""MO2 tool registration."""

import logging

import mobase
from PyQt6.QtCore import qInfo
from PyQt6.QtGui import QIcon

from .picker import OverwritePicker, show_result
from .preview import PreviewError

_LOG = logging.getLogger(__name__)


class OrganizerTool(mobase.IPluginTool):
    def init(self, organizer):
        if organizer is None:
            _LOG.error("%s initialized without an organizer interface", self.name())
            return False
        self._organizer = organizer
        qInfo(f"{self.name()} initialized")
        return True

    def author(self):
        return "MO2 Overwrite Organizer contributors"

    def version(self):
        return mobase.VersionInfo(0, 1, 0)

    def settings(self):
        return []

    def tooltip(self):
        return self.description()

    def icon(self):
        return QIcon()


class OverwritePickerTool(OrganizerTool):
    def name(self):
        return "MO2 Overwrite Organizer"

    def displayName(self):
        return "Move to New Mod..."

    def description(self):
        return "Move a game plugin from Overwrite into a new mod."

    def display(self):
        parent = self._parentWidget()
        try:
            picker = OverwritePicker(parent, self._organizer)
            try:
                picker.exec()
            finally:
                picker.deleteLater()
        except PreviewError as error:
            show_result(parent, self.displayName(), str(error), error=True)
        except Exception:
            _LOG.exception("Could not open the Overwrite picker")
            show_result(parent, self.displayName(), "Could not read MO2's plugin list. See the MO2 log.", error=True)
