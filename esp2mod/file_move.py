# SPDX-FileCopyrightText: 2026 Petri Hoskonen
# SPDX-License-Identifier: GPL-3.0-only

"""No-replace Windows file movement, independent of the MO2 and Qt runtimes."""

import errno
import os
import stat

from .preview import PreviewError, file_stamp, path_status


def directory_identity(path):
    status = path_status(path)
    if not stat.S_ISDIR(status.st_mode) or not status.st_ino:
        raise PreviewError(f"Cannot verify the directory identity: {path}")
    return status.st_dev, status.st_ino


def matches_file(path, stamp):
    try:
        status = path_status(path)
    except (OSError, PreviewError):
        return False
    return stat.S_ISREG(status.st_mode) and file_stamp(status) == stamp


def rename_no_replace(source, destination):
    if os.name != "nt":
        raise PreviewError("This release supports file moves on Windows only.")
    try:
        # On Windows os.rename fails if the destination exists or is on another volume.
        os.rename(source, destination)
    except OSError as error:
        if error.errno == errno.EXDEV or getattr(error, "winerror", None) == 17:
            raise PreviewError("Cross-volume moves are unsupported. Move the plugin manually.") from error
        raise


class FileMove:
    def __init__(self, source, stamp, directory):
        self.source = source
        self.stamp = stamp
        self.directory = directory
        self.destination = directory / source.name
        self.created = False
        self.moved = False

    def create_directory(self):
        if os.name != "nt":
            raise PreviewError("This release supports file moves on Windows only.")
        self.source_root = directory_identity(self.source.parent)
        self.mods_root = directory_identity(self.directory.parent)
        if not self.stamp[1] or not matches_file(self.source, self.stamp):
            raise PreviewError("The selected file changed or its identity could not be verified.")
        if self.stamp[0] != self.mods_root[0]:
            raise PreviewError("Cross-volume moves are unsupported. Move the plugin manually.")

        self.directory.mkdir(exist_ok=False)
        self.created = True
        self.directory_id = directory_identity(self.directory)

    def verify_directory(self):
        if (
            directory_identity(self.source.parent) != self.source_root
            or directory_identity(self.directory.parent) != self.mods_root
            or directory_identity(self.directory) != self.directory_id
        ):
            raise PreviewError("The Overwrite or destination directory changed during the operation.")

    def verify_empty_directory(self):
        self.verify_directory()
        # A freshly registered folder can contain MO2's own metadata.
        for entry in self.directory.iterdir():
            if entry.name.casefold() != "meta.ini" or not stat.S_ISREG(path_status(entry).st_mode):
                raise PreviewError("The new mod directory gained unexpected contents.")

    def move(self):
        self.verify_empty_directory()
        if not matches_file(self.source, self.stamp):
            raise PreviewError("The selected plugin changed or became unavailable before the move.")
        rename_no_replace(self.source, self.destination)
        self.moved = True
        self.verify_destination()

    def verify_destination(self):
        self.verify_directory()
        if not matches_file(self.destination, self.stamp):
            raise PreviewError("The moved file could not be verified at the destination.")

    def rollback(self):
        self.verify_destination()
        rename_no_replace(self.destination, self.source)
        self.moved = False
        if not matches_file(self.source, self.stamp):
            raise PreviewError("The returned file could not be verified in Overwrite.")
