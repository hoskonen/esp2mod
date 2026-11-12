# SPDX-FileCopyrightText: 2026 Petri Hoskonen
# SPDX-License-Identifier: GPL-3.0-only

"""MO2 entry point. Host imports are deferred so the preview can be tested offline."""


def createPlugin():
    from .plugin import OverwritePickerTool

    return OverwritePickerTool()
