import sys

if __name__ == "__main__":
    # `python main.py scan <folder> [options]` runs the headless CLI (no
    # PySide6 / display required); anything else launches the GUI as
    # before (including the existing --minimized / --tray flags).
    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        from audiocleaner.cli import main as cli_main
        sys.exit(cli_main(sys.argv[2:]))
    else:
        from audiocleaner.gui import main as gui_main
        gui_main()
