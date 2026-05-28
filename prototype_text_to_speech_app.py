"""
text_to_speech_app.py
---------------------
Text-to-Speech GUI application.

Segments:
1) MAIN WINDOW
   - Clear Text
   - Play button
   - Rewind button

2) WIZARDS
   - Settings screen (speed + font size)

3) DIALOG BOXES
   - Open file
   - Save / Save As (WAV, MP3, OGG audio)
   - About the application
   - Audio Settings Dialog

4) CHANGE SPEED
   - UI controls and logic to change playback speed

Dependencies:
    pip install pyttsx3
    pip install pydub   # optional, for MP3/OGG (requires ffmpeg)
"""

from __future__ import annotations

import os
import sys
import threading
import queue
from typing import Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tkinter.font as tkfont

import pyttsx3

# Optional pydub for MP3/OGG export
try:
    from pydub import AudioSegment
    HAVE_PYDUB = True
except Exception:
    HAVE_PYDUB = False


# ============================================================
# SHARED: THREADED TTS ENGINE (used by main window + dialogs)
# ============================================================

class TTSEngine:
    """Threaded wrapper around pyttsx3 so GUI stays responsive."""

    def __init__(self, on_volume_change=None) -> None:
        self.on_volume_change = on_volume_change
        self._engine = pyttsx3.init()
        self._cmd_q: "queue.Queue[tuple[str, tuple, dict]]" = queue.Queue()
        self._stop_flag = threading.Event()
        self._speaking_flag = threading.Event()
        self._stop_requested = threading.Event()
        self._lock = threading.Lock()
        self._current_rate = 180
        self._current_volume = 0.5
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def set_volume(self, volume: float) -> None:
        """Set TTS volume immediately (0.0 to 1.0)."""
        self._current_volume = max(0.0, min(1.0, float(volume)))
        with self._lock:
            try:
                self._engine.setProperty("volume", self._current_volume)
            except Exception:
                pass

        if self.on_volume_change:
            self.on_volume_change(self._current_volume)

    def set_rate(self, rate: int) -> None:
        """Set TTS rate immediately."""
        self._current_rate = int(rate)
        with self._lock:
            try:
                self._engine.setProperty("rate", self._current_rate)
            except Exception:
                pass

    def speak(self, text: str) -> None:
        """Queue text to be spoken."""
        self._stop_requested.clear()
        self._cmd_q.put(("speak", (text,), {}))

    def stop(self) -> None:
        """Stop speech immediately."""
        self._stop_requested.set()
        with self._lock:
            try:
                self._engine.stop()
            except Exception:
                pass
        # Clear any pending speak commands
        while not self._cmd_q.empty():
            try:
                self._cmd_q.get_nowait()
                self._cmd_q.task_done()
            except queue.Empty:
                break

    def save_audio(self, text: str, path: str, fmt: Optional[str]) -> None:
        self._cmd_q.put(("save", (text, path, fmt), {}))

    def shutdown(self) -> None:
        self._stop_flag.set()
        self.stop()

    def _run(self) -> None:
        while not self._stop_flag.is_set():
            try:
                cmd, args, _kwargs = self._cmd_q.get(timeout=0.1)
            except queue.Empty:
                continue

            if cmd == "speak":
                if self._stop_requested.is_set():
                    self._cmd_q.task_done()
                    continue
                text = args[0]
                try:
                    self._speaking_flag.set()
                    with self._lock:
                        self._engine.setProperty("rate", self._current_rate)
                        self._engine.setProperty("volume", self._current_volume)
                        self._engine.say(text)
                    self._engine.runAndWait()
                except Exception:
                    pass
                finally:
                    self._speaking_flag.clear()

            elif cmd == "save":
                text, path, fmt = args
                try:
                    self._handle_save(text, path, fmt)
                except Exception:
                    pass

            self._cmd_q.task_done()

    def _handle_save(self, text: str, path: str, fmt: Optional[str]) -> None:
        # infer format from extension if needed
        if not fmt:
            if "." in path:
                fmt = path.rsplit(".", 1)[1].lower()
            else:
                fmt = "wav"
                path = path + ".wav"
        fmt = fmt.lower()

        if fmt == "wav":
            self._engine.save_to_file(text, path)
            self._engine.runAndWait()
        else:
            if not HAVE_PYDUB:
                raise RuntimeError("MP3/OGG export requires pydub + ffmpeg.")
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                wav_path = os.path.join(tmp, "tts_temp.wav")
                self._engine.save_to_file(text, wav_path)
                self._engine.runAndWait()
                audio = AudioSegment.from_wav(wav_path)
                audio.export(path, format=fmt)

# ============================================================
# SEGMENT 2: WIZARDS (SETTINGS SCREEN FOR SPEED & FONT SIZE)
# ============================================================

class SettingsWizard(tk.Toplevel):
    """
    Wizard / settings screen.

    Lets the user:
    - change TTS speed (words per minute)
    - change font size for the text box
    - live font preview
    - validation and clamped values
    - live font preview
    - validation and clamped values
    """

    def __init__(self, parent: tk.Tk, font_size: int) -> None:
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result: Optional[tuple[int, int]] = None

        # Main Body
        # Main Body
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        # Font size Selection
        ttk.Label(body, text="Font size:").grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 2))
        self.size_var = tk.IntVar(value=font_size)
        self.size_spin = tk.Spinbox(body, from_=8, to=48, textvariable=self.size_var, width=6, command=self._update_preview_font)
        self.size_spin.grid(row=3, column=0, sticky="w")
        
        # Preview Box
        preview_frame = tk.LabelFrame(body, text="Preview", pady=10)
        preview_frame.grid(row=4, column=0, columnspan=2, sticky="we", pady=(12,0))
        
        self.preview_label = tk.Label(preview_frame, text="This is a test.")
        self.preview_label.pack(fill="x")
        self._update_preview_font()

        # Buttons
        btns = ttk.Frame(body)
        btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(14, 0))
        btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="Cancel", command=self._cancel).pack(side="right")
        ttk.Button(btns, text="OK", command=self._ok).pack(side="right", padx=(0, 8))
        
        # Keyboard Bindings
        
        # Keyboard Bindings
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())

        # Layout Behavior
        # Layout Behavior
        body.columnconfigure(0, weight=1)
        
        # Window Position (offset from parent)
        
        # Window Position (offset from parent)
        self.update_idletasks()
        px = parent.winfo_rootx() + 80
        py = parent.winfo_rooty() + 80
        self.geometry(f"+{px}+{py}")

    # Internal Callbacks
    def _on_speed_change(self, _val: str) -> None:
        """Keep speed_var synced wit the slidebar and clamp to ints."""
        val = (int(float(self.speed_scale.get())))
        val = max(80,min(300, val))
        self.speed_var.set(val)
        self.speed_label.configure(text=str(val))
    
    def _update_preview_font(self) -> None:
        """Live update font size in the preview text."""
        px = parent.winfo_rootx() + 80
        py = parent.winfo_rooty() + 80
        self.geometry(f"+{px}+{py}")

    # Internal Callbacks
    def _on_speed_change(self, _val: str) -> None:
        """Keep speed_var synced wit the slidebar and clamp to ints."""
        val = (int(float(self.speed_scale.get())))
        val = max(80,min(300, val))
        self.speed_var.set(val)
        self.speed_label.configure(text=str(val))
    
    def _update_preview_font(self) -> None:
        """Live update font size in the preview text."""
        try:
            size = int(self.size_var.get())
        except Exception:
            size = 12
        size = max(8, min(48, size))
        self.size_var.set(size)
        
        font_obj = tkfont.Font(size=size)
        self.preview_label.configure(font=font_obj)
        
        
    # OK/Cancel
    def _ok(self) -> None:
        """Validate and return chosen values."""
        try:
            size = max(8, min(48,int(self.size_var.get())))
        except Exception:
            size = 180, 12
        self.result = (size)
        self.grab_release()
        self.destroy()

    def _cancel(self) -> None:
        """Cancel -> return None"""
        self.result = None
        self.grab_release()
        self.destroy()


# ============================================================
# SEGMENT 3: DIALOG BOXES
#   - OPEN FILE
#   - SAVE / SAVE AS (AUDIO)
#   - ABOUT THE APPLICATION
# ============================================================

class DialogMixin:
    """
    Mixin for dialog-related methods.
    This expects the main window to have:
    - self (Tk)
    - self.text (Text widget)
    - self.tts (TTSEngine)
    - self.current_text_path
    - self._set_status(msg: str)
    """

    # --- OPEN FILE (TEXT) ---
    def open_text_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open Text File",
            filetypes=[("Text files", "*.txt *.md *.log *.csv"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            messagebox.showerror("Open Error", f"Failed to open file:\n{exc}")
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.current_text_path = path
        self._set_status(f"Opened: {os.path.basename(path)}")

    # --- SAVE / SAVE AS (AUDIO FILES) ---
    def save_audio_file(self) -> None:
        text = self.text.get("1.0", "end-1c").strip()
        if not text:
            messagebox.showwarning("No Text", "Please enter or open text before saving audio.")
            return

        path = filedialog.asksaveasfilename(
            title="Save Audio As",
            defaultextension=".wav",
            filetypes=[
                ("WAV audio", "*.wav"),
                ("MP3 audio", "*.mp3"),
                ("OGG audio", "*.ogg *.oga"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        ext = os.path.splitext(path)[1].lower().lstrip(".") or "wav"

        if ext != "wav" and not HAVE_PYDUB:
            messagebox.showerror(
                "Export Error",
                "MP3/OGG export requires pydub and ffmpeg.\n"
                "Please install them or save as WAV instead."
            )
            return

        self._set_status(f"Exporting audio as {ext.upper()}...")
        try:
            self.tts.save_audio(text, path, fmt=ext)
            messagebox.showinfo("Audio Export", f"Audio export started for:\n{path}")
        except RuntimeError as exc:
            messagebox.showerror("Export Error", str(exc))
        except Exception as exc:
            messagebox.showerror("Export Error", f"Could not start export:\n{exc}")

    # --- ABOUT THE APPLICATION ---
    def show_about_dialog(self) -> None:
        """
        First open the Audio Settings dialog (to adjust speed & volume live),
        then show the About information.
        """
        dlg = AudioSettingsDialog(self)
        self.wait_window(dlg)

        messagebox.showinfo(
            "About Text-to-Speech App",
            "Text-to-Speech App\n\n"
            "Type or open text, adjust speed and volume, and click Play.\n"
            "You can also export audio as WAV, MP3, or OGG.\n\n"
            "This application demonstrates Python, Tkinter, threading,\n"
            "dialog boxes, and text-to-speech integration."
        )


# --- AUDIO SETTINGS DIALOG (LIVE SPEED + VOLUME) ---

class AudioSettingsDialog(tk.Toplevel):
    """
    Dialog that allows changing TTS speed and volume LIVE.
    Updates apply immediately while text is being read.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Audio Settings")
        self.transient(parent)
        self.resizable(False, False)
        self.grab_set()

        # Store original values so Cancel can restore them
        self.original_speed = getattr(parent, "current_speed", 180)
        self.original_volume = getattr(parent, "current_volume", 0.5)

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        # ---- SPEED ----
        ttk.Label(body, text="Reading Speed (WPM):").grid(row=0, column=0, sticky="w")
        
        self.speed_var = tk.IntVar(value=self.original_speed)
        self.speed_scale = ttk.Scale(
            body,
            from_=80,
            to=300,
            orient="horizontal",
            length=240,
            command=self._on_speed_change
        )
        self.speed_scale.set(self.original_speed)
        self.speed_scale.grid(row=1, column=0, sticky="we", pady=(4, 10))

        self.speed_label = ttk.Label(body, text=str(self.original_speed))
        self.speed_label.grid(row=1, column=1, sticky="w", padx=6)

        # ---- VOLUME ----
        ttk.Label(body, text="Volume:").grid(row=2, column=0, sticky="w")

        self.volume_var = tk.DoubleVar(value=self.original_volume)
        self.volume_scale = ttk.Scale(
            body,
            from_=0.0,
            to=1.0,
            orient="horizontal",
            length=240,
            command=self._on_volume_change
        )
        self.volume_scale.set(self.original_volume)
        self.volume_scale.grid(row=3, column=0, sticky="we", pady=(4, 10))

        self.volume_label = ttk.Label(body, text=f"{self.original_volume:.2f}")
        self.volume_label.grid(row=3, column=1, sticky="w", padx=6)

        # ---- BUTTONS ----
        button_frame = ttk.Frame(body)
        button_frame.grid(row=4, column=0, columnspan=2, sticky="e")

        ttk.Button(button_frame, text="Cancel", command=self._cancel).pack(side="right")
        ttk.Button(button_frame, text="OK", command=self._ok).pack(side="right", padx=(0, 8))

        # Window position
        self.update_idletasks()
        px = parent.winfo_rootx() + 80
        py = parent.winfo_rooty() + 80
        self.geometry(f"+{px}+{py}")

    # ---- LIVE UPDATE HANDLERS ----

    def _on_speed_change(self, value):
        """Apply new speed immediately."""
        speed = int(float(value))
        self.speed_var.set(speed)
        self.speed_label.config(text=str(speed))

        # Update parent + engine live
        if hasattr(self.parent, "current_speed"):
            self.parent.current_speed = speed
        if hasattr(self.parent, "tts"):
            self.parent.tts.set_rate(speed)

        # Update main window UI
        if hasattr(self.parent, "speed_scale"):
            self.parent.speed_scale.set(speed)
        if hasattr(self.parent, "speed_var"):
            self.parent.speed_var.set(speed)
        if hasattr(self.parent, "speed_label"):
            self.parent.speed_label.config(text=str(speed))

    def _on_volume_change(self, value):
        """Apply new volume immediately."""
        volume = float(value)
        self.volume_var.set(volume)
        self.volume_label.config(text=f"{volume:.2f}")

        # Update parent + engine live
        if hasattr(self.parent, "current_volume"):
            self.parent.current_volume = volume
        if hasattr(self.parent, "tts"):
            self.parent.tts.set_volume(volume)

        # Update main window UI
        if hasattr(self.parent, "volume_slider"):
            self.parent.volume_slider.set(volume)
        if hasattr(self.parent, "volume_var"):
            self.parent.volume_var.set(volume)
        if hasattr(self.parent, "volume_label"):
            self.parent.volume_label.config(text=f"{volume:.2f}")

    # ---- OK / CANCEL ----

    def _ok(self):
        """Keep changes."""
        self.grab_release()
        self.destroy()

    def _cancel(self):
        """Restore original settings and close."""
        # Restore speed
        if hasattr(self.parent, "current_speed"):
            self.parent.current_speed = self.original_speed
        if hasattr(self.parent, "tts"):
            self.parent.tts.set_rate(self.original_speed)
        if hasattr(self.parent, "speed_var"):
            self.parent.speed_var.set(self.original_speed)
        if hasattr(self.parent, "speed_scale"):
            self.parent.speed_scale.set(self.original_speed)
        if hasattr(self.parent, "speed_label"):
            self.parent.speed_label.config(text=str(self.original_speed))

        # Restore volume
        if hasattr(self.parent, "current_volume"):
            self.parent.current_volume = self.original_volume
        if hasattr(self.parent, "tts"):
            self.parent.tts.set_volume(self.original_volume)
        if hasattr(self.parent, "volume_slider"):
            self.parent.volume_slider.set(self.original_volume)
        if hasattr(self.parent, "volume_label"):
            self.parent.volume_label.config(text=f"{self.original_volume:.2f}")

        self.grab_release()
        self.destroy()


# ============================================================
# SEGMENT 4: CHANGE SPEED (LOGIC + UI HOOKS)
# ============================================================

class SpeedControlMixin:
    """
    Mixin for changing TTS speed.

    Expects:
    - self.tts (TTSEngine)
    - self._set_status()
    - method open_settings_wizard() to show the SettingsWizard
    """

    def open_settings_wizard(self) -> None:
        """Open the settings wizard (speed + font size)."""
        dlg = SettingsWizard(self, self.current_font_size)
        self.wait_window(dlg)
        if dlg.result:
            size = dlg.result
            self.current_font_size = size
            self.text_font.configure(size=size)
            self.text.configure(font=self.text_font)
            self._set_status(f"Updated settings (font={size}pt).")


# ============================================================
# SEGMENT 1: MAIN WINDOW
#   - CLEAR TEXT
#   - PLAY BUTTON
#   - REWIND BUTTON
#   (Plus menus wired to the other segments)
# ============================================================

class TextToSpeechApp(tk.Tk, DialogMixin, SpeedControlMixin):
    """Main window of the Text-to-Speech app."""

    def __init__(self) -> None:
        tk.Tk.__init__(self)
        self.title("Text-to-Speech App")
        self.geometry("650x750")

        # State
        self.tts = TTSEngine(on_volume_change=self.update_volume_display)

        self.current_text_path: Optional[str] = None
        self.current_speed: int = 180
        self.current_font_size: int = 12
        self.result: Optional[tuple[int, int]] = None
        self.current_volume: int = .5

        # Font for the text widget
        family = "Consolas" if sys.platform == "win32" else "Menlo"
        self.text_font = tkfont.Font(family=family, size=self.current_font_size)

        # Build main UI
        self._build_menubar()
        self._build_toolbar()
        self._build_text_area()
        self._build_status_bar()
        self._build_context_menu()

        # Apply initial speed
        self.apply_speed(self.current_speed)

        # Speed controls
        ttk.Label(self, text="Reading Speed:").pack(padx=1, pady=1)
        self.speed_var = tk.IntVar(value=self.current_speed)
        self.speed_scale = ttk.Scale(self, from_=80, to=300, orient="horizontal", length=240, command=self._on_speed_change)
        self.speed_scale.set(self.current_speed)
        self.speed_scale.pack(padx=0, pady=0)
        self.speed_label = ttk.Label(self, text=str(self.current_speed))
        self.speed_label.pack(padx=0, pady=1)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        #Volume Controls
        ttk.Label(self, text="Volume:").pack(padx=1, pady=1)
        self.volume_var = tk.DoubleVar(value=self.current_volume)
        self.volume_slider = ttk.Scale(self, from_=0.0, to=1.0, orient="horizontal", length=240, command=self.tts.set_volume)
        self.volume_slider.pack(padx=0, pady=0)

        self.volume_label = ttk.Label(self, text=self.current_volume)
        self.volume_label.pack(padx=0, pady=1)

    # ---------- BUILDING MAIN WINDOW WIDGETS ----------
    def _build_menubar(self) -> None:
        menu = tk.Menu(self)
        self.config(menu=menu)

        # File (uses DialogMixin for open/save audio)
        m_file = tk.Menu(menu, tearoff=False)
        m_file.add_command(label="New", command=self.clear_text)
        m_file.add_command(label="Open Text...", command=self.open_text_file)
        m_file.add_command(label="Save Audio...", command=self.save_audio_file)
        m_file.add_command(label="Exit", command=self.on_close)
        menu.add_cascade(label="File", menu=m_file)

        # Edit
        m_edit = tk.Menu(menu, tearoff=False)
        m_edit.add_command(label="Clear Text", command=self.clear_text)
        m_edit.add_command(label="Cut", command=lambda: self.text.event_generate("<<Cut>>"))
        m_edit.add_command(label="Copy", command=lambda: self.text.event_generate("<<Copy>>"))
        m_edit.add_command(label="Paste", command=lambda: self.text.event_generate("<<Paste>>"))
        menu.add_cascade(label="Edit", menu=m_edit)

        # Settings (Speed + font)
        m_settings = tk.Menu(menu, tearoff=False)
        m_settings.add_command(label="Font Size", command=self.open_settings_wizard)
        menu.add_cascade(label="Settings", menu=m_settings)

        # Help (Wizard + About)
        m_help = tk.Menu(menu, tearoff=False)
        m_help.add_command(label="Wizard...", command=self.open_help_wizard)
        m_help.add_separator()
        m_help.add_command(label="About", command=self.show_about_dialog)
        menu.add_cascade(label="Help", menu=m_help)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(8, 4))
        bar.pack(side="top", fill="x")

        # Clear text
        ttk.Button(bar, text="Clear Text", command=self.clear_text).pack(side="left")
        # Play / Stop / Rewind
        ttk.Button(bar, text="Play", command=self.play_text).pack(side="left")
        ttk.Button(bar, text="Stop", command=self.stop_playback).pack(side="left", padx=(4, 0))
        ttk.Button(bar, text="Rewind", command=self.rewind_text).pack(side="left", padx=(4, 0))
        ttk.Button(bar, text="Set Speed", command=self._ok_speed).pack(side="left", padx=(0, 8))

    def _build_text_area(self) -> None:
        frame = ttk.Frame(self, padding=(8, 4))
        frame.pack(expand=True, fill="both")

        yscroll = ttk.Scrollbar(frame, orient="vertical")
        xscroll = ttk.Scrollbar(frame, orient="horizontal")

        self.text = tk.Text(frame, wrap="none", undo=True, maxundo=-1, font=self.text_font,)
        self.text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        yscroll.configure(command=self.text.yview)
        xscroll.configure(command=self.text.xview)

        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")

    def _build_status_bar(self) -> None:
        self.status_label = ttk.Label(self, text="", anchor="w", padding=(8, 4))
        self.status_label.pack(side="bottom", fill="x")

    def _build_context_menu(self) -> None:
        self.context = tk.Menu(self, tearoff=False)
        self.context.add_command(label="Cut", command=lambda: self.text.event_generate("<<Cut>>"))
        self.context.add_command(label="Copy", command=lambda: self.text.event_generate("<<Copy>>"))
        self.context.add_command(label="Paste", command=lambda: self.text.event_generate("<<Paste>>"))
        self.context.add_separator()
        self.context.add_command(label="Clear Text", command=self.clear_text)

        def show_context(event: tk.Event) -> None:
            try:
                self.context.tk_popup(event.x_root, event.y_root)
            finally:
                self.context.grab_release()

        self.text.bind("<Button-3>", show_context)
        self.text.bind("<Button-2>", show_context)  # some mac configs

    # ---------- MAIN WINDOW ACTIONS (CLEAR / PLAY / REWIND) ----------
    def _on_speed_change(self, _val: str) -> None:
        self.speed_var.set(int(float(self.speed_scale.get())))
        self.speed_label.configure(text=str(self.speed_var.get()))
    
    def update_volume_display(self, value: float):
        """Show TTS volume output inside the GUI."""
        self.volume_label.config(text=f"{value:.2f}")

    def apply_speed(self, speed: int) -> None:
        """Apply speed to TTS engine and update status."""
        self.current_speed = speed
        self.tts.set_rate(speed)
        self._set_status(f"Speed set to {speed} words per minute.")

    def _ok_speed(self) -> None:
        try:
            speed = int(self.speed_var.get())
        except Exception:
            speed = 180
        self.result = (speed)
        self.grab_release()
        self.apply_speed(speed)

    def clear_text(self) -> None:
        """Clear all text from the main text box."""
        self.text.delete("1.0", "end")
        self._set_status("Text cleared.")

    def play_text(self) -> None:
        """Play text using the TTS engine."""
        content = self.text.get("1.0", "end-1c").strip()
        if not content:
            messagebox.showwarning("No Text", "Please enter or open text before playing.")
            return
        self.tts.set_rate(self.current_speed)  # ensure speed is applied
        self.tts.speak(content)
        self._set_status("Playing text...")

    def stop_playback(self) -> None:
        """Stop current playback."""
        self.tts.stop()
        self._set_status("Playback stopped.")

    def rewind_text(self) -> None:
        """Stop playback and move cursor to start of text."""
        self.stop_playback()
        self.text.mark_set("insert", "1.0")
        self.text.see("1.0")
        self._set_status("Rewound to start.")

    # ---------- HELP / WIZARD ----------

    def open_help_wizard(self) -> None:
        """Open a simple wizard explaining how to use the app."""
        WizardDialog(self)

    # ---------- UTILITY / STATUS / CLOSE ----------

    def _set_status(self, msg: str) -> None:
        self.status_label.configure(text=f"Status: {msg}")

    def on_close(self) -> None:
        try:
            self.tts.shutdown()
        except Exception:
            pass
        self.destroy()


# Simple wizard dialog that explains the steps.
class WizardDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk) -> None:
        super().__init__(parent)
        self.title("Wizard — How to use this app")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        steps = [
            "Step 1: Type or paste text into the main text area, or open a text file.",
            "Step 2: Use Settings to adjust speed and font size if needed.",
            "Step 3: Click Play to listen, Rewind to jump back to the start.",
            "Step 4: Use 'Save Audio...' to export your text as an audio file.",
        ]

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        label = ttk.Label(body, wraplength=380, justify="left",
                          text="\n\n".join(steps))
        label.grid(row=0, column=0, sticky="w")

        ttk.Button(body, text="Close", command=self._close).grid(row=1, column=0, sticky="e", pady=(12, 0))

        self.bind("<Escape>", lambda e: self._close())
        self.update_idletasks()
        self.geometry(f"+{parent.winfo_rootx()+80}+{parent.winfo_rooty()+80}")

    def _close(self) -> None:
        self.grab_release()
        self.destroy()


# ============================================================
# ENTRY POINT
# ============================================================

def main() -> None:
    app = TextToSpeechApp()
    app.mainloop()


if __name__ == "__main__":
    main()
