"""MO2 entry point. Host imports are deferred so the preview can be tested offline."""


def createPlugins():
    from .diagnostic import DiscoveryDiagnostic
    from .plugin import OverwritePickerTool

    return [OverwritePickerTool(), DiscoveryDiagnostic()]
