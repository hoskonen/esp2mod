# esp2mod

Move one `.esp`, `.esm`, or `.esl` from Mod Organizer 2's Overwrite folder into a new managed mod. Targets MO2 2.5.2 on Windows.

## Install

Close MO2. If upgrading, remove the previous `esp2mod` or `overwrite_organizer` folder from MO2's `plugins` directory. Extract the ZIP directly into `plugins` so the result is `plugins\esp2mod\__init__.py`. Start MO2 and look for **Move to New Mod...** under **Tools**.

## Use

1. Close the tool that created the plugin, then open **Tools → Move to New Mod...** in MO2.
2. Select an Overwrite plugin. Use **Show all** to find older files.
3. Review or edit the mod name, then click **Create Mod and Move**.

Only the selected file moves. The new mod is enabled for the current profile. Overwrite and the mods directory must be on the same Windows volume. If MO2 changes the plugin's activation or load order, check the Plugins tab.

## License

esp2mod is licensed under [GNU GPL version 3 only](LICENSE) (`GPL-3.0-only`). MO2 supplies the Python runtime, `mobase`, and PyQt6.
