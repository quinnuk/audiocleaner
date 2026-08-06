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
"""

import os
import platform
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QPlainTextEdit, QFileDialog, QMessageBox,
    QGroupBox, QFormLayout, QSpinBox, QFrame, QListWidget, QCheckBox,
    QSystemTrayIcon, QMenu, QStyle,
)

from .config import APP_NAME, LOG_FILENAME, CODEC_LABELS, WATCH_DEFAULT_SETTLE_SECONDS
from .worker import CleanerWorker, WatchWorker
from .probe import check_tools_available, get_missing_tools
from . import autostart


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(680, 600)

        self.settings = QSettings()

        self.worker: CleanerWorker | None = None
        self.watch_workers: list[WatchWorker] = []
        self.selected_roots: list[Path] = []
        self._start_time: float | None = None
        self._watch_processed_count = 0
        self.tray_icon: QSystemTrayIcon | None = None

        # Multi-folder manual-run queue state
        self._run_queue: list[Path] = []
        self._run_totals = {
            "total_scanned": 0, "cleaned": 0, "skipped_single_track": 0,
            "no_english": 0, "errors": 0, "total_removed_tracks": 0,
            "total_bytes_saved": 0, "elapsed_seconds": 0.0,
        }
        self._run_folder_index = 0
        self._run_folder_count = 0

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
            "QFrame { background-color: #fff3cd; border: 1px solid #e0c265; border-radius: 4px; }"
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
        self.folder_list.setMaximumHeight(120)
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
        self.start_btn.clicked.connect(self._on_start)
        self.start_btn.setEnabled(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setEnabled(False)
        action_row.addWidget(self.start_btn)
        action_row.addWidget(self.cancel_btn)
        layout.addLayout(action_row)

        # Watch mode row
        watch_row = QHBoxLayout()
        self.watch_btn = QPushButton("Start Watching All Folders")
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

        self._update_action_buttons_enabled()

    def _save_folders(self):
        self.settings.setValue("folders", [str(p) for p in self.selected_roots])

    def _save_settle(self):
        self.settings.setValue("settle_seconds", self.settle_spin.value())

    # ---------------------------------------------------------- autostart
    def _on_toggle_autostart(self, checked: bool):
        try:
            autostart.set_enabled(checked)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't update the Windows startup setting:\n{e}")
            self.autostart_check.blockSignals(True)
            self.autostart_check.setChecked(not checked)
            self.autostart_check.blockSignals(False)

    # ---------------------------------------------------------- system tray
    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
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
        self.watch_btn.setEnabled(False)

        self._run_queue = list(self.selected_roots)
        self._run_folder_count = len(self._run_queue)
        self._run_folder_index = 0
        for key in self._run_totals:
            self._run_totals[key] = 0 if key != "elapsed_seconds" else 0.0

        self._run_next_folder_in_queue()

    def _run_next_folder_in_queue(self):
        if not self._run_queue:
            self._show_combined_summary()
            self.start_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.watch_btn.setEnabled(True)
            return

        root = self._run_queue.pop(0)
        self._run_folder_index += 1
        self.current_folder_label.setText(
            f"{root} ({self._run_folder_index} of {self._run_folder_count})"
        )
        self._log(f"--- Starting folder {self._run_folder_index}/{self._run_folder_count}: {root} ---")

        self.worker = CleanerWorker(root)
        self.worker.progress.connect(self._on_progress)
        self.worker.file_done.connect(self._on_file_done)
        self.worker.finished_ok.connect(self._on_folder_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_folder_finished(self, summary):
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
        saved_mb = t["total_bytes_saved"] / 1_048_576
        self.summary_label.setText(
            "<b>Completion Summary</b> (all folders)<br>"
            f"Folders processed: {self._run_folder_count}<br>"
            f"Total files scanned: {t['total_scanned']}<br>"
            f"Files cleaned: {t['cleaned']}<br>"
            f"Files skipped (already single English track): {t['skipped_single_track']}<br>"
            f"Files with no English audio: {t['no_english']}<br>"
            f"Errors: {t['errors']}<br>"
            f"Audio tracks removed: {t['total_removed_tracks']}<br>"
            f"Total processing time: {_format_seconds(t['elapsed_seconds'])}<br>"
            f"Estimated disk space recovered: {saved_mb:.1f} MB"
        )

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
            w = WatchWorker(root, self.settle_spin.value())
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

    def _on_watch_file_done(self, result):
        self._watch_processed_count += 1
        self.files_count_label.setText(f"{self._watch_processed_count} processed")
        self.current_file_label.setText(Path(result.path).name)
        self._log(_format_result_line(result))

    def _on_watch_heartbeat(self, message: str):
        self._log(message)

    def _on_watch_failed(self, message: str):
        self._log(f"Watch mode error: {message}")
        if self.isVisible():
            QMessageBox.critical(self, APP_NAME, f"One of the watched folders stopped unexpectedly:\n{message}")
        elif self.tray_icon:
            self.tray_icon.showMessage(APP_NAME, f"Watch error: {message}", QSystemTrayIcon.Warning, 5000)
        # Leave other folders' watchers running; just drop the failed one's
        # reference so Stop Watching doesn't wait on a dead thread forever.
        self.watch_workers = [w for w in self.watch_workers if w.isRunning()]
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
    def _on_progress(self, done: int, total: int, filename: str, phase: str):
        self.current_file_label.setText(f"[{phase}] {filename}")
        self.files_count_label.setText(f"{done} of {total}")
        pct = int((done / total) * 100) if total else 0
        self.progress_bar.setValue(pct)

        if phase == "processing" and self._start_time and done > 0:
            elapsed = time.time() - self._start_time
            rate = elapsed / done
            remaining = rate * (total - done)
            self.eta_label.setText(_format_seconds(remaining))

    def _on_file_done(self, result):
        self._log(_format_result_line(result))

    def _on_failed(self, message: str):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.watch_btn.setEnabled(True)
        self._run_queue.clear()
        QMessageBox.critical(self, APP_NAME, f"AudioCleaner stopped unexpectedly:\n{message}")

    def _log(self, line: str):
        self.status_box.appendPlainText(line)


def _format_result_line(result) -> str:
    name = Path(result.path).name
    if result.status == "cleaned":
        codec = CODEC_LABELS.get(result.kept_codec, result.kept_codec)
        return f"✔ {name} — kept {codec}, removed {result.removed_track_count} track(s)"
    if result.status == "skipped_single_track":
        return f"– {name} — already clean"
    if result.status == "no_english":
        return f"⚠ {name} — no English audio, skipped"
    if result.status == "error":
        return f"✘ {name} — ERROR: {result.message}"
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


def main():
    minimized = "--minimized" in sys.argv or "--tray" in sys.argv

    app = QApplication(sys.argv)
    app.setOrganizationName(APP_NAME)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # keep running when hidden to tray

    win = MainWindow()

    if minimized:
        win._launch_minimized()
    else:
        win.show()

    sys.exit(app.exec())
