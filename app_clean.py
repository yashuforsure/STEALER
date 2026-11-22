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
