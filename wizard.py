from __future__ import annotations

import ctypes
import json
import os
import random
import string
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QFileDialog,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "Wave Hub Setup"
APP_VERSION = "1.0.0"
VENDOR = "Wave"

GNU_GPL_URL = "https://www.gnu.org/licenses/gpl-3.0.txt"
WAVE_HUB_URL = "https://media.githubusercontent.com/media/Githy912/Wave-Hub/main/Wave%20Hub.exe"
IDE_URL = "https://media.githubusercontent.com/media/Githy912/Wave-Hub/main/ide.exe"

DEFAULT_INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs" / "Wave Hub"
APPDATA_WIZARD_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Wave" / "Wave Hub" / "Wizard"
CODE_FILENAME = "code.txt"
LOCK_FILENAME = "WaveHubWizard.lock"
MAX_AUTH_ATTEMPTS = 3


def application_storage_dir() -> Path:
    """Return a persistent, writable per-user location for wizard state."""
    try:
        path = APPDATA_WIZARD_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        fallback = Path.home() / ".wave" / "wave-hub-wizard"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def code_candidate_paths() -> list[Path]:
    """Candidate paths for code.txt, including the packaged EXE directory."""
    candidates: list[Path] = []

    # When frozen by PyInstaller/cx_Freeze/etc., write beside the actual EXE.
    # This intentionally uses sys.executable, NOT sys._MEIPASS.
    try:
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent / CODE_FILENAME)
        else:
            candidates.append(Path(__file__).resolve().parent / CODE_FILENAME)
    except Exception:
        pass

    # Robust per-user fallback. This is used automatically when the EXE folder
    # is protected or otherwise not writable.
    candidates.append(application_storage_dir() / CODE_FILENAME)
    return candidates


def lock_candidate_paths() -> list[Path]:
    """Candidate paths for the persistent installer lock."""
    candidates: list[Path] = []

    try:
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent / LOCK_FILENAME)
        else:
            candidates.append(Path(__file__).resolve().parent / LOCK_FILENAME)
    except Exception:
        pass

    candidates.append(application_storage_dir() / LOCK_FILENAME)
    return candidates


def read_text_safe(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def write_text_safe(path: Path, text: str) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True
    except (OSError, PermissionError):
        return False


def generate_auth_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.SystemRandom().choices(alphabet, k=6))


def get_persistent_lock_path() -> Path:
    """Return the best persistent lock path, creating it when necessary."""
    for path in lock_candidate_paths():
        if path.exists():
            return path

    for path in lock_candidate_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Wave Hub Setup is permanently locked.\n", encoding="utf-8")
            return path
        except (OSError, PermissionError):
            continue

    # Last resort. The file need not be created here; the lock check simply
    # cannot persist on a truly unwritable machine.
    return application_storage_dir() / LOCK_FILENAME


def is_installer_locked() -> bool:
    return any(path.exists() for path in lock_candidate_paths())


def permanently_lock_installer() -> None:
    for path in lock_candidate_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "Wave Hub Setup has been permanently locked after three invalid authentication attempts.\n",
                encoding="utf-8",
            )
            # Hidden file on Windows is only cosmetic. Failure is harmless.
            if os.name == "nt":
                try:
                    FILE_ATTRIBUTE_HIDDEN = 0x2
                    ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_HIDDEN)
                except Exception:
                    pass
        except (OSError, PermissionError):
            continue


def load_or_create_auth_code() -> tuple[str, Path]:
    """
    Load a valid existing six-character code or create one.

    Important packaged-binary behavior:
    - For an EXE, first tries the directory containing the EXE.
    - If that directory is not writable, automatically falls back to a
      per-user LOCALAPPDATA location.
    - Never uses a one-file PyInstaller extraction directory.
    """
    for path in code_candidate_paths():
        existing = read_text_safe(path)
        if (
            existing
            and len(existing) == 6
            and all(ch in string.ascii_uppercase + string.digits for ch in existing)
        ):
            return existing, path

    code = generate_auth_code()
    for path in code_candidate_paths():
        if write_text_safe(path, code + "\n"):
            return code, path

    raise RuntimeError("Wave Hub Setup could not create code.txt in a writable location.")


def add_user_path(folder: Path) -> bool:
    """Add folder to the current user's PATH without requiring admin rights."""
    folder_str = str(folder.resolve())

    if os.name != "nt":
        current = os.environ.get("PATH", "")
        if folder_str not in [p for p in current.split(os.pathsep) if p]:
            os.environ["PATH"] = current + (os.pathsep if current else "") + folder_str
        return True

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_READ | winreg.KEY_SET_VALUE,
        ) as key:
            try:
                old_path, value_type = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                old_path, value_type = "", winreg.REG_EXPAND_SZ

            parts = [p.strip() for p in str(old_path).split(";") if p.strip()]
            normalized = {os.path.normcase(os.path.normpath(p)) for p in parts}

            if os.path.normcase(os.path.normpath(folder_str)) not in normalized:
                parts.append(folder_str)
                new_path = ";".join(parts)
                winreg.SetValueEx(key, "Path", 0, value_type, new_path)

        # Notify existing Windows processes that the user environment changed.
        try:
            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x001A
            SMTO_ABORTIFHUNG = 0x0002
            ctypes.windll.user32.SendMessageTimeoutW(
                HWND_BROADCAST,
                WM_SETTINGCHANGE,
                0,
                "Environment",
                SMTO_ABORTIFHUNG,
                5000,
                ctypes.byref(ctypes.c_ulong()),
            )
        except Exception:
            pass

        os.environ["PATH"] = os.environ.get("PATH", "") + ";" + folder_str
        return True
    except Exception:
        return False


def launch_executable(path: Path) -> bool:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen([str(path)])
        return True
    except Exception:
        try:
            subprocess.Popen([str(path)], cwd=str(path.parent))
            return True
        except Exception:
            return False


class DownloadWorker(QThread):
    progress = pyqtSignal(int)
    file_status = pyqtSignal(str)
    succeeded = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, downloads: list[tuple[str, str, Path]], parent=None):
        super().__init__(parent)
        self.downloads = downloads
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            total_bytes = 0
            sizes: list[int | None] = []

            for _, url, _ in self.downloads:
                try:
                    request = urllib.request.Request(
                        url,
                        headers={"User-Agent": "WaveHubWizard/1.0"},
                        method="HEAD",
                    )
                    with urllib.request.urlopen(request, timeout=15) as response:
                        length = response.headers.get("Content-Length")
                        size = int(length) if length and length.isdigit() else None
                except Exception:
                    size = None
                sizes.append(size)
                if size:
                    total_bytes += size

            completed_bytes = 0

            for index, (display_name, url, destination) in enumerate(self.downloads):
                if self._cancel.is_set():
                    return

                self.file_status.emit(f"Downloading {display_name}...")
                destination.parent.mkdir(parents=True, exist_ok=True)
                temp = destination.with_suffix(destination.suffix + ".download")

                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "WaveHubWizard/1.0",
                        "Accept": "application/octet-stream,*/*",
                    },
                )

                try:
                    with urllib.request.urlopen(request, timeout=60) as response, temp.open("wb") as output:
                        expected = response.headers.get("Content-Length")
                        expected_size = int(expected) if expected and expected.isdigit() else sizes[index]
                        current = 0

                        while True:
                            if self._cancel.is_set():
                                try:
                                    temp.unlink(missing_ok=True)
                                except Exception:
                                    pass
                                return

                            chunk = response.read(1024 * 1024)
                            if not chunk:
                                break

                            output.write(chunk)
                            current += len(chunk)

                            if total_bytes > 0:
                                overall = completed_bytes + current
                                self.progress.emit(min(100, int(overall * 100 / total_bytes)))
                            elif expected_size:
                                base = int(index * 100 / len(self.downloads))
                                span = int(100 / len(self.downloads))
                                self.progress.emit(min(100, base + int(current * span / expected_size)))

                    # A Git LFS pointer is not the actual EXE. Detect it clearly.
                    try:
                        sample = temp.read_bytes()[:256]
                    except OSError:
                        sample = b""

                    if sample.startswith(b"version https://git-lfs.github.com/spec/v1"):
                        raise RuntimeError(
                            f"GitHub returned a Git LFS pointer for {display_name} instead of the binary."
                        )

                    if len(sample) < 1024:
                        raise RuntimeError(f"Downloaded {display_name} is unexpectedly small and may be invalid.")

                    temp.replace(destination)
                except Exception:
                    try:
                        temp.unlink(missing_ok=True)
                    except Exception:
                        pass
                    raise

                if sizes[index]:
                    completed_bytes += sizes[index] or 0
                self.progress.emit(min(100, int(completed_bytes * 100 / total_bytes)) if total_bytes else int((index + 1) * 100 / len(self.downloads)))

            self.progress.emit(100)
            self.succeeded.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class StepList(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StepList")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSpacing(6)

        for title in [
            "Welcome",
            "License",
            "Install Location",
            "Authentication Code",
            "Review",
            "Installing...",
            "Done",
        ]:
            item = QListWidgetItem(title)
            self.addItem(item)


class WizardWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setMinimumSize(1000, 680)
        self.resize(1080, 720)

        self.auth_code = ""
        self.code_path: Path | None = None
        self.auth_attempts = 0
        self.auth_verified = False
        self.license_text = ""
        self.install_path = DEFAULT_INSTALL_DIR
        self.download_worker: DownloadWorker | None = None
        self.install_cancelled = False
        self.install_ok = False

        self._build_ui()
        self._apply_style()
        self._load_authentication_code()
        self.show_step(0)
        self._fetch_license()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.steps = StepList()
        root_layout.addWidget(self.steps, 0)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(34, 28, 34, 24)
        right_layout.setSpacing(18)

        header = QHBoxLayout()
        self.brand = QLabel("WAVE HUB")
        self.brand.setObjectName("Brand")
        self.version = QLabel(APP_VERSION)
        self.version.setObjectName("Version")
        header.addWidget(self.brand)
        header.addStretch()
        header.addWidget(self.version)
        right_layout.addLayout(header)

        self.title = QLabel()
        self.title.setObjectName("PageTitle")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("PageSubtitle")
        self.subtitle.setWordWrap(True)
        right_layout.addWidget(self.title)
        right_layout.addWidget(self.subtitle)

        self.pages = QWidget()
        self.page_layout = QVBoxLayout(self.pages)
        self.page_layout.setContentsMargins(0, 0, 0, 0)
        self.page_layout.setSpacing(0)
        right_layout.addWidget(self.pages, 1)

        footer_line = QFrame()
        footer_line.setFrameShape(QFrame.Shape.HLine)
        footer_line.setObjectName("FooterLine")
        right_layout.addWidget(footer_line)

        footer = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel")
        self.back_button = QPushButton("< Back")
        self.next_button = QPushButton("Next >")
        self.finish_button = QPushButton("Finish")
        self.finish_button.setObjectName("PrimaryButton")

        footer.addWidget(self.cancel_button)
        footer.addStretch()
        footer.addWidget(self.back_button)
        footer.addWidget(self.next_button)
        footer.addWidget(self.finish_button)
        right_layout.addLayout(footer)

        root_layout.addWidget(right, 1)
        self.setCentralWidget(root)

        self.cancel_button.clicked.connect(self.cancel)
        self.back_button.clicked.connect(self.back)
        self.next_button.clicked.connect(self.next)
        self.finish_button.clicked.connect(self.finish)

        self._build_pages()

    def _build_pages(self) -> None:
        self.page_widgets: list[QWidget] = []
        self.page_widgets.append(self._page_welcome())
        self.page_widgets.append(self._page_license())
        self.page_widgets.append(self._page_install_location())
        self.page_widgets.append(self._page_auth())
        self.page_widgets.append(self._page_review())
        self.page_widgets.append(self._page_installing())
        self.page_widgets.append(self._page_done())

        for page in self.page_widgets:
            self.page_layout.addWidget(page)
            page.hide()

    def _card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        return card

    def _page_welcome(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(16)

        hero = self._card()
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(28, 28, 28, 28)
        hero_layout.setSpacing(10)

        h = QLabel("Install Wave Hub")
        h.setObjectName("CardTitle")
        p = QLabel(
            "Wave Hub is a lightweight development environment built around a focused editor,\n"
            "project explorer, smart editing, search and replace, command palette, and file runners."
        )
        p.setWordWrap(True)
        p.setObjectName("CardText")
        hero_layout.addWidget(h)
        hero_layout.addWidget(p)

        features = QLabel(
            "• Python, C, C++, Rust, and Go project starters\n"
            "• Cascadia Code editor with syntax highlighting and smart editing\n"
            "• Tabs, dirty-state tracking, save-all, zoom, Find, Replace, and F5 run\n"
            "• Explorer context actions and a return-to-Welcome project lifecycle"
        )
        features.setObjectName("CardText")
        features.setWordWrap(True)
        hero_layout.addWidget(features)
        layout.addWidget(hero)
        layout.addStretch()
        return page

    def _page_license(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        self.license_status = QLabel("Fetching GNU GPL v3.0 license text...")
        self.license_status.setObjectName("InfoText")
        layout.addWidget(self.license_status)

        self.license_box = QPlainTextEdit()
        self.license_box.setReadOnly(True)
        self.license_box.setPlaceholderText("The GNU GPL v3.0 text will appear here.")
        layout.addWidget(self.license_box, 1)

        self.license_note = QLabel(
            "Wave Hub is distributed under the GNU General Public License, version 3.0."
        )
        self.license_note.setObjectName("InfoText")
        self.license_note.setWordWrap(True)
        layout.addWidget(self.license_note)
        return page

    def _page_install_location(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(16)

        card = self._card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 24, 24, 24)
        cl.setSpacing(12)

        label = QLabel("Where should Wave Hub be installed?")
        label.setObjectName("CardTitle")
        cl.addWidget(label)

        row = QHBoxLayout()
        self.install_edit = QLineEdit(str(self.install_path))
        self.install_edit.textChanged.connect(self._on_install_path_changed)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self.browse_install_path)
        row.addWidget(self.install_edit, 1)
        row.addWidget(self.browse_button)
        cl.addLayout(row)

        self.path_preview = QLabel()
        self.path_preview.setObjectName("PathPreview")
        self.path_preview.setWordWrap(True)
        cl.addWidget(self.path_preview)

        self.path_check = QLabel()
        self.path_check.setObjectName("InfoText")
        cl.addWidget(self.path_check)

        self.path_checkbox = QCheckBox("Add Wave Hub to my user PATH")
        self.path_checkbox.setChecked(True)
        cl.addWidget(self.path_checkbox)

        note = QLabel(
            "The installer uses a per-user install location by default, so administrator access is not required."
        )
        note.setObjectName("MutedText")
        note.setWordWrap(True)
        cl.addWidget(note)

        layout.addWidget(card)
        layout.addStretch()
        return page

    def _page_auth(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(16)

        card = self._card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 24, 24, 24)
        cl.setSpacing(12)

        h = QLabel("Authentication Code")
        h.setObjectName("CardTitle")
        cl.addWidget(h)

        text = QLabel(
            "A six-character authentication code was generated when this installer opened.\n"
            "Enter the code stored in code.txt to continue. You have three attempts."
        )
        text.setObjectName("CardText")
        text.setWordWrap(True)
        cl.addWidget(text)

        self.auth_input = QLineEdit()
        self.auth_input.setPlaceholderText("Enter 6-character code")
        self.auth_input.setMaxLength(6)
        self.auth_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.auth_input.setFont(QFont("Cascadia Code", 18))
        self.auth_input.textChanged.connect(lambda value: self.auth_input.setText(value.upper()))
        cl.addWidget(self.auth_input)

        self.auth_status = QLabel()
        self.auth_status.setObjectName("InfoText")
        self.auth_status.setWordWrap(True)
        cl.addWidget(self.auth_status)

        self.auth_hint = QLabel()
        self.auth_hint.setObjectName("MutedText")
        self.auth_hint.setWordWrap(True)
        cl.addWidget(self.auth_hint)

        layout.addWidget(card)
        layout.addStretch()
        return page

    def _page_review(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(16)

        card = self._card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 24, 24, 24)
        cl.setSpacing(12)

        h = QLabel("Review your installation")
        h.setObjectName("CardTitle")
        cl.addWidget(h)

        self.review_list = QLabel()
        self.review_list.setObjectName("ReviewText")
        self.review_list.setTextFormat(Qt.TextFormat.RichText)
        self.review_list.setWordWrap(True)
        cl.addWidget(self.review_list)

        note = QLabel(
            "The installer will download the current Wave Hub.exe and ide.exe files from the Wave Hub GitHub repository."
        )
        note.setObjectName("MutedText")
        note.setWordWrap(True)
        cl.addWidget(note)

        layout.addWidget(card)
        layout.addStretch()
        return page

    def _page_installing(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(16)

        card = self._card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 24, 24, 24)
        cl.setSpacing(14)

        self.install_status = QLabel("Preparing installation...")
        self.install_status.setObjectName("CardTitle")
        self.install_status.setWordWrap(True)
        cl.addWidget(self.install_status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        cl.addWidget(self.progress)

        self.install_details = QLabel("Waiting for download worker...")
        self.install_details.setObjectName("InfoText")
        self.install_details.setWordWrap(True)
        cl.addWidget(self.install_details)

        layout.addWidget(card)
        layout.addStretch()
        return page

    def _page_done(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(16)

        card = self._card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 24, 24, 24)
        cl.setSpacing(12)

        self.done_title = QLabel("Wave Hub is installed")
        self.done_title.setObjectName("CardTitle")
        cl.addWidget(self.done_title)

        self.done_text = QLabel()
        self.done_text.setObjectName("CardText")
        self.done_text.setWordWrap(True)
        cl.addWidget(self.done_text)

        self.launch_checkbox = QCheckBox("Launch Wave Hub when I click Finish")
        self.launch_checkbox.setChecked(True)
        cl.addWidget(self.launch_checkbox)

        layout.addWidget(card)
        layout.addStretch()
        return page

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            * {
                font-family: "Quicksand";
            }
            QMainWindow {
                background: #0b0d12;
            }
            #StepList {
                background: #11141b;
                border: none;
                padding: 22px 12px;
                color: #aeb5c4;
                min-width: 215px;
                max-width: 215px;
                font-size: 10.5pt;
            }
            #StepList::item {
                padding: 12px 15px;
                border-radius: 7px;
                margin: 1px 0;
            }
            #StepList::item:selected {
                background: #252b36;
                color: #ffffff;
            }
            #StepList::item:hover {
                background: #1a1f28;
            }
            #Brand {
                color: #ffffff;
                font-size: 13pt;
                font-weight: 700;
                letter-spacing: 1px;
            }
            #Version {
                color: #7f8797;
                font-size: 9pt;
            }
            #PageTitle {
                color: #ffffff;
                font-size: 21pt;
                font-weight: 700;
            }
            #PageSubtitle {
                color: #939baa;
                font-size: 10.5pt;
            }
            #Card {
                background: #12161d;
                border: 1px solid #242a34;
                border-radius: 11px;
            }
            #CardTitle {
                color: #ffffff;
                font-size: 13pt;
                font-weight: 700;
            }
            #CardText, #ReviewText {
                color: #c5cad4;
                font-size: 10.5pt;
            }
            #InfoText {
                color: #9fa7b6;
                font-size: 9.5pt;
            }
            #MutedText {
                color: #737b8c;
                font-size: 9pt;
            }
            #PathPreview {
                color: #b8c1d2;
                font-family: "Cascadia Code";
                font-size: 9pt;
            }
            #FooterLine {
                color: #252a33;
                background: #252a33;
            }
            QPushButton {
                background: #1a1f28;
                color: #dfe3ea;
                border: 1px solid #303744;
                border-radius: 6px;
                padding: 9px 16px;
                min-width: 82px;
            }
            QPushButton:hover {
                background: #232a35;
            }
            QPushButton:pressed {
                background: #171b22;
            }
            QPushButton:disabled {
                color: #5a6170;
                background: #14171d;
                border-color: #20242c;
            }
            #PrimaryButton {
                background: #3d7eff;
                color: white;
                border-color: #3d7eff;
            }
            #PrimaryButton:hover {
                background: #4b88ff;
            }
            QLineEdit, QPlainTextEdit {
                background: #0b0e13;
                color: #e2e6ed;
                border: 1px solid #2b313d;
                border-radius: 6px;
                padding: 9px;
                selection-background-color: #315fa8;
            }
            QPlainTextEdit {
                font-family: "Cascadia Code";
                font-size: 9pt;
            }
            QLineEdit:focus, QPlainTextEdit:focus {
                border-color: #4b88ff;
            }
            QCheckBox {
                color: #d8dce4;
                spacing: 9px;
            }
            QProgressBar {
                background: #0a0d12;
                border: 1px solid #252c36;
                border-radius: 6px;
                text-align: center;
                color: #e8ebf0;
                min-height: 22px;
            }
            QProgressBar::chunk {
                background: #3d7eff;
                border-radius: 5px;
            }
            """
        )

    # ------------------------------------------------------------------
    # Startup/authentication
    # ------------------------------------------------------------------
    def _load_authentication_code(self) -> None:
        if is_installer_locked():
            self._show_locked_state()
            return

        try:
            self.auth_code, self.code_path = load_or_create_auth_code()
            self.auth_hint.setText(
                f"The installer stored the generated code at:\n{self.code_path}"
            )
            self.auth_status.setText("Authentication is required before installation can continue.")
        except Exception as exc:
            self.auth_status.setText(str(exc))
            self.next_button.setEnabled(False)

    def _show_locked_state(self) -> None:
        self.auth_code = ""
        self.auth_verified = False
        self.auth_status.setText("This installer has been permanently locked after three invalid authentication attempts.")
        self.auth_status.setObjectName("InfoText")
        self.auth_input.setEnabled(False)
        self.next_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.auth_hint.setText("A persistent lock marker was found. This setup instance cannot continue.")

    # ------------------------------------------------------------------
    # License
    # ------------------------------------------------------------------
    def _fetch_license(self) -> None:
        class LicenseWorker(QThread):
            done = pyqtSignal(str)
            failed = pyqtSignal(str)

            def run(self) -> None:
                try:
                    request = urllib.request.Request(
                        GNU_GPL_URL,
                        headers={"User-Agent": "WaveHubWizard/1.0"},
                    )
                    with urllib.request.urlopen(request, timeout=20) as response:
                        data = response.read().decode("utf-8", errors="replace")
                    self.done.emit(data)
                except Exception as exc:
                    self.failed.emit(str(exc))

        self.license_worker = LicenseWorker(self)
        self.license_worker.done.connect(self._license_loaded)
        self.license_worker.failed.connect(self._license_failed)
        self.license_worker.start()

    def _license_loaded(self, text: str) -> None:
        self.license_text = text
        self.license_box.setPlainText(text)
        self.license_status.setText("GNU GPL v3.0 fetched successfully.")

    def _license_failed(self, error: str) -> None:
        self.license_status.setText(f"Could not fetch GNU GPL v3.0: {error}")
        self.license_box.setPlainText(
            "The license could not be downloaded right now.\n\n"
            "Wave Hub is intended to be distributed under GNU GPL v3.0.\n"
            "You may continue, but the license text could not be displayed from the network."
        )

    # ------------------------------------------------------------------
    # Navigation/pages
    # ------------------------------------------------------------------
    def show_step(self, index: int) -> None:
        index = max(0, min(index, len(self.page_widgets) - 1))
        self.current_step = index

        for i, page in enumerate(self.page_widgets):
            page.setVisible(i == index)

        self.steps.setCurrentRow(index)

        titles = [
            ("Welcome", "Review what will be installed before continuing."),
            ("License", "GNU GPL v3.0 is fetched directly from the GNU project."),
            ("Install Location", "Choose where Wave Hub should live on this PC."),
            ("Authentication Code", "Verify the code generated when the installer started."),
            ("Review", "Confirm the settings before downloading the binaries."),
            ("Installing...", "Downloading and installing Wave Hub."),
            ("Done", "Installation completed successfully."),
        ]
        self.title.setText(titles[index][0])
        self.subtitle.setText(titles[index][1])

        self.back_button.setVisible(index not in (0, 5, 6))
        self.next_button.setVisible(index not in (5, 6))
        self.finish_button.setVisible(index == 6)
        self.cancel_button.setEnabled(index != 5)

        if index == 1:
            self.next_button.setEnabled(True)
        elif index == 3:
            self.next_button.setEnabled(self.auth_verified)
        elif index == 5:
            self.next_button.setEnabled(False)
        elif index == 6:
            self.finish_button.setEnabled(self.install_ok)
        elif index != 6:
            self.next_button.setEnabled(True)

        if index == 4:
            self._update_review()

    def _update_review(self) -> None:
        path = Path(self.install_edit.text().strip()).expanduser()
        add_path = "Yes" if self.path_checkbox.isChecked() else "No"
        self.review_list.setText(
            f"<b>Installation path</b><br>{path}<br><br>"
            f"<b>Add to user PATH</b><br>{add_path}<br><br>"
            f"<b>Files</b><br>Wave Hub.exe<br>ide.exe<br><br>"
            f"<b>Authentication</b><br>Verified"
        )

    def next(self) -> None:
        if self.current_step == 0:
            self.show_step(1)
            return
        if self.current_step == 1:
            self.show_step(2)
            return
        if self.current_step == 2:
            if not self.validate_install_path():
                return
            self.show_step(3)
            return
        if self.current_step == 3:
            if not self.auth_verified:
                self.verify_auth_code()
                return
            self.show_step(4)
            return
        if self.current_step == 4:
            if not self.validate_install_path():
                return
            self.show_step(5)
            self.start_installation()
            return

    def back(self) -> None:
        if self.current_step == 1:
            self.show_step(0)
        elif self.current_step == 2:
            self.show_step(1)
        elif self.current_step == 3:
            self.show_step(2)
        elif self.current_step == 4:
            self.show_step(3)

    # ------------------------------------------------------------------
    # Install path
    # ------------------------------------------------------------------
    def _on_install_path_changed(self, value: str) -> None:
        path = Path(value.strip()).expanduser() if value.strip() else Path()
        self.path_preview.setText(f"Files will be installed to:\n{path}")
        self._validate_path_visual(path)

    def _validate_path_visual(self, path: Path) -> bool:
        if not str(path):
            self.path_check.setText("Choose an installation directory.")
            return False

        try:
            resolved = path.resolve()
            if resolved.parent == resolved:
                self.path_check.setText("Choose a directory inside a filesystem root.")
                return False
        except Exception:
            self.path_check.setText("The selected path could not be resolved.")
            return False

        self.path_check.setText("Installation path looks valid.")
        return True

    def browse_install_path(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Installation Folder",
            self.install_edit.text().strip() or str(DEFAULT_INSTALL_DIR),
        )
        if directory:
            self.install_edit.setText(directory)

    def validate_install_path(self) -> bool:
        text = self.install_edit.text().strip()
        if not text:
            QMessageBox.warning(self, APP_NAME, "Please choose an installation directory.")
            return False

        path = Path(text).expanduser()
        try:
            resolved = path.resolve()
            if resolved.parent == resolved:
                QMessageBox.warning(self, APP_NAME, "Installing directly into a filesystem root is not supported.")
                return False

            # Ensure either the directory or its nearest existing parent is writable.
            probe_parent = resolved
            while not probe_parent.exists() and probe_parent != probe_parent.parent:
                probe_parent = probe_parent.parent

            if not os.access(str(probe_parent), os.W_OK):
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    f"The selected location is not writable:\n\n{probe_parent}",
                )
                return False
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"Invalid installation path:\n{exc}")
            return False

        self.install_path = resolved
        return True

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    def verify_auth_code(self) -> None:
        if not self.auth_code:
            return

        entered = self.auth_input.text().strip().upper()
        if entered == self.auth_code:
            self.auth_verified = True
            self.auth_status.setText("Authentication successful. You can continue.")
            self.next_button.setEnabled(True)
            self.auth_input.setEnabled(False)
            self.auth_hint.setText("The installer code was verified successfully.")
            return

        self.auth_attempts += 1
        remaining = MAX_AUTH_ATTEMPTS - self.auth_attempts

        if remaining <= 0:
            permanently_lock_installer()
            self.auth_status.setText("Three invalid attempts were entered. The installer is now permanently locked.")
            self.auth_input.setEnabled(False)
            self.next_button.setEnabled(False)
            self.back_button.setEnabled(False)
            self.cancel_button.setText("Close")
            QMessageBox.critical(
                self,
                APP_NAME,
                "Authentication failed three times.\n\nThis installer is now locked and cannot continue.",
            )
            return

        self.auth_status.setText(
            f"Incorrect authentication code. {remaining} attempt{'s' if remaining != 1 else ''} remaining."
        )
        self.auth_input.selectAll()
        self.auth_input.setFocus()

    # ------------------------------------------------------------------
    # Installation
    # ------------------------------------------------------------------
    def start_installation(self) -> None:
        self.install_ok = False
        self.install_cancelled = False
        self.install_status.setText("Preparing installation...")
        self.install_details.setText(str(self.install_path))
        self.progress.setValue(0)

        try:
            self.install_path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self.installation_failed(str(exc))
            return

        downloads = [
            ("Wave Hub.exe", WAVE_HUB_URL, self.install_path / "Wave Hub.exe"),
            ("ide.exe", IDE_URL, self.install_path / "ide.exe"),
        ]

        self.download_worker = DownloadWorker(downloads, self)
        self.download_worker.progress.connect(self.progress.setValue)
        self.download_worker.file_status.connect(self.install_details.setText)
        self.download_worker.succeeded.connect(self.installation_succeeded)
        self.download_worker.failed.connect(self.installation_failed)
        self.download_worker.start()

    def installation_succeeded(self) -> None:
        if self.path_checkbox.isChecked():
            if not add_user_path(self.install_path):
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    "Wave Hub installed, but the user PATH could not be updated automatically.",
                )

        wave_hub_exe = self.install_path / "Wave Hub.exe"
        ide_exe = self.install_path / "ide.exe"
        valid = wave_hub_exe.exists() and ide_exe.exists()

        self.install_ok = valid
        self.progress.setValue(100 if valid else 0)

        if valid:
            self.done_text.setText(
                f"Wave Hub has been installed to:<br><br><b>{self.install_path}</b><br><br>"
                "Both Wave Hub.exe and ide.exe are ready."
            )
            self.install_status.setText("Installation complete.")
            self.install_details.setText("Wave Hub.exe and ide.exe installed successfully.")
            self.show_step(6)
        else:
            self.installation_failed("The downloaded files were not found after installation.")

    def installation_failed(self, error: str) -> None:
        self.install_ok = False
        self.install_status.setText("Installation failed.")
        self.install_details.setText(error)
        self.next_button.setEnabled(False)
        QMessageBox.critical(
            self,
            APP_NAME,
            "Wave Hub could not be installed.\n\n" + error,
        )
        self.show_step(4)

    # ------------------------------------------------------------------
    # Finish/cancel
    # ------------------------------------------------------------------
    def cancel(self) -> None:
        if self.current_step == 5:
            return

        answer = QMessageBox.question(
            self,
            APP_NAME,
            "Cancel Wave Hub Setup?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.close()

    def finish(self) -> None:
        if not self.install_ok:
            return

        if self.launch_checkbox.isChecked():
            wave_hub_exe = self.install_path / "Wave Hub.exe"
            if not launch_executable(wave_hub_exe):
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    f"Wave Hub was installed successfully, but it could not be launched automatically.\n\n{wave_hub_exe}",
                )
                return

        self.close()

    def closeEvent(self, event) -> None:
        if self.download_worker is not None and self.download_worker.isRunning():
            event.ignore()
            QMessageBox.information(
                self,
                APP_NAME,
                "Installation is still running. Please wait for it to finish.",
            )
            return
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(VENDOR)

    if is_installer_locked():
        QMessageBox.critical(
            None,
            APP_NAME,
            "This Wave Hub installer has been permanently locked after three invalid authentication attempts.",
        )
        return 1

    window = WizardWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
