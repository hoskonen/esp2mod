"""MO2 entry point. Host imports are deferred so the preview can be tested offline."""


def createPlugin():
    from .plugin import OverwritePickerTool

    return OverwritePickerTool()
