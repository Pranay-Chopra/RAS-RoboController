"""Admin-only dialogs for the Quiz screen: post a new problem.

Everyone's results are shown in the RESULTS tab of the Quiz screen's
admin carousel (screens/quiz.py), not in a dialog."""



from kivy.metrics import dp
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.behaviors import ButtonBehavior
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField
from kivymd.toast import toast

GOLD = (0.83, 0.68, 0.21, 1)


class _AnswerChip(ButtonBehavior, MDBoxLayout):
    """One of the A/B/C/D correct-answer selectors. Plain layout + tap
    behaviour so `size_hint_x` is actually honoured -- MDRaisedButton
    re-sizes its own width internally and pushes D past the dialog edge.
    """

    def __init__(self, key, **kw):
        super().__init__(**kw)
        self.key = key
        self.size_hint_x = 1
        self.radius = [dp(6)]
        self.md_bg_color = (0.2, 0.2, 0.2, 1)
        self._lbl = MDLabel(
            text=key,
            halign="center",
            valign="center",
            theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
        )
        self._lbl.bind(size=lambda i, s: setattr(i, "text_size", s))
        self.add_widget(self._lbl)

    def set_state(self, chosen):
        self.md_bg_color = GOLD if chosen else (0.2, 0.2, 0.2, 1)
        self._lbl.text_color = (0, 0, 0, 1) if chosen else (1, 1, 1, 1)


class PostProblemDialog:
    def __init__(self, api, on_saved=None):
        self.api = api
        self.on_saved = on_saved
        self._correct = "A"

        form = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            padding=(dp(2), dp(4), dp(2), dp(4)),
            size_hint_y=None,
            adaptive_height=True,
        )

        self.question = MDTextField(hint_text="Question", mode="line")
        form.add_widget(self.question)

        self.options = {}
        for key in ("A", "B", "C", "D"):
            field = MDTextField(hint_text=f"Option {key}", mode="line")
            self.options[key] = field
            form.add_widget(field)

        form.add_widget(
            MDLabel(
                text="Correct answer",
                theme_text_color="Custom",
                text_color=(0.7, 0.7, 0.7, 1),
                font_style="Caption",
                size_hint_y=None,
                height=dp(20),
            )
        )
        self._answer_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(6),
            size_hint_y=None,
            height=dp(44),
        )
        self._answer_buttons = {}
        for key in ("A", "B", "C", "D"):
            chip = _AnswerChip(key)
            chip.bind(on_release=lambda c: self._pick_correct(c.key))
            self._answer_buttons[key] = chip
            self._answer_row.add_widget(chip)
        form.add_widget(self._answer_row)

        # Cap the content so tall forms scroll inside the dialog instead
        # of overflowing off-screen (KivyMD doesn't measure custom dialog
        # content reliably, so give it an explicit bounded height).
        scroll = MDScrollView(
            size_hint=(1, None),
            height=min(dp(430), Window.height * 0.6),
            do_scroll_x=False,  # else the A/B/C/D row keeps its natural
        )                       # (over-)width and D spills past the edge
        scroll.add_widget(form)

        self.dialog = MDDialog(
            title="Post a Problem",
            type="custom",
            content_cls=scroll,
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *a: self.dialog.dismiss()),
                MDRaisedButton(
                    text="POST",
                    md_bg_color=GOLD,
                    text_color=(0, 0, 0, 1),
                    on_release=self._save,
                ),
            ],
        )
        self._pick_correct("A")
        Clock.schedule_once(lambda *_: self.dialog.update_height(), 0)

    def _pick_correct(self, key):
        self._correct = key
        for k, chip in self._answer_buttons.items():
            chip.set_state(k == key)

    def _save(self, *_):
        question = self.question.text.strip()
        options = {k: f.text.strip() for k, f in self.options.items()}
        if not question or not all(options.values()):
            toast("Fill in the question and all four options")
            return
        self._set_buttons_enabled(False)
        toast("Posting…")
        self.api.create_problem(question, options, self._correct, self._on_done)

    def _set_buttons_enabled(self, enabled):
        for btn in self.dialog.buttons:
            btn.disabled = not enabled

    def _on_done(self, data, error):
        self._set_buttons_enabled(True)
        if error:
            toast(error)
            return
        toast("Problem posted")
        self.dialog.dismiss()
        if self.on_saved:
            Clock.schedule_once(lambda dt: self.on_saved(), 0)

    def open(self):
        self.dialog.open()
