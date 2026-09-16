from __future__ import annotations

import ctypes
import hashlib
import html
import json
import os
import random
import re
import string
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontDatabase, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


# ============================================================
# Application
# ============================================================

APP_NAME = "Wave Hub Setup"
APP_VERSION = "1.0.1"
VENDOR = "Wave"

REPO_OWNER = "Githy912"
REPO_NAME = "Wave-Hub"

GITHUB_API_URL = (
    f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
)

# Direct GitHub Media fallbacks.
# Release assets are preferred. These are only used when release metadata
# cannot be retrieved or does not contain the requested assets.
WAVE_HUB_FALLBACK_URL = (
    "https://media.githubusercontent.com/media/"
    "Githy912/Wave-Hub/main/Wave%20Hub.exe"
)
IDE_FALLBACK_URL = (
    "https://media.githubusercontent.com/media/"
    "Githy912/Wave-Hub/main/ide.exe"
)

# Official GNU GPL sources.
GNU_GPL_URLS = [
    "https://www.gnu.org/licenses/gpl-3.0.txt",
    "https://www.gnu.org/licenses/old-licenses/gpl-3.0.txt",
]

# Remote Quicksand font sources.
# No font file is required beside wizard.py.
GOOGLE_FONTS_CSS_URL = (
    "https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700"
    "&display=swap"
)

QUICKSAND_FALLBACK_FONT_URLS = [
    "https://raw.githubusercontent.com/google/fonts/main/ofl/quicksand/"
    "Quicksand%5Bwght%5D.ttf",
]

DEFAULT_INSTALL_DIR = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    / "Programs"
    / "Wave Hub"
)

APPDATA_WIZARD_DIR = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    / "Wave"
    / "Wave Hub"
    / "Wizard"
)

CODE_FILENAME = "code.txt"
LOCK_FILENAME = "WaveHubWizard.lock"
LICENSE_CACHE_NAME = "GPL-3.0.txt"
FONT_CACHE_NAME = "Quicksand.ttf"

MAX_AUTH_ATTEMPTS = 3
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
NETWORK_TIMEOUT = 45

USER_AGENT = f"WaveHubWizard/{APP_VERSION}"


# ============================================================
# Generic helpers
# ============================================================

def ensure_storage_dir() -> Path:
    try:
        APPDATA_WIZARD_DIR.mkdir(parents=True, exist_ok=True)
        return APPDATA_WIZARD_DIR
    except OSError:
        fallback = Path.home() / ".wave" / "wave-hub-wizard"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


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


def normalize_code(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch in string.ascii_uppercase + string.digits)


def escape_html(value: str) -> str:
    return html.escape(str(value), quote=True)


def format_bytes(size: int | None) -> str:
    if size is None:
        return "Unknown size"

    value = float(size)

    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024

    return f"{size} B"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        while True:
            block = file.read(DOWNLOAD_CHUNK_SIZE)
            if not block:
                break
            digest.update(block)

    return digest.hexdigest()


# ============================================================
# Authentication state
# ============================================================

def code_candidate_paths() -> list[Path]:
    candidates: list[Path] = []

    try:
        if getattr(sys, "frozen", False):
            candidates.append(
                Path(sys.executable).resolve().parent / CODE_FILENAME
            )
        else:
            candidates.append(
                Path(__file__).resolve().parent / CODE_FILENAME
            )
    except Exception:
        pass

    candidates.append(
        ensure_storage_dir() / CODE_FILENAME
    )

    return candidates


def lock_candidate_paths() -> list[Path]:
    candidates: list[Path] = []

    try:
        if getattr(sys, "frozen", False):
            candidates.append(
                Path(sys.executable).resolve().parent / LOCK_FILENAME
            )
        else:
            candidates.append(
                Path(__file__).resolve().parent / LOCK_FILENAME
            )
    except Exception:
        pass

    candidates.append(
        ensure_storage_dir() / LOCK_FILENAME
    )

    return candidates


def is_installer_locked() -> bool:
    return any(path.exists() for path in lock_candidate_paths())


def permanently_lock_installer() -> None:
    text = (
        "Wave Hub Setup has been permanently locked after three invalid "
        "authentication attempts.\n"
    )

    for path in lock_candidate_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

            if os.name == "nt":
                try:
                    FILE_ATTRIBUTE_HIDDEN = 0x2
                    ctypes.windll.kernel32.SetFileAttributesW(
                        str(path),
                        FILE_ATTRIBUTE_HIDDEN,
                    )
                except Exception:
                    pass
        except (OSError, PermissionError):
            continue


def generate_auth_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(
        random.SystemRandom().choices(alphabet, k=6)
    )


def load_or_create_auth_code() -> tuple[str, Path]:
    valid_chars = set(string.ascii_uppercase + string.digits)

    for path in code_candidate_paths():
        existing = read_text_safe(path)

        if (
            existing
            and len(existing) == 6
            and all(ch in valid_chars for ch in existing)
        ):
            return existing, path

    code = generate_auth_code()

    for path in code_candidate_paths():
        if write_text_safe(path, code + "\n"):
            return code, path

    raise RuntimeError(
        "Wave Hub Setup could not create code.txt in a writable location."
    )


# ============================================================
# PATH
# ============================================================

def add_user_path(folder: Path) -> bool:
    folder_str = str(folder.resolve())

    if os.name != "nt":
        current = os.environ.get("PATH", "")
        parts = [
            p for p in current.split(os.pathsep)
            if p
        ]

        normalized = {
            os.path.normcase(os.path.normpath(p))
            for p in parts
        }

        candidate = os.path.normcase(
            os.path.normpath(folder_str)
        )

        if candidate not in normalized:
            parts.append(folder_str)
            os.environ["PATH"] = os.pathsep.join(parts)

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
                old_path, value_type = winreg.QueryValueEx(
                    key,
                    "Path",
                )
            except FileNotFoundError:
                old_path = ""
                value_type = winreg.REG_EXPAND_SZ

            parts = [
                p.strip()
                for p in str(old_path).split(";")
                if p.strip()
            ]

            normalized = {
                os.path.normcase(
                    os.path.normpath(p)
                )
                for p in parts
            }

            candidate = os.path.normcase(
                os.path.normpath(folder_str)
            )

            if candidate not in normalized:
                parts.append(folder_str)

                winreg.SetValueEx(
                    key,
                    "Path",
                    0,
                    value_type,
                    ";".join(parts),
                )

        # Tell running Windows applications that the environment changed.
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

        # Keep this process's PATH usable too.
        current_process_path = os.environ.get("PATH", "")
        current_parts = [
            p for p in current_process_path.split(";")
            if p
        ]

        normalized_current = {
            os.path.normcase(
                os.path.normpath(p)
            )
            for p in current_parts
        }

        candidate = os.path.normcase(
            os.path.normpath(folder_str)
        )

        if candidate not in normalized_current:
            current_parts.append(folder_str)
            os.environ["PATH"] = ";".join(current_parts)

        return True

    except Exception:
        return False


# ============================================================
# Launch
# ============================================================

def launch_executable(path: Path) -> bool:
    try:
        if not path.exists():
            return False

        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(
                [str(path)],
                cwd=str(path.parent),
            )

        return True

    except Exception:
        try:
            subprocess.Popen(
                [str(path)],
                cwd=str(path.parent),
            )
            return True
        except Exception:
            return False


# ============================================================
# Executable validation
# ============================================================

def inspect_pe_file(path: Path) -> tuple[bool, str]:
    """
    Validate that a downloaded Windows executable is actually a PE binary.

    This intentionally does NOT impose an arbitrary minimum file size.
    A valid executable's size is allowed to vary.
    """

    try:
        file_size = path.stat().st_size
    except OSError as exc:
        return False, f"Could not inspect {path.name}: {exc}"

    if file_size <= 0:
        return False, f"{path.name} is empty."

    try:
        with path.open("rb") as file:
            header = file.read(4096)
    except OSError as exc:
        return False, f"Could not read {path.name}: {exc}"

    # Git LFS pointer detection.
    lfs_prefix = b"version https://git-lfs.github.com/spec/v1"

    if header.startswith(lfs_prefix):
        return (
            False,
            f"GitHub returned a Git LFS pointer for {path.name} "
            "instead of the executable binary.",
        )

    # HTML/error page detection.
    lower = header.lower()

    if (
        b"<html" in lower
        or b"<!doctype html" in lower
        or b"<head" in lower
        or b"<body" in lower
    ):
        return (
            False,
            f"GitHub returned HTML instead of the executable {path.name}.",
        )

    # Windows PE starts with MZ.
    if len(header) < 64 or header[:2] != b"MZ":
        return (
            False,
            f"{path.name} does not have a valid Windows MZ executable header.",
        )

    try:
        pe_offset = int.from_bytes(
            header[0x3C:0x40],
            "little",
            signed=False,
        )
    except Exception:
        return False, f"{path.name} has an invalid PE header offset."

    if pe_offset < 0 or pe_offset + 4 > file_size:
        return False, f"{path.name} has an invalid PE header."

    try:
        with path.open("rb") as file:
            file.seek(pe_offset)
            signature = file.read(4)
    except OSError as exc:
        return False, f"Could not inspect PE header of {path.name}: {exc}"

    if signature != b"PE\x00\x00":
        return (
            False,
            f"{path.name} has an MZ header but is not a valid PE executable.",
        )

    return True, f"{path.name} verified as a Windows PE executable."


# ============================================================
# Remote HTTP helpers
# ============================================================

def http_request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = NETWORK_TIMEOUT,
) -> bytes:
    request_headers = {
        "User-Agent": USER_AGENT,
    }

    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        url,
        headers=request_headers,
        method="GET",
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:
        return response.read()


def http_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> dict:
    payload = http_request(
        url,
        headers=headers,
        timeout=NETWORK_TIMEOUT,
    )

    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"GitHub returned invalid JSON: {exc}"
        ) from exc

    if not isinstance(value, dict):
        raise RuntimeError("GitHub returned an unexpected API response.")

    return value


# ============================================================
# Release discovery
# ============================================================

def choose_release_asset(
    assets: list[dict],
    wanted_name: str,
) -> dict | None:
    target = wanted_name.casefold()

    # Exact filename first.
    for asset in assets:
        name = str(asset.get("name", "")).casefold()

        if name == target:
            return asset

    # Then tolerate harmless capitalization differences.
    for asset in assets:
        name = str(asset.get("name", ""))

        if name.casefold() == target:
            return asset

    return None


def get_latest_release_assets() -> tuple[str, dict[str, str], dict[str, int | None]]:
    """
    Return:
        release label,
        filename -> download URL,
        filename -> optional release asset size
    """

    data = http_json(
        GITHUB_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
        },
    )

    tag_name = str(
        data.get("tag_name")
        or data.get("name")
        or "latest"
    )

    raw_assets = data.get("assets", [])

    if not isinstance(raw_assets, list):
        raise RuntimeError(
            "GitHub release metadata did not contain a valid assets list."
        )

    assets = [
        item for item in raw_assets
        if isinstance(item, dict)
    ]

    wave_asset = choose_release_asset(
        assets,
        "Wave Hub.exe",
    )

    ide_asset = choose_release_asset(
        assets,
        "ide.exe",
    )

    if wave_asset is None or ide_asset is None:
        missing = []

        if wave_asset is None:
            missing.append("Wave Hub.exe")

        if ide_asset is None:
            missing.append("ide.exe")

        raise RuntimeError(
            "The latest GitHub release is missing required asset(s): "
            + ", ".join(missing)
        )

    wave_url = str(
        wave_asset.get("browser_download_url")
        or ""
    ).strip()

    ide_url = str(
        ide_asset.get("browser_download_url")
        or ""
    ).strip()

    if not wave_url or not ide_url:
        raise RuntimeError(
            "The latest GitHub release contains the assets, "
            "but their download URLs are unavailable."
        )

    sizes = {
        "Wave Hub.exe": (
            int(wave_asset["size"])
            if str(wave_asset.get("size", "")).isdigit()
            else None
        ),
        "ide.exe": (
            int(ide_asset["size"])
            if str(ide_asset.get("size", "")).isdigit()
            else None
        ),
    }

    urls = {
        "Wave Hub.exe": wave_url,
        "ide.exe": ide_url,
    }

    return tag_name, urls, sizes


# ============================================================
# GNU GPL fetching
# ============================================================

def license_is_valid(text: str) -> bool:
    normalized = text.upper()

    required_fragments = [
        "GNU GENERAL PUBLIC LICENSE",
        "VERSION 3",
        "END OF TERMS AND CONDITIONS",
    ]

    return all(
        fragment in normalized
        for fragment in required_fragments
    )


def load_cached_license() -> str | None:
    for location in (
        LICENSE_CACHE,
        ensure_storage_dir() / LICENSE_CACHE_NAME,
    ):
        try:
            text = location.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        if license_is_valid(text):
            return text

    return None


def fetch_gpl_text() -> tuple[str, str]:
    """
    Fetch the GNU GPL v3 text from GNU's official web site.

    The function tries both current and old-license locations.
    A valid cached official copy is used only after network attempts fail.
    """

    errors: list[str] = []

    headers = {
        "Accept": "text/plain,text/*;q=0.9,*/*;q=0.8",
    }

    for url in GNU_GPL_URLS:
        try:
            payload = http_request(
                url,
                headers=headers,
                timeout=25,
            )

            text = payload.decode(
                "utf-8",
                errors="replace",
            )

            if not license_is_valid(text):
                raise RuntimeError(
                    "The downloaded document did not look like GNU GPL v3.0."
                )

            cache_path = ensure_storage_dir() / LICENSE_CACHE_NAME

            try:
                cache_path.write_text(
                    text,
                    encoding="utf-8",
                )
            except OSError:
                pass

            return text, url

        except Exception as exc:
            errors.append(
                f"{url}: {exc}"
            )

    cached = load_cached_license()

    if cached:
        return cached, "cached official GNU GPL v3.0 copy"

    raise RuntimeError(
        "Could not fetch GNU GPL v3.0 from the official GNU site.\n\n"
        + "\n".join(errors)
    )


# ============================================================
# Quicksand fetching
# ============================================================

def extract_font_urls(css_text: str) -> list[str]:
    matches = re.findall(
        r"url\((['\"]?)(https?://[^)'\"]+)\1\)",
        css_text,
        flags=re.IGNORECASE,
    )

    results: list[str] = []

    for _, url in matches:
        if url not in results:
            results.append(url)

    return results


def load_cached_quicksand() -> bool:
    locations = [
        FONT_CACHE,
        ensure_storage_dir() / FONT_CACHE_NAME,
    ]

    for path in locations:
        try:
            if not path.exists():
                continue

            if path.stat().st_size <= 0:
                continue

            font_id = QFontDatabase.addApplicationFont(str(path))

            if font_id != -1:
                return True

        except Exception:
            continue

    return False


def fetch_quicksand() -> bool:
    """
    Fetch Quicksand remotely.

    It first asks Google Fonts for the CSS and extracts the current font URL.
    This is more resilient than hardcoding a single raw-font URL.
    """

    errors: list[str] = []

    css_headers = {
        "Accept": "text/css,*/*;q=0.8",
    }

    try:
        css_bytes = http_request(
            GOOGLE_FONTS_CSS_URL,
            headers=css_headers,
            timeout=25,
        )

        css_text = css_bytes.decode(
            "utf-8",
            errors="replace",
        )

        font_urls = extract_font_urls(css_text)

        if font_urls:
            for font_url in font_urls:
                try:
                    font_bytes = http_request(
                        font_url,
                        headers={
                            # Google Fonts sometimes varies its response
                            # based on the browser's User-Agent.
                            "Accept": "font/ttf,font/otf,*/*;q=0.8",
                        },
                        timeout=30,
                    )

                    if len(font_bytes) < 1024:
                        raise RuntimeError(
                            "Returned font data is unexpectedly small."
                        )

                    cache_path = ensure_storage_dir() / FONT_CACHE_NAME

                    try:
                        cache_path.write_bytes(font_bytes)
                    except OSError:
                        pass

                    font_id = QFontDatabase.addApplicationFont(
                        str(cache_path)
                    )

                    if font_id != -1:
                        return True

                    # The cache may have failed because of filesystem issues.
                    temp_font = ensure_storage_dir() / (
                        f"Quicksand-{random.randint(1000, 9999)}.ttf"
                    )

                    try:
                        temp_font.write_bytes(font_bytes)
                        font_id = QFontDatabase.addApplicationFont(
                            str(temp_font)
                        )

                        if font_id != -1:
                            return True
                    except Exception:
                        pass

                except Exception as exc:
                    errors.append(
                        f"{font_url}: {exc}"
                    )

    except Exception as exc:
        errors.append(
            f"Google Fonts CSS: {exc}"
        )

    # Raw GitHub fallback.
    for url in QUICKSAND_FALLBACK_FONT_URLS:
        try:
            font_bytes = http_request(
                url,
                headers={
                    "Accept": "font/ttf,*/*;q=0.8",
                },
                timeout=30,
            )

            if len(font_bytes) < 1024:
                raise RuntimeError(
                    "Returned font data is unexpectedly small."
                )

            cache_path = ensure_storage_dir() / FONT_CACHE_NAME

            try:
                cache_path.write_bytes(font_bytes)
            except OSError:
                pass

            font_id = QFontDatabase.addApplicationFont(
                str(cache_path)
            )

            if font_id != -1:
                return True

        except Exception as exc:
            errors.append(
                f"{url}: {exc}"
            )

    # Cached copy is the final font fallback.
    if load_cached_quicksand():
        return True

    return False


# ============================================================
# Download worker
# ============================================================

class DownloadWorker(QThread):
    progress = pyqtSignal(int)
    file_status = pyqtSignal(str)
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        downloads: list[tuple[str, str, Path, int | None]],
        parent=None,
    ):
        super().__init__(parent)

        self.downloads = downloads
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            known_total = sum(
                size or 0
                for _, _, _, size in self.downloads
            )

            known_downloaded = 0

            for index, (
                display_name,
                url,
                destination,
                known_size,
            ) in enumerate(self.downloads):

                if self._cancel.is_set():
                    return

                self.file_status.emit(
                    f"Downloading {display_name}..."
                )

                destination.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                temp = destination.with_name(
                    destination.name + ".download"
                )

                try:
                    temp.unlink(missing_ok=True)
                except Exception:
                    pass

                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": (
                            "application/octet-stream,"
                            "application/x-msdownload,"
                            "*/*"
                        ),
                    },
                    method="GET",
                )

                try:
                    with urllib.request.urlopen(
                        request,
                        timeout=NETWORK_TIMEOUT,
                    ) as response, temp.open("wb") as output:

                        content_length = response.headers.get(
                            "Content-Length"
                        )

                        if (
                            content_length
                            and content_length.isdigit()
                        ):
                            expected_size = int(
                                content_length
                            )
                        else:
                            expected_size = known_size

                        current = 0

                        while True:
                            if self._cancel.is_set():
                                try:
                                    temp.unlink(
                                        missing_ok=True
                                    )
                                except Exception:
                                    pass
                                return

                            chunk = response.read(
                                DOWNLOAD_CHUNK_SIZE
                            )

                            if not chunk:
                                break

                            output.write(chunk)
                            current += len(chunk)

                            if known_total > 0:
                                percentage = int(
                                    (
                                        known_downloaded
                                        + current
                                    )
                                    * 100
                                    / known_total
                                )
                                self.progress.emit(
                                    max(0, min(100, percentage))
                                )
                            elif expected_size:
                                base = int(
                                    index
                                    * 100
                                    / len(self.downloads)
                                )
                                span = 100 / len(
                                    self.downloads
                                )

                                local_percentage = min(
                                    1.0,
                                    current / expected_size
                                )

                                overall = int(
                                    base
                                    + local_percentage * span
                                )

                                self.progress.emit(
                                    max(0, min(100, overall))
                                )

                    # Do NOT use an arbitrary "must be 1 KB" rule.
                    # Validate the actual file format instead.
                    valid, message = inspect_pe_file(
                        temp
                    )

                    if not valid:
                        raise RuntimeError(message)

                    actual_size = temp.stat().st_size

                    if known_size and actual_size != known_size:
                        # GitHub can technically send a changed asset while
                        # metadata is stale. This is a warning, not an
                        # automatic rejection.
                        self.file_status.emit(
                            f"{display_name} downloaded "
                            f"({format_bytes(actual_size)})."
                        )

                    temp.replace(destination)

                except urllib.error.HTTPError as exc:
                    try:
                        temp.unlink(
                            missing_ok=True
                        )
                    except Exception:
                        pass

                    raise RuntimeError(
                        f"HTTP {exc.code} while downloading "
                        f"{display_name}: {exc.reason}"
                    ) from exc

                except urllib.error.URLError as exc:
                    try:
                        temp.unlink(
                            missing_ok=True
                        )
                    except Exception:
                        pass

                    raise RuntimeError(
                        f"Network error while downloading "
                        f"{display_name}: {exc.reason}"
                    ) from exc

                except Exception:
                    try:
                        temp.unlink(
                            missing_ok=True
                        )
                    except Exception:
                        pass

                    raise

                known_downloaded += (
                    known_size
                    if known_size
                    else actual_size
                )

                if known_total > 0:
                    self.progress.emit(
                        max(
                            0,
                            min(
                                100,
                                int(
                                    known_downloaded
                                    * 100
                                    / known_total
                                )
                            ),
                        )
                    )
                else:
                    self.progress.emit(
                        int(
                            (index + 1)
                            * 100
                            / len(self.downloads)
                        )
                    )

            self.progress.emit(100)

            self.succeeded.emit(
                "All Wave Hub binaries were downloaded and verified."
            )

        except Exception as exc:
            self.failed.emit(str(exc))


# ============================================================
# License worker
# ============================================================

class LicenseWorker(QThread):
    loaded = pyqtSignal(str, str)
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            text, source = fetch_gpl_text()
            self.loaded.emit(text, source)
        except Exception as exc:
            self.failed.emit(str(exc))


# ============================================================
# Font worker
# ============================================================

class FontWorker(QThread):
    finished = pyqtSignal(bool)

    def run(self) -> None:
        success = fetch_quicksand()
        self.finished.emit(success)


# ============================================================
# Sidebar
# ============================================================

class StepList(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("StepList")
        self.setFocusPolicy(
            Qt.FocusPolicy.NoFocus
        )

        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

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


# ============================================================
# Wizard window
# ============================================================

class WizardWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            f"{APP_NAME} {APP_VERSION}"
        )

        self.setMinimumSize(
            1000,
            680,
        )

        self.resize(
            1080,
            720,
        )

        self.current_step = 0

        self.auth_code = ""
        self.code_path: Path | None = None
        self.auth_attempts = 0
        self.auth_verified = False

        self.license_text = ""
        self.license_source = ""

        self.install_path = DEFAULT_INSTALL_DIR

        self.release_tag = ""
        self.release_urls: dict[str, str] = {}
        self.release_sizes: dict[str, int | None] = {}

        self.download_worker: DownloadWorker | None = None
        self.license_worker: LicenseWorker | None = None
        self.font_worker: FontWorker | None = None

        self.install_ok = False
        self.installation_in_progress = False
        self.launch_after_install = True

        self._build_ui()
        self._apply_style()

        self._initialize_font()

        self._load_authentication_code()

        self.show_step(0)

        self._fetch_license()

    # --------------------------------------------------------
    # UI
    # --------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()

        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        root_layout.setSpacing(0)

        self.steps = StepList()
        root_layout.addWidget(
            self.steps,
            0,
        )

        right = QWidget()

        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(
            34,
            28,
            34,
            24,
        )
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
        self.subtitle.setObjectName(
            "PageSubtitle"
        )
        self.subtitle.setWordWrap(True)

        right_layout.addWidget(self.title)
        right_layout.addWidget(self.subtitle)

        self.pages = QWidget()

        self.page_layout = QVBoxLayout(
            self.pages
        )
        self.page_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        self.page_layout.setSpacing(0)

        right_layout.addWidget(
            self.pages,
            1,
        )

        footer_line = QFrame()
        footer_line.setFrameShape(
            QFrame.Shape.HLine
        )
        footer_line.setObjectName(
            "FooterLine"
        )

        right_layout.addWidget(
            footer_line
        )

        footer = QHBoxLayout()

        self.cancel_button = QPushButton(
            "Cancel"
        )

        self.back_button = QPushButton(
            "< Back"
        )

        self.next_button = QPushButton(
            "Next >"
        )

        self.finish_button = QPushButton(
            "Finish"
        )
        self.finish_button.setObjectName(
            "PrimaryButton"
        )

        footer.addWidget(
            self.cancel_button
        )

        footer.addStretch()

        footer.addWidget(
            self.back_button
        )

        footer.addWidget(
            self.next_button
        )

        footer.addWidget(
            self.finish_button
        )

        right_layout.addLayout(
            footer
        )

        root_layout.addWidget(
            right,
            1,
        )

        self.setCentralWidget(root)

        self.cancel_button.clicked.connect(
            self.cancel
        )

        self.back_button.clicked.connect(
            self.back
        )

        self.next_button.clicked.connect(
            self.next
        )

        self.finish_button.clicked.connect(
            self.finish
        )

        self._build_pages()

    def _build_pages(self) -> None:
        self.page_widgets: list[QWidget] = [
            self._page_welcome(),
            self._page_license(),
            self._page_install_location(),
            self._page_auth(),
            self._page_review(),
            self._page_installing(),
            self._page_done(),
        ]

        for page in self.page_widgets:
            self.page_layout.addWidget(page)
            page.hide()

    def _card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        return card

    # --------------------------------------------------------
    # Welcome
    # --------------------------------------------------------

    def _page_welcome(self) -> QWidget:
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(
            0,
            10,
            0,
            0,
        )
        layout.setSpacing(16)

        hero = self._card()

        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(
            28,
            28,
            28,
            28,
        )
        hero_layout.setSpacing(10)

        heading = QLabel(
            "Install Wave Hub"
        )
        heading.setObjectName(
            "CardTitle"
        )

        description = QLabel(
            "Wave Hub is a lightweight development "
            "environment built around a focused editor,\n"
            "project explorer, smart editing, search and "
            "replace, command palette, and file runners."
        )
        description.setWordWrap(True)
        description.setObjectName(
            "CardText"
        )

        hero_layout.addWidget(
            heading
        )

        hero_layout.addWidget(
            description
        )

        features = QLabel(
            "• Python, C, C++, Rust, and Go project starters\n"
            "• Cascadia Code editor with syntax highlighting and smart editing\n"
            "• Tabs, dirty-state tracking, save-all, zoom, Find, Replace, and F5 run\n"
            "• Explorer context actions and return-to-Welcome project lifecycle\n"
            "• Lightweight native PyQt6 interface"
        )

        features.setObjectName(
            "CardText"
        )

        features.setWordWrap(True)

        hero_layout.addWidget(
            features
        )

        layout.addWidget(
            hero
        )

        layout.addStretch()

        return page

    # --------------------------------------------------------
    # License
    # --------------------------------------------------------

    def _page_license(self) -> QWidget:
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(
            0,
            10,
            0,
            0,
        )
        layout.setSpacing(10)

        self.license_status = QLabel(
            "Fetching GNU GPL v3.0..."
        )
        self.license_status.setObjectName(
            "InfoText"
        )

        layout.addWidget(
            self.license_status
        )

        self.license_box = QPlainTextEdit()
        self.license_box.setReadOnly(True)
        self.license_box.setPlaceholderText(
            "The GNU GPL v3.0 text will appear here."
        )

        layout.addWidget(
            self.license_box,
            1,
        )

        self.license_note = QLabel(
            "Wave Hub is distributed under "
            "the GNU General Public License, version 3.0."
        )

        self.license_note.setObjectName(
            "InfoText"
        )

        self.license_note.setWordWrap(
            True
        )

        layout.addWidget(
            self.license_note
        )

        return page

    # --------------------------------------------------------
    # Install location
    # --------------------------------------------------------

    def _page_install_location(self) -> QWidget:
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(
            0,
            10,
            0,
            0,
        )
        layout.setSpacing(16)

        card = self._card()

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(
            24,
            24,
            24,
            24,
        )
        card_layout.setSpacing(12)

        heading = QLabel(
            "Where should Wave Hub be installed?"
        )
        heading.setObjectName(
            "CardTitle"
        )

        card_layout.addWidget(
            heading
        )

        row = QHBoxLayout()

        self.install_edit = QLineEdit(
            str(self.install_path)
        )

        self.install_edit.textChanged.connect(
            self._on_install_path_changed
        )

        self.browse_button = QPushButton(
            "Browse..."
        )

        self.browse_button.clicked.connect(
            self.browse_install_path
        )

        row.addWidget(
            self.install_edit,
            1,
        )

        row.addWidget(
            self.browse_button
        )

        card_layout.addLayout(
            row
        )

        self.path_preview = QLabel()

        self.path_preview.setObjectName(
            "PathPreview"
        )

        self.path_preview.setWordWrap(
            True
        )

        card_layout.addWidget(
            self.path_preview
        )

        self.path_check = QLabel()

        self.path_check.setObjectName(
            "InfoText"
        )

        self.path_check.setWordWrap(
            True
        )

        card_layout.addWidget(
            self.path_check
        )

        self.path_checkbox = QCheckBox(
            "Add Wave Hub to my user PATH"
        )

        self.path_checkbox.setChecked(
            True
        )

        card_layout.addWidget(
            self.path_checkbox
        )

        note = QLabel(
            "The installer uses a per-user install location "
            "by default, so administrator access is not required."
        )

        note.setObjectName(
            "MutedText"
        )

        note.setWordWrap(
            True
        )

        card_layout.addWidget(
            note
        )

        layout.addWidget(
            card
        )

        layout.addStretch()

        self._on_install_path_changed(
            str(self.install_path)
        )

        return page

    # --------------------------------------------------------
    # Authentication
    # --------------------------------------------------------

    def _page_auth(self) -> QWidget:
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(
            0,
            10,
            0,
            0,
        )
        layout.setSpacing(16)

        card = self._card()

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(
            24,
            24,
            24,
            24,
        )
        card_layout.setSpacing(12)

        heading = QLabel(
            "Authentication Code"
        )

        heading.setObjectName(
            "CardTitle"
        )

        card_layout.addWidget(
            heading
        )

        text = QLabel(
            "A six-character authentication code was generated "
            "when this installer opened.\n"
            "Enter the code stored in code.txt to continue. "
            "You have three attempts."
        )

        text.setObjectName(
            "CardText"
        )

        text.setWordWrap(
            True
        )

        card_layout.addWidget(
            text
        )

        self.auth_input = QLineEdit()

        self.auth_input.setPlaceholderText(
            "Enter 6-character code"
        )

        self.auth_input.setMaxLength(
            6
        )

        self.auth_input.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.auth_input.setFont(
            QFont(
                "Cascadia Code",
                18,
            )
        )

        self.auth_input.setInputMethodHints(
            Qt.InputMethodHint.ImhLatinOnly
        )

        self.auth_input.textChanged.connect(
            self._on_auth_text_changed
        )

        self.auth_input.returnPressed.connect(
            self.verify_auth_code
        )

        card_layout.addWidget(
            self.auth_input
        )

        self.auth_status = QLabel()

        self.auth_status.setObjectName(
            "InfoText"
        )

        self.auth_status.setWordWrap(
            True
        )

        card_layout.addWidget(
            self.auth_status
        )

        self.auth_hint = QLabel()

        self.auth_hint.setObjectName(
            "MutedText"
        )

        self.auth_hint.setWordWrap(
            True
        )

        card_layout.addWidget(
            self.auth_hint
        )

        layout.addWidget(
            card
        )

        layout.addStretch()

        return page

    # --------------------------------------------------------
    # Review
    # --------------------------------------------------------

    def _page_review(self) -> QWidget:
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(
            0,
            10,
            0,
            0,
        )
        layout.setSpacing(16)

        card = self._card()

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(
            24,
            24,
            24,
            24,
        )
        card_layout.setSpacing(12)

        heading = QLabel(
            "Review your installation"
        )

        heading.setObjectName(
            "CardTitle"
        )

        card_layout.addWidget(
            heading
        )

        self.review_list = QLabel()

        self.review_list.setObjectName(
            "ReviewText"
        )

        self.review_list.setTextFormat(
            Qt.TextFormat.RichText
        )

        self.review_list.setWordWrap(
            True
        )

        card_layout.addWidget(
            self.review_list
        )

        note = QLabel(
            "The installer will download the current "
            "Wave Hub.exe and ide.exe assets from the "
            "latest GitHub release when available."
        )

        note.setObjectName(
            "MutedText"
        )

        note.setWordWrap(
            True
        )

        card_layout.addWidget(
            note
        )

        layout.addWidget(
            card
        )

        layout.addStretch()

        return page

    # --------------------------------------------------------
    # Installing
    # --------------------------------------------------------

    def _page_installing(self) -> QWidget:
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(
            0,
            10,
            0,
            0,
        )
        layout.setSpacing(16)

        card = self._card()

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(
            24,
            24,
            24,
            24,
        )
        card_layout.setSpacing(14)

        self.install_status = QLabel(
            "Preparing installation..."
        )

        self.install_status.setObjectName(
            "CardTitle"
        )

        self.install_status.setWordWrap(
            True
        )

        card_layout.addWidget(
            self.install_status
        )

        self.progress = QProgressBar()

        self.progress.setRange(
            0,
            100,
        )

        self.progress.setValue(
            0
        )

        self.progress.setTextVisible(
            True
        )

        card_layout.addWidget(
            self.progress
        )

        self.install_details = QLabel(
            "Waiting for download worker..."
        )

        self.install_details.setObjectName(
            "InfoText"
        )

        self.install_details.setWordWrap(
            True
        )

        card_layout.addWidget(
            self.install_details
        )

        layout.addWidget(
            card
        )

        layout.addStretch()

        return page

    # --------------------------------------------------------
    # Done
    # --------------------------------------------------------

    def _page_done(self) -> QWidget:
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(
            0,
            10,
            0,
            0,
        )
        layout.setSpacing(16)

        card = self._card()

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(
            24,
            24,
            24,
            24,
        )
        card_layout.setSpacing(12)

        self.done_title = QLabel(
            "Wave Hub is installed"
        )

        self.done_title.setObjectName(
            "CardTitle"
        )

        card_layout.addWidget(
            self.done_title
        )

        self.done_text = QLabel()

        self.done_text.setObjectName(
            "CardText"
        )

        self.done_text.setWordWrap(
            True
        )

        card_layout.addWidget(
            self.done_text
        )

        self.launch_checkbox = QCheckBox(
            "Launch Wave Hub when I click Finish"
        )

        self.launch_checkbox.setChecked(
            True
        )

        card_layout.addWidget(
            self.launch_checkbox
        )

        layout.addWidget(
            card
        )

        layout.addStretch()

        return page

    # --------------------------------------------------------
    # Styling
    # --------------------------------------------------------

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

            QScrollBar:vertical {
                background: #0f1218;
                width: 10px;
                margin: 0;
            }

            QScrollBar::handle:vertical {
                background: #303744;
                border-radius: 5px;
                min-height: 30px;
            }

            QScrollBar::handle:vertical:hover {
                background: #3c4656;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0;
            }
            """
        )

    # --------------------------------------------------------
    # Font
    # --------------------------------------------------------

    def _initialize_font(self) -> None:
        # Keep the interface usable immediately even before the network font
        # finishes downloading.
        QApplication.instance().setFont(
            QFont(
                "Quicksand",
                10,
            )
        )

        self.font_worker = FontWorker(self)

        self.font_worker.finished.connect(
            self._quicksand_loaded
        )

        self.font_worker.start()

    def _quicksand_loaded(self, success: bool) -> None:
        if not success:
            return

        app = QApplication.instance()

        if app is None:
            return

        app.setFont(
            QFont(
                "Quicksand",
                10,
            )
        )

        # Re-polish the existing widgets now that the remote font is available.
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    # --------------------------------------------------------
    # Authentication loading
    # --------------------------------------------------------

    def _load_authentication_code(self) -> None:
        if is_installer_locked():
            self._show_locked_state()
            return

        try:
            (
                self.auth_code,
                self.code_path,
            ) = load_or_create_auth_code()

            self.auth_status.setText(
                "Authentication is required before installation can continue."
            )

            self.auth_hint.setText(
                "The installer stored the generated code at:\n"
                f"{self.code_path}"
            )

            self._on_auth_text_changed(
                self.auth_input.text()
            )

        except Exception as exc:
            self.auth_status.setText(
                str(exc)
            )
            self.next_button.setEnabled(
                False
            )

    def _show_locked_state(self) -> None:
        self.auth_code = ""
        self.auth_verified = False

        self.auth_status.setText(
            "This installer has been permanently locked "
            "after three invalid authentication attempts."
        )

        self.auth_input.clear()
        self.auth_input.setEnabled(
            False
        )

        self.next_button.setEnabled(
            False
        )

        self.back_button.setEnabled(
            False
        )

        self.auth_hint.setText(
            "A persistent lock marker was found. "
            "This setup instance cannot continue."
        )

    # --------------------------------------------------------
    # GPL
    # --------------------------------------------------------

    def _fetch_license(self) -> None:
        self.license_worker = LicenseWorker(
            self
        )

        self.license_worker.loaded.connect(
            self._license_loaded
        )

        self.license_worker.failed.connect(
            self._license_failed
        )

        self.license_worker.start()

    def _license_loaded(
        self,
        text: str,
        source: str,
    ) -> None:
        self.license_text = text
        self.license_source = source

        self.license_box.setPlainText(
            text
        )

        if source.startswith("http"):
            self.license_status.setText(
                "GNU GPL v3.0 fetched successfully from the official GNU site."
            )
        else:
            self.license_status.setText(
                "GNU GPL v3.0 loaded from the cached official copy."
            )

    def _license_failed(
        self,
        error: str,
    ) -> None:
        self.license_status.setText(
            "Could not fetch GNU GPL v3.0 automatically."
        )

        self.license_box.setPlainText(
            "The GNU GPL v3.0 text could not be downloaded right now.\n\n"
            "Wave Hub is intended to be distributed under GNU GPL v3.0.\n\n"
            "Network error:\n"
            f"{error}\n\n"
            "You may continue, but the online license text is unavailable "
            "for this installer session."
        )

    # --------------------------------------------------------
    # Navigation
    # --------------------------------------------------------

    def show_step(
        self,
        index: int,
    ) -> None:
        index = max(
            0,
            min(
                index,
                len(self.page_widgets) - 1,
            ),
        )

        self.current_step = index

        for i, page in enumerate(
            self.page_widgets
        ):
            page.setVisible(
                i == index
            )

        self.steps.setCurrentRow(
            index
        )

        titles = [
            (
                "Welcome",
                "Review what will be installed before continuing.",
            ),
            (
                "License",
                "GNU GPL v3.0 is fetched directly from the GNU project.",
            ),
            (
                "Install Location",
                "Choose where Wave Hub should live on this PC.",
            ),
            (
                "Authentication Code",
                "Verify the code generated when the installer started.",
            ),
            (
                "Review",
                "Confirm the settings before downloading the binaries.",
            ),
            (
                "Installing...",
                "Downloading and installing Wave Hub.",
            ),
            (
                "Done",
                "Installation completed successfully.",
            ),
        ]

        self.title.setText(
            titles[index][0]
        )

        self.subtitle.setText(
            titles[index][1]
        )

        self.back_button.setVisible(
            index not in (0, 5, 6)
        )

        self.next_button.setVisible(
            index not in (5, 6)
        )

        self.finish_button.setVisible(
            index == 6
        )

        self.cancel_button.setEnabled(
            index != 5
        )

        if index == 0:
            self.next_button.setEnabled(
                True
            )

        elif index == 1:
            self.next_button.setEnabled(
                True
            )

        elif index == 2:
            self.next_button.setEnabled(
                True
            )

        elif index == 3:
            self._on_auth_text_changed(
                self.auth_input.text()
            )

        elif index == 4:
            self._update_review()
            self.next_button.setEnabled(
                True
            )

        elif index == 5:
            self.next_button.setEnabled(
                False
            )

        elif index == 6:
            self.finish_button.setEnabled(
                self.install_ok
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
            self.auth_input.setFocus()
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

    # --------------------------------------------------------
    # Install path
    # --------------------------------------------------------

    def _on_install_path_changed(
        self,
        value: str,
    ) -> None:
        text = value.strip()

        if not text:
            self.path_preview.setText(
                "Files will be installed to:\n"
                "Choose an installation directory."
            )

            self.path_check.setText(
                "Choose an installation directory."
            )

            return

        path = Path(
            text
        ).expanduser()

        self.path_preview.setText(
            "Files will be installed to:\n"
            f"{path}"
        )

        self._validate_path_visual(
            path
        )

    def _validate_path_visual(
        self,
        path: Path,
    ) -> bool:
        try:
            resolved = path.resolve()

            if resolved.parent == resolved:
                self.path_check.setText(
                    "Choose a directory inside a filesystem root."
                )
                return False

        except Exception:
            self.path_check.setText(
                "The selected path could not be resolved."
            )
            return False

        self.path_check.setText(
            "Installation path looks valid."
        )

        return True

    def browse_install_path(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Installation Folder",
            self.install_edit.text().strip()
            or str(DEFAULT_INSTALL_DIR),
        )

        if directory:
            self.install_edit.setText(
                directory
            )

    def validate_install_path(self) -> bool:
        text = self.install_edit.text().strip()

        if not text:
            QMessageBox.warning(
                self,
                APP_NAME,
                "Please choose an installation directory.",
            )
            return False

        path = Path(
            text
        ).expanduser()

        try:
            resolved = path.resolve()

            if resolved.parent == resolved:
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    "Installing directly into a filesystem root "
                    "is not supported.",
                )
                return False

            # Find the nearest existing parent.
            probe_parent = resolved

            while (
                not probe_parent.exists()
                and probe_parent != probe_parent.parent
            ):
                probe_parent = probe_parent.parent

            if not os.access(
                str(probe_parent),
                os.W_OK,
            ):
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    "The selected location is not writable:\n\n"
                    f"{probe_parent}",
                )
                return False

        except Exception as exc:
            QMessageBox.warning(
                self,
                APP_NAME,
                "Invalid installation path:\n"
                f"{exc}",
            )
            return False

        self.install_path = resolved

        return True

    # --------------------------------------------------------
    # Authentication
    # --------------------------------------------------------

    def _on_auth_text_changed(
        self,
        value: str,
    ) -> None:
        normalized = normalize_code(
            value
        )

        if value != normalized:
            cursor_position = self.auth_input.cursorPosition()

            self.auth_input.blockSignals(
                True
            )

            self.auth_input.setText(
                normalized
            )

            self.auth_input.setCursorPosition(
                min(
                    cursor_position,
                    len(normalized),
                )
            )

            self.auth_input.blockSignals(
                False
            )

        if self.auth_verified:
            return

        # This is the important deadlock fix:
        # once six valid characters are present, Next is enabled.
        # Clicking Next or pressing Enter performs verification.
        ready = (
            len(normalized) == 6
            and bool(self.auth_code)
        )

        if self.current_step == 3:
            self.next_button.setEnabled(
                ready
            )

        if not normalized:
            self.auth_status.setText(
                "Enter the six-character authentication code from code.txt."
            )

        elif len(normalized) < 6:
            self.auth_status.setText(
                f"{6 - len(normalized)} more character(s) required."
            )

    def verify_auth_code(self) -> None:
        if self.auth_verified:
            return

        if not self.auth_code:
            return

        entered = normalize_code(
            self.auth_input.text()
        )

        if len(entered) != 6:
            self.auth_status.setText(
                "Enter all six characters before verifying the code."
            )

            self.next_button.setEnabled(
                False
            )

            return

        if entered == self.auth_code:
            self.auth_verified = True

            self.auth_status.setText(
                "Authentication successful. You can continue."
            )

            self.auth_hint.setText(
                "The installer code was verified successfully."
            )

            self.auth_input.setEnabled(
                False
            )

            self.next_button.setEnabled(
                True
            )

            return

        self.auth_attempts += 1

        remaining = (
            MAX_AUTH_ATTEMPTS
            - self.auth_attempts
        )

        if remaining <= 0:
            permanently_lock_installer()

            self.auth_status.setText(
                "Three invalid attempts were entered. "
                "The installer is now permanently locked."
            )

            self.auth_input.setEnabled(
                False
            )

            self.next_button.setEnabled(
                False
            )

            self.back_button.setEnabled(
                False
            )

            self.cancel_button.setText(
                "Close"
            )

            QMessageBox.critical(
                self,
                APP_NAME,
                "Authentication failed three times.\n\n"
                "This installer is now locked and cannot continue.",
            )

            return

        self.auth_status.setText(
            "Incorrect authentication code. "
            f"{remaining} attempt"
            f"{'s' if remaining != 1 else ''} remaining."
        )

        # Re-enable Next after an invalid attempt so another full code
        # can be entered without requiring weird navigation.
        self.next_button.setEnabled(
            False
        )

        self.auth_input.selectAll()
        self.auth_input.setFocus()

    # --------------------------------------------------------
    # Review
    # --------------------------------------------------------

    def _update_review(self) -> None:
        path = Path(
            self.install_edit.text().strip()
        ).expanduser()

        add_path = (
            "Yes"
            if self.path_checkbox.isChecked()
            else "No"
        )

        release = (
            escape_html(self.release_tag)
            if self.release_tag
            else "Latest GitHub release"
        )

        self.review_list.setText(
            f"<b>Installation path</b><br>"
            f"{escape_html(str(path))}"
            f"<br><br>"
            f"<b>Add to user PATH</b><br>"
            f"{add_path}"
            f"<br><br>"
            f"<b>Release source</b><br>"
            f"{release}"
            f"<br><br>"
            f"<b>Files</b><br>"
            f"Wave Hub.exe<br>"
            f"ide.exe"
            f"<br><br>"
            f"<b>Authentication</b><br>"
            f"Verified"
        )

    # --------------------------------------------------------
    # Release setup
    # --------------------------------------------------------

    def _prepare_release_downloads(
        self,
    ) -> tuple[list[tuple[str, str, Path, int | None]], str]:
        """
        Prefer the newest GitHub release's actual release assets.

        If GitHub release metadata cannot be reached, use the known
        repository media URLs as a fallback.
        """

        try:
            (
                release_tag,
                urls,
                sizes,
            ) = get_latest_release_assets()

            self.release_tag = release_tag
            self.release_urls = urls
            self.release_sizes = sizes

            downloads = [
                (
                    "Wave Hub.exe",
                    urls["Wave Hub.exe"],
                    self.install_path / "Wave Hub.exe",
                    sizes.get("Wave Hub.exe"),
                ),
                (
                    "ide.exe",
                    urls["ide.exe"],
                    self.install_path / "ide.exe",
                    sizes.get("ide.exe"),
                ),
            ]

            return (
                downloads,
                f"GitHub release {release_tag}",
            )

        except Exception as release_exc:
            # Fallback remains useful when the GitHub API is temporarily
            # unavailable. We still perform PE validation afterwards.
            self.release_tag = "repository fallback"

            self.release_urls = {
                "Wave Hub.exe": WAVE_HUB_FALLBACK_URL,
                "ide.exe": IDE_FALLBACK_URL,
            }

            self.release_sizes = {
                "Wave Hub.exe": None,
                "ide.exe": None,
            }

            downloads = [
                (
                    "Wave Hub.exe",
                    WAVE_HUB_FALLBACK_URL,
                    self.install_path / "Wave Hub.exe",
                    None,
                ),
                (
                    "ide.exe",
                    IDE_FALLBACK_URL,
                    self.install_path / "ide.exe",
                    None,
                ),
            ]

            return (
                downloads,
                "GitHub repository fallback "
                f"(release lookup unavailable: {release_exc})",
            )

    # --------------------------------------------------------
    # Installation
    # --------------------------------------------------------

    def start_installation(self) -> None:
        if self.installation_in_progress:
            return

        self.install_ok = False
        self.installation_in_progress = True

        self.install_status.setText(
            "Preparing installation..."
        )

        self.install_details.setText(
            str(self.install_path)
        )

        self.progress.setValue(
            0
        )

        try:
            self.install_path.mkdir(
                parents=True,
                exist_ok=True,
            )

        except Exception as exc:
            self.installation_failed(
                f"Could not create the installation directory:\n{exc}"
            )
            return

        try:
            test_file = (
                self.install_path
                / ".wavehub_write_test"
            )

            with test_file.open(
                "wb"
            ) as file:
                file.write(
                    b"ok"
                )

            test_file.unlink(
                missing_ok=True
            )

        except Exception as exc:
            self.installation_failed(
                "The installation directory cannot be written to:\n"
                f"{exc}"
            )
            return

        try:
            (
                downloads,
                source_description,
            ) = self._prepare_release_downloads()

            self.install_details.setText(
                "Source: "
                + source_description
            )

        except Exception as exc:
            self.installation_failed(
                str(exc)
            )
            return

        self.download_worker = DownloadWorker(
            downloads,
            self,
        )

        self.download_worker.progress.connect(
            self.progress.setValue
        )

        self.download_worker.file_status.connect(
            self.install_details.setText
        )

        self.download_worker.succeeded.connect(
            self.installation_succeeded
        )

        self.download_worker.failed.connect(
            self.installation_failed
        )

        self.download_worker.start()

    def installation_succeeded(
        self,
        message: str = "",
    ) -> None:
        self.installation_in_progress = False

        wave_hub_exe = (
            self.install_path / "Wave Hub.exe"
        )

        ide_exe = (
            self.install_path / "ide.exe"
        )

        valid_wave, wave_message = inspect_pe_file(
            wave_hub_exe
        )

        valid_ide, ide_message = inspect_pe_file(
            ide_exe
        )

        if not valid_wave or not valid_ide:
            details = "\n".join(
                value
                for value in (
                    wave_message,
                    ide_message,
                )
                if value
            )

            self.installation_failed(
                "The downloaded files were not valid executables "
                "after installation.\n\n"
                + details
            )

            return

        path_warning = ""

        if self.path_checkbox.isChecked():
            if not add_user_path(
                self.install_path
            ):
                path_warning = (
                    "Wave Hub was installed, but the user PATH "
                    "could not be updated automatically."
                )

        self.install_ok = True
        self.progress.setValue(
            100
        )

        self.install_status.setText(
            "Installation complete."
        )

        self.install_details.setText(
            "Wave Hub.exe and ide.exe installed successfully."
        )

        done_details = (
            f"Wave Hub has been installed to:"
            f"<br><br>"
            f"<b>{escape_html(str(self.install_path))}</b>"
            f"<br><br>"
            f"Both Wave Hub.exe and ide.exe are ready."
        )

        if self.release_tag:
            done_details += (
                f"<br><br>"
                f"Release source: "
                f"<b>{escape_html(self.release_tag)}</b>"
            )

        if path_warning:
            done_details += (
                "<br><br>"
                f"<font color='#d9a441'>"
                f"{escape_html(path_warning)}"
                f"</font>"
            )

            QMessageBox.warning(
                self,
                APP_NAME,
                path_warning,
            )

        self.done_text.setText(
            done_details
        )

        self.show_step(6)

    def installation_failed(
        self,
        error: str,
    ) -> None:
        self.installation_in_progress = False
        self.install_ok = False

        self.install_status.setText(
            "Installation failed."
        )

        self.install_details.setText(
            error
        )

        self.next_button.setEnabled(
            False
        )

        QMessageBox.critical(
            self,
            APP_NAME,
            "Wave Hub could not be installed.\n\n"
            + error,
        )

        self.show_step(4)

    # --------------------------------------------------------
    # Cancel / finish
    # --------------------------------------------------------

    def cancel(self) -> None:
        if self.current_step == 5:
            return

        answer = QMessageBox.question(
            self,
            APP_NAME,
            "Cancel Wave Hub Setup?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer == QMessageBox.StandardButton.Yes:
            self.close()

    def finish(self) -> None:
        if not self.install_ok:
            return

        if self.launch_checkbox.isChecked():
            wave_hub_exe = (
                self.install_path
                / "Wave Hub.exe"
            )

            if not launch_executable(
                wave_hub_exe
            ):
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    "Wave Hub was installed successfully, "
                    "but it could not be launched automatically.\n\n"
                    f"{wave_hub_exe}",
                )

                return

        self.close()

    def closeEvent(self, event) -> None:
        if (
            self.download_worker is not None
            and self.download_worker.isRunning()
        ):
            event.ignore()

            QMessageBox.information(
                self,
                APP_NAME,
                "Installation is still running. "
                "Please wait for it to finish.",
            )

            return

        if (
            self.license_worker is not None
            and self.license_worker.isRunning()
        ):
            self.license_worker.requestInterruption()
            self.license_worker.quit()
            self.license_worker.wait(1500)

        if (
            self.font_worker is not None
            and self.font_worker.isRunning()
        ):
            self.font_worker.requestInterruption()
            self.font_worker.quit()
            self.font_worker.wait(1500)

        event.accept()


# ============================================================
# Main
# ============================================================

def main() -> int:
    app = QApplication(sys.argv)

    app.setApplicationName(
        APP_NAME
    )

    app.setApplicationVersion(
        APP_VERSION
    )

    app.setOrganizationName(
        VENDOR
    )

    # Single-instance behavior is intentionally not enforced here.
    # This keeps the installer portable and avoids requiring extra packages.

    if is_installer_locked():
        QMessageBox.critical(
            None,
            APP_NAME,
            "This Wave Hub installer has been permanently locked "
            "after three invalid authentication attempts.",
        )

        return 1

    # Set a sensible fallback immediately.
    app.setFont(
        QFont(
            "Quicksand",
            10,
        )
    )

    window = WizardWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
