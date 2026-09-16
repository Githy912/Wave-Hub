from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    QEvent,
    QEasingCurve,
    QPropertyAnimation,
    QRegularExpression,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
    QSyntaxHighlighter,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "Wave Hub"

MAX_EXPLORER_DEPTH = 8
MAX_EXPLORER_CHILDREN = 1500
MAX_EXPLORER_TOTAL = 5000

IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".idea",
    ".vs",
    ".venv",
    "venv",
    "node_modules",
    "target",
    "build",
    "dist",
    ".cache",
}

TEXT_ENCODINGS = [
    "utf-8-sig",
    "utf-8",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "utf-32",
    "utf-32-le",
    "utf-32-be",
    "cp1252",
    "latin-1",
    "cp437",
    "cp850",
    "shift_jis",
    "cp932",
    "gb18030",
    "big5",
    "euc-jp",
]

BINARY_CHECK_BYTES = 8192


# ============================================================================
# GLOBAL ERROR HANDLING
# ============================================================================

_exception_dialog_open = False


def crash_log_path() -> Path:
    base = Path(
        os.environ.get(
            "LOCALAPPDATA",
            str(Path.home()),
        )
    )

    directory = base / "Wave" / "Wave Hub"

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return directory / "ide-crash.log"


def write_exception_log(
    exc_type,
    exc_value,
    exc_traceback,
) -> None:
    try:
        with crash_log_path().open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write("\n")
            handle.write("=" * 90)
            handle.write("\n")
            handle.write("Wave Hub IDE exception\n")
            handle.write(
                "".join(
                    traceback.format_exception(
                        exc_type,
                        exc_value,
                        exc_traceback,
                    )
                )
            )
            handle.write("\n")
    except Exception:
        pass


def global_exception_hook(
    exc_type,
    exc_value,
    exc_traceback,
) -> None:
    global _exception_dialog_open

    write_exception_log(
        exc_type,
        exc_value,
        exc_traceback,
    )

    application = QApplication.instance()

    if application is None:
        return

    if _exception_dialog_open:
        return

    _exception_dialog_open = True

    try:
        QMessageBox.critical(
            None,
            "Wave Hub Error",
            (
                "Wave Hub encountered an unexpected error.\n\n"
                "The error was written to:\n"
                f"{crash_log_path()}\n\n"
                f"{exc_value}"
            ),
        )
    finally:
        _exception_dialog_open = False


# ============================================================================
# WINDOWS PROCESS / WELCOME FALLBACK
# ============================================================================

def _no_window_flag() -> int:
    return getattr(
        subprocess,
        "CREATE_NO_WINDOW",
        0,
    )


def _normalise_path(
    path: Path | str,
) -> str:
    try:
        return (
            str(
                Path(path).resolve()
            )
            .replace("/", "\\")
            .rstrip("\\")
            .lower()
        )
    except Exception:
        return (
            str(path)
            .replace("/", "\\")
            .rstrip("\\")
            .lower()
        )


def find_running_welcome(
    main_path: Path,
) -> Optional[int]:
    if os.name != "nt":
        return None

    target = _normalise_path(
        main_path
    )

    command = (
        "$ErrorActionPreference='SilentlyContinue'; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { "
        "$_.Name -eq 'python.exe' -or "
        "$_.Name -eq 'pythonw.exe' "
        "} | "
        "Select-Object ProcessId,CommandLine | "
        "ConvertTo-Json -Compress"
    )

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=_no_window_flag(),
        )

        if result.returncode != 0:
            return None

        if not result.stdout.strip():
            return None

        value = json.loads(
            result.stdout
        )

        if isinstance(
            value,
            dict,
        ):
            value = [value]

        if not isinstance(
            value,
            list,
        ):
            return None

        for entry in value:
            if not isinstance(
                entry,
                dict,
            ):
                continue

            pid = entry.get(
                "ProcessId"
            )

            command_line = (
                entry.get(
                    "CommandLine"
                )
                or ""
            )

            if not pid:
                continue

            normalised_command = (
                command_line
                .replace("/", "\\")
                .lower()
            )

            if target in normalised_command:
                try:
                    return int(pid)
                except Exception:
                    continue

    except Exception:
        return None

    return None


def focus_process(
    pid: int,
) -> bool:
    if os.name != "nt":
        return False

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        EnumWindowsProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            wintypes.HWND,
            wintypes.LPARAM,
        )

        found = {
            "hwnd": None,
        }

        def callback(
            hwnd,
            _lparam,
        ):
            process_id = wintypes.DWORD()

            user32.GetWindowThreadProcessId(
                hwnd,
                ctypes.byref(process_id),
            )

            if process_id.value != pid:
                return True

            if not user32.IsWindowVisible(
                hwnd
            ):
                return True

            found["hwnd"] = hwnd
            return False

        user32.EnumWindows(
            EnumWindowsProc(callback),
            0,
        )

        hwnd = found["hwnd"]

        if not hwnd:
            return False

        if user32.IsIconic(
            hwnd
        ):
            user32.ShowWindow(
                hwnd,
                9,
            )

        user32.SetForegroundWindow(
            hwnd
        )

        return True

    except Exception:
        return False


def launch_welcome_fallback() -> bool:
    main_path = (
        Path(__file__)
        .resolve()
        .with_name("main.py")
    )

    if not main_path.is_file():
        return False

    existing = find_running_welcome(
        main_path
    )

    if existing:
        return focus_process(
            existing
        )

    try:
        subprocess.Popen(
            [
                sys.executable,
                str(main_path),
            ],
            cwd=str(
                main_path.parent
            ),
            creationflags=_no_window_flag(),
            close_fds=True,
        )

        return True

    except Exception:
        return False


# ============================================================================
# LANGUAGE DETECTION
# ============================================================================

LANGUAGE_MAP = {
    ".py": "Python",
    ".pyw": "Python",

    ".c": "C",
    ".h": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".hh": "C++",

    ".cs": "C#",

    ".rs": "Rust",

    ".go": "Go",

    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",

    ".ts": "TypeScript",
    ".tsx": "TypeScript",

    ".java": "Java",

    ".kt": "Kotlin",
    ".kts": "Kotlin",

    ".swift": "Swift",

    ".php": "PHP",

    ".lua": "Lua",

    ".sql": "SQL",

    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".fish": "Shell",

    ".ps1": "PowerShell",
    ".psm1": "PowerShell",

    ".bat": "Batch",
    ".cmd": "Batch",

    ".json": "JSON",
    ".jsonc": "JSON",

    ".yaml": "YAML",
    ".yml": "YAML",

    ".toml": "TOML",

    ".ini": "INI",
    ".cfg": "INI",
    ".conf": "INI",

    ".asm": "Assembly",
    ".s": "Assembly",

    ".html": "HTML",
    ".htm": "HTML",
    ".xhtml": "HTML",

    ".xml": "XML",
    ".svg": "SVG",

    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "SASS",
    ".less": "Less",

    ".md": "Markdown",
    ".markdown": "Markdown",

    ".tex": "LaTeX",

    ".graphql": "GraphQL",
    ".gql": "GraphQL",

    ".proto": "Protobuf",

    ".dart": "Dart",

    ".hs": "Haskell",
    ".lhs": "Haskell",

    ".pas": "Pascal",
    ".pp": "Pascal",

    ".f90": "Fortran",
    ".f95": "Fortran",
    ".f03": "Fortran",

    ".pl": "Perl",
    ".pm": "Perl",

    ".jl": "Julia",

    ".zig": "Zig",

    ".nim": "Nim",

    ".sol": "Solidity",

    ".r": "R",

    ".vim": "Vimscript",
}


FILENAME_LANGUAGE_MAP = {
    "dockerfile": "Dockerfile",
    "makefile": "Makefile",
    "gnumakefile": "Makefile",
    "cmakelists.txt": "CMake",
    ".editorconfig": "INI",
    ".env": "Shell",
}


def language_for_file(
    path: Path,
) -> str:
    name = path.name.lower()

    if name in FILENAME_LANGUAGE_MAP:
        return FILENAME_LANGUAGE_MAP[name]

    return LANGUAGE_MAP.get(
        path.suffix.lower(),
        "Text",
    )


# ============================================================================
# LANGUAGE PROFILES
# ============================================================================

def word_set(
    value: str,
) -> set[str]:
    return set(
        value.split()
    )


GENERIC_KEYWORDS = word_set(
    """
    if else elif for while do switch case break continue return
    class struct enum interface namespace module import from export
    public private protected static const let var fn def function
    try catch finally throw throws async await yield new delete
    using use package extends implements override virtual operator
    in is as with where match when
    """
)

GENERIC_TYPES = word_set(
    """
    int uint short ushort long ulong float double decimal bool boolean
    char wchar_t string str void byte bytes object any auto size_t
    usize isize u8 u16 u32 u64 i8 i16 i32 i64 f32 f64
    """
)

GENERIC_BUILTINS = word_set(
    """
    print println printf input len range map filter reduce open
    main init self this super
    """
)


def make_profile(
    keywords: str = "",
    types: str = "",
    builtins: str = "",
    booleans: str = "",
    nulls: str = "",
    line_comment: str = "",
    block_comment: Optional[tuple[str, str]] = None,
) -> dict:
    return {
        "keywords": word_set(keywords),
        "types": word_set(types),
        "builtins": word_set(builtins),
        "booleans": word_set(booleans),
        "nulls": word_set(nulls),
        "line_comment": line_comment,
        "block_comment": block_comment,
    }


LANGUAGE_PROFILES = {
    "Python": make_profile(
        """
        and as assert async await break case class continue def del
        elif else except finally for from global if import in is lambda
        match nonlocal not or pass raise return try while with yield
        """,
        """
        int float complex bool bytes bytearray str list tuple dict set
        frozenset object type
        """,
        """
        print len range enumerate zip map filter sum min max abs all any
        open super isinstance issubclass getattr setattr hasattr input
        sorted reversed round
        """,
        "True False",
        "None",
        "#",
    ),

    "C": make_profile(
        """
        auto break case char const continue default do double else enum
        extern float for goto if inline int long register restrict return
        short signed sizeof static struct switch typedef union unsigned
        void volatile while _Bool _Complex _Atomic
        """,
        """
        size_t int8_t int16_t int32_t int64_t uint8_t uint16_t
        uint32_t uint64_t
        """,
        """
        printf scanf malloc calloc realloc free memcpy memset strlen
        """,
        "true false",
        "NULL",
        "//",
    ),

    "C++": make_profile(
        """
        alignas alignof and and_eq asm auto bitand bitor break case catch
        class compl concept const consteval constexpr constinit const_cast
        continue co_await co_return co_yield decltype default delete do
        dynamic_cast else enum explicit export extern false for friend goto
        if inline mutable namespace new noexcept not not_eq nullptr operator
        or or_eq private protected public register reinterpret_cast requires
        return signed sizeof static static_assert static_cast struct
        switch template this thread_local throw true try typedef typeid
        typename union unsigned using virtual void volatile wchar_t while
        xor xor_eq
        """,
        """
        size_t ptrdiff_t int8_t int16_t int32_t int64_t uint8_t uint16_t
        uint32_t uint64_t
        """,
        """
        std vector string map set unordered_map unordered_set cout cin cerr
        endl move forward
        """,
        "true false",
        "nullptr",
        "//",
    ),

    "C#": make_profile(
        """
        abstract as base bool break byte case catch char checked class const
        continue decimal default delegate do double else enum event explicit
        extern false finally fixed float for foreach goto if implicit in int
        interface internal is lock long namespace new null object operator out
        override params private protected public readonly ref return sbyte
        sealed short sizeof stackalloc static string struct switch this throw
        true try typeof uint ulong unchecked unsafe ushort using virtual void
        volatile while async await var record required
        """,
        """
        Task List Dictionary HashSet IEnumerable Action Func
        """,
        """
        Console String Math Convert DateTime
        """,
        "true false",
        "null",
        "//",
    ),

    "Rust": make_profile(
        """
        as async await break const continue crate dyn else enum extern false
        fn for if impl in let loop match mod move mut pub ref return self Self
        static struct super trait true type union unsafe use where while
        """,
        """
        bool char str String Vec Option Result usize isize u8 u16 u32 u64
        u128 i8 i16 i32 i64 i128 f32 f64
        """,
        """
        println print format vec Some None Ok Err Box Rc Arc
        """,
        "true false",
        "None",
        "//",
    ),

    "Go": make_profile(
        """
        break default func interface select case defer go map struct chan else
        goto package switch const fallthrough if range type continue for import
        return var
        """,
        """
        bool string int int8 int16 int32 int64 uint uint8 uint16 uint32
        uint64 uintptr byte rune float32 float64 complex64 complex128
        """,
        """
        append cap close complex copy delete imag len make new panic print
        println real recover
        """,
        "true false",
        "nil",
        "//",
    ),

    "JavaScript": make_profile(
        """
        break case catch class const continue debugger default delete do else
        export extends finally for function if import in instanceof let new
        return super switch this throw try typeof var void while with yield
        async await of static get set
        """,
        """
        Array Object String Number Boolean Promise Map Set Date RegExp
        """,
        """
        console JSON Math parseInt parseFloat setTimeout setInterval
        """,
        "true false",
        "null undefined",
        "//",
    ),

    "TypeScript": make_profile(
        """
        break case catch class const continue debugger default delete do else
        export extends finally for function if import in instanceof let new
        return super switch this throw try typeof var void while with yield
        async await interface type namespace declare abstract implements
        public private protected readonly keyof infer satisfies
        """,
        """
        string number boolean any unknown never void object symbol bigint
        """,
        """
        Array Promise Record Partial Pick Omit Readonly
        """,
        "true false",
        "null undefined",
        "//",
    ),

    "Java": make_profile(
        """
        abstract assert boolean break byte case catch char class const continue
        default do double else enum extends final finally float for goto if
        implements import instanceof int interface long native new package
        private protected public return short static strictfp super switch
        synchronized this throw throws transient try void volatile while var
        record sealed permits
        """,
        """
        String Integer Long Double Float Boolean Object
        """,
        """
        System Math Arrays Collections StringBuilder
        """,
        "true false",
        "null",
        "//",
        ("/*", "*/"),
    ),

    "Kotlin": make_profile(
        """
        as break class continue do else false for fun if in interface is null
        object package return super this throw true try typealias typeof
        val var when while by catch constructor delegate dynamic field file
        finally get import init abstract annotation companion const data enum
        expect external final infix inline inner internal lateinit open operator
        override private protected public reified sealed suspend tailrec vararg
        """,
        """
        Int Long Short Byte Float Double Boolean String Any Unit Nothing
        """,
        """
        println print arrayOf listOf mutableListOf mapOf setOf
        """,
        "true false",
        "null",
        "//",
    ),

    "Swift": make_profile(
        """
        associatedtype class deinit enum extension fileprivate func import init
        inout internal let open operator private protocol public static struct
        subscript typealias var break case continue default defer do else
        fallthrough for guard if in repeat return switch where while as Any catch
        false is nil rethrows super self Self true try throws weak unowned async
        await actor
        """,
        """
        Int UInt Float Double Bool String Character Array Dictionary Set
        """,
        """
        print readLine map filter reduce
        """,
        "true false",
        "nil",
        "//",
    ),

    "PHP": make_profile(
        """
        and or xor while endwhile for endforeach foreach declare enddeclare as
        switch endswitch case default break continue goto function const return
        try catch finally throw if elseif else endif class interface extends
        implements public private protected static abstract final trait namespace
        use global var isset empty echo print match fn
        """,
        """
        int float string bool array object callable iterable
        """,
        """
        strlen count isset empty explode implode json_encode json_decode
        """,
        "true false",
        "null",
        "//",
    ),

    "Lua": make_profile(
        """
        and break do else elseif end false for function goto if in local nil not
        or repeat return then true until while
        """,
        """
        string number boolean table function
        """,
        """
        print pairs ipairs tonumber tostring type next
        """,
        "true false",
        "nil",
        "--",
    ),

    "SQL": make_profile(
        """
        SELECT FROM WHERE INSERT INTO UPDATE DELETE CREATE ALTER DROP TABLE INDEX
        VIEW JOIN LEFT RIGHT INNER OUTER FULL ON AS AND OR NOT NULL VALUES SET
        GROUP BY ORDER HAVING LIMIT OFFSET DISTINCT UNION ALL CASE WHEN THEN ELSE
        END PRIMARY KEY FOREIGN REFERENCES DEFAULT UNIQUE DATABASE SCHEMA
        """,
        """
        INT INTEGER BIGINT SMALLINT VARCHAR CHAR TEXT DATE TIME BOOLEAN DECIMAL
        """,
        """
        COUNT SUM AVG MIN MAX COALESCE CAST CONVERT
        """,
        "TRUE FALSE",
        "NULL",
        "--",
    ),

    "Shell": make_profile(
        """
        if then else elif fi for while in do done case esac function select until
        """,
        "",
        """
        echo printf read cd pwd export unset source alias test
        """,
        "true false",
        "",
        "#",
    ),

    "PowerShell": make_profile(
        """
        if elseif else foreach for while do until switch function class enum
        return break continue throw try catch finally trap param begin process end
        """,
        """
        string int bool object array hashtable datetime
        """,
        """
        Write-Host Write-Output Get-ChildItem Get-Content Set-Content
        Set-Location
        """,
        "$true $false",
        "$null",
        "#",
    ),

    "JSON": make_profile(
        "",
        "",
        "",
        "true false",
        "null",
    ),

    "YAML": make_profile(
        "true false null yes no on off",
        "",
        "",
        "true false yes no on off",
        "null",
        "#",
    ),

    "TOML": make_profile(
        "true false",
        "",
        "",
        "true false",
        "",
        "#",
    ),

    "INI": make_profile(
        "",
        "",
        "",
        "",
        "",
        ";",
    ),

    "Assembly": make_profile(
        """
        mov add sub mul div inc dec cmp test jmp je jne jl jle jg jge call ret
        push pop lea and or xor not shl shr rol ror nop int syscall section
        global extern db dw dd dq equ org bits
        """,
        "",
        "",
        "",
        "",
        ";",
    ),

    "Dockerfile": make_profile(
        """
        FROM RUN CMD LABEL MAINTAINER EXPOSE ENV ADD COPY ENTRYPOINT VOLUME
        USER WORKDIR ARG ONBUILD STOPSIGNAL HEALTHCHECK SHELL
        """,
        "",
        "",
        "",
        "",
        "#",
    ),

    "Makefile": make_profile(
        """
        ifeq ifneq ifdef ifndef else endif include define endef export override
        private
        """,
        "",
        "",
        "",
        "",
        "#",
    ),

    "CMake": make_profile(
        """
        project cmake_minimum_required add_executable add_library
        target_link_libraries target_include_directories set option if elseif
        else endif foreach endforeach while endwhile function endfunction
        """,
        "",
        "",
        "",
        "",
        "#",
    ),

    "GraphQL": make_profile(
        """
        query mutation subscription fragment schema type interface union enum
        input scalar extend directive on
        """,
        "String Int Float Boolean ID",
        "",
        "",
        "null",
        "#",
    ),

    "Protobuf": make_profile(
        """
        syntax package import message enum service rpc returns repeated optional
        required oneof map reserved
        """,
        """
        string bytes int32 int64 uint32 uint64 bool float double
        """,
        "",
        "",
        "",
        "//",
    ),

    "LaTeX": make_profile(
        """
        documentclass usepackage begin end section subsection subsubsection
        textbf textit label ref cite
        """,
        "",
        "",
        "",
        "",
        "%",
    ),

    "SCSS": make_profile(
        """
        @mixin @include @extend @if @else @for @each @while
        """,
        "",
        """
        display position color background margin padding width height
        """,
        "",
        "",
        "//",
    ),

    "SASS": make_profile(
        """
        @mixin @include @extend @if @else @for @each @while
        """,
        "",
        """
        display position color background margin padding width height
        """,
        "",
        "",
        "//",
    ),

    "Less": make_profile(
        """
        @media @import @mixin
        """,
        "",
        """
        display position color background margin padding width height
        """,
        "",
        "",
        "//",
    ),

    "CSS": make_profile(
        """
        @media @supports @keyframes @font-face @import @layer
        """,
        "",
        """
        display position color background margin padding width height font
        border transform
        """,
        "",
        "",
    ),

    "Markdown": make_profile(),

    "HTML": make_profile(),
    "XML": make_profile(),
    "SVG": make_profile(),
}


# ============================================================================
# SYNTAX HIGHLIGHTER
# ============================================================================

class SyntaxTheme:
    keyword = "#c586c0"
    type_ = "#4ec9b0"
    builtin = "#dcdcaa"
    string = "#ce9178"
    number = "#b5cea8"
    comment = "#6a9955"
    decorator = "#d7ba7d"
    directive = "#569cd6"
    boolean = "#569cd6"
    null = "#569cd6"
    tag = "#569cd6"
    attribute = "#9cdcfe"
    heading = "#4ec9b0"
    link = "#569cd6"
    code = "#ce9178"


def make_format(
    color: str,
    bold: bool = False,
    italic: bool = False,
) -> QTextCharFormat:
    format_ = QTextCharFormat()

    format_.setForeground(
        QColor(color)
    )

    if bold:
        format_.setFontWeight(
            QFont.Weight.Bold
        )

    if italic:
        format_.setFontItalic(
            True
        )

    return format_


class WaveSyntaxHighlighter(
    QSyntaxHighlighter
):
    def __init__(
        self,
        document,
        language: str,
    ):
        super().__init__(
            document
        )

        self.language = language
        self.profile = profile_for_language(
            language
        )

        self.formats = {
            "keyword": make_format(
                SyntaxTheme.keyword
            ),
            "type": make_format(
                SyntaxTheme.type_
            ),
            "builtin": make_format(
                SyntaxTheme.builtin
            ),
            "string": make_format(
                SyntaxTheme.string
            ),
            "number": make_format(
                SyntaxTheme.number
            ),
            "comment": make_format(
                SyntaxTheme.comment,
                italic=True,
            ),
            "decorator": make_format(
                SyntaxTheme.decorator
            ),
            "directive": make_format(
                SyntaxTheme.directive
            ),
            "boolean": make_format(
                SyntaxTheme.boolean
            ),
            "null": make_format(
                SyntaxTheme.null
            ),
            "tag": make_format(
                SyntaxTheme.tag,
                bold=True,
            ),
            "attribute": make_format(
                SyntaxTheme.attribute
            ),
            "heading": make_format(
                SyntaxTheme.heading,
                bold=True,
            ),
            "link": make_format(
                SyntaxTheme.link
            ),
            "code": make_format(
                SyntaxTheme.code
            ),
        }

        self.rules = []

        self.build_rules()

    def set_language(
        self,
        language: str,
    ) -> None:
        self.language = language
        self.profile = profile_for_language(
            language
        )

        self.rules.clear()
        self.build_rules()
        self.rehighlight()

    def add_words(
        self,
        words: set[str],
        format_name: str,
    ) -> None:
        if not words:
            return

        escaped = sorted(
            (
                re.escape(value)
                for value in words
                if value
            ),
            key=len,
            reverse=True,
        )

        if not escaped:
            return

        expression = QRegularExpression(
            rf"\b(?:{'|'.join(escaped)})\b"
        )

        self.rules.append(
            (
                expression,
                self.formats[
                    format_name
                ],
            )
        )

    def build_rules(
        self,
    ) -> None:
        self.add_words(
            self.profile["keywords"],
            "keyword",
        )

        self.add_words(
            self.profile["types"],
            "type",
        )

        self.add_words(
            self.profile["builtins"],
            "builtin",
        )

        self.add_words(
            self.profile["booleans"],
            "boolean",
        )

        self.add_words(
            self.profile["nulls"],
            "null",
        )

        self.rules.extend(
            [
                (
                    QRegularExpression(
                        r"\b(?:0[xX][0-9A-Fa-f]+|0[bB][01]+|0[oO][0-7]+|\d+(?:\.\d+)?)\b"
                    ),
                    self.formats[
                        "number"
                    ],
                ),
                (
                    QRegularExpression(
                        r"@[A-Za-z_][A-Za-z0-9_]*"
                    ),
                    self.formats[
                        "decorator"
                    ],
                ),
                (
                    QRegularExpression(
                        r"^\s*(?:#!|#|//|;|%|!)\S?.*$"
                    ),
                    self.formats[
                        "directive"
                    ],
                ),
                (
                    QRegularExpression(
                        r"\b[A-Za-z_][A-Za-z0-9_]*(?=\s*\()"
                    ),
                    self.formats[
                        "builtin"
                    ],
                ),
            ]
        )

        if self.language in {
            "HTML",
            "XML",
            "SVG",
        }:
            self.rules.extend(
                [
                    (
                        QRegularExpression(
                            r"</?[A-Za-z][^>]*?>"
                        ),
                        self.formats[
                            "tag"
                        ],
                    ),
                    (
                        QRegularExpression(
                            r"\b[A-Za-z_:][\w:.-]*(?=\s*=)"
                        ),
                        self.formats[
                            "attribute"
                        ],
                    ),
                ]
            )

        if self.language == "Markdown":
            self.rules.extend(
                [
                    (
                        QRegularExpression(
                            r"^\s*#{1,6}\s+.*"
                        ),
                        self.formats[
                            "heading"
                        ],
                    ),
                    (
                        QRegularExpression(
                            r"`[^`]+`"
                        ),
                        self.formats[
                            "code"
                        ],
                    ),
                    (
                        QRegularExpression(
                            r"\[[^\]]+\]\([^)]+\)"
                        ),
                        self.formats[
                            "link"
                        ],
                    ),
                ]
            )

    def apply_rules(
        self,
        text: str,
    ) -> None:
        for expression, format_ in self.rules:
            matches = expression.globalMatch(
                text
            )

            while matches.hasNext():
                match = matches.next()

                start = match.capturedStart()
                length = match.capturedLength()

                if length > 0:
                    self.setFormat(
                        start,
                        length,
                        format_,
                    )

    def highlightBlock(
        self,
        text: str,
    ) -> None:
        self.setCurrentBlockState(
            0
        )

        self.apply_rules(
            text
        )

        string_patterns = [
            r'"(?:\\.|[^"\\])*"',
            r"'(?:\\.|[^'\\])*'",
        ]

        if self.language == "Markdown":
            string_patterns = [
                r"`[^`]+`"
            ]

        for pattern in string_patterns:
            matches = QRegularExpression(
                pattern
            ).globalMatch(
                text
            )

            while matches.hasNext():
                match = matches.next()

                self.setFormat(
                    match.capturedStart(),
                    match.capturedLength(),
                    self.formats[
                        "string"
                    ],
                )

        line_comment = self.profile.get(
            "line_comment",
            "",
        )

        if line_comment:
            expression = QRegularExpression(
                rf"{re.escape(line_comment)}.*$"
            )

            matches = expression.globalMatch(
                text
            )

            while matches.hasNext():
                match = matches.next()

                self.setFormat(
                    match.capturedStart(),
                    match.capturedLength(),
                    self.formats[
                        "comment"
                    ],
                )

        block_comment = self.profile.get(
            "block_comment"
        )

        if not block_comment:
            return

        start_token, end_token = (
            block_comment
        )

        state = self.previousBlockState()

        if state == 1:
            end_index = text.find(
                end_token
            )

            if end_index == -1:
                self.setFormat(
                    0,
                    len(text),
                    self.formats[
                        "comment"
                    ],
                )

                self.setCurrentBlockState(
                    1
                )

                return

            self.setFormat(
                0,
                end_index + len(end_token),
                self.formats[
                    "comment"
                ],
            )

        search_start = 0

        while True:
            start_index = text.find(
                start_token,
                search_start,
            )

            if start_index < 0:
                break

            end_index = text.find(
                end_token,
                start_index + len(start_token),
            )

            if end_index < 0:
                self.setFormat(
                    start_index,
                    len(text) - start_index,
                    self.formats[
                        "comment"
                    ],
                )

                self.setCurrentBlockState(
                    1
                )

                return

            self.setFormat(
                start_index,
                (
                    end_index
                    + len(end_token)
                    - start_index
                ),
                self.formats[
                    "comment"
                ],
            )

            search_start = (
                end_index
                + len(end_token)
            )


def profile_for_language(
    language: str,
) -> dict:
    return LANGUAGE_PROFILES.get(
        language,
        {
            "keywords": GENERIC_KEYWORDS,
            "types": GENERIC_TYPES,
            "builtins": GENERIC_BUILTINS,
            "booleans": word_set(
                "true false True False"
            ),
            "nulls": word_set(
                "null nil None NULL"
            ),
            "line_comment": "",
            "block_comment": None,
        },
    )


# ============================================================================
# LINE NUMBERS
# ============================================================================

class LineNumberArea(QWidget):
    def __init__(
        self,
        editor: "CodeEditor",
    ):
        super().__init__(
            editor
        )

        self.editor = editor

    def sizeHint(
        self,
    ) -> QSize:
        return QSize(
            self.editor.line_number_area_width(),
            0,
        )

    def paintEvent(
        self,
        event,
    ):
        self.editor.paint_line_numbers(
            event
        )


# ============================================================================
# CODE EDITOR
# ============================================================================

class CodeEditor(
    QPlainTextEdit
):
    dirtyChanged = pyqtSignal(bool)
    cursorInfoChanged = pyqtSignal()
    languageChanged = pyqtSignal(str)

    PAIRS = {
        "(": ")",
        "[": "]",
        "{": "}",
        '"': '"',
        "'": "'",
        "`": "`",
    }

    AUTO_COMMENT_LANGUAGES = set(
        LANGUAGE_PROFILES.keys()
    )

    HTML_LANGUAGES = {
        "HTML",
        "XML",
        "SVG",
    }

    VOID_HTML_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(
        self,
        language: str,
        parent=None,
    ):
        super().__init__(
            parent
        )

        self.language = language
        self.clean_text = ""
        self.encoding = "utf-8"
        self.encoding_warning = ""

        self._ignore_dirty = False

        self._auto_pair_position = -1
        self._auto_pair_text = ""

        self._auto_tag_position = -1
        self._auto_tag_text = ""

        self.editor_zoom = 11

        font = QFont(
            "Cascadia Code"
        )

        font.setStyleHint(
            QFont.StyleHint.Monospace
        )

        font.setPointSize(
            self.editor_zoom
        )

        self.setFont(
            font
        )

        self.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.NoWrap
        )

        self.setFrameShape(
            QFrame.Shape.NoFrame
        )

        self.setUndoRedoEnabled(
            True
        )

        self.setTabStopDistance(
            4
            * self.fontMetrics().horizontalAdvance(
                " "
            )
        )

        self.setStyleSheet(
            """
            QPlainTextEdit {
                background: #0a0c11;
                color: #d4d4d4;
                selection-background-color: #264f78;
                selection-color: #ffffff;
                border: none;
                padding: 10px 10px 10px 0px;
                font-family: "Cascadia Code";
                font-size: 11pt;
            }

            QScrollBar:vertical {
                background: #0a0c11;
                width: 10px;
                margin: 2px 2px 2px 0;
            }

            QScrollBar::handle:vertical {
                background: #2b3140;
                border-radius: 5px;
                min-height: 30px;
            }

            QScrollBar::handle:vertical:hover {
                background: #3b4354;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0;
            }

            QScrollBar:horizontal {
                background: #0a0c11;
                height: 10px;
            }

            QScrollBar::handle:horizontal {
                background: #2b3140;
                border-radius: 5px;
                min-width: 30px;
            }

            QScrollBar::handle:horizontal:hover {
                background: #3b4354;
            }

            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {
                width: 0;
            }
            """
        )

        self.line_number_area = LineNumberArea(
            self
        )

        self.highlighter = WaveSyntaxHighlighter(
            self.document(),
            language,
        )

        self.document().contentsChange.connect(
            self._contents_changed
        )

        self.cursorPositionChanged.connect(
            self._cursor_changed
        )

        self.updateRequest.connect(
            self._update_line_number_area
        )

        self.blockCountChanged.connect(
            self._update_line_number_area_width
        )

        self._update_line_number_area_width(
            0
        )

        self._cursor_changed()

    # ------------------------------------------------------------------
    # Document state
    # ------------------------------------------------------------------

    def set_language(
        self,
        language: str,
    ) -> None:
        self.language = language

        self.highlighter.set_language(
            language
        )

        self.languageChanged.emit(
            language
        )

    def set_file_text(
        self,
        text: str,
        encoding: str,
        warning: str = "",
    ) -> None:
        self._ignore_dirty = True

        try:
            self.setPlainText(
                text
            )

            self.clean_text = text
            self.encoding = encoding
            self.encoding_warning = warning

            self.document().setModified(
                False
            )

            self.clear_auto_pair()
            self.clear_auto_tag()

        finally:
            self._ignore_dirty = False

        self.moveCursor(
            QTextCursor.MoveOperation.Start
        )

        self._cursor_changed()

    def _contents_changed(
        self,
        _position,
        _removed,
        _added,
    ):
        if self._ignore_dirty:
            return

        self.document().setModified(
            self.toPlainText()
            != self.clean_text
        )

        self.dirtyChanged.emit(
            self.document().isModified()
        )

        self._update_line_number_area_width()

    def is_dirty(
        self,
    ) -> bool:
        return self.document().isModified()

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------

    def set_editor_zoom(
        self,
        point_size: int,
    ) -> None:
        point_size = max(
            7,
            min(
                28,
                point_size,
            ),
        )

        self.editor_zoom = point_size

        font = QFont(
            "Cascadia Code"
        )

        font.setStyleHint(
            QFont.StyleHint.Monospace
        )

        font.setPointSize(
            self.editor_zoom
        )

        self.setFont(
            font
        )

        self.setTabStopDistance(
            4
            * self.fontMetrics().horizontalAdvance(
                " "
            )
        )

        self.viewport().update()
        self.line_number_area.update()

        self._update_line_number_area_width()

    def zoom_in(
        self,
    ):
        self.set_editor_zoom(
            self.editor_zoom + 1
        )

    def zoom_out(
        self,
    ):
        self.set_editor_zoom(
            self.editor_zoom - 1
        )

    def zoom_reset(
        self,
    ):
        self.set_editor_zoom(
            11
        )

    # ------------------------------------------------------------------
    # Line numbers
    # ------------------------------------------------------------------

    def line_number_area_width(
        self,
    ) -> int:
        digits = len(
            str(
                max(
                    1,
                    self.blockCount(),
                )
            )
        )

        return (
            22
            + self.fontMetrics().horizontalAdvance(
                "9"
            )
            * digits
        )

    def _update_line_number_area_width(
        self,
        _count=0,
    ):
        width = (
            self.line_number_area_width()
        )

        self.setViewportMargins(
            width,
            0,
            0,
            0,
        )

        self.line_number_area.setGeometry(
            0,
            0,
            width,
            self.height(),
        )

        self.line_number_area.update()

    def _update_line_number_area(
        self,
        rect,
        dy,
    ):
        if dy:
            self.line_number_area.scroll(
                0,
                dy,
            )
        else:
            self.line_number_area.update(
                0,
                rect.y(),
                self.line_number_area.width(),
                rect.height(),
            )

        if rect.contains(
            self.viewport().rect()
        ):
            self._update_line_number_area_width()

    def resizeEvent(
        self,
        event,
    ):
        super().resizeEvent(
            event
        )

        width = (
            self.line_number_area_width()
        )

        self.line_number_area.setGeometry(
            0,
            0,
            width,
            self.height(),
        )

    def paint_line_numbers(
        self,
        event,
    ):
        painter = QPainter(
            self.line_number_area
        )

        painter.fillRect(
            event.rect(),
            QColor("#090b10"),
        )

        block = self.firstVisibleBlock()

        block_number = (
            block.blockNumber()
        )

        top = int(
            self.blockBoundingGeometry(
                block
            )
            .translated(
                self.contentOffset()
            )
            .top()
        )

        bottom = (
            top
            + int(
                self.blockBoundingRect(
                    block
                ).height()
            )
        )

        current_block = (
            self.textCursor()
            .blockNumber()
        )

        while (
            block.isValid()
            and top <= event.rect().bottom()
        ):
            if (
                block.isVisible()
                and bottom >= event.rect().top()
            ):
                number = str(
                    block_number + 1
                )

                painter.setPen(
                    QColor(
                        "#e7edf7"
                        if block_number
                        == current_block
                        else "#4e5668"
                    )
                )

                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width()
                    - 10,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    number,
                )

            block = block.next()

            top = bottom

            if block.isValid():
                bottom = (
                    top
                    + int(
                        self.blockBoundingRect(
                            block
                        ).height()
                    )
                )

            block_number += 1

        painter.end()

    # ------------------------------------------------------------------
    # Cursor
    # ------------------------------------------------------------------

    def _cursor_changed(
        self,
    ):
        selection = QTextEdit.ExtraSelection()

        selection.format.setBackground(
            QColor("#10141c")
        )

        selection.format.setProperty(
            QTextFormat.Property.FullWidthSelection,
            True,
        )

        cursor = self.textCursor()

        cursor.clearSelection()

        selection.cursor = cursor

        self.setExtraSelections(
            [selection]
        )

        self.line_number_area.update()

        self.cursorInfoChanged.emit()

    # ------------------------------------------------------------------
    # Auto pair state
    # ------------------------------------------------------------------

    def clear_auto_pair(
        self,
    ):
        self._auto_pair_position = -1
        self._auto_pair_text = ""

    def clear_auto_tag(
        self,
    ):
        self._auto_tag_position = -1
        self._auto_tag_text = ""

    def auto_pair_valid(
        self,
    ) -> bool:
        if (
            self._auto_pair_position < 0
            or not self._auto_pair_text
        ):
            return False

        source = self.toPlainText()

        end = (
            self._auto_pair_position
            + len(
                self._auto_pair_text
            )
        )

        return (
            end <= len(source)
            and source[
                self._auto_pair_position:end
            ]
            == self._auto_pair_text
        )

    def auto_tag_valid(
        self,
    ) -> bool:
        if (
            self._auto_tag_position < 0
            or not self._auto_tag_text
        ):
            return False

        source = self.toPlainText()

        end = (
            self._auto_tag_position
            + len(
                self._auto_tag_text
            )
        )

        return (
            end <= len(source)
            and source[
                self._auto_tag_position:end
            ]
            == self._auto_tag_text
        )

    # ------------------------------------------------------------------
    # Pair insertion
    # ------------------------------------------------------------------

    def insert_pair(
        self,
        opener: str,
        closer: str,
    ):
        cursor = self.textCursor()

        if cursor.hasSelection():
            selected = cursor.selectedText()

            cursor.insertText(
                opener
                + selected
                + closer
            )

            cursor.setPosition(
                cursor.position()
                - len(closer)
            )

            self.setTextCursor(
                cursor
            )

            self.clear_auto_pair()

            return

        position = cursor.position()

        cursor.insertText(
            opener + closer
        )

        cursor.setPosition(
            position + 1
        )

        self.setTextCursor(
            cursor
        )

        self._auto_pair_position = (
            position + 1
        )

        self._auto_pair_text = closer

    # ------------------------------------------------------------------
    # HTML/XML tag insertion
    # ------------------------------------------------------------------

    def insert_html_closer(
        self,
    ) -> bool:
        if (
            self.language
            not in self.HTML_LANGUAGES
        ):
            return False

        cursor = self.textCursor()

        if cursor.hasSelection():
            return False

        block = cursor.block().text()

        column = (
            cursor.positionInBlock()
        )

        before = block[:column]

        match = re.search(
            r"<([A-Za-z][A-Za-z0-9:_-]*)(?:\s+[^<>]*)?>$",
            before,
        )

        if not match:
            return False

        tag_name = match.group(1)

        if (
            tag_name.lower()
            in self.VOID_HTML_TAGS
        ):
            return False

        closing = (
            f"</{tag_name}>"
        )

        position = cursor.position()

        cursor.insertText(
            closing
        )

        cursor.setPosition(
            position
        )

        self.setTextCursor(
            cursor
        )

        self._auto_tag_position = position
        self._auto_tag_text = closing

        return True

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def continue_comment(
        self,
        cursor: QTextCursor,
    ) -> bool:
        if (
            self.language
            not in self.AUTO_COMMENT_LANGUAGES
        ):
            return False

        prefix = (
            profile_for_language(
                self.language
            ).get(
                "line_comment",
                "",
            )
        )

        if not prefix:
            return False

        block = cursor.block().text()

        if (
            cursor.positionInBlock()
            != len(block)
        ):
            return False

        stripped = block.lstrip()

        if not stripped.startswith(
            prefix
        ):
            return False

        body = stripped[
            len(prefix):
        ]

        if not body.strip():
            return False

        indentation = block[
            :len(block)
            - len(stripped)
        ]

        cursor.beginEditBlock()

        try:
            cursor.insertBlock()

            cursor.insertText(
                indentation
                + prefix
                + " "
            )

        finally:
            cursor.endEditBlock()

        self.setTextCursor(
            cursor
        )

        return True

    # ------------------------------------------------------------------
    # Smart indentation
    # ------------------------------------------------------------------

    def smart_newline(
        self,
        cursor: QTextCursor,
    ) -> bool:
        block = cursor.block().text()

        if (
            cursor.positionInBlock()
            != len(block)
        ):
            return False

        stripped = block.rstrip()

        if not stripped:
            return False

        match = re.match(
            r"^\s*",
            block,
        )

        indentation = (
            match.group(0)
            if match
            else ""
        )

        extra = ""

        if stripped.endswith(
            (
                "{",
                "(",
                "[",
                ":",
            )
        ):
            extra = "    "

        if self.language == "Python":
            if stripped.endswith(
                ":"
            ):
                extra = "    "

        if (
            self.language
            in self.HTML_LANGUAGES
        ):
            if re.search(
                r"<[A-Za-z][^/>]*>$",
                stripped,
            ):
                extra = "    "

        cursor.beginEditBlock()

        try:
            cursor.insertBlock()

            cursor.insertText(
                indentation
                + extra
            )

        finally:
            cursor.endEditBlock()

        self.setTextCursor(
            cursor
        )

        return True

    # ------------------------------------------------------------------
    # Backspace
    # ------------------------------------------------------------------

    def handle_auto_backspace(
        self,
    ) -> bool:
        cursor = self.textCursor()

        if cursor.hasSelection():
            return False

        if self.auto_pair_valid():
            if (
                cursor.position()
                == self._auto_pair_position
            ):
                closer = (
                    self._auto_pair_text
                )

                cursor.setPosition(
                    self._auto_pair_position
                )

                cursor.movePosition(
                    QTextCursor.MoveOperation.NextCharacter,
                    QTextCursor.MoveMode.KeepAnchor,
                    len(closer),
                )

                cursor.removeSelectedText()

                self.setTextCursor(
                    cursor
                )

                self.clear_auto_pair()

                return True

        if self.auto_tag_valid():
            if (
                cursor.position()
                == self._auto_tag_position
            ):
                closing = (
                    self._auto_tag_text
                )

                cursor.setPosition(
                    self._auto_tag_position
                )

                cursor.movePosition(
                    QTextCursor.MoveOperation.NextCharacter,
                    QTextCursor.MoveMode.KeepAnchor,
                    len(closing),
                )

                cursor.removeSelectedText()

                self.setTextCursor(
                    cursor
                )

                self.clear_auto_tag()

                return True

        return False

    # ------------------------------------------------------------------
    # Key handling
    # ------------------------------------------------------------------

    def keyPressEvent(
        self,
        event,
    ):
        text = event.text()
        key = event.key()

        if text:
            if self.auto_pair_valid():
                cursor = self.textCursor()

                if (
                    not cursor.hasSelection()
                    and cursor.position()
                    == self._auto_pair_position
                    and text
                    == self._auto_pair_text
                ):
                    cursor.movePosition(
                        QTextCursor.MoveOperation.NextCharacter
                    )

                    self.setTextCursor(
                        cursor
                    )

                    self.clear_auto_pair()

                    return

        if (
            key
            == Qt.Key.Key_Backspace
            and self.handle_auto_backspace()
        ):
            return

        if key in {
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        }:
            cursor = self.textCursor()

            if not cursor.hasSelection():
                if self.continue_comment(
                    cursor
                ):
                    self.clear_auto_pair()
                    self.clear_auto_tag()
                    return

                if self.smart_newline(
                    cursor
                ):
                    self.clear_auto_pair()
                    self.clear_auto_tag()
                    return

        if (
            text in self.PAIRS
            and not (
                event.modifiers()
                & Qt.KeyboardModifier.ControlModifier
            )
            and not (
                event.modifiers()
                & Qt.KeyboardModifier.AltModifier
            )
        ):
            self.insert_pair(
                text,
                self.PAIRS[text],
            )

            return

        if (
            text == ">"
            and self.language
            in self.HTML_LANGUAGES
            and not self.textCursor().hasSelection()
        ):
            super().keyPressEvent(
                event
            )

            self.insert_html_closer()

            return

        self.clear_auto_pair()
        self.clear_auto_tag()

        super().keyPressEvent(
            event
        )


# ============================================================================
# FILE ENCODING
# ============================================================================

def looks_binary(
    data: bytes,
) -> bool:
    if not data:
        return False

    sample = data[
        :BINARY_CHECK_BYTES
    ]

    if b"\x00" in sample:
        return True

    control_bytes = sum(
        1
        for byte in sample
        if (
            byte < 8
            or (
                14 <= byte < 32
                and byte not in {
                    9,
                    10,
                    13,
                }
            )
        )
    )

    return control_bytes > max(
        8,
        len(sample) // 20,
    )


def decode_text(
    data: bytes,
) -> tuple[str, str, str]:
    if looks_binary(data):
        raise ValueError(
            "This file appears to be binary."
        )

    candidates: list[str] = []

    if data.startswith(
        b"\xef\xbb\xbf"
    ):
        candidates.append(
            "utf-8-sig"
        )

    elif data.startswith(
        b"\xff\xfe\x00\x00"
    ):
        candidates.append(
            "utf-32-le"
        )

    elif data.startswith(
        b"\x00\x00\xfe\xff"
    ):
        candidates.append(
            "utf-32-be"
        )

    elif data.startswith(
        b"\xff\xfe"
    ):
        candidates.append(
            "utf-16-le"
        )

    elif data.startswith(
        b"\xfe\xff"
    ):
        candidates.append(
            "utf-16-be"
        )

    candidates.extend(
        encoding
        for encoding in TEXT_ENCODINGS
        if encoding not in candidates
    )

    for encoding in candidates:
        try:
            text = data.decode(
                encoding
            )

            warning = ""

            if encoding not in {
                "utf-8",
                "utf-8-sig",
            }:
                warning = (
                    f"Encoding: {encoding}"
                )

            return (
                text,
                encoding,
                warning,
            )

        except (
            UnicodeDecodeError,
            LookupError,
        ):
            continue

    return (
        data.decode(
            "utf-8",
            errors="replace",
        ),
        "utf-8",
        "Invalid byte sequences "
        "were replaced.",
    )


def read_text_file(
    path: Path,
) -> tuple[str, str, str]:
    return decode_text(
        path.read_bytes()
    )


def write_text_file(
    path: Path,
    text: str,
    encoding: str,
) -> None:
    with path.open(
        "w",
        encoding=encoding,
        newline="",
    ) as handle:
        handle.write(text)


# ============================================================================
# EDITOR TAB
# ============================================================================

class EditorTab(QWidget):
    dirtyChanged = pyqtSignal(bool)
    metadataChanged = pyqtSignal()

    def __init__(
        self,
        path: Path,
        parent=None,
    ):
        super().__init__(
            parent
        )

        self.path = path.resolve()

        self.language = language_for_file(
            self.path
        )

        self.encoding = "utf-8"
        self.encoding_warning = ""
        self.last_mtime_ns: Optional[int] = None

        self.editor = CodeEditor(
            self.language,
            self,
        )

        layout = QVBoxLayout(
            self
        )

        layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        layout.addWidget(
            self.editor
        )

        self.editor.dirtyChanged.connect(
            self._dirty_changed
        )

        self.editor.cursorInfoChanged.connect(
            self.metadataChanged.emit
        )

        self.load()

    @property
    def is_dirty(
        self,
    ) -> bool:
        return self.editor.is_dirty()

    def _dirty_changed(
        self,
        value: bool,
    ):
        self.dirtyChanged.emit(
            value
        )

        self.metadataChanged.emit()

    def load(
        self,
    ):
        try:
            (
                text,
                encoding,
                warning,
            ) = read_text_file(
                self.path
            )

            self.encoding = encoding
            self.encoding_warning = warning

            self.editor.set_file_text(
                text,
                encoding,
                warning,
            )

            try:
                self.last_mtime_ns = (
                    self.path.stat()
                    .st_mtime_ns
                )

            except OSError:
                self.last_mtime_ns = None

        except PermissionError as exc:
            QMessageBox.critical(
                self.window(),
                "Permission Denied",
                (
                    "Could not read:\n\n"
                    f"{self.path}\n\n"
                    f"{exc}"
                ),
            )

            raise

        except ValueError as exc:
            QMessageBox.warning(
                self.window(),
                "Cannot Open File",
                (
                    f"{self.path.name}\n\n"
                    f"{exc}"
                ),
            )

            raise

        except OSError as exc:
            QMessageBox.critical(
                self.window(),
                "File Error",
                (
                    "Could not read:\n\n"
                    f"{self.path}\n\n"
                    f"{exc}"
                ),
            )

            raise

    def save(
        self,
        force: bool = False,
    ) -> bool:
        try:
            current_mtime = (
                self.path.stat()
                .st_mtime_ns
            )

            if (
                self.is_dirty
                and not force
                and self.last_mtime_ns is not None
                and current_mtime
                != self.last_mtime_ns
            ):
                response = QMessageBox.warning(
                    self.window(),
                    "File Changed Externally",
                    (
                        f"{self.path.name} "
                        "was changed outside "
                        "Wave Hub.\n\n"
                        "Saving will overwrite "
                        "those external changes."
                    ),
                    QMessageBox.StandardButton.Save
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )

                if (
                    response
                    != QMessageBox.StandardButton.Save
                ):
                    return False

            write_text_file(
                self.path,
                self.editor.toPlainText(),
                self.encoding,
            )

            self.editor.clean_text = (
                self.editor.toPlainText()
            )

            self.editor.document().setModified(
                False
            )

            self.last_mtime_ns = (
                self.path.stat()
                .st_mtime_ns
            )

            self.dirtyChanged.emit(
                False
            )

            self.metadataChanged.emit()

            return True

        except UnicodeEncodeError as exc:
            QMessageBox.critical(
                self.window(),
                "Encoding Error",
                (
                    f"Could not save "
                    f"{self.path.name} using "
                    f"{self.encoding}.\n\n"
                    f"{exc}"
                ),
            )

            return False

        except PermissionError as exc:
            QMessageBox.critical(
                self.window(),
                "Permission Denied",
                (
                    "Could not save:\n\n"
                    f"{self.path}\n\n"
                    f"{exc}"
                ),
            )

            return False

        except OSError as exc:
            QMessageBox.critical(
                self.window(),
                "Save Error",
                (
                    "Could not save:\n\n"
                    f"{self.path}\n\n"
                    f"{exc}"
                ),
            )

            return False


# ============================================================================
# FILE EXPLORER
# ============================================================================

class FileExplorer(QWidget):
    fileActivated = pyqtSignal(Path)
    statusMessage = pyqtSignal(str)

    ROLE_PATH = Qt.ItemDataRole.UserRole
    ROLE_DIRECTORY = Qt.ItemDataRole.UserRole + 1
    ROLE_LOADED = Qt.ItemDataRole.UserRole + 2
    ROLE_DEPTH = Qt.ItemDataRole.UserRole + 3

    DUMMY = "__wave_dummy__"

    def __init__(
        self,
        project_path: Path,
        parent=None,
    ):
        super().__init__(
            parent
        )

        self.project_path = (
            project_path.resolve()
        )

        self.loaded_entries = 0

        layout = QVBoxLayout(
            self
        )

        layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        layout.setSpacing(
            0
        )

        header = QFrame()

        header.setFixedHeight(
            42
        )

        header.setStyleSheet(
            """
            QFrame {
                background: #10131b;
                border-bottom: 1px solid #202532;
            }
            """
        )

        header_layout = QHBoxLayout(
            header
        )

        header_layout.setContentsMargins(
            14,
            0,
            10,
            0,
        )

        title = QLabel(
            "EXPLORER"
        )

        title.setStyleSheet(
            """
            QLabel {
                color: #9da7b8;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            """
        )

        refresh = QPushButton(
            "↻"
        )

        refresh.setFixedSize(
            30,
            28,
        )

        refresh.setToolTip(
            "Refresh Explorer"
        )

        refresh.clicked.connect(
            self.refresh
        )

        refresh.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                color: #8892a4;
                border: none;
                border-radius: 8px;
                font-size: 18px;
            }

            QPushButton:hover {
                background: #1b202b;
                color: #ffffff;
            }
            """
        )

        header_layout.addWidget(
            title
        )

        header_layout.addStretch()

        header_layout.addWidget(
            refresh
        )

        self.tree = QTreeWidget()

        self.tree.setHeaderHidden(
            True
        )

        self.tree.setIndentation(
            16
        )

        self.tree.setAnimated(
            True
        )

        self.tree.setUniformRowHeights(
            True
        )

        self.tree.setExpandsOnDoubleClick(
            True
        )

        self.tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )

        self.tree.customContextMenuRequested.connect(
            self.show_context_menu
        )

        self.tree.setStyleSheet(
            """
            QTreeWidget {
                background: #0d1016;
                color: #cbd2de;
                border: none;
                outline: none;
                padding: 8px 6px;
            }

            QTreeWidget::item {
                height: 28px;
                padding: 2px 4px;
                border-radius: 7px;
            }

            QTreeWidget::item:hover {
                background: #171c26;
            }

            QTreeWidget::item:selected {
                background: #1d2737;
                color: #ffffff;
            }

            QScrollBar:vertical {
                background: #0d1016;
                width: 9px;
            }

            QScrollBar::handle:vertical {
                background: #282f3c;
                border-radius: 4px;
                min-height: 30px;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0;
            }
            """
        )

        layout.addWidget(
            header
        )

        layout.addWidget(
            self.tree
        )

        self.tree.itemExpanded.connect(
            self._item_expanded
        )

        self.tree.itemDoubleClicked.connect(
            self._item_double_clicked
        )

        self.refresh()

    # ------------------------------------------------------------------
    # Explorer
    # ------------------------------------------------------------------

    def refresh(
        self,
    ):
        self.tree.clear()

        self.loaded_entries = 0

        root = QTreeWidgetItem(
            [
                "📁  "
                + (
                    self.project_path.name
                    or str(self.project_path)
                )
            ]
        )

        root.setData(
            0,
            self.ROLE_PATH,
            str(self.project_path),
        )

        root.setData(
            0,
            self.ROLE_DIRECTORY,
            True,
        )

        root.setData(
            0,
            self.ROLE_LOADED,
            False,
        )

        root.setData(
            0,
            self.ROLE_DEPTH,
            0,
        )

        self.tree.addTopLevelItem(
            root
        )

        self.add_dummy(
            root
        )

        self.tree.expandItem(
            root
        )

    def add_dummy(
        self,
        item: QTreeWidgetItem,
    ):
        item.addChild(
            QTreeWidgetItem(
                [self.DUMMY]
            )
        )

    def is_dummy(
        self,
        item: QTreeWidgetItem,
    ) -> bool:
        return (
            item.text(0)
            == self.DUMMY
        )

    def enumerate_directory(
        self,
        directory: Path,
        depth: int,
    ) -> list[Path]:
        if (
            depth
            > MAX_EXPLORER_DEPTH
        ):
            return []

        result: list[Path] = []

        try:
            with os.scandir(
                directory
            ) as iterator:
                for entry in iterator:
                    if (
                        self.loaded_entries
                        >= MAX_EXPLORER_TOTAL
                    ):
                        break

                    try:
                        if entry.name in (
                            IGNORED_DIRECTORIES
                        ):
                            continue

                        if entry.is_symlink():
                            continue

                        if entry.is_dir(
                            follow_symlinks=False
                        ):
                            if (
                                entry.name.startswith(".")
                                and entry.name != ".config"
                            ):
                                continue

                            result.append(
                                Path(entry.path)
                            )

                        elif entry.is_file(
                            follow_symlinks=False
                        ):
                            result.append(
                                Path(entry.path)
                            )

                    except OSError:
                        continue

        except (
            PermissionError,
            OSError,
        ):
            return []

        result.sort(
            key=lambda path: (
                not path.is_dir(),
                path.name.lower(),
            )
        )

        return result[
            :MAX_EXPLORER_CHILDREN
        ]

    def _item_expanded(
        self,
        item: QTreeWidgetItem,
    ):
        if self.is_dummy(
            item
        ):
            return

        if not item.data(
            0,
            self.ROLE_DIRECTORY,
        ):
            return

        if item.data(
            0,
            self.ROLE_LOADED,
        ):
            return

        self.populate_directory(
            item
        )

    def populate_directory(
        self,
        item: QTreeWidgetItem,
    ):
        path_value = item.data(
            0,
            self.ROLE_PATH,
        )

        if not path_value:
            return

        directory = Path(
            path_value
        )

        depth = int(
            item.data(
                0,
                self.ROLE_DEPTH,
            )
            or 0
        )

        item.takeChildren()

        item.setData(
            0,
            self.ROLE_LOADED,
            True,
        )

        if (
            depth
            >= MAX_EXPLORER_DEPTH
        ):
            item.addChild(
                QTreeWidgetItem(
                    [
                        "… depth limit reached"
                    ]
                )
            )

            return

        entries = self.enumerate_directory(
            directory,
            depth + 1,
        )

        if not entries:
            item.addChild(
                QTreeWidgetItem(
                    ["Empty"]
                )
            )

            return

        for child in entries:
            if (
                self.loaded_entries
                >= MAX_EXPLORER_TOTAL
            ):
                break

            is_directory = child.is_dir()

            node = QTreeWidgetItem(
                [
                    (
                        "📁  "
                        if is_directory
                        else "📄  "
                    )
                    + child.name
                ]
            )

            node.setData(
                0,
                self.ROLE_PATH,
                str(child),
            )

            node.setData(
                0,
                self.ROLE_DIRECTORY,
                is_directory,
            )

            node.setData(
                0,
                self.ROLE_LOADED,
                False,
            )

            node.setData(
                0,
                self.ROLE_DEPTH,
                depth + 1,
            )

            item.addChild(
                node
            )

            self.loaded_entries += 1

            if (
                is_directory
                and depth + 1
                < MAX_EXPLORER_DEPTH
            ):
                self.add_dummy(
                    node
                )

        if (
            len(entries)
            > MAX_EXPLORER_CHILDREN
        ):
            item.addChild(
                QTreeWidgetItem(
                    [
                        "… too many entries"
                    ]
                )
            )

        if (
            self.loaded_entries
            >= MAX_EXPLORER_TOTAL
        ):
            item.addChild(
                QTreeWidgetItem(
                    [
                        "… explorer safety limit reached"
                    ]
                )
            )

    def _item_double_clicked(
        self,
        item: QTreeWidgetItem,
        _column,
    ):
        if self.is_dummy(
            item
        ):
            return

        if item.data(
            0,
            self.ROLE_DIRECTORY,
        ):
            return

        path_value = item.data(
            0,
            self.ROLE_PATH,
        )

        if not path_value:
            return

        self.fileActivated.emit(
            Path(path_value)
        )

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def show_context_menu(
        self,
        position,
    ):
        item = self.tree.itemAt(
            position
        )

        menu = QMenu(
            self.tree
        )

        if item is None:
            new_folder_action = menu.addAction(
                "New Folder"
            )

            refresh_action = menu.addAction(
                "Refresh Explorer"
            )

            chosen = menu.exec(
                self.tree.viewport().mapToGlobal(
                    position
                )
            )

            if chosen == new_folder_action:
                self.create_folder(
                    self.project_path
                )

            elif chosen == refresh_action:
                self.refresh()

            return

        if self.is_dummy(
            item
        ):
            return

        path_value = item.data(
            0,
            self.ROLE_PATH,
        )

        if not path_value:
            return

        path = Path(
            path_value
        )

        self.tree.setCurrentItem(
            item
        )

        open_action = menu.addAction(
            "Open"
        )

        run_action = None

        if (
            path.is_file()
            and path.suffix.lower()
            in {
                ".py",
                ".pyw",
            }
        ):
            run_action = menu.addAction(
                "Run Python"
            )

        menu.addSeparator()

        rename_action = menu.addAction(
            "Rename"
        )

        delete_action = menu.addAction(
            "Delete"
        )

        if path.is_dir():
            new_file_action = menu.addAction(
                "New File"
            )

            new_folder_action = menu.addAction(
                "New Folder"
            )

        else:
            new_file_action = None
            new_folder_action = None

        menu.addSeparator()

        folder_action = menu.addAction(
            "Open Containing Folder"
        )

        menu.addSeparator()

        refresh_action = menu.addAction(
            "Refresh Explorer"
        )

        chosen = menu.exec(
            self.tree.viewport().mapToGlobal(
                position
            )
        )

        if chosen is None:
            return

        if chosen == open_action:
            if path.is_dir():
                item.setExpanded(
                    not item.isExpanded()
                )
            else:
                self.fileActivated.emit(
                    path
                )

        elif (
            run_action is not None
            and chosen == run_action
        ):
            self.run_python_file(
                path
            )

        elif chosen == rename_action:
            self.rename_path(
                path
            )

        elif chosen == delete_action:
            self.delete_path(
                path
            )

        elif (
            new_file_action is not None
            and chosen == new_file_action
        ):
            self.create_file(
                path
            )

        elif (
            new_folder_action is not None
            and chosen == new_folder_action
        ):
            self.create_folder(
                path
            )

        elif chosen == folder_action:
            self.open_folder(
                path
            )

        elif chosen == refresh_action:
            self.refresh()

    def create_file(
        self,
        directory: Path,
    ):
        name, accepted = QInputDialog.getText(
            self.window(),
            "New File",
            "File name:",
        )

        if not accepted:
            return

        name = name.strip()

        if not name:
            return

        path = (
            directory
            / name
        )

        try:
            if path.exists():
                QMessageBox.warning(
                    self.window(),
                    "File Exists",
                    "That file already exists.",
                )

                return

            path.write_text(
                "",
                encoding="utf-8",
            )

            self.refresh()

            self.fileActivated.emit(
                path
            )

        except OSError as exc:
            QMessageBox.critical(
                self.window(),
                "Create File Error",
                str(exc),
            )

    def create_folder(
        self,
        directory: Path,
    ):
        name, accepted = QInputDialog.getText(
            self.window(),
            "New Folder",
            "Folder name:",
        )

        if not accepted:
            return

        name = name.strip()

        if not name:
            return

        path = (
            directory
            / name
        )

        try:
            path.mkdir()

            self.refresh()

            self.statusMessage.emit(
                f"Created folder {name}"
            )

        except FileExistsError:
            QMessageBox.warning(
                self.window(),
                "Folder Exists",
                "That folder already exists.",
            )

        except OSError as exc:
            QMessageBox.critical(
                self.window(),
                "Create Folder Error",
                str(exc),
            )

    def rename_path(
        self,
        path: Path,
    ):
        name, accepted = QInputDialog.getText(
            self.window(),
            "Rename",
            "New name:",
            text=path.name,
        )

        if not accepted:
            return

        name = name.strip()

        if not name:
            return

        target = (
            path.parent
            / name
        )

        if _normalise_path(
            target
        ) == _normalise_path(
            path
        ):
            return

        try:
            if target.exists():
                QMessageBox.warning(
                    self.window(),
                    "Already Exists",
                    "A file or folder with that name already exists.",
                )

                return

            path.rename(
                target
            )

            self.refresh()

            self.statusMessage.emit(
                f"Renamed to {name}"
            )

        except OSError as exc:
            QMessageBox.critical(
                self.window(),
                "Rename Error",
                str(exc),
            )

    def delete_path(
        self,
        path: Path,
    ):
        response = QMessageBox.question(
            self.window(),
            "Delete",
            (
                "Delete this item?\n\n"
                f"{path}"
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if response != QMessageBox.StandardButton.Yes:
            return

        try:
            if path.is_dir():
                shutil.rmtree(
                    path
                )
            else:
                path.unlink()

            self.refresh()

            self.statusMessage.emit(
                f"Deleted {path.name}"
            )

        except OSError as exc:
            QMessageBox.critical(
                self.window(),
                "Delete Error",
                str(exc),
            )

    def open_folder(
        self,
        path: Path,
    ):
        target = (
            path
            if path.is_dir()
            else path.parent
        )

        try:
            if os.name == "nt":
                os.startfile(
                    str(target)
                )

            elif sys.platform == "darwin":
                subprocess.Popen(
                    [
                        "open",
                        str(target),
                    ]
                )

            else:
                subprocess.Popen(
                    [
                        "xdg-open",
                        str(target),
                    ]
                )

        except Exception as exc:
            QMessageBox.warning(
                self.window(),
                "Could Not Open Folder",
                str(exc),
            )

    def run_python_file(
        self,
        path: Path,
    ):
        try:
            flags = (
                getattr(
                    subprocess,
                    "CREATE_NEW_CONSOLE",
                    0,
                )
                if os.name == "nt"
                else 0
            )

            subprocess.Popen(
                [
                    sys.executable,
                    str(path),
                ],
                cwd=str(
                    path.parent
                ),
                creationflags=flags,
            )

            self.statusMessage.emit(
                f"Running {path.name}"
            )

        except Exception as exc:
            QMessageBox.critical(
                self.window(),
                "Run Python Error",
                (
                    f"Could not run:\n\n"
                    f"{path}\n\n"
                    f"{exc}"
                ),
            )


# ============================================================================
# EDITOR TABS
# ============================================================================

class EditorTabs(QTabWidget):
    currentMetadataChanged = pyqtSignal()

    def __init__(
        self,
        parent=None,
    ):
        super().__init__(
            parent
        )

        self.setTabsClosable(
            True
        )

        self.setMovable(
            True
        )

        self.setDocumentMode(
            True
        )

        self.setElideMode(
            Qt.TextElideMode.ElideMiddle
        )

        self.setStyleSheet(
            """
            QTabWidget::pane {
                border: none;
                background: #0a0c11;
            }

            QTabBar {
                background: #0e1118;
            }

            QTabBar::tab {
                background: #11151d;
                color: #788294;
                padding: 10px 32px 10px 18px;
                margin-right: 1px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                min-width: 110px;
            }

            QTabBar::tab:hover {
                color: #b7c0cf;
                background: #171c25;
            }

            QTabBar::tab:selected {
                color: #f1f5fb;
                background: #0a0c11;
            }

            QTabBar::close-button {
                width: 16px;
                height: 16px;
                subcontrol-position: right;
                subcontrol-origin: padding;
                margin-right: 7px;
                margin-left: 2px;
            }

            QTabBar::close-button:hover {
                background: #2b3342;
                border-radius: 8px;
            }
            """
        )

        self.tabCloseRequested.connect(
            self.close_tab
        )

        self.currentChanged.connect(
            lambda _index:
            self.currentMetadataChanged.emit()
        )

        self.tabBar().installEventFilter(
            self
        )

    def eventFilter(
        self,
        watched,
        event,
    ):
        if (
            watched is self.tabBar()
            and event.type()
            == QEvent.Type.MouseButtonPress
        ):
            if (
                event.button()
                == Qt.MouseButton.MiddleButton
            ):
                index = self.tabBar().tabAt(
                    event.position().toPoint()
                )

                if index >= 0:
                    self.close_tab(
                        index
                    )

                    return True

        return super().eventFilter(
            watched,
            event
        )

    def current_editor_tab(
        self,
    ) -> Optional[EditorTab]:
        widget = self.currentWidget()

        if isinstance(
            widget,
            EditorTab,
        ):
            return widget

        return None

    def open_file(
        self,
        path: Path,
    ) -> Optional[EditorTab]:
        path = path.resolve()

        for index in range(
            self.count()
        ):
            tab = self.widget(
                index
            )

            if not isinstance(
                tab,
                EditorTab,
            ):
                continue

            if (
                _normalise_path(
                    tab.path
                )
                == _normalise_path(
                    path
                )
            ):
                self.setCurrentIndex(
                    index
                )

                return tab

        try:
            tab = EditorTab(
                path,
                self,
            )

        except Exception:
            return None

        tab.dirtyChanged.connect(
            lambda _dirty:
            self.update_tab_title(
                tab
            )
        )

        tab.metadataChanged.connect(
            self.currentMetadataChanged.emit
        )

        index = self.addTab(
            tab,
            path.name,
        )

        self.setCurrentIndex(
            index
        )

        self.update_tab_title(
            tab
        )

        self.animate_new_tab(
            tab
        )

        return tab

    def animate_new_tab(
        self,
        tab: EditorTab,
    ):
        animation = QPropertyAnimation(
            tab,
            b"maximumHeight",
            self,
        )

        old_height = max(
            1,
            tab.height(),
        )

        animation.setDuration(
            180
        )

        animation.setStartValue(
            max(
                60,
                old_height - 24,
            )
        )

        animation.setEndValue(
            16777215
        )

        animation.setEasingCurve(
            QEasingCurve.Type.OutCubic
        )

        setattr(
            tab,
            "_wave_tab_animation",
            animation,
        )

        animation.finished.connect(
            lambda:
            tab.setMaximumHeight(
                16777215
            )
        )

        animation.start()

    def update_tab_title(
        self,
        tab: EditorTab,
    ):
        index = self.indexOf(
            tab
        )

        if index < 0:
            return

        title = (
            "● "
            if tab.is_dirty
            else ""
        ) + tab.path.name

        self.setTabText(
            index,
            title,
        )

        self.setTabToolTip(
            index,
            str(tab.path),
        )

        self.currentMetadataChanged.emit()

    def close_tab(
        self,
        index: int,
        ask: bool = True,
    ) -> bool:
        if (
            index < 0
            or index >= self.count()
        ):
            return True

        tab = self.widget(
            index
        )

        if not isinstance(
            tab,
            EditorTab,
        ):
            self.removeTab(
                index
            )

            return True

        if (
            ask
            and tab.is_dirty
        ):
            response = QMessageBox.question(
                self.window(),
                "Unsaved Changes",
                (
                    f"{tab.path.name} "
                    "has unsaved changes.\n\n"
                    "Save before closing?"
                ),
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )

            if (
                response
                == QMessageBox.StandardButton.Cancel
            ):
                return False

            if (
                response
                == QMessageBox.StandardButton.Save
            ):
                if not tab.save():
                    return False

        self.removeTab(
            index
        )

        tab.deleteLater()

        self.currentMetadataChanged.emit()

        return True

    def close_all(
        self,
        ask: bool = True,
    ) -> bool:
        index = (
            self.count() - 1
        )

        while index >= 0:
            if not self.close_tab(
                index,
                ask,
            ):
                return False

            index -= 1

        return True

    def save_current(
        self,
    ) -> bool:
        tab = self.current_editor_tab()

        if tab is None:
            return True

        return tab.save()

    def save_all(
        self,
    ) -> bool:
        for index in range(
            self.count()
        ):
            tab = self.widget(
                index
            )

            if not isinstance(
                tab,
                EditorTab,
            ):
                continue

            if (
                tab.is_dirty
                and not tab.save()
            ):
                return False

        return True

    def has_unsaved(
        self,
    ) -> bool:
        for index in range(
            self.count()
        ):
            tab = self.widget(
                index
            )

            if (
                isinstance(
                    tab,
                    EditorTab,
                )
                and tab.is_dirty
            ):
                return True

        return False


# ============================================================================
# SEARCH DIALOGS
# ============================================================================

class SearchDialog(QDialog):
    findRequested = pyqtSignal(
        str,
        bool,
        bool,
        bool,
        bool,
    )

    nextRequested = pyqtSignal()
    previousRequested = pyqtSignal()

    def __init__(
        self,
        parent=None,
        title="Find",
    ):
        super().__init__(
            parent
        )

        self.setWindowTitle(
            title
        )

        self.resize(
            560,
            220,
        )

        self.setStyleSheet(
            """
            QDialog {
                background: #10131a;
                color: #d4dbe7;
            }

            QLabel {
                color: #8993a5;
            }

            QLineEdit {
                background: #171c25;
                color: #f1f5fb;
                border: 1px solid #2a3140;
                border-radius: 9px;
                padding: 10px;
            }

            QCheckBox {
                color: #b8c2d1;
                spacing: 7px;
            }

            QPushButton {
                background: #171c25;
                color: #d4dbe7;
                border: 1px solid #293140;
                border-radius: 8px;
                padding: 8px 12px;
            }

            QPushButton:hover {
                background: #202736;
            }
            """
        )

        root = QVBoxLayout(
            self
        )

        root.setContentsMargins(
            16,
            16,
            16,
            16,
        )

        root.setSpacing(
            10
        )

        self.find_input = QLineEdit()

        self.find_input.setPlaceholderText(
            "Find…"
        )

        self.case_check = QCheckBox(
            "Match case"
        )

        self.whole_check = QCheckBox(
            "Whole word"
        )

        self.regex_check = QCheckBox(
            "Regular expression"
        )

        self.wrap_check = QCheckBox(
            "Wrap around"
        )

        self.wrap_check.setChecked(
            True
        )

        options = QHBoxLayout()

        options.addWidget(
            self.case_check
        )

        options.addWidget(
            self.whole_check
        )

        options.addWidget(
            self.regex_check
        )

        options.addWidget(
            self.wrap_check
        )

        options.addStretch()

        button_row = QHBoxLayout()

        self.previous_button = QPushButton(
            "Previous"
        )

        self.next_button = QPushButton(
            "Next"
        )

        close_button = QPushButton(
            "Close"
        )

        button_row.addWidget(
            self.previous_button
        )

        button_row.addWidget(
            self.next_button
        )

        button_row.addStretch()

        button_row.addWidget(
            close_button
        )

        root.addWidget(
            QLabel("Find text")
        )

        root.addWidget(
            self.find_input
        )

        root.addLayout(
            options
        )

        root.addLayout(
            button_row
        )

        self.find_input.textChanged.connect(
            self.emit_find
        )

        self.find_input.returnPressed.connect(
            self.request_next
        )

        self.next_button.clicked.connect(
            self.request_next
        )

        self.previous_button.clicked.connect(
            self.request_previous
        )

        close_button.clicked.connect(
            self.close
        )

    def current_options(
        self,
    ):
        return (
            self.find_input.text(),
            self.case_check.isChecked(),
            self.whole_check.isChecked(),
            self.regex_check.isChecked(),
            self.wrap_check.isChecked(),
        )

    def emit_find(
        self,
    ):
        self.findRequested.emit(
            *self.current_options()
        )

    def request_next(
        self,
    ):
        self.findRequested.emit(
            *self.current_options()
        )

        self.nextRequested.emit()

    def request_previous(
        self,
    ):
        self.findRequested.emit(
            *self.current_options()
        )

        self.previousRequested.emit()


class ReplaceDialog(SearchDialog):
    replaceNextRequested = pyqtSignal()
    replaceAllRequested = pyqtSignal()

    def __init__(
        self,
        parent=None,
    ):
        super().__init__(
            parent,
            "Replace",
        )

        self.resize(
            580,
            270,
        )

        self.replace_input = QLineEdit()

        self.replace_input.setPlaceholderText(
            "Replace with…"
        )

        layout = self.layout()

        layout.insertWidget(
            2,
            QLabel("Replace with")
        )

        layout.insertWidget(
            3,
            self.replace_input
        )

        row = QHBoxLayout()

        replace_next_button = QPushButton(
            "Replace Next"
        )

        replace_all_button = QPushButton(
            "Replace All"
        )

        row.addWidget(
            replace_next_button
        )

        row.addWidget(
            replace_all_button
        )

        row.addStretch()

        layout.insertLayout(
            5,
            row
        )

        replace_next_button.clicked.connect(
            self.replaceNextRequested.emit
        )

        replace_all_button.clicked.connect(
            self.replaceAllRequested.emit
        )

    def replacement_text(
        self,
    ) -> str:
        return self.replace_input.text()


# ============================================================================
# STATUS BAR
# ============================================================================

class IDEStatusBar(QFrame):
    def __init__(
        self,
        parent=None,
    ):
        super().__init__(
            parent
        )

        self.setFixedHeight(
            30
        )

        self.setStyleSheet(
            """
            QFrame {
                background: #0d1016;
                border-top: 1px solid #202532;
            }

            QLabel {
                color: #737d8e;
                font-size: 11px;
            }
            """
        )

        layout = QHBoxLayout(
            self
        )

        layout.setContentsMargins(
            12,
            0,
            12,
            0,
        )

        layout.setSpacing(
            16
        )

        self.message = QLabel(
            "Ready"
        )

        self.filename = QLabel(
            ""
        )

        self.language = QLabel(
            ""
        )

        self.encoding = QLabel(
            ""
        )

        self.indentation = QLabel(
            "Spaces: 4"
        )

        self.cursor = QLabel(
            "Ln 1, Col 1"
        )

        layout.addWidget(
            self.message
        )

        layout.addStretch()

        layout.addWidget(
            self.encoding
        )

        layout.addWidget(
            self.indentation
        )

        layout.addWidget(
            self.filename
        )

        layout.addWidget(
            self.language
        )

        layout.addWidget(
            self.cursor
        )

    def set_status(
        self,
        message: str,
        temporary: bool = False,
    ):
        self.message.setText(
            message
        )

        if temporary:
            effect = QGraphicsOpacityEffect(
                self.message
            )

            self.message.setGraphicsEffect(
                effect
            )

            animation = QPropertyAnimation(
                effect,
                b"opacity",
                self,
            )

            animation.setDuration(
                180
            )

            animation.setStartValue(
                0.25
            )

            animation.setEndValue(
                1.0
            )

            animation.setEasingCurve(
                QEasingCurve.Type.OutCubic
            )

            animation.finished.connect(
                lambda:
                self.message.setGraphicsEffect(
                    None
                )
            )

            setattr(
                self,
                "_status_animation",
                animation,
            )

            animation.start()


# ============================================================================
# COMMAND PALETTE
# ============================================================================

class CommandPalette(QDialog):
    commandTriggered = pyqtSignal(str)

    def __init__(
        self,
        parent=None,
    ):
        super().__init__(
            parent
        )

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )

        self.setModal(
            True
        )

        self.resize(
            650,
            460,
        )

        self.setStyleSheet(
            """
            QDialog {
                background: #10131a;
                border: 1px solid #2a3040;
                border-radius: 18px;
            }

            QLineEdit {
                background: #171b24;
                color: #f1f5fb;
                border: 1px solid #2b3140;
                border-radius: 12px;
                padding: 13px;
                font-size: 14px;
            }

            QListWidget {
                background: transparent;
                color: #bec7d5;
                border: none;
                outline: none;
                padding: 8px;
            }

            QListWidget::item {
                padding: 12px;
                border-radius: 10px;
            }

            QListWidget::item:hover {
                background: #171c26;
            }

            QListWidget::item:selected {
                background: #1d2737;
                color: #ffffff;
            }
            """
        )

        layout = QVBoxLayout(
            self
        )

        layout.setContentsMargins(
            14,
            14,
            14,
            14,
        )

        layout.setSpacing(
            10
        )

        self.search = QLineEdit()

        self.search.setPlaceholderText(
            "Search commands…"
        )

        self.list = QListWidget()

        layout.addWidget(
            self.search
        )

        layout.addWidget(
            self.list
        )

        commands = [
            (
                "New File",
                "new_file",
            ),
            (
                "Open File",
                "open_file",
            ),
            (
                "Save",
                "save",
            ),
            (
                "Save All",
                "save_all",
            ),
            (
                "Find",
                "find",
            ),
            (
                "Replace",
                "replace",
            ),
            (
                "Find Next",
                "find_next",
            ),
            (
                "Find Previous",
                "find_previous",
            ),
            (
                "Close Tab",
                "close_tab",
            ),
            (
                "Close All Tabs",
                "close_all",
            ),
            (
                "Zoom In",
                "zoom_in",
            ),
            (
                "Zoom Out",
                "zoom_out",
            ),
            (
                "Reset Editor Zoom",
                "zoom_reset",
            ),
            (
                "Refresh Explorer",
                "refresh",
            ),
            (
                "Exit Project and Go Back to Welcome",
                "exit",
            ),
        ]

        for title, command_id in commands:
            item = QListWidgetItem(
                title
            )

            item.setData(
                Qt.ItemDataRole.UserRole,
                command_id,
            )

            self.list.addItem(
                item
            )

        self.search.textChanged.connect(
            self.filter_items
        )

        self.search.returnPressed.connect(
            self.activate_current
        )

        self.list.itemActivated.connect(
            self.activate_item
        )

        self.list.setCurrentRow(
            0
        )

        self.search.setFocus()

    def filter_items(
        self,
        text: str,
    ):
        query = (
            text.strip().lower()
        )

        first_visible = -1

        for row in range(
            self.list.count()
        ):
            item = self.list.item(
                row
            )

            visible = (
                not query
                or query
                in item.text().lower()
            )

            item.setHidden(
                not visible
            )

            if (
                visible
                and first_visible < 0
            ):
                first_visible = row

        if first_visible >= 0:
            self.list.setCurrentRow(
                first_visible
            )

    def activate_current(
        self,
    ):
        row = self.list.currentRow()

        if row < 0:
            return

        item = self.list.item(
            row
        )

        if (
            item is None
            or item.isHidden()
        ):
            return

        self.activate_item(
            item
        )

    def activate_item(
        self,
        item: QListWidgetItem,
    ):
        command_id = item.data(
            Qt.ItemDataRole.UserRole
        )

        self.commandTriggered.emit(
            str(command_id)
        )

        self.accept()


# ============================================================================
# IDE WINDOW
# ============================================================================

class IDEWindow(QMainWindow):
    returnToWelcome = pyqtSignal()

    def __init__(
        self,
        project_path: str | Path,
        parent=None,
    ):
        super().__init__(
            parent
        )

        self.project_path = (
            Path(project_path)
            .expanduser()
            .resolve()
        )

        self._closing = False
        self._animations = []

        self._search_dialog: Optional[
            SearchDialog
        ] = None

        self._replace_dialog: Optional[
            ReplaceDialog
        ] = None

        self._last_find_text = ""
        self._last_find_case = False
        self._last_find_whole = False
        self._last_find_regex = False
        self._last_find_wrap = True
        self._last_find_pattern: Optional[
            re.Pattern
        ] = None

        self.setWindowTitle(
            f"{APP_NAME} • "
            f"{self.project_path.name}"
        )

        self.resize(
            1400,
            900,
        )

        self.setMinimumSize(
            1050,
            700,
        )

        self.apply_window_style()

        self.build_ui()

        self.build_menus()

        self.connect_signals()

        self.animate_entrance()

        QTimer.singleShot(
            120,
            lambda:
            self.status.set_status(
                (
                    f"Opened "
                    f"{self.project_path.name}"
                ),
                temporary=True,
            ),
        )

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------

    def apply_window_style(
        self,
    ):
        self.setStyleSheet(
            """
            QMainWindow {
                background: #0a0c11;
            }

            QWidget {
                font-family: Quicksand;
            }

            QPushButton {
                background: #151a23;
                color: #dce3ee;
                border: 1px solid #242b38;
                border-radius: 9px;
                padding: 7px 12px;
            }

            QPushButton:hover {
                background: #1b2230;
                border-color: #344056;
            }

            QPushButton:pressed {
                background: #11151d;
            }
            """
        )

        self.menuBar().setStyleSheet(
            """
            QMenuBar {
                background: #0f1219;
                color: #aab4c3;
                border-bottom: 1px solid #171c25;
            }

            QMenuBar::item {
                padding: 7px 11px;
            }

            QMenuBar::item:selected {
                background: #171c26;
                color: #ffffff;
            }

            QMenu {
                background: #11151d;
                color: #c8d0dd;
                border: 1px solid #2a3040;
                padding: 6px;
            }

            QMenu::item {
                padding: 8px 26px 8px 10px;
                border-radius: 7px;
            }

            QMenu::item:selected {
                background: #1d2737;
                color: #ffffff;
            }
            """
        )

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def build_ui(
        self,
    ):
        central = QWidget()

        root = QVBoxLayout(
            central
        )

        root.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        root.setSpacing(
            0
        )

        self.topbar = self.build_topbar()

        splitter = QSplitter(
            Qt.Orientation.Horizontal
        )

        splitter.setHandleWidth(
            1
        )

        splitter.setStyleSheet(
            """
            QSplitter::handle {
                background: #1b202b;
            }
            """
        )

        self.explorer = FileExplorer(
            self.project_path
        )

        self.tabs = EditorTabs()

        splitter.addWidget(
            self.explorer
        )

        splitter.addWidget(
            self.tabs
        )

        splitter.setSizes(
            [
                300,
                1100,
            ]
        )

        self.status = IDEStatusBar()

        root.addWidget(
            self.topbar
        )

        root.addWidget(
            splitter,
            1,
        )

        root.addWidget(
            self.status
        )

        self.setCentralWidget(
            central
        )

        self.splitter = splitter

    def build_topbar(
        self,
    ) -> QWidget:
        topbar = QFrame()

        topbar.setFixedHeight(
            58
        )

        topbar.setStyleSheet(
            """
            QFrame {
                background: #0f1219;
                border-bottom: 1px solid #202532;
            }
            """
        )

        layout = QHBoxLayout(
            topbar
        )

        layout.setContentsMargins(
            14,
            0,
            14,
            0,
        )

        layout.setSpacing(
            10
        )

        dot = QLabel(
            "●"
        )

        dot.setStyleSheet(
            """
            QLabel {
                color: #6aa8ff;
                font-size: 12px;
            }
            """
        )

        brand = QLabel(
            "Wave Hub"
        )

        brand.setStyleSheet(
            """
            QLabel {
                color: #edf2f8;
                font-weight: 700;
                font-size: 14px;
            }
            """
        )

        separator = QLabel(
            "/"
        )

        separator.setStyleSheet(
            """
            QLabel {
                color: #3b4352;
            }
            """
        )

        project = QLabel(
            self.project_path.name
        )

        project.setStyleSheet(
            """
            QLabel {
                color: #7d8798;
                font-size: 12px;
            }
            """
        )

        self.project_button = QPushButton(
            "Project Folder"
        )

        self.project_button.clicked.connect(
            self.open_project_folder
        )

        self.command_button = QPushButton(
            "Command Palette"
        )

        self.command_button.clicked.connect(
            self.open_command_palette
        )

        layout.addWidget(
            dot
        )

        layout.addWidget(
            brand
        )

        layout.addWidget(
            separator
        )

        layout.addWidget(
            project
        )

        layout.addStretch()

        layout.addWidget(
            self.project_button
        )

        layout.addWidget(
            self.command_button
        )

        return topbar

    # ------------------------------------------------------------------
    # Menus
    # ------------------------------------------------------------------

    def build_menus(
        self,
    ):
        file_menu = self.menuBar().addMenu(
            "&File"
        )

        new_action = QAction(
            "New File",
            self,
        )

        new_action.setShortcut(
            QKeySequence("Ctrl+N")
        )

        new_action.triggered.connect(
            self.new_file
        )

        open_action = QAction(
            "Open File",
            self,
        )

        open_action.setShortcut(
            QKeySequence("Ctrl+O")
        )

        open_action.triggered.connect(
            self.open_file_dialog
        )

        save_action = QAction(
            "Save",
            self,
        )

        save_action.setShortcut(
            QKeySequence("Ctrl+S")
        )

        save_action.triggered.connect(
            self.save_current
        )

        save_all_action = QAction(
            "Save All",
            self,
        )

        save_all_action.setShortcut(
            QKeySequence("Ctrl+Shift+S")
        )

        save_all_action.triggered.connect(
            self.save_all
        )

        close_tab_action = QAction(
            "Close Tab",
            self,
        )

        close_tab_action.setShortcut(
            QKeySequence("Ctrl+W")
        )

        close_tab_action.triggered.connect(
            lambda:
            self.tabs.close_tab(
                self.tabs.currentIndex()
            )
        )

        close_all_action = QAction(
            "Close All Tabs",
            self,
        )

        close_all_action.setShortcut(
            QKeySequence("Ctrl+Shift+W")
        )

        close_all_action.triggered.connect(
            self.close_all_tabs
        )

        refresh_action = QAction(
            "Refresh Explorer",
            self,
        )

        refresh_action.setShortcut(
            QKeySequence("Ctrl+Shift+R")
        )

        refresh_action.triggered.connect(
            self.refresh_explorer
        )

        exit_action = QAction(
            "Exit Project and Go Back to Welcome",
            self,
        )

        exit_action.setShortcut(
            QKeySequence(
                "Ctrl+Shift+Q"
            )
        )

        exit_action.triggered.connect(
            self.exit_project_to_welcome
        )

        file_menu.addAction(
            new_action
        )

        file_menu.addAction(
            open_action
        )

        file_menu.addSeparator()

        file_menu.addAction(
            save_action
        )

        file_menu.addAction(
            save_all_action
        )

        file_menu.addSeparator()

        file_menu.addAction(
            close_tab_action
        )

        file_menu.addAction(
            close_all_action
        )

        file_menu.addSeparator()

        file_menu.addAction(
            refresh_action
        )

        file_menu.addSeparator()

        file_menu.addAction(
            exit_action
        )

        edit_menu = self.menuBar().addMenu(
            "&Edit"
        )

        undo_action = QAction(
            "Undo",
            self,
        )

        undo_action.setShortcut(
            QKeySequence("Ctrl+Z")
        )

        undo_action.triggered.connect(
            self.edit_undo
        )

        redo_action = QAction(
            "Redo",
            self,
        )

        redo_action.setShortcut(
            QKeySequence("Ctrl+Y")
        )

        redo_action.triggered.connect(
            self.edit_redo
        )

        find_action = QAction(
            "Find",
            self,
        )

        find_action.setShortcut(
            QKeySequence("Ctrl+F")
        )

        find_action.triggered.connect(
            self.find_text
        )

        replace_action = QAction(
            "Replace",
            self,
        )

        replace_action.setShortcut(
            QKeySequence("Ctrl+H")
        )

        replace_action.triggered.connect(
            self.replace_text
        )

        next_find_action = QAction(
            "Find Next",
            self,
        )

        next_find_action.setShortcut(
            QKeySequence("F3")
        )

        next_find_action.triggered.connect(
            self.find_next
        )

        previous_find_action = QAction(
            "Find Previous",
            self,
        )

        previous_find_action.setShortcut(
            QKeySequence("Shift+F3")
        )

        previous_find_action.triggered.connect(
            self.find_previous
        )

        edit_menu.addAction(
            undo_action
        )

        edit_menu.addAction(
            redo_action
        )

        edit_menu.addSeparator()

        edit_menu.addAction(
            find_action
        )

        edit_menu.addAction(
            replace_action
        )

        edit_menu.addAction(
            next_find_action
        )

        edit_menu.addAction(
            previous_find_action
        )

        view_menu = self.menuBar().addMenu(
            "&View"
        )

        palette_action = QAction(
            "Command Palette",
            self,
        )

        palette_action.setShortcut(
            QKeySequence(
                "Ctrl+Shift+P"
            )
        )

        palette_action.triggered.connect(
            self.open_command_palette
        )

        zoom_in_action = QAction(
            "Zoom In",
            self,
        )

        zoom_in_action.setShortcut(
            QKeySequence("Ctrl+=")
        )

        zoom_in_action.triggered.connect(
            self.zoom_in
        )

        zoom_out_action = QAction(
            "Zoom Out",
            self,
        )

        zoom_out_action.setShortcut(
            QKeySequence("Ctrl+-")
        )

        zoom_out_action.triggered.connect(
            self.zoom_out
        )

        zoom_reset_action = QAction(
            "Reset Editor Zoom",
            self,
        )

        zoom_reset_action.setShortcut(
            QKeySequence("Ctrl+0")
        )

        zoom_reset_action.triggered.connect(
            self.zoom_reset
        )

        next_tab_action = QAction(
            "Next Tab",
            self,
        )

        next_tab_action.setShortcut(
            QKeySequence("Ctrl+Tab")
        )

        next_tab_action.triggered.connect(
            self.next_tab
        )

        previous_tab_action = QAction(
            "Previous Tab",
            self,
        )

        previous_tab_action.setShortcut(
            QKeySequence(
                "Ctrl+Shift+Tab"
            )
        )

        previous_tab_action.triggered.connect(
            self.previous_tab
        )

        view_menu.addAction(
            palette_action
        )

        view_menu.addSeparator()

        view_menu.addAction(
            zoom_in_action
        )

        view_menu.addAction(
            zoom_out_action
        )

        view_menu.addAction(
            zoom_reset_action
        )

        view_menu.addSeparator()

        view_menu.addAction(
            next_tab_action
        )

        view_menu.addAction(
            previous_tab_action
        )

        run_menu = self.menuBar().addMenu(
            "&Run"
        )

        run_action = QAction(
            "Run Current File",
            self,
        )

        run_action.setShortcut(
            QKeySequence("F5")
        )

        run_action.triggered.connect(
            self.run_file
        )

        run_menu.addAction(
            run_action
        )

        terminal_menu = self.menuBar().addMenu(
            "&Terminal"
        )

        terminal_action = QAction(
            "Open Project Folder",
            self,
        )

        terminal_action.triggered.connect(
            self.open_project_folder
        )

        terminal_menu.addAction(
            terminal_action
        )

        help_menu = self.menuBar().addMenu(
            "&Help"
        )

        about_action = QAction(
            "About Wave Hub",
            self,
        )

        about_action.triggered.connect(
            self.show_about
        )

        help_menu.addAction(
            about_action
        )

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def connect_signals(
        self,
    ):
        self.explorer.fileActivated.connect(
            self.open_file
        )

        self.explorer.statusMessage.connect(
            lambda message:
            self.status.set_status(
                message,
                temporary=True,
            )
        )

        self.tabs.currentMetadataChanged.connect(
            self.update_status
        )

        self.tabs.currentChanged.connect(
            self.tab_changed
        )

    # ------------------------------------------------------------------
    # Animations
    # ------------------------------------------------------------------

    def animate_entrance(
        self,
    ):
        for widget, duration, delay in (
            (
                self.topbar,
                240,
                0,
            ),
            (
                self.explorer,
                300,
                70,
            ),
            (
                self.tabs,
                360,
                110,
            ),
            (
                self.status,
                260,
                170,
            ),
        ):
            effect = QGraphicsOpacityEffect(
                widget
            )

            widget.setGraphicsEffect(
                effect
            )

            effect.setOpacity(
                0.0
            )

            animation = QPropertyAnimation(
                effect,
                b"opacity",
                self,
            )

            animation.setDuration(
                duration
            )

            animation.setStartValue(
                0.0
            )

            animation.setEndValue(
                1.0
            )

            animation.setEasingCurve(
                QEasingCurve.Type.OutCubic
            )

            def finish(
                widget=widget,
                animation=animation,
            ):
                widget.setGraphicsEffect(
                    None
                )

                try:
                    self._animations.remove(
                        animation
                    )
                except ValueError:
                    pass

            animation.finished.connect(
                finish
            )

            self._animations.append(
                animation
            )

            if delay:
                QTimer.singleShot(
                    delay,
                    animation.start,
                )
            else:
                animation.start()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def update_status(
        self,
    ):
        tab = (
            self.tabs.current_editor_tab()
        )

        if tab is None:
            self.status.filename.setText(
                ""
            )

            self.status.language.setText(
                ""
            )

            self.status.encoding.setText(
                ""
            )

            self.status.cursor.setText(
                "Ln 1, Col 1"
            )

            self.status.set_status(
                "Ready"
            )

            return

        cursor = tab.editor.textCursor()

        self.status.filename.setText(
            tab.path.name
        )

        self.status.language.setText(
            tab.language
        )

        self.status.encoding.setText(
            tab.encoding
        )

        self.status.cursor.setText(
            (
                f"Ln "
                f"{cursor.blockNumber() + 1}, "
                f"Col "
                f"{cursor.positionInBlock() + 1}"
            )
        )

        if tab.is_dirty:
            self.status.set_status(
                "Unsaved changes"
            )

        elif tab.encoding_warning:
            self.status.set_status(
                tab.encoding_warning
            )

        else:
            self.status.set_status(
                "Ready"
            )

    def tab_changed(
        self,
        _index,
    ):
        tab = (
            self.tabs.current_editor_tab()
        )

        if tab is not None:
            tab.editor.setUpdatesEnabled(
                True
            )

            tab.editor.viewport().update()
            tab.editor.update()

        self.update_status()

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def open_file(
        self,
        path: Path,
    ):
        try:
            path = path.resolve()

            if not path.exists():
                raise FileNotFoundError(
                    "The file no longer exists."
                )

            if not path.is_file():
                raise IsADirectoryError(
                    "The selected path is not a file."
                )

            tab = self.tabs.open_file(
                path
            )

            if tab is not None:
                self.status.set_status(
                    f"Opened {path.name}",
                    temporary=True,
                )

        except Exception as exc:
            write_exception_log(
                type(exc),
                exc,
                exc.__traceback__,
            )

            QMessageBox.critical(
                self,
                "Open File Error",
                (
                    "Could not open:\n\n"
                    f"{path}\n\n"
                    f"{exc}"
                ),
            )

    def open_file_dialog(
        self,
    ):
        filename, _ = (
            QFileDialog.getOpenFileName(
                self,
                "Open File",
                str(self.project_path),
                "All Files (*.*)",
            )
        )

        if filename:
            self.open_file(
                Path(filename)
            )

    def new_file(
        self,
    ):
        filename, _ = (
            QFileDialog.getSaveFileName(
                self,
                "Create New File",
                str(self.project_path),
                "All Files (*.*)",
            )
        )

        if not filename:
            return

        path = Path(
            filename
        )

        try:
            if path.exists():
                QMessageBox.warning(
                    self,
                    "File Exists",
                    "That file already exists.",
                )

                return

            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            path.write_text(
                "",
                encoding="utf-8",
            )

            self.explorer.refresh()

            self.open_file(
                path
            )

        except OSError as exc:
            QMessageBox.critical(
                self,
                "Create File Error",
                str(exc),
            )

    # ------------------------------------------------------------------
    # Save / close
    # ------------------------------------------------------------------

    def save_current(
        self,
    ):
        if self.tabs.save_current():
            self.status.set_status(
                "Saved",
                temporary=True,
            )

    def save_all(
        self,
    ):
        if self.tabs.save_all():
            self.status.set_status(
                "All files saved",
                temporary=True,
            )

    def close_all_tabs(
        self,
    ):
        if self.tabs.close_all():
            self.status.set_status(
                "All tabs closed",
                temporary=True,
            )

    def confirm_unsaved(
        self,
    ) -> bool:
        if not self.tabs.has_unsaved():
            return True

        response = QMessageBox.question(
            self,
            "Unsaved Changes",
            (
                "There are unsaved changes "
                "in this project.\n\n"
                "Save all changes before "
                "returning to Welcome?"
            ),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )

        if (
            response
            == QMessageBox.StandardButton.Cancel
        ):
            return False

        if (
            response
            == QMessageBox.StandardButton.Save
        ):
            return self.tabs.save_all()

        return True

    # ------------------------------------------------------------------
    # Welcome lifecycle
    # ------------------------------------------------------------------

    def _show_existing_welcome(
        self,
    ) -> bool:
        parent = self.parentWidget()

        if parent is None:
            return False

        try:
            show_welcome = getattr(
                parent,
                "show_welcome",
                None,
            )

            if callable(
                show_welcome
            ):
                show_welcome()
                return True

            parent.show()
            parent.raise_()
            parent.activateWindow()

            return True

        except Exception as exc:
            write_exception_log(
                type(exc),
                exc,
                exc.__traceback__,
            )

            return False

    def _return_to_welcome_now(
        self,
    ):
        if not self._closing:
            return

        self.hide()

        if self.parentWidget() is not None:
            self._show_existing_welcome()

            self.returnToWelcome.emit()

            self.close()

            return

        launch_welcome_fallback()

        self.close()

    def exit_project_to_welcome(
        self,
    ):
        if self._closing:
            return

        if not self.confirm_unsaved():
            return

        self._closing = True

        self.status.set_status(
            "Returning to Welcome…",
            temporary=True,
        )

        QTimer.singleShot(
            0,
            self._return_to_welcome_now,
        )

    def closeEvent(
        self,
        event,
    ):
        if self._closing:
            event.accept()
            return

        if not self.confirm_unsaved():
            event.ignore()
            return

        self._closing = True

        event.ignore()

        QTimer.singleShot(
            0,
            self._return_to_welcome_now,
        )

    # ------------------------------------------------------------------
    # Project folder
    # ------------------------------------------------------------------

    def open_project_folder(
        self,
    ):
        try:
            if os.name == "nt":
                os.startfile(
                    str(self.project_path)
                )

            elif sys.platform == "darwin":
                subprocess.Popen(
                    [
                        "open",
                        str(self.project_path),
                    ]
                )

            else:
                subprocess.Popen(
                    [
                        "xdg-open",
                        str(self.project_path),
                    ]
                )

        except Exception as exc:
            QMessageBox.warning(
                self,
                "Could Not Open Folder",
                str(exc),
            )

    def refresh_explorer(
        self,
    ):
        self.explorer.refresh()

        self.status.set_status(
            "Explorer refreshed",
            temporary=True,
        )

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------

    def edit_undo(
        self,
    ):
        tab = (
            self.tabs.current_editor_tab()
        )

        if tab is not None:
            tab.editor.undo()

    def edit_redo(
        self,
    ):
        tab = (
            self.tabs.current_editor_tab()
        )

        if tab is not None:
            tab.editor.redo()

    def zoom_in(
        self,
    ):
        tab = (
            self.tabs.current_editor_tab()
        )

        if tab is not None:
            tab.editor.zoom_in()

            self.status.set_status(
                f"Editor zoom: {tab.editor.editor_zoom}pt",
                temporary=True,
            )

    def zoom_out(
        self,
    ):
        tab = (
            self.tabs.current_editor_tab()
        )

        if tab is not None:
            tab.editor.zoom_out()

            self.status.set_status(
                f"Editor zoom: {tab.editor.editor_zoom}pt",
                temporary=True,
            )

    def zoom_reset(
        self,
    ):
        tab = (
            self.tabs.current_editor_tab()
        )

        if tab is not None:
            tab.editor.zoom_reset()

            self.status.set_status(
                "Editor zoom reset",
                temporary=True,
            )

    def next_tab(
        self,
    ):
        count = self.tabs.count()

        if count <= 1:
            return

        current = self.tabs.currentIndex()

        self.tabs.setCurrentIndex(
            (current + 1) % count
        )

    def previous_tab(
        self,
    ):
        count = self.tabs.count()

        if count <= 1:
            return

        current = self.tabs.currentIndex()

        self.tabs.setCurrentIndex(
            (current - 1) % count
        )

    # ------------------------------------------------------------------
    # Find / Replace
    # ------------------------------------------------------------------

    def build_find_pattern(
        self,
        query: str,
        case_sensitive: bool,
        whole_word: bool,
        regex: bool,
    ):
        if not query:
            return None

        source = (
            query
            if regex
            else re.escape(query)
        )

        if whole_word:
            source = (
                rf"(?<!\w)(?:{source})(?!\w)"
            )

        flags = 0

        if not case_sensitive:
            flags |= re.IGNORECASE

        flags |= re.MULTILINE

        try:
            return re.compile(
                source,
                flags,
            )

        except re.error as exc:
            QMessageBox.warning(
                self,
                "Invalid Regular Expression",
                str(exc),
            )

            return None

    def remember_find_options(
        self,
        query: str,
        case_sensitive: bool,
        whole_word: bool,
        regex: bool,
        wrap: bool,
    ):
        self._last_find_text = query
        self._last_find_case = case_sensitive
        self._last_find_whole = whole_word
        self._last_find_regex = regex
        self._last_find_wrap = wrap

        self._last_find_pattern = (
            self.build_find_pattern(
                query,
                case_sensitive,
                whole_word,
                regex,
            )
        )

    def find_match(
        self,
        forward: bool = True,
        explicit_wrap: Optional[bool] = None,
    ) -> bool:
        tab = (
            self.tabs.current_editor_tab()
        )

        if tab is None:
            return False

        query = self._last_find_text

        pattern = self._last_find_pattern

        if (
            not query
            or pattern is None
        ):
            return False

        text = tab.editor.toPlainText()

        cursor = tab.editor.textCursor()

        if forward:
            start = cursor.selectionEnd()

            match = pattern.search(
                text,
                start,
            )

            if (
                match is None
                and (
                    explicit_wrap
                    if explicit_wrap is not None
                    else self._last_find_wrap
                )
            ):
                match = pattern.search(
                    text,
                    0,
                )
        else:
            start = cursor.selectionStart()

            matches = list(
                pattern.finditer(
                    text,
                    0,
                    start,
                )
            )

            match = (
                matches[-1]
                if matches
                else None
            )

            if (
                match is None
                and (
                    explicit_wrap
                    if explicit_wrap is not None
                    else self._last_find_wrap
                )
            ):
                matches = list(
                    pattern.finditer(
                        text,
                    )
                )

                match = (
                    matches[-1]
                    if matches
                    else None
                )

        if match is None:
            self.status.set_status(
                "No matches found",
                temporary=True,
            )

            return False

        cursor.setPosition(
            match.start()
        )

        cursor.setPosition(
            match.end(),
            QTextCursor.MoveMode.KeepAnchor,
        )

        tab.editor.setTextCursor(
            cursor
        )

        tab.editor.ensureCursorVisible()

        self.status.set_status(
            (
                "Match found"
                if forward
                else "Previous match found"
            ),
            temporary=True,
        )

        return True

    def find_text(
        self,
    ):
        tab = (
            self.tabs.current_editor_tab()
        )

        if tab is None:
            return

        if self._search_dialog is None:
            self._search_dialog = SearchDialog(
                self,
                "Find",
            )

            self._search_dialog.findRequested.connect(
                self.update_find_options
            )

            self._search_dialog.nextRequested.connect(
                self.find_next
            )

            self._search_dialog.previousRequested.connect(
                self.find_previous
            )

        dialog = self._search_dialog

        dialog.find_input.setText(
            self._last_find_text
        )

        dialog.case_check.setChecked(
            self._last_find_case
        )

        dialog.whole_check.setChecked(
            self._last_find_whole
        )

        dialog.regex_check.setChecked(
            self._last_find_regex
        )

        dialog.wrap_check.setChecked(
            self._last_find_wrap
        )

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        dialog.find_input.setFocus()
        dialog.find_input.selectAll()

    def update_find_options(
        self,
        query: str,
        case_sensitive: bool,
        whole_word: bool,
        regex: bool,
        wrap: bool,
    ):
        self.remember_find_options(
            query,
            case_sensitive,
            whole_word,
            regex,
            wrap,
        )

    def find_next(
        self,
    ):
        if not self._last_find_text:
            self.find_text()
            return

        self.find_match(
            True
        )

    def find_previous(
        self,
    ):
        if not self._last_find_text:
            self.find_text()
            return

        self.find_match(
            False
        )

    def replace_text(
        self,
    ):
        if self.tabs.current_editor_tab() is None:
            return

        if self._replace_dialog is None:
            self._replace_dialog = ReplaceDialog(
                self
            )

            self._replace_dialog.findRequested.connect(
                self.update_find_options
            )

            self._replace_dialog.nextRequested.connect(
                self.find_next
            )

            self._replace_dialog.previousRequested.connect(
                self.find_previous
            )

            self._replace_dialog.replaceNextRequested.connect(
                self.replace_next
            )

            self._replace_dialog.replaceAllRequested.connect(
                self.replace_all
            )

        dialog = self._replace_dialog

        dialog.find_input.setText(
            self._last_find_text
        )

        dialog.case_check.setChecked(
            self._last_find_case
        )

        dialog.whole_check.setChecked(
            self._last_find_whole
        )

        dialog.regex_check.setChecked(
            self._last_find_regex
        )

        dialog.wrap_check.setChecked(
            self._last_find_wrap
        )

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        dialog.find_input.setFocus()
        dialog.find_input.selectAll()

    def replace_next(
        self,
    ):
        dialog = self._replace_dialog

        if dialog is None:
            return

        query = dialog.find_input.text()

        self.update_find_options(
            query,
            dialog.case_check.isChecked(),
            dialog.whole_check.isChecked(),
            dialog.regex_check.isChecked(),
            dialog.wrap_check.isChecked(),
        )

        tab = (
            self.tabs.current_editor_tab()
        )

        if tab is None:
            return

        cursor = tab.editor.textCursor()

        if (
            cursor.hasSelection()
            and cursor.selectedText()
            == cursor.selectedText()
        ):
            selected = cursor.selectedText()

            pattern = (
                self._last_find_pattern
            )

            if (
                pattern is not None
                and pattern.fullmatch(
                    selected
                )
            ):
                cursor.insertText(
                    self.make_replacement(
                        selected,
                        dialog.replacement_text(),
                        pattern,
                    )
                )

                tab.editor.setTextCursor(
                    cursor
                )

                tab.editor.document().setModified(
                    True
                )

                tab.editor.dirtyChanged.emit(
                    True
                )

                self.find_match(
                    True
                )

                return

        self.find_match(
            True
        )

    def make_replacement(
        self,
        matched_text: str,
        replacement: str,
        pattern: re.Pattern,
    ) -> str:
        try:
            return pattern.sub(
                replacement,
                matched_text,
                count=1,
            )
        except re.error:
            return replacement

    def replace_all(
        self,
    ):
        dialog = self._replace_dialog

        if dialog is None:
            return

        query = dialog.find_input.text()

        self.update_find_options(
            query,
            dialog.case_check.isChecked(),
            dialog.whole_check.isChecked(),
            dialog.regex_check.isChecked(),
            dialog.wrap_check.isChecked(),
        )

        tab = (
            self.tabs.current_editor_tab()
        )

        if tab is None:
            return

        pattern = self._last_find_pattern

        if pattern is None:
            return

        replacement = (
            dialog.replacement_text()
        )

        text = tab.editor.toPlainText()

        try:
            new_text, count = (
                pattern.subn(
                    replacement,
                    text,
                )
            )

        except re.error as exc:
            QMessageBox.warning(
                self,
                "Replace Error",
                str(exc),
            )

            return

        if count == 0:
            self.status.set_status(
                "No matches found",
                temporary=True,
            )

            return

        cursor = tab.editor.textCursor()

        position = min(
            cursor.position(),
            len(new_text),
        )

        tab.editor.blockSignals(
            True
        )

        try:
            tab.editor.setPlainText(
                new_text
            )

        finally:
            tab.editor.blockSignals(
                False
            )

        tab.editor.document().setModified(
            True
        )

        tab.editor.clean_text = (
            tab.editor.clean_text
        )

        tab.editor.dirtyChanged.emit(
            True
        )

        cursor = tab.editor.textCursor()

        cursor.setPosition(
            position
        )

        tab.editor.setTextCursor(
            cursor
        )

        self.tabs.update_tab_title(
            tab
        )

        self.status.set_status(
            f"Replaced {count} occurrence(s)",
            temporary=True,
        )

    # ------------------------------------------------------------------
    # Command palette
    # ------------------------------------------------------------------

    def open_command_palette(
        self,
    ):
        palette = CommandPalette(
            self
        )

        effect = QGraphicsOpacityEffect(
            palette
        )

        palette.setGraphicsEffect(
            effect
        )

        effect.setOpacity(
            0.0
        )

        animation = QPropertyAnimation(
            effect,
            b"opacity",
            palette,
        )

        animation.setDuration(
            160
        )

        animation.setStartValue(
            0.0
        )

        animation.setEndValue(
            1.0
        )

        animation.setEasingCurve(
            QEasingCurve.Type.OutCubic
        )

        setattr(
            palette,
            "_wave_palette_animation",
            animation,
        )

        animation.start()

        palette.commandTriggered.connect(
            self.execute_command
        )

        palette.exec()

    def execute_command(
        self,
        command_id: str,
    ):
        commands = {
            "new_file":
                self.new_file,

            "open_file":
                self.open_file_dialog,

            "save":
                self.save_current,

            "save_all":
                self.save_all,

            "find":
                self.find_text,

            "replace":
                self.replace_text,

            "find_next":
                self.find_next,

            "find_previous":
                self.find_previous,

            "close_tab":
                lambda:
                self.tabs.close_tab(
                    self.tabs.currentIndex()
                ),

            "close_all":
                self.close_all_tabs,

            "zoom_in":
                self.zoom_in,

            "zoom_out":
                self.zoom_out,

            "zoom_reset":
                self.zoom_reset,

            "refresh":
                self.refresh_explorer,

            "exit":
                self.exit_project_to_welcome,
        }

        action = commands.get(
            command_id
        )

        if action is None:
            return

        try:
            action()

        except Exception as exc:
            write_exception_log(
                type(exc),
                exc,
                exc.__traceback__,
            )

            QMessageBox.critical(
                self,
                "Command Error",
                str(exc),
            )

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run_file(
        self,
    ):
        tab = (
            self.tabs.current_editor_tab()
        )

        if tab is None:
            QMessageBox.information(
                self,
                "Run File",
                "Open a file first.",
            )

            return

        if tab.is_dirty:
            if not tab.save():
                return

        path = tab.path
        suffix = path.suffix.lower()

        try:
            if suffix == ".py":
                flags = (
                    getattr(
                        subprocess,
                        "CREATE_NEW_CONSOLE",
                        0,
                    )
                    if os.name == "nt"
                    else 0
                )

                subprocess.Popen(
                    [
                        sys.executable,
                        str(path),
                    ],
                    cwd=str(
                        self.project_path
                    ),
                    creationflags=flags,
                )

                self.status.set_status(
                    "Running Python file",
                    temporary=True,
                )

            elif (
                suffix in {
                    ".bat",
                    ".cmd",
                }
                and os.name == "nt"
            ):
                os.startfile(
                    str(path)
                )

            elif (
                suffix == ".ps1"
                and os.name == "nt"
            ):
                subprocess.Popen(
                    [
                        "powershell",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(path),
                    ],
                    cwd=str(
                        self.project_path
                    ),
                    creationflags=_no_window_flag(),
                )

                self.status.set_status(
                    "Running PowerShell file",
                    temporary=True,
                )

            elif suffix in {
                ".sh",
                ".bash",
                ".zsh",
            }:
                subprocess.Popen(
                    [
                        "sh",
                        str(path),
                    ],
                    cwd=str(
                        self.project_path
                    ),
                )

                self.status.set_status(
                    "Running shell script",
                    temporary=True,
                )

            else:
                QMessageBox.information(
                    self,
                    "Run File",
                    (
                        "Wave Hub does not have "
                        "a built-in runner for "
                        f"{tab.language} yet."
                    ),
                )

        except FileNotFoundError as exc:
            QMessageBox.critical(
                self,
                "Runtime Not Found",
                str(exc),
            )

        except OSError as exc:
            QMessageBox.critical(
                self,
                "Run Error",
                str(exc),
            )

    # ------------------------------------------------------------------
    # About
    # ------------------------------------------------------------------

    def show_about(
        self,
    ):
        QMessageBox.about(
            self,
            "About Wave Hub",
            (
                "<h2>Wave Hub</h2>"
                "<p>"
                "A lightweight project IDE by Wave."
                "</p>"
                "<p>"
                "Native editor, syntax highlighting, "
                "smart editing, safe explorer traversal "
                "and project lifecycle management."
                "</p>"
                "<p><b>Wave Hub 1.0</b></p>"
            ),
        )


# ============================================================================
# STANDALONE MODE
# ============================================================================

def main() -> int:
    app = QApplication.instance()

    if app is None:
        app = QApplication(
            sys.argv
        )

    app.setApplicationName(
        APP_NAME
    )

    app.setApplicationDisplayName(
        APP_NAME
    )

    sys.excepthook = (
        global_exception_hook
    )

    if len(sys.argv) > 1:
        path = Path(
            sys.argv[1]
        ).expanduser()
    else:
        path = Path.cwd()

    try:
        path = path.resolve()
    except OSError:
        pass

    if not path.exists():
        QMessageBox.critical(
            None,
            APP_NAME,
            (
                "Project path does not exist:\n\n"
                f"{path}"
            ),
        )

        return 2

    if not path.is_dir():
        QMessageBox.critical(
            None,
            APP_NAME,
            (
                "Project path is not a directory:\n\n"
                f"{path}"
            ),
        )

        return 3

    try:
        window = IDEWindow(
            path
        )

        window.showMaximized()

        return app.exec()

    except Exception as exc:
        write_exception_log(
            type(exc),
            exc,
            exc.__traceback__,
        )

        QMessageBox.critical(
            None,
            "Wave Hub Startup Error",
            (
                f"{exc}\n\n"
                f"Log:\n{crash_log_path()}"
            ),
        )

        return 4


if __name__ == "__main__":
    raise SystemExit(
        main()
    )