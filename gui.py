"""mp4-comp GUI — モダンダークテーマ + 実行予約機能付き再実装。"""

import os
import queue
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

from compress import (
    DEFAULT_QUALITY_KEY,
    DEFAULT_TARGET_SIZE_MB,
    QUALITY_PROFILES,
    assess_video_quality,
    compress_video_to_quality,
    compress_video_to_size,
    convert_mov_to_mp4,
    describe_video,
    probe_video,
)


def _configure_tcl_environment() -> None:
    candidate_roots = [
        Path(sys.base_prefix) / "tcl",
        Path(sys.exec_prefix) / "tcl",
        Path(r"C:\Program Files\Git\mingw64\lib"),
    ]
    if not os.environ.get("TCL_LIBRARY"):
        for root in candidate_roots:
            tcl_dir = root / "tcl8.6"
            if (tcl_dir / "init.tcl").exists():
                os.environ["TCL_LIBRARY"] = str(tcl_dir)
                break
    if not os.environ.get("TK_LIBRARY"):
        for root in candidate_roots:
            tk_dir = root / "tk8.6"
            if (tk_dir / "tk.tcl").exists():
                os.environ["TK_LIBRARY"] = str(tk_dir)
                break


_configure_tcl_environment()

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

# ── デザイントークン ────────────────────────────────────────────────────────────
C = {
    "bg":          "#0f1117",
    "surface":     "#1a1b26",
    "surface2":    "#242538",
    "surface3":    "#2d2f4e",
    "accent":      "#7c6af7",
    "accent_dk":   "#6055c9",
    "success":     "#73d68e",
    "error":       "#f7768e",
    "warning":     "#ff9e64",
    "text":        "#c0caf5",
    "text_muted":  "#565f89",
    "border":      "#2f334d",
}

FONT      = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_SM   = ("Segoe UI", 9)
FONT_LG   = ("Segoe UI", 13, "bold")
FONT_MONO = ("Consolas", 9)
FONT_CD   = ("Segoe UI", 18, "bold")   # countdown


def _apply_dark_theme(root: tk.Tk) -> None:
    root.configure(bg=C["bg"])
    s = ttk.Style(root)
    if "clam" in s.theme_names():
        s.theme_use("clam")

    s.configure(".",
        background=C["bg"], foreground=C["text"],
        bordercolor=C["border"], darkcolor=C["surface"], lightcolor=C["surface"],
        troughcolor=C["surface2"], selectbackground=C["accent"],
        selectforeground="white", fieldbackground=C["surface2"], font=FONT,
    )
    s.configure("TFrame",     background=C["bg"])
    s.configure("Card.TFrame", background=C["surface"], relief="flat")

    s.configure("TLabel",         background=C["bg"],      foreground=C["text"])
    s.configure("Muted.TLabel",   background=C["bg"],      foreground=C["text_muted"])
    s.configure("Card.TLabel",    background=C["surface"], foreground=C["text"])
    s.configure("Card2.TLabel",   background=C["surface2"],foreground=C["text"])
    s.configure("Accent.TLabel",  background=C["bg"],      foreground=C["accent"],   font=FONT_BOLD)
    s.configure("Success.TLabel", background=C["bg"],      foreground=C["success"])
    s.configure("Error.TLabel",   background=C["bg"],      foreground=C["error"])
    s.configure("Large.TLabel",   background=C["bg"],      foreground=C["text"],     font=FONT_LG)
    s.configure("Card.Muted.TLabel", background=C["surface"], foreground=C["text_muted"])
    s.configure("CD.TLabel",      background=C["surface2"],foreground=C["warning"],  font=FONT_CD)

    s.configure("TLabelframe",       background=C["bg"],  bordercolor=C["border"])
    s.configure("TLabelframe.Label", background=C["bg"],  foreground=C["text_muted"], font=FONT_SM)
    s.configure("Card.TLabelframe",       background=C["surface"], bordercolor=C["border"])
    s.configure("Card.TLabelframe.Label", background=C["surface"], foreground=C["text_muted"], font=FONT_SM)

    s.configure("TEntry",
        fieldbackground=C["surface2"], foreground=C["text"],
        insertcolor=C["text"], bordercolor=C["border"],
        lightcolor=C["surface2"], darkcolor=C["surface2"],
    )
    s.map("TEntry", bordercolor=[("focus", C["accent"])])

    # Primary button
    s.configure("TButton",
        background=C["accent"], foreground="white",
        bordercolor=C["accent"], lightcolor=C["accent"], darkcolor=C["accent_dk"],
        relief="flat", padding=(18, 9), font=FONT_BOLD,
    )
    s.map("TButton",
        background=[("active", C["accent_dk"]), ("disabled", C["surface2"])],
        foreground=[("disabled", C["text_muted"])],
    )
    # Secondary button
    s.configure("Secondary.TButton",
        background=C["surface2"], foreground=C["text"],
        bordercolor=C["border"], lightcolor=C["surface2"], darkcolor=C["surface3"],
        relief="flat", padding=(18, 9),
    )
    s.map("Secondary.TButton", background=[("active", C["surface3"])])

    # Danger button
    s.configure("Danger.TButton",
        background="#c75069", foreground="white",
        bordercolor="#c75069", lightcolor="#f7768e", darkcolor="#a03050",
        relief="flat", padding=(18, 9), font=FONT_BOLD,
    )
    s.map("Danger.TButton", background=[("active", "#a03050")])

    # Notebook
    s.configure("TNotebook", background=C["bg"], bordercolor=C["bg"])
    s.configure("TNotebook.Tab",
        background=C["surface"], foreground=C["text_muted"], padding=(22, 10),
    )
    s.map("TNotebook.Tab",
        background=[("selected", C["surface2"])],
        foreground=[("selected", C["accent"])],
    )

    # Progressbar
    s.configure("TProgressbar",
        troughcolor=C["surface2"], background=C["accent"],
        bordercolor=C["surface2"], lightcolor=C["accent"], darkcolor=C["accent_dk"],
        thickness=6,
    )

    for w in ("TRadiobutton", "TCheckbutton"):
        s.configure(w, background=C["bg"], foreground=C["text"])
        s.map(w,
            background=[("active", C["bg"])],
            foreground=[("active", C["text"])],
            indicatorcolor=[("selected", C["accent"]), ("!selected", C["surface2"])],
        )

    s.configure("Card.TCheckbutton", background=C["surface2"], foreground=C["text"])
    s.map("Card.TCheckbutton",
        background=[("active", C["surface2"])],
        indicatorcolor=[("selected", C["accent"]), ("!selected", C["surface3"])],
    )

    s.configure("TCombobox",
        fieldbackground=C["surface2"], foreground=C["text"],
        background=C["surface2"], selectbackground=C["accent"],
        arrowcolor=C["text_muted"],
    )
    s.map("TCombobox",
        fieldbackground=[("readonly", C["surface2"])],
        selectbackground=[("readonly", C["accent"])],
    )

    s.configure("TSpinbox",
        fieldbackground=C["surface2"], foreground=C["text"],
        background=C["surface2"], arrowcolor=C["text_muted"], insertcolor=C["text"],
    )

    s.configure("TScrollbar",
        background=C["surface2"], troughcolor=C["surface"],
        bordercolor=C["surface"], arrowcolor=C["text_muted"],
    )


# ── カード風フレーム ─────────────────────────────────────────────────────────────

class Card(tk.Frame):
    """角を丸めたカード風パネル（Canvas ベース）。"""

    def __init__(self, parent: tk.Widget, **kw):
        super().__init__(parent, bg=C["bg"])
        radius = kw.pop("radius", 10)
        pad    = kw.pop("pad", 16)
        bg     = kw.pop("card_bg", C["surface"])

        self._canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)

        self._inner = tk.Frame(self._canvas, bg=bg, **kw)
        self._window = self._canvas.create_window(0, 0, anchor="nw", window=self._inner)
        self._radius = radius
        self._pad    = pad
        self._bg     = bg

        self._canvas.bind("<Configure>", self._on_resize)
        self._inner.bind("<Configure>",  self._on_inner_resize)

    def _on_resize(self, event: tk.Event) -> None:
        w, h = event.width, event.height
        self._canvas.delete("card_bg")
        r = self._radius
        self._canvas.create_arc( 0,  0, 2*r, 2*r, start=90,  extent=90, fill=self._bg, outline=self._bg, tags="card_bg")
        self._canvas.create_arc(w-2*r, 0, w, 2*r, start=0,  extent=90, fill=self._bg, outline=self._bg, tags="card_bg")
        self._canvas.create_arc( 0, h-2*r, 2*r, h, start=180, extent=90, fill=self._bg, outline=self._bg, tags="card_bg")
        self._canvas.create_arc(w-2*r, h-2*r, w, h, start=270, extent=90, fill=self._bg, outline=self._bg, tags="card_bg")
        self._canvas.create_rectangle(r, 0, w-r, h,   fill=self._bg, outline=self._bg, tags="card_bg")
        self._canvas.create_rectangle(0, r, w,   h-r, fill=self._bg, outline=self._bg, tags="card_bg")
        self._canvas.coords(self._window, self._pad, self._pad)
        self._canvas.itemconfigure(self._window, width=w - 2*self._pad)

    def _on_inner_resize(self, _event: tk.Event) -> None:
        h = self._inner.winfo_reqheight() + 2 * self._pad
        self._canvas.configure(height=h)

    @property
    def inner(self) -> tk.Frame:
        return self._inner


# ── ヘルパー ─────────────────────────────────────────────────────────────────────

def _lbl(parent: tk.Widget, text: str, style: str = "TLabel", **kw) -> ttk.Label:
    return ttk.Label(parent, text=text, style=style, **kw)


def _sep(parent: tk.Widget) -> ttk.Separator:
    sep = ttk.Separator(parent, orient="horizontal")
    sep.pack(fill="x", pady=10)
    return sep


# ── メイン GUI ──────────────────────────────────────────────────────────────────

class Mp4CompGUI(tk.Tk):

    def __init__(self) -> None:
        super().__init__()
        self.title("mp4-comp")
        self.geometry("820x820")
        self.minsize(760, 720)

        _apply_dark_theme(self)

        self.event_queue: queue.Queue = queue.Queue()
        self.is_running   = False

        # 予約状態
        self._schedule_cancel = threading.Event()
        self._is_scheduled    = False

        # 画質プロファイルマップ
        self.quality_label_to_key = {p.label: p.key for p in QUALITY_PROFILES}
        self.quality_key_to_label = {p.key: p.label for p in QUALITY_PROFILES}

        # ── 圧縮タブ変数 ──
        self.input_path_var          = tk.StringVar()
        self.mode_var                = tk.StringVar(value="size")
        self.target_size_var         = tk.StringVar(value=str(DEFAULT_TARGET_SIZE_MB))
        self.quality_var             = tk.StringVar(value=self.quality_key_to_label[DEFAULT_QUALITY_KEY])
        self.current_quality_var     = tk.StringVar(value="ファイルを選択すると現在の画質を判定します。")
        self.video_detail_var        = tk.StringVar(value="長さや解像度などをここに表示します。")
        self.output_hint_var         = tk.StringVar(value="出力ファイル名は自動で決まります。")
        self.quality_description_var = tk.StringVar()
        self.quality_estimate_var    = tk.StringVar()
        self._video_info             = None  # 解析済み VideoInfo を保持

        # ── 変換タブ変数 ──
        self.conv_input_path_var  = tk.StringVar()
        self.conv_video_detail_var = tk.StringVar(value="長さや解像度などをここに表示します。")
        self.conv_output_hint_var  = tk.StringVar(value="出力ファイル名は自動で決まります。")

        # ── 共通予約変数 ──
        self.schedule_enabled_var = tk.BooleanVar(value=False)
        _now_plus1 = datetime.now() + timedelta(hours=1)
        self.sched_year_var  = tk.StringVar(value=str(_now_plus1.year))
        self.sched_month_var = tk.StringVar(value=f"{_now_plus1.month:02d}")
        self.sched_day_var   = tk.StringVar(value=f"{_now_plus1.day:02d}")
        self.sched_hour_var  = tk.StringVar(value=f"{_now_plus1.hour:02d}")
        self.sched_min_var   = tk.StringVar(value=f"{_now_plus1.minute:02d}")

        self._build_ui()
        self._apply_mode_state()
        self._update_quality_description()
        self._update_output_hint()
        self.after(150, self._poll_events)
        self.after(1000, self._tick_countdown)

    # ── UI 構築 ──────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = tk.Frame(self, bg=C["bg"])
        outer.pack(fill="both", expand=True, padx=18, pady=14)

        # ヘッダー
        hdr = tk.Frame(outer, bg=C["bg"])
        hdr.pack(fill="x", pady=(0, 10))
        tk.Label(hdr, text="mp4-comp", font=("Segoe UI", 18, "bold"),
                 fg=C["accent"], bg=C["bg"]).pack(side="left")
        tk.Label(hdr, text="  動画圧縮 & 変換ツール", font=FONT,
                 fg=C["text_muted"], bg=C["bg"]).pack(side="left", padx=(4, 0))

        # タブ（残りの縦スペースを分け合う）
        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)

        compress_tab = tk.Frame(self.notebook, bg=C["bg"])
        self.notebook.add(compress_tab, text="  MP4 圧縮  ")

        convert_tab = tk.Frame(self.notebook, bg=C["bg"])
        self.notebook.add(convert_tab, text="  MOV → MP4 変換  ")

        self._build_compress_tab(compress_tab)
        self._build_convert_tab(convert_tab)

        # 共有ステータスエリア（固定高さ）
        status_hdr = tk.Frame(outer, bg=C["bg"])
        status_hdr.pack(fill="x", pady=(10, 4))
        tk.Label(status_hdr, text="ログ", font=FONT_BOLD,
                 fg=C["text_muted"], bg=C["bg"]).pack(side="left")

        log_frame = tk.Frame(outer, bg=C["surface"], padx=2, pady=2)
        log_frame.pack(fill="x")

        self.status_text = ScrolledText(
            log_frame, height=8, wrap="word",
            bg=C["surface"], fg=C["text"], insertbackground=C["text"],
            font=FONT_MONO, relief="flat", borderwidth=0,
            selectbackground=C["accent"], selectforeground="white",
        )
        self.status_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.status_text.insert("end", "準備完了です。\n")
        self.status_text.configure(state="disabled")

    # ── 圧縮タブ ─────────────────────────────────────────────────────────────────

    def _build_compress_tab(self, parent: tk.Frame) -> None:
        scroll_outer = tk.Frame(parent, bg=C["bg"])
        scroll_outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(scroll_outer, bg=C["bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(scroll_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=C["bg"])
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_frame_configure(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(e):
            canvas.itemconfigure(win_id, width=e.width)

        inner.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_enter(_e): canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        def _on_leave(_e): canvas.unbind_all("<MouseWheel>")
        canvas.bind("<Enter>", _on_enter)
        canvas.bind("<Leave>", _on_leave)

        p = inner  # shorthand

        # ── 入力ファイル ──
        self._build_section_label(p, "入力ファイル")
        file_card = tk.Frame(p, bg=C["surface"], pady=10, padx=12)
        file_card.pack(fill="x", pady=(4, 0))
        row = tk.Frame(file_card, bg=C["surface"])
        row.pack(fill="x")
        self.file_entry = tk.Entry(
            row, textvariable=self.input_path_var,
            bg=C["surface2"], fg=C["text"], insertbackground=C["text"],
            relief="flat", font=FONT, bd=0,
        )
        self.file_entry.pack(side="left", fill="x", expand=True, ipady=6, ipadx=6)
        self.file_entry.bind("<FocusOut>", lambda _e: self._analyze_selected_file(False))
        self.browse_button = ttk.Button(file_card, text="参照...", command=self._browse_file,
                                        style="Secondary.TButton")
        self.browse_button.pack(side="right", padx=(8, 0))
        row.pack_configure(side="left", expand=True, fill="x")
        self.browse_button.pack(side="right")

        # ── 動画情報 ──
        self._build_section_label(p, "元動画の情報")
        info_card = tk.Frame(p, bg=C["surface"], pady=10, padx=12)
        info_card.pack(fill="x", pady=(4, 0))
        tk.Label(info_card, text="現在の画質", font=FONT_BOLD,
                 fg=C["accent"], bg=C["surface"]).pack(anchor="w")
        tk.Label(info_card, textvariable=self.current_quality_var,
                 fg=C["text"], bg=C["surface"], font=FONT, wraplength=680, justify="left").pack(anchor="w", pady=(2, 0))
        tk.Label(info_card, textvariable=self.video_detail_var,
                 fg=C["text_muted"], bg=C["surface"], font=FONT_SM, wraplength=680, justify="left").pack(anchor="w", pady=(6, 0))

        # ── 圧縮設定 ──
        self._build_section_label(p, "圧縮設定")
        mode_card = tk.Frame(p, bg=C["surface"], pady=10, padx=12)
        mode_card.pack(fill="x", pady=(4, 0))

        ttk.Radiobutton(mode_card, text="目標ファイルサイズで圧縮",
                        variable=self.mode_var, value="size",
                        command=self._on_mode_changed).pack(anchor="w")
        ttk.Radiobutton(mode_card, text="目標画質を言葉で選んで圧縮",
                        variable=self.mode_var, value="quality",
                        command=self._on_mode_changed).pack(anchor="w", pady=(6, 0))

        self.size_settings_frame = tk.Frame(mode_card, bg=C["surface"])
        self.size_settings_frame.pack(fill="x", pady=(10, 0))
        tk.Label(self.size_settings_frame, text="目標サイズ (MB)",
                 fg=C["text_muted"], bg=C["surface"], font=FONT_SM).pack(anchor="w")
        row2 = tk.Frame(self.size_settings_frame, bg=C["surface"])
        row2.pack(anchor="w", pady=(4, 0))
        self.size_entry = tk.Entry(
            row2, textvariable=self.target_size_var, width=10,
            bg=C["surface2"], fg=C["text"], insertbackground=C["text"],
            relief="flat", font=FONT, bd=0,
        )
        self.size_entry.pack(ipady=6, ipadx=6)
        tk.Label(row2, text="MB", fg=C["text_muted"], bg=C["surface"], font=FONT).pack(side="right", padx=(6, 0))

        self.quality_settings_frame = tk.Frame(mode_card, bg=C["surface"])
        self.quality_settings_frame.pack(fill="x", pady=(10, 0))
        tk.Label(self.quality_settings_frame, text="目標画質",
                 fg=C["text_muted"], bg=C["surface"], font=FONT_SM).pack(anchor="w")
        self.quality_combo = ttk.Combobox(
            self.quality_settings_frame,
            textvariable=self.quality_var,
            values=[p.label for p in QUALITY_PROFILES],
            state="readonly", width=30,
        )
        self.quality_combo.pack(anchor="w", pady=(4, 0))
        self.quality_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_quality_changed())
        tk.Label(self.quality_settings_frame, textvariable=self.quality_description_var,
                 fg=C["text_muted"], bg=C["surface"], font=FONT_SM,
                 wraplength=640, justify="left").pack(anchor="w", pady=(6, 0))
        # 推定サイズ行
        est_row = tk.Frame(self.quality_settings_frame, bg=C["surface"])
        est_row.pack(anchor="w", pady=(6, 0))
        tk.Label(est_row, text="目安サイズ:", fg=C["text_muted"], bg=C["surface"], font=FONT_SM).pack(side="left")
        self._quality_estimate_label = tk.Label(
            est_row, textvariable=self.quality_estimate_var,
            fg=C["accent"], bg=C["surface"], font=FONT_BOLD,
        )
        self._quality_estimate_label.pack(side="left", padx=(6, 0))

        # ── 出力先 ──
        self._build_section_label(p, "出力先")
        out_card = tk.Frame(p, bg=C["surface"], pady=10, padx=12)
        out_card.pack(fill="x", pady=(4, 0))
        tk.Label(out_card, textvariable=self.output_hint_var,
                 fg=C["text_muted"], bg=C["surface"], font=FONT_SM,
                 wraplength=680, justify="left").pack(anchor="w")

        # ── 実行予約 ──
        self._build_section_label(p, "実行予約")
        self.compress_sched_frame = self._build_schedule_section(p)

        # ── プログレスバー ──
        self._build_section_label(p, "進捗")
        prog_card = tk.Frame(p, bg=C["surface"], pady=10, padx=12)
        prog_card.pack(fill="x", pady=(4, 0))
        self.compress_progress = ttk.Progressbar(prog_card, mode="indeterminate", length=400)
        self.compress_progress.pack(fill="x")
        self.compress_progress_label = tk.Label(prog_card, text="待機中",
                                                fg=C["text_muted"], bg=C["surface"], font=FONT_SM)
        self.compress_progress_label.pack(anchor="w", pady=(4, 0))

        # ── アクションボタン ──
        btn_row = tk.Frame(p, bg=C["bg"])
        btn_row.pack(fill="x", pady=(14, 8))
        self.compress_cancel_btn = ttk.Button(
            btn_row, text="予約をキャンセル", style="Danger.TButton",
            command=self._cancel_schedule, state="disabled",
        )
        self.compress_cancel_btn.pack(side="left")
        self.start_button = ttk.Button(
            btn_row, text="圧縮を開始  →", command=self._start_compression,
        )
        self.start_button.pack(side="right")

    # ── 変換タブ ─────────────────────────────────────────────────────────────────

    def _build_convert_tab(self, parent: tk.Frame) -> None:
        scroll_outer = tk.Frame(parent, bg=C["bg"])
        scroll_outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(scroll_outer, bg=C["bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(scroll_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=C["bg"])
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_frame_configure(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(e):
            canvas.itemconfigure(win_id, width=e.width)

        inner.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_enter2(_e): canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        def _on_leave2(_e): canvas.unbind_all("<MouseWheel>")
        canvas.bind("<Enter>", _on_enter2)
        canvas.bind("<Leave>", _on_leave2)

        p = inner

        # ── 入力ファイル ──
        self._build_section_label(p, "入力ファイル (.MOV / 動画全般)")
        cfile_card = tk.Frame(p, bg=C["surface"], pady=10, padx=12)
        cfile_card.pack(fill="x", pady=(4, 0))
        row = tk.Frame(cfile_card, bg=C["surface"])
        row.pack(fill="x")
        self.conv_file_entry = tk.Entry(
            row, textvariable=self.conv_input_path_var,
            bg=C["surface2"], fg=C["text"], insertbackground=C["text"],
            relief="flat", font=FONT, bd=0,
        )
        self.conv_file_entry.pack(side="left", fill="x", expand=True, ipady=6, ipadx=6)
        self.conv_file_entry.bind("<FocusOut>", lambda _e: self._analyze_conv_file(False))
        self.conv_browse_button = ttk.Button(cfile_card, text="参照...", command=self._browse_conv_file,
                                              style="Secondary.TButton")
        self.conv_browse_button.pack(side="right", padx=(8, 0))
        row.pack_configure(side="left", expand=True, fill="x")
        self.conv_browse_button.pack(side="right")

        # ── 動画情報 ──
        self._build_section_label(p, "元動画の情報")
        cinfo_card = tk.Frame(p, bg=C["surface"], pady=10, padx=12)
        cinfo_card.pack(fill="x", pady=(4, 0))
        tk.Label(cinfo_card, textvariable=self.conv_video_detail_var,
                 fg=C["text_muted"], bg=C["surface"], font=FONT,
                 wraplength=680, justify="left").pack(anchor="w")

        # ── 出力先 ──
        self._build_section_label(p, "出力先")
        cout_card = tk.Frame(p, bg=C["surface"], pady=10, padx=12)
        cout_card.pack(fill="x", pady=(4, 0))
        tk.Label(cout_card, textvariable=self.conv_output_hint_var,
                 fg=C["text_muted"], bg=C["surface"], font=FONT_SM,
                 wraplength=680, justify="left").pack(anchor="w")

        # ── 変換について ──
        self._build_section_label(p, "変換の仕様")
        desc_card = tk.Frame(p, bg=C["surface"], pady=10, padx=12)
        desc_card.pack(fill="x", pady=(4, 0))
        tk.Label(desc_card,
                 text="MOV ファイルを高品質 (CRF 18) の H.264 MP4 に変換します。\n"
                      "音声は AAC 128kbps で再エンコードされます。",
                 fg=C["text_muted"], bg=C["surface"], font=FONT_SM,
                 wraplength=680, justify="left").pack(anchor="w")

        # ── 実行予約 ──
        self._build_section_label(p, "実行予約")
        self.convert_sched_frame = self._build_schedule_section(p)

        # ── プログレスバー ──
        self._build_section_label(p, "進捗")
        cprog_card = tk.Frame(p, bg=C["surface"], pady=10, padx=12)
        cprog_card.pack(fill="x", pady=(4, 0))
        self.convert_progress = ttk.Progressbar(cprog_card, mode="indeterminate", length=400)
        self.convert_progress.pack(fill="x")
        self.convert_progress_label = tk.Label(cprog_card, text="待機中",
                                               fg=C["text_muted"], bg=C["surface"], font=FONT_SM)
        self.convert_progress_label.pack(anchor="w", pady=(4, 0))

        # ── アクションボタン ──
        cbtn_row = tk.Frame(p, bg=C["bg"])
        cbtn_row.pack(fill="x", pady=(14, 8))
        self.convert_cancel_btn = ttk.Button(
            cbtn_row, text="予約をキャンセル", style="Danger.TButton",
            command=self._cancel_schedule, state="disabled",
        )
        self.convert_cancel_btn.pack(side="left")
        self.conv_start_button = ttk.Button(
            cbtn_row, text="変換を開始  →", command=self._start_conversion,
        )
        self.conv_start_button.pack(side="right")

    # ── セクションラベル ──────────────────────────────────────────────────────────

    def _build_section_label(self, parent: tk.Widget, text: str) -> None:
        tk.Label(parent, text=text.upper(), font=("Segoe UI", 8, "bold"),
                 fg=C["text_muted"], bg=C["bg"]).pack(anchor="w", pady=(14, 0))

    # ── 実行予約セクション ────────────────────────────────────────────────────────

    def _build_schedule_section(self, parent: tk.Widget) -> tk.Frame:
        card = tk.Frame(parent, bg=C["surface2"], pady=10, padx=12)
        card.pack(fill="x", pady=(4, 0))

        # チェックボックス
        chk = tk.Checkbutton(
            card, text="  指定した時刻に自動実行する",
            variable=self.schedule_enabled_var,
            command=self._on_schedule_toggle,
            bg=C["surface2"], fg=C["text"], font=FONT,
            activebackground=C["surface2"], activeforeground=C["text"],
            selectcolor=C["surface3"],
        )
        chk.pack(anchor="w")

        # 日時入力エリア（最初は非表示）
        detail = tk.Frame(card, bg=C["surface2"])
        detail.pack(fill="x", pady=(10, 0))
        detail.pack_forget()
        card._sched_detail = detail  # type: ignore[attr-defined]

        # 日付行
        drow = tk.Frame(detail, bg=C["surface2"])
        drow.pack(anchor="w")

        tk.Label(drow, text="日時:", fg=C["text_muted"], bg=C["surface2"], font=FONT_SM).pack(side="left", padx=(0, 8))

        def _spinbox(parent, var, width, from_, to_):
            sb = ttk.Spinbox(
                parent, textvariable=var, width=width, from_=from_, to=to_,
                wrap=True, format="%02.0f",
            )
            sb.pack(side="left", padx=2)
            return sb

        _spinbox(drow, self.sched_year_var,  5, 2024, 2099)
        tk.Label(drow, text="年", fg=C["text_muted"], bg=C["surface2"], font=FONT_SM).pack(side="left")
        _spinbox(drow, self.sched_month_var, 3, 1, 12)
        tk.Label(drow, text="月", fg=C["text_muted"], bg=C["surface2"], font=FONT_SM).pack(side="left")
        _spinbox(drow, self.sched_day_var,   3, 1, 31)
        tk.Label(drow, text="日", fg=C["text_muted"], bg=C["surface2"], font=FONT_SM).pack(side="left", padx=(0, 16))
        _spinbox(drow, self.sched_hour_var,  3, 0, 23)
        tk.Label(drow, text="時", fg=C["text_muted"], bg=C["surface2"], font=FONT_SM).pack(side="left")
        _spinbox(drow, self.sched_min_var,   3, 0, 59)
        tk.Label(drow, text="分", fg=C["text_muted"], bg=C["surface2"], font=FONT_SM).pack(side="left")

        # カウントダウン表示
        cd_row = tk.Frame(detail, bg=C["surface2"])
        cd_row.pack(anchor="w", pady=(10, 0))
        tk.Label(cd_row, text="実行まで :", fg=C["text_muted"], bg=C["surface2"], font=FONT_SM).pack(side="left", padx=(0, 8))
        self._countdown_label = tk.Label(cd_row, text="--:--:--",
                                          fg=C["warning"], bg=C["surface2"], font=FONT_CD)
        self._countdown_label.pack(side="left")

        # このカードを参照できるよう保持
        self._sched_detail_frame = detail

        return card

    # ── 予約トグル ────────────────────────────────────────────────────────────────

    def _on_schedule_toggle(self) -> None:
        if self.schedule_enabled_var.get():
            self._sched_detail_frame.pack(fill="x", pady=(10, 0))
        else:
            self._sched_detail_frame.pack_forget()

    # ── カウントダウンタイマー ────────────────────────────────────────────────────

    def _tick_countdown(self) -> None:
        if self._is_scheduled:
            try:
                target = self._parse_schedule_datetime()
                diff = target - datetime.now()
                total_secs = int(diff.total_seconds())
                if total_secs <= 0:
                    self._countdown_label.configure(text="00:00:00")
                else:
                    h, rem = divmod(total_secs, 3600)
                    m, s   = divmod(rem, 60)
                    self._countdown_label.configure(text=f"{h:02d}:{m:02d}:{s:02d}")
            except ValueError:
                self._countdown_label.configure(text="--:--:--")
        elif self.schedule_enabled_var.get():
            try:
                target = self._parse_schedule_datetime()
                diff = target - datetime.now()
                total_secs = int(diff.total_seconds())
                if total_secs <= 0:
                    self._countdown_label.configure(text="過去の日時です", fg=C["error"])
                else:
                    h, rem = divmod(total_secs, 3600)
                    m, s   = divmod(rem, 60)
                    self._countdown_label.configure(text=f"{h:02d}:{m:02d}:{s:02d}", fg=C["warning"])
            except ValueError:
                self._countdown_label.configure(text="--:--:--", fg=C["text_muted"])

        self.after(1000, self._tick_countdown)

    def _parse_schedule_datetime(self) -> datetime:
        return datetime(
            int(self.sched_year_var.get()),
            int(self.sched_month_var.get()),
            int(self.sched_day_var.get()),
            int(self.sched_hour_var.get()),
            int(self.sched_min_var.get()),
        )

    # ── 予約スケジュール実行 ──────────────────────────────────────────────────────

    def _schedule_and_run(self, action: str) -> None:
        """action: "compress" | "convert"。予約待機スレッドを起動する。"""
        try:
            target = self._parse_schedule_datetime()
        except ValueError as e:
            messagebox.showerror("予約エラー", f"日時の入力が正しくありません。\n{e}")
            return

        delay = (target - datetime.now()).total_seconds()
        if delay < 0:
            messagebox.showwarning("予約エラー", "指定した日時は過去です。\n未来の時刻を設定してください。")
            return

        self._schedule_cancel.clear()
        self._is_scheduled = True
        self._set_running_state(True, waiting=True)
        self._append_status(
            f"予約を設定しました。{target.strftime('%Y-%m-%d %H:%M')} に実行を開始します。"
        )

        def _waiter():
            import time as _time
            cancelled = self._schedule_cancel.wait(timeout=delay)
            if cancelled:
                self.event_queue.put(("schedule_cancelled", None))
            else:
                self.event_queue.put(("schedule_fire", action))

        threading.Thread(target=_waiter, daemon=True).start()

    def _cancel_schedule(self) -> None:
        if self._is_scheduled:
            self._schedule_cancel.set()

    # ── 共通ヘルパー ──────────────────────────────────────────────────────────────

    def _append_status(self, message: str) -> None:
        self.status_text.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self.status_text.insert("end", f"[{ts}] {message}\n")
        self.status_text.see("end")
        self.status_text.configure(state="disabled")

    def _set_running_state(self, is_running: bool, waiting: bool = False) -> None:
        self.is_running = is_running
        state = "disabled" if is_running else "normal"

        self.file_entry.configure(state=state)
        self.browse_button.configure(state=state)
        self.start_button.configure(state=state)
        self.conv_file_entry.configure(state=state)
        self.conv_browse_button.configure(state=state)
        self.conv_start_button.configure(state=state)

        cancel_state = "normal" if (is_running and waiting) else "disabled"
        self.compress_cancel_btn.configure(state=cancel_state)
        self.convert_cancel_btn.configure(state=cancel_state)

        if not is_running:
            self._apply_mode_state()
            self.compress_progress.stop()
            self.convert_progress.stop()
            self.compress_progress_label.configure(text="待機中", fg=C["text_muted"])
            self.convert_progress_label.configure(text="待機中", fg=C["text_muted"])
            self._is_scheduled = False
        else:
            self.size_entry.configure(state="disabled")
            self.quality_combo.configure(state="disabled")
            if not waiting:
                self.compress_progress.start(12)
                self.convert_progress.start(12)

    def _start_progress(self) -> None:
        self.compress_progress.start(12)
        self.convert_progress.start(12)
        self.compress_progress_label.configure(text="処理中...", fg=C["accent"])
        self.convert_progress_label.configure(text="処理中...", fg=C["accent"])

    def _queue_status(self, message: str) -> None:
        self.event_queue.put(("status", message))

    # ── 圧縮タブ ロジック ─────────────────────────────────────────────────────────

    def _browse_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="MP4ファイルを選択",
            filetypes=[("MP4 files", "*.mp4"), ("All files", "*.*")],
        )
        if not selected:
            return
        self.input_path_var.set(selected)
        self._update_output_hint()
        self._analyze_selected_file(show_message=True)

    def _analyze_selected_file(self, show_message: bool) -> None:
        path = self.input_path_var.get().strip().strip('"')
        self._update_output_hint()
        if not path:
            self._video_info = None
            self.current_quality_var.set("ファイルを選択すると現在の画質を判定します。")
            self.video_detail_var.set("長さや解像度などをここに表示します。")
            self._update_quality_description()
            return
        try:
            info = probe_video(path)
            self._video_info = info
            q = assess_video_quality(info)
            self.current_quality_var.set(f"{q.label}  —  {q.description}")
            self.video_detail_var.set(describe_video(info))
            self._update_quality_description()
            self._append_status(f"解析完了: {Path(path).name}")
        except Exception as exc:
            self._video_info = None
            self.current_quality_var.set("解析に失敗しました。")
            self.video_detail_var.set(str(exc))
            self._update_quality_description()
            if show_message:
                messagebox.showerror("解析エラー", str(exc))

    def _on_mode_changed(self) -> None:
        self._apply_mode_state()
        self._update_output_hint()

    def _on_quality_changed(self) -> None:
        self._update_quality_description()
        self._update_output_hint()

    def _apply_mode_state(self) -> None:
        if self.mode_var.get() == "size":
            self.size_entry.configure(state="normal")
            self.quality_combo.configure(state="disabled")
        else:
            self.size_entry.configure(state="disabled")
            self.quality_combo.configure(state="readonly")

    def _selected_quality_key(self) -> str:
        return self.quality_label_to_key[self.quality_var.get()]

    def _update_quality_description(self) -> None:
        from compress import estimate_quality_output_size_mb
        key = self._selected_quality_key()
        profile = next(p for p in QUALITY_PROFILES if p.key == key)
        self.quality_description_var.set(profile.description)

        if self._video_info is not None:
            estimated_mb = estimate_quality_output_size_mb(self._video_info, key)
            source_mb = self._video_info.source_size_bytes / (1024 * 1024)
            ratio = (estimated_mb / source_mb * 100) if source_mb > 0 else 0
            self.quality_estimate_var.set(f"約 {estimated_mb:.1f} MB  ({ratio:.0f}%)")
            self._quality_estimate_label.configure(fg=C["accent"])
        else:
            self.quality_estimate_var.set("ファイルを選択すると表示されます")
            self._quality_estimate_label.configure(fg=C["text_muted"])

    def _update_output_hint(self) -> None:
        path = self.input_path_var.get().strip().strip('"')
        if not path:
            self.output_hint_var.set("出力ファイル名は自動で決まります。")
            return
        source = Path(path)
        if self.mode_var.get() == "size":
            name = f"{source.stem}_compressed{source.suffix}"
        else:
            name = f"{source.stem}_quality_{self._selected_quality_key()}{source.suffix}"
        self.output_hint_var.set(f"→  {source.with_name(name)}")

    def _start_compression(self) -> None:
        input_path = self.input_path_var.get().strip().strip('"')
        if not input_path:
            messagebox.showwarning("入力不足", "圧縮する MP4 ファイルを選択してください。")
            return
        if not Path(input_path).exists():
            messagebox.showwarning("入力不足", "指定されたファイルが見つかりません。")
            return

        mode = self.mode_var.get()
        target_size = None
        if mode == "size":
            try:
                target_size = int(self.target_size_var.get().strip())
            except ValueError:
                messagebox.showwarning("入力不足", "目標サイズは整数で入力してください。")
                return
            if target_size <= 0:
                messagebox.showwarning("入力不足", "目標サイズは 1MB 以上で指定してください。")
                return

        if self.schedule_enabled_var.get():
            self._set_running_state(True, waiting=True)
            self._schedule_and_run("compress")
            return

        self._set_running_state(True)
        self._start_progress()
        self._append_status("圧縮を開始します。")
        threading.Thread(
            target=self._run_compression,
            args=(input_path, mode, target_size, self._selected_quality_key()),
            daemon=True,
        ).start()

    def _run_compression(self, input_path: str, mode: str, target_size, quality_key: str) -> None:
        try:
            if mode == "size":
                result = compress_video_to_size(
                    input_path, target_size or DEFAULT_TARGET_SIZE_MB,
                    status_callback=self._queue_status,
                )
            else:
                result = compress_video_to_quality(
                    input_path, quality_key,
                    status_callback=self._queue_status,
                )
            self.event_queue.put(("done", result))
        except Exception as exc:
            self.event_queue.put(("error", str(exc)))
        finally:
            self.event_queue.put(("idle", None))

    # ── 変換タブ ロジック ─────────────────────────────────────────────────────────

    def _browse_conv_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="動画ファイルを選択",
            filetypes=[
                ("MOV files", "*.mov *.MOV"),
                ("動画ファイル", "*.mov *.MOV *.mp4 *.avi *.mkv"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return
        self.conv_input_path_var.set(selected)
        self._update_conv_output_hint()
        self._analyze_conv_file(show_message=True)

    def _analyze_conv_file(self, show_message: bool) -> None:
        path = self.conv_input_path_var.get().strip().strip('"')
        self._update_conv_output_hint()
        if not path:
            self.conv_video_detail_var.set("長さや解像度などをここに表示します。")
            return
        try:
            info = probe_video(path)
            self.conv_video_detail_var.set(describe_video(info))
            self._append_status(f"解析完了: {Path(path).name}")
        except Exception as exc:
            self.conv_video_detail_var.set(str(exc))
            if show_message:
                messagebox.showerror("解析エラー", str(exc))

    def _update_conv_output_hint(self) -> None:
        path = self.conv_input_path_var.get().strip().strip('"')
        if not path:
            self.conv_output_hint_var.set("出力ファイル名は自動で決まります。")
            return
        source = Path(path)
        name = f"{source.stem}.mp4" if source.suffix.lower() != ".mp4" else f"{source.stem}_converted.mp4"
        self.conv_output_hint_var.set(f"→  {source.with_name(name)}")

    def _start_conversion(self) -> None:
        input_path = self.conv_input_path_var.get().strip().strip('"')
        if not input_path:
            messagebox.showwarning("入力不足", "変換する動画ファイルを選択してください。")
            return
        if not Path(input_path).exists():
            messagebox.showwarning("入力不足", "指定されたファイルが見つかりません。")
            return

        if self.schedule_enabled_var.get():
            self._set_running_state(True, waiting=True)
            self._schedule_and_run("convert")
            return

        self._set_running_state(True)
        self._start_progress()
        self._append_status("MOV → MP4 変換を開始します。")
        threading.Thread(
            target=self._run_conversion_thread,
            args=(input_path,),
            daemon=True,
        ).start()

    def _run_conversion_thread(self, input_path: str) -> None:
        try:
            result = convert_mov_to_mp4(input_path, status_callback=self._queue_status)
            self.event_queue.put(("done", result))
        except Exception as exc:
            self.event_queue.put(("error", str(exc)))
        finally:
            self.event_queue.put(("idle", None))

    # ── イベントポーリング ────────────────────────────────────────────────────────

    def _poll_events(self) -> None:
        while True:
            try:
                event_type, payload = self.event_queue.get_nowait()
            except queue.Empty:
                break

            if event_type == "status":
                self._append_status(str(payload))

            elif event_type == "done":
                result = payload
                self.compress_progress.stop()
                self.convert_progress.stop()
                self.compress_progress_label.configure(text="完了", fg=C["success"])
                self.convert_progress_label.configure(text="完了", fg=C["success"])
                self._append_status("処理が完了しました。")
                messagebox.showinfo(
                    "完了",
                    f"出力ファイル:\n{result.output_file}\n\n出力サイズ: {result.final_size_mb:.2f} MB",
                )
                self._analyze_selected_file(show_message=False)

            elif event_type == "error":
                self.compress_progress.stop()
                self.convert_progress.stop()
                self.compress_progress_label.configure(text="エラー", fg=C["error"])
                self.convert_progress_label.configure(text="エラー", fg=C["error"])
                self._append_status(f"エラー: {payload}")
                messagebox.showerror("エラー", str(payload))

            elif event_type == "idle":
                self._set_running_state(False)

            elif event_type == "schedule_fire":
                action = payload
                self._is_scheduled = False
                self._append_status("予約時刻になりました。処理を開始します。")
                self._start_progress()
                if action == "compress":
                    input_path = self.input_path_var.get().strip().strip('"')
                    mode = self.mode_var.get()
                    target_size = None
                    if mode == "size":
                        try:
                            target_size = int(self.target_size_var.get().strip())
                        except ValueError:
                            target_size = DEFAULT_TARGET_SIZE_MB
                    threading.Thread(
                        target=self._run_compression,
                        args=(input_path, mode, target_size, self._selected_quality_key()),
                        daemon=True,
                    ).start()
                else:
                    input_path = self.conv_input_path_var.get().strip().strip('"')
                    threading.Thread(
                        target=self._run_conversion_thread,
                        args=(input_path,),
                        daemon=True,
                    ).start()

            elif event_type == "schedule_cancelled":
                self._is_scheduled = False
                self._set_running_state(False)
                self._append_status("予約をキャンセルしました。")

        self.after(150, self._poll_events)


def main() -> None:
    try:
        app = Mp4CompGUI()
    except tk.TclError as exc:
        print("GUI の起動に失敗しました。")
        print(f"詳細: {exc}")
        sys.exit(1)
    app.mainloop()


if __name__ == "__main__":
    main()
