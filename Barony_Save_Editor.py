import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import shutil
import time

BARONY_SAVE_EXT = ".baronysave"


def bind_mousewheel(widget):
    def _on_mousewheel(event):
        if hasattr(event, "num") and event.num in {4, 5}:
            widget.yview_scroll(-1 if event.num == 4 else 1, "units")
            return
        if hasattr(event, "delta"):
            widget.yview_scroll(int(-1 * (event.delta / 120)), "units")

    widget.bind("<MouseWheel>", _on_mousewheel)
    widget.bind("<Button-4>", lambda event: widget.yview_scroll(-1, "units"))
    widget.bind("<Button-5>", lambda event: widget.yview_scroll(1, "units"))


class ScrollableFrame(ttk.Frame):
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        canvas = tk.Canvas(self, borderwidth=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scroll_frame = ttk.Frame(canvas)

        self.scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )

        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        bind_mousewheel(canvas)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")


class ToolTip:
    """Simple tooltip for Tkinter widgets."""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, event=None):
        if self.tipwindow or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify=tk.LEFT, background="#ffffe0", relief=tk.SOLID, borderwidth=1, font=(None, 9))
        label.pack(ipadx=4, ipady=2)

    def hide(self, event=None):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()


def parse_path(path_str):
    tokens = []
    current = ""
    i = 0
    while i < len(path_str):
        ch = path_str[i]
        if ch == ".":
            if current:
                tokens.append(current)
                current = ""
            i += 1
        elif ch == "[":
            if current:
                tokens.append(current)
                current = ""
            end = path_str.find("]", i)
            if end == -1:
                raise ValueError("Invalid path string")
            index = int(path_str[i + 1 : end])
            tokens.append(index)
            i = end + 1
        else:
            current += ch
            i += 1
    if current:
        tokens.append(current)
    return tokens


def nested_set(data, tokens, value):
    current = data
    for token in tokens[:-1]:
        current = current[token]
    current[tokens[-1]] = value


class JsonEditorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Barony Save Editor")
        self.geometry("1000x650")
        self.resizable(False, False)

        self.json_data = None
        self.current_file = None
        self.fields = {}
        self.type_map = {}
        self.player_fields = {}
        self.metadata_fields = {}
        self.save_filter = tk.StringVar(value="both")
        self.backup_max_per_save = 10
        self.backup_max_age_days = 30
        self.config_path = Path.home() / ".barony_save_editor_config.json"

        self._build_ui()
        self._load_config()

    def _show_message(self, kind, title, message, parent=None):
        if parent is None:
            parent = self
        if kind == "error":
            return messagebox.showerror(title, message, parent=parent)
        if kind == "warning":
            return messagebox.showwarning(title, message, parent=parent)
        return messagebox.showinfo(title, message, parent=parent)

    def _build_ui(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill="both", expand=True)

        left_panel = ttk.Frame(main_frame, width=280)
        left_panel.pack(side="left", fill="y", padx=(0, 10))

        ttk.Label(left_panel, text="Save Directory", font=(None, 11, "bold")).pack(anchor="w")
        self.dir_label = ttk.Label(left_panel, text="No folder selected", wraplength=260)
        self.dir_label.pack(anchor="w", pady=(0, 10))

        ttk.Button(left_panel, text="Choose Folder", command=self.choose_folder).pack(fill="x")
        ttk.Button(left_panel, text="Refresh Save List", command=self.refresh_json_list).pack(fill="x", pady=(5, 10))

        filter_frame = ttk.LabelFrame(left_panel, text="Show saves")
        filter_frame.pack(fill="x", pady=(0, 10))
        ttk.Radiobutton(filter_frame, text="Both", variable=self.save_filter, value="both", command=self.refresh_json_list).pack(anchor="w", padx=6, pady=2)
        ttk.Radiobutton(filter_frame, text="Single player", variable=self.save_filter, value="single", command=self.refresh_json_list).pack(anchor="w", padx=6, pady=2)
        ttk.Radiobutton(filter_frame, text="Multiplayer", variable=self.save_filter, value="multi", command=self.refresh_json_list).pack(anchor="w", padx=6, pady=2)

        self.file_list = tk.Listbox(left_panel, height=25)
        self.file_list.pack(fill="both", expand=True)
        self.file_list.bind("<<ListboxSelect>>", self.on_file_select)
        bind_mousewheel(self.file_list)

        right_panel = ttk.Frame(main_frame)
        right_panel.pack(side="left", fill="both", expand=True)

        top_buttons = ttk.Frame(right_panel)
        top_buttons.pack(fill="x", pady=(0, 10))

        ttk.Button(top_buttons, text="Reload File", command=self.reload_file).pack(side="left")
        ttk.Button(top_buttons, text="Save Changes", command=self.save_changes).pack(side="left", padx=(10, 0))
        ttk.Button(top_buttons, text="Validate Host/Client", command=self.open_validation_window).pack(side="left", padx=(10, 0))
        ttk.Button(top_buttons, text="Restore Backup", command=self.restore_backup).pack(side="left", padx=(10, 0))
        ttk.Button(top_buttons, text="Settings", command=self.open_settings_window).pack(side="left", padx=(10,0))

        file_info_frame = ttk.Frame(right_panel)
        file_info_frame.pack(fill="x", pady=(10, 10))

        self.file_path_label = ttk.Label(file_info_frame, text="No file loaded", font=(None, 10, "italic"))
        self.file_path_label.pack(anchor="w")

        player_selector_frame = ttk.Frame(file_info_frame)
        player_selector_frame.pack(fill="x", pady=(6, 0))
        ttk.Label(player_selector_frame, text="Selected Player:").pack(side="left")
        self.player_combo = ttk.Combobox(player_selector_frame, state="readonly", width=24)
        self.player_combo.pack(side="left", padx=(6, 0))
        self.player_combo.bind("<<ComboboxSelected>>", self.on_player_selected)

        self.editor_container = ScrollableFrame(right_panel)
        self.editor_container.pack(fill="both", expand=True)

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Select Barony save folder")
        if not folder:
            return
        self.base_dir = Path(folder)
        self.dir_label.config(text=str(self.base_dir))
        self._save_config()
        self.refresh_json_list()

    def _load_config(self):
        if not self.config_path.exists():
            return
        try:
            with self.config_path.open("r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            return

        self.save_filter.set(config.get("save_filter", "both"))
        self.backup_max_per_save = config.get("backup_max_per_save", self.backup_max_per_save)
        self.backup_max_age_days = config.get("backup_max_age_days", self.backup_max_age_days)
        folder = config.get("last_directory")
        if folder:
            path = Path(folder)
            if path.exists() and path.is_dir():
                self.base_dir = path
                self.dir_label.config(text=str(self.base_dir))
                self.refresh_json_list()

    def _save_config(self):
        try:
            with self.config_path.open("w", encoding="utf-8") as f:
                json.dump({
                    "last_directory": str(self.base_dir),
                    "save_filter": self.save_filter.get(),
                    "backup_max_per_save": int(self.backup_max_per_save),
                    "backup_max_age_days": int(self.backup_max_age_days),
                }, f, indent=2)
        except Exception:
            pass

    def _matches_filter(self, path: Path):
        name = path.name.lower()
        is_multi = name.endswith(f"_mp{BARONY_SAVE_EXT}")
        mode = self.save_filter.get()
        if mode == "both":
            return True
        if mode == "single":
            return not is_multi
        if mode == "multi":
            return is_multi
        return True

    def refresh_json_list(self):
        if not hasattr(self, "base_dir") or not self.base_dir.exists():
            messagebox.showwarning("No folder", "Please choose a folder containing JSON files first.")
            return

        self.file_list.delete(0, tk.END)
        for path in sorted(self.base_dir.glob(f"*{BARONY_SAVE_EXT}")):
            if self._matches_filter(path):
                self.file_list.insert(tk.END, path.name)

        self.clear_editor()
        no_files_text = {
            "both": f"No {BARONY_SAVE_EXT} files found in folder.",
            "single": f"No single-player{BARONY_SAVE_EXT} files found.",
            "multi": f"No multiplayer{BARONY_SAVE_EXT} files found.",
        }.get(self.save_filter.get(), f"No {BARONY_SAVE_EXT} files found in folder.")
        self.file_path_label.config(text="Select a file from the list to begin." if self.file_list.size() else no_files_text)

    def on_file_select(self, event):
        selection = self.file_list.curselection()
        if not selection:
            return
        index = selection[0]
        file_name = self.file_list.get(index)
        self.load_file(self.base_dir / file_name)

    def load_file(self, path: Path):
        try:
            with path.open("r", encoding="utf-8") as f:
                self.json_data = json.load(f)
        except Exception as exc:
            messagebox.showerror("Failed to load", f"Could not read save file:\n{exc}")
            return

        self.current_file = path
        self.file_path_label.config(text=str(path))
        self._update_player_selector()
        self.build_editor()

    def reload_file(self):
        if not self.current_file:
            messagebox.showinfo("No file", "No JSON file is currently loaded.")
            return
        self.load_file(self.current_file)

    def clear_editor(self):
        for child in self.editor_container.scroll_frame.winfo_children():
            child.destroy()
        self.fields.clear()
        self.type_map.clear()
        self.player_fields.clear()
        self.metadata_fields.clear()

    def build_editor(self):
        self.clear_editor()
        if self.json_data is None:
            return

        ttk.Label(self.editor_container.scroll_frame, text="Barony save editor", font=(None, 12, "bold")).pack(anchor="w", pady=(0, 10))
        self._build_metadata_section()
        self._build_player_section()

    def _build_metadata_section(self):
        section = ttk.LabelFrame(self.editor_container.scroll_frame, text="Save metadata")
        section.pack(fill="x", pady=(0, 10), padx=2)

        metadata_keys = [
            "game_name",
            "mapseed",
            "gametimer",
            "svflags",
            "player_num",
            "multiplayer_type",
            "players_connected",
            "dungeon_lvl",
            "customseed",
            "customseed_string",
        ]

        # tooltips for specific metadata fields
        tooltips = {
            "mapseed": "Client savefile should have the same value as the host.",
            "dungeon_lvl": "Client savefile should have the same value as the host.",
            "level_track": "Client savefile should have the same value as the host.",
            "multiplayer_type": "Singleplayer = 0 |Host = 1 | Client = 2",
            "player_num": "Host should be 0; Client should be 1, 2 or 3 depending on which player slot they are in.",
            "players_connected": "Host is the first 1. the second third and fourth entries are 1 if there is a player for that slot or 0 if not.",
        }

        for key in metadata_keys:
            if key in self.json_data:
                tip = tooltips.get(key)
                self._build_field_row(section, key, self.json_data[key], target_store=self.metadata_fields, tooltip=tip)

    def _build_player_section(self):
        players = self.json_data.get("players", [])
        if not players:
            return

        self.selected_player_index = int(self.player_combo.get().split(":", 1)[0]) if self.player_combo.get() else 0
        current_player = players[self.selected_player_index]

        section = ttk.LabelFrame(self.editor_container.scroll_frame, text="Selected player data")
        section.pack(fill="both", expand=True, pady=(0, 10), padx=2)

        player_info = [
            ("char_class", current_player.get("char_class")),
            ("race", current_player.get("race")),
            ("conduct_penniless", current_player.get("conduct_penniless")),
            ("conduct_foodless", current_player.get("conduct_foodless")),
            ("conduct_vegetarian", current_player.get("conduct_vegetarian")),
            ("conduct_illiterate", current_player.get("conduct_illiterate")),
        ]
        for name, value in player_info:
            self._build_field_row(section, f"players[{self.selected_player_index}].{name}", value, target_store=self.player_fields)

        stats = current_player.get("stats", {})
        stats_section = ttk.LabelFrame(section, text="Stats")
        stats_section.pack(fill="x", pady=(10, 0), padx=2)

        stats_keys = [
            "name",
            "type",
            "sex",
            "appearance",
            "HP",
            "maxHP",
            "MP",
            "maxMP",
            "STR",
            "DEX",
            "CON",
            "INT",
            "PER",
            "CHR",
            "EXP",
            "LVL",
            "GOLD",
            "HUNGER",
        ]
        for key in stats_keys:
            if key in stats:
                self._build_field_row(stats_section, f"players[{self.selected_player_index}].stats.{key}", stats[key], target_store=self.player_fields)

    def _update_player_selector(self):
        players = self.json_data.get("players", []) if self.json_data else []
        player_names = [self._format_player_label(i, player) for i, player in enumerate(players)]
        self.player_combo["values"] = player_names
        if player_names:
            self.player_combo.current(0)

    def on_player_selected(self, event=None):
        if not self.json_data:
            return
        self.build_editor()

    def _format_player_label(self, index, player):
        name = player.get("stats", {}).get("name") or f"Player {index}"
        return f"{index}: {name}"

    def open_validation_window(self):
        files = sorted(self.base_dir.glob(f"*{BARONY_SAVE_EXT}")) if hasattr(self, "base_dir") else []
        if not files:
            self._show_message("info", "No saves", "No save files available to compare. Select a folder first.", parent=None)
            return

        win = tk.Toplevel(self)
        win.title("Validate Host vs Client")
        win.geometry("900x520")
        win.resizable(False, False)

        # selectors (placed at the top to avoid overlapping the left/right panes)
        selector_frame = ttk.Frame(win, padding=(10, 6))
        selector_frame.pack(fill="x", side="top")
        ttk.Label(selector_frame, text="Host file:").grid(row=0, column=0, sticky="e")
        host_combo = ttk.Combobox(selector_frame, values=[p.name for p in files], width=60, state="readonly")
        host_combo.grid(row=0, column=1, padx=8, sticky="w")

        # client picker rendered as checkboxes so it feels cleaner and less cluttered
        client_options_frame = ttk.LabelFrame(selector_frame, text="Client files")
        client_options_frame.grid(row=1, column=1, columnspan=3, padx=8, pady=(6, 4), sticky="w")
        client_options_frame.grid_remove()

        client_canvas = tk.Canvas(client_options_frame, width=420, height=120, highlightthickness=0)
        bind_mousewheel(client_canvas)
        client_canvas.pack(side="left", fill="both", expand=True)
        client_scroll = ttk.Scrollbar(client_options_frame, orient="vertical", command=client_canvas.yview)
        client_scroll.pack(side="right", fill="y")
        client_canvas.configure(yscrollcommand=client_scroll.set)

        client_inner = ttk.Frame(client_canvas)
        client_canvas.create_window((0, 0), window=client_inner, anchor="nw")
        client_inner.bind("<Configure>", lambda event: client_canvas.configure(scrollregion=client_canvas.bbox("all")))

        client_checkvars = {}

        def refresh_client_checkboxes(host_name):
            for child in client_inner.winfo_children():
                child.destroy()
            client_checkvars.clear()

            if not host_name:
                client_options_frame.grid_remove()
                return

            available_clients = [p.name for p in files if p.name != host_name]
            if not available_clients:
                ttk.Label(client_inner, text="No additional client saves available.", wraplength=360).pack(anchor="w", padx=6, pady=6)
            else:
                ttk.Label(client_inner, text="Select up to 3 client files to compare:", wraplength=360).pack(anchor="w", padx=6, pady=(4, 4))
                for name in available_clients:
                    var = tk.BooleanVar(value=False)
                    client_checkvars[name] = var
                    row = ttk.Frame(client_inner)
                    row.pack(fill="x", padx=4, pady=2)
                    ttk.Checkbutton(row, variable=var, text=name).pack(anchor="w")

            client_options_frame.grid()
            client_inner.update_idletasks()
            client_canvas.configure(scrollregion=client_canvas.bbox("all"))

        # top button area next to selectors so controls are always visible
        selector_button_frame = ttk.Frame(selector_frame)
        selector_button_frame.grid(row=0, column=2, rowspan=2, padx=8, sticky="n")

        # separate selectors from comparison area
        ttk.Separator(win, orient="horizontal").pack(fill="x", padx=10, pady=6)

        compare_frame = ttk.Frame(win, padding=10)
        compare_frame.pack(fill="both", expand=True)

        left = ttk.Frame(compare_frame)
        left.grid(row=0, column=0, sticky="nsew")
        right = ttk.Frame(compare_frame)
        right.grid(row=0, column=1, sticky="nsew")
        compare_frame.columnconfigure(0, weight=1)
        compare_frame.columnconfigure(1, weight=1)

        # leave the host selector blank until the user chooses a host explicitly
        if self.current_file and self.current_file.name in [p.name for p in files]:
            host_combo.set(self.current_file.name)
        else:
            host_combo.set("")

        def on_host_select(event=None):
            name = host_combo.get()
            if not name:
                refresh_client_checkboxes("")
                return
            path = self.base_dir / name
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as exc:
                self._show_message("error", "Load error", f"Could not read host file:\n{exc}", parent=win)
                host_combo.set("")
                refresh_client_checkboxes("")
                return

            if data.get("player_num") != 0 or data.get("multiplayer_type") != 1:
                self._show_message("error", "Invalid host", "Selected host file is not a valid host save (player_num must be 0 and multiplayer_type must be 1).", parent=win)
                host_combo.set("")
                refresh_client_checkboxes("")
                return

            refresh_client_checkboxes(name)

        host_combo.bind("<<ComboboxSelected>>", on_host_select)
        # trigger validation if already set
        if host_combo.get():
            on_host_select()

        # compare results area
        # Use a shared grid so host and client rows align
        fields_frame = ttk.Frame(compare_frame)
        fields_frame.grid(row=1, column=0, columnspan=2, sticky="nsew")
        compare_frame.rowconfigure(1, weight=1)

        # fields to compare
        compare_keys = [
            "mapseed",
            "player_num",
            "multiplayer_type",
            "dungeon_lvl",
            "level_track",
            "players_connected",
        ]

        left_labels = {}
        # header labels placed in the shared grid so host and client columns align
        ttk.Label(fields_frame, text="Host", font=(None, 11, "bold")).grid(row=0, column=1, sticky="nw", padx=4, pady=(0, 8))
        client_header_frame = ttk.Frame(fields_frame)
        client_header_frame.grid(row=0, column=2, sticky="nw", padx=4, pady=(0, 8))
        client_top_frame = ttk.Frame(client_header_frame)
        client_top_frame.pack(anchor="w")
        ttk.Label(client_top_frame, text="Client(s)", font=(None, 11, "bold")).pack(side="left")
        current_client_label = ttk.Label(client_top_frame, text="", font=(None, 9), foreground="#444444")
        current_client_label.pack(side="left", padx=(8, 0))
        rad_inner = ttk.Frame(client_header_frame)
        rad_inner.pack(anchor="w", pady=(8, 0))

        # create key and host columns in the shared fields_frame
        for i, key in enumerate(compare_keys, start=2):
            ttk.Label(fields_frame, text=key).grid(row=i, column=0, sticky="w", padx=4, pady=4)
            lval = ttk.Label(fields_frame, text="", width=40)
            lval.grid(row=i, column=1, sticky="w", padx=4)
            left_labels[key] = lval
        # client entries will go in column 2 of fields_frame

        def do_compare():
            host_name = host_combo.get()
            selected_client_names = [name for name, var in client_checkvars.items() if var.get()]
            if not host_name or not selected_client_names:
                self._show_message("warning", "Select files", "Please select a valid host and at least one client (up to 3) to compare.", parent=win)
                return
            if len(selected_client_names) > 3:
                self._show_message("warning", "Too many clients", "Please select up to 3 client files to compare.", parent=win)
                return

            client_names = selected_client_names
            host_path = self.base_dir / host_name
            try:
                with host_path.open("r", encoding="utf-8") as f:
                    host_data = json.load(f)
            except Exception as exc:
                self._show_message("error", "Load error", f"Could not read host file:\n{exc}", parent=win)
                return

            # validate host
            if host_data.get("player_num") != 0 or host_data.get("multiplayer_type") != 1:
                self._show_message("error", "Invalid host", "Selected host file does not look like a valid host save (player_num must be 0 and multiplayer_type must be 1).", parent=win)
                return

            # populate host values into the left column
            for key in compare_keys:
                left_labels[key].config(text=str(host_data.get(key, "<MISSING>")), foreground="black")

            # clear previous client column in shared fields_frame (column 2)
            # keep header at row 0 intact; only remove rows for actual client fields (row >= 1)
            for child in fields_frame.grid_slaves(column=2):
                info = child.grid_info()
                try:
                    r = int(info.get('row', 0))
                except Exception:
                    r = 0
                if r >= 1:
                    child.destroy()

            # remove any existing radio/button frames from previous compares
            if hasattr(win, '_rad_frame'):
                try:
                    win._rad_frame.destroy()
                except Exception:
                    pass

            # ensure selector button area doesn't accumulate repeated Apply buttons
            try:
                for child in selector_button_frame.winfo_children():
                    try:
                        if child.cget("text") != "Compare":
                            child.destroy()
                    except Exception:
                        pass
            except Exception:
                pass

            client_widgets = {}
            client_paths = {}
            client_datas = {}
            client_names_by_index = {}

            # create a fresh inner radio container inside the header cell (previous one may have been destroyed)
            rad_inner = ttk.Frame(client_header_frame)
            rad_inner.pack(anchor="w", pady=(8, 0))
            # reference the inner radio container so we can destroy radios without removing the header
            win._rad_frame = rad_inner
            ttk.Label(rad_inner, text="Client slot:", font=(None, 9)).pack(side="left")
            selected_client = tk.IntVar(value=0)
            # persist the IntVar on window to prevent GC issues
            win._selected_client = selected_client

            def show_client(idx):
                current_client_label.config(text=client_names_by_index.get(idx, ""))
                # clear existing client column but preserve header row (row 0)
                for child in fields_frame.grid_slaves(column=2):
                    info = child.grid_info()
                    try:
                        r = int(info.get('row', 0))
                    except Exception:
                        r = 0
                    if r >= 2:
                        child.destroy()
                data = client_datas.get(idx)
                if data is None:
                    return
                any_mismatch = False
                for i, key in enumerate(compare_keys, start=2):
                    cval = data.get(key, "<MISSING>")
                    entry = ttk.Entry(fields_frame, width=30)
                    entry.insert(0, str(cval))
                    entry.grid(row=i, column=2, sticky="w", padx=4, pady=2)

                    # mismatch logic and reason tooltip for each displayed client field
                    mismatch = False
                    reason = None
                    hval = host_data.get(key, "<MISSING>")
                    if key in ("mapseed", "dungeon_lvl", "level_track"):
                        mismatch = (hval != cval)
                        if mismatch:
                            reason = "Should match host."
                    elif key == "multiplayer_type":
                        mismatch = not (hval == 1 and cval == 2)
                        if mismatch:
                            reason = "Host should be 1; client should be 2."
                    elif key == "player_num":
                        mismatch = not (hval == 0 and isinstance(cval, int) and cval > 0)
                        if mismatch:
                            reason = "Host should be 0; client should be a positive player index."
                    elif key == "players_connected":
                        mismatch = (hval != cval)
                        if mismatch:
                            reason = "Entries indicate which player slots are occupied; first entry is host."

                    if mismatch:
                        entry.config(foreground="red")
                        left_labels[key].config(foreground="red")
                        if reason:
                            ToolTip(entry, reason)
                        any_mismatch = True
                    else:
                        entry.config(foreground="green")
                        left_labels[key].config(foreground="green")

                    # add a 'Use Host' button for fields that are expected to match the host
                    MATCH_KEYS = ("mapseed", "dungeon_lvl", "level_track", "players_connected")
                    if key in MATCH_KEYS:
                        def _use_host(k=key, ent=entry):
                            hv = host_data.get(k, "")
                            ent.delete(0, tk.END)
                            ent.insert(0, str(hv))
                            ent.config(foreground="green")
                            left_labels[k].config(foreground="green")

                        ttk.Button(fields_frame, text="Use Host", width=10, command=_use_host).grid(row=i, column=3, padx=4, pady=2)

                    client_widgets.setdefault(idx, {})[key] = (entry, data)

                current_client_label.config(foreground="red" if any_mismatch else "green")

            # load client datas and create radio buttons
            for col, cname in enumerate(client_names):
                cpath = self.base_dir / cname
                try:
                    with cpath.open("r", encoding="utf-8") as f:
                        cdata = json.load(f)
                except Exception as exc:
                    self._show_message("error", "Load error", f"Could not read client file {cname}:\n{exc}", parent=win)
                    continue

                client_paths[col] = cpath
                client_datas[col] = cdata
                client_names_by_index[col] = cname
                ttk.Radiobutton(rad_inner, text=str(col + 1), variable=selected_client, value=col, command=lambda i=col: show_client(i)).pack(side="left", padx=4)

                # color host mismatches when loading
                for key in compare_keys:
                    hval = host_data.get(key, "<MISSING>")
                    cval = cdata.get(key, "<MISSING>")
                    if key in ("mapseed", "dungeon_lvl", "level_track"):
                        mismatch = (hval != cval)
                    elif key == "multiplayer_type":
                        mismatch = not (hval == 1 and cval == 2)
                    elif key == "player_num":
                        mismatch = not (hval == 0 and isinstance(cval, int) and cval > 0)
                    elif key == "players_connected":
                        mismatch = (hval != cval)
                    else:
                        mismatch = False
                    if mismatch:
                        left_labels[key].config(foreground="red")
                    else:
                        left_labels[key].config(foreground="green")

            # show first client if present and ensure its radio is selected
            if client_datas:
                win._selected_client.set(0)
                show_client(0)

            def apply_updates():
                if not messagebox.askyesno('Confirm updates', 'Apply updates to selected client file(s)? Backups will be created automatically.', parent=win):
                    return
                # iterate through clients and write updates
                for col, mapping in client_widgets.items():
                    cpath = client_paths.get(col)
                    if not cpath:
                        continue
                    _, sample_cdata = next(iter(mapping.values()))
                    # create backup
                    try:
                        backups_dir = self.base_dir / 'backups'
                        backups_dir.mkdir(exist_ok=True)
                        ts = int(time.time())
                        backup_name = f"{cpath.name}.bak.{ts}"
                        shutil.copy2(cpath, backups_dir / backup_name)
                        try:
                            self._prune_backups(backups_dir, cpath.name)
                        except Exception:
                            pass
                    except Exception:
                        pass

                    # apply changes into cdata
                    for key, (entry, cdata) in mapping.items():
                        raw = entry.get().strip()
                        orig = cdata.get(key)
                        try:
                            if isinstance(orig, list):
                                new_value = json.loads(raw) if raw else []
                            elif isinstance(orig, bool):
                                new_value = raw.lower() in ('1', 'true', 'yes')
                            elif isinstance(orig, int):
                                new_value = int(raw)
                            elif isinstance(orig, float):
                                new_value = float(raw)
                            elif orig is None:
                                if raw.lower() in ('null', 'none', ''):
                                    new_value = None
                                else:
                                    try:
                                        new_value = json.loads(raw)
                                    except Exception:
                                        new_value = raw
                            else:
                                new_value = raw
                        except Exception as exc:
                            self._show_message('error', 'Invalid value', f'Could not convert value for {key} in {cpath.name}: {exc}', parent=win)
                            return

                        cdata[key] = new_value

                    # write back file
                    try:
                        with cpath.open('w', encoding='utf-8') as f:
                            json.dump(cdata, f, indent=2, ensure_ascii=False)
                    except Exception as exc:
                        self._show_message('error', 'Save failed', f'Could not save {cpath.name}:\n{exc}', parent=win)
                        return

                self._show_message('info', 'Updated', 'Selected client files updated successfully.', parent=win)

            # place Apply Updates into the selector button area so it's visible
            ttk.Button(selector_button_frame, text='Apply Updates', command=apply_updates).pack(side="top", pady=4)

        # Compare button in the top selector area
        ttk.Button(selector_button_frame, text="Compare", command=do_compare).pack(side="top", pady=4)

    def _build_fields(self, current, container, prefix=""):
        if isinstance(current, dict):
            for key, value in current.items():
                label_text = f"{prefix}.{key}" if prefix else key
                self._build_fields(value, container, label_text)
        elif isinstance(current, list):
            for idx, value in enumerate(current):
                label_text = f"{prefix}[{idx}]"
                self._build_fields(value, container, label_text)
        else:
            self._build_field_row(container, prefix, current)

    def _build_field_row(self, container, path, value, target_store=None, tooltip=None):
        if target_store is None:
            target_store = self.fields

        row = ttk.Frame(container)
        row.pack(fill="x", pady=2)

        label = ttk.Label(row, text=path)
        label.pack(side="left", padx=(0, 6), anchor="w")

        info_label = None
        if tooltip:
            info_label = ttk.Label(row, text="ⓘ", foreground="blue")
            info_label.pack(side="left", padx=(0, 8))
            ToolTip(info_label, tooltip)

        if isinstance(value, bool):
            var = tk.BooleanVar(value=value)
            widget = ttk.Checkbutton(row, variable=var)
            widget.pack(side="left", anchor="w")
            target_store[path] = var
            self.type_map[path] = bool
        else:
            widget = ttk.Entry(row, width=60)
            widget.insert(0, json.dumps(value) if value is None else str(value))
            widget.pack(side="left", fill="x", expand=True)
            target_store[path] = widget
            self.type_map[path] = type(value)


    def save_changes(self):
        if self.json_data is None or self.current_file is None:
            self._show_message("warning", "No data", "There is no JSON file loaded to save.", parent=self)
            return

        # create backup before saving
        try:
            backups_dir = self.base_dir / "backups"
            backups_dir.mkdir(exist_ok=True)
            ts = int(time.time())
            backup_name = f"{self.current_file.name}.bak.{ts}"
            shutil.copy2(self.current_file, backups_dir / backup_name)
            # prune old backups according to settings
            try:
                self._prune_backups(backups_dir, self.current_file.name)
            except Exception:
                pass
        except Exception:
            # non-fatal
            pass

        updated = json.loads(json.dumps(self.json_data))
        editable_items = {**self.metadata_fields, **self.player_fields}
        for path, widget in editable_items.items():
            path_tokens = parse_path(path)
            target_type = self.type_map[path]
            try:
                if target_type is bool:
                    new_value = widget.get()
                else:
                    raw_text = widget.get().strip()
                    if raw_text == "" and target_type is str:
                        new_value = ""
                    elif raw_text.lower() in {"null", "none"}:
                        new_value = None
                    elif target_type is int:
                        new_value = int(raw_text)
                    elif target_type is float:
                        new_value = float(raw_text)
                    elif target_type is str:
                        new_value = raw_text
                    else:
                        new_value = json.loads(raw_text)
            except Exception as exc:
                self._show_message("error", "Invalid value", f"Could not convert value for {path}: {exc}", parent=self)
                return

            nested_set(updated, path_tokens, new_value)

        try:
            with self.current_file.open("w", encoding="utf-8") as f:
                json.dump(updated, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            self._show_message("error", "Save failed", f"Could not save JSON file:\n{exc}", parent=self)
            return

        self.json_data = updated
        self._show_message("info", "Saved", f"Saved changes to {self.current_file.name}", parent=self)

    def restore_backup(self):
        # open a single window listing saves that actually have backups
        if not hasattr(self, "base_dir"):
            self._show_message("info", "No folder", "Select a save folder first.", parent=self)
            return
        backups_dir = self.base_dir / "backups"
        if not backups_dir.exists():
            self._show_message("info", "No backups", "No backups directory found.", parent=self)
            return

        # find saves in base_dir that have backups
        saves_with_backups = []
        for p in sorted(self.base_dir.glob(f"*{BARONY_SAVE_EXT}")):
            pattern = f"{p.name}.bak.*"
            if any(backups_dir.glob(pattern)):
                saves_with_backups.append(p.name)

        if not saves_with_backups:
            self._show_message("info", "No backups", "No backups found for any saves in the selected folder.", parent=win)
            return

        win = tk.Toplevel(self)
        win.title("Restore Backup")
        win.geometry("900x420")
        win.resizable(False, False)

        left = ttk.Frame(win, padding=8)
        left.pack(side="left", fill="y")
        right = ttk.Frame(win, padding=8)
        right.pack(side="left", fill="both", expand=True)

        ttk.Label(left, text="Saves With Backups", font=(None, 11, "bold")).pack(anchor="w")
        saves_list = tk.Listbox(left, width=40, height=20, exportselection=False)
        bind_mousewheel(saves_list)
        saves_list.pack(fill="y", expand=True)
        for name in saves_with_backups:
            saves_list.insert(tk.END, name)

        ttk.Label(right, text="Backups", font=(None, 11, "bold")).pack(anchor="w")
        backups_list = tk.Listbox(right, width=60, height=12, exportselection=False)
        bind_mousewheel(backups_list)
        backups_list.pack(fill="x")

        # quick restore button directly under backups list for visibility
        quick_btns = ttk.Frame(right)
        quick_btns.pack(fill='x', pady=(4,6))
        ttk.Button(quick_btns, text='Restore Selected Backup', command=lambda: do_restore() if 'do_restore' in globals() or True else None).pack(side='left')

        details_title = ttk.Label(right, text="Backup details", font=(None, 11, "bold"))
        details_title.pack(anchor="w", pady=(6,0))
        details = tk.Text(right, height=10)
        bind_mousewheel(details)
        details.pack(fill="both", expand=True)

        # storage for current backup paths
        backup_paths = []
        selected_target = None

        def load_backups_for_selected_save(evt=None):
            nonlocal backup_paths, selected_target
            sel = saves_list.curselection()
            backups_list.delete(0, tk.END)
            details.delete('1.0', tk.END)
            backup_paths = []
            if not sel:
                return
            selected_idx = sel[0]
            target_name = saves_list.get(selected_idx)
            selected_target = self.base_dir / target_name
            # collect backups for this save
            bs = sorted(backups_dir.glob(f"{target_name}.bak.*"), key=lambda p: p.stat().st_mtime, reverse=True)
            for b in bs:
                parts = b.name.split('.bak.')
                ts_text = parts[1] if len(parts) > 1 else ''
                try:
                    ts = int(ts_text)
                    timestr = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
                except Exception:
                    timestr = ''
                backups_list.insert(tk.END, f"{timestr}   {b.name}")
                backup_paths.append(b)

        def show_backup_details(evt=None):
            sel = backups_list.curselection()
            details.delete('1.0', tk.END)
            if not sel:
                return
            bp = backup_paths[sel[0]]
            try:
                with bp.open('r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as exc:
                details.insert(tk.END, f"Could not read backup: {exc}")
                return

            info_lines = []
            info_lines.append(f"File: {bp.name}")
            info_lines.append("")
            pc = data.get('players_connected')
            if pc is not None:
                info_lines.append(f"players_connected: {pc}")
            players = data.get('players', [])
            info_lines.append(f"players ({len(players)}):")
            for i, p in enumerate(players):
                pname = p.get('stats', {}).get('name', '')
                info_lines.append(f"  [{i}] {pname}")

            details.insert(tk.END, '\n'.join(info_lines))

        saves_list.bind('<<ListboxSelect>>', load_backups_for_selected_save)
        backups_list.bind('<<ListboxSelect>>', show_backup_details)

        def do_restore():
            sel = backups_list.curselection()
            if not sel:
                self._show_message('warning', 'No selection', 'Select a backup to restore.', parent=win)
                return
            if selected_target is None:
                self._show_message('error', 'No target', 'No target save selected.', parent=win)
                return
            bp = backup_paths[sel[0]]
            if not messagebox.askyesno('Confirm restore', f'Restore {bp.name} to {selected_target.name}? This will overwrite the target file.'):
                return
            try:
                shutil.copy2(bp, selected_target)
                self._show_message('info', 'Restored', f'Restored {bp.name} to {selected_target.name}', parent=win)
                win.destroy()
            except Exception as exc:
                self._show_message('error', 'Restore failed', f'Could not restore backup:\n{exc}', parent=win)

        btn_frame = ttk.Frame(right)
        btn_frame.pack(fill='x', pady=(6,0))
        ttk.Button(btn_frame, text='Restore Selected Backup', command=do_restore).pack(side='left')
        ttk.Button(btn_frame, text='Close', command=win.destroy).pack(side='right')

    def open_settings_window(self):
        win = tk.Toplevel(self)
        win.title('Settings')
        win.geometry('400x220')
        win.resizable(False, False)

        frame = ttk.Frame(win, padding=10)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text='Backup rotation (per-save)').grid(row=0, column=0, sticky='w', pady=6)
        max_backups_var = tk.IntVar(value=self.backup_max_per_save)
        ttk.Spinbox(frame, from_=0, to=9999, textvariable=max_backups_var, width=8).grid(row=0, column=1, sticky='w')
        ttk.Label(frame, text='(0 = unlimited)').grid(row=0, column=2, sticky='w')

        ttk.Label(frame, text='Max backup age (days)').grid(row=1, column=0, sticky='w', pady=6)
        max_age_var = tk.IntVar(value=self.backup_max_age_days)
        ttk.Spinbox(frame, from_=0, to=3650, textvariable=max_age_var, width=8).grid(row=1, column=1, sticky='w')
        ttk.Label(frame, text='(0 = unlimited)').grid(row=1, column=2, sticky='w')

        def apply_settings():
            try:
                self.backup_max_per_save = int(max_backups_var.get())
                self.backup_max_age_days = int(max_age_var.get())
            except Exception:
                self._show_message('error', 'Invalid', 'Please enter valid integer values.', parent=win)
                return
            self._save_config()
            self._show_message('info', 'Saved', 'Settings saved.', parent=win)
            win.destroy()

        btns = ttk.Frame(frame)
        btns.grid(row=10, column=0, columnspan=3, pady=14)
        ttk.Button(btns, text='Apply', command=apply_settings).pack(side='left', padx=6)
        ttk.Button(btns, text='Cancel', command=win.destroy).pack(side='left', padx=6)

    def _prune_backups(self, backups_dir: Path, target_name: str):
        # Remove backups older than max age or exceeding max per save.
        # If backup_max_per_save <= 0, do not enforce count limit. If backup_max_age_days <= 0, do not enforce age.
        pattern = f"{target_name}.bak.*"
        files = sorted(backups_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

        now = time.time()
        keep = []
        for i, f in enumerate(files):
            remove = False
            if self.backup_max_age_days and self.backup_max_age_days > 0:
                age_sec = now - f.stat().st_mtime
                if age_sec > (self.backup_max_age_days * 86400):
                    remove = True
            if not remove and self.backup_max_per_save and self.backup_max_per_save > 0:
                if i >= self.backup_max_per_save:
                    remove = True
            if remove:
                try:
                    f.unlink()
                except Exception:
                    pass
            else:
                keep.append(f)


if __name__ == "__main__":
    app = JsonEditorApp()
    app.mainloop()
