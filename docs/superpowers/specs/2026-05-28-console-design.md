# SpyDE Console — Design Spec

**Date:** 2026-05-28  
**Status:** Approved

---

## Overview

Add a collapsible bottom-dock Python console to SpyDE. The console gives users a live REPL with full access to open signal trees, the Dask client, and the running application — extending the GUI for data exploration and transformation without leaving the app.

---

## 1. Layout & UI Structure

A `QDockWidget` docked at `Qt.BottomDockWidgetArea`, default height ~220px. Toggled by pressing `Ctrl` alone (bare modifier key). Detection: on `KeyRelease` of `Qt.Key_Control`, if no other key was pressed during that press, toggle the dock. Implemented via `QApplication`-level `eventFilter` so it fires regardless of which widget has focus. A secondary toggle is available via **View → Console** in the menu bar.

Inside the dock, a vertical `QSplitter` holds two widgets:

```
┌─────────────────────────────────────────────────────────────┐
│  MainWindow (MDI area with plot subwindows)                 │
├─────────────────────────────────────────────────────────────┤
│ Console                                              [×] [^]│
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  OUTPUT AREA (QPlainTextEdit, read-only, dark bg)           │
│  >>> import numpy as np                                     │
│  >>> trees[0].root.data.shape                               │
│  (256, 256, 4, 4)                                           │
│  >>> s = trees[0].root                                      │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ >>>  [input editor - QPlainTextEdit, 1-3 lines tall]        │
└─────────────────────────────────────────────────────────────┘
```

### Key Bindings (input editor)

| Key | Action |
|---|---|
| `Enter` | Newline |
| `Shift+Enter` | Execute input |
| `Ctrl+Enter` | Execute input (alternative) |
| `Up` / `Down` | Cycle history (single-line input, or cursor at top/bottom) |
| `Tab` | Trigger autocomplete popup |
| `Ctrl+L` | Clear output area |
| `Ctrl` (tap alone) | Toggle console dock show/hide |

The input editor shows placeholder text `"Shift+Enter to run  ·  Tab to complete  ·  Ctrl to toggle"` when empty.

---

## 2. Execution & Namespace

A single persistent `dict` namespace lives for the entire app session. Seeded on first console show with live references:

```python
{
    "app":    <MainWindow>,        # the running application
    "trees":  app.signal_trees,    # live list reference — always current
    "client": app.client,          # Dask distributed.Client
    "hs":     hyperspy.api,
    "np":     numpy,
    "plt":    matplotlib.pyplot,
}
```

`trees` is the same list object as `MainWindow.signal_trees` — no refresh needed.

Two helpers injected via `app`:

```python
app.open_signal(s: BaseSignal)       # push signal into MDI area as new PlotWindow
app.close_signal(tree: BaseSignalTree)  # remove signal tree and its plot windows
```

### Execution Flow

1. `Shift+Enter` or `Ctrl+Enter` grabs input text from the editor.
2. `code.compile_command()` checks for incomplete blocks (`def`, `for`, `if`, etc.). If incomplete, the prompt switches to `...` and waits for more input.
3. On a complete block, `exec()` runs in the shared namespace. stdout/stderr are captured via `contextlib.redirect_stdout` + `StringIO` and flushed to the output area.
4. Exceptions are caught, formatted with `traceback.format_exc()`, and printed in muted red (`#e06c75`). They never crash the app.
5. Input is appended to the in-memory history list and the editor is cleared.

---

## 3. Autocomplete & Type Awareness

`Tab` triggers `jedi.Script` against the current input with `namespaces=[namespace]`. Jedi introspects live objects — it sees actual `BaseSignal` instances, their attributes, method signatures, and docstrings.

Completions appear in a `QListWidget` popup just above the input editor:

```
┌─────────────────────────────────────────────────┐
│  .data                  ndarray                 │
│  .axes_manager          AxesManager             │
│  .metadata              DictionaryTreeBrowser   │
│▶ .map()                 Apply function...       │
│  .decomposition()       Decomposition...        │
└─────────────────────────────────────────────────┘
│ >>>  trees[0].root.              [cursor here]  │
└─────────────────────────────────────────────────┘
```

Each item shows name + jedi type hint. First line of docstring shown as tooltip on hover.

### Popup Behaviour

- `Escape` or click-outside dismisses.
- Arrow keys navigate while focus stays in the input editor.
- `Tab` or `Enter` (inside popup) inserts selected completion.
- Auto-updates on each keystroke while popup is open.
- If jedi returns 0 completions, inserts 4 spaces instead.

---

## 4. Output Area & History

**Output area** (`QPlainTextEdit`, read-only). Three `QTextCharFormat` styles:

| Content | Color | Prefix |
|---|---|---|
| Input echo | Dim gray (`#6c6c6c`) | `>>> ` / `... ` |
| Output | White (`#ffffff`) | none |
| Errors | Muted red (`#e06c75`) | none |

Auto-scrolls to bottom after each execution.

**History** — `list[str]` on the widget, in-memory only (not persisted between sessions). `Up`/`Down` walks the list; current draft is saved and restored when navigating back to the bottom.

---

## 5. File Structure

```
spyde/
└── console/
    ├── __init__.py
    ├── console_widget.py      # QDockWidget, toggle logic, Ctrl key filter
    ├── input_editor.py        # QPlainTextEdit subclass, key bindings, history navigation
    ├── output_area.py         # QPlainTextEdit subclass, append helpers, color formats
    ├── executor.py            # exec loop, stdout/stderr capture, compile_command wrapper
    ├── completer.py           # jedi integration, QListWidget popup
    └── namespace.py           # builds and owns the shared namespace dict, injects helpers
```

---

## 6. Integration into MainWindow

Changes to `spyde/__main__.py`:

- Instantiate `ConsoleWidget(main_window=self)` and add as bottom dock widget.
- Install app-level `eventFilter` on `QApplication` for bare `Ctrl` key toggle.
- Add `View → Console` menu action as secondary toggle.
- Add `open_signal(s: BaseSignal)` method — constructs a `BaseSignalTree` and calls `add_plot_window`, matching the file-open path.
- Add `close_signal(tree: BaseSignalTree)` method — removes tree from `signal_trees` and closes associated plot windows.

---

## 7. Dependencies

- `jedi` — pip installable, add to `pyproject.toml` under `[project.dependencies]`
- All other dependencies (PySide6, `code`, `contextlib`, `traceback`, `io`) are already present or stdlib.

---

## 8. Out of Scope (v1)

- History persistence across sessions
- Rich output (images, HTML inline)
- Notebook-style cells (considered, deferred)
- Magic commands (`%timeit`, `%who`, etc.)
- Syntax highlighting in the input editor
