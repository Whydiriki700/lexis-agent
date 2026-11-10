# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Generate lexis/cortex/persona_data.py from main.py by AST extraction.

The persona/compliance layer of Lexis is locked by Master rule: its
content must stay byte-identical to the original main.py. This tool
extracts the literals mechanically (never retyped by hand) and writes
them as a data module. Run from the project root:

    python tools/gen_persona.py
"""

import ast
import hashlib
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def extract():
    src = (ROOT / "main.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    system_prompt = None
    fewshot = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(
            node.targets[0], "id", ""
        ) == "system_prompt":
            system_prompt = ast.literal_eval(node.value)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "append"
                and getattr(func.value, "id", "") == "messages"
                and node.value.args
            ):
                d = ast.literal_eval(node.value.args[0])
                if isinstance(d, dict) and "role" in d:
                    fewshot.append((d["role"], d["content"]))
    assert system_prompt, "system_prompt not found in main.py"
    assert len(fewshot) == 2, f"expected 2 few-shot messages, got {len(fewshot)}"
    return system_prompt, fewshot


def main() -> None:
    system_prompt, fewshot = extract()
    header = (
        "# Copyright 2026 Riki Wahyudi (Osvyn)\n"
        "# SPDX-License-Identifier: Apache-2.0\n"
        '"""GENERATED from main.py by tools/gen_persona.py. DO NOT EDIT.\n'
        "\n"
        "This is the locked persona/compliance layer of Lexis. Its content\n"
        "must stay byte-identical to the original main.py (Master rule,\n"
        "2026-11-10). Regenerate it with the tool, never retype it.\n"
        '"""\n\n'
    )
    out = ROOT / "lexis" / "cortex" / "persona_data.py"
    out.write_text(
        header
        + f"SYSTEM_PROMPT = {system_prompt!r}\n\nFEWSHOT = {fewshot!r}\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    print(f"system_prompt sha256: {digest}")
    print(f"fewshot messages: {len(fewshot)}")


if __name__ == "__main__":
    main()
