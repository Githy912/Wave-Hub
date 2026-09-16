import json
import os
import sys
import time
from pathlib import Path

from PyQt6.QtCore import (
    Qt,
    QUrl,
    QTimer,
    QPropertyAnimation,
    QEasingCurve,
)
from PyQt6.QtGui import QIcon, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QComboBox,
    QPlainTextEdit,
    QTextEdit,
    QGraphicsOpacityEffect,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView

from ide import IDEWindow


# ============================================================
# APPLICATION CONSTANTS
# ============================================================

APP_NAME = "Wave Hub"
APP_ORGANIZATION = "Wave"

BASE_DIR = Path(__file__).resolve().parent
LOAD_SVG = BASE_DIR / "load.svg"

RECENT_MAX_AGE = 72 * 60 * 60

LOCAL_APP_DATA = (
    Path(
        os.environ.get(
            "LOCALAPPDATA",
            str(Path.home())
        )
    )
    / APP_ORGANIZATION
    / APP_NAME
)

RECENTS_FILE = (
    LOCAL_APP_DATA / "recents.json"
)


# ============================================================
# RECENT PROJECT MANAGER
# ============================================================

class RecentProjectManager:
    def __init__(self):
        self.file = RECENTS_FILE
        self.ensure_storage()

    def ensure_storage(self):
        try:
            self.file.parent.mkdir(
                parents=True,
                exist_ok=True
            )
        except OSError:
            pass

    def _load(self):
        if not self.file.exists():
            return []

        try:
            with self.file.open(
                "r",
                encoding="utf-8"
            ) as handle:
                data = json.load(handle)

            if not isinstance(
                data,
                list
            ):
                return []

            return data

        except (
            OSError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ):
            return []

    def _save(self, entries):
        self.ensure_storage()

        try:
            temporary = self.file.with_suffix(
                ".tmp"
            )

            with temporary.open(
                "w",
                encoding="utf-8"
            ) as handle:
                json.dump(
                    entries,
                    handle,
                    indent=4
                )

            temporary.replace(
                self.file
            )

        except OSError:
            pass

    def cleanup(self):
        now = time.time()

        entries = self._load()
        cleaned = []

        seen = set()

        for entry in entries:
            if not isinstance(
                entry,
                dict
            ):
                continue

            path = entry.get(
                "path"
            )

            timestamp = entry.get(
                "timestamp"
            )

            if not isinstance(
                path,
                str
            ):
                continue

            if not isinstance(
                timestamp,
                (int, float)
            ):
                continue

            normalized = os.path.normcase(
                os.path.abspath(path)
            )

            if normalized in seen:
                continue

            if (
                now - float(timestamp)
                > RECENT_MAX_AGE
            ):
                continue

            if not os.path.isdir(
                path
            ):
                continue

            seen.add(
                normalized
            )

            cleaned.append(
                {
                    "name": entry.get(
                        "name",
                        Path(path).name
                    ),
                    "path": path,
                    "timestamp": float(
                        timestamp
                    ),
                }
            )

        cleaned.sort(
            key=lambda item: item["timestamp"],
            reverse=True
        )

        self._save(
            cleaned
        )

        return cleaned

    def add(self, path):
        path = os.path.abspath(
            os.path.expanduser(path)
        )

        if not os.path.isdir(
            path
        ):
            return

        existing = self._load()

        normalized_path = os.path.normcase(
            path
        )

        new_entries = []

        for entry in existing:
            if not isinstance(
                entry,
                dict
            ):
                continue

            old_path = entry.get(
                "path"
            )

            if not isinstance(
                old_path,
                str
            ):
                continue

            old_normalized = os.path.normcase(
                os.path.abspath(
                    old_path
                )
            )

            if old_normalized == normalized_path:
                continue

            new_entries.append(
                entry
            )

        new_entries.insert(
            0,
            {
                "name": Path(path).name or path,
                "path": path,
                "timestamp": time.time(),
            }
        )

        self._save(
            new_entries
        )

        self.cleanup()

    def remove(self, path):
        normalized_path = os.path.normcase(
            os.path.abspath(path)
        )

        remaining = []

        for entry in self._load():
            if not isinstance(
                entry,
                dict
            ):
                continue

            old_path = entry.get(
                "path"
            )

            if not isinstance(
                old_path,
                str
            ):
                continue

            old_normalized = os.path.normcase(
                os.path.abspath(
                    old_path
                )
            )

            if old_normalized != normalized_path:
                remaining.append(
                    entry
                )

        self._save(
            remaining
        )

    def get_recent(self):
        return self.cleanup()


recent_projects = RecentProjectManager()


def format_recent_time(timestamp):
    age = max(
        0,
        time.time() - float(timestamp)
    )

    if age < 60:
        return "Just now"

    if age < 3600:
        minutes = int(
            age // 60
        )

        return (
            "1 minute ago"
            if minutes == 1
            else f"{minutes} minutes ago"
        )

    if age < 86400:
        hours = int(
            age // 3600
        )

        return (
            "1 hour ago"
            if hours == 1
            else f"{hours} hours ago"
        )

    days = int(
        age // 86400
    )

    return (
        "1 day ago"
        if days == 1
        else f"{days} days ago"
    )


# ============================================================
# INTRO HTML
# ============================================================

INTRO_HTML = r"""
<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">

    <meta
        name="viewport"
        content="width=device-width,
                 initial-scale=1.0,
                 maximum-scale=1.0,
                 user-scalable=no"
    >

    <title>Wave Hub</title>

    <link
        rel="preconnect"
        href="https://fonts.googleapis.com"
    >

    <link
        rel="preconnect"
        href="https://fonts.gstatic.com"
        crossorigin
    >

    <link
        href="https://fonts.googleapis.com/css2?family=Quicksand:wght@300;400;500;600;700&display=swap"
        rel="stylesheet"
    >

    <style>

        * {
            box-sizing: border-box;
        }

        html,
        body {
            width: 100%;
            height: 100%;

            margin: 0;
            padding: 0;

            overflow: hidden;
        }

        body {
            background: #090b10;

            color: white;

            font-family: "Quicksand", sans-serif;

            display: flex;

            align-items: center;
            justify-content: center;

            user-select: none;
        }

        .background {
            position: fixed;

            inset: 0;

            background:
                radial-gradient(
                    circle at 50% 42%,
                    rgba(70, 130, 255, 0.13),
                    transparent 34%
                ),

                radial-gradient(
                    circle at 15% 85%,
                    rgba(90, 170, 255, 0.06),
                    transparent 30%
                ),

                #090b10;
        }

        .noise {
            position: fixed;

            inset: 0;

            opacity: 0.025;

            background-image:
                url(
                    "data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.5'/%3E%3C/svg%3E"
                );
        }

        .container {
            position: relative;

            z-index: 2;

            width: min(
                90vw,
                700px
            );

            display: flex;

            flex-direction: column;

            align-items: center;

            text-align: center;
        }

        .logo {
            width: 82px;
            height: 82px;

            margin-bottom: 28px;

            border-radius: 24px;

            display: flex;

            align-items: center;
            justify-content: center;

            overflow: hidden;

            opacity: 0;

            transform: scale(
                0.65
            );

            background:
                linear-gradient(
                    135deg,
                    rgba(80, 150, 255, 0.16),
                    rgba(60, 100, 255, 0.04)
                );

            border:
                1px solid rgba(
                    255,
                    255,
                    255,
                    0.06
                );

            box-shadow:
                0 20px 80px rgba(
                    0,
                    0,
                    0,
                    0.35
                ),

                inset 0 1px 0 rgba(
                    255,
                    255,
                    255,
                    0.04
                );

            transition:
                opacity 0.8s ease,
                transform 0.8s cubic-bezier(
                    .16,
                    1,
                    .3,
                    1
                );
        }

        .logo.visible {
            opacity: 1;
            transform: scale(1);
        }

        .logo-mark {
            font-size: 37px;

            font-weight: 700;

            letter-spacing: -3px;
        }

        .title {
            margin: 0;

            font-size: clamp(
                42px,
                8vw,
                74px
            );

            line-height: 0.95;

            font-weight: 600;

            letter-spacing: -3px;

            opacity: 0;

            transform:
                translateY(18px);

            transition:
                opacity 0.8s ease,
                transform 0.9s cubic-bezier(
                    .16,
                    1,
                    .3,
                    1
                );
        }

        .title.visible {
            opacity: 1;

            transform:
                translateY(0);
        }

        .subtitle {
            margin-top: 16px;

            font-size: clamp(
                15px,
                2vw,
                18px
            );

            font-weight: 400;

            color:
                rgba(
                    255,
                    255,
                    255,
                    0.54
                );

            letter-spacing: 0.4px;

            opacity: 0;

            transform:
                translateY(10px);

            transition:
                opacity 0.8s ease,
                transform 0.8s cubic-bezier(
                    .16,
                    1,
                    .3,
                    1
                );
        }

        .subtitle.visible {
            opacity: 1;

            transform:
                translateY(0);
        }

        .loading {
            margin-top: 58px;

            display: flex;

            flex-direction: column;

            align-items: center;

            opacity: 0;

            transform:
                translateY(8px);

            transition:
                opacity 0.7s ease,
                transform 0.7s ease;
        }

        .loading.visible {
            opacity: 1;

            transform:
                translateY(0);
        }

        .loader {
            width: 64px;
            height: 64px;

            object-fit: contain;

            display: block;

            animation:
                loaderPulse
                1.6s
                ease-in-out
                infinite;
        }

        @keyframes loaderPulse {

            0% {
                opacity: 0.55;

                transform:
                    scale(0.94);
            }

            50% {
                opacity: 1;

                transform:
                    scale(1);
            }

            100% {
                opacity: 0.55;

                transform:
                    scale(0.94);
            }
        }

        .status {
            margin-top: 17px;

            min-height: 22px;

            font-size: 13px;

            font-weight: 500;

            letter-spacing: 0.35px;

            color:
                rgba(
                    255,
                    255,
                    255,
                    0.48
                );
        }

        .status.fade {
            opacity: 0;

            transform:
                translateY(-3px);
        }

        .version {
            position: fixed;

            bottom: 25px;

            left: 0;
            right: 0;

            text-align: center;

            font-size: 11px;

            font-weight: 500;

            letter-spacing: 0.8px;

            color:
                rgba(
                    255,
                    255,
                    255,
                    0.20
                );

            opacity: 0;

            transition:
                opacity 1s ease;
        }

        .version.visible {
            opacity: 1;
        }

    </style>

</head>

<body>

    <div class="background"></div>
    <div class="noise"></div>

    <main class="container">

        <div
            class="logo"
            id="logo"
        >
            <div class="logo-mark">
                W
            </div>
        </div>

        <h1
            class="title"
            id="title"
        >
            Wave Hub
        </h1>

        <div
            class="subtitle"
            id="subtitle"
        >
            Your development space.
        </div>

        <div
            class="loading"
            id="loading"
        >

            <img
                class="loader"
                src="__LOAD_SVG__"
                alt=""
            >

            <div
                class="status"
                id="status"
            >
                Starting Wave Hub...
            </div>

        </div>

    </main>

    <div
        class="version"
        id="version"
    >
        WAVE HUB
    </div>

    <script>

        const logo =
            document.getElementById(
                "logo"
            );

        const title =
            document.getElementById(
                "title"
            );

        const subtitle =
            document.getElementById(
                "subtitle"
            );

        const loading =
            document.getElementById(
                "loading"
            );

        const status =
            document.getElementById(
                "status"
            );

        const version =
            document.getElementById(
                "version"
            );

        const stages = [
            "Starting Wave Hub...",
            "Preparing workspace...",
            "Loading editor...",
            "Detecting development tools...",
            "Preparing environment..."
        ];

        function setStatus(text) {

            status.classList.add(
                "fade"
            );

            setTimeout(
                () => {

                    status.textContent =
                        text;

                    status.classList.remove(
                        "fade"
                    );

                },
                180
            );
        }

        window.addEventListener(
            "load",
            () => {

                setTimeout(
                    () => {
                        logo.classList.add(
                            "visible"
                        );
                    },
                    100
                );

                setTimeout(
                    () => {
                        title.classList.add(
                            "visible"
                        );
                    },
                    450
                );

                setTimeout(
                    () => {
                        subtitle.classList.add(
                            "visible"
                        );
                    },
                    720
                );

                setTimeout(
                    () => {
                        loading.classList.add(
                            "visible"
                        );
                    },
                    1000
                );

                setTimeout(
                    () => {
                        version.classList.add(
                            "visible"
                        );
                    },
                    1250
                );

                stages.forEach(
                    (
                        stage,
                        index
                    ) => {

                        setTimeout(
                            () => {
                                setStatus(
                                    stage
                                );
                            },
                            1150
                            + (
                                index * 700
                            )
                        );

                    }
                );

            }
        );

    </script>

</body>

</html>
"""


# ============================================================
# INTRO VIEW
# ============================================================

class IntroView(QWebEngineView):
    def __init__(
        self,
        parent=None
    ):
        super().__init__(
            parent
        )

        self.setContextMenuPolicy(
            Qt.ContextMenuPolicy.NoContextMenu
        )

        self.setStyleSheet(
            """
            QWebEngineView {
                border: none;
                background: #090b10;
            }
            """
        )


# ============================================================
# NEW PROJECT DIALOG
# ============================================================

class NewProjectDialog(QDialog):
    def __init__(
        self,
        parent=None
    ):
        super().__init__(
            parent
        )

        self.setWindowTitle(
            "New Project"
        )

        self.setModal(
            True
        )

        self.resize(
            620,
            500
        )

        self.setMinimumSize(
            560,
            450
        )

        self.setStyleSheet(
            """
            QDialog {
                background: #0d1017;
            }

            QLabel {
                font-family: "Quicksand";
            }

            QLabel#DialogTitle {
                color: white;
                font-size: 28px;
                font-weight: 600;
            }

            QLabel#DialogSubtitle {
                color:
                    rgba(
                        255,
                        255,
                        255,
                        0.48
                    );

                font-size: 14px;
            }

            QLabel#FieldLabel {
                color:
                    rgba(
                        255,
                        255,
                        255,
                        0.70
                    );

                font-size: 13px;
            }

            QLabel#PathPreview {
                color:
                    rgba(
                        255,
                        255,
                        255,
                        0.40
                    );

                background:
                    rgba(
                        255,
                        255,
                        255,
                        0.025
                    );

                border:
                    1px solid rgba(
                        255,
                        255,
                        255,
                        0.06
                    );

                border-radius: 8px;

                padding: 11px 12px;

                font-size: 12px;
            }

            QLineEdit,
            QComboBox {
                background:
                    rgba(
                        255,
                        255,
                        255,
                        0.045
                    );

                border:
                    1px solid rgba(
                        255,
                        255,
                        255,
                        0.08
                    );

                border-radius: 9px;

                color: white;

                padding: 11px 12px;

                font-family:
                    "Quicksand";

                font-size: 14px;
            }

            QLineEdit:focus,
            QComboBox:focus {
                border:
                    1px solid rgba(
                        90,
                        145,
                        255,
                        0.65
                    );
            }

            QComboBox::drop-down {
                border: none;
                width: 30px;
            }

            QComboBox QAbstractItemView {
                background: #11151e;
                color: white;

                border:
                    1px solid rgba(
                        255,
                        255,
                        255,
                        0.08
                    );

                selection-background-color:
                    rgba(
                        80,
                        135,
                        255,
                        0.22
                    );
            }

            QPushButton {
                border: none;

                border-radius: 9px;

                padding: 11px 18px;

                font-family:
                    "Quicksand";

                font-size: 14px;

                color:
                    rgba(
                        255,
                        255,
                        255,
                        0.78
                    );

                background:
                    rgba(
                        255,
                        255,
                        255,
                        0.055
                    );
            }

            QPushButton:hover {
                background:
                    rgba(
                        255,
                        255,
                        255,
                        0.085
                    );

                color: white;
            }

            QPushButton#CreateButton {
                background:
                    rgba(
                        80,
                        135,
                        255,
                        0.18
                    );

                color: white;
            }

            QPushButton#CreateButton:hover {
                background:
                    rgba(
                        80,
                        135,
                        255,
                        0.27
                    );
            }

            QFrame#Divider {
                background:
                    rgba(
                        255,
                        255,
                        255,
                        0.06
                    );

                max-height: 1px;
            }
            """
        )

        self.build_ui()

        self.update_path_preview()

    def build_ui(self):
        root = QVBoxLayout(
            self
        )

        root.setContentsMargins(
            38,
            34,
            38,
            30
        )

        title = QLabel(
            "New Project"
        )

        title.setObjectName(
            "DialogTitle"
        )

        root.addWidget(
            title
        )

        subtitle = QLabel(
            "Create a new development project."
        )

        subtitle.setObjectName(
            "DialogSubtitle"
        )

        root.addSpacing(
            7
        )

        root.addWidget(
            subtitle
        )

        root.addSpacing(
            30
        )

        name_label = QLabel(
            "Project name"
        )

        name_label.setObjectName(
            "FieldLabel"
        )

        root.addWidget(
            name_label
        )

        root.addSpacing(
            7
        )

        self.name_edit = QLineEdit()

        self.name_edit.setPlaceholderText(
            "MyProject"
        )

        self.name_edit.textChanged.connect(
            self.update_path_preview
        )

        root.addWidget(
            self.name_edit
        )

        root.addSpacing(
            20
        )

        location_label = QLabel(
            "Location"
        )

        location_label.setObjectName(
            "FieldLabel"
        )

        root.addWidget(
            location_label
        )

        root.addSpacing(
            7
        )

        location_row = QHBoxLayout()

        location_row.setSpacing(
            8
        )

        self.location_edit = QLineEdit()

        default_location = (
            Path.home() / "Documents"
        )

        if not default_location.exists():
            default_location = Path.home()

        self.location_edit.setText(
            str(default_location)
        )

        self.location_edit.textChanged.connect(
            self.update_path_preview
        )

        location_row.addWidget(
            self.location_edit,
            1
        )

        browse = QPushButton(
            "Browse"
        )

        browse.clicked.connect(
            self.browse_location
        )

        location_row.addWidget(
            browse
        )

        root.addLayout(
            location_row
        )

        root.addSpacing(
            20
        )

        type_label = QLabel(
            "Project type"
        )

        type_label.setObjectName(
            "FieldLabel"
        )

        root.addWidget(
            type_label
        )

        root.addSpacing(
            7
        )

        self.type_combo = QComboBox()

        self.type_combo.addItems(
            [
                "Empty Project",
                "Python Project",
                "C Project",
                "C++ Project",
                "Rust Project",
                "Go Project",
            ]
        )

        root.addWidget(
            self.type_combo
        )

        root.addSpacing(
            20
        )

        preview_label = QLabel(
            "Project will be created at"
        )

        preview_label.setObjectName(
            "FieldLabel"
        )

        root.addWidget(
            preview_label
        )

        root.addSpacing(
            7
        )

        self.path_preview = QLabel()

        self.path_preview.setObjectName(
            "PathPreview"
        )

        self.path_preview.setWordWrap(
            True
        )

        root.addWidget(
            self.path_preview
        )

        root.addStretch(
            1
        )

        divider = QFrame()

        divider.setObjectName(
            "Divider"
        )

        root.addWidget(
            divider
        )

        root.addSpacing(
            18
        )

        buttons = QHBoxLayout()

        buttons.addStretch(
            1
        )

        cancel = QPushButton(
            "Cancel"
        )

        cancel.clicked.connect(
            self.reject
        )

        buttons.addWidget(
            cancel
        )

        create = QPushButton(
            "Create Project"
        )

        create.setObjectName(
            "CreateButton"
        )

        create.clicked.connect(
            self.create_project
        )

        buttons.addWidget(
            create
        )

        root.addLayout(
            buttons
        )

    def browse_location(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            "Choose Project Location",
            self.location_edit.text()
        )

        if directory:
            self.location_edit.setText(
                directory
            )

    def update_path_preview(self):
        name = (
            self.name_edit
            .text()
            .strip()
        )

        location = (
            self.location_edit
            .text()
            .strip()
        )

        if not name:
            name = "MyProject"

        if not location:
            location = str(
                Path.home()
            )

        self.path_preview.setText(
            str(
                Path(location) / name
            )
        )

    def create_project(self):
        name = (
            self.name_edit
            .text()
            .strip()
        )

        location = (
            self.location_edit
            .text()
            .strip()
        )

        if not name:
            QMessageBox.warning(
                self,
                "Project Name Required",
                "Please enter a project name."
            )

            return

        if not location:
            QMessageBox.warning(
                self,
                "Location Required",
                "Please choose a location."
            )

            return

        invalid_chars = '<>:"/\\|?*'

        if any(
            char in name
            for char in invalid_chars
        ):
            QMessageBox.warning(
                self,
                "Invalid Project Name",
                "The project name contains characters "
                "that are not allowed in Windows "
                "file names."
            )

            return

        root = Path(
            location
        ).expanduser()

        try:
            root.mkdir(
                parents=True,
                exist_ok=True
            )

        except OSError as exc:
            QMessageBox.critical(
                self,
                "Cannot Access Location",
                f"{exc}"
            )

            return

        project_path = root / name

        if project_path.exists():
            QMessageBox.warning(
                self,
                "Project Already Exists",
                f"The project directory already exists:\n\n"
                f"{project_path}"
            )

            return

        try:
            project_path.mkdir()

            self.create_project_files(
                project_path,
                self.type_combo.currentText()
            )

        except OSError as exc:
            QMessageBox.critical(
                self,
                "Project Creation Failed",
                f"{exc}"
            )

            return

        recent_projects.add(
            str(project_path)
        )

        self.accept()

        # Open the actual IDE after the dialog closes.
        self.parent().open_project_workspace(
            str(project_path)
        )

    @staticmethod
    def create_project_files(
        project_path,
        project_type
    ):
        if project_type == "Python Project":

            (
                project_path / "main.py"
            ).write_text(
                '''def main():
    print("Hello from Wave Hub!")


if __name__ == "__main__":
    main()
''',
                encoding="utf-8"
            )

        elif project_type == "C Project":

            (
                project_path / "main.c"
            ).write_text(
                '''#include <stdio.h>

int main(void)
{
    printf("Hello from Wave Hub!\\n");
    return 0;
}
''',
                encoding="utf-8"
            )

        elif project_type == "C++ Project":

            (
                project_path / "main.cpp"
            ).write_text(
                '''#include <iostream>

int main()
{
    std::cout << "Hello from Wave Hub!\\n";
    return 0;
}
''',
                encoding="utf-8"
            )

        elif project_type == "Rust Project":

            src = (
                project_path / "src"
            )

            src.mkdir()

            (
                src / "main.rs"
            ).write_text(
                '''fn main() {
    println!("Hello from Wave Hub!");
}
''',
                encoding="utf-8"
            )

            (
                project_path / "Cargo.toml"
            ).write_text(
                '''[package]
name = "wavehub_project"
version = "0.1.0"
edition = "2021"

[dependencies]
''',
                encoding="utf-8"
            )

        elif project_type == "Go Project":

            (
                project_path / "main.go"
            ).write_text(
                '''package main

import "fmt"

func main() {
    fmt.Println("Hello from Wave Hub!")
}
''',
                encoding="utf-8"
            )


# ============================================================
# RECENTS DIALOG
# ============================================================

class RecentsDialog(QDialog):
    def __init__(
        self,
        parent=None
    ):
        super().__init__(
            parent
        )

        self.setWindowTitle(
            "Recent Projects"
        )

        self.resize(
            760,
            540
        )

        self.setStyleSheet(
            """
            QDialog {
                background: #0d1017;
            }

            QLabel#Title {
                color: white;
                font-family: "Quicksand";
                font-size: 28px;
                font-weight: 600;
            }

            QLabel#Subtitle {
                color:
                    rgba(
                        255,
                        255,
                        255,
                        0.48
                    );

                font-family: "Quicksand";
                font-size: 14px;
            }

            QListWidget {
                background:
                    rgba(
                        255,
                        255,
                        255,
                        0.025
                    );

                border:
                    1px solid rgba(
                        255,
                        255,
                        255,
                        0.07
                    );

                border-radius: 12px;

                outline: none;

                color: white;

                padding: 6px;

                font-family:
                    "Quicksand";
            }

            QListWidget::item {
                border-radius: 9px;
                padding: 13px 14px;
                margin: 2px;
            }

            QListWidget::item:hover {
                background:
                    rgba(
                        255,
                        255,
                        255,
                        0.045
                    );
            }

            QListWidget::item:selected {
                background:
                    rgba(
                        80,
                        135,
                        255,
                        0.16
                    );
            }

            QPushButton {
                border: none;
                border-radius: 9px;

                padding: 11px 18px;

                background:
                    rgba(
                        255,
                        255,
                        255,
                        0.055
                    );

                color:
                    rgba(
                        255,
                        255,
                        255,
                        0.80
                    );

                font-family:
                    "Quicksand";
            }

            QPushButton:hover {
                background:
                    rgba(
                        255,
                        255,
                        255,
                        0.085
                    );
            }

            QPushButton#OpenButton {
                background:
                    rgba(
                        80,
                        135,
                        255,
                        0.18
                    );

                color: white;
            }
            """
        )

        self.build_ui()

        self.populate()

    def build_ui(self):
        layout = QVBoxLayout(
            self
        )

        layout.setContentsMargins(
            34,
            30,
            34,
            28
        )

        title = QLabel(
            "Recent Projects"
        )

        title.setObjectName(
            "Title"
        )

        layout.addWidget(
            title
        )

        subtitle = QLabel(
            "Projects opened or created within "
            "the last 72 hours."
        )

        subtitle.setObjectName(
            "Subtitle"
        )

        layout.addSpacing(
            7
        )

        layout.addWidget(
            subtitle
        )

        layout.addSpacing(
            24
        )

        self.list = QListWidget()

        self.list.itemDoubleClicked.connect(
            self.open_selected
        )

        layout.addWidget(
            self.list
        )

        layout.addSpacing(
            18
        )

        buttons = QHBoxLayout()

        buttons.addStretch(
            1
        )

        close = QPushButton(
            "Close"
        )

        close.clicked.connect(
            self.reject
        )

        buttons.addWidget(
            close
        )

        open_button = QPushButton(
            "Open Project"
        )

        open_button.setObjectName(
            "OpenButton"
        )

        open_button.clicked.connect(
            self.open_selected
        )

        buttons.addWidget(
            open_button
        )

        layout.addLayout(
            buttons
        )

    def populate(self):
        self.list.clear()

        entries = (
            recent_projects
            .get_recent()
        )

        if not entries:
            item = QListWidgetItem(
                "No projects from the last 72 hours."
            )

            item.setData(
                Qt.ItemDataRole.UserRole,
                None
            )

            self.list.addItem(
                item
            )

            return

        for entry in entries:

            name = entry.get(
                "name",
                "Unnamed Project"
            )

            path = entry.get(
                "path",
                ""
            )

            timestamp = entry.get(
                "timestamp",
                0
            )

            item = QListWidgetItem(
                f"{name}\n"
                f"{path}\n"
                f"{format_recent_time(timestamp)}"
            )

            item.setData(
                Qt.ItemDataRole.UserRole,
                path
            )

            self.list.addItem(
                item
            )

        self.list.setCurrentRow(
            0
        )

    def open_selected(
        self,
        item=None
    ):
        if item is None:
            item = self.list.currentItem()

        if item is None:
            return

        path = item.data(
            Qt.ItemDataRole.UserRole
        )

        if not path:
            return

        if not os.path.isdir(
            path
        ):
            recent_projects.remove(
                path
            )

            QMessageBox.warning(
                self,
                "Project Not Found",
                "This project directory no longer exists."
            )

            self.populate()

            return

        recent_projects.add(
            path
        )

        self.accept()

        self.parent().open_project_workspace(
            path
        )


# ============================================================
# WELCOME PAGE
# ============================================================

class WelcomePage(QWidget):
    def __init__(
        self,
        parent=None
    ):
        super().__init__(
            parent
        )

        self.setObjectName(
            "WelcomePage"
        )

        self.setStyleSheet(
            """
            QWidget#WelcomePage {
                background: #0a0c11;
            }

            QLabel {
                font-family: "Quicksand";
            }

            QLabel#WelcomeTitle {
                color: white;
                font-size: 42px;
                font-weight: 600;
            }

            QLabel#WelcomeSubtitle {
                color:
                    rgba(
                        255,
                        255,
                        255,
                        0.50
                    );

                font-size: 16px;
            }

            QPushButton {
                border: none;
                border-radius: 10px;

                background: transparent;

                color:
                    rgba(
                        255,
                        255,
                        255,
                        0.82
                    );

                text-align: left;

                padding: 14px 16px;

                font-family:
                    "Quicksand";

                font-size: 16px;
            }

            QPushButton:hover {
                background:
                    rgba(
                        255,
                        255,
                        255,
                        0.055
                    );

                color: white;
            }

            QPushButton#PrimaryButton {
                background:
                    rgba(
                        80,
                        135,
                        255,
                        0.13
                    );

                color: white;
            }

            QPushButton#PrimaryButton:hover {
                background:
                    rgba(
                        80,
                        135,
                        255,
                        0.19
                    );
            }

            QFrame#RightPanel {
                background:
                    qradialgradient(
                        cx: 0.50,
                        cy: 0.45,
                        radius: 0.75,

                        fx: 0.50,
                        fy: 0.45,

                        stop: 0
                            rgba(
                                50,
                                100,
                                220,
                                0.075
                            ),

                        stop: 0.55
                            rgba(
                                20,
                                30,
                                55,
                                0.025
                            ),

                        stop: 1
                            rgba(
                                0,
                                0,
                                0,
                                0
                            )
                    );

                border-left:
                    1px solid
                    rgba(
                        255,
                        255,
                        255,
                        0.055
                    );
            }
            """
        )

        self.build_ui()

    def build_ui(self):
        outer = QHBoxLayout(
            self
        )

        outer.setContentsMargins(
            0,
            0,
            0,
            0
        )

        outer.setSpacing(
            0
        )

        left = QWidget()

        left.setMinimumWidth(
            570
        )

        left_layout = QVBoxLayout(
            left
        )

        left_layout.setContentsMargins(
            80,
            70,
            70,
            70
        )

        title = QLabel(
            "Welcome!"
        )

        title.setObjectName(
            "WelcomeTitle"
        )

        left_layout.addWidget(
            title
        )

        subtitle = QLabel(
            "Please choose to proceed:"
        )

        subtitle.setObjectName(
            "WelcomeSubtitle"
        )

        left_layout.addSpacing(
            12
        )

        left_layout.addWidget(
            subtitle
        )

        left_layout.addSpacing(
            44
        )

        new_project = QPushButton(
            "New Project  >"
        )

        new_project.setObjectName(
            "PrimaryButton"
        )

        new_project.setMinimumHeight(
            54
        )

        new_project.clicked.connect(
            self.new_project
        )

        left_layout.addWidget(
            new_project
        )

        left_layout.addSpacing(
            10
        )

        open_project = QPushButton(
            "Open existing project  >"
        )

        open_project.setMinimumHeight(
            54
        )

        open_project.clicked.connect(
            self.open_project
        )

        left_layout.addWidget(
            open_project
        )

        left_layout.addSpacing(
            10
        )

        recent = QPushButton(
            "Browse Recents  >"
        )

        recent.setMinimumHeight(
            54
        )

        recent.clicked.connect(
            self.browse_recents
        )

        left_layout.addWidget(
            recent
        )

        left_layout.addStretch(
            1
        )

        footer = QLabel(
            "Wave Hub"
        )

        footer.setStyleSheet(
            """
            QLabel {
                color:
                    rgba(
                        255,
                        255,
                        255,
                        0.20
                    );

                font-size: 12px;
                font-weight: 500;
                letter-spacing: 0.5px;
            }
            """
        )

        left_layout.addWidget(
            footer
        )

        right = QFrame()

        right.setObjectName(
            "RightPanel"
        )

        right_layout = QVBoxLayout(
            right
        )

        right_layout.addStretch(
            1
        )

        mark = QLabel(
            "W"
        )

        mark.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        mark.setStyleSheet(
            """
            QLabel {
                color:
                    rgba(
                        255,
                        255,
                        255,
                        0.075
                    );

                font-size: 110px;
                font-weight: 700;
            }
            """
        )

        right_layout.addWidget(
            mark
        )

        text = QLabel(
            "WAVE HUB"
        )

        text.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        text.setStyleSheet(
            """
            QLabel {
                color:
                    rgba(
                        255,
                        255,
                        255,
                        0.13
                    );

                font-size: 14px;
                font-weight: 600;
                letter-spacing: 4px;
            }
            """
        )

        right_layout.addWidget(
            text
        )

        right_layout.addStretch(
            1
        )

        outer.addWidget(
            left
        )

        outer.addWidget(
            right,
            1
        )

    def new_project(self):
        dialog = NewProjectDialog(
            self.window()
        )

        dialog.exec()

    def open_project(self):
        directory = QFileDialog.getExistingDirectory(
            self.window(),
            "Open Existing Project",
            str(Path.home())
        )

        if not directory:
            return

        directory = os.path.abspath(
            directory
        )

        recent_projects.add(
            directory
        )

        self.window().open_project_workspace(
            directory
        )

    def browse_recents(self):
        dialog = RecentsDialog(
            self.window()
        )

        dialog.exec()


# ============================================================
# MAIN WINDOW
# ============================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            APP_NAME
        )

        self.resize(
            1280,
            800
        )

        self.setMinimumSize(
            1000,
            650
        )

        if LOAD_SVG.exists():
            self.setWindowIcon(
                QIcon(
                    str(LOAD_SVG)
                )
            )

        self.setStyleSheet(
            """
            QMainWindow {
                background: #0a0c11;
            }
            """
        )

        self.current_ide = None
        self.intro_finished = False
        self.transition_started = False

        self.intro = IntroView(
            self
        )

        self.setCentralWidget(
            self.intro
        )

        self.load_intro()

        QTimer.singleShot(
            5100,
            self.start_intro_fade
        )

    # ========================================================
    # INTRO
    # ========================================================

    def load_intro(self):
        load_path = (
            LOAD_SVG.as_uri()
        )

        html = INTRO_HTML.replace(
            "__LOAD_SVG__",
            load_path
        )

        self.intro.setHtml(
            html,
            QUrl.fromLocalFile(
                str(BASE_DIR)
                + os.sep
            )
        )

    def start_intro_fade(self):
        if self.transition_started:
            return

        self.transition_started = True

        effect = QGraphicsOpacityEffect(
            self.intro
        )

        effect.setOpacity(
            1.0
        )

        self.intro.setGraphicsEffect(
            effect
        )

        self.fade_out = QPropertyAnimation(
            effect,
            b"opacity",
            self
        )

        self.fade_out.setDuration(
            850
        )

        self.fade_out.setStartValue(
            1.0
        )

        self.fade_out.setEndValue(
            0.0
        )

        self.fade_out.setEasingCurve(
            QEasingCurve.Type.InOutCubic
        )

        self.fade_out.finished.connect(
            self.show_welcome
        )

        self.fade_out.start()

    def show_welcome(self):
        welcome = WelcomePage(
            self
        )

        effect = QGraphicsOpacityEffect(
            welcome
        )

        effect.setOpacity(
            0.0
        )

        welcome.setGraphicsEffect(
            effect
        )

        self.setCentralWidget(
            welcome
        )

        self.fade_in = QPropertyAnimation(
            effect,
            b"opacity",
            self
        )

        self.fade_in.setDuration(
            850
        )

        self.fade_in.setStartValue(
            0.0
        )

        self.fade_in.setEndValue(
            1.0
        )

        self.fade_in.setEasingCurve(
            QEasingCurve.Type.InOutCubic
        )

        self.fade_in.finished.connect(
            self.finish_transition
        )

        self.fade_in.start()

    def finish_transition(self):
        self.intro_finished = True

    # ========================================================
    # REAL IDE
    # ========================================================

    def open_project_workspace(
        self,
        project_path
    ):
        project_path = os.path.abspath(
            project_path
        )

        if not os.path.isdir(
            project_path
        ):
            QMessageBox.warning(
                self,
                "Project Not Found",
                "The selected project directory "
                "does not exist."
            )

            return

        recent_projects.add(
            project_path
        )

        # Replace the home window with the actual IDE.
        ide = IDEWindow(
            project_path
        )

        self.current_ide = ide

        self.setCentralWidget(
            ide
        )

        self.setWindowTitle(
            f"{Path(project_path).name} - {APP_NAME}"
        )

        # Keep the normal maximized Wave Hub experience.
        self.showMaximized()

    # ========================================================
    # WINDOW CLOSE
    # ========================================================

    def closeEvent(self, event):
        if self.current_ide is not None:

            ide = self.current_ide

            # Let IDEWindow perform its own unsaved-change
            # checks before allowing this top-level window
            # to disappear.
            ide.closeEvent(
                event
            )

            return

        event.accept()


# ============================================================
# ENTRY POINT
# ============================================================

def main():
    QApplication.setAttribute(
        Qt.ApplicationAttribute.AA_ShareOpenGLContexts
    )

    app = QApplication(
        sys.argv
    )

    app.setApplicationName(
        APP_NAME
    )

    app.setApplicationDisplayName(
        APP_NAME
    )

    app.setOrganizationName(
        APP_ORGANIZATION
    )

    app.setFont(
        QFont(
            "Quicksand",
            10
        )
    )

    window = MainWindow()

    window.showMaximized()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()