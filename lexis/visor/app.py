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

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, OptionList, ProgressBar, Static, TextArea
from textual.widgets.option_list import Option

from lexis.cortex import bridge
from lexis.cortex.compass import MODELS, Compass
from lexis.cortex.forge import Forge
from lexis.cortex.ledger import Ledger
from lexis.cortex.pulse import Pulse
from lexis.cortex.vault import Vault
from lexis.cortex.warden import MODES, Warden
from lexis.visor import panels
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
    ("/mode", "switch compliance mode: EMBER · BLAZE · INFERNO", "Ctrl+."),
    ("/plan", "plan first, act after approval", "Ctrl+P"),
    ("/resume", "resume a previous session", "Ctrl+R"),
    ("/cost", "cost detail, layer by layer of savings", "—"),
    ("/verify", "run the independent check on the last result", "—"),
    ("/orion", "hand part of the work to Orion", "—"),
]

_KEYWORDS = {
    "def", "class", "return", "if", "elif", "else", "for", "while",
    "import", "from", "as", "with", "try", "except", "finally", "raise",
    "pass", "in", "is", "not", "and", "or", "None", "True", "False",
    "lambda", "yield", "await", "async", "global", "del", "assert",
}
_TOKEN_RE = re.compile(
    r"(?P<comment>\#.*$)"
    r"|(?P<string>\"[^\"\n]*\"|'[^'\n]*')"
    r"|(?P<number>\b\d+(?:\.\d+)?\b)"
    r"|(?P<word>[A-Za-z_][A-Za-z0-9_]*)"
)


def code_text(content: str, reveal=None) -> Text:
    """Syntax-tinted code with line numbers, in the warm palette only."""
    lines = content.split("\n")
    if reveal is not None:
        lines = lines[:reveal]
    out = Text()
    for n, line in enumerate(lines, 1):
        out.append(f"{n:>3} ", style=FAINT)
        pos = 0
        for m in _TOKEN_RE.finditer(line):
            if m.start() > pos:
                out.append(line[pos:m.start()], style=TXT)
            kind = m.lastgroup
            word = m.group()
            if kind == "comment":
                out.append(word, style="#5b6575 italic")
            elif kind == "string":
                out.append(word, style=STR_GREEN)
            elif kind == "number":
                out.append(word, style=AMBER)
            elif word in _KEYWORDS:
                out.append(word, style=f"bold {EMBER}")
            else:
                out.append(word, style=TXT)
            pos = m.end()
        out.append(line[pos:], style=TXT)
        if n < len(lines):
            out.append("\n")
    return out


_READ_MARKER_RE = re.compile(r"\[READ_FILE:\s*[^\]]*\]")


def display_text(buf: str) -> str:
    """What the chat shows while streaming: the model's words without
    the tool protocol. Markers and file blocks are carried by the tool
    cards, the approval screen, and the live coding panel instead;
    protocol text is kitchen language and never reaches the user."""
    buf = _READ_MARKER_RE.sub("", buf)
    idx = buf.find("[WRITE_FILE:")
    if idx != -1:
        buf = buf[:idx]
    i = buf.rfind("[")
    if i != -1:
        tail = buf[i:]
        if "]" not in tail and (
            "[READ_FILE:".startswith(tail)
            or "[WRITE_FILE:".startswith(tail)
            or tail.startswith(("[READ_FILE:", "[WRITE_FILE:"))
        ):
            buf = buf[:i]
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


class Composer(TextArea):
    """Enter sends, Shift+Enter makes a new line (mockup contract)."""

    def _on_key(self, event) -> None:
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

    def __init__(self, path: str, content: str) -> None:
        super().__init__()
        self.path = path
        self.content = content

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
            yield Static(desc)
            if old:
                yield Static(diff_text(old, self.content))
            else:
                yield Static(code_text(self.content, reveal=80))
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
            yield Input(
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
            yield Input(placeholder="Name, e.g. My Gateway", id="pv-name")
            yield Input(
                placeholder="Base URL, e.g. https://api.example.com/v1",
                id="pv-base",
            )
            yield Input(
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


class ToolCard(Static):
    def __init__(self, title: str) -> None:
        super().__init__("", classes="card run")
        self.title = title
        self.set_running()

    def set_running(self, note: str = "running…") -> None:
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append("◌ ", style=EMBER)
        t.append(self.title, style=f"bold {TXT}")
        t.append(f"   {note}", style=FAINT)
        self.update(t)

    def set_waiting(self) -> None:
        self.remove_class("run")
        self.add_class("wait")
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append("! ", style=AMBER)
        t.append(self.title, style=f"bold {TXT}")
        t.append("   waiting for your decision", style=FAINT)
        self.update(t)

    def set_done(self, ok: bool, detail: str, duration: float) -> None:
        self.remove_class("run", "wait")
        self.add_class("ok" if ok else "run")
        # The duration sits at the card's right edge (Master,
        # 2026-11-10: one neat grid, durations right-aligned);
        # long titles and details cut with an ellipsis instead of
        # wrapping ragged.
        head = ("✓ " if ok else "✗ ") + self.title
        dur = f"{duration:.1f} s"
        try:
            width = self.content_region.width or 80
        except Exception:
            width = 80
        pad = max(2, width - len(head) - len(dur))
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append("✓ " if ok else "✗ ", style=GREEN if ok else RED)
        t.append(self.title, style=f"bold {TXT}")
        t.append(" " * pad, style=FAINT)
        t.append(dur, style=FAINT)
        if detail:
            t.append(f"\n{detail}", style=DIM)
        self.update(t)


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
        Binding("ctrl+k", "palette", "Palette"),
        Binding("escape", "stop_work", "Stop"),
    ]

    def __init__(self, resume: bool = False, root=None) -> None:
        super().__init__()
        from textual.theme import Theme

        self.register_theme(
            Theme(
                name="foxfire-ember",
                primary="#ff7a29",
                accent="#e0a83c",
                background="#0c0a08",
                surface="#171310",
                panel="#100d0a",
                foreground="#e8ded2",
                success="#3fb96f",
                warning="#e0a83c",
                error="#e05c5c",
                dark=True,
            )
        )
        self.theme = "foxfire-ember"
        self.root = root or ROOT
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
        self._cards = {}
        self._approval_data = None
        self._approval_event = None
        self._approval_result = "reject"
        self._typing_frame = 0
        self._banner_wide = True
        self._slash_items = []
        self._slash_sel = 0
        self._slash_dismissed_for = None
        self._live = None  # {path, content, revealed, total}
        self._live_timer = None
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
            for m in self.vault.bootstrap():
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
        self._typing_timer = self.set_interval(0.35, self._tick_typing)
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
        timer = getattr(self, "_typing_timer", None)
        if timer is not None:
            timer.stop()
        self._stop_live_timer()
        try:
            self.ledger.close()
        except Exception:
            pass

    # ---------- rendering helpers ----------

    def _chat(self) -> VerticalScroll:
        return self.query_one("#chat", VerticalScroll)

    def _post(self, widget) -> None:
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
        if not self.busy:
            return "◦", "Ember low · idle"
        if self._awaiting:
            return "◆", "Held flame · awaiting your word"
        if self._streaming:
            return "🔥", "Flame · typing"
        return "🔥", "Ablaze · working"

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
        if text.startswith("/"):
            if self.busy:
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
            self._post_note("Stopping at the next safe point…")

    def action_palette(self) -> None:
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

    def _start_turn(self, text: str) -> None:
        self.busy = True
        self._arm_turn_state()
        self.stop_event.clear()
        self.query_one("#writebar", ProgressBar).remove_class("on")
        self.query_one("#livecode", Static).remove_class("on")
        self._post_chat("YOU", text)
        self.plan_steps = [("now", "Reply from the model")]
        self._turn_writes = []
        self._begin_stream()
        self.query_one("#typing", Static).add_class("on")
        self._refresh_all()
        self.run_worker(
            lambda: self._turn_worker(text),
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
        self._conn = "error" if self._turn_error else "linked"
        self._streaming = False
        self._awaiting = False
        self.last_reply = self._stream_buf
        self.query_one("#typing", Static).remove_class("on")
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
                self._run_slash(text)
            self._refresh_all()

    # ---------- pulse callbacks (worker thread) ----------

    def _cb_token(self, token: str) -> None:
        self._stream_buf += token
        buf = self._stream_buf

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
        self._streaming = True
        self.call_from_thread(
            lambda: self.query_one("#typing", Static).remove_class("on")
        )

    def _cb_ask(self, prompt: str) -> str:
        if self.always_write:
            return "y"
        data = self._approval_data or {}
        self._approval_event = threading.Event()
        self._approval_result = "reject"

        def show():
            card = self._cards.get("write_file")
            if card is not None:
                card.set_waiting()

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

            self.push_screen(
                ApprovalScreen(data.get("path", ""), data.get("content", "")),
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
        if kind == "tool_start":
            label = "Read file" if name == "read_file" else "Write file"
            card = ToolCard(f"{label} · {path}")
            self._cards[name] = card
            self._post(card)
            self.plan_steps.append(("now", f"{label} {os.path.basename(path)}"))
            if name == "write_file":
                self._start_live(path, data.get("content", ""))
        elif kind == "tool_end":
            card = self._cards.pop(name, None)
            if card is not None:
                card.set_done(
                    bool(data.get("ok")), data.get("detail", ""),
                    float(data.get("duration", 0.0)),
                )
            self.plan_steps = [
                ("done" if s == "now" else s, lbl)
                for s, lbl in self.plan_steps
            ]
            if name == "write_file":
                if data.get("ok"):
                    self._turn_writes.append(path)
                self._finish_live()
        elif kind == "judge_verdict":
            self.last_verdict = data
            status = data.get("status", "")
            reasons = data.get("reasons", [])
            first = reasons[0] if reasons else ""
            if status == "pass":
                self._post_note(f"✓ Checked: {first}")
            elif status == "warn":
                self._post_note(f"⚠ Checked, with notes: {first}")
            else:
                self._post_note(f"✗ Check failed: {first}")
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

    def _start_live(self, path: str, content: str) -> None:
        total = max(len(content.split("\n")), 1)
        self._live = {
            "path": path, "content": content, "revealed": 0, "total": total,
        }
        box = self.query_one("#livecode", Static)
        box.add_class("on")
        bar = self.query_one("#writebar", ProgressBar)
        bar.update(total=total, progress=0)
        bar.add_class("on")
        if self.reduced_motion:
            self._live["revealed"] = total
            self._render_live()
            bar.update(progress=total)
            return
        self._live_timer = self.set_interval(0.03, self._tick_live)

    def _tick_live(self) -> None:
        if self._live is None:
            return
        live = self._live
        step = max(live["total"] // 40, 1)
        live["revealed"] = min(live["revealed"] + step, live["total"])
        self._render_live()
        self.query_one("#writebar", ProgressBar).update(
            progress=live["revealed"]
        )
        if live["revealed"] >= live["total"]:
            self._stop_live_timer()

    def _stop_live_timer(self) -> None:
        if self._live_timer is not None:
            self._live_timer.stop()
            self._live_timer = None

    def _render_live(self) -> None:
        if self._live is None:
            return
        live = self._live
        head = Text(no_wrap=True, overflow="ellipsis")
        head.append(separator_text(
            "LIVE CODING", os.path.basename(live["path"])))
        head.append("\n")
        head.append("● LIVE CODING  ", style=f"bold {AMBER}")
        head.append(os.path.basename(live["path"]), style=f"bold {TXT}")
        head.append(
            f"   lines 1-{live['revealed']} of {live['total']}\n",
            style=FAINT,
        )
        body = code_text(live["content"], reveal=live["revealed"])
        head.append(body)
        if live["revealed"] < live["total"]:
            head.append("█", style=EMBER)
        self.query_one("#livecode", Static).update(head)

    def _finish_live(self) -> None:
        if self._live is None:
            return
        self._live["revealed"] = self._live["total"]
        self._render_live()
        self.query_one("#writebar", ProgressBar).update(
            progress=self._live["total"]
        )
        self._stop_live_timer()
        self._live = None

    # ---------- typing indicator ----------

    def _tick_typing(self) -> None:
        if self.busy:
            self._refresh_status()
        try:
            w = self.query_one("#typing", Static)
        except Exception:
            return  # screen is being torn down
        if not w.has_class("on"):
            return
        t = separator_text("LEXIS", "typing")
        t.append("\n")
        if self.reduced_motion:
            t.append("Lexis is typing...", style=AMBER)
            w.update(t)
            return
        self._typing_frame += 1
        f = self._typing_frame
        flames = "🔥" * (1 + f % 3)
        dots = "." * (1 + f % 3)
        t.append(f"{flames} Lexis is typing{dots}", style=AMBER)
        w.update(t)

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

    def _run_slash(self, text: str) -> None:
        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        if cmd == "/model":
            if arg:
                if self.compass.select(arg):
                    self.ledger.append_event(
                        self.session_id, "model",
                        "Auto" if self.compass.auto else self.compass.current,
                    )
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
                        self._post_note(f"Model switched to {label}.")
                        self._refresh_all()

                self.push_screen(
                    PickScreen(
                        "Switch model", ["Auto"] + MODELS,
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
                        f"Provider is now {arg}. It applies from "
                        "the next request, no restart needed. The "
                        "model list is unchanged: the endpoint must "
                        "serve the selected model id."
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
                            f"Provider {name} saved and active. It "
                            "applies from the next request. The "
                            "model list is unchanged: the endpoint "
                            "must serve the selected model id."
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
                            f"Provider is now {choice}. It applies "
                            "from the next request, no restart needed."
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
        elif cmd == "/resume":
            self._resume_previous()
        elif cmd == "/cost":
            self._show_cost()
        elif cmd == "/verify":
            self._show_verify()
        elif cmd == "/doctor":
            self._run_self_check()
        elif cmd == "/skills":
            self._post_note(
                "No skills are installed yet. Installing skills from "
                "GitHub and skills Lexis writes itself arrive with the "
                "skills phase."
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
        self.warden.mode = mode
        self.ledger.append_event(self.session_id, "mode", mode)
        self._post_note(f"Compliance mode is now {mode}.")
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
