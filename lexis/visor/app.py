# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Lexis Visor: the Textual face of Lexis Agent.

Layout and behavior follow the approved 5-view mockup: horizontal
banner, always-visible Plan and Context panels, inline tool cards,
a live coding panel, per-risk approvals with a real diff, a command
palette, a permanent status bar, and a composer that never locks
while Lexis works (messages queue and are acknowledged at once).
All product text is English. The Cortex (pulse, compass, forge,
warden, vault, ledger) is shared unchanged with the plain CLI.
"""

import difflib
import io
import os
import re
import shutil
import threading
import time
from contextlib import redirect_stdout
from datetime import datetime

from pygments.style import Style as PygmentsStyle
from pygments.token import (
    Comment,
    Error,
    Keyword,
    Name,
    Number,
    Operator,
    String,
    Text as PygText,
)
from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, OptionList, ProgressBar, Static, TextArea
from textual.widgets.option_list import Option

from lexis.cortex import attachments, bridge
from lexis.cortex.compass import MODELS, Compass
from lexis.cortex.forge import Forge
from lexis.cortex.ledger import Ledger
from lexis.cortex.pulse import Pulse
from lexis.cortex.vault import Vault
from lexis.cortex.warden import MODES, Warden
from lexis.visor import banner as banner_mod
from lexis.visor import clipboard as clipboard_mod
from lexis.visor import panels
from lexis.visor import prefs as visor_prefs
from lexis.visor import themes as themes_mod
from lexis.visor import flames
from lexis.visor.icons import brain_fire_text, skull_fire_text
from lexis.visor.banner import (
    AMBER,
    ART_WIDTH,
    EMBER,
    banner_compact_text,
    banner_text,
)

ROOT = bridge.find_home()
GREEN = "#3fb96f"
RED = "#e05c5c"
TXT = "#e8ded2"
DIM = "#a08b74"
FAINT = "#6f5f4e"
PALE = "#ffd9a0"
STR_GREEN = "#9ccc8f"

HINTS = (
    "Enter send · while working, Enter queues your message · "
    "Shift+Enter new line · Ctrl+K palette · /model switch model · Esc stop"
)

PALETTE_COMMANDS = [
    ("/model", "switch model or the Auto profile", "Ctrl+M"),
    ("/provider", "switch provider or add a new endpoint + key", "—"),
    ("/skills", "manage skills: install from GitHub, create new, disable", "—"),
    ("/evolve", "draft a new skill from this session's verified work", "—"),
    ("/copy", "copy the last reply, or /copy all for the conversation", "Ctrl+Shift+C"),
    ("/mode", "switch compliance mode: EMBER · BLAZE · INFERNO", "Ctrl+."),
    ("/term", "terminal display: front end streams live, back end shows the result only", "—"),
    ("/theme", "switch theme: Foxfire Ember or Kitsune Azure", "—"),
    ("/plan", "plan first, act after approval", "Ctrl+P"),
    ("/stop", "stop the current work, the flame dims to low ember", "Esc"),
    ("/new", "open a clean new session, the old one stays untouched", "—"),
    ("/start", "show the lit work session and its flame state", "—"),
    ("/resume", "resume a previous session", "Ctrl+R"),
    ("/cost", "cost detail, layer by layer of savings", "—"),
    ("/verify", "run the independent check on the last result", "—"),
    ("/orion", "hand part of the work to Orion", "—"),
]

class FoxfireSyntaxStyle(PygmentsStyle):
    """The Foxfire Ember syntax theme (Master, 2026-11-11):
    Rich Syntax renders the code, colored only from the locked
    warm palette on the live panel's own background."""

    background_color = "#0a0806"
    default_style = ""
    styles = {
        PygText: "#e8ded2",
        Comment: "italic #7a6a55",
        Keyword: "bold #ff7a29",
        Keyword.Constant: "#e0a83c",
        Name.Function: "#ffd9a0",
        Name.Class: "#ffd9a0",
        Name.Builtin: "#ffc46b",
        Name.Decorator: "#e0a83c",
        String: "#9ccc8f",
        Number: "#e0a83c",
        Operator: "#ff9a3c",
        Error: "#ff6b4a",
    }


_LEXER_BY_EXT = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".json": "json", ".md": "markdown", ".html": "html",
    ".css": "css", ".sh": "bash", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".rs": "rust", ".go": "go", ".java": "java",
    ".c": "c", ".cpp": "cpp", ".sql": "sql",
}


def _lexer_for(path) -> str:
    if not path:
        return "python"
    return _LEXER_BY_EXT.get(
        os.path.splitext(str(path))[1].lower(), "text")


def _open_write(buf: str):
    """The write marker still open in a streaming reply:
    (path, body so far), or None. Mirrors forge's marker shape
    ([WRITE_FILE: path] body [/WRITE_FILE])."""
    start = buf.rfind("[WRITE_FILE:")
    if start < 0:
        return None
    tail = buf[start:]
    if "[/WRITE_FILE]" in tail:
        return None
    end = tail.find("]")
    if end < 0:
        return None
    path = tail[len("[WRITE_FILE:"):end].strip()
    body = tail[end + 1:]
    if body.startswith("\n"):
        body = body[1:]
    return path, body


_TOOL_LABELS = {
    "read_file": "Read file", "write_file": "Write file",
    "edit_file": "Edit file", "search_text": "Search",
    "list_dir": "List folder", "run_command": "Run command",
    "run_tests": "Run tests", "fetch_url": "Fetch page",
    "browse_page": "Browse page", "use_skill": "Use skill",
}

# No kitchen words on the user's surface (Master, 2026-11-11):
# raw system errors and internal tool names are translated to
# plain words before anything is shown. The precise originals
# stay in the ledger, where they belong.
_ERRNO_WORDS = (
    ("No such file or directory", "the file does not exist"),
    ("Permission denied", "permission denied"),
    ("Is a directory", "that is a folder, not a file"),
    ("Not a directory", "part of the path is not a folder"),
    ("File exists", "the file already exists"),
)


def _plain_detail(detail: str) -> str:
    d = str(detail)
    if "Errno" in d:
        for raw, plain in _ERRNO_WORDS:
            if raw in d:
                return plain
        return "the system refused the operation"
    return d


def _plain_reason(reason: str) -> str:
    r = str(reason)
    if "Errno" in r:
        plain = "the system refused the operation"
        for raw, words in _ERRNO_WORDS:
            if raw in r:
                plain = words
                break
        start = r.find("(")
        end = r.rfind(")")
        if start != -1 and end > start:
            r = r[:start] + f"({plain})" + r[end + 1:]
    for name, label in _TOOL_LABELS.items():
        r = r.replace(name, label)
    return r


class AzureSyntaxStyle(PygmentsStyle):
    """The Kitsune Azure syntax theme (Master, 2026-11-10):
    the Foxfire style answered in blue, on the azure
    panel's own deep background."""

    background_color = "#05080f"
    default_style = ""
    styles = {
        PygText: "#e6f2ff",
        Comment: "italic #5b7bab",
        Keyword: "bold #38bdf8",
        Keyword.Constant: "#7dd3fc",
        Name.Function: "#e0f2fe",
        Name.Class: "#e0f2fe",
        Name.Builtin: "#bae6fd",
        Name.Decorator: "#7dd3fc",
        String: "#9ccc8f",
        Number: "#7dd3fc",
        Operator: "#93c5fd",
        Error: "#ff6b4a",
    }


_SYNTAX_THEMES = {
    "foxfire-ember": (FoxfireSyntaxStyle, "#0a0806"),
    "kitsune-azure": (AzureSyntaxStyle, "#05080f"),
}
_syntax_active = "foxfire-ember"


def code_text(content: str, reveal=None, path=None) -> Syntax:
    """Real syntax highlighting (Rich Syntax + Pygments, Master
    2026-11-11) with line numbers, in the active theme's
    style. reveal limits the render to the first N lines
    for the live reveal."""
    lines = content.split("\n")
    if reveal is not None:
        lines = lines[:reveal]
    style, bg = _SYNTAX_THEMES[_syntax_active]
    return Syntax(
        "\n".join(lines),
        _lexer_for(path),
        theme=style,
        line_numbers=True,
        background_color=bg,
        word_wrap=False,
    )


_READ_MARKER_RE = re.compile(r"\[READ_FILE:\s*[^\]]*\]")
_LINE_MARKER_RE = re.compile(
    r"\[(?:SEARCH|LIST_DIR|RUN|RUN_TESTS|FETCH|BROWSE|USE_SKILL)"
    r":[^\n\]]*\]?"
)
_MARKER_HEADS = (
    "[READ_FILE:", "[WRITE_FILE:", "[EDIT_FILE:", "[SEARCH:",
    "[LIST_DIR:", "[RUN:", "[RUN_TESTS:", "[FETCH:", "[BROWSE:",
    "[USE_SKILL:",
)
# The angle dialect (Master's session, 2026-11-11: the model
# wrote <LIST_DIR: workspace> and the raw markup reached the
# screen). Protocol is kitchen language in every dialect.
_TAGS = (
    "READ_FILE", "WRITE_FILE", "EDIT_FILE", "SEARCH", "LIST_DIR",
    "RUN", "RUN_TESTS", "FETCH", "BROWSE", "USE_SKILL",
)
_ANGLE_READ_RE = re.compile(r"<READ_FILE:\s*[^>]*>?")
_ANGLE_LINE_MARKER_RE = re.compile(
    r"<(?:SEARCH|LIST_DIR|RUN|RUN_TESTS|FETCH|BROWSE|USE_SKILL)"
    r":[^\n>]*>?")
_ANGLE_CLOSE_RE = re.compile(
    r"</(?:" + "|".join(_TAGS) + r")>")
_ANGLE_HEADS = (
    tuple(f"<{t}:" for t in _TAGS)
    + tuple(f"</{t}>" for t in _TAGS)
)
# Markdown emphasis (Master's session, 2026-11-21: the model's
# **bold** reached the screen as raw asterisks). The chat renders
# plain Text, so emphasis markers are stripped and the words
# stay. Only paired markers are touched: an unpaired marker may
# still be completed by the next stream chunk, arithmetic with
# spaces around the asterisks is not emphasis, and a __dunder__
# name is code, not bold (underscore bold needs a space inside).
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
_MD_BOLD_U_RE = re.compile(r"__([^_]*\s[^_]*?)__")
_MD_STRIKE_RE = re.compile(r"~~(.+?)~~", re.S)
_MD_CODE_RE = re.compile(r"`([^`\n]+?)`")
_MD_ITALIC_RE = re.compile(r"\*([^*\s][^*\n]*?[^*\s]|[^*\s])\*")
_MD_HEADING_RE = re.compile(r"(?m)^#{1,6}[ \t]+")
_MD_QUOTE_RE = re.compile(r"(?m)^>[ \t]?")


def display_text(buf: str) -> str:
    """What the chat shows while streaming: the model's words without
    the tool protocol. Markers and file blocks are carried by the tool
    cards, the approval screen, and the live coding panel instead;
    protocol text is kitchen language and never reaches the user."""
    buf = _READ_MARKER_RE.sub("", buf)
    buf = _LINE_MARKER_RE.sub("", buf)
    for head in ("[WRITE_FILE:", "[EDIT_FILE:"):
        idx = buf.find(head)
        if idx != -1:
            buf = buf[:idx]
    i = buf.rfind("[")
    if i != -1:
        tail = buf[i:]
        if "]" not in tail and any(
            head.startswith(tail) or tail.startswith(head)
            for head in _MARKER_HEADS
        ):
            buf = buf[:i]
    buf = _ANGLE_READ_RE.sub("", buf)
    buf = _ANGLE_LINE_MARKER_RE.sub("", buf)
    buf = _ANGLE_CLOSE_RE.sub("", buf)
    for head in ("<WRITE_FILE:", "<EDIT_FILE:"):
        idx = buf.find(head)
        if idx != -1:
            buf = buf[:idx]
    i = buf.rfind("<")
    if i != -1:
        tail = buf[i:]
        if ">" not in tail and any(
            head.startswith(tail) or tail.startswith(head)
            for head in _ANGLE_HEADS
        ):
            buf = buf[:i]
    buf = _MD_BOLD_RE.sub(r"\1", buf)
    buf = _MD_BOLD_U_RE.sub(r"\1", buf)
    buf = _MD_STRIKE_RE.sub(r"\1", buf)
    buf = _MD_CODE_RE.sub(r"\1", buf)
    buf = _MD_ITALIC_RE.sub(r"\1", buf)
    buf = _MD_HEADING_RE.sub("", buf)
    buf = _MD_QUOTE_RE.sub("", buf)
    return buf


def diff_text(old: str, new: str) -> Text:
    out = Text()
    diff = list(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(), lineterm="", n=2
        )
    )
    if not diff:
        out.append("No textual differences.", style=DIM)
        return out
    for line in diff[:80]:
        if line.startswith("+") and not line.startswith("+++"):
            out.append(line + "\n", style=GREEN)
        elif line.startswith("-") and not line.startswith("---"):
            out.append(line + "\n", style=RED)
        elif line.startswith("@@"):
            out.append(line + "\n", style=FAINT)
        else:
            out.append(line + "\n", style=DIM)
    if len(diff) > 80:
        out.append(f"… {len(diff) - 80} more lines", style=FAINT)
    return out


def separator_text(label: str, sub: str = "") -> Text:
    """The Lexis turn separator (Master, 2026-11-10): deliberately
    stronger than a plain rule. A short ember bar burns bright, a
    diamond marks the turn, the speaker label follows, and the rest
    of the line fades to dark. Used between chat turns, over the
    typing indicator, and over the live coding panel."""
    t = Text(overflow="crop")
    t.append("━━━", style=f"bold {EMBER}")
    t.append(" ◆ ", style=f"bold {AMBER}")
    t.append(label, style=f"bold {EMBER if label != 'YOU' else AMBER}")
    if sub:
        t.append(f"  {sub}", style=FAINT)
    t.append("  " + "─" * 120, style="#4a3826")
    return t


class EntryInput(Input):
    """An Input with working clipboard keys (Master, 2026-11-11:
    Ctrl+C copies, Ctrl+V pastes, Ctrl+X cuts, in every entry
    without exception)."""

    BINDINGS = [
        Binding("ctrl+c", "clip_copy", "Copy"),
        Binding("ctrl+v", "clip_paste", "Paste"),
        Binding("ctrl+x", "clip_cut", "Cut"),
    ]

    def _selected(self) -> str:
        start, end = self.selection.start, self.selection.end
        if start == end:
            return ""
        return self.value[start:end]

    def action_clip_copy(self) -> None:
        clipboard_mod.set_text(self._selected() or self.value)

    def action_clip_cut(self) -> None:
        start, end = self.selection.start, self.selection.end
        if start == end:
            clipboard_mod.set_text(self.value)
            self.value = ""
            return
        clipboard_mod.set_text(self.value[start:end])
        self.value = self.value[:start] + self.value[end:]
        self.cursor_position = start

    def action_clip_paste(self) -> None:
        text = clipboard_mod.get_text()
        if not text:
            return
        start, end = self.selection.start, self.selection.end
        self.value = self.value[:start] + text + self.value[end:]
        self.cursor_position = start + len(text)


class Composer(TextArea):
    """Enter sends, Shift+Enter makes a new line (mockup contract)."""

    def _clip_copy(self, cut: bool = False) -> None:
        selected = self.selected_text
        if not selected and not cut:
            # The composer keeps keyboard focus even while
            # the owner selects conversation text with the
            # mouse, so a plain Ctrl+C landed here and copied
            # the (often empty) composer instead of the text
            # on screen (Master, 2026-11-11: copy still felt
            # broken). A live screen selection wins.
            try:
                screen_text = self.app.screen.get_selected_text()
            except Exception:
                screen_text = ""
            if screen_text:
                clipboard_mod.set_text(screen_text)
                return
        clipboard_mod.set_text(selected or self.text)
        if cut:
            if selected:
                start, end = self.selection
                self.delete(start, end)
            else:
                self.clear()

    def _clip_paste(self) -> None:
        text = clipboard_mod.get_text()
        if text:
            self.replace(text, *self.selection)

    def _on_key(self, event) -> None:
        if event.key in ("ctrl+c", "ctrl+v", "ctrl+x"):
            event.prevent_default()
            event.stop()
            if event.key == "ctrl+v":
                self._clip_paste()
            else:
                self._clip_copy(cut=event.key == "ctrl+x")
            return
        active = getattr(self.app, "slash_menu_active", None)
        if active is not None and active():
            if event.key == "down":
                event.prevent_default()
                event.stop()
                self.app.slash_move(1)
                return
            if event.key == "up":
                event.prevent_default()
                event.stop()
                self.app.slash_move(-1)
                return
            if event.key == "tab":
                event.prevent_default()
                event.stop()
                self.app.slash_complete()
                return
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self.app.slash_dismiss()
                return
            if event.key == "enter":
                selected = self.app.slash_selected()
                if selected and self.text.strip() != selected:
                    event.prevent_default()
                    event.stop()
                    self.app.slash_complete()
                    return
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.app.submit_from_composer()
            return
        if event.key == "shift+enter":
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        super()._on_key(event)


class ApprovalScreen(ModalScreen):
    """Per-risk approval with a real diff. No answer means rejection."""

    BINDINGS = [Binding("escape", "reject", "Reject")]

    def __init__(self, path: str, content: str,
                 warning: str = "") -> None:
        super().__init__()
        self.path = path
        self.content = content
        self.warning = warning

    def compose(self) -> ComposeResult:
        old = ""
        if os.path.isfile(self.path):
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                old = f.read()
        title = Text()
        title.append("Allow this change?  ", style=f"bold {TXT}")
        title.append(" MEDIUM RISK ", style=f"bold {AMBER}")
        desc = Text()
        desc.append("Write file · ", style=DIM)
        desc.append(self.path, style=f"bold {TXT}")
        desc.append(
            " · a restore point is created automatically before "
            "anything is applied",
            style=DIM,
        )
        undo = Text(
            "How to undo: a restore point is created automatically before "
            "the change is applied and recorded in the session history. "
            "Undo restores tracked files only. Changes you made by hand "
            "outside Lexis are not covered.",
            style=FAINT,
        )
        note = Text(
            "Esc closes this with no effect at all. "
            "No answer is treated as a rejection.",
            style=FAINT,
        )
        with Vertical(classes="modalbox"):
            yield Static(title)
            if self.warning:
                yield Static(Text(self.warning,
                                  style=f"bold {AMBER}"))
            yield Static(desc)
            # The diff lives in its own scroll region: however
            # long the change, the buttons below stay inside
            # the box (Master's screenshot, 2026-11-11: a long
            # diff pushed Approve/Reject off the modal and the
            # owner was stuck with no way to answer).
            with VerticalScroll(classes="diffscroll"):
                if old:
                    yield Static(diff_text(old, self.content))
                else:
                    yield Static(code_text(
                        self.content, reveal=80, path=self.path))
            yield Static(undo)
            with Horizontal():
                yield Button("Approve", id="approve", variant="primary")
                yield Button("Always approve this kind", id="always")
                yield Button("Edit first", id="edit")
                yield Button("Reject", id="reject", variant="error")
            yield Static(note)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)

    def action_reject(self) -> None:
        self.dismiss("reject")


class PaletteScreen(ModalScreen):
    BINDINGS = [Binding("escape", "close", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="modalbox"):
            yield Static(separator_text("COMMANDS", "palette"))
            yield EntryInput(
                placeholder="Search commands, sessions, skills, files",
                id="pal-q",
            )
            yield OptionList(
                *[
                    Option(f"{cmd}   {desc}   {key}", id=cmd)
                    for cmd, desc, key in PALETTE_COMMANDS
                ],
                id="pal-list",
            )
            yield Static(
                Text(
                    "Esc closes with no side effects. "
                    "Nothing runs until you choose.",
                    style=FAINT,
                )
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        q = event.value.lower()
        lst = self.query_one("#pal-list", OptionList)
        lst.clear_options()
        for cmd, desc, key in PALETTE_COMMANDS:
            if q in cmd.lower() or q in desc.lower():
                lst.add_option(Option(f"{cmd}   {desc}   {key}", id=cmd))

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        self.dismiss(event.option.id)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        lst = self.query_one("#pal-list", OptionList)
        if lst.option_count:
            opt = lst.get_option_at_index(lst.highlighted or 0)
            self.dismiss(opt.id)

    def action_close(self) -> None:
        self.dismiss(None)


class PickScreen(ModalScreen):
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, title: str, options, current: str) -> None:
        super().__init__()
        self.title = title
        self.options = options
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(classes="modalbox"):
            yield Static(Text(self.title, style=f"bold {TXT}"))
            yield OptionList(
                *[
                    Option(
                        f"{o}   (active)" if o == self.current else o, id=o
                    )
                    for o in self.options
                ]
            )

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        self.dismiss(event.option.id)

    def action_close(self) -> None:
        self.dismiss(None)


class ProviderScreen(ModalScreen):
    """Add a provider from inside the app (Master, 2026-11-10):
    name, base URL, and API key typed here, never in a file the
    owner must edit first. The key field is masked; the key itself
    is stored only in the profile .env by bridge.add_provider and
    is never shown anywhere."""

    BINDINGS = [Binding("escape", "close", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="modalbox"):
            yield Static(separator_text("PROVIDER", "add new"))
            yield EntryInput(placeholder="Name, e.g. My Gateway", id="pv-name")
            yield EntryInput(
                placeholder="Base URL, e.g. https://api.example.com/v1",
                id="pv-base",
            )
            yield EntryInput(
                placeholder="API key (stored in .env, never shown)",
                id="pv-key", password=True,
            )
            yield Static(
                Text(
                    "Unlimited providers, any OpenAI-compatible "
                    "endpoint. The key is written only to this "
                    "profile's .env file.",
                    style=FAINT,
                )
            )
            with Horizontal():
                yield Button(
                    "Save provider", id="pv-save", variant="primary"
                )
                yield Button("Cancel", id="pv-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "pv-save":
            self.dismiss(None)
            return
        name = self.query_one("#pv-name", Input).value.strip()
        base = self.query_one("#pv-base", Input).value.strip()
        key = self.query_one("#pv-key", Input).value.strip()
        if not name or not base:
            return  # both are required; stay open
        self.dismiss((name, base, key))

    def action_close(self) -> None:
        self.dismiss(None)


MODE_DESCR = {
    "EMBER": "Guardian. Lexis may hold or refuse a harmful order, "
             "and explains why.",
    "BLAZE": "Loyal. Lexis warns once, briefly, then your confirmed "
             "word stands.",
    "INFERNO": "Full compliance. Your word is law: no warnings, "
               "no refusals.",
}


class LadderScreen(ModalScreen):
    """The compliance ladder: all three modes with what each one
    means, the active rung marked. Choosing INFERNO never applies
    directly from here; it goes through its own confirmation."""

    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, current: str) -> None:
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(classes="modalbox"):
            yield Static(Text("Compliance mode", style=f"bold {TXT}"))
            yield Static(
                Text(
                    "The ladder is permanent: the active mode always "
                    "shows in the header and the rail.",
                    style=FAINT,
                )
            )
            yield OptionList(
                *[
                    Option(
                        (f"{m}   (active)   " if m == self.current
                         else f"{m}   ") + MODE_DESCR[m],
                        id=m,
                    )
                    for m in MODES
                ]
            )
            yield Static(
                Text("Esc closes with no side effects.", style=FAINT)
            )

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        self.dismiss(event.option.id)

    def action_close(self) -> None:
        self.dismiss(None)


class InfernoScreen(ModalScreen):
    """Entering INFERNO is always a conscious act: its own screen,
    its own button, never a side effect of another choice."""

    BINDINGS = [Binding("escape", "close", "Close")]

    def compose(self) -> ComposeResult:
        title = Text()
        title.append("Enter INFERNO?  ", style=f"bold {TXT}")
        title.append(" FULL COMPLIANCE ", style=f"bold {RED}")
        body = Text(
            "In INFERNO your word is law. Lexis will not warn, hold, "
            "or refuse, whatever you order. The mode stays visible "
            "in the header and the compliance ladder for as long as "
            "it is active, and switching back is always one command "
            "away (/mode).",
            style=TXT,
        )
        with Vertical(classes="modalbox"):
            yield Static(skull_fire_text())
            yield Static(title)
            yield Static(body)
            with Horizontal():
                yield Button("Enter INFERNO", id="enter", variant="error")
                yield Button("Not now", id="stay")
            yield Static(
                Text("Esc closes with no side effects.", style=FAINT)
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)

    def action_close(self) -> None:
        self.dismiss("stay")


class BootScreen(Screen):
    """Startup reveal (Master's decision, 2026-11-10): opening Lexis
    is a moment, not a flash. The banner assembles line by line
    while the real load stages tick underneath, each one read from
    state the app actually loaded: configuration documents, the
    session, the brain's model, the compliance mode. Nothing here
    is timed to fake work; the stages are the load that already
    happened, presented in order. Skipped entirely under reduced
    motion and in headless test runs."""

    def __init__(self, banner: Text, stages, interval: float = 0.40):
        # 15 ticks (10 banner lines + 5 stages) at 0.40 s is a ~6 s
        # opening; Master set the floor at 5-7 s on 2026-11-10.
        super().__init__()
        self._banner = banner
        plain = banner.plain
        self._cuts = []
        pos = 0
        for line in plain.splitlines():
            pos += len(line) + 1
            self._cuts.append(min(pos, len(plain)))
        self._stages = list(stages)
        self._interval = interval
        self._tick_no = 0
        self._lines_shown = 0
        self._stages_shown = 0
        self._timer = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(id="boot-banner")
            yield Static(brain_fire_text(), id="boot-emblem")
            yield Static(id="boot-stages")
            yield ProgressBar(
                id="boot-bar",
                total=len(self._cuts) + len(self._stages),
                show_eta=False, show_percentage=False,
            )

    def on_mount(self) -> None:
        self._timer = self.set_interval(self._interval, self._tick)

    def _render_stages(self) -> None:
        lines = []
        for i in range(self._stages_shown):
            last = i == self._stages_shown - 1 and not self._done()
            mark = "▸" if last else "✓"
            lines.append(f"{mark} {self._stages[i]}")
        self.query_one("#boot-stages", Static).update(
            Text("\n".join(lines), style="#ffd9a0")
        )

    def _done(self) -> bool:
        return (
            self._lines_shown >= len(self._cuts)
            and self._stages_shown >= len(self._stages)
        )

    def _tick(self) -> None:
        self._tick_no += 1
        bar = self.query_one("#boot-bar", ProgressBar)
        if self._lines_shown < len(self._cuts):
            cut = self._cuts[self._lines_shown]
            self._lines_shown += 1
            self.query_one("#boot-banner", Static).update(
                self._banner[:cut]
            )
        elif self._stages_shown < len(self._stages):
            self._stages_shown += 1
            self._render_stages()
        bar.progress = self._lines_shown + self._stages_shown
        if self._done():
            self._render_stages()
            if self._timer is not None:
                self._timer.stop()
            self.dismiss(None)
        elif self._tick_no > 200:  # never trap the owner behind a splash
            if self._timer is not None:
                self._timer.stop()
            self.dismiss(None)


class LexisVisor(App):
    CSS_PATH = "theme.tcss"
    BINDINGS = [
        # Priority: the composer's editor keymap also claims
        # ctrl+k, and the palette must win from every entry.
        Binding("ctrl+k", "palette", "Palette", priority=True),
        Binding("escape", "stop_work", "Stop"),
        Binding("ctrl+shift+c", "copy_selection", "Copy"),
    ]

    def __init__(self, resume: bool = False, root=None) -> None:
        super().__init__()
        from textual.theme import Theme

        for _name, _spec in themes_mod.THEMES.items():
            self.register_theme(
                Theme(
                    name=_name,
                    primary=_spec["primary"],
                    accent=_spec["accent"],
                    background=_spec["background"],
                    surface=_spec["surface"],
                    panel=_spec["panel"],
                    foreground=_spec["foreground"],
                    success="#3fb96f",
                    warning=_spec["accent"],
                    error="#e05c5c",
                    dark=True,
                    variables=dict(_spec["css"]),
                )
            )
        self.theme = themes_mod.DEFAULT
        self._theme_name = themes_mod.DEFAULT
        self.root = root or ROOT
        # Terminal display mode (Master, 2026-11-10): front
        # end streams command output live; back end shows
        # only the label and the result, with the full
        # output still journaled. Remembered per profile.
        self._term_mode = visor_prefs.get(
            self.root, "term_mode", "front")
        if self._term_mode not in ("front", "back"):
            self._term_mode = "front"
        # The profile's theme: the saved choice, or the
        # default from themes.py (Kitsune Azure since
        # Master's 2026-11-21 decision; Foxfire Ember
        # remains a full choice).
        _saved_theme = visor_prefs.get(
            self.root, "theme", themes_mod.DEFAULT)
        if _saved_theme not in themes_mod.THEMES:
            _saved_theme = themes_mod.DEFAULT
        self._apply_theme(_saved_theme)
        self.resume = resume
        self.reduced_motion = os.getenv("LEXIS_REDUCED_MOTION") == "1"
        self.busy = False
        self.queue = []
        self.stop_event = threading.Event()
        self.always_write = False
        self.plan_steps = []
        self.last_turn_time = None
        self.last_verdict = None
        self.last_reply = ""
        self._turn_writes = []
        self._plan_flow = False
        self._stream_buf = ""
        self._last_live_tok = 0
        self._conn = "standby"
        self._streaming = False
        self._awaiting = False
        self._turn_error = False
        self._turn_started = None
        self._cost_cache = (0, 0, None, None)
        self._stream_widget = None
        self._approval_data = None
        self._live_stream = None
        self._activity_current = None
        self._approval_event = None
        self._approval_result = "reject"
        self._typing_frame = 0
        self._dimming = 0
        self._stopping = False
        self._flame_level = 0.0
        self._live_frame = 0
        self._banner_wide = True
        self._slash_items = []
        self._slash_sel = 0
        self._slash_dismissed_for = None
        self._live = None  # {path, content, revealed, total}
        self._resumed = False

    # ---------- setup ----------

    def on_mount(self) -> None:
        bridge.load_env(self.root)
        self.compass = Compass(root=self.root)
        self.warden = Warden(os.getenv("LEXIS_MODE", "EMBER"))
        self.forge = Forge()
        data_dir = os.path.join(self.root, "lexis_data")
        os.makedirs(data_dir, exist_ok=True)
        self.ledger = Ledger(os.path.join(data_dir, "state.db"))
        self.vault = Vault()
        self.session_id = None
        if self.resume:
            last = self.ledger.last_session_id()
            if last is not None:
                self.session_id = last
                self._resumed = True
                self.vault.replace_all(self.ledger.load_messages(last))
        if self.session_id is None:
            self.session_id = self.ledger.start_session(self.compass.current)
            for m in self.vault.bootstrap(self.root):
                self.ledger.append_message(
                    self.session_id, m["role"], m["content"]
                )
        self.documents = self.vault.register_config(self.root, self.ledger)
        self.pulse = Pulse(
            self.root, self.compass, self.vault, self.forge, self.warden,
            self.ledger, self.session_id,
            emit_token=self._cb_token,
            emit_line=lambda t: None,  # tool cards carry this in English
            ask=self._cb_ask,
            on_first_token=self._cb_first_token,
            on_event=self._cb_event,
            should_stop=self.stop_event.is_set,
        )
        from lexis.cortex import skills as skills_mod

        _slugs = skills_mod.sync_bundled(self.root)
        _registry = skills_mod.SkillRegistry(self.root, self.ledger)
        _registry.activate_bundled(_slugs)
        self.pulse.skills = _registry
        welcome = self.query_one("#welcome", Static)
        if self._resumed:
            welcome.update(
                f'Welcome back. Your last session has been resumed and '
                f'{len(self.documents)} documents are stored in the Vault. '
                f"Type / for commands, Ctrl+K for the palette."
            )
        else:
            welcome.update("Welcome. Type / for commands, Ctrl+K for the palette.")
        if self.resume:
            self._render_history()
        self._refresh_all()
        # One fine clock (~90 ms, Hermes class) drives all flame
        # motion. It stays alive at idle too, at a whisper: the
        # status ember breathes there (Master, 2026-11-11).
        # Reduced motion keeps the old discipline and rests.
        self._flame_timer = self.set_interval(0.09, self._tick_flames)
        if self.reduced_motion:
            self._flame_timer.pause()
        # A short repeating check keeps the banner matched to the
        # window: it catches the first real layout and every later
        # resize without depending on event timing.
        self.set_interval(0.3, self._apply_banner)
        if self.reduced_motion or self.is_headless:
            self.query_one("#composer", Composer).focus()
        else:
            boot_banner = (
                banner_text()
                if self.size.width - 48 >= ART_WIDTH
                else banner_compact_text()
            )

            def _after_boot(_r):
                self._apply_banner()
                self.query_one("#composer", Composer).focus()

            self.push_screen(
                BootScreen(boot_banner, self._boot_stages()),
                callback=_after_boot,
            )

    def _boot_stages(self):
        """The boot screen's stage lines, all from loaded state."""
        session = "session resumed" if self._resumed else "new session"
        return [
            f"Configuration · {len(self.documents)} documents loaded",
            f"Memory · {session}",
            f"Brain · Lexis Cortex · {self.compass.current}",
            f"Compliance · {self.warden.mode}",
            "Ready",
        ]

    def compose(self) -> ComposeResult:
        yield Static(id="hdr")
        with Horizontal(id="body"):
            with Vertical(id="main"):
                with Vertical(id="bannerbox"):
                    yield Static(banner_text(), id="banner")
                    yield Static(id="welcome")
                yield VerticalScroll(id="chat")
                yield Static(id="activity")
                yield Static(id="livecode")
                yield ProgressBar(
                    id="writebar", total=100, show_eta=False,
                    show_percentage=False,
                )
                yield Static(id="typing")
            with VerticalScroll(id="rail"):
                yield Static(classes="pnl", id="pnl-plan")
                with Vertical(classes="pnl"):
                    yield Static(id="pnl-context")
                    yield ProgressBar(
                        id="ctxbar", total=100, show_eta=False,
                        show_percentage=False,
                    )
                yield Static(classes="pnl", id="pnl-tokens")
                yield Static(classes="pnl", id="pnl-memory")
                yield Static(classes="pnl", id="pnl-skills")
                yield Static(classes="pnl", id="pnl-mode")
        yield Static(id="status")
        yield Static(id="slashmenu")
        with Vertical(id="composerbox"):
            yield Composer(id="composer")
            yield Static(HINTS, id="hints")

    def on_unmount(self) -> None:
        timer = getattr(self, "_flame_timer", None)
        if timer is not None:
            timer.stop()
        try:
            self.ledger.close()
        except Exception:
            pass

    # ---------- rendering helpers ----------

    def _chat(self) -> VerticalScroll:
        return self.query_one("#chat", VerticalScroll)

    def _follow_tail(self) -> None:
        """Keep the conversation tail in view while surfaces
        below the chat grow, but never yank a reader who has
        scrolled up on purpose."""
        try:
            chat = self._chat()
        except Exception:
            return
        if chat.scroll_y >= chat.max_scroll_y - 3:
            chat.scroll_end(animate=False)

    # ---------- activity strip (outside the chat) ----------

    def _activity(self, text) -> None:
        try:
            w = self.query_one("#activity", Static)
        except Exception:
            return
        if text is None:
            w.remove_class("on")
            return
        w.update(text)
        w.add_class("on")

    def _activity_running(self, label: str, target: str) -> None:
        self._activity_current = (label, target)
        self._activity_verb = "running"
        self._activity_started_at = time.time()
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append("◌ ", style=EMBER)
        t.append(f"{label} · {target}", style=f"bold {TXT}")
        t.append("   running…", style=FAINT)
        self._activity(t)

    def _activity_tick(self) -> None:
        """The running line carries its elapsed time, Hermes
        style, so a long tool never looks frozen."""
        cur = getattr(self, "_activity_current", None)
        started = getattr(self, "_activity_started_at", None)
        if not cur or started is None or self._awaiting:
            return
        label, target = cur
        secs = time.time() - started
        verb = getattr(self, "_activity_verb", "running")
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append("◌ ", style=EMBER)
        t.append(f"{label} · {target}", style=f"bold {TXT}")
        t.append(f"   {verb} · {secs:.0f}s", style=FAINT)
        self._activity(t)

    def _activity_waiting(self) -> None:
        label, target = self._activity_current or ("Write file", "")
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append("! ", style=AMBER)
        t.append(f"{label} · {target}", style=f"bold {TXT}")
        t.append("   waiting for your decision", style=FAINT)
        self._activity(t)

    def _activity_done(self, ok: bool, detail: str,
                       duration: float) -> None:
        self._activity_started_at = None
        # The finished line gets a short moment on the strip;
        # if the turn is still going, the flame clock then
        # hands the strip to a live continuation (see
        # _activity_continue) instead of leaving a frozen
        # tick behind (Master, 2026-11-11: after the terminal
        # finished, no status animation continued, so it was
        # impossible to tell done from hung).
        self._activity_done_at = (time.time(), self._turn_started)
        label, target = self._activity_current or ("Tool", "")
        self._activity_last_done = (label, target)
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append("✓ " if ok else "✗ ", style=GREEN if ok else RED)
        t.append(f"{label} · {target}", style=f"bold {TXT}")
        detail = _plain_detail(detail)
        if detail:
            t.append(f" — {detail}", style=DIM)
        t.append(f" · {duration:.1f} s", style=FAINT)
        self._activity(t)

    def _activity_continue(self) -> None:
        """Hand the strip to the post-tool continuation: a
        turn always goes back to the model after a tool, and
        that wait stays visibly alive here, timed on the
        turn's own clock like the status strip, until the
        turn truly ends and _turn_finished settles the line
        with a plain done."""
        self._activity_done_at = None
        self._activity_continuation = True
        self._activity_current = ("Lexis", "working on the result")
        self._activity_verb = "working"
        self._activity_started_at = self._turn_started
        self._activity_tick()

    def _post(self, widget) -> None:
        # Conversation text is selectable with the mouse:
        # Textual widgets allow selection by default
        # (ALLOW_SELECT is True and allow_select is a
        # read-only property; verified on the PC venv,
        # 2026-11-11). Ctrl+Shift+C copies the selection;
        # /copy covers the keyboard-only path.
        chat = self._chat()
        chat.mount(widget)
        chat.scroll_end(animate=False)

    # ---------- responsive banner ----------

    def _apply_banner(self) -> None:
        """The wide art needs ART_WIDTH columns of chat width; below
        that it would wrap and scramble, so the compact banner takes
        over (Master's small-window report, 2026-11-10)."""
        try:
            w = self.query_one("#bannerbox").content_region.width
        except Exception:
            return
        if not w:
            return
        wide = w >= ART_WIDTH + 2
        if wide != self._banner_wide:
            self._banner_wide = wide
            self.query_one("#banner", Static).update(
                banner_text() if wide else banner_compact_text()
            )

    def on_resize(self, event) -> None:
        self._apply_banner()

    def _post_chat(self, who: str, body: str) -> None:
        if who == "YOU":
            self._post(Static(separator_text("YOU"), classes="sep"))
        t = Text()
        t.append(
            who + "\n",
            style=f"bold {EMBER if who == 'YOU' else FAINT}",
        )
        t.append(body, style=TXT)
        self._post(Static(t, classes="msg"))

    def _post_note(self, body: str) -> None:
        self._post_chat("LEXIS", body)

    def _render_history(self) -> None:
        msgs = self.vault.messages()
        for m in msgs[3:]:  # skip system + few-shot bootstrap
            if m["role"] == "user" and not m["content"].startswith(
                "[HASIL BACA FILE"
            ):
                self._post_chat("YOU", m["content"])
            elif m["role"] == "assistant":
                self._post_chat("LEXIS", m["content"])

    def _refresh_all(self) -> None:
        mode_icon = {
            "EMBER": "🔥", "BLAZE": "⚡", "INFERNO": "💀",
        }.get(self.warden.mode, "🔥")
        hdr = Text(overflow="crop")
        hdr.append("🔥 LEXIS ", style=f"bold {EMBER}")
        hdr.append("AGENT", style=f"bold {AMBER}")
        hdr.append(".   ", style=f"bold {EMBER}")
        hdr.append("🧠 Brain ", style=DIM)
        hdr.append("Lexis Cortex", style=f"bold {TXT}")
        hdr.append(" · ◆ Model ", style=DIM)
        hdr.append("Auto" if self.compass.auto else self.compass.current,
                   style=TXT)
        hdr.append(" · ● Provider ", style=DIM)
        hdr.append(bridge.provider_name(self.root), style=f"bold {TXT}")
        hdr.append(f" · {mode_icon} Compliance ", style=DIM)
        hdr.append(
            self.warden.mode,
            style=f"bold {RED if self.warden.mode == 'INFERNO' else AMBER}",
        )
        self.query_one("#hdr", Static).update(hdr)

        self._status_mode_icon = mode_icon
        if hasattr(self, "ledger") and self.session_id is not None:
            import json as _json

            tot_in = tot_out = 0
            last_in = last_out = None
            for (detail,) in self.ledger._conn.execute(
                "SELECT detail FROM events WHERE session_id = ? "
                "AND kind = 'cost' ORDER BY id",
                (self.session_id,),
            ).fetchall():
                try:
                    d = _json.loads(detail)
                except ValueError:
                    continue
                last_in = int(d.get("prompt_tokens_est", 0))
                last_out = int(d.get("reply_tokens_est", 0))
                tot_in += last_in
                tot_out += last_out
            self._cost_cache = (tot_in, tot_out, last_in, last_out)
        self._refresh_status()

        self.query_one("#pnl-plan", Static).update(
            panels.plan_text(self.plan_steps)
        )
        msgs = self.vault.messages()
        self.query_one("#pnl-context", Static).update(
            panels.context_text(msgs)
        )
        self.query_one("#ctxbar", ProgressBar).update(
            progress=panels.context_percent(msgs)
        )
        self.query_one("#pnl-tokens", Static).update(
            panels.tokens_text(
                self.ledger, self.session_id,
                live_out_chars=len(self._stream_buf) if self.busy else 0,
                busy=self.busy,
            )
        )
        self.query_one("#pnl-memory", Static).update(
            panels.memory_text(self.ledger, self.session_id, self.documents)
        )
        self.query_one("#pnl-skills", Static).update(
            panels.skills_text(self.ledger, self.session_id)
        )
        self.query_one("#pnl-mode", Static).update(
            panels.mode_text(self.warden.mode)
        )

    # ---------- status strip ----------

    def _work_state(self):
        """The flame-language work state (Master, 2026-11-10): the
        strip says what the fire is doing, in place."""
        if getattr(self, "_stopping", False):
            return "◇", "Ember dimming · stopping"
        if not self.busy:
            return (
                flames.status_flame(
                    getattr(self, "_idle_frame", 0), False,
                    self.reduced_motion),
                "Ember low · idle",
            )
        if self._awaiting:
            return "◆", "Held flame · awaiting your word"
        icon = flames.status_flame(
            self._typing_frame, True, self.reduced_motion)
        # The wait is timed where the user looks (Master,
        # 2026-11-11): past five seconds the status itself
        # counts, so a silent provider can never look like a
        # frozen app.
        wait = ""
        if self._turn_started is not None:
            secs = int(time.time() - self._turn_started)
            if secs >= 5:
                wait = f" · {secs}s"
        if self._streaming:
            return icon, f"Flame · typing{wait}"
        return icon, f"Ablaze · working{wait}"

    def _refresh_status(self) -> None:
        try:
            status_w = self.query_one("#status", Static)
        except Exception:
            return  # not mounted yet / tearing down
        tot_in, tot_out, last_in, last_out = self._cost_cache
        if self.busy and self._turn_started is not None:
            turn_secs = time.time() - self._turn_started
        else:
            turn_secs = self.last_turn_time
        s_icon, s_label = self._work_state()
        status_w.update(panels.status_text(
            model="Auto" if self.compass.auto else self.compass.current,
            provider=bridge.provider_name(self.root),
            mode=self.warden.mode,
            mode_icon=getattr(self, "_status_mode_icon", "🔥"),
            conn=self._conn,
            state_icon=s_icon,
            state_label=s_label,
            turn_in=last_in,
            turn_out=(len(self._stream_buf) // 4 if self.busy
                      else (last_out or 0)),
            live=self.busy,
            sess_total=tot_in + tot_out,
            ctx_pct=panels.context_percent(self.vault.messages()),
            turn_secs=turn_secs,
            queued=len(self.queue),
            state_style=(
                f"bold {flames.glow_color(self._typing_frame)}"
                if self.busy and not self.reduced_motion else None
            ),
            width=status_w.size.width or 0,
            folder=self.pulse.workdir,
        ))

    # ---------- composer / queue ----------

    def submit_from_composer(self) -> None:
        area = self.query_one("#composer", Composer)
        text = area.text.strip()
        if not text:
            return
        area.text = ""
        self.submit_text(text)

    def submit_text(self, text: str) -> None:
        if text.strip().lower() == "/stop":
            # /stop is Esc's equal (Master, 2026-11-10): it acts
            # now, never queues behind the work it must stop.
            self.action_stop_work()
            return
        if text.startswith("/"):
            if self.busy:
                # /model is a control, not work (bug, Master
                # 2026-11-11): a mid-task switch must land now
                # and steer the task from its next step, never
                # queue behind the work it should steer.
                if text.strip().split(maxsplit=1)[0].lower() \
                        == "/model":
                    self._run_slash(text)
                    return
                self.queue.append(("cmd", text))
                self._post_note(
                    f"Queued. “{text}” runs as soon as the current "
                    "work finishes."
                )
                self._refresh_all()
                return
            self._run_slash(text)
            return
        if self.busy:
            self.queue.append(("msg", text))
            self._post_chat("YOU", text)
            self._post_note(
                "Queued. Lexis will read this between steps, "
                "without stopping the current work."
            )
            self._refresh_all()
            return
        self._start_turn(text)

    def action_stop_work(self) -> None:
        if self.busy:
            self.stop_event.set()
            # Hermes /stop semantics in flame language (Master,
            # 2026-11-10): stop this session's turn, drop this
            # session's queued work only, and report the count.
            dropped = len(self.queue)
            self.queue.clear()
            # The flame language for stopping: an eased dim to
            # low ember over the fine clock's frames, never an
            # instant disappearance.
            self._dimming = 1
            self._stopping = True
            timer = getattr(self, "_flame_timer", None)
            if timer is not None:
                timer.resume()
            self._refresh_status()
            if dropped:
                self._post_note(
                    f"Stopping at the next safe point… "
                    f"{dropped} queued item(s) dropped."
                )
            else:
                self._post_note("Stopping at the next safe point…")

    def action_palette(self) -> None:
        if self.screen.__class__.__name__ == "PaletteScreen":
            return

        def done(cmd):
            if cmd:
                self.submit_text(cmd)

        self.push_screen(PaletteScreen(), done)

    # ---------- turn engine ----------

    def _begin_stream(self, sub: str = "") -> None:
        """Open a Lexis reply: its separator bar first, then the
        stream widget the tokens land in."""
        self._post(Static(separator_text("LEXIS", sub), classes="sep"))
        self._stream_buf = ""
        self._last_live_tok = 0
        body = Text()
        body.append("LEXIS\n", style=f"bold {FAINT}")
        self._stream_widget = Static(body, classes="msg")
        self._post(self._stream_widget)

    def _arm_turn_state(self) -> None:
        self._turn_started = time.time()
        self._turn_error = False
        self._streaming = False
        self._awaiting = False
        self._activity_continuation = False
        self._activity_done_at = None
        # A new turn cancels any dim and lights the flame with
        # an eased ramp from low ember.
        self._dimming = 0
        self._stopping = False
        self._flame_level = 0.0
        timer = getattr(self, "_flame_timer", None)
        if timer is not None:
            timer.resume()

    def _start_turn(self, text: str) -> None:
        self.busy = True
        self._arm_turn_state()
        self.stop_event.clear()
        self.query_one("#writebar", ProgressBar).remove_class("on")
        self.query_one("#livecode", Static).remove_class("on")
        self._post_chat("YOU", text)
        # Dropped files: detection is stat-only and content reads
        # are budget-capped, so this never stalls the interface;
        # the cards land instantly, the model gets the content.
        atts = attachments.scan(text)
        for att in atts:
            self._post(Static(
                Text(att.card_text(), style=f"bold {AMBER}"),
                classes="attach",
            ))
        self.plan_steps = [("now", "Reply from the model")]
        self._turn_writes = []
        self._begin_stream()
        self.query_one("#typing", Static).add_class("on")
        self._refresh_all()
        self.run_worker(
            lambda: self._turn_worker(attachments.enrich(text, atts)),
            thread=True, group="turn", exclusive=False,
        )

    def _turn_worker(self, text: str) -> None:
        try:
            self.pulse.handle_turn(text)
        except Exception as e:  # surface like the plain CLI does
            self._turn_error = True
            self.call_from_thread(self._post_note, f"Error: {e}")
        finally:
            self.call_from_thread(self._turn_finished)

    def _start_plan_draft(self, goal: str) -> None:
        self.busy = True
        self._arm_turn_state()
        self.stop_event.clear()
        self._plan_flow = True
        self._turn_writes = []
        self._post_chat("YOU", f"/plan {goal}")
        self.plan_steps = [("now", "Draft the plan")]
        self._begin_stream("planning")
        self.query_one("#typing", Static).add_class("on")
        self._refresh_all()

        def work():
            try:
                self.pulse.draft_plan(goal)
            except Exception as e:
                self._turn_error = True
                self.call_from_thread(self._post_note, f"Error: {e}")
            finally:
                self.call_from_thread(self._turn_finished)

        self.run_worker(work, thread=True, group="turn", exclusive=False)

    def _start_plan_run(self) -> None:
        self.busy = True
        self._arm_turn_state()
        self.stop_event.clear()
        self._plan_flow = True
        self._turn_writes = []
        self._post_chat("YOU", "/plan run")
        self._begin_stream("running the plan")
        self.query_one("#typing", Static).add_class("on")
        self._refresh_all()

        def work():
            try:
                self.pulse.run_plan()
            except Exception as e:
                self._turn_error = True
                self.call_from_thread(self._post_note, f"Error: {e}")
            finally:
                self.call_from_thread(self._turn_finished)

        self.run_worker(work, thread=True, group="turn", exclusive=False)

    def _turn_finished(self) -> None:
        self.busy = False
        if getattr(self, "_activity_continuation", False):
            # Settle the continuation on the turn's last tool,
            # so the resting line still names the work that
            # finished (the strip's long-standing contract),
            # with a plain done for the turn as a whole.
            self._activity_continuation = False
            self._activity_current = getattr(
                self, "_activity_last_done", None) or ("Lexis", "done")
            self._activity_done(True, "done", max(
                0.0, time.time() - (self._turn_started or time.time())))
        self._activity_done_at = None
        self._conn = "error" if self._turn_error else "linked"
        self._streaming = False
        self._awaiting = False
        self.last_reply = self._stream_buf
        if not getattr(self, "_dimming", 0) and not self.queue:
            # Natural completion eases out too (Master, 2026-11-11):
            # the flame leans down over the fine clock instead of
            # cutting off. A queued next turn cancels the dim in
            # _arm_turn_state and keeps the flame lit.
            self._dimming = 1
            timer = getattr(self, "_flame_timer", None)
            if timer is not None:
                timer.resume()
        if self._live is not None:
            self._finish_live()
        self.query_one("#writebar", ProgressBar).remove_class("on")
        if not self._plan_flow:
            self.plan_steps = [
                ("done" if s != "todo" else "done", lbl)
                for s, lbl in self.plan_steps
            ] + [("done", "Save the session")]
        self._plan_flow = False
        self._refresh_all()
        if self.queue:
            kind, text = self.queue.pop(0)
            if kind == "msg":
                self._start_turn(text)
            else:
                # A queued command is not a turn: the flame rests
                # unless the command itself starts one (a plan
                # draft re-lights it in _arm_turn_state).
                self.query_one("#typing", Static).remove_class("on")
                self._run_slash(text)
            self._refresh_all()

    # ---------- pulse callbacks (worker thread) ----------

    def _cb_token(self, token: str) -> None:
        self._stream_buf += token
        buf = self._stream_buf
        # Truly live coding (Master, 2026-11-11): a write marker
        # that is still open in the stream IS the file being
        # born; the panel follows the stream itself, not a
        # replay after the fact.
        self._live_stream = _open_write(buf)

        def render():
            if self._stream_widget is not None:
                t = Text()
                t.append("LEXIS\n", style=f"bold {FAINT}")
                t.append(display_text(buf), style=TXT)
                self._stream_widget.update(t)
                self._chat().scroll_end(animate=False)
            est = len(buf) // 4
            if est != self._last_live_tok:
                self._last_live_tok = est
                try:
                    self.query_one("#pnl-tokens", Static).update(
                        panels.tokens_text(
                            self.ledger, self.session_id,
                            live_out_chars=len(buf), busy=True,
                        )
                    )
                except Exception:
                    pass

        self.call_from_thread(render)

    def _cb_first_token(self) -> None:
        # The flame strip stays lit for the whole turn (locked
        # flame language, Master 2026-11-10): streaming IS the
        # typing state, so the first token must not retire the
        # indicator. It turns off only when the turn finishes
        # (or dims out after /stop).
        self._streaming = True

    def _cb_ask(self, prompt: str) -> str:
        if self.always_write:
            return "y"
        data = self._approval_data or {}
        self._approval_event = threading.Event()
        self._approval_result = "reject"

        def show():
            self._activity_waiting()

            def done(choice):
                if choice == "always":
                    self.always_write = True
                    self._approval_result = "y"
                elif choice == "approve":
                    self._approval_result = "y"
                elif choice == "edit":
                    self._approval_result = "n"
                    self._post_note(
                        "Write cancelled. Tell Lexis what to change."
                    )
                else:
                    self._approval_result = "n"
                if self._approval_event is not None:
                    self._approval_event.set()

            warning = ""
            if data.get("warn_once"):
                warning = (
                    "BLAZE · Loyal: this is your one warning for "
                    "this kind of action. Approve it and Lexis "
                    "will not ask again this session."
                )
            self.push_screen(
                ApprovalScreen(
                    data.get("path", ""), data.get("content", ""),
                    warning=warning),
                done,
            )

        self.call_from_thread(show)
        self._awaiting = True
        try:
            self._approval_event.wait()
        finally:
            self._awaiting = False
        return self._approval_result

    def _cb_event(self, kind: str, data: dict) -> None:
        if kind == "approval_needed":
            self._approval_data = data
            return
        if kind == "tool_start" and data.get("name") == "write_file":
            # The restore point is created synchronously here, before
            # forge writes, so the approval promise is always true.
            self._make_restore_point(data.get("path", ""))
        self.call_from_thread(self._on_event_ui, kind, data)

    def _make_restore_point(self, path: str) -> None:
        try:
            if path and os.path.isfile(path):
                dest_dir = os.path.join(
                    self.root, "lexis_data", "restore_points"
                )
                os.makedirs(dest_dir, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                dest = os.path.join(
                    dest_dir, f"{os.path.basename(path)}.{stamp}.bak"
                )
                shutil.copy2(path, dest)
                self.ledger.append_event(
                    self.session_id, "restore_point", dest
                )
        except OSError:
            pass

    # ---------- pulse events (UI thread) ----------

    def _on_event_ui(self, kind: str, data: dict) -> None:
        name = data.get("name", "")
        path = data.get("path", "")
        if kind == "phase":
            # The phase contract: Pulse owns the work phase and
            # emits it as data; the flame renderer consumes it
            # instead of deriving the phase locally.
            self._pulse_phase = data.get("phase", "")
        if kind == "tool_output":
            text = str(data.get("text", ""))
            # Back end display keeps the stream out of the
            # panel; the strip still carries the label and
            # the result, and the full output stays in the
            # journal either way (presentation only).
            if text and self._term_mode == "front":
                self._stream_tool_line(text)
        if kind == "tool_start":
            self._tools_running = getattr(self, "_tools_running", 0) + 1
        elif kind == "tool_end":
            self._tools_running = max(
                0, getattr(self, "_tools_running", 0) - 1)
        if kind == "tool_start":
            # Tool status lives on its own strip, never in the
            # chat (Master, 2026-11-11; Hermes keeps it separate
            # and so do we now).
            label = _TOOL_LABELS.get(name, name)
            self._stream_tool_name = name
            self._stream_tool_path = path
            self._activity_running(label, path)
            self.plan_steps.append(("now", f"{label} {os.path.basename(path)}"))
            if name == "write_file":
                self._start_live(path, data.get("content", ""))
        elif kind == "tool_end":
            self._activity_done(
                bool(data.get("ok")), data.get("detail", ""),
                float(data.get("duration", 0.0)),
            )
            # Plan steps tell the truth (Master, 2026-11-11):
            # a failed step shows a cross, never a green tick.
            ok = bool(data.get("ok", True))
            marked = False
            new_steps = []
            for s, lbl in self.plan_steps:
                if s == "now" and not marked:
                    new_steps.append(
                        ("done" if ok else "fail", lbl))
                    marked = True
                else:
                    new_steps.append((s, lbl))
            self.plan_steps = new_steps
            if name == "write_file":
                if data.get("ok"):
                    self._turn_writes.append(path)
                self._finish_live()
            elif name in ("run_command", "run_tests"):
                if (self._live is not None
                        and self._live.get("kind") == "output"):
                    self._finish_live()
        elif kind == "judge_verdict":
            self.last_verdict = data
            status = data.get("status", "")
            reasons = data.get("reasons", [])
            first = _plain_reason(reasons[0]) if reasons else ""
            if status == "pass":
                self._post_note(f"✓ Checked: {first}")
            elif status == "warn":
                self._post_note(f"⚠ Checked, with notes: {first}")
            else:
                self._post_note(f"✗ Check failed: {first}")
        elif kind == "conscience_refusal":
            # EMBER's deliberation gate fired: Lexis itself
            # refused, and the owner always hears the reason
            # in plain language (blueprint rule).
            self._post_note(
                "Lexis refused this itself: "
                + str(data.get("reason", "")))
        elif kind == "model_fallback":
            self._post_note(
                f"The model {data.get('from')} did not answer "
                f"({data.get('reason')}), so this task continued "
                f"with {data.get('to')}."
            )
        elif kind == "compaction":
            self._post_note(
                "Older conversation was condensed to stay within "
                f"the context budget. {data.get('facts', 0)} durable "
                "facts were stored in memory first, so nothing "
                "important was lost."
            )
        elif kind == "plan_ready":
            self.plan_steps = [
                ("todo", s) for s in data.get("steps", [])
            ]
            steps = data.get("steps", [])
            listing = "\n".join(
                f"{i}. {s}" for i, s in enumerate(steps, 1)
            )
            self._post_note(
                f"Plan ready for: {data.get('goal', '')}\n{listing}\n"
                "No files were changed while planning. Run it with "
                "/plan run, or draft a new one with /plan <goal>."
            )
        elif kind == "plan_step":
            label = data.get("label", "")
            state = data.get("state", "todo")
            if state == "now" and self._stream_buf.strip():
                # One stream widget carries the whole plan run; keep
                # each step's reply readable under its own heading.
                # This handler already runs on the app thread, so it
                # renders directly (the token callback would raise:
                # call_from_thread is worker-thread only).
                self._stream_buf += f"\n\nStep: {label}\n"
                if self._stream_widget is not None:
                    t = Text()
                    t.append("LEXIS\n", style=f"bold {FAINT}")
                    t.append(display_text(self._stream_buf), style=TXT)
                    self._stream_widget.update(t)
            self.plan_steps = [
                (state if lbl == label else s, lbl)
                for s, lbl in self.plan_steps
            ]
        elif kind == "plan_done":
            self._post_note("Plan complete. Every step was checked.")
        elif kind == "turn_done":
            self.last_turn_time = float(data.get("duration", 0.0))
        self._refresh_all()

    # ---------- live coding ----------

    def _stream_tool_line(self, line: str) -> None:
        """Live terminal output (Master, 2026-11-11): command
        and test lines appear in the live panel as the process
        prints them, instead of arriving in one block at the
        end of the run."""
        live = self._live
        if live is None or live.get("kind") != "output":
            name = getattr(self, "_stream_tool_name", "")
            label = _TOOL_LABELS.get(name, "Terminal")
            target = getattr(self, "_stream_tool_path", "")
            self._live = {
                "path": f"{label} · {target}".rstrip(" ·"),
                "content": "", "revealed": 0, "total": 1,
                "streaming": True, "kind": "output",
            }
            self.query_one("#livecode", Static).add_class("on")
            live = self._live
        lines = live["content"].split("\n") if live["content"] \
            else []
        lines.append(line)
        lines = lines[-300:]
        live["content"] = "\n".join(lines)
        live["total"] = max(len(lines), 1)
        live["revealed"] = live["total"]
        self._render_live()
        self._follow_tail()

    def _start_live(self, path: str, content: str) -> None:
        """Execution-time entry for a write. If the panel is
        already streaming this file from the model's reply, the
        stream is adopted and completed with the authoritative
        content; otherwise the finished content appears whole.
        There is no replay reveal anymore (Master, 2026-11-11):
        live means streamed, not staged."""
        live = self._live
        if (live is not None and live["path"] == path
                and live.get("streaming")):
            if content:
                live["content"] = content
            live["streaming"] = False
            live["total"] = max(
                len(live["content"].split("\n")), 1)
            live["revealed"] = live["total"]
            bar = self.query_one("#writebar", ProgressBar)
            bar.update(total=live["total"], progress=live["total"])
            bar.add_class("on")
            self._render_live()
            self._follow_tail()
            return
        total = max(len(content.split("\n")), 1)
        self._live = {
            "path": path, "content": content, "revealed": total,
            "total": total, "streaming": False,
        }
        box = self.query_one("#livecode", Static)
        box.add_class("on")
        bar = self.query_one("#writebar", ProgressBar)
        bar.update(total=total, progress=total)
        bar.add_class("on")
        self._render_live()
        self._follow_tail()

    def _sync_live_stream(self) -> None:
        """Follow the model's stream: while a write marker is
        open in the reply, the panel shows the file exactly as
        far as the stream has produced it. Runs on the flame
        clock (one clock for everything, no fighting)."""
        stream = self._live_stream
        if stream is None:
            return
        path, body = stream
        live = self._live
        if (live is None or live["path"] != path
                or not live.get("streaming")):
            self._live = {
                "path": path, "content": body, "revealed": 0,
                "total": 1, "streaming": True,
            }
            self.query_one("#livecode", Static).add_class("on")
        else:
            live["content"] = body
        live = self._live
        lines = max(len(body.split("\n")), 1)
        live["total"] = lines
        live["revealed"] = lines
        self._render_live()
        self._follow_tail()

    def _render_live(self) -> None:
        if self._live is None:
            return
        live = self._live
        kind = live.get("kind", "code")
        shown = live["path"] if kind == "output" \
            else os.path.basename(live["path"])
        head = Text(no_wrap=True, overflow="ellipsis")
        head.append(separator_text(
            "TERMINAL" if kind == "output" else "LIVE CODING",
            shown))
        head.append("\n")
        head.append(
            "● TERMINAL  " if kind == "output"
            else "● LIVE CODING  ", style=f"bold {AMBER}")
        head.append(shown, style=f"bold {TXT}")
        if live.get("streaming"):
            head.append(
                f"   streaming · {live['revealed']} lines so far\n",
                style=FAINT,
            )
        else:
            head.append(
                f"   lines 1-{live['revealed']} of {live['total']}\n",
                style=FAINT,
            )
        if live.get("streaming"):
            # Ember particles rise from the panel while it runs
            # (locked flame language, 2026-11-10).
            self._live_frame += 1
            sparks = [" "] * 34
            styles = {}
            for col, row, glyph, color in flames.flame_rows(
                    self._live_frame, width=34):
                if row == 0 and col < 34:
                    sparks[col] = glyph
                    styles[col] = color
            spark_line = Text(no_wrap=True, overflow="crop")
            for i, ch in enumerate(sparks):
                spark_line.append(
                    ch, style=styles.get(i) if ch != " " else None)
            head.append_text(spark_line)
            head.append("\n")
        if kind == "output":
            body = Text(live["content"], style=TXT)
        else:
            body = code_text(live["content"],
                             reveal=live["revealed"],
                             path=live["path"])
        if live.get("streaming"):
            renderable = Group(head, body, Text("█", style=EMBER))
        else:
            renderable = Group(head, body)
        self.query_one("#livecode", Static).update(renderable)

    def _finish_live(self) -> None:
        if self._live is None:
            return
        self._live["streaming"] = False
        self._live["revealed"] = self._live["total"]
        self._render_live()
        self.query_one("#writebar", ProgressBar).update(
            progress=self._live["total"]
        )
        self._live = None

    # ---------- typing indicator ----------

    def _tick_flames(self) -> None:
        """One fine clock (~90 ms) drives every flame motion and
        nothing else heavy: the full status strip refreshes only
        every fifth tick. The flame level eases toward each
        phase's target, so transitions and the /stop dim are
        ramps the eye can follow (Master, 2026-11-11). The
        timer pauses itself when nothing animates."""
        try:
            w = self.query_one("#typing", Static)
        except Exception:
            return  # screen is being torn down
        dimming = bool(getattr(self, "_dimming", 0))
        live_streaming = (
            self._live is not None and self._live.get("streaming"))
        if self._live_stream is not None:
            live_streaming = True
        if live_streaming:
            self._sync_live_stream()
        if not w.has_class("on") and not dimming and not live_streaming:
            # Idle: the status ember breathes slowly, so the
            # fire is visibly alive even at rest (Master,
            # 2026-11-11). Reduced motion rests the timer as
            # before; stillness wins there.
            if self.reduced_motion:
                timer = getattr(self, "_flame_timer", None)
                if timer is not None:
                    timer.pause()
                return
            self._idle_frame = getattr(self, "_idle_frame", 0) + 1
            if self._idle_frame % 6 == 0:
                self._refresh_status()
            return
        if not w.has_class("on") and not dimming:
            return  # only the live panel is animating
        self._typing_frame += 1
        f = self._typing_frame
        if dimming:
            target, label, phase = 0.0, "Lexis is stopping", "dimming"
        elif getattr(self, "_pulse_phase", "") == "held-for-approval":
            target, label, phase = 0.85, "Lexis is held", "held"
        elif getattr(self, "_pulse_phase", "") in (
                "typing", "working", "thinking"):
            _p = self._pulse_phase
            target, label, phase = 1.0, f"Lexis is {_p}", _p
        elif getattr(self, "_pulse_phase", "") == "dimming":
            target, label, phase = 0.0, "Lexis is stopping", "dimming"
        elif self._awaiting:
            target, label, phase = 0.85, "Lexis is held", "held"
        elif self._streaming:
            target, label, phase = 1.0, "Lexis is typing", "typing"
        elif getattr(self, "_tools_running", 0):
            target, label, phase = 1.0, "Lexis is working", "working"
        else:
            target, label, phase = 1.0, "Lexis is thinking", "thinking"
        if self.busy and self._turn_started is not None:
            _secs = int(time.time() - self._turn_started)
            if _secs >= 5:
                # Liveness (Master's bug, 2026-11-11): a long
                # wait must LOOK long. Thinking and dead may
                # never render the same again.
                label = f"{label} · {_secs}s"
        if self.reduced_motion:
            self._flame_level = target
        else:
            self._flame_level += (target - self._flame_level) * 0.28
        if dimming and self._flame_level < 0.05:
            self._flame_level = 0.0
            self._dimming = 0
            self._stopping = False
            w.remove_class("on")
            self._refresh_status()
            return
        t = separator_text("LEXIS", "typing")
        t.append("\n")
        t.append_text(flames.typing_text(
            f, label=label, intensity=self._flame_level,
            reduced=self.reduced_motion, phase=phase))
        w.update(t)
        if f % 5 == 0 and (self.busy or dimming):
            self._refresh_status()
        if f % 5 == 0 and self.busy and not dimming:
            stamp = getattr(self, "_activity_done_at", None)
            if (stamp is not None and stamp[1] is self._turn_started
                    and time.time() - stamp[0] >= 1.2
                    and not getattr(self, "_tools_running", 0)
                    and not self._awaiting):
                # The finished tool's line had its moment and
                # the turn is still going: the strip must not
                # freeze on the tick (Master, 2026-11-11).
                self._activity_continue()
            elif getattr(self, "_activity_started_at", None):
                self._activity_tick()
        if (f % 5 == 0 and self.busy and not dimming
                and not self._streaming
                and not getattr(self, "_tools_running", 0)
                and self._turn_started is not None):
            # A silent provider or model announces itself
            # once per turn (Master, 2026-11-11): a timed
            # note, not a frozen screen.
            secs = int(time.time() - self._turn_started)
            if (secs >= 30
                    and getattr(self, "_stall_noted_for", None)
                    != self._turn_started):
                self._stall_noted_for = self._turn_started
                model = ("the model" if self.compass.auto
                         else self.compass.current)
                self._post_note(
                    f"Still waiting for {model} to answer "
                    f"· {secs}s. If it stays silent, Lexis "
                    "switches models on its own."
                )

    # ---------- slash command preview ----------

    def on_text_area_changed(self, event) -> None:
        if getattr(event.text_area, "id", None) != "composer":
            return
        self._slash_update(event.text_area.text)

    def _slash_update(self, text: str) -> None:
        try:
            menu = self.query_one("#slashmenu", Static)
        except Exception:
            return
        first = text.split("\n")[0]
        if (self._slash_dismissed_for is not None
                and first != self._slash_dismissed_for):
            self._slash_dismissed_for = None
        items = []
        if first.startswith("/") and " " not in first and "\n" not in text:
            items = [
                (c, d) for c, d, _k in PALETTE_COMMANDS
                if c.startswith(first)
            ]
        if not items or self._slash_dismissed_for == first:
            self._slash_items = []
            menu.remove_class("on")
            return
        if items != self._slash_items:
            self._slash_sel = 0
        self._slash_items = items
        self._render_slash_menu()
        menu.add_class("on")

    def _render_slash_menu(self) -> None:
        t = Text(overflow="crop")
        t.append("◆ COMMANDS", style=f"bold {AMBER}")
        t.append("   up/down choose · Tab complete · Enter run\n",
                 style=FAINT)
        for i, (cmd, desc) in enumerate(self._slash_items):
            mark = "▸ " if i == self._slash_sel else "  "
            style = f"bold {EMBER}" if i == self._slash_sel else TXT
            t.append(f"{mark}{cmd}", style=style)
            t.append(f"   {desc}", style=FAINT)
            if i < len(self._slash_items) - 1:
                t.append("\n")
        self.query_one("#slashmenu", Static).update(t)

    def slash_menu_active(self) -> bool:
        if not self._slash_items:
            return False
        try:
            return self.query_one("#slashmenu", Static).has_class("on")
        except Exception:
            return False

    def slash_selected(self):
        if not self._slash_items:
            return None
        return self._slash_items[self._slash_sel][0]

    def slash_move(self, delta: int) -> None:
        if not self._slash_items:
            return
        self._slash_sel = (
            (self._slash_sel + delta) % len(self._slash_items)
        )
        self._render_slash_menu()

    def slash_complete(self) -> None:
        cmd = self.slash_selected()
        if not cmd:
            return
        area = self.query_one("#composer", Composer)
        area.text = cmd + " "
        area.cursor_location = (0, len(cmd) + 1)

    def slash_dismiss(self) -> None:
        area = self.query_one("#composer", Composer)
        self._slash_dismissed_for = area.text.split("\n")[0]
        self._slash_items = []
        self.query_one("#slashmenu", Static).remove_class("on")

    # ---------- slash commands ----------

    def _copy_out(self, text: str, what: str) -> None:
        """Put text on the system clipboard and say so. The
        Win32 module is the primary path (proven on the
        owner's desktop class of session); Textual's own
        clipboard write is the fallback."""
        from lexis.visor import clipboard

        ok = False
        try:
            ok = bool(clipboard.set_text(text))
        except Exception:
            ok = False
        if not ok:
            try:
                self.copy_to_clipboard(text)
                ok = True
            except Exception:
                ok = False
        if ok:
            self._post_note(
                f"Copied {what} ({len(text)} characters).")
        else:
            self._post_note(
                "Copy failed: the system clipboard is not "
                "reachable from this session.")

    def action_copy_selection(self) -> None:
        """Ctrl+Shift+C: copy the mouse selection from the
        conversation; with no selection, copy the last reply
        (Master's bug, 2026-11-11: nothing could be copied
        out of the chat)."""
        text = ""
        try:
            text = self.screen.get_selected_text() or ""
        except Exception:
            text = ""
        if text:
            self._copy_out(text, "the selected text")
        elif self.last_reply:
            self._copy_out(self.last_reply, "Lexis's last reply")
        else:
            self._post_note("Nothing to copy yet.")

    def _transcript_text(self) -> str:
        """The visible conversation as plain text for /copy
        all: owner and Lexis turns only, tool feedback and
        system scaffolding left out."""
        lines = []
        for m in self.vault.messages()[3:]:
            content = m["content"]
            if content.startswith(
                    ("[HASIL", "[SISTEM", "[ISI SKILL", "[IZIN")):
                continue
            who = "YOU" if m["role"] == "user" else "LEXIS"
            lines.append(f"{who}: {content}")
        return "\n\n".join(lines)

    def _provider_models_note(self, name: str) -> str:
        """Refresh the model catalog from the now-active
        provider and report what was actually read (Master's
        bug, 2026-11-11: an added provider kept the old
        catalog and the old model)."""
        count = self.compass.refresh_models()
        if self.compass.catalog_source == "provider":
            return (
                f"{count} models read from {name}; now using "
                f"{self.compass.current}. Applies from the next "
                "request, no restart needed."
            )
        if self.compass.catalog_source == "provider-failed":
            err = getattr(self.compass, "catalog_error", None)
            if err == "billing":
                return (
                    f"{name} refused its model list: the account "
                    "needs credit (402). The switch applies, but "
                    "requests will fail until the account is "
                    "funded. Keeping the current catalog."
                )
            if err == "auth":
                return (
                    f"{name} rejected the saved key (401). Check "
                    "this provider's key, then switch again. "
                    "Keeping the current catalog."
                )
            return (
                f"Could not read a model list from {name}; "
                "keeping the current catalog. Applies from the "
                "next request, no restart needed."
            )
        return (
            f"Using the built-in catalog ({count} models); now "
            f"using {self.compass.current}. Applies from the "
            "next request, no restart needed."
        )

    def _start_evolve(self, slug: str) -> None:
        """Draft a skill from this session's verified work
        (Step 3): the drafting model call runs in the turn
        worker so the interface never freezes."""
        if self.busy:
            self._post_note(
                "Lexis is working. Wait for the turn to finish, "
                "then /evolve."
            )
            return
        if not slug:
            self._post_note(
                "Usage: /evolve <skill-name>. Lexis drafts a "
                "skill from this session's verified work; the "
                "draft waits for your approval under /skills."
            )
            return
        self.busy = True
        self._arm_turn_state()
        self.stop_event.clear()
        self.query_one("#typing", Static).add_class("on")
        self._refresh_all()
        self.run_worker(
            lambda: self._evolve_worker(slug),
            thread=True, group="turn", exclusive=False,
        )

    def _evolve_worker(self, slug: str) -> None:
        try:
            result = self.pulse.evolve_skill(slug)
        except Exception as e:
            result = {"ok": False, "reason": str(e)}
        self.call_from_thread(self._evolve_done, result)

    def _evolve_done(self, result: dict) -> None:
        self.busy = False
        try:
            self.query_one("#typing", Static).remove_class("on")
        except Exception:
            pass
        if not result.get("ok"):
            self._post_note(
                "Could not draft the skill: "
                + result.get("reason", "unknown reason")
            )
        elif result.get("status") == "blocked":
            self._post_note(
                f"Draft skill {result['slug']} was BLOCKED by "
                "the security scan ("
                + ", ".join(result.get("findings", []))
                + "). It will never activate."
            )
        else:
            self._post_note(
                f"Draft skill {result['slug']} is written and "
                "pending. Review it under /skills, then approve "
                f"it with /skills approve {result['slug']}."
            )
        self._refresh_all()

    def _run_slash(self, text: str) -> None:
        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        if cmd == "/stop":
            self.action_stop_work()
            return
        if cmd == "/model":
            if arg:
                if self.compass.select(arg):
                    self.ledger.append_event(
                        self.session_id, "model",
                        "Auto" if self.compass.auto else self.compass.current,
                    )
                    if self.busy:
                        # Honest timing (Master, 2026-11-11):
                        # the step already streaming finishes
                        # on the old model; the switch steers
                        # from the next step of this task.
                        self._post_note(
                            "Auto routing is on. It applies "
                            "from the next step of this task."
                            if self.compass.auto
                            else f"Model switched to "
                            f"{self.compass.current}. It applies "
                            "from the next step of this task."
                        )
                    else:
                        self._post_note(
                            "Auto routing is on. Lexis picks the model "
                            "per task, with the probed fallback chain "
                            "behind it."
                            if self.compass.auto
                            else f"Model switched to {self.compass.current}."
                        )
                else:
                    self._post_note("That model is not in the catalog.")
            else:
                def pick(choice):
                    if choice:
                        if choice == "Auto":
                            self.compass.auto = True
                            label = "Auto"
                        else:
                            self.compass.current = choice
                            self.compass.auto = False
                            label = choice
                        self.ledger.append_event(
                            self.session_id, "model", label
                        )
                        if self.busy:
                            self._post_note(
                                f"Model switched to {label}. "
                                "It applies from the next step "
                                "of this task."
                            )
                        else:
                            self._post_note(
                                f"Model switched to {label}.")
                        self._refresh_all()

                self.push_screen(
                    PickScreen(
                        "Switch model",
                        ["Auto"] + self.compass.list_models(),
                        "Auto" if self.compass.auto
                        else self.compass.current,
                    ),
                    pick,
                )
        elif cmd == "/provider":
            if arg:
                if bridge.set_active_provider(self.root, arg):
                    self.ledger.append_event(
                        self.session_id, "provider", arg
                    )
                    self._post_note(
                        f"Provider is now {arg}. "
                        + self._provider_models_note(arg)
                    )
                else:
                    names = ", ".join(
                        p["name"]
                        for p in bridge.list_providers(self.root)
                    )
                    self._post_note(
                        f"No provider named {arg}. Saved: {names}. "
                        "Type /provider to pick or add one."
                    )
                self._refresh_all()
            else:
                add_label = "+ Add new provider"

                def added(result):
                    if result:
                        name, base, key = result
                        bridge.add_provider(self.root, name, base, key)
                        self.ledger.append_event(
                            self.session_id, "provider", name
                        )
                        self._post_note(
                            f"Provider {name} saved and active. "
                            + self._provider_models_note(name)
                        )
                        self._refresh_all()

                def pick(choice):
                    if not choice:
                        return
                    if choice == add_label:
                        self.push_screen(ProviderScreen(), added)
                        return
                    if bridge.set_active_provider(self.root, choice):
                        self.ledger.append_event(
                            self.session_id, "provider", choice
                        )
                        self._post_note(
                            f"Provider is now {choice}. "
                            + self._provider_models_note(choice)
                        )
                        self._refresh_all()

                names = [
                    p["name"] for p in bridge.list_providers(self.root)
                ]
                self.push_screen(
                    PickScreen(
                        "Switch provider", names + [add_label],
                        bridge.provider_name(self.root),
                    ),
                    pick,
                )
        elif cmd == "/mode":
            target = arg.upper()
            if target in MODES and target != "INFERNO":
                self._set_mode(target)
            elif target == "INFERNO" or not arg:
                def ladder_done(choice):
                    if not choice or choice == self.warden.mode:
                        return
                    if choice == "INFERNO":
                        def inferno_done(answer):
                            if answer == "enter":
                                self._set_mode("INFERNO")

                        self.push_screen(InfernoScreen(), inferno_done)
                    else:
                        self._set_mode(choice)

                if target == "INFERNO":
                    def inferno_done2(answer):
                        if answer == "enter":
                            self._set_mode("INFERNO")

                    self.push_screen(InfernoScreen(), inferno_done2)
                else:
                    self.push_screen(
                        LadderScreen(self.warden.mode), ladder_done
                    )
            else:
                self._post_note(
                    "Modes are EMBER, BLAZE, and INFERNO. "
                    "Use /mode to see the ladder."
                )
        elif cmd == "/term":
            target = arg.lower()
            if target in ("front", "back"):
                self._set_term_mode(target)
            elif not arg:
                front_label = "Front end · output streams live"
                back_label = "Back end · label and result only"

                def term_done(choice):
                    if not choice:
                        return
                    self._set_term_mode(
                        "front" if choice == front_label
                        else "back")

                self.push_screen(
                    PickScreen(
                        "Terminal display",
                        [front_label, back_label],
                        front_label if self._term_mode == "front"
                        else back_label,
                    ),
                    term_done,
                )
            else:
                self._post_note(
                    "Terminal display is front or back. "
                    "Use /term to switch.")
        elif cmd == "/theme":
            target = arg.lower()
            if target in ("foxfire", "ember",
                          themes_mod.FOXFIRE):
                self._set_theme(themes_mod.FOXFIRE)
            elif target in ("azure", "kitsune",
                            themes_mod.AZURE):
                self._set_theme(themes_mod.AZURE)
            elif not arg:
                # The picker lists every registered theme
                # (Master, 2026-11-21: /theme is an official
                # command and must show its markers): the
                # default theme carries a "default" marker in
                # its label, and PickScreen itself marks the
                # active one "(active)". Choosing applies at
                # once and is remembered per profile through
                # _set_theme.
                def _theme_label(key):
                    spec = themes_mod.THEMES[key]
                    text = f"{spec['label']} · {spec['blurb']}"
                    if key == themes_mod.DEFAULT:
                        text += " · default"
                    return text

                labels = {
                    key: _theme_label(key)
                    for key in themes_mod.THEMES
                }

                def theme_done(choice):
                    if not choice:
                        return
                    for key, label in labels.items():
                        if choice == label:
                            self._set_theme(key)

                self.push_screen(
                    PickScreen(
                        "Theme",
                        list(labels.values()),
                        labels[self._theme_name],
                    ),
                    theme_done,
                )
            else:
                self._post_note(
                    "Themes are Foxfire Ember and Kitsune "
                    "Azure. Use /theme to switch.")
        elif cmd == "/plan":
            if not arg:
                if self.pulse.plan:
                    lines = []
                    marks = {"done": "✓", "now": "▸", "todo": "·"}
                    for s in self.pulse.plan:
                        lines.append(
                            f"{marks.get(s['state'], '·')} {s['label']}"
                        )
                    self._post_note(
                        f"Plan for: {self.pulse.plan_goal}\n"
                        + "\n".join(lines)
                        + "\nRun it with /plan run."
                    )
                else:
                    self._post_note(
                        "No plan yet. Draft one with /plan <your goal>. "
                        "While drafting, file writing is held at the "
                        "tool level."
                    )
            elif arg.lower() == "run":
                if self.pulse.plan:
                    self._start_plan_run()
                else:
                    self._post_note("There is no plan to run yet.")
            elif arg.lower() == "clear":
                self.pulse.plan = []
                self.pulse.plan_goal = ""
                self.plan_steps = []
                self._post_note("Plan cleared.")
            else:
                self._start_plan_draft(arg)
        elif cmd == "/start":
            icon, label = self._work_state()
            self._post_note(
                f"Work session lit · session #{self.session_id} · "
                f"{icon} {label}. Type a task, or /new for a clean "
                "session."
            )
        elif cmd == "/new":
            self._new_session()
        elif cmd == "/resume":
            self._resume_previous()
        elif cmd == "/cost":
            self._show_cost()
        elif cmd == "/verify":
            self._show_verify()
        elif cmd == "/doctor":
            self._run_self_check()
        elif cmd == "/copy":
            if arg.strip().lower() == "all":
                text = self._transcript_text()
                if text:
                    self._copy_out(text, "the conversation")
                else:
                    self._post_note("Nothing to copy yet.")
            elif self.last_reply:
                self._copy_out(self.last_reply, "Lexis's last reply")
            else:
                self._post_note("Nothing to copy yet.")
        elif cmd == "/evolve":
            self._start_evolve(arg.strip())
        elif cmd == "/skills":
            registry = getattr(self.pulse, "skills", None)
            if registry is None:
                self._post_note("The skill registry is not ready.")
            elif arg.lower().startswith("approve "):
                slug = arg.split(None, 1)[1].strip()
                registry.refresh()
                if registry.approve(slug):
                    self._post_note(
                        f"Skill {slug} approved and active. It "
                        "rides in the catalog from the next turn."
                    )
                else:
                    self._post_note(
                        f"Skill {slug} cannot be approved: it is "
                        "unknown or blocked by the security scan."
                    )
            elif not registry.skills:
                self._post_note("No skills are installed yet.")
            else:
                registry.refresh()
                rows = [
                    f"{r['slug']:<28} {r['status']}"
                    for r in sorted(
                        registry.skills.values(),
                        key=lambda r: r["slug"])
                ]
                self._post_note(
                    "Skills (active ones ride in the catalog):\n"
                    + "\n".join(rows)
                )
        elif cmd == "/orion":
            self._post_note(
                "Orion joins through the ecosystem bridge in a later "
                "phase. Nothing was handed over."
            )
        elif cmd == "/clear":
            self._chat().remove_children()
        elif cmd == "/help":
            self._post(Static(separator_text("COMMANDS"), classes="sep"))
            lines = "\n".join(
                f"{c:<9} {d}" for c, d, _ in PALETTE_COMMANDS
            )
            self._post_note(lines)
        else:
            self._post_note(f"Unknown command {cmd}. Type /help for the list.")
        self._refresh_all()

    def _new_session(self) -> None:
        """Session cycle (Master, 2026-11-10): /new opens a clean
        session with a NEW ledger id; old sessions stay untouched
        in state.db and remain resumable."""
        if self.busy:
            self._post_note(
                "Lexis is working. /stop first, then /new."
            )
            return
        old_id = self.session_id
        self.session_id = self.ledger.start_session(
            self.compass.current)
        self.vault.replace_all(self.vault.bootstrap(self.root))
        for m in self.vault.messages():
            self.ledger.append_message(
                self.session_id, m["role"], m["content"])
        self.pulse.session_id = self.session_id
        self._chat().remove_children()
        self._post_note(
            f"New session lit · session #{self.session_id}. "
            f"Session #{old_id} is untouched and resumable "
            "with /resume."
        )
        self._refresh_all()

    def _resume_previous(self) -> None:
        rows = self.ledger._conn.execute(
            "SELECT id FROM sessions WHERE id != ? ORDER BY id DESC LIMIT 1",
            (self.session_id,),
        ).fetchone()
        if not rows:
            self._post_note("There is no earlier session to resume.")
            return
        self.session_id = int(rows[0])
        self.vault.replace_all(self.ledger.load_messages(self.session_id))
        self._chat().remove_children()
        self._render_history()
        self.pulse.session_id = self.session_id
        self._post_note("Session resumed. The whole history is back.")

    def _set_mode(self, mode: str) -> None:
        self.warden.set_mode(mode)
        self.ledger.append_event(self.session_id, "mode", mode)
        self._post_note(f"Compliance mode is now {mode}.")
        self._refresh_all()

    def _set_term_mode(self, mode: str) -> None:
        """Terminal display mode (Master, 2026-11-10):
        front end streams command output into the live
        panel; back end shows only the tool's label and
        result on the activity strip. Presentation only;
        the full output is journaled in both modes."""
        self._term_mode = mode
        visor_prefs.set_pref(self.root, "term_mode", mode)
        if mode == "front":
            self._post_note(
                "Terminal display: front end. Command output "
                "streams live while it runs.")
        else:
            self._post_note(
                "Terminal display: back end. Commands show "
                "their label and result only; the full output "
                "stays in the journal.")

    def _apply_theme(self, name: str) -> None:
        """Recolor the whole face from the one palette
        table (themes.py): the Textual theme and its CSS
        variables, the flames, the banner, the panels, the
        emblems, the syntax style, and this module's own
        accents. The artwork never changes, only colors."""
        global EMBER, AMBER, DIM, FAINT, PALE, _syntax_active
        spec = themes_mod.THEMES[name]
        self._theme_name = name
        self.theme = name
        _syntax_active = name
        EMBER = spec["ember"]
        AMBER = spec["amber"]
        DIM = spec["dim"]
        FAINT = spec["faint"]
        PALE = spec["pale"]
        flames.set_palette(name)
        banner_mod.set_colors(
            spec["ember"], spec["amber"], spec["pale"],
            spec["faint"], spec["dim"])
        panels.set_colors(
            spec["ember"], spec["amber"],
            spec["foreground"], spec["dim"], spec["faint"])

    def _set_theme(self, name: str) -> None:
        self._apply_theme(name)
        visor_prefs.set_pref(self.root, "theme", name)
        spec = themes_mod.THEMES[name]
        self._post_note(
            f"Theme is now {spec['label']}, {spec['blurb']}.")
        self._refresh_all()

    def _show_cost(self) -> None:
        from lexis.cortex.compass import Compass

        summary = Compass.cost_summary(self.ledger)
        if not summary:
            self._post_note(
                "No finished tasks yet, so there is no cost record. "
                "Costs are recorded per finished task from this "
                "phase on."
            )
            return
        lines = ["Cost per finished task, by model:"]
        for model, s in sorted(summary.items()):
            lines.append(
                f"{model}: {s['tasks']} tasks, {int(s['done_rate'] * 100)}% "
                f"completed, {s['avg_seconds']:.1f} s and "
                f"~{s['avg_tokens'] / 1000:.1f}K tokens on average"
            )
        lines.append(
            "Token counts are estimates; prices are not published by "
            "the provider, so money cost is not shown rather than "
            "guessed."
        )
        self._post_note("\n".join(lines))

    def _show_verify(self) -> None:
        from lexis.cortex import judge as judge_mod

        if self.last_verdict is None and not self._turn_writes:
            self._post_note(
                "Nothing to verify yet. The independent check runs "
                "on every finished turn; its verdict appears right "
                "under the reply."
            )
            return
        tools = []
        for path in self._turn_writes:
            full = path if os.path.isabs(path) else os.path.join(
                self.root, path
            )
            content = ""
            if os.path.isfile(full):
                with open(full, "rb") as f:
                    content = f.read().decode("utf-8", errors="replace")
            tools.append({
                "name": "write_file", "ok": True, "path": path,
                "content": content,
            })
        verdict = judge_mod.verify_turn(
            self.last_reply or "(no reply recorded)", tools, self.root
        )
        mark = {"pass": "✓", "warn": "⚠", "fail": "✗"}[verdict.status]
        lines = [f"{mark} Independent check: {verdict.status}"]
        lines += [f"  · {r}" for r in verdict.reasons]
        self._post_note("\n".join(lines))

    def _run_self_check(self) -> None:
        from lexis import doctor

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = doctor.run()
        verdict = "passed" if code == 0 else "found problems"
        self._post_note(f"Self-check {verdict}.\n" + buf.getvalue().strip())


def run_visor(argv=None) -> int:
    argv = list(argv or [])
    app = LexisVisor(resume="--resume" in argv)
    app.run()
    return 0
