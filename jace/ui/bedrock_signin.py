"""Xbox sign-in for Bedrock on Linux (BedrockOnLinux's device-code login): Realms, servers,
Friends and the Marketplace need it. Shown before Play when you aren't signed in."""
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from jace.ui.common import run_task


class XboxSignInDialog(QDialog):
    """accept() = signed in; reject() with offline=True = play without online features."""

    def __init__(self, data, parent=None):
        super().__init__(parent)
        from jace import bol
        self.offline = False
        self.url = ""
        self.setWindowTitle("Sign in to Xbox")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        intro = QLabel("<b>Sign in with the Microsoft account that owns Minecraft</b><br>"
                       "Realms, servers, Friends and the Marketplace need it. You only do this once.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.step = QLabel("Getting a sign-in code…")
        self.step.setWordWrap(True)
        lay.addWidget(self.step)
        self.code = QLabel("")
        f = QFont()
        f.setPointSize(26)
        f.setBold(True)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
        self.code.setFont(f)
        self.code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.code)
        row = QHBoxLayout()
        self.open_btn = QPushButton("Open sign-in page")
        self.open_btn.setObjectName("primary")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open)
        self.copy_btn = QPushButton("Copy code")
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.code.text()))
        offline = QPushButton("Play offline")
        offline.setToolTip("Single-player and LAN only: no Realms, servers, Friends or Marketplace")
        offline.clicked.connect(self._offline)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        for b in (self.open_btn, self.copy_btn):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(offline)
        row.addWidget(cancel)
        lay.addLayout(row)

        self.login = bol.XboxLogin(data, lambda url, code: None)
        run_task(lambda callback: self._run(callback), use_callback=True, on_status=self._got_code,
                 on_done=self._finished, on_error=self._failed)

    def _run(self, callback):
        self.login.on_code = lambda url, code: callback["setStatus"](f"{url}\n{code}")
        return self.login.run()

    def _got_code(self, msg: str):
        if "\n" not in msg:
            return
        self.url, code = msg.split("\n", 1)
        self.code.setText(code)
        self.step.setText(f"Go to <b>{self.url.replace('https://', '')}</b> and enter this code. It opens in "
                          "your browser; this window closes by itself when you're signed in.")
        self.step.setTextFormat(Qt.TextFormat.RichText)
        self.open_btn.setEnabled(True)
        self.copy_btn.setEnabled(True)
        QGuiApplication.clipboard().setText(code)
        self._open()

    def _open(self):
        if self.url:
            webbrowser.open(f"{self.url}?otc={self.code.text()}")

    def _finished(self, ok):
        if self.isVisible():
            if ok:
                self.accept()
            else:
                self.step.setText("The sign-in didn't finish (the code may have expired). Close this and press "
                                  "Play to try again, or play offline.")

    def _failed(self, msg):
        if self.isVisible():
            self.step.setText(msg)

    def _offline(self):
        self.offline = True
        self.reject()

    def done(self, r):
        self.login.stop()
        super().done(r)
