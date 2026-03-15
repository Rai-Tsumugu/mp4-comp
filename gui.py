import os
import queue
import sys
import threading
from pathlib import Path

from compress import (
    DEFAULT_QUALITY_KEY,
    DEFAULT_TARGET_SIZE_MB,
    QUALITY_PROFILES,
    assess_video_quality,
    compress_video_to_quality,
    compress_video_to_size,
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


class Mp4CompGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("mp4-comp")
        self.geometry("760x620")
        self.minsize(720, 580)

        self.event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.is_running = False

        self.input_path_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="size")
        self.target_size_var = tk.StringVar(value=str(DEFAULT_TARGET_SIZE_MB))
        self.current_quality_var = tk.StringVar(value="ファイルを選択すると現在の画質を判定します。")
        self.video_detail_var = tk.StringVar(value="長さや解像度などをここに表示します。")
        self.output_hint_var = tk.StringVar(value="出力ファイル名は自動で決まります。")
        self.quality_description_var = tk.StringVar()

        self.quality_label_to_key = {profile.label: profile.key for profile in QUALITY_PROFILES}
        self.quality_key_to_label = {profile.key: profile.label for profile in QUALITY_PROFILES}
        self.quality_var = tk.StringVar(value=self.quality_key_to_label[DEFAULT_QUALITY_KEY])

        self._build_ui()
        self._apply_mode_state()
        self._update_quality_description()
        self._update_output_hint()
        self.after(150, self._poll_events)

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)

        file_frame = ttk.LabelFrame(root, text="入力ファイル", padding=12)
        file_frame.pack(fill="x")

        self.file_entry = ttk.Entry(file_frame, textvariable=self.input_path_var)
        self.file_entry.pack(fill="x", side="left", expand=True)
        self.file_entry.bind("<FocusOut>", lambda _event: self._analyze_selected_file(show_message=False))

        self.browse_button = ttk.Button(file_frame, text="参照...", command=self._browse_file)
        self.browse_button.pack(side="left", padx=(8, 0))

        info_frame = ttk.LabelFrame(root, text="元動画の状態", padding=12)
        info_frame.pack(fill="x", pady=(12, 0))

        ttk.Label(
            info_frame,
            text="現在の画質",
            font=("", 10, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            info_frame,
            textvariable=self.current_quality_var,
            wraplength=680,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))
        ttk.Label(
            info_frame,
            textvariable=self.video_detail_var,
            foreground="#444444",
            wraplength=680,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        mode_frame = ttk.LabelFrame(root, text="圧縮方法", padding=12)
        mode_frame.pack(fill="x", pady=(12, 0))

        ttk.Radiobutton(
            mode_frame,
            text="目標ファイルサイズで圧縮する",
            variable=self.mode_var,
            value="size",
            command=self._on_mode_changed,
        ).pack(anchor="w")
        ttk.Radiobutton(
            mode_frame,
            text="目標画質を言葉で選んで圧縮する",
            variable=self.mode_var,
            value="quality",
            command=self._on_mode_changed,
        ).pack(anchor="w", pady=(6, 0))

        self.size_settings_frame = ttk.Frame(mode_frame)
        self.size_settings_frame.pack(fill="x", pady=(12, 0))
        ttk.Label(self.size_settings_frame, text="目標サイズ (MB)").pack(anchor="w")
        self.size_entry = ttk.Entry(
            self.size_settings_frame, textvariable=self.target_size_var, width=12
        )
        self.size_entry.pack(anchor="w", pady=(4, 0))

        self.quality_settings_frame = ttk.Frame(mode_frame)
        self.quality_settings_frame.pack(fill="x", pady=(12, 0))
        ttk.Label(self.quality_settings_frame, text="目標画質").pack(anchor="w")
        self.quality_combo = ttk.Combobox(
            self.quality_settings_frame,
            textvariable=self.quality_var,
            values=[profile.label for profile in QUALITY_PROFILES],
            state="readonly",
        )
        self.quality_combo.pack(fill="x", pady=(4, 0))
        self.quality_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_quality_changed())
        ttk.Label(
            self.quality_settings_frame,
            textvariable=self.quality_description_var,
            foreground="#444444",
            wraplength=680,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        output_frame = ttk.LabelFrame(root, text="出力", padding=12)
        output_frame.pack(fill="x", pady=(12, 0))
        ttk.Label(
            output_frame,
            textvariable=self.output_hint_var,
            wraplength=680,
            justify="left",
        ).pack(anchor="w")

        action_frame = ttk.Frame(root)
        action_frame.pack(fill="x", pady=(12, 0))
        self.start_button = ttk.Button(action_frame, text="圧縮を開始", command=self._start_compression)
        self.start_button.pack(anchor="e")

        status_frame = ttk.LabelFrame(root, text="ステータス", padding=12)
        status_frame.pack(fill="both", expand=True, pady=(12, 0))
        self.status_text = ScrolledText(status_frame, height=14, wrap="word")
        self.status_text.pack(fill="both", expand=True)
        self.status_text.insert("end", "準備完了です。\n")
        self.status_text.configure(state="disabled")

    def _append_status(self, message: str) -> None:
        self.status_text.configure(state="normal")
        self.status_text.insert("end", message + "\n")
        self.status_text.see("end")
        self.status_text.configure(state="disabled")

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
            self.current_quality_var.set("ファイルを選択すると現在の画質を判定します。")
            self.video_detail_var.set("長さや解像度などをここに表示します。")
            return

        try:
            video_info = probe_video(path)
            quality = assess_video_quality(video_info)
            self.current_quality_var.set(f"{quality.label} - {quality.description}")
            self.video_detail_var.set(describe_video(video_info))
            self._append_status(f"解析完了: {Path(path).name}")
        except Exception as exc:
            self.current_quality_var.set("解析に失敗しました。")
            self.video_detail_var.set(str(exc))
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
        selected_key = self._selected_quality_key()
        profile = next(profile for profile in QUALITY_PROFILES if profile.key == selected_key)
        self.quality_description_var.set(profile.description)

    def _update_output_hint(self) -> None:
        path = self.input_path_var.get().strip().strip('"')
        if not path:
            self.output_hint_var.set("出力ファイル名は自動で決まります。")
            return

        source = Path(path)
        if self.mode_var.get() == "size":
            output_name = f"{source.stem}_compressed{source.suffix}"
        else:
            output_name = f"{source.stem}_quality_{self._selected_quality_key()}{source.suffix}"
        self.output_hint_var.set(f"出力ファイル: {source.with_name(output_name)}")

    def _set_running_state(self, is_running: bool) -> None:
        self.is_running = is_running
        state = "disabled" if is_running else "normal"
        self.file_entry.configure(state=state)
        self.browse_button.configure(state=state)
        self.start_button.configure(state=state)
        if not is_running:
            self._apply_mode_state()
        else:
            self.size_entry.configure(state="disabled")
            self.quality_combo.configure(state="disabled")

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

        self._set_running_state(True)
        self._append_status("圧縮を開始します。")

        worker = threading.Thread(
            target=self._run_compression,
            args=(input_path, mode, target_size, self._selected_quality_key()),
            daemon=True,
        )
        worker.start()

    def _run_compression(
        self, input_path: str, mode: str, target_size: int | None, quality_key: str
    ) -> None:
        try:
            if mode == "size":
                result = compress_video_to_size(
                    input_path, target_size or DEFAULT_TARGET_SIZE_MB, self._queue_status
                )
            else:
                result = compress_video_to_quality(input_path, quality_key, self._queue_status)
            self.event_queue.put(("done", result))
        except Exception as exc:
            self.event_queue.put(("error", str(exc)))
        finally:
            self.event_queue.put(("idle", None))

    def _queue_status(self, message: str) -> None:
        self.event_queue.put(("status", message))

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
                self._append_status("処理が完了しました。")
                messagebox.showinfo(
                    "完了",
                    f"出力ファイル:\n{result.output_file}\n\n出力サイズ: {result.final_size_mb:.2f} MB",
                )
                self._analyze_selected_file(show_message=False)
            elif event_type == "error":
                self._append_status(f"エラー: {payload}")
                messagebox.showerror("圧縮エラー", str(payload))
            elif event_type == "idle":
                self._set_running_state(False)

        self.after(150, self._poll_events)


def main() -> None:
    try:
        app = Mp4CompGUI()
    except tk.TclError as exc:
        print("GUI の起動に失敗しました。")
        print("この環境では Tcl/Tk ランタイムが不整合なため、Windows では gui.ps1 の利用を推奨します。")
        print(f"詳細: {exc}")
        sys.exit(1)

    app.mainloop()


if __name__ == "__main__":
    main()
