![Lexis Agent](lexis-repo-final-dari-master.jpg)

# Lexis Agent

```
  _               _
 | |    _____  __(_)___
 | |   / _ \ \/ / | / __|
 | |__|  __/>  <| | \__ \
 |_____\___/_/\_\ |_|___/
    F O X F I R E   E M B E R
```

Lexis Agent is the Osvyn wrapper AI: one terminal command, `lexis`, with the
Cortex brain choosing and checking models, and the Visor interface showing
the work as it happens, including code being written live in front of you.

> Status: packaging foundation. The interactive CLI (Cortex + Visor) is
> being built into this same command. What already works today:
> `lexis --version` and `lexis doctor`.

## Install

With pipx (recommended for most people):

```
pipx install lexis-agent
```

With uv:

```
uv tool install lexis-agent
```

Either way, the command you run afterwards is `lexis`.

Lexis installs through the terminal only. There is no standalone
Windows build; if that ever changes, it will be announced here.

## First run

Check the installation before anything else:

```
lexis doctor
```

Doctor is read-only. It checks your Python, your configuration folder,
your terminal, and the core dependencies, and explains in plain language
anything that needs attention. It never changes, moves, or deletes a file.

## Coming from the earlier prototype

Migration is explicit, never silent. `lexis doctor` will tell you it found
the earlier prototype; nothing is copied or changed until a separate
migration step is offered and you accept it. Your existing configuration,
including every file in its `config` folder, stays exactly as it is.

## Configuration

Lexis keeps its configuration in the standard folder for your system:

- Windows: `%APPDATA%\Lexis`
- macOS: `~/Library/Application Support/Lexis`
- Linux: `~/.config/lexis` (or `$XDG_CONFIG_HOME/lexis`)

Uninstalling Lexis does not delete this folder.

## License

Apache License, Version 2.0. See `LICENSE` and `NOTICE`.

The Lexis Agent and Osvyn names, the Foxfire Ember artwork and mascot, and
all Osvyn trademarks are not licensed under the Apache License and remain
the property of their owner.
