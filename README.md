# Barony Save Editor

## Purpose
- Primary: compare Barony host & client saves to resolve mismatches quickly.
- Secondary: general JSON field editing and safe save management (backups & restore).

## Key features
- Host/Client compare view: inspect host values and up to 3 client saves side-by-side.
- Inline editing: edit client fields directly and apply updates back to client files.
- "Use Host" buttons: copy an individual host field into the selected client field.
- Mismatch hints: colored indicators and tooltips explain why a field is flagged.
- Automatic backups: creates timestamped backups before writing changes.
- Restore browser: browse saves that have backups and restore a chosen backup.
- Backup rotation: configurable max backups per save and max age (days).
- Save filtering and persistence: remember the last opened folder and filter .baronysave files.

## Notes
- This GUI is implemented with Tkinter and targets Windows & Linux.
- The app edits JSON-formatted Barony save files (`.baronysave`), while it may work for other `.JSON` files there is no guarantee as to how well that will work.
- Backups are stored in a `backups/` folder next to the selected save directory.

## Disclosure

program was made using prompts given to AI in Visual Studio Code.
