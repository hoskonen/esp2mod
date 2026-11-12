"""Manually invoked test of external mod discovery in a disposable MO2 instance."""

from dataclasses import dataclass
import logging
from pathlib import Path
import re
import stat
from uuid import uuid4

import mobase
from PyQt6.QtCore import QTimer, Qt, qInfo
from PyQt6.QtWidgets import QInputDialog, QMessageBox

from .picker import show_result
from .plugin import OrganizerTool
from .preview import PreviewError, configured_directory, path_status

_LOG = logging.getLogger(__name__)
_PREFIX = "MO2-Overwrite-Diagnostic-"
_TIMEOUT_MS = 30_000


@dataclass(frozen=True)
class Inspection:
    instance: str
    profile: str
    mods: Path
    names: tuple[str, ...]

    @property
    def context(self):
        return self.instance, self.profile, self.mods


class DiscoveryDiagnostic(OrganizerTool):
    _pending = None

    def name(self):
        return "MO2 Overwrite Organizer Discovery Diagnostic"

    def displayName(self):
        return "Overwrite Organizer: Mod Discovery Diagnostic..."

    def description(self):
        return "Inspect mod discovery and optionally test it in a disposable MO2 instance."

    def _inspect(self):
        organizer = self._organizer
        mods = configured_directory(organizer.modsPath(), "mods")
        profile = organizer.profilePath()
        if not profile:
            raise PreviewError("Open an MO2 profile before using this diagnostic.")
        mod_list = organizer.modList()
        for method in (organizer.refresh, organizer.onNextRefresh, mod_list.getMod,
                       mod_list.setActive, mod_list.state):
            if not callable(method):
                raise PreviewError("A required MO2 mod-list or refresh method is unavailable.")
        return Inspection(organizer.basePath(), profile, mods, tuple(mod_list.allMods()))

    def display(self):
        if self._pending is not None:
            show_result(self._parentWidget(), self.displayName(), "A refresh check is already running.")
            return
        try:
            self._show_inspection(self._inspect())
        except PreviewError as error:
            show_result(self._parentWidget(), self.displayName(), str(error), error=True)
        except Exception:
            _LOG.exception("Mod discovery diagnostic failed")
            show_result(self._parentWidget(), self.displayName(),
                        "The diagnostic failed. See the MO2 log for details.", error=True)

    def _show_inspection(self, inspection):
        parent = self._parentWidget()
        box = QMessageBox(parent)
        box.setWindowTitle(self.displayName())
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(
            f"Instance base: {inspection.instance}\n"
            f"Profile: {inspection.profile}\n"
            f"Mods directory: {inspection.mods}\n"
            f"MO2 mod-list entries: {len(inspection.names)}"
        )
        box.setDetailedText(
            "Available APIs: refresh, onNextRefresh, getMod, setActive, state\n\n"
            + ("\n".join(sorted(inspection.names, key=str.casefold)) or "No mod-list entries.")
        )
        start = box.addButton("Test in Disposable Instance...", QMessageBox.ButtonRole.ActionRole)
        check = box.addButton("Check Previous Test...", QMessageBox.ButtonRole.ActionRole)
        close = box.addButton(QMessageBox.StandardButton.Close)
        box.setDefaultButton(close)
        box.setEscapeButton(close)
        box.exec()

        if box.clickedButton() == start:
            phrase, accepted = QInputDialog.getText(
                parent,
                "Confirm Disposable Instance",
                "This creates and enables one new empty mod in the displayed instance. "
                "The test directory stays on disk.\n\n"
                "Verify this is a disposable instance with its own mods directory. "
                "Type DISPOSABLE to confirm.",
            )
            if accepted and phrase == "DISPOSABLE":
                self._start(inspection)
        elif box.clickedButton() == check:
            self._check_previous(inspection)

    def _registered_mod(self, directory):
        mod_list = self._organizer.modList()
        mod = mod_list.getMod(directory.name)
        if mod is not None and Path(mod.absolutePath()) != directory:
            raise PreviewError("The registered mod points to a different directory.")
        return mod

    def _start(self, inspection):
        current = self._inspect()
        if current.context != inspection.context:
            raise PreviewError("The instance, profile or mods directory changed. Reopen the diagnostic.")

        name = _PREFIX + uuid4().hex
        if any(existing.casefold() == name.casefold() for existing in current.names):
            raise PreviewError("The generated diagnostic name already exists. Reopen the diagnostic.")

        directory = current.mods / name
        directory.mkdir(exist_ok=False)
        qInfo(f"Mod discovery diagnostic directory created: {directory}")
        try:
            identity = path_status(directory)
            before = self._registered_mod(directory) is not None
            self._after_refresh(
                directory,
                lambda: self._enable_test_mod(current, directory, identity, before),
            )
        except Exception as error:
            self._report_failure(directory, error)

    def _after_refresh(self, directory, continuation):
        token = object()
        self._pending = token

        def finish():
            if self._pending is not token:
                return
            self._pending = None
            try:
                continuation()
            except Exception as error:
                self._report_failure(directory, error)

        def timeout():
            if self._pending is token:
                self._pending = None
                self._report_failure(directory, PreviewError("MO2 did not signal refresh completion."))

        try:
            # Defer the continuation until MO2 finishes dispatching and clearing callbacks.
            if not self._organizer.onNextRefresh(lambda: QTimer.singleShot(0, finish), False):
                raise PreviewError("MO2 declined the refresh callback.")
            QTimer.singleShot(_TIMEOUT_MS, timeout)
            self._organizer.refresh()
        except Exception:
            self._pending = None
            raise

    def _verify_test_directory(self, inspection, directory, identity):
        if self._inspect().context != inspection.context:
            raise PreviewError("The instance, profile or mods directory changed during refresh.")
        status = path_status(directory)
        if (
            not stat.S_ISDIR(status.st_mode)
            or (status.st_dev, status.st_ino) != (identity.st_dev, identity.st_ino)
        ):
            raise PreviewError("The diagnostic directory changed during refresh.")
        for entry in directory.iterdir():
            if entry.name.casefold() != "meta.ini" or not stat.S_ISREG(path_status(entry).st_mode):
                raise PreviewError("Unexpected contents appeared in the diagnostic directory.")

    def _enable_test_mod(self, inspection, directory, identity, before):
        self._verify_test_directory(inspection, directory, identity)
        if self._registered_mod(directory) is None:
            raise PreviewError(f"getMod() found no mod after refresh. Found before refresh: {before}.")
        if not self._organizer.modList().setActive(directory.name, True):
            raise PreviewError("MO2 rejected enablement of the diagnostic mod.")
        self._after_refresh(
            directory,
            lambda: self._report_activation(inspection, directory, identity, before),
        )

    def _is_active(self, name):
        return bool(self._organizer.modList().state(name) & mobase.ModState.ACTIVE)

    def _report_activation(self, inspection, directory, identity, before):
        self._verify_test_directory(inspection, directory, identity)
        if self._registered_mod(directory) is None or not self._is_active(directory.name):
            raise PreviewError(f"Mod enablement was not visible after refresh. Found before refresh: {before}.")
        message = (
            f"Test mod: {directory.name}\n"
            f"Directory: {directory}\n"
            f"Found before refresh: {'Yes' if before else 'No'}\n"
            "Found and active after refresh: Yes\n\n"
            "Copy the test mod name. Restart MO2 with the same profile and use "
            "Check Previous Test to verify persistence."
        )
        qInfo(message)
        show_result(self._parentWidget(), self.displayName(), message)

    def _check_previous(self, inspection):
        name, accepted = QInputDialog.getText(
            self._parentWidget(), "Check Previous Test", "Enter the test mod name from the previous run."
        )
        if not accepted:
            return
        if not re.fullmatch(re.escape(_PREFIX) + r"[0-9a-f]{32}", name):
            raise PreviewError("Enter the full name of an Overwrite Organizer diagnostic mod.")
        if self._inspect().context != inspection.context:
            raise PreviewError("The instance, profile or mods directory changed. Reopen the diagnostic.")
        directory = inspection.mods / name
        registered = self._registered_mod(directory) is not None
        active = registered and self._is_active(name)
        show_result(
            self._parentWidget(), self.displayName(),
            f"Profile: {inspection.profile}\nDirectory: {directory}\n"
            f"Registered: {'Yes' if registered else 'No'}\n"
            f"Enabled in this profile: {'Yes' if active else 'No'}",
        )

    def _report_failure(self, directory, error):
        _LOG.warning("Mod discovery diagnostic stopped for %s: %s", directory, error,
                     exc_info=error if error.__traceback__ else None)
        details = str(error) if isinstance(error, PreviewError) else "See the MO2 log for details."
        show_result(
            self._parentWidget(), self.displayName(),
            f"{details}\n\nTest directory: {directory}\nCheck its current mod state in MO2.",
            error=True,
        )
