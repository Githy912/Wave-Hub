# Wave Hub

Wave Hub is a lightweight project IDE by **Wave**.

It focuses on the essentials of a modern coding environment without turning into a heavyweight development suite.

## Features

### Welcome & Projects

- Clean Wave Hub Welcome interface
- Create new projects
- Open existing projects
- Browse recent projects
- Automatic recent-project tracking
- Same Welcome instance is restored when leaving a project
- Single-instance Welcome behavior

### Project Explorer

- Native project file tree
- Lazy directory loading
- Animated directory expansion
- Explorer depth safety limit
- Per-directory child limit
- Total explorer-entry safety limit
- Skips common generated/build directories
- Skips symbolic links
- Refresh Explorer

### Explorer Right-Click Menu

Right-click files and folders for:

- Open
- Run Python / PythonW
- Rename
- Delete
- New File
- New Folder
- Open Folder
- Open Containing Folder
- Refresh Explorer

### Code Editor

Wave Hub uses a native `QPlainTextEdit` based code editor with:

- Cascadia Code
- Dark editor interface
- Syntax highlighting
- Line numbers
- Current-line highlighting
- No automatic line wrapping
- Undo / redo
- Multiple editor tabs
- Dirty-file indicators
- Native scrolling

### Smart Editing

- Automatic bracket pairing
- Automatic quote pairing
- Automatic backtick pairing
- Selection wrapping
- Automatic HTML/XML/SVG closing tags
- HTML void-tag awareness
- Comment continuation
- Smart indentation
- Python `:` indentation
- Brace / bracket / parenthesis indentation
- HTML indentation
- Intelligent backspace handling for generated pairs and tags

### Syntax Highlighting

Built-in language/file profiles include:

- Python
- C
- C++
- C#
- Rust
- Go
- JavaScript
- TypeScript
- Java
- Kotlin
- Swift
- PHP
- Lua
- SQL
- Shell
- PowerShell
- Batch
- JSON
- YAML
- TOML
- INI
- Assembly
- HTML
- XML
- SVG
- CSS
- SCSS
- SASS
- Less
- Markdown
- LaTeX
- GraphQL
- Protobuf
- Dart
- Haskell
- Pascal
- Fortran
- Perl
- Julia
- Zig
- Nim
- Solidity
- R
- Vimscript
- Dockerfile
- Makefile
- CMake

Unknown file types fall back to plain text.

### Find

Wave Hub includes a full Find interface with:

- Normal text search
- Case-sensitive search
- Case-insensitive search
- Whole-word matching
- Regular expressions
- Wrap-around searching
- Search from the current cursor position
- Find Next
- Find Previous

Shortcuts:

- `Ctrl+F` -> Find
- `F3` -> Find Next
- `Shift+F3` -> Find Previous

### Replace

Wave Hub includes:

- Replace Next
- Replace All
- Match case
- Whole word
- Regular expressions
- Wrap-around searching
- Regular-expression replacement support

Shortcut:

- `Ctrl+H` -> Replace

### File Handling

- UTF-8 support
- UTF-8 BOM detection
- UTF-16 / UTF-32 support
- Multiple legacy encoding fallbacks
- Encoding warnings
- Binary-file detection
- Safe decoding fallback
- Preserve detected encoding when saving
- External modification detection
- Save-before-overwrite warning
- Permission-error handling
- File I/O error handling

### New File Workflow

Wave Hub intentionally uses:

```text
New File
   |
   v
Choose the filename and location
   |
   v
The new file opens immediately for editing
```

This keeps file creation direct and avoids creating a temporary untitled document.

### Tabs

- Multiple open files
- Dirty indicator
- Full-path tooltips
- Movable tabs
- Closable tabs
- Native close buttons
- Middle-click to close
- Next / previous tab shortcuts

### Editor Zoom

- `Ctrl+=` -> Zoom In
- `Ctrl+-` -> Zoom Out
- `Ctrl+0` -> Reset Zoom

### Running Files

Built-in runners currently support:

- Python
- PythonW
- PowerShell
- Batch / CMD
- Shell scripts

Shortcut:

- `F5` -> Run Current File

Unsupported languages are reported instead of silently failing.

### Command Palette

Shortcut:

- `Ctrl+Shift+P`

Available actions include:

- New File
- Open File
- Save
- Save All
- Find
- Replace
- Find Next
- Find Previous
- Close Tab
- Close All Tabs
- Zoom In
- Zoom Out
- Reset Editor Zoom
- Refresh Explorer
- Exit Project and Go Back to Welcome

### Status Bar

The status bar displays information such as:

- Current status
- Filename
- Language
- Encoding
- Cursor line
- Cursor column
- Unsaved-change state
- Encoding warnings

Example:

```text
Ready    UTF-8    Spaces: 4    main.py    Python    Ln 12, Col 8
```

### UI

- Dark Wave Hub interface
- Quicksand UI typography
- Cascadia Code editor typography
- Rounded controls
- Dark Explorer
- Styled menus
- Styled tabs
- Lightweight interface animations
- Search / Command Palette animation
- Animated Explorer expansion

### Error Handling

Unexpected IDE exceptions are logged to:

```text
%LOCALAPPDATA%\\Wave\\Wave Hub\\ide-crash.log
```

Wave Hub also shows a visible error dialog when an unexpected exception reaches the global exception handler.

### Project Lifecycle

Wave Hub protects work when leaving a project:

- Detects unsaved files
- Save
- Discard
- Cancel
- Prevents accidental project exit
- Returns to the existing Welcome window
- Avoids spawning duplicate Welcome windows during normal use

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+N` | New File |
| `Ctrl+O` | Open File |
| `Ctrl+S` | Save |
| `Ctrl+Shift+S` | Save All |
| `Ctrl+W` | Close Tab |
| `Ctrl+Shift+W` | Close All Tabs |
| `Ctrl+F` | Find |
| `Ctrl+H` | Replace |
| `F3` | Find Next |
| `Shift+F3` | Find Previous |
| `Ctrl+Shift+P` | Command Palette |
| `Ctrl+=` | Zoom In |
| `Ctrl+-` | Zoom Out |
| `Ctrl+0` | Reset Editor Zoom |
| `Ctrl+Tab` | Next Tab |
| `Ctrl+Shift+Tab` | Previous Tab |
| `Ctrl+Shift+R` | Refresh Explorer |
| `F5` | Run Current File |
| `Ctrl+Shift+Q` | Exit Project and Return to Welcome |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |

## Source Structure

```text
WaveHub/
├── main.py
├── ide.py
└── load.svg
```

### `main.py`

The Wave Hub Welcome application.

It handles:

- Welcome UI
- Project creation
- Existing-project opening
- Recent projects
- Application singleton behavior
- IDE launching
- Returning to Welcome

### `ide.py`

The main IDE implementation.

It contains:

- Code editor
- Syntax highlighter
- Project Explorer
- Context menus
- Tabs
- Find / Replace
- Command Palette
- File operations
- File runners
- Status bar
- Project lifecycle handling
- Error logging

### `load.svg`

Startup/loading artwork for the Wave Hub interface.

## Running From Source

From the project directory:

```powershell
cd C:\Users\Admin\Desktop\WaveHub
python main.py
```

Wave Hub is built with **Python** and **PyQt6**.

## Design Philosophy

Wave Hub is intentionally lightweight.

The core workflow is:

```text
Welcome
   |
   v
Create / Open Project
   |
   v
Explore Files
   |
   v
Edit Code
   |
   v
Find / Replace
   |
   v
Save
   |
   v
Run
   |
   v
Return to Welcome
```

The first release concentrates on the everyday editing workflow instead of loading the application with a large extension ecosystem, full debugger stack, or heavyweight development services.

## License

Wave Hub is licensed under the **GNU General Public License v3.0 (GPL-3.0)**.

See the project's license file for the complete license text.

## Wave

**Wave Hub 1.0**

A lightweight IDE by Wave.
