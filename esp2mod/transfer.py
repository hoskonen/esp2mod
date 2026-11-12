"""Coordinate the filesystem move and the public MO2 refresh and mod-list APIs."""

from dataclasses import dataclass
import logging
from pathlib import Path

from .file_move import FileMove, matches_file
from .preview import PreviewError, build_preview, plugin_status, verify_candidate

_LOG = logging.getLogger(__name__)
_REFRESH_TIMEOUT_MS = 30_000


@dataclass(frozen=True)
class TransferResult:
    title: str
    message: str
    level: str = "success"


class _RefreshRejected(PreviewError):
    pass


class Transfer:
    def __init__(self, organizer, preview, active_flag, schedule, report):
        self.organizer = organizer
        self.preview = preview
        self.active_flag = active_flag
        self.schedule = schedule
        self.report = report
        candidate = preview.candidate
        self.files = FileMove(candidate.source, candidate.stamp, preview.destination)
        self.pending = None
        self.mod_enabled = None

    def start(self):
        self._run(self._create_directory)

    def _run(self, step):
        try:
            step()
        except Exception as error:
            self._fail(error)

    def _check_context(self):
        if (
            self.organizer.profilePath() != self.preview.profile
            or Path(self.organizer.modsPath()) != self.files.directory.parent
            or Path(self.organizer.overwritePath()) != self.files.source.parent
        ):
            raise PreviewError("The active profile or configured paths changed. Reopen the picker.")

    def _check_initial_state(self, status):
        initial = self.preview.status
        if initial.enabled is not None and status.enabled is not None and initial.enabled != status.enabled:
            raise PreviewError("The game plugin's enabled state changed. Reopen the picker.")

    def _create_directory(self):
        self._check_context()
        current = build_preview(self.organizer, self.preview.candidate, self.preview.mod_name)
        self._check_initial_state(current.status)
        if current.profile != self.preview.profile or current.destination != self.preview.destination:
            raise PreviewError("The active profile or destination changed. Reopen the picker.")
        self.files.create_directory()
        self._refresh(self._enable_and_move)

    def _refresh(self, continuation):
        token = object()
        self.pending = token

        def finish():
            if self.pending is token:
                self.pending = None
                self._run(continuation)

        def timeout():
            if self.pending is token:
                self._fail(PreviewError("MO2 did not signal refresh completion."))

        # MO2 clears its callback list before finishing its own post-refresh updates.
        if not self.organizer.onNextRefresh(lambda: self.schedule(0, finish), False):
            raise _RefreshRejected("MO2 declined the refresh callback.")
        self.schedule(_REFRESH_TIMEOUT_MS, timeout)
        self.organizer.refresh()

    def _registered_mod(self):
        mod_list = self.organizer.modList()
        mod = mod_list.getMod(self.preview.mod_name)
        if mod is None:
            raise PreviewError("MO2 did not discover the new mod directory after refresh.")
        if (
            Path(mod.absolutePath()) != self.files.directory
            or mod.name().casefold() != self.preview.mod_name.casefold()
            or not self.files.directory.samefile(mod.absolutePath())
        ):
            raise PreviewError("MO2 registered a mod that does not match the new directory.")
        return mod_list, mod.name()

    def _enable_and_move(self):
        self._check_context()
        self.files.verify_empty_directory()
        mod_list, name = self._registered_mod()
        candidate = self.preview.candidate
        plugins = verify_candidate(self.organizer, candidate)
        self._check_initial_state(plugin_status(plugins, candidate.filename))

        # MO2 2.5.2 can enable game plugins when enabling a populated mod.
        if not mod_list.setActive(name, True):
            raise PreviewError("MO2 rejected activation of the new empty mod.")
        self._check_context()
        mod_list, name = self._registered_mod()
        self.mod_enabled = bool(mod_list.state(name) & self.active_flag)
        if not self.mod_enabled:
            raise PreviewError("MO2 did not report the new empty mod as enabled.")
        plugins = verify_candidate(self.organizer, candidate)
        self._check_initial_state(plugin_status(plugins, candidate.filename))
        self.files.move()

        try:
            self._refresh(self._verify)
        except _RefreshRejected:
            try:
                self._check_context()
                self.files.rollback()
            except (OSError, PreviewError) as error:
                raise PreviewError(f"MO2 declined the final refresh and rollback could not complete: {error}") from error
            try:
                self.organizer.refresh()
            except Exception:
                _LOG.exception("Could not refresh MO2 after returning the plugin to Overwrite")
            raise PreviewError("MO2 declined the final refresh. The plugin was returned to Overwrite.") from None

    def _verify(self):
        self.mod_enabled = None
        self._check_context()
        self.files.verify_destination()
        mod_list, name = self._registered_mod()
        self.mod_enabled = bool(mod_list.state(name) & self.active_flag)
        if not self.mod_enabled:
            raise PreviewError("MO2 did not report the new mod as enabled.")

        filename = self.preview.candidate.filename
        plugins = self.organizer.pluginList()
        matches = [entry for entry in plugins.pluginNames() if entry.casefold() == filename.casefold()]
        resolved = Path(self.organizer.resolvePath(filename))
        if (
            len(matches) != 1
            or plugins.origin(matches[0]).casefold() != name.casefold()
            or resolved != self.files.destination
            or not self.files.destination.samefile(resolved)
        ):
            raise PreviewError("MO2 does not resolve the plugin to the new mod.")

        current = plugin_status(plugins, matches[0])
        initial = self.preview.status
        warnings = []
        information = []
        if initial.enabled is None or current.enabled is None:
            information.append("Game-plugin activation could not be compared.")
        elif initial.enabled != current.enabled:
            expected = "enabled" if initial.enabled else "disabled"
            warnings.append(f"MO2 changed the game-plugin state. Set {filename} back to {expected} in the Plugins tab.")
        for label, before, after in (
            ("Load order", initial.load_order, current.load_order),
            ("Plugin priority", initial.priority, current.priority),
        ):
            if before is not None and before != after:
                if after is None:
                    information.append(f"{label} was {before} and is now unavailable.")
                else:
                    warnings.append(f"{label} was {before} and is now {after}. Check the Plugins tab.")
        if initial.enabled is True and initial.load_order is None:
            information.append("The original active load-order position was unavailable.")
        elif initial.load_order is None and initial.priority is None:
            information.append("The original plugin position was unavailable.")
        message = f"Moved {filename} to:\n{self.files.destination}\n\nThe mod is enabled in the active profile."
        if initial.enabled is not None and initial.enabled == current.enabled:
            message += f" The game plugin remains {'enabled' if current.enabled else 'disabled'}."
        if warnings:
            message += "\n\n" + "\n".join(warnings + information)
            self.report(TransferResult("Move complete with warnings", message, "warning"))
        elif information:
            _LOG.info("%s %s", message, " ".join(information))
            self.report(TransferResult("Move complete", " ".join(information), "information"))
        else:
            self.report(TransferResult("Move complete", message))

    def _fail(self, error):
        self.pending = None
        _LOG.warning("Transfer stopped for %s: %s", self.files.source, error,
                     exc_info=error if error.__traceback__ else None)
        if isinstance(error, FileExistsError):
            details = "The destination already exists. No existing file was replaced."
        elif isinstance(error, PermissionError):
            details = "Windows denied access. Close any tool using the file and check folder permissions."
        elif isinstance(error, PreviewError):
            details = str(error)
        elif isinstance(error, OSError):
            details = f"The filesystem operation failed: {error}"
        else:
            details = "MO2 could not complete the operation. See the MO2 log for details."

        if matches_file(self.files.source, self.files.stamp):
            location = f"Verified file in Overwrite:\n{self.files.source}"
        elif self.files.moved and matches_file(self.files.destination, self.files.stamp):
            location = (
                f"Verified file in the new mod directory:\n{self.files.destination}\n"
                "Refresh MO2 and check the mod's enablement and the plugin's state. "
                "To return the file manually, first make sure the original Overwrite path is vacant."
            )
        else:
            location = (
                "The selected file's location could not be verified. Inspect both paths before retrying:\n"
                f"{self.files.source}\n{self.files.destination}"
            )
        if self.files.created:
            activation = {
                True: "Last verified enabled",
                False: "Last verified disabled",
                None: "Enablement unverified",
            }[self.mod_enabled]
            mod = f"New mod directory created ({activation}):\n{self.files.directory}"
        else:
            mod = "No new mod directory was created."
        self.report(TransferResult("Move did not complete", f"{details}\n\n{location}\n\n{mod}", "failure"))
