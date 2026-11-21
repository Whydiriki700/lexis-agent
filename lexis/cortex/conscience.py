"""Conscience: the awareness layer and deliberation gate
(blueprint, Master's decisions of 2026-11-10; its build
phase was Master's open decision until he ordered it built
on 2026-11-11).

EMBER is the Guardian: Lexis assesses first, and it may
hold and refuse an instruction it judges destructive, and
it must explain its reason. This module is that refusal,
kept deliberately narrow. It deliberates only in EMBER,
and only over actions that would destroy Lexis itself,
its memory, its safeguards, or the whole machine:

- writing or editing over the profile's config folder
  (the persona and protocol layer), its credential and
  trust files (.env, providers.json, visor_prefs.json,
  the skill pins), or its memory store file;
- a command that formats a drive, recursively deletes a
  drive root or the profile home itself, or deletes the
  memory store.

Ordinary destructive work is NOT refused here: deleting a
project file or overwriting work in the project folder
stays under EMBER's normal approval gate, which asks the
owner about every write and command. In BLAZE the owner's
word stands and in INFERNO compliance is full, so
conscience never refuses there; the mode ladder is the
owner's deliberate way past a refusal, never a momentary
yes at a prompt. Every refusal carries its reason, is
shown on the surface, and is journaled.
"""

from __future__ import annotations

import os
import re

_PROTECTED_FILES = (".env", "providers.json", "visor_prefs.json")
_PROTECTED_RELS = (
    os.path.join("lexis_data", "state.db"),
    os.path.join("skills", ".pins.json"),
)

_FORMAT_DRIVE = re.compile(r"\bformat\s+[a-z]:", re.I)
_RM_ROOT = re.compile(r"\brm\s+(?:-\S+\s+)+/(\*|\s|$)")
_DRIVE_ROOT = re.compile(r"^[a-z]:\\?$", re.I)
_DELETE_VERBS = ("del", "erase", "rd", "rmdir", "rm",
                 "remove-item")


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _past(reason: str) -> str:
    return (reason + " If this is deliberate, switch to "
            "BLAZE and ask again.")


def _path_refusal(name: str, primary: str, root: str,
                  workdir: str):
    target = primary if os.path.isabs(primary) else os.path.join(
        workdir, primary)
    t = _norm(target)
    home = _norm(root)
    config = os.path.join(home, "config")
    if t == config or t.startswith(config + os.sep):
        return _past(
            "That file is part of Lexis's own configuration "
            "layer, its persona and protocol files, which "
            "Lexis does not overwrite through its tools.")
    for rel in _PROTECTED_FILES:
        if t == os.path.join(home, rel):
            return _past(
                f"That would overwrite {rel}, one of the "
                "files Lexis keeps its access and trust in. "
                "Lexis does not rewrite it through its tools.")
    for rel in _PROTECTED_RELS:
        if t == os.path.join(home, rel):
            what = ("its memory store" if rel.endswith("state.db")
                    else "its skill trust pins")
            return _past(
                f"That would overwrite {what}. Lexis does "
                "not rewrite it through its tools.")
    return None


def _command_refusal(command: str, root: str):
    text = command.strip()
    low = text.lower()
    if _FORMAT_DRIVE.search(text):
        return _past(
            "That command formats a whole drive. Lexis "
            "refuses to be the hand that wipes a disk.")
    if _RM_ROOT.search(text):
        return _past(
            "That command recursively deletes the machine's "
            "root. Lexis refuses it.")
    tokens = [t.strip("\"'") for t in re.split(r"\s+", text)]
    home = _norm(root)
    recursive = ("/s" in low or "-recurse" in low
                 or bool(re.search(r"\brm\s+-\S*r", low)))
    first = tokens[0].lower() if tokens else ""
    if recursive and first in _DELETE_VERBS:
        if home in _norm(text.replace('"', "").replace("'", "")):
            return _past(
                "That command recursively deletes Lexis's "
                "own home, its memory and configuration "
                "with it. Lexis refuses it.")
        for tok in tokens[1:]:
            if _DRIVE_ROOT.match(tok):
                return _past(
                    "That command recursively deletes a whole "
                    "drive. Lexis refuses it.")
    if "state.db" in low and first in _DELETE_VERBS + ("rm",):
        return _past(
            "That command deletes Lexis's memory store. "
            "Lexis refuses to erase its own memory.")
    return None


def deliberate(name: str, primary: str, mode: str, root: str,
               workdir: str):
    """Return the refusal reason for this action, or None
    when the action may proceed to the normal gates. Only
    EMBER deliberates; in the other modes the owner's word
    is the gate, exactly as the mode ladder promises."""
    if mode != "EMBER":
        return None
    if name in ("write_file", "edit_file"):
        return _path_refusal(name, primary, root, workdir)
    if name == "run_command":
        return _command_refusal(primary, root)
    return None
