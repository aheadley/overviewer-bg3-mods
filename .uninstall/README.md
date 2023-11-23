# Uninstallation

**NOTE** This process is untested, your mileage may vary. Some mods add permanent features to your characters, that will cause saves made after adding the mod to crash the game, if loaded after the mod is removed. So there are some in-game steps that need to be taken to prepare a save to work after mods are removed.

## In-game Prep

This is only required if you want to be able to load a campaign save after uninstalling mods, and should be done for each campaign to be kept.

  - Add each possible companion to the party (at the same time).
  - Un-equip these items, if any character is using them:
    - *Circle of Bones* from Act 2
    - *Crypt Lord Ring* from Act 3
  - On each party member (including the host character) disable the 2 Necromancy Passives added by *Animate Dead++* and remove them from the hotbar, if added. Also dismiss any summons, pets, etc that the character has.
  - Talk to the bone man and respec each character to whatever class they are and **DO NOT** level them up, leaving them at level 1.
  - Dismiss all characters from the party, down to only the host character.
  - Make a new save.

## Remove Mod Files

For the OPTIONAL MODS:

  - Delete `%steamapps%/common/Baldurs Gate 3/bin/bink2w64.dll`
  - In `%steamapps%/common/Baldurs Gate 3/bin/` , rename `bink2w64_original.dll` to `bink2w64.dll`
  - Delete `%steamapps%/common/Baldurs Gate 3/bin/NativeMods/`

For the required mods:

  - Delete the files in (but not the folder itself): `%localappdata%/Larian Studios/Baldur's Gate 3/Mods/`
  - Replace `%localappdata%/Larian Studios/Baldur's Gate 3/PlayerProfiles/Public/modsettings.lsx` with the one next to this README file.
  - In `%steamapps%/common/Baldurs Gate 3/Data/`: delete the `Public/` and `Mods/` folders.

Then verify the game installation in Steam and ensure those new saves that were made load in the game, and don't cause it to crash or something. Should also probably go ahead and make new, mod-free saves.
