"""Read-only selection and preview logic using MO2's public interfaces."""

from collections import Counter
from dataclasses import dataclass
import logging
from pathlib import Path
import re
import stat

_LOG = logging.getLogger(__name__)
_PLUGIN_EXTENSIONS = {".esp", ".esm", ".esl"}
_INVALID_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_DEVICE = re.compile(r"CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[1-9¹²³]", re.I)
_SPECIAL_MOD = re.compile(r"overwrite|data|.*_separator|.*_backup[0-9]*", re.I)
_RECENT_LIMIT = 10


class PreviewError(ValueError):
    """A validation failure that can be shown to the user."""


@dataclass(frozen=True)
class Candidate:
    filename: str
    source: Path
    stamp: tuple[int, int, int, int]


@dataclass(frozen=True)
class PluginStatus:
    enabled: bool | None
    load_order: int | None
    priority: int | None


@dataclass(frozen=True)
class OperationPreview:
    candidate: Candidate
    mod_name: str
    destination: Path
    status: PluginStatus
    profile: str


def file_stamp(status):
    return status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns


def valid_component(value):
    return (
        bool(value.strip())
        and len(value.encode("utf-16-le", errors="surrogatepass")) <= 510
        and value not in {".", ".."}
        and not value.endswith((".", " "))
        and not _INVALID_COMPONENT.search(value)
        and not _RESERVED_DEVICE.fullmatch(value.split(".", 1)[0].rstrip(" "))
    )


def valid_plugin_name(filename):
    return valid_component(filename) and Path(filename).suffix.lower() in _PLUGIN_EXTENSIONS


def suggest_mod_name(filename):
    return Path(filename).stem


def path_status(path):
    """Inspect a path and its ancestors without accepting links or reparse points."""
    status = path.lstat()
    for info in (status, *(parent.lstat() for parent in path.parents)):
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise PreviewError(f"Linked or redirected paths are unsupported: {path}")
    return status


def configured_directory(value, label):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise PreviewError(f"MO2 did not provide an absolute {label} directory.")
    try:
        if stat.S_ISDIR(path_status(path).st_mode):
            return path
    except (FileNotFoundError, NotADirectoryError):
        pass
    raise PreviewError(f"The configured {label} directory is unavailable: {path}")


def _candidate(organizer, plugins, overwrite, filename):
    if not valid_plugin_name(filename) or plugins.origin(filename).casefold() != "overwrite":
        return None
    origins = tuple(origin.casefold() for origin in organizer.getFileOrigins(filename))
    if origins != ("overwrite",):
        return None

    source = overwrite / filename
    resolved = Path(organizer.resolvePath(filename))
    if resolved != source:
        return None
    try:
        status = path_status(source)
        if stat.S_ISREG(status.st_mode) and source.samefile(resolved):
            return Candidate(filename, source, file_stamp(status))
    except (FileNotFoundError, NotADirectoryError, PreviewError):
        pass
    return None


def discover(organizer):
    overwrite = configured_directory(organizer.overwritePath(), "Overwrite")
    plugins = organizer.pluginList()
    names = tuple(plugins.pluginNames())
    counts = Counter(name.casefold() for name in names)
    candidates = [
        candidate
        for name in names
        if counts[name.casefold()] == 1
        and (candidate := _candidate(organizer, plugins, overwrite, name)) is not None
    ]
    return sorted(candidates, key=lambda item: (-item.stamp[3], item.filename.casefold()))


def picker_view(candidates, show_all, selected=None):
    visible = candidates if show_all else candidates[:_RECENT_LIMIT]
    index = visible.index(selected) if selected in visible else (0 if visible else -1)
    return visible, index


def verify_candidate(organizer, selected):
    overwrite = configured_directory(organizer.overwritePath(), "Overwrite")
    plugins = organizer.pluginList()
    matching = [name for name in plugins.pluginNames() if name.casefold() == selected.filename.casefold()]
    current = _candidate(organizer, plugins, overwrite, matching[0]) if len(matching) == 1 else None
    if current is None or current.source != selected.source:
        raise PreviewError("The selected plugin is no longer eligible. Reopen the picker to refresh it.")
    if current.stamp != selected.stamp:
        raise PreviewError("The selected plugin changed on disk. Finish saving and reopen the picker.")
    return plugins


def plugin_status(plugins, filename):
    enabled = None
    try:
        state = plugins.state(filename)
        value = getattr(state, "value", state)
        # MO2 2.5.2 returns QFlags<PluginState>. Missing is 0, inactive 1, active 2.
        if not isinstance(value, (bool, str, bytes, float)):
            enabled = {1: False, 2: True}.get(int(value))
    except (TypeError, ValueError):
        _LOG.debug("Unrecognized plugin state for %s", filename, exc_info=True)
    except Exception:
        _LOG.warning("Could not read the enabled state for %s", filename, exc_info=True)

    def position(method):
        try:
            value = getattr(plugins, method)(filename)
            return value if isinstance(value, int) and value >= 0 else None
        except Exception:
            _LOG.warning("Could not read plugin %s for %s", method, filename, exc_info=True)
            return None

    return PluginStatus(enabled, position("loadOrder"), position("priority"))


def destination_for(organizer, overwrite, mod_name):
    if not valid_component(mod_name) or mod_name != mod_name.strip() or _SPECIAL_MOD.fullmatch(mod_name):
        raise PreviewError("Enter a valid, non-reserved Windows mod name.")

    mods = configured_directory(organizer.modsPath(), "mods")
    if mods.is_relative_to(overwrite) or overwrite.is_relative_to(mods):
        raise PreviewError("The mods and Overwrite directories must be separate.")
    destination = mods / mod_name
    if (
        any(name.casefold() == mod_name.casefold() for name in organizer.modList().allMods())
        or any(entry.name.casefold() == mod_name.casefold() for entry in mods.iterdir())
    ):
        raise PreviewError("A mod or filesystem entry with that name already exists.")
    return destination


def build_preview(organizer, selected, mod_name):
    destination = destination_for(organizer, selected.source.parent, mod_name)
    plugins = verify_candidate(organizer, selected)
    profile = organizer.profilePath()
    if not profile:
        raise PreviewError("Open an MO2 profile before moving a plugin.")
    return OperationPreview(selected, mod_name, destination, plugin_status(plugins, selected.filename), profile)
