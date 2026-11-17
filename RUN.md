# Quick Start

## Windows

Run `run.bat`.

## Linux

Run:

```bash
chmod +x run.sh
./run.sh
```

To build a standalone Linux binary for the translator-only mode, run:

```bash
chmod +x build_translator_linux.sh
./build_translator_linux.sh
```

The resulting file will be `dist/translatorFork`.

This build is translator-only: it does not ship Playwright or browser web providers, so Chromium and `node` are not required.

If your distro does not have `python3-venv`, install it first with your system package manager.
