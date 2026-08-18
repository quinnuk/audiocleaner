"""
Minimal GUI: a list of folders (add/remove as many as you like — they
don't need a shared parent), Start/Watch buttons, progress, status log,
completion summary, Open Log button.

Also supports:
  - Persisting the folder list + settle time between sessions (QSettings)
  - "Start with Windows" checkbox (HKCU Run key, see autostart.py)
  - Minimising to the system tray instead of quitting on close
  - A --minimized launch mode (used by the autostart entry) that skips
    showing the window and auto-resumes watching the saved folders
  - Single-instance enforcement: launching a second copy brings the
    existing window to front instead of starting a duplicate
"""

import os
import platform
import subprocess
import sys
import time
import traceback
import webbrowser
import functools
from pathlib import Path

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QIcon, QColor, QTextCharFormat, QTextCursor
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QPlainTextEdit, QFileDialog, QMessageBox,
    QGroupBox, QFormLayout, QSpinBox, QFrame, QListWidget, QCheckBox,
    QSystemTrayIcon, QMenu, QStyle, QScrollArea,
    QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QLineEdit,
)

from .config import (
    APP_NAME, LOG_FILENAME, CODEC_LABELS, WATCH_DEFAULT_SETTLE_SECONDS,
    DEFAULT_KEEP_COMMENTARY, DEFAULT_SUBTITLE_FILTER_ENABLED, DEFAULT_SUBTITLE_LANGUAGES,
    DEFAULT_MAX_SAFETY_MODE, DEFAULT_PERSISTENT_BACKUP, CACHE_FILENAME,
    DEFAULT_REMUX_STALL_TIMEOUT_SECONDS,
)
from .worker import CleanerWorker, WatchWorker, LanguageScanWorker
from .probe import check_tools_available, get_missing_tools
from .history import ProcessingHistory
from . import autostart

# Friendly display names for subtitle-language checkboxes. Falls back to
# the raw ISO code for anything not listed here.
_LANGUAGE_NAMES = {
    "eng": "English", "ger": "German", "deu": "German", "fre": "French",
    "fra": "French", "spa": "Spanish", "ita": "Italian", "jpn": "Japanese",
    "chi": "Chinese", "zho": "Chinese", "kor": "Korean", "rus": "Russian",
    "por": "Portuguese", "dut": "Dutch", "nld": "Dutch", "swe": "Swedish",
    "nor": "Norwegian", "dan": "Danish", "fin": "Finnish", "pol": "Polish",
    "tur": "Turkish", "ara": "Arabic", "heb": "Hebrew", "hin": "Hindi",
    "tha": "Thai", "vie": "Vietnamese", "cze": "Czech", "ces": "Czech",
    "hun": "Hungarian", "gre": "Greek", "ell": "Greek", "rum": "Romanian",
    "ron": "Romanian", "bul": "Bulgarian", "hrv": "Croatian", "srp": "Serbian",
    "slo": "Slovak", "slk": "Slovak", "slv": "Slovenian", "ukr": "Ukrainian",
    "und": "Undetermined",
}


def _language_label(code: str) -> str:
    code = (code or "und").lower()
    name = _LANGUAGE_NAMES.get(code)
    return f"{name} ({code})" if name else code

# Name of the local IPC server used to detect an already-running instance
# and ask it to show itself, instead of starting a second copy that could
# end up watching/remuxing the same folder at the same time.
_SINGLE_INSTANCE_SERVER_NAME = f"{APP_NAME}-SingleInstance"

# Colour used for each result status in the status log (None = default
# text colour, used for plain informational lines like heartbeats).
_STATUS_COLORS = {
    "cleaned": QColor("#2e7d32"),               # green
    "error": QColor("#c62828"),                 # red
    "no_english": QColor("#b8860b"),             # amber
    "unknown_codec": QColor("#b8860b"),         # amber - same "skipped, not an error" tone
    "skipped_single_track": QColor("#6b6b6b"),  # muted grey
}

# --- App theme ---
# Drawn from the actual app icon (audio_cleaner_icon.ico): a deep
# indigo-to-purple gradient behind a cyan waveform, with a small gold
# sparkle accent. Before this, the GUI had no palette of its own at all --
# every widget just inherited whatever bare default the OS/Qt style
# happened to supply, and the icon's colours appeared nowhere else in the
# app. This ties the window to the icon instead of looking unrelated to it.
_ACCENT = "#5b2fa8"          # primary accent -- punchier version of the icon's mid-gradient purple
_ACCENT_HOVER = "#7040c4"
_ACCENT_PRESSED = "#41217a"
_ACCENT_DISABLED = "#c3b3e6"
_ACCENT_SOFT = "#efe6fb"     # very light tint of the accent, for hover states

# Second accent for Start Watching, deliberately distinct from _ACCENT
# (Start) -- pulled from the icon's cyan waveform. Start and Start
# Watching are both primary actions but different in kind (a one-off run
# vs an indefinite background mode); giving them the same colour made
# them too easy to mix up at a glance.
_WATCH_ACCENT = "#0f8fa8"
_WATCH_ACCENT_HOVER = "#12a8c4"
_WATCH_ACCENT_PRESSED = "#0b6b7d"
_WATCH_ACCENT_DISABLED = "#a9d3da"

_APP_STYLESHEET = f"""
QWidget {{
    background-color: #f6f5fa;
    color: #262233;
}}
QGroupBox {{
    border: 1px solid #d8d2ea;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: 600;
    color: {_ACCENT};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QPushButton {{
    background-color: #ffffff;
    border: 1px solid #c9c1e0;
    border-radius: 5px;
    padding: 5px 14px;
}}
QPushButton:hover {{
    background-color: {_ACCENT_SOFT};
}}
QPushButton:pressed {{
    background-color: #ddc9f5;
}}
QPushButton:disabled {{
    color: #a49bb8;
    background-color: #f0eef5;
    border-color: #ded9ea;
}}
/* Primary call-to-action button: Start -- the one-off "run now" action. */
QPushButton#primaryButton {{
    background-color: {_ACCENT};
    color: #ffffff;
    border: 1px solid {_ACCENT_PRESSED};
    font-weight: 600;
    padding: 6px 16px;
}}
QPushButton#primaryButton:hover {{
    background-color: {_ACCENT_HOVER};
}}
QPushButton#primaryButton:pressed, QPushButton#primaryButton:checked {{
    background-color: {_ACCENT_PRESSED};
}}
QPushButton#primaryButton:disabled {{
    background-color: {_ACCENT_DISABLED};
    color: #f2effa;
    border-color: {_ACCENT_DISABLED};
}}
/* Start Watching -- deliberately a different colour from Start (see
   _WATCH_ACCENT above for why). */
QPushButton#watchButton {{
    background-color: {_WATCH_ACCENT};
    color: #ffffff;
    border: 1px solid {_WATCH_ACCENT_PRESSED};
    font-weight: 600;
    padding: 6px 16px;
}}
QPushButton#watchButton:hover {{
    background-color: {_WATCH_ACCENT_HOVER};
}}
QPushButton#watchButton:pressed, QPushButton#watchButton:checked {{
    background-color: {_WATCH_ACCENT_PRESSED};
}}
QPushButton#watchButton:disabled {{
    background-color: {_WATCH_ACCENT_DISABLED};
    color: #eefbfd;
    border-color: {_WATCH_ACCENT_DISABLED};
}}
QPlainTextEdit, QTableWidget, QListWidget, QLineEdit, QComboBox, QSpinBox {{
    background-color: #ffffff;
    border: 1px solid #d8d2ea;
    border-radius: 4px;
    selection-background-color: {_ACCENT};
    selection-color: #ffffff;
}}
QLineEdit, QComboBox, QSpinBox {{
    padding: 3px 6px;
}}
QHeaderView::section {{
    background-color: #eeeaf7;
    border: none;
    border-bottom: 1px solid #d8d2ea;
    padding: 4px 6px;
    font-weight: 600;
    color: {_ACCENT};
}}
QProgressBar {{
    border: 1px solid #d8d2ea;
    border-radius: 4px;
    text-align: center;
    background-color: #ffffff;
}}
QProgressBar::chunk {{
    background-color: {_ACCENT};
    border-radius: 3px;
}}
QCheckBox::indicator:checked {{
    background-color: {_ACCENT};
    border: 1px solid {_ACCENT_PRESSED};
}}
QScrollArea {{
    border: none;
}}
"""


def _apply_theme(app: QApplication) -> None:
    """Fusion renders QSS reliably across platforms (the native Windows
    style largely ignores palette/stylesheet colour overrides for several
    widgets) so this is applied before the stylesheet, giving the app a
    consistent look tied to its own icon instead of an unstyled default."""
    app.setStyle("Fusion")
    app.setStyleSheet(_APP_STYLESHEET)


def _install_global_excepthook():
    """
    PySide6 slots are frequently invoked from C++ (any signal delivered
    across threads -- which is every CleanerWorker/WatchWorker/
    LanguageScanWorker signal, since each runs on its own QThread -- is
    queued and dispatched this way even though the slot itself is plain
    Python). If a Python exception escapes one of those slots uncaught, it
    can't be propagated back through the C++ call stack; PySide6's default
    behaviour in that situation is to abort the whole process outright --
    no traceback window, no crash dialog, especially not in a windowed
    (console=False) PyInstaller build where there's no console to print to
    in the first place. From the user's side this looks exactly like the
    app just closing itself for no reason, often right as the first batch
    of progress/status signals start arriving after clicking Start.

    Installing a top-level excepthook is defence in depth: every
    individual worker-signal handler below is also wrapped with
    @_safe_slot so exceptions are caught before they ever reach this
    point, but this still catches anything outside those (or in
    @_safe_slot itself) instead of silently killing the app.
    """
    def _hook(exc_type, exc_value, exc_tb):
        message = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        sys.stderr.write(message)
        try:
            app = QApplication.instance()
            QMessageBox.critical(
                app.activeWindow() if app else None,
                APP_NAME,
                "AudioCleaner hit an unexpected internal error and had to stop "
                f"what it was doing, but is still running:\n\n{exc_value}",
            )
        except Exception:
            pass  # the error dialog itself must never be what brings the app down
    sys.excepthook = _hook


def _safe_slot(func):
    """
    Wraps a Qt slot method so an exception inside it is caught, logged,
    and shown to the user via a message box instead of propagating back
    into PySide6/Qt's C++ layer -- see _install_global_excepthook() above
    for why that matters. Applied to every method connected to a
    CleanerWorker/WatchWorker/LanguageScanWorker signal, since those are
    exactly the cross-thread-delivered slots where this failure mode
    happens.
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            traceback.print_exc()
            try:
                QMessageBox.critical(
                    self, APP_NAME,
                    f"AudioCleaner hit an unexpected internal error in "
                    f"{func.__name__} and had to stop what it was doing, but "
                    f"is still running:\n\n{e}",
                )
            except Exception:
                pass
    return wrapper


def _icon_path() -> str | None:
    """Locate the bundled app icon, whether running frozen (PyInstaller
    one-file, extracted to sys._MEIPASS at runtime) or from source (sitting
    in the project root during development)."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    candidate = base / "audio_cleaner_icon.ico"
    return str(candidate) if candidate.is_file() else None


class HistoryDialog(QDialog):
    """Processing History view (spec sec 25): a table of what AudioCleaner
    has done, across every folder and run, backed by history.ProcessingHistory.
    Supports filtering by result and opening the containing folder for any
    entry."""

    _STATUS_FILTERS = ["All", "cleaned", "skipped_single_track", "no_english",
                        "unknown_codec", "error"]
    _STATUS_DISPLAY = {
        "cleaned": "Cleaned", "skipped_single_track": "Already OK",
        "no_english": "No English audio", "unknown_codec": "Unknown format",
        "error": "Error", "All": "All",
    }

    def __init__(self, history: ProcessingHistory, parent=None):
        super().__init__(parent)
        self.history = history
        self._file_filter_path: str | None = None
        self.setWindowTitle(f"{APP_NAME} — Processing History")
        self.resize(900, 500)

        layout = QVBoxLayout(self)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Show:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems([self._STATUS_DISPLAY[s] for s in self._STATUS_FILTERS])
        self.filter_combo.currentIndexChanged.connect(self._reload)
        filter_row.addWidget(self.filter_combo)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search filename or path…")
        self.search_edit.textChanged.connect(self._reload)
        filter_row.addWidget(self.search_edit)
        filter_row.addStretch()
        self.summary_label = QLabel("")
        filter_row.addWidget(self.summary_label)
        layout.addLayout(filter_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Date", "File", "Folder", "Result", "Saved", "Details"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemDoubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.open_folder_btn = QPushButton("Open Containing Folder")
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        btn_row.addWidget(self.open_folder_btn)
        self.file_history_btn = QPushButton("History For This File Only")
        self.file_history_btn.setToolTip(
            "Show every entry recorded for the selected row's exact file path, "
            "across every folder and run -- double-clicking a row does the same thing."
        )
        self.file_history_btn.clicked.connect(self._on_filter_to_selected_file)
        btn_row.addWidget(self.file_history_btn)
        self.clear_file_filter_btn = QPushButton("Clear File Filter")
        self.clear_file_filter_btn.setVisible(False)
        self.clear_file_filter_btn.clicked.connect(self._on_clear_file_filter)
        btn_row.addWidget(self.clear_file_filter_btn)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._reload()

    def _selected_full_path(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 1)
        return item.data(Qt.UserRole) if item else None

    def _on_row_double_clicked(self, _item):
        self._on_filter_to_selected_file()

    def _on_filter_to_selected_file(self):
        full_path = self._selected_full_path()
        if not full_path:
            QMessageBox.information(self, APP_NAME, "Select an entry first.")
            return
        self._file_filter_path = full_path
        self.filter_combo.setEnabled(False)
        self.search_edit.setEnabled(False)
        self.clear_file_filter_btn.setVisible(True)
        self._reload()

    def _on_clear_file_filter(self):
        self._file_filter_path = None
        self.filter_combo.setEnabled(True)
        self.search_edit.setEnabled(True)
        self.clear_file_filter_btn.setVisible(False)
        self._reload()

    def _reload(self):
        if self._file_filter_path:
            # "What did AudioCleaner do to this exact file, ever" --
            # history.ProcessingHistory.for_path() is built exactly for
            # this and is an exact-path match (unlike search(), which is a
            # substring match that could pull in a different file that
            # happens to share part of its name).
            entries = self.history.for_path(self._file_filter_path, limit=500)
        else:
            status_filter = self._STATUS_FILTERS[self.filter_combo.currentIndex()]
            status_filter = None if status_filter == "All" else status_filter
            search_term = self.search_edit.text().strip()
            if search_term:
                entries = self.history.search(search_term, limit=500, status_filter=status_filter)
            else:
                entries = self.history.recent(limit=500, status_filter=status_filter)
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            name = Path(entry.path).name
            saved = _format_bytes(entry.bytes_saved) if entry.status == "cleaned" and not entry.preview else "—"
            result_text = self._STATUS_DISPLAY.get(entry.status, entry.status)
            if entry.preview:
                result_text += " (preview)"
            details = entry.message or (CODEC_LABELS.get(entry.kept_codec, entry.kept_codec) if entry.kept_codec else "")

            self.table.setItem(row, 0, QTableWidgetItem(_format_timestamp(entry.timestamp)))
            self.table.setItem(row, 1, QTableWidgetItem(name))
            self.table.setItem(row, 2, QTableWidgetItem(entry.folder))
            self.table.setItem(row, 3, QTableWidgetItem(result_text))
            self.table.setItem(row, 4, QTableWidgetItem(saved))
            self.table.setItem(row, 5, QTableWidgetItem(details))
            # Stash the full path for "Open Containing Folder" / file filter.
            self.table.item(row, 1).setData(Qt.UserRole, entry.path)

        if self._file_filter_path:
            self.summary_label.setText(
                f"History for {Path(self._file_filter_path).name}: {len(entries)} entr"
                f"{'y' if len(entries) == 1 else 'ies'}"
            )
        else:
            totals = self.history.library_totals()
            self.summary_label.setText(
                f"{totals['files_cleaned']} file(s) cleaned overall — "
                f"{_format_bytes(totals['bytes_saved'])} recovered"
            )

    def _on_open_folder(self):
        full_path = self._selected_full_path()
        if not full_path:
            QMessageBox.information(self, APP_NAME, "Select an entry first.")
            return
        folder = Path(full_path).parent
        if not folder.exists():
            QMessageBox.warning(self, APP_NAME, f"Folder no longer exists:\n{folder}")
            return
        if os.name == "nt":
            os.startfile(folder)  # noqa: S606 - intended, opens Explorer
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)])
        else:
            subprocess.run(["xdg-open", str(folder)])


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(700, 640)

        icon_path = _icon_path()
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

        self.settings = QSettings()

        self.worker: CleanerWorker | None = None
        self.watch_workers: list[WatchWorker] = []
        self.selected_roots: list[Path] = []
        self._start_time: float | None = None
        self._watch_processed_count = 0
        self.tray_icon: QSystemTrayIcon | None = None
        self.language_scan_worker: LanguageScanWorker | None = None
        # Subtitle languages the user has checked, persisted across
        # sessions even before the checklist widget has been populated by
        # a scan in the current session (e.g. a --minimized autostart run).
        self._saved_subtitle_languages: set = set(DEFAULT_SUBTITLE_LANGUAGES)
        self._lang_checkboxes: dict[str, QCheckBox] = {}

        # Multi-folder manual-run queue state
        self._run_queue: list[Path] = []
        self._run_totals = {
            "total_scanned": 0, "cleaned": 0, "skipped_single_track": 0,
            "no_english": 0, "unknown_codec": 0, "errors": 0, "total_removed_tracks": 0,
            "total_removed_subtitle_tracks": 0,
            "total_bytes_saved": 0, "elapsed_seconds": 0.0,
        }
        self._run_folder_index = 0
        self._run_folder_count = 0
        self._run_was_preview = False
        # Retry Errors support: which root each currently-processing file
        # belongs to (set each time a folder is popped from the queue),
        # the list of (root, file_path) pairs that errored on the most
        # recently completed manual run, and a per-root file-list override
        # used to constrain a retry run to just those files instead of a
        # full rescan.
        self._current_run_root: Path | None = None
        self._last_error_paths: list[tuple[Path, Path]] = []
        self._run_only_paths: dict[Path, list[Path]] = {}

        self._deps_ok = False
        self._build_ui()
        self._setup_tray()
        self._load_saved_folders()
        self._check_dependencies()

    # ---------------------------------------------------------- UI layout
    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Dependency warning banner (hidden unless something is missing)
        self.dep_banner = QFrame()
        self.dep_banner.setFrameShape(QFrame.StyledPanel)
        self.dep_banner.setStyleSheet(
            "QFrame { background-color: #fff3cd; border: 1px solid #e0c265; border-radius: 6px; }"
        )
        dep_layout = QVBoxLayout(self.dep_banner)
        self.dep_title = QLabel("")
        self.dep_title.setWordWrap(True)
        self.dep_title.setStyleSheet("font-weight: bold;")
        dep_layout.addWidget(self.dep_title)
        self.dep_buttons_row = QVBoxLayout()
        dep_layout.addLayout(self.dep_buttons_row)
        recheck_row = QHBoxLayout()
        self.dep_recheck_btn = QPushButton("I've installed them — Check Again")
        self.dep_recheck_btn.clicked.connect(self._check_dependencies)
        recheck_row.addWidget(self.dep_recheck_btn)
        recheck_row.addStretch()
        dep_layout.addLayout(recheck_row)
        self.dep_banner.setVisible(False)
        layout.addWidget(self.dep_banner)

        # Folder list
        layout.addWidget(QLabel("Folders to clean / watch (any number, don't need to be related):"))
        self.folder_list = QListWidget()
        self.folder_list.setMaximumHeight(90)
        layout.addWidget(self.folder_list)

        folder_btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Folder…")
        add_btn.clicked.connect(self._on_add_folder)
        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.clicked.connect(self._on_remove_folder)
        folder_btn_row.addWidget(add_btn)
        folder_btn_row.addWidget(self.remove_btn)
        folder_btn_row.addStretch()
        layout.addLayout(folder_btn_row)

        # Start / Cancel row
        action_row = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.clicked.connect(self._on_start)
        self.start_btn.setEnabled(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setEnabled(False)
        self.retry_errors_btn = QPushButton("Retry Errors")
        self.retry_errors_btn.setToolTip(
            "Re-run only the file(s) that failed with an error on the last run, "
            "instead of rescanning everything again."
        )
        self.retry_errors_btn.clicked.connect(self._on_retry_errors)
        self.retry_errors_btn.setEnabled(False)
        action_row.addWidget(self.start_btn)
        action_row.addWidget(self.cancel_btn)
        action_row.addWidget(self.retry_errors_btn)
        layout.addLayout(action_row)

        preview_row = QHBoxLayout()
        self.preview_check = QCheckBox(
            "Preview Only — show what would happen, don't modify any files"
        )
        self.preview_check.toggled.connect(self._save_preview_setting)
        preview_row.addWidget(self.preview_check)
        preview_row.addStretch()
        layout.addLayout(preview_row)

        # Watch mode row -- deliberately a different colour (teal/cyan) from
        # Start (purple): they're both primary actions, but different ones
        # (a one-off run vs an indefinite background mode), and sharing one
        # colour made them easy to mix up at a glance.
        watch_row = QHBoxLayout()
        self.watch_btn = QPushButton("Start Watching All Folders")
        self.watch_btn.setObjectName("watchButton")
        self.watch_btn.setCheckable(True)
        self.watch_btn.clicked.connect(self._on_toggle_watch)
        self.watch_btn.setEnabled(False)
        self.settle_spin = QSpinBox()
        self.settle_spin.setRange(10, 3600)
        self.settle_spin.setSingleStep(10)
        self.settle_spin.setValue(WATCH_DEFAULT_SETTLE_SECONDS)
        self.settle_spin.setSuffix(" s")
        self.settle_spin.valueChanged.connect(self._save_settle)
        watch_row.addWidget(self.watch_btn)
        watch_row.addWidget(QLabel("Wait for new files to finish copying:"))
        watch_row.addWidget(self.settle_spin)
        watch_row.addStretch()
        layout.addLayout(watch_row)

        # Startup behaviour row
        startup_row = QHBoxLayout()
        self.autostart_check = QCheckBox(
            "Start with Windows (minimised to tray, auto-watch saved folders)"
        )
        self.autostart_check.setChecked(autostart.is_enabled())
        self.autostart_check.toggled.connect(self._on_toggle_autostart)
        startup_row.addWidget(self.autostart_check)
        startup_row.addStretch()
        layout.addLayout(startup_row)

        # Safety Options and Audio & Subtitle Options side by side -- this
        # is what keeps the window from being twice as tall as it needs to
        # be while still putting everything on one page (no tabs to
        # switch between to find a setting).
        options_row = QHBoxLayout()
        self._build_safety_options(options_row)
        self._build_audio_subtitle_options(options_row)
        layout.addLayout(options_row)
        self._update_subtitle_controls_enabled()

        # Progress group
        progress_box = QGroupBox("Progress")
        progress_layout = QFormLayout()
        self.current_folder_label = QLabel("—")
        self.current_file_label = QLabel("—")
        self.current_file_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.files_count_label = QLabel("0 of 0")
        self.eta_label = QLabel("—")
        progress_layout.addRow("Current folder:", self.current_folder_label)
        progress_layout.addRow("Current file:", self.current_file_label)
        progress_layout.addRow("Progress:", self.progress_bar)
        progress_layout.addRow("Files processed:", self.files_count_label)
        progress_layout.addRow("Estimated time remaining:", self.eta_label)
        progress_box.setLayout(progress_layout)
        layout.addWidget(progress_box)

        # Status window
        layout.addWidget(QLabel("Status:"))
        self.status_box = QPlainTextEdit()
        self.status_box.setReadOnly(True)
        layout.addWidget(self.status_box, stretch=1)

        # Completion summary
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        # Open log button
        bottom_row = QHBoxLayout()
        self.open_log_btn = QPushButton("Open Log (selected folder)")
        self.open_log_btn.clicked.connect(self._on_open_log)
        self.open_log_btn.setEnabled(False)
        bottom_row.addStretch()
        bottom_row.addWidget(self.open_log_btn)
        layout.addLayout(bottom_row)

    def _build_safety_options(self, parent_row: QHBoxLayout):
        safety_box = QGroupBox("Safety Options")
        safety_layout = QVBoxLayout()

        self.max_safety_check = QCheckBox("Maximum Safety Mode")
        self.max_safety_check.setToolTip(
            "Keeps a full backup until the replaced file is re-verified; "
            "auto-restores the original if that check fails."
        )
        self.max_safety_check.setChecked(DEFAULT_MAX_SAFETY_MODE)
        self.max_safety_check.toggled.connect(self._save_safety_options)
        safety_layout.addWidget(self.max_safety_check)
        max_safety_hint = QLabel(
            "Keeps a full backup until the replaced file is re-verified; "
            "auto-restores the original if that check fails."
        )
        max_safety_hint.setWordWrap(True)
        max_safety_hint.setStyleSheet("color: #666;")
        safety_layout.addWidget(max_safety_hint)

        self.persistent_backup_check = QCheckBox("Keep the backup after a successful clean too")
        self.persistent_backup_check.setToolTip("Uses extra disk space.")
        self.persistent_backup_check.setChecked(DEFAULT_PERSISTENT_BACKUP)
        self.persistent_backup_check.setEnabled(DEFAULT_MAX_SAFETY_MODE)
        self.persistent_backup_check.toggled.connect(self._save_safety_options)
        safety_layout.addWidget(self.persistent_backup_check)

        stall_row = QHBoxLayout()
        stall_label = QLabel("Give up on a file after zero progress for:")
        stall_row.addWidget(stall_label)
        self.stall_timeout_spin = QSpinBox()
        self.stall_timeout_spin.setRange(5, 240)
        self.stall_timeout_spin.setSingleStep(5)
        self.stall_timeout_spin.setValue(DEFAULT_REMUX_STALL_TIMEOUT_SECONDS // 60)
        self.stall_timeout_spin.setSuffix(" min")
        self.stall_timeout_spin.setToolTip(
            "A file that's still making real progress is never affected by this, no "
            "matter how large or slow -- it only fires once mkvmerge's own reported "
            "progress hasn't moved at all for this long. Raise it if your library "
            "lives on a slow, external, or network drive that can legitimately take "
            "a while to wake up or keep up with a large 4K remux."
        )
        self.stall_timeout_spin.valueChanged.connect(self._save_safety_options)
        stall_row.addWidget(self.stall_timeout_spin)
        stall_row.addStretch()
        safety_layout.addLayout(stall_row)

        self.rebuild_cache_btn = QPushButton("Rebuild Cache…")
        self.rebuild_cache_btn.clicked.connect(self._on_rebuild_cache)
        safety_layout.addWidget(self.rebuild_cache_btn)
        rebuild_hint = QLabel(
            "Forces every selected folder to be re-analysed from scratch on the next run. "
            "Does not modify any media file."
        )
        rebuild_hint.setWordWrap(True)
        rebuild_hint.setStyleSheet("color: #666;")
        safety_layout.addWidget(rebuild_hint)

        self.history_btn = QPushButton("Processing History…")
        self.history_btn.clicked.connect(self._on_show_history)
        safety_layout.addWidget(self.history_btn)
        history_hint = QLabel("What AudioCleaner has done, across every folder and run.")
        history_hint.setWordWrap(True)
        history_hint.setStyleSheet("color: #666;")
        safety_layout.addWidget(history_hint)

        safety_layout.addStretch()
        safety_box.setLayout(safety_layout)
        parent_row.addWidget(safety_box, stretch=1)

    def _build_audio_subtitle_options(self, parent_row: QHBoxLayout):
        # Audio & subtitle options
        options_box = QGroupBox("Audio && Subtitle Options")
        options_layout = QVBoxLayout()

        self.keep_commentary_check = QCheckBox("Keep commentary tracks")
        self.keep_commentary_check.setToolTip(
            "Default: removed like any other extra audio track."
        )
        self.keep_commentary_check.setChecked(DEFAULT_KEEP_COMMENTARY)
        self.keep_commentary_check.toggled.connect(self._save_audio_subtitle_options)
        options_layout.addWidget(self.keep_commentary_check)
        commentary_hint = QLabel("Default: removed like any other extra audio track.")
        commentary_hint.setWordWrap(True)
        commentary_hint.setStyleSheet("color: #666;")
        options_layout.addWidget(commentary_hint)

        self.subtitle_filter_check = QCheckBox("Also clean subtitle tracks")
        self.subtitle_filter_check.setToolTip(
            "Keep only checked languages below, plus any Forced tracks."
        )
        self.subtitle_filter_check.setChecked(DEFAULT_SUBTITLE_FILTER_ENABLED)
        self.subtitle_filter_check.toggled.connect(self._on_toggle_subtitle_filter)
        options_layout.addWidget(self.subtitle_filter_check)
        subtitle_hint = QLabel("Keeps only checked languages below, plus any Forced tracks.")
        subtitle_hint.setWordWrap(True)
        subtitle_hint.setStyleSheet("color: #666;")
        options_layout.addWidget(subtitle_hint)

        self.scan_languages_btn = QPushButton("Scan Folders for Subtitle Languages…")
        self.scan_languages_btn.clicked.connect(self._on_scan_languages)
        options_layout.addWidget(self.scan_languages_btn)

        self.lang_scroll = QScrollArea()
        self.lang_scroll.setWidgetResizable(True)
        self.lang_scroll.setMaximumHeight(90)
        self.lang_checklist_widget = QWidget()
        self.lang_checklist_layout = QVBoxLayout(self.lang_checklist_widget)
        self.lang_checklist_placeholder = QLabel(
            "Scan folders above to see which subtitle languages are actually present."
        )
        self.lang_checklist_placeholder.setWordWrap(True)
        self.lang_checklist_placeholder.setStyleSheet("color: #666;")
        self.lang_checklist_layout.addWidget(self.lang_checklist_placeholder)
        self.lang_checklist_layout.addStretch()
        self.lang_scroll.setWidget(self.lang_checklist_widget)
        options_layout.addWidget(self.lang_scroll)

        options_layout.addStretch()
        options_box.setLayout(options_layout)
        parent_row.addWidget(options_box, stretch=1)

    def _check_dependencies(self):
        missing = get_missing_tools()
        self._deps_ok = len(missing) == 0

        while self.dep_buttons_row.count():
            item = self.dep_buttons_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if missing:
            names = " and ".join(m["label"] for m in missing)
            self.dep_title.setText(
                f"⚠ AudioCleaner needs {names} installed first. "
                "Click below to download, install it, then click \"Check Again\"."
            )
            for m in missing:
                btn = QPushButton(f"Download {m['label']}")
                url = m["download_url"]
                btn.clicked.connect(lambda checked=False, u=url: webbrowser.open(u))
                self.dep_buttons_row.addWidget(btn)
                hint_label = QLabel(f"   {m['hint']}")
                hint_label.setStyleSheet("color: #555;")
                self.dep_buttons_row.addWidget(hint_label)
            self.dep_banner.setVisible(True)
        else:
            self.dep_banner.setVisible(False)

        self._update_action_buttons_enabled()

    def _update_action_buttons_enabled(self):
        ready = self._deps_ok and len(self.selected_roots) > 0
        self.start_btn.setEnabled(ready)
        self.watch_btn.setEnabled(ready)
        self.open_log_btn.setEnabled(len(self.selected_roots) > 0)

    # ---------------------------------------------------------- persistence
    def _load_saved_folders(self):
        saved = self.settings.value("folders", [])
        if isinstance(saved, str):  # QSettings can collapse a 1-item list to a bare string
            saved = [saved]
        for p in saved:
            path = Path(p)
            if path.exists() and path not in self.selected_roots:
                self.selected_roots.append(path)
                self.folder_list.addItem(str(path))

        settle = self.settings.value("settle_seconds", None)
        if settle is not None:
            self.settle_spin.blockSignals(True)
            self.settle_spin.setValue(int(settle))
            self.settle_spin.blockSignals(False)

        keep_commentary = self.settings.value("keep_commentary", DEFAULT_KEEP_COMMENTARY, type=bool)
        self.keep_commentary_check.blockSignals(True)
        self.keep_commentary_check.setChecked(keep_commentary)
        self.keep_commentary_check.blockSignals(False)

        subtitle_filter = self.settings.value("subtitle_filter_enabled", DEFAULT_SUBTITLE_FILTER_ENABLED, type=bool)
        self.subtitle_filter_check.blockSignals(True)
        self.subtitle_filter_check.setChecked(subtitle_filter)
        self.subtitle_filter_check.blockSignals(False)

        saved_langs = self.settings.value("subtitle_languages", list(DEFAULT_SUBTITLE_LANGUAGES))
        if isinstance(saved_langs, str):  # QSettings can collapse a 1-item list to a bare string
            saved_langs = [saved_langs]
        self._saved_subtitle_languages = {str(l).lower() for l in saved_langs}

        preview = self.settings.value("preview_only", False, type=bool)
        self.preview_check.blockSignals(True)
        self.preview_check.setChecked(preview)
        self.preview_check.blockSignals(False)

        max_safety = self.settings.value("max_safety_mode", DEFAULT_MAX_SAFETY_MODE, type=bool)
        self.max_safety_check.blockSignals(True)
        self.max_safety_check.setChecked(max_safety)
        self.max_safety_check.blockSignals(False)

        persistent_backup = self.settings.value("persistent_backup", DEFAULT_PERSISTENT_BACKUP, type=bool)
        self.persistent_backup_check.blockSignals(True)
        self.persistent_backup_check.setChecked(persistent_backup)
        self.persistent_backup_check.blockSignals(False)
        self.persistent_backup_check.setEnabled(max_safety)

        stall_minutes = self.settings.value(
            "stall_timeout_minutes", DEFAULT_REMUX_STALL_TIMEOUT_SECONDS // 60, type=int
        )
        self.stall_timeout_spin.blockSignals(True)
        self.stall_timeout_spin.setValue(stall_minutes)
        self.stall_timeout_spin.blockSignals(False)

        self._update_subtitle_controls_enabled()
        self._update_action_buttons_enabled()

    def _save_folders(self):
        self.settings.setValue("folders", [str(p) for p in self.selected_roots])

    def _save_settle(self):
        self.settings.setValue("settle_seconds", self.settle_spin.value())

    def _save_preview_setting(self):
        self.settings.setValue("preview_only", self.preview_check.isChecked())

    def _save_audio_subtitle_options(self):
        self.settings.setValue("keep_commentary", self.keep_commentary_check.isChecked())
        self.settings.setValue("subtitle_filter_enabled", self.subtitle_filter_check.isChecked())

    def _save_safety_options(self):
        # Persistent Backup only makes sense once Maximum Safety Mode is on
        # (that's the only mode that creates a backup at all).
        self.persistent_backup_check.setEnabled(self.max_safety_check.isChecked())
        self.settings.setValue("max_safety_mode", self.max_safety_check.isChecked())
        self.settings.setValue("persistent_backup", self.persistent_backup_check.isChecked())
        self.settings.setValue("stall_timeout_minutes", self.stall_timeout_spin.value())

    def _on_rebuild_cache(self):
        if not self.selected_roots:
            QMessageBox.information(self, APP_NAME, "Add a folder first.")
            return
        reply = QMessageBox.question(
            self, APP_NAME,
            f"This clears the saved scan cache for {len(self.selected_roots)} folder(s), "
            f"so every file will be re-analysed (not re-modified) on the next run. "
            f"No media file is changed by this. Continue?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        cleared, errors = 0, []
        for root in self.selected_roots:
            cache_path = Path(root) / CACHE_FILENAME
            if not cache_path.exists():
                continue
            try:
                cache_path.unlink()
                cleared += 1
            except OSError as e:
                errors.append(f"{root}: {e}")
        msg = f"Cache cleared for {cleared} folder(s)."
        if errors:
            msg += "\n\nCouldn't clear:\n" + "\n".join(errors)
        QMessageBox.information(self, APP_NAME, msg)

    def _on_show_history(self):
        try:
            history = ProcessingHistory()
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't open the processing history database:\n{e}")
            return
        dlg = HistoryDialog(history, parent=self)
        dlg.exec()
        history.close()

    def _update_subtitle_controls_enabled(self):
        enabled = self.subtitle_filter_check.isChecked()
        self.scan_languages_btn.setEnabled(enabled)
        self.lang_scroll.setEnabled(enabled)

    def _on_toggle_subtitle_filter(self, checked: bool):
        self._update_subtitle_controls_enabled()
        self._save_audio_subtitle_options()

    def _get_selected_subtitle_languages(self) -> set:
        if self._lang_checkboxes:
            return {lang for lang, cb in self._lang_checkboxes.items() if cb.isChecked()}
        # Checklist hasn't been populated this session (e.g. a --minimized
        # autostart launch) -- fall back to whatever was saved last time.
        return set(self._saved_subtitle_languages)

    def _save_subtitle_language_selection(self):
        selected = {lang for lang, cb in self._lang_checkboxes.items() if cb.isChecked()}
        self._saved_subtitle_languages = selected
        self.settings.setValue("subtitle_languages", sorted(selected))

    # ---------------------------------------------------------- subtitle language scan
    def _on_scan_languages(self):
        if not self.selected_roots:
            QMessageBox.information(self, APP_NAME, "Add a folder first.")
            return
        self.scan_languages_btn.setEnabled(False)
        self.scan_languages_btn.setText("Scanning…")
        self._log("Scanning for subtitle languages across all folders…")

        self.language_scan_worker = LanguageScanWorker(self.selected_roots)
        self.language_scan_worker.finished_ok.connect(self._on_languages_scanned)
        self.language_scan_worker.failed.connect(self._on_languages_scan_failed)
        self.language_scan_worker.start()

    @_safe_slot
    def _on_languages_scanned(self, languages: set):
        self._retire_worker(self.language_scan_worker)
        while self.lang_checklist_layout.count():
            item = self.lang_checklist_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self._lang_checkboxes = {}
        if not languages:
            self.lang_checklist_layout.addWidget(QLabel("No subtitle tracks found in these folders."))
        else:
            for code in sorted(languages, key=_language_label):
                cb = QCheckBox(_language_label(code))
                cb.setChecked(code in self._saved_subtitle_languages)
                cb.toggled.connect(self._save_subtitle_language_selection)
                self.lang_checklist_layout.addWidget(cb)
                self._lang_checkboxes[code] = cb
        self.lang_checklist_layout.addStretch()

        self._save_subtitle_language_selection()
        self.scan_languages_btn.setEnabled(True)
        self.scan_languages_btn.setText("Scan Folders for Subtitle Languages…")
        self._log(f"Found {len(languages)} subtitle language(s).")

    @_safe_slot
    def _on_languages_scan_failed(self, message: str):
        self._retire_worker(self.language_scan_worker)
        self.scan_languages_btn.setEnabled(True)
        self.scan_languages_btn.setText("Scan Folders for Subtitle Languages…")
        self._log(f"Subtitle language scan failed: {message}")

    # ---------------------------------------------------------- autostart
    def _on_toggle_autostart(self, checked: bool):
        try:
            autostart.set_enabled(checked)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't update the Windows startup setting:\n{e}")
            self.autostart_check.blockSignals(True)
            self.autostart_check.setChecked(not checked)
            self.autostart_check.blockSignals(False)

    # ---------------------------------------------------------- single instance
    def _setup_single_instance_server(self):
        """Listen for pings from any second copy that gets launched while
        this one is already running, and bring our window to front instead."""
        QLocalServer.removeServer(_SINGLE_INSTANCE_SERVER_NAME)  # clear stale handle from a crash
        self._single_instance_server = QLocalServer(self)
        self._single_instance_server.newConnection.connect(self._on_single_instance_ping)
        self._single_instance_server.listen(_SINGLE_INSTANCE_SERVER_NAME)

    def _on_single_instance_ping(self):
        socket = self._single_instance_server.nextPendingConnection()
        if socket:
            socket.disconnectFromServer()
        self._show_from_tray()
        if self.tray_icon:
            self.tray_icon.showMessage(
                APP_NAME,
                "AudioCleaner is already running — bringing it to the front.",
                QSystemTrayIcon.Information,
                3000,
            )

    # ---------------------------------------------------------- system tray
    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        icon_path = _icon_path()
        if icon_path:
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_MediaVolume))
        self.tray_icon.setToolTip(APP_NAME)

        menu = QMenu()
        self.tray_show_action = menu.addAction("Show Window")
        self.tray_show_action.triggered.connect(self._show_from_tray)
        menu.addSeparator()
        self.tray_watch_action = menu.addAction("Start Watching")
        self.tray_watch_action.triggered.connect(self._toggle_watch_from_tray)
        menu.addSeparator()
        quit_action = menu.addAction("Quit AudioCleaner")
        quit_action.triggered.connect(self._quit_from_tray)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_from_tray()

    def _show_from_tray(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _toggle_watch_from_tray(self):
        self.watch_btn.click()

    def _quit_from_tray(self):
        self._stop_watching()
        if self.tray_icon:
            self.tray_icon.hide()
        if getattr(self, "_single_instance_server", None):
            self._single_instance_server.close()
        QApplication.instance().quit()

    def closeEvent(self, event):
        # Minimise to tray instead of quitting. Real exit is via the tray
        # menu's "Quit AudioCleaner", so background watching keeps running.
        event.ignore()
        self.hide()
        if self.tray_icon:
            self.tray_icon.showMessage(
                APP_NAME,
                "Still running in the background, watching your folders.",
                QSystemTrayIcon.Information,
                3000,
            )

    def _launch_minimized(self):
        """Used on --minimized startup: skip showing the window, go
        straight to tray, and resume watching the saved folders."""
        if self.selected_roots and self._deps_ok:
            self.watch_btn.setChecked(True)
            self._start_watching()
        if self.tray_icon:
            self.tray_icon.showMessage(
                APP_NAME,
                "Started minimised — watching your saved folders."
                if self.selected_roots else
                "Started minimised. Open the window to add folders to watch.",
                QSystemTrayIcon.Information,
                3000,
            )

    # ---------------------------------------------------------- folder list handlers
    def _on_add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select a folder to add")
        if not folder:
            return
        path = Path(folder)
        if path in self.selected_roots:
            QMessageBox.information(self, APP_NAME, "That folder is already in the list.")
            return
        self.selected_roots.append(path)
        self.folder_list.addItem(str(path))
        self._update_action_buttons_enabled()
        self._save_folders()

    def _on_remove_folder(self):
        row = self.folder_list.currentRow()
        if row < 0:
            QMessageBox.information(self, APP_NAME, "Select a folder in the list first.")
            return
        self.folder_list.takeItem(row)
        del self.selected_roots[row]
        self._update_action_buttons_enabled()
        self._save_folders()

    # ---------------------------------------------------------- manual run (multi-folder queue)
    def _on_start(self):
        if not self.selected_roots:
            return

        tool_error = check_tools_available()
        if tool_error:
            QMessageBox.critical(self, APP_NAME, tool_error)
            return

        self.status_box.clear()
        self.summary_label.setText("")
        self.progress_bar.setValue(0)
        self.files_count_label.setText("0 of 0")
        self.eta_label.setText("—")
        self.current_file_label.setText("—")
        self._start_time = time.time()

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.retry_errors_btn.setEnabled(False)
        self.watch_btn.setEnabled(False)

        self._run_queue = list(self.selected_roots)
        self._run_only_paths = {}
        self._last_error_paths = []
        self._run_folder_count = len(self._run_queue)
        self._run_folder_index = 0
        self._run_was_preview = self.preview_check.isChecked()
        for key in self._run_totals:
            self._run_totals[key] = 0 if key != "elapsed_seconds" else 0.0

        if self._run_was_preview:
            self._log("=== PREVIEW MODE — no files will be modified ===")

        self._run_next_folder_in_queue()

    def _on_retry_errors(self):
        if not self._last_error_paths:
            return

        tool_error = check_tools_available()
        if tool_error:
            QMessageBox.critical(self, APP_NAME, tool_error)
            return

        by_root: dict[Path, list[Path]] = {}
        for root, path in self._last_error_paths:
            by_root.setdefault(root, []).append(path)
        total_files = sum(len(v) for v in by_root.values())

        self.status_box.clear()
        self.summary_label.setText("")
        self.progress_bar.setValue(0)
        self.files_count_label.setText("0 of 0")
        self.eta_label.setText("—")
        self.current_file_label.setText("—")
        self._start_time = time.time()

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.retry_errors_btn.setEnabled(False)
        self.watch_btn.setEnabled(False)

        self._run_queue = list(by_root.keys())
        self._run_only_paths = by_root
        self._last_error_paths = []  # this run will repopulate it with whatever still fails
        self._run_folder_count = len(self._run_queue)
        self._run_folder_index = 0
        self._run_was_preview = self.preview_check.isChecked()
        for key in self._run_totals:
            self._run_totals[key] = 0 if key != "elapsed_seconds" else 0.0

        self._log(f"=== Retrying {total_files} file(s) that previously errored ===")
        self._run_next_folder_in_queue()

    def _run_next_folder_in_queue(self):
        if not self._run_queue:
            self._show_combined_summary()
            self.start_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.retry_errors_btn.setEnabled(len(self._last_error_paths) > 0)
            self.watch_btn.setEnabled(True)
            return

        root = self._run_queue.pop(0)
        self._current_run_root = root
        self._run_folder_index += 1
        self.current_folder_label.setText(
            f"{root} ({self._run_folder_index} of {self._run_folder_count})"
        )
        self._log(f"--- Starting folder {self._run_folder_index}/{self._run_folder_count}: {root} ---")

        self.worker = CleanerWorker(
            root,
            keep_commentary=self.keep_commentary_check.isChecked(),
            subtitle_filter_enabled=self.subtitle_filter_check.isChecked(),
            subtitle_languages=self._get_selected_subtitle_languages(),
            preview_only=self.preview_check.isChecked(),
            max_safety_mode=self.max_safety_check.isChecked(),
            persistent_backup=self.persistent_backup_check.isChecked(),
            only_paths=self._run_only_paths.get(root),
            stall_timeout_seconds=self.stall_timeout_spin.value() * 60,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.file_done.connect(self._on_file_done)
        self.worker.notice.connect(self._on_notice)
        self.worker.finished_ok.connect(self._on_folder_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _retire_worker(self, worker):
        """
        Blocks briefly until `worker`'s underlying OS thread has fully
        wound down before its Python reference is allowed to be replaced
        or dropped. This matters because a QThread having emitted its
        "done" signal and having its run() method return are not the same
        instant as the OS thread being fully joined at the Qt/native
        level -- deleting (or letting Python's refcounting garbage-collect)
        a QThread object while Qt still considers it "running" is a
        well-known hard crash in PySide/PyQt, not a catchable Python
        exception, so it bypasses @_safe_slot and the global excepthook
        entirely and just takes the whole process down with no dialog, no
        traceback, nothing.
        This bites hardest on the *fastest*-finishing runs -- e.g. a
        folder with zero matching files, where run_pipeline returns
        almost instantly -- because that's exactly when this method's
        caller is most likely to reuse or drop the worker reference before
        Qt has had time to settle the thread's state naturally, unlike a
        real multi-minute clean where that settling has ample time to
        happen on its own. wait() is a no-op if the thread has already
        fully stopped, so this costs nothing in the normal case.
        """
        if worker is not None:
            worker.wait(5000)

    @_safe_slot
    def _on_folder_finished(self, summary):
        self._retire_worker(self.worker)
        for key in self._run_totals:
            self._run_totals[key] += getattr(summary, key)
        self._run_next_folder_in_queue()

    def _on_cancel(self):
        if self.worker:
            self.worker.cancel()
            self._run_queue.clear()  # don't start further folders after this one
            self.cancel_btn.setEnabled(False)
            self._log("Cancelling after the current file finishes… (remaining folders skipped)")

    def _show_combined_summary(self):
        self.progress_bar.setValue(100)
        self.eta_label.setText("Done")
        t = self._run_totals
        is_preview = getattr(self, "_run_was_preview", False)

        header = "<b>Preview Summary</b> (no files were modified)" if is_preview else "<b>Completion Summary</b> (all folders)"
        cleaned_label = "Files that would be cleaned" if is_preview else "Files cleaned"
        audio_label = "Audio tracks that would be removed" if is_preview else "Audio tracks removed"
        subtitle_label = "Subtitle tracks that would be removed" if is_preview else "Subtitle tracks removed"

        lines = [
            header,
            f"Folders processed: {self._run_folder_count}",
            f"Total files scanned: {t['total_scanned']}",
            f"{cleaned_label}: {t['cleaned']}",
            f"Files skipped (already single English track): {t['skipped_single_track']}",
            f"Files with no English audio: {t['no_english']}",
            f"Files with unrecognised audio format: {t['unknown_codec']}",
            f"Errors: {t['errors']}",
            f"{audio_label}: {t['total_removed_tracks']}",
            f"{subtitle_label}: {t['total_removed_subtitle_tracks']}",
            f"Total processing time: {_format_seconds(t['elapsed_seconds'])}",
        ]
        if is_preview:
            lines.append("Disk space recovered: not calculated in preview mode — run for real to see actual savings")
        else:
            saved_mb = t["total_bytes_saved"] / 1_048_576
            lines.append(f"Estimated disk space recovered: {saved_mb:.1f} MB")

        self.summary_label.setText("<br>".join(lines))

    # ---------------------------------------------------------- watch mode (one worker per folder)
    def _on_toggle_watch(self, checked: bool):
        if checked:
            self._start_watching()
        else:
            self._stop_watching()

    def _start_watching(self):
        if not self.selected_roots:
            self.watch_btn.setChecked(False)
            return

        tool_error = check_tools_available()
        if tool_error:
            QMessageBox.critical(self, APP_NAME, tool_error)
            self.watch_btn.setChecked(False)
            return

        self.start_btn.setEnabled(False)
        self.watch_btn.setChecked(True)
        self.watch_btn.setText("Stop Watching")
        self.tray_watch_action.setText("Stop Watching")
        self.settle_spin.setEnabled(False)
        self._watch_processed_count = 0
        self.files_count_label.setText("0 processed")
        self.eta_label.setText("Continuous")
        self.current_folder_label.setText(f"Watching {len(self.selected_roots)} folder(s)")
        self.progress_bar.setRange(0, 0)  # indeterminate "busy" style

        self.watch_workers = []
        for root in self.selected_roots:
            w = WatchWorker(
                root, self.settle_spin.value(),
                keep_commentary=self.keep_commentary_check.isChecked(),
                subtitle_filter_enabled=self.subtitle_filter_check.isChecked(),
                subtitle_languages=self._get_selected_subtitle_languages(),
                max_safety_mode=self.max_safety_check.isChecked(),
                persistent_backup=self.persistent_backup_check.isChecked(),
                stall_timeout_seconds=self.stall_timeout_spin.value() * 60,
            )
            w.file_done.connect(self._on_watch_file_done)
            w.heartbeat.connect(self._on_watch_heartbeat)
            w.failed.connect(self._on_watch_failed)
            self.watch_workers.append(w)
            w.start()

    def _stop_watching(self):
        for w in self.watch_workers:
            w.stop()
        for w in self.watch_workers:
            w.wait(5000)
        self.watch_workers = []
        self.watch_btn.setText("Start Watching All Folders")
        self.watch_btn.setChecked(False)
        self.tray_watch_action.setText("Start Watching")
        self.settle_spin.setEnabled(True)
        self.start_btn.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.current_file_label.setText("—")
        self.current_folder_label.setText("—")
        self.eta_label.setText("—")

    @_safe_slot
    def _on_watch_file_done(self, result):
        self._watch_processed_count += 1
        self.files_count_label.setText(f"{self._watch_processed_count} processed")
        self.current_file_label.setText(Path(result.path).name)
        self._log(_format_result_line(result), status=result.status)

    @_safe_slot
    def _on_watch_heartbeat(self, message: str):
        self._log(message)

    @_safe_slot
    def _on_watch_failed(self, message: str):
        self._log(f"Watch mode error: {message}")
        if self.isVisible():
            QMessageBox.critical(self, APP_NAME, f"One of the watched folders stopped unexpectedly:\n{message}")
        elif self.tray_icon:
            self.tray_icon.showMessage(APP_NAME, f"Watch error: {message}", QSystemTrayIcon.Warning, 5000)
        # Leave other folders' watchers running; just drop the failed one's
        # reference so Stop Watching doesn't wait on a dead thread forever.
        # wait() first for the same reason _retire_worker() exists -- the
        # failed signal firing doesn't guarantee the OS thread has fully
        # wound down yet, and dropping a QThread reference while Qt still
        # considers it running is a hard, unrecoverable crash.
        still_running = []
        for w in self.watch_workers:
            if w.isRunning():
                still_running.append(w)
            else:
                w.wait(5000)
        self.watch_workers = still_running
        if not self.watch_workers:
            self._stop_watching()

    # ---------------------------------------------------------- log
    def _on_open_log(self):
        row = self.folder_list.currentRow()
        if row < 0:
            if len(self.selected_roots) == 1:
                row = 0
            else:
                QMessageBox.information(
                    self, APP_NAME, "Select a folder in the list first, then click Open Log."
                )
                return
        root = self.selected_roots[row]
        log_path = root / LOG_FILENAME
        if not log_path.exists():
            QMessageBox.information(self, APP_NAME, f"No log file yet for:\n{root}")
            return
        if platform.system() == "Windows":
            os.startfile(log_path)  # noqa: S606 - intended, opens in default text editor
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(log_path)])
        else:
            subprocess.run(["xdg-open", str(log_path)])

    # ---------------------------------------------------------- worker callbacks
    @_safe_slot
    def _on_progress(self, done: int, total: int, filename: str, phase: str, file_pct: int = -1):
        label = f"[{phase}] {filename}"
        if phase == "processing" and file_pct >= 0:
            # Real progress on the file currently being remuxed (from
            # mkvmerge's own --gui-mode output) -- this is what keeps a
            # single large file from looking frozen while it's worked on.
            label += f" — {file_pct}%"
        self.current_file_label.setText(label)
        self.files_count_label.setText(f"{done} of {total}")

        # Scanning (quick metadata pass) gets a small slice of the bar so
        # the processing phase -- the slow, disk-heavy part -- doesn't
        # visually snap back to a lower percentage when it begins.
        if total:
            if phase == "scanning":
                pct = int((done / total) * 20)
            else:
                file_fraction = max(file_pct, 0) / 100
                pct = 20 + int((((done - 1) + file_fraction) / total) * 80)
        else:
            pct = 0
        self.progress_bar.setValue(pct)

        if phase == "processing" and self._start_time and done > 0:
            elapsed = time.time() - self._start_time
            rate = elapsed / done
            remaining = rate * (total - done)
            self.eta_label.setText(_format_seconds(remaining))

    @_safe_slot
    def _on_file_done(self, result):
        if result.status == "error" and self._current_run_root is not None:
            self._last_error_paths.append((self._current_run_root, Path(result.path)))
        self._log(_format_result_line(result), status=result.status)

    @_safe_slot
    def _on_notice(self, message: str):
        self._log(f"ℹ {message}")

    @_safe_slot
    def _on_failed(self, message: str):
        self._retire_worker(self.worker)
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.retry_errors_btn.setEnabled(len(self._last_error_paths) > 0)
        self.watch_btn.setEnabled(True)
        self._run_queue.clear()
        QMessageBox.critical(self, APP_NAME, f"AudioCleaner stopped unexpectedly:\n{message}")

    def _log(self, line: str, status: str | None = None):
        cursor = self.status_box.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        color = _STATUS_COLORS.get(status)
        if color:
            fmt.setForeground(color)
        cursor.insertText(line + "\n", fmt)
        self.status_box.setTextCursor(cursor)
        self.status_box.ensureCursorVisible()


def _format_result_line(result) -> str:
    name = Path(result.path).name
    if result.status == "cleaned":
        codec = CODEC_LABELS.get(result.kept_codec, result.kept_codec)
        if result.preview:
            line = f"👁 {name} — would keep {codec}, would remove {result.removed_track_count} audio track(s)"
            if result.removed_subtitle_count:
                line += f", {result.removed_subtitle_count} subtitle track(s)"
            line += " (preview only)"
            return line
        line = f"✔ {name} — kept {codec}, removed {result.removed_track_count} audio track(s)"
        if result.removed_subtitle_count:
            line += f", {result.removed_subtitle_count} subtitle track(s)"
        return line
    if result.status == "skipped_single_track":
        return f"– {name} — already clean"
    if result.status == "no_english":
        return f"⚠ {name} — no English audio, skipped"
    if result.status == "unknown_codec":
        return f"⚠ {name} — unrecognised audio format, skipped (file not modified)"
    if result.status == "error":
        restored = " (original restored from backup)" if getattr(result, "restored_from_backup", False) else ""
        return f"✘ {name} — ERROR{restored}: {result.message}"
    return f"{name} — {result.status}"


def _format_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _format_bytes(n: int) -> str:
    n = max(0, n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


def _format_timestamp(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def main():
    minimized = "--minimized" in sys.argv or "--tray" in sys.argv

    app = QApplication(sys.argv)
    _install_global_excepthook()
    app.setOrganizationName(APP_NAME)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # keep running when hidden to tray
    _apply_theme(app)
    icon_path = _icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    # --- single instance check ---
    # If another AudioCleaner is already running, ping it to show itself
    # and exit immediately rather than starting a second copy (two copies
    # watching/remuxing the same folder at once isn't safe).
    probe_socket = QLocalSocket()
    probe_socket.connectToServer(_SINGLE_INSTANCE_SERVER_NAME)
    if probe_socket.waitForConnected(200):
        probe_socket.write(b"show")
        probe_socket.flush()
        probe_socket.waitForBytesWritten(500)
        probe_socket.disconnectFromServer()
        return
    probe_socket.abort()

    win = MainWindow()
    win._setup_single_instance_server()

    if minimized:
        win._launch_minimized()
    else:
        win.show()

    sys.exit(app.exec())