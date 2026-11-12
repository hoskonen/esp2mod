# esp2mod

Move one `.esp`, `.esm`, or `.esl` from Mod Organizer 2's Overwrite folder into a new managed mod. Targets MO2 2.5.2 on Windows.

## Install

Close MO2. If upgrading, remove the previous `esp2mod` or `overwrite_organizer` folder from MO2's `plugins` directory. Extract the ZIP directly into `plugins` so the result is `plugins\esp2mod\__init__.py`. Start MO2 and look for **Move to New Mod...** under **Tools**.

## Use

1. Close the tool that created the plugin, then open Tools → Move to New Mod... in MO2.
2. Select an ESP, ESM, or ESL from Overwrite. The most recently modified plugins appear first. If more than 10 are available, use Show all to view the complete list.
3. Review or edit the suggested mod name, then click Create Mod and Move.

Only the selected file is moved. The new mod is automatically enabled in the current MO2 profile.

## License

esp2mod is licensed under [GNU GPL version 3 only](LICENSE) (`GPL-3.0-only`). MO2 supplies the Python runtime, `mobase`, and PyQt6.
