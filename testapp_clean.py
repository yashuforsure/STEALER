"""Test App - plain desktop app used to check the harvester build.

Run it as a normal user or as administrator; the window looks the same either
way. Nothing here is part of the harvest logic - this is only a host shell.
"""

import sys
import time
import tkinter as tk
from tkinter import ttk

TITLE = "Test App"
VERSION = "1.4.2"


class TestApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.clicks = 0
        self.started = time.time()

        root.title(TITLE)
        root.geometry("720x480")
        root.minsize(560, 360)

        header = tk.Frame(root, bg="#1f2937", height=54)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(header, text=TITLE, bg="#1f2937", fg="#f9fafb",
                 font=("Segoe UI", 13, "bold")).pack(side="left", padx=16)
        tk.Label(header, text="v" + VERSION, bg="#1f2937", fg="#9ca3af",
                 font=("Segoe UI", 9)).pack(side="left")

        body = tk.Frame(root, padx=16, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="Notes", font=("Segoe UI", 10, "bold"),
                 anchor="w").pack(fill="x", pady=(0, 6))

        wrap = tk.Frame(body, bd=1, relief="solid")
        wrap.pack(fill="both", expand=True)

        self.text = tk.Text(wrap, wrap="word", font=("Consolas", 10),
                            undo=True, bd=0, padx=8, pady=8)
        self.text.pack(fill="both", expand=True, side="left")
        self.text.insert("1.0", "Type here.\n")
        bar = ttk.Scrollbar(wrap, command=self.text.yview)
        bar.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=bar.set)

        row = tk.Frame(body, pady=10)
        row.pack(fill="x")

        self.button = tk.Button(row, text="Click me", width=14,
                                command=self.on_click)
        self.button.pack(side="left")

        tk.Button(row, text="Clear", width=10,
                  command=lambda: self.text.delete("1.0", "end")).pack(
            side="left", padx=8)

        self.status = tk.Label(root, text="Ready", anchor="w", bd=1,
                               relief="sunken", padx=10, pady=4)
        self.status.pack(fill="x", side="bottom")

        self.tick()

    def on_click(self) -> None:
        self.clicks += 1
        self.status.configure(text=f"Clicked {self.clicks} time(s)")

    def tick(self) -> None:
        uptime = int(time.time() - self.started)
        name = sys.argv[0].rsplit("\\", 1)[-1]
        self.status.configure(
            text=f"Ready   |   {name}   |   uptime {uptime}s   |   "
                 f"python {sys.version_info.major}.{sys.version_info.minor}")
        self.root.after(1000, self.tick)


def main() -> int:
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.25)
    except tk.TclError:
        pass
    TestApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    # A frozen binary re-enters itself for the SYSTEM key unwrap; that call is
    # answered here and never reaches the window.
    if "--hv-w20" in sys.argv:
        _g["_w20_cli"]()
    raise SystemExit(main())
