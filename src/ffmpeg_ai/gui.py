"""Retro Linux desktop launcher for ffmpeg-ai."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path
import os
import queue
import shlex
import shutil
import subprocess
import sys
import threading
from typing import Literal

from dotenv import load_dotenv

from .ai.openrouter import FREE_MODELS, STYLE_PRESETS
from .ai.tts import VOICES
from .video.shorts import MODES

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

ActionKind = Literal[
    "generate",
    "batch",
    "auto",
    "channel",
    "models",
    "voices",
    "providers",
    "youtube-setup",
    "channel-init",
    "channel-list",
    "channel-status",
    "channel-validate",
    "channel-setup-yt",
]


@dataclass(slots=True)
class JobSpec:
    kind: ActionKind
    topic: str = ""
    topics_file: str = ""
    output_path: str = ""
    output_dir: str = ""
    mode: str = "shorts"
    duration: int = 45
    model: str = FREE_MODELS[0]
    voice: str = "en-female"
    style: str = ""
    caption_style: str = "karaoke"
    render_mode: str = ""
    brand_name: str = ""
    accent_color: str = "#c084ff"
    images_dir: str = ""
    music_path: str = ""
    script_path: str = ""
    count: int = 3
    privacy: str = "public"
    upload: str = "auto"
    shorts: bool = True
    landscape: bool = True
    dry_run: bool = False
    edit_script: bool = False
    fresh: bool = False
    no_thumbnail: bool = False
    no_ambience: bool = False
    no_captions: bool = False
    no_hook: bool = False
    font_path: str = ""
    no_ai_images: bool = False
    channel_name: str = ""
    lines: int = 5
def build_command(spec: JobSpec) -> list[str]:
    """Build the CLI command for a GUI action."""
    base = [sys.executable, "-m", "ffmpeg_ai"]

    if spec.kind == "generate":
        if not spec.topic.strip():
            raise ValueError("topic is required")
        cmd = base + ["generate", spec.topic.strip()]
        if spec.mode:
            cmd += ["--mode", spec.mode]
        if spec.output_path:
            cmd += ["--output", spec.output_path]
        if spec.duration:
            cmd += ["--duration", str(spec.duration)]
        if spec.model:
            cmd += ["--model", spec.model]
        if spec.voice:
            cmd += ["--voice", spec.voice]
        if spec.style:
            cmd += ["--style", spec.style]
        if spec.caption_style:
            cmd += ["--caption-style", spec.caption_style]
        if spec.render_mode:
            cmd += ["--render-mode", spec.render_mode]
        if spec.brand_name:
            cmd += ["--brand-name", spec.brand_name]
        if spec.accent_color:
            cmd += ["--accent-color", spec.accent_color]
        if spec.images_dir:
            cmd += ["--images-dir", spec.images_dir]
        if spec.music_path:
            cmd += ["--music", spec.music_path]
        if spec.script_path:
            cmd += ["--script", spec.script_path]
        if spec.dry_run:
            cmd.append("--dry-run")
        if spec.edit_script:
            cmd.append("--edit-script")
        if spec.fresh:
            cmd.append("--fresh")
        if spec.no_thumbnail:
            cmd.append("--no-thumbnail")
        if spec.no_ambience:
            cmd.append("--no-ambience")
        if spec.no_captions:
            cmd.append("--no-captions")
        if spec.no_ai_images:
            cmd.append("--no-ai-images")
        if spec.no_hook:
            cmd.append("--no-hook")
        if spec.font_path:
            cmd += ["--font", spec.font_path]
        cmd.append("--quiet")
        return cmd

    if spec.kind == "batch":
        if not spec.topics_file.strip():
            raise ValueError("topics file is required")
        cmd = base + ["batch", spec.topics_file.strip()]
        if spec.output_dir:
            cmd += ["--output-dir", spec.output_dir]
        if spec.mode:
            cmd += ["--mode", spec.mode]
        if spec.duration:
            cmd += ["--duration", str(spec.duration)]
        if spec.model:
            cmd += ["--model", spec.model]
        if spec.voice:
            cmd += ["--voice", spec.voice]
        if spec.style:
            cmd += ["--style", spec.style]
        if spec.caption_style:
            cmd += ["--caption-style", spec.caption_style]
        if spec.render_mode:
            cmd += ["--render-mode", spec.render_mode]
        if spec.brand_name:
            cmd += ["--brand-name", spec.brand_name]
        if spec.accent_color:
            cmd += ["--accent-color", spec.accent_color]
        if spec.fresh:
            cmd.append("--fresh")
        if spec.no_thumbnail:
            cmd.append("--no-thumbnail")
        if spec.no_ambience:
            cmd.append("--no-ambience")
        if spec.no_hook:
            cmd.append("--no-hook")
        if spec.font_path:
            cmd += ["--font", spec.font_path]
        cmd.append("--quiet")
        return cmd

    if spec.kind == "auto":
        cmd = base + ["auto", "--count", str(max(1, spec.count))]
        if spec.upload == "on":
            cmd.append("--upload")
        if spec.privacy:
            cmd += ["--privacy", spec.privacy]
        if spec.style:
            cmd += ["--style", spec.style]
        if spec.voice:
            cmd += ["--voice", spec.voice]
        if spec.brand_name:
            cmd += ["--brand-name", spec.brand_name]
        if spec.accent_color:
            cmd += ["--accent-color", spec.accent_color]
        if spec.dry_run:
            cmd.append("--dry-run")
        cmd.append("--quiet")
        return cmd

    if spec.kind == "channel":
        cmd = base + ["channel", "run"]
        if spec.channel_name.strip():
            cmd.append(spec.channel_name.strip())
        if not spec.shorts:
            cmd.append("--no-shorts")
        if not spec.landscape:
            cmd.append("--no-landscape")
        if spec.upload == "on":
            cmd.append("--upload")
        if spec.upload == "off":
            cmd.append("--no-upload")
        if spec.count:
            cmd += ["--count", str(max(1, spec.count))]
        if spec.model:
            cmd += ["--model", spec.model]
        if spec.dry_run:
            cmd.append("--dry-run")
        cmd.append("--quiet")
        return cmd

    if spec.kind == "models":
        return base + ["models"]
    if spec.kind == "voices":
        return base + ["voices"]
    if spec.kind == "providers":
        return base + ["providers"]
    if spec.kind == "youtube-setup":
        return base + ["youtube-setup"]
    if spec.kind == "channel-init":
        return base + ["channel", "init-presets"]
    if spec.kind == "channel-list":
        return base + ["channel", "list"]
    if spec.kind == "channel-status":
        cmd = base + ["channel", "status"]
        if spec.channel_name.strip():
            cmd.append(spec.channel_name.strip())
        if spec.lines:
            cmd += ["--lines", str(max(1, spec.lines))]
        return cmd
    if spec.kind == "channel-validate":
        cmd = base + ["channel", "validate"]
        if spec.channel_name.strip():
            cmd.append(spec.channel_name.strip())
        return cmd
    if spec.kind == "channel-setup-yt":
        cmd = base + ["channel", "setup-yt"]
        if spec.channel_name.strip():
            cmd.append(spec.channel_name.strip())
        return cmd
    raise ValueError(f"unsupported action: {spec.kind}")


def _pick_default_output() -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(Path.home() / "Videos" / "ffmpeg-ai" / f"{ts}.mp4")


def _pick_default_output_dir() -> str:
    return str(Path.home() / "Videos" / "ffmpeg-ai")


class RetroApp:
    """Tkinter operator panel for ffmpeg-ai."""

    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext, ttk

        self.tk = tk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.scrolledtext = scrolledtext
        self.ttk = ttk
        self.root = tk.Tk()
        self.root.title("ffmpeg-ai operator node")
        self.root.geometry("640x780")
        self.root.minsize(620, 720)
        self.root.configure(bg="#050707")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self._proc: subprocess.Popen[str] | None = None
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._poll_id: str | None = None

        self._theme = {
            "bg": "#050707",
            "panel": "#0b0f0d",
            "panel2": "#101614",
            "fg": "#d6ffe0",
            "muted": "#83a08a",
            "accent": "#86f7c9",
            "accent2": "#ffb26b",
            "warn": "#ff6a6a",
            "line": "#1d3327",
        }
        self._mono = self._choose_mono_font()

        self.topic_var = tk.StringVar(value="how to automate a youtube channel")
        self.output_var = tk.StringVar(value=_pick_default_output())
        self.mode_var = tk.StringVar(value="shorts")
        self.duration_var = tk.IntVar(value=45)
        self.model_var = tk.StringVar(value=FREE_MODELS[0])
        self.voice_var = tk.StringVar(value="en-female")
        self.style_var = tk.StringVar(value="")
        self.caption_var = tk.StringVar(value="karaoke")
        self.brand_var = tk.StringVar(value="ffmpeg-ai")
        self.accent_var = tk.StringVar(value="#c084ff")
        self.images_var = tk.StringVar(value="")
        self.music_var = tk.StringVar(value="")
        self.script_var = tk.StringVar(value="")
        self.batch_topics_var = tk.StringVar(value="")
        self.batch_output_var = tk.StringVar(value=_pick_default_output_dir())
        self.auto_count_var = tk.IntVar(value=3)
        self.auto_privacy_var = tk.StringVar(value="public")
        self.auto_upload_var = tk.StringVar(value="auto")
        self.channel_name_var = tk.StringVar(value="")
        self.channel_count_var = tk.IntVar(value=1)
        self.channel_model_var = tk.StringVar(value=FREE_MODELS[0])
        self.channel_upload_var = tk.StringVar(value="auto")
        self.channel_shorts_var = tk.BooleanVar(value=True)
        self.channel_landscape_var = tk.BooleanVar(value=True)
        self.lines_var = tk.IntVar(value=5)
        self.dry_run_var = tk.BooleanVar(value=False)
        self.edit_script_var = tk.BooleanVar(value=False)
        self.fresh_var = tk.BooleanVar(value=False)
        self.no_thumbnail_var = tk.BooleanVar(value=False)
        self.no_ambience_var = tk.BooleanVar(value=False)
        self.no_captions_var = tk.BooleanVar(value=False)
        self.no_ai_images_var = tk.BooleanVar(value=False)

        self._build_ui()
        self._update_status()

    def _choose_mono_font(self) -> tuple[str, int]:
        import tkinter.font as tkfont

        preferred = [
            "Terminus",
            "DejaVu Sans Mono",
            "Liberation Mono",
            "Noto Sans Mono",
            "Courier New",
        ]
        families = set(tkfont.families(self.root))
        for family in preferred:
            if family in families:
                return (family, 10)
        return ("TkFixedFont", 10)

    def _build_ui(self) -> None:
        tk = self.tk
        ttk = self.ttk
        colors = self._theme
        root = self.root

        root.grid_rowconfigure(3, weight=1)
        root.grid_columnconfigure(0, weight=1)

        header = tk.Frame(root, bg=colors["bg"], highlightbackground=colors["line"], highlightthickness=1)
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        header.grid_columnconfigure(0, weight=1)
        tk.Label(
            header,
            text="ffmpeg-ai operator node",
            bg=colors["bg"],
            fg=colors["accent"],
            font=(self._mono[0], 13, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
        tk.Label(
            header,
            text="retro terminal control panel for generate / batch / auto / channel",
            bg=colors["bg"],
            fg=colors["muted"],
            font=self._mono,
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        self.status_line = tk.Label(
            header,
            text="",
            bg=colors["bg"],
            fg=colors["accent2"],
            font=self._mono,
            anchor="w",
        )
        self.status_line.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))

        container = tk.Frame(root, bg=colors["bg"])
        container.grid(row=1, column=0, sticky="nsew", padx=10)
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Retro.TNotebook", background=colors["bg"], borderwidth=0)
        style.configure("Retro.TNotebook.Tab", padding=(10, 5), background=colors["panel2"], foreground=colors["fg"])
        style.map("Retro.TNotebook.Tab", background=[("selected", colors["panel"])], foreground=[("selected", colors["accent"])])

        notebook = ttk.Notebook(container, style="Retro.TNotebook")
        notebook.grid(row=0, column=0, sticky="nsew")

        self._build_generate_tab(notebook)
        self._build_batch_tab(notebook)
        self._build_auto_tab(notebook)
        self._build_channel_tab(notebook)
        self._build_tools_tab(notebook)

        footer = tk.Frame(root, bg=colors["bg"], highlightbackground=colors["line"], highlightthickness=1)
        footer.grid(row=2, column=0, sticky="ew", padx=10, pady=6)
        footer.grid_columnconfigure(0, weight=1)
        self.command_line = tk.Label(
            footer,
            text="idle",
            bg=colors["bg"],
            fg=colors["accent"],
            font=self._mono,
            anchor="w",
        )
        self.command_line.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 0))
        buttons = tk.Frame(footer, bg=colors["bg"])
        buttons.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 6))
        buttons.grid_columnconfigure((0, 1, 2), weight=1)
        self._button(buttons, "open output", self.open_output).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._button(buttons, "open .env", self.open_env).grid(row=0, column=1, sticky="ew", padx=4)
        self._button(buttons, "stop", self.stop, warn=True).grid(row=0, column=2, sticky="ew", padx=(4, 0))

        log_frame = tk.Frame(root, bg=colors["bg"], highlightbackground=colors["line"], highlightthickness=1)
        log_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        self.log = self.scrolledtext.ScrolledText(
            log_frame,
            height=14,
            bg=colors["panel"],
            fg=colors["fg"],
            insertbackground=colors["accent"],
            relief="flat",
            wrap="word",
            font=self._mono,
            borderwidth=0,
        )
        self.log.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.log.tag_configure("cmd", foreground=colors["accent"])
        self.log.tag_configure("warn", foreground=colors["accent2"])
        self.log.tag_configure("err", foreground=colors["warn"])
        self.log.tag_configure("dim", foreground=colors["muted"])
        self.log.configure(state="disabled")

        self._append_log("node online", tag="dim")

    def _panel(self, parent, title: str):
        tk = self.tk
        colors = self._theme
        frame = tk.Frame(parent, bg=colors["panel"], highlightbackground=colors["line"], highlightthickness=1)
        frame.grid_columnconfigure(1, weight=1)
        tk.Label(
            frame,
            text=title,
            bg=colors["panel"],
            fg=colors["accent"],
            font=(self._mono[0], 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, sticky="ew", padx=8, pady=(6, 4))
        return frame

    def _label(self, parent, row: int, text: str) -> None:
        self.tk.Label(
            parent,
            text=text,
            bg=self._theme["panel"],
            fg=self._theme["muted"],
            font=self._mono,
            anchor="w",
        ).grid(row=row, column=0, sticky="w", padx=8, pady=2)

    def _entry(self, parent, row: int, var, browse: str = "", command=None, width: int = 34) -> None:
        tk = self.tk
        colors = self._theme
        entry = tk.Entry(
            parent,
            textvariable=var,
            bg=colors["bg"],
            fg=colors["fg"],
            insertbackground=colors["accent"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=colors["line"],
            highlightcolor=colors["accent"],
            font=self._mono,
            width=width,
        )
        entry.grid(row=row, column=1, sticky="ew", padx=8, pady=2)
        if browse and command:
            self._button(parent, browse, command).grid(row=row, column=2, sticky="ew", padx=(0, 8), pady=2)

    def _combo(self, parent, row: int, var, values: list[str], width: int = 18) -> None:
        combo = self.ttk.Combobox(parent, textvariable=var, values=values, width=width, state="readonly")
        combo.grid(row=row, column=1, sticky="ew", padx=8, pady=2)

    def _spin(self, parent, row: int, var, frm: int, to: int, width: int = 8) -> None:
        spin = self.tk.Spinbox(
            parent,
            textvariable=var,
            from_=frm,
            to=to,
            bg=self._theme["bg"],
            fg=self._theme["fg"],
            insertbackground=self._theme["accent"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=self._theme["line"],
            highlightcolor=self._theme["accent"],
            font=self._mono,
            width=width,
            buttonbackground=self._theme["panel2"],
        )
        spin.grid(row=row, column=1, sticky="w", padx=8, pady=2)

    def _check(self, parent, row: int, text: str, var) -> None:
        cb = self.tk.Checkbutton(
            parent,
            text=text,
            variable=var,
            bg=self._theme["panel"],
            fg=self._theme["fg"],
            activebackground=self._theme["panel"],
            activeforeground=self._theme["accent"],
            selectcolor=self._theme["bg"],
            font=self._mono,
        )
        cb.grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=2)

    def _button(self, parent, text: str, command, warn: bool = False):
        return self.tk.Button(
            parent,
            text=text,
            command=command,
            bg=self._theme["accent2"] if warn else self._theme["panel2"],
            fg="#060707",
            activebackground=self._theme["accent"] if not warn else "#ffcf8a",
            activeforeground="#060707",
            relief="flat",
            borderwidth=0,
            font=(self._mono[0], 9, "bold"),
            cursor="hand2",
        )

    def _build_generate_tab(self, notebook) -> None:
        frame = self.tk.Frame(notebook, bg=self._theme["bg"])
        frame.grid_columnconfigure(0, weight=1)
        panel = self._panel(frame, "generate")
        panel.pack(fill="both", expand=True)
        self._label(panel, 1, "topic")
        self._entry(panel, 1, self.topic_var, browse="paste", command=self.paste_topic)
        self._label(panel, 2, "output")
        self._entry(panel, 2, self.output_var, browse="file", command=self.pick_output)
        self._label(panel, 3, "mode")
        self._combo(panel, 3, self.mode_var, list(MODES))
        self._label(panel, 4, "duration")
        self._spin(panel, 4, self.duration_var, 10, 600)
        self._label(panel, 5, "model")
        self._combo(panel, 5, self.model_var, FREE_MODELS, width=32)
        self._label(panel, 6, "voice")
        self._combo(panel, 6, self.voice_var, list(VOICES))
        self._label(panel, 7, "style")
        self._combo(panel, 7, self.style_var, [""] + sorted(STYLE_PRESETS))
        self._label(panel, 8, "captions")
        self._combo(panel, 8, self.caption_var, ["karaoke", "plain", "bold-center"])
        self._label(panel, 9, "brand")
        self._entry(panel, 9, self.brand_var)
        self._label(panel, 10, "accent")
        self._entry(panel, 10, self.accent_var)
        self._label(panel, 11, "images")
        self._entry(panel, 11, self.images_var, browse="dir", command=self.pick_images)
        self._label(panel, 12, "music")
        self._entry(panel, 12, self.music_var, browse="file", command=self.pick_music)
        self._label(panel, 13, "script")
        self._entry(panel, 13, self.script_var, browse="file", command=self.pick_script)
        self._check(panel, 14, "dry run", self.dry_run_var)
        self._check(panel, 15, "edit script", self.edit_script_var)
        self._check(panel, 16, "fresh", self.fresh_var)
        self._check(panel, 17, "no thumbnail", self.no_thumbnail_var)
        self._check(panel, 18, "no ambience", self.no_ambience_var)
        self._check(panel, 19, "no captions", self.no_captions_var)
        self._check(panel, 20, "no ai images", self.no_ai_images_var)
        self._button_row(panel, 21, [("generate", self.run_generate), ("open output", self.open_output)])
        notebook.add(frame, text="generate")

    def _build_batch_tab(self, notebook) -> None:
        frame = self.tk.Frame(notebook, bg=self._theme["bg"])
        panel = self._panel(frame, "batch")
        panel.pack(fill="both", expand=True)
        self._label(panel, 1, "topics file")
        self._entry(panel, 1, self.batch_topics_var, browse="file", command=self.pick_topics_file)
        self._label(panel, 2, "output dir")
        self._entry(panel, 2, self.batch_output_var, browse="dir", command=self.pick_batch_output)
        self._label(panel, 3, "mode")
        self._combo(panel, 3, self.mode_var, list(MODES))
        self._label(panel, 4, "duration")
        self._spin(panel, 4, self.duration_var, 10, 600)
        self._label(panel, 5, "model")
        self._combo(panel, 5, self.model_var, FREE_MODELS, width=32)
        self._label(panel, 6, "voice")
        self._combo(panel, 6, self.voice_var, list(VOICES))
        self._label(panel, 7, "style")
        self._combo(panel, 7, self.style_var, [""] + sorted(STYLE_PRESETS))
        self._label(panel, 8, "captions")
        self._combo(panel, 8, self.caption_var, ["karaoke", "plain", "bold-center"])
        self._check(panel, 9, "fresh", self.fresh_var)
        self._check(panel, 10, "no thumbnail", self.no_thumbnail_var)
        self._check(panel, 11, "no ambience", self.no_ambience_var)
        self._button_row(panel, 12, [("batch", self.run_batch)])
        notebook.add(frame, text="batch")

    def _build_auto_tab(self, notebook) -> None:
        frame = self.tk.Frame(notebook, bg=self._theme["bg"])
        panel = self._panel(frame, "auto")
        panel.pack(fill="both", expand=True)
        self._label(panel, 1, "count")
        self._spin(panel, 1, self.auto_count_var, 1, 20)
        self._label(panel, 2, "privacy")
        self._combo(panel, 2, self.auto_privacy_var, ["public", "unlisted", "private"])
        self._label(panel, 3, "upload")
        self._combo(panel, 3, self.auto_upload_var, ["auto", "on", "off"])
        self._label(panel, 4, "style")
        self._combo(panel, 4, self.style_var, [""] + sorted(STYLE_PRESETS))
        self._label(panel, 5, "voice")
        self._combo(panel, 5, self.voice_var, list(VOICES))
        self._label(panel, 6, "brand")
        self._entry(panel, 6, self.brand_var)
        self._label(panel, 7, "accent")
        self._entry(panel, 7, self.accent_var)
        self._check(panel, 8, "dry run", self.dry_run_var)
        self._button_row(panel, 9, [("auto", self.run_auto), ("youtube setup", self.run_youtube_setup)])
        notebook.add(frame, text="auto")

    def _build_channel_tab(self, notebook) -> None:
        frame = self.tk.Frame(notebook, bg=self._theme["bg"])
        panel = self._panel(frame, "channel")
        panel.pack(fill="both", expand=True)
        self._label(panel, 1, "name")
        self._entry(panel, 1, self.channel_name_var)
        self._label(panel, 2, "count")
        self._spin(panel, 2, self.channel_count_var, 1, 10)
        self._label(panel, 3, "model")
        self._combo(panel, 3, self.channel_model_var, FREE_MODELS, width=32)
        self._label(panel, 4, "upload")
        self._combo(panel, 4, self.channel_upload_var, ["auto", "on", "off"])
        self._check(panel, 5, "shorts", self.channel_shorts_var)
        self._check(panel, 6, "landscape", self.channel_landscape_var)
        self._check(panel, 7, "dry run", self.dry_run_var)
        self._label(panel, 8, "lines")
        self._spin(panel, 8, self.lines_var, 1, 20)
        self._button_row(panel, 9, [
            ("run", self.run_channel),
            ("setup yt", lambda: self.run_tool("channel-setup-yt")),
            ("list", lambda: self.run_tool("channel-list")),
            ("init", lambda: self.run_tool("channel-init")),
            ("status", lambda: self.run_tool("channel-status")),
            ("validate", lambda: self.run_tool("channel-validate")),
        ])
        notebook.add(frame, text="channel")

    def _build_tools_tab(self, notebook) -> None:
        frame = self.tk.Frame(notebook, bg=self._theme["bg"])
        panel = self._panel(frame, "tools")
        panel.pack(fill="both", expand=True)
        self._button_row(panel, 1, [
            ("models", lambda: self.run_tool("models")),
            ("voices", lambda: self.run_tool("voices")),
            ("providers", lambda: self.run_tool("providers")),
        ])
        self._button_row(panel, 2, [("youtube setup", self.run_youtube_setup)])
        self._make_topmost_control(panel, 3)
        self._button_row(panel, 4, [("open cache", self.open_cache), ("open videos", self.open_output)])
        notebook.add(frame, text="tools")

    def _make_topmost_control(self, parent, row: int) -> None:
        var = self.tk.BooleanVar(value=False)

        def _apply() -> None:
            self.root.attributes("-topmost", bool(var.get()))

        cb = self.tk.Checkbutton(
            parent,
            text="keep on top",
            variable=var,
            command=_apply,
            bg=self._theme["panel"],
            fg=self._theme["fg"],
            activebackground=self._theme["panel"],
            activeforeground=self._theme["accent"],
            selectcolor=self._theme["bg"],
            font=self._mono,
        )
        cb.grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=2)

    def _button_row(self, parent, row: int, buttons: list[tuple[str, object]]) -> None:
        row_frame = self.tk.Frame(parent, bg=self._theme["panel"])
        row_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8, pady=(6, 8))
        for idx in range(len(buttons)):
            row_frame.grid_columnconfigure(idx, weight=1)
        for idx, (text, command) in enumerate(buttons):
            self._button(row_frame, text, command, warn=text in {"stop", "youtube setup"}).grid(
                row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 4, 0)
            )

    def _append_log(self, text: str, tag: str | None = None) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def _update_status(self) -> None:
        ffmpeg_ok = "ok" if shutil.which("ffmpeg") else "missing"
        key_ok = "set" if os.environ.get("OPENROUTER_API_KEY") else "unset"
        yt_ok = "set" if self._yt_token_path().exists() else "unset"
        self.status_line.configure(
            text=f"ffmpeg={ffmpeg_ok}  openrouter={key_ok}  youtube={yt_ok}",
        )

    def _yt_token_path(self) -> Path:
        try:
            return Path.home() / ".config" / "ffmpeg-ai" / "token.json"
        except Exception:
            return Path.home() / "token.json"

    def _runner(self, cmd: list[str]) -> None:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        self._append_log(f"$ {' '.join(shlex.quote(part) for part in cmd)}", tag="cmd")
        self.command_line.configure(text="running")
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert self._proc.stdout is not None

        def _pump() -> None:
            try:
                for line in self._proc.stdout:
                    self._queue.put(line)
            finally:
                self._queue.put(None)

        threading.Thread(target=_pump, daemon=True).start()
        self._poll_queue()

    def _poll_queue(self) -> None:
        try:
            while True:
                line = self._queue.get_nowait()
                if line is None:
                    self._finish_process()
                    return
                tag = "err" if "error" in line.lower() or "failed" in line.lower() else None
                self._append_log(line, tag=tag)
        except queue.Empty:
            pass
        if self._proc and self._proc.poll() is None:
            self._poll_id = self.root.after(80, self._poll_queue)
        else:
            self._finish_process()

    def _finish_process(self) -> None:
        if self._poll_id is not None:
            try:
                self.root.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        if self._proc is not None:
            code = self._proc.poll()
            if code is None:
                code = -1
            self.command_line.configure(text=f"exit {code}")
            self._append_log(f"[exit {code}]", tag="warn" if code else "dim")
        self._proc = None
        self._update_status()

    def _run(self, spec: JobSpec) -> None:
        try:
            cmd = build_command(spec)
        except ValueError as exc:
            self.messagebox.showerror("ffmpeg-ai", str(exc))
            return
        self._runner(cmd)

    def run_generate(self) -> None:
        self._run(JobSpec(
            kind="generate",
            topic=self.topic_var.get(),
            output_path=self.output_var.get(),
            mode=self.mode_var.get(),
            duration=self.duration_var.get(),
            model=self.model_var.get(),
            voice=self.voice_var.get(),
            style=self.style_var.get(),
            caption_style=self.caption_var.get(),
            render_mode="",
            brand_name=self.brand_var.get(),
            accent_color=self.accent_var.get(),
            images_dir=self.images_var.get(),
            music_path=self.music_var.get(),
            script_path=self.script_var.get(),
            dry_run=self.dry_run_var.get(),
            edit_script=self.edit_script_var.get(),
            fresh=self.fresh_var.get(),
            no_thumbnail=self.no_thumbnail_var.get(),
            no_ambience=self.no_ambience_var.get(),
            no_captions=self.no_captions_var.get(),
            no_ai_images=self.no_ai_images_var.get(),
        ))

    def run_batch(self) -> None:
        self._run(JobSpec(
            kind="batch",
            topics_file=self.batch_topics_var.get(),
            output_dir=self.batch_output_var.get(),
            mode=self.mode_var.get(),
            duration=self.duration_var.get(),
            model=self.model_var.get(),
            voice=self.voice_var.get(),
            style=self.style_var.get(),
            caption_style=self.caption_var.get(),
            render_mode="",
            fresh=self.fresh_var.get(),
            no_thumbnail=self.no_thumbnail_var.get(),
            no_ambience=self.no_ambience_var.get(),
        ))

    def run_auto(self) -> None:
        self._run(JobSpec(
            kind="auto",
            count=self.auto_count_var.get(),
            privacy=self.auto_privacy_var.get(),
            upload=self.auto_upload_var.get(),
            style=self.style_var.get(),
            voice=self.voice_var.get(),
            brand_name=self.brand_var.get(),
            accent_color=self.accent_var.get(),
            dry_run=self.dry_run_var.get(),
        ))

    def run_channel(self) -> None:
        self._run(JobSpec(
            kind="channel",
            channel_name=self.channel_name_var.get(),
            count=self.channel_count_var.get(),
            model=self.channel_model_var.get(),
            upload=self.channel_upload_var.get(),
            shorts=self.channel_shorts_var.get(),
            landscape=self.channel_landscape_var.get(),
            dry_run=self.dry_run_var.get(),
        ))

    def run_tool(self, kind: ActionKind) -> None:
        self._run(JobSpec(
            kind=kind,
            channel_name=self.channel_name_var.get(),
            lines=self.lines_var.get(),
        ))

    def run_youtube_setup(self) -> None:
        self._run(JobSpec(kind="youtube-setup"))

    def pick_output(self) -> None:
        path = self.filedialog.asksaveasfilename(
            parent=self.root,
            initialdir=str(Path(self.output_var.get()).expanduser().parent),
            initialfile=Path(self.output_var.get()).name,
            defaultextension=".mp4",
            filetypes=[("MP4 video", "*.mp4"), ("All files", "*.*")],
        )
        if path:
            self.output_var.set(path)

    def pick_batch_output(self) -> None:
        path = self.filedialog.askdirectory(parent=self.root, initialdir=self.batch_output_var.get())
        if path:
            self.batch_output_var.set(path)

    def pick_topics_file(self) -> None:
        path = self.filedialog.askopenfilename(
            parent=self.root,
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self.batch_topics_var.set(path)

    def pick_images(self) -> None:
        path = self.filedialog.askdirectory(parent=self.root)
        if path:
            self.images_var.set(path)

    def pick_music(self) -> None:
        path = self.filedialog.askopenfilename(
            parent=self.root,
            filetypes=[("Audio files", "*.mp3 *.wav *.m4a *.aac"), ("All files", "*.*")],
        )
        if path:
            self.music_var.set(path)

    def pick_script(self) -> None:
        path = self.filedialog.askopenfilename(
            parent=self.root,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.script_var.set(path)

    def open_output(self) -> None:
        self._open_path(Path(self.output_var.get()).expanduser().parent)

    def open_cache(self) -> None:
        self._open_path(Path.home() / ".cache" / "ffmpeg-ai")

    def open_env(self) -> None:
        self._open_path(PROJECT_ROOT / ".env")

    def paste_topic(self) -> None:
        try:
            text = self.root.clipboard_get().strip()
        except Exception:
            text = ""
        if text:
            self.topic_var.set(text)

    def _open_path(self, path: Path) -> None:
        if not path.exists():
            self.messagebox.showwarning("ffmpeg-ai", f"path not found: {path}")
            return
        opener = shutil.which("xdg-open") or shutil.which("gio")
        if opener is None:
            self.messagebox.showwarning("ffmpeg-ai", "no desktop opener found (xdg-open/gio)")
            return
        subprocess.Popen([opener, str(path)])

    def stop(self) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            self._append_log("no running job", tag="dim")
            return
        self._append_log("stopping current job...", tag="warn")
        proc.terminate()

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            if not self.messagebox.askyesno("ffmpeg-ai", "stop the running job and quit?"):
                return
            self._proc.terminate()
        self.root.destroy()


def main() -> None:
    try:
        app = RetroApp()
    except ModuleNotFoundError as exc:
        raise SystemExit(f"tkinter is required for the GUI: {exc}") from exc
    app.root.mainloop()
