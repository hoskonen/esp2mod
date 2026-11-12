# esp2mod

Move one `.esp`, `.esm`, or `.esl` from Mod Organizer 2's Overwrite folder into a new managed mod. Targets MO2 2.5.2 on Windows.

## Install

Copy the `esp2mod` folder into your MO2 installation's `plugins` directory so it contains `plugins\esp2mod\__init__.py`. Restart MO2. If you installed an earlier build, remove its `overwrite_organizer` package from `plugins` first.

## Use

1. Close the tool that created the plugin, then open **Tools → Move to New Mod...** in MO2.
2. Select an Overwrite plugin. Use **Show all** to find older files.
3. Review or edit the mod name, then click **Create Mod and Move**.

Only the selected file moves. The new mod is enabled for the current profile. Overwrite and the mods directory must be on the same drive.
