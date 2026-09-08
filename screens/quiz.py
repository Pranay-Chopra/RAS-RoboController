from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.metrics import dp
from kivy.properties import BooleanProperty
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.carousel import Carousel
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton, MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.toast import toast

import quiz_config
from services.google_auth import GoogleAuth
from services.quiz_api import QuizAPI
from dialogs.quiz_dialogs import PostProblemDialog

GOLD = (0.83, 0.68, 0.21, 1)

# Per-question answer window. Each unanswered question card counts down
# from this the moment the quiz renders; at zero it locks with whatever
# is selected (nothing -> recorded as a wrong no-answer).
ANSWER_SECONDS = 15

# Roboto (KivyMD's default) has no glyph for the result marks U+2713 / U+2A2F
# -- they render as tofu. DejaVuSans (shipped with Kivy) has both.
_SYM_FONT = "Roboto"
try:
    LabelBase.register(name="QuizSym", fn_regular="data/fonts/DejaVuSans.ttf")
    _SYM_FONT = "QuizSym"
except Exception as e:  # pragma: no cover
    print(f"[QuizScreen] Could not register symbol font: {e}")

MARK_OK = chr(0x2713)  # U+2713 CHECK MARK
MARK_NO = chr(0x2A2F)  # U+2A2F VECTOR OR CROSS PRODUCT
MARK_UP = chr(0x25B2)  # U+25B2 BLACK UP-POINTING TRIANGLE (sort asc)
MARK_DOWN = chr(0x25BC)  # U+25BC BLACK DOWN-POINTING TRIANGLE (sort desc)


def _label(text, **kw):
    kw.setdefault("theme_text_color", "Custom")
    kw.setdefault("text_color", (0.9, 0.9, 0.9, 1))
    kw.setdefault("size_hint_y", None)
    lbl = MDLabel(text=text, **kw)
    lbl.bind(
        width=lambda inst, w: setattr(inst, "text_size", (w, None)),
        texture_size=lambda inst, ts: setattr(inst, "height", ts[1]),
    )
    return lbl


def _sym_label(text, color=(0.9, 0.9, 0.9, 1)):
    """Plain Kivy Label in the DejaVu symbol font so the ✓ / ⨯ marks
    render (Roboto has no glyph for them)."""
    lbl = Label(
        text=text,
        font_name=_SYM_FONT,
        color=color,
        size_hint_y=None,
        halign="left",
        valign="top",
    )
    lbl.bind(
        width=lambda i, w: setattr(i, "text_size", (w, None)),
        texture_size=lambda i, ts: setattr(i, "height", ts[1]),
    )
    return lbl


def _scroll_body(padding=dp(16), spacing=dp(12)):
    """A vertical, height-driven MDBoxLayout inside a vertical-only
    ScrollView. Returns (scroll, box); add content to `box`."""
    box = MDBoxLayout(
        orientation="vertical",
        padding=padding,
        spacing=spacing,
        size_hint_y=None,
    )
    box.bind(minimum_height=box.setter("height"))
    scroll = ScrollView(do_scroll_x=False)
    scroll.add_widget(box)
    return scroll, box


class _TabButton(ButtonBehavior, MDBoxLayout):
    """Flat tab header for the admin carousel. Plain layout + tap
    behaviour so `size_hint_x` is honoured (MDRaisedButton manages its
    own width and spills past the edge -- see quiz_dialogs._AnswerChip)."""

    def __init__(self, text, **kw):
        super().__init__(**kw)
        self.size_hint_x = 1
        self.md_bg_color = (0.2, 0.2, 0.2, 1)
        self._lbl = MDLabel(
            text=text,
            halign="center",
            valign="center",
            bold=True,
            font_style="Button",
            theme_text_color="Custom",
            text_color=(0.9, 0.9, 0.9, 1),
        )
        self._lbl.bind(size=lambda i, s: setattr(i, "text_size", s))
        self.add_widget(self._lbl)

    def set_active(self, active):
        self.md_bg_color = GOLD if active else (0.2, 0.2, 0.2, 1)
        self._lbl.text_color = (0, 0, 0, 1) if active else (0.9, 0.9, 0.9, 1)


class _SortHeader(ButtonBehavior, MDLabel):
    """A tappable results-table column header (sorts on release)."""


class _OptionRow(ButtonBehavior, MDBoxLayout):
    """A tappable answer option. Built on MDBoxLayout (whose
    BackgroundColorBehavior repaints md_bg_color immediately) rather than
    MDFlatButton (only updates its background on the *second* state
    change) or MDCard (already mixes in ButtonBehavior -> MRO clash).
    """

    def __init__(self, key, text, **kw):
        super().__init__(**kw)
        self._key = key
        self.orientation = "vertical"
        self.size_hint_y = None
        self.adaptive_height = True
        self.padding = (dp(12), dp(10))
        self.spacing = 0
        self.radius = [dp(8)]
        self.md_bg_color = (0, 0, 0, 0)
        self._lbl = MDLabel(
            text=text,
            theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
            size_hint_y=None,
        )
        self._lbl.bind(
            width=lambda i, w: setattr(i, "text_size", (w, None)),
            texture_size=lambda i, ts: setattr(i, "height", ts[1]),
        )
        self.add_widget(self._lbl)

    def set_selected(self, selected):
        self.md_bg_color = GOLD if selected else (0, 0, 0, 0)
        self._lbl.text_color = (0, 0, 0, 1) if selected else (1, 1, 1, 1)

    def lock(self, kind):
        """Show a non-interactive, already-answered option.
        kind: 'correct' | 'wrong' | 'plain'."""
        if kind == "correct":
            self.md_bg_color = (0.18, 0.40, 0.20, 1)
            self._lbl.text_color = (1, 1, 1, 1)
        elif kind == "wrong":
            self.md_bg_color = (0.45, 0.17, 0.17, 1)
            self._lbl.text_color = (1, 1, 1, 1)
        else:
            self.md_bg_color = (0, 0, 0, 0)
            self._lbl.text_color = (0.55, 0.55, 0.55, 1)


class QuizScreen(MDScreen):
    """Google-authenticated quiz. Students take posted problems and see
    their score; whitelisted admins can also post problems and read
    everyone's results. Auth is Google OAuth2 (services/google_auth.py),
    storage is a Google Apps Script backend (services/quiz_api.py)."""

    signed_in = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._auth = None
        self._api = None
        self._problems = []
        self._my_results = []
        self._answers = {}
        self._pending_ids = []
        self._busy = False
        self._q_timers = []          # live Clock events, one per pending card
        self._expired = set()        # pids whose 15s window has closed
        self._submitting = False
        # Content area: "plain" is a single scroll (sign-in / student);
        # "admin" is a MANAGE / RESULTS carousel.
        self._layout_mode = None
        self._body = None            # box the quiz renders into (both modes)
        self._carousel = None
        self._tab_buttons = []
        self._results_box = None
        self._results_loaded = False
        self._results_rows = []
        self._table_holder = None
        self._sort_key = "name"      # "name" | "email" | "percent"
        self._sort_desc = False

    @property
    def app(self):
        return MDApp.get_running_app()

    def switch_screen(self, screen_name: str) -> None:
        if hasattr(self.app, "root") and self.app.root:
            if hasattr(self.app.root, "current"):
                self.app.root.current = screen_name

    # ------------------------------------------------------------------
    def on_pre_enter(self):
        if self._auth is None:
            self._auth = GoogleAuth()
            self._api = QuizAPI(self._auth)
        self._refresh_account()
        if self._auth.is_signed_in:
            self._load_problems()
        else:
            self._render_signin()

    def _refresh_account(self):
        self.signed_in = self._auth.is_signed_in
        if self.signed_in:
            role = "Admin" if self._auth.is_admin else "Student"
            self.ids.account_label.text = f"{self._auth.name}  ·  {role}"

    def _set_status(self, text):
        self.ids.status.text = text or ""

    # ---------------------------- sign in ----------------------------
    def _render_signin(self):
        self._set_plain_layout()
        body = self._body
        body.clear_widgets()
        self._set_status("")
        if not quiz_config.is_configured():
            body.add_widget(
                _label(
                    "The quiz isn't set up on this build yet.\n"
                    "See SETUP_QUIZ.md for the one-time Google + backend setup.",
                    text_color=(0.8, 0.6, 0.3, 1),
                )
            )
            return
        body.add_widget(
            _label(
                "Sign in with your LNMIIT Google account (@lnmiit.ac.in) "
                "to take the quiz."
            )
        )
        btn = MDRaisedButton(
            text="SIGN IN WITH GOOGLE",
            md_bg_color=GOLD,
            text_color=(0, 0, 0, 1),
            pos_hint={"center_x": 0.5},
        )
        btn.bind(on_release=lambda *a: self._do_sign_in())
        body.add_widget(btn)

    def _do_sign_in(self):
        if self._busy:
            return
        self._busy = True
        self._set_status("Opening Google sign-in… approve it, then you'll come back here.")
        self._auth.sign_in(self._on_signed_in)

    def _on_signed_in(self, ok, error):
        self._busy = False
        self._refresh_account()
        if not ok:
            self._render_signin()
            self._set_status(error or "Sign-in failed")
            return
        self._set_status("")
        self._load_problems()

    def sign_out(self):
        self._auth.sign_out()
        self._cancel_q_timers()
        self._answers = {}
        self._problems = []
        self._my_results = []
        self._pending_ids = []
        self._expired = set()
        self._submitting = False
        self._refresh_account()
        self._render_signin()

    # ---------------------------- quiz ----------------------------
    def _load_problems(self):
        self._set_status("Loading…")
        self._cancel_q_timers()
        self._expired = set()
        if self._layout_mode is None:
            self._set_plain_layout()
        self._body.clear_widgets()
        self._problems = []
        self._my_results = []
        self._answers = {}
        self._api.list_problems(self._on_problems)

    def _on_problems(self, data, error):
        if error:
            self._set_status(error)
            return
        self._problems = data or []
        # Also pull everything this user has already answered, so the
        # screen can show a running record + cumulative score.
        self._api.my_results(self._on_my_results)

    def _on_my_results(self, data, error):
        if error:
            # A results hiccup shouldn't block taking the quiz.
            print(f"[QuizScreen] my_results failed: {error}")
        self._my_results = data or []
        self._render_quiz()

    def _answered_map(self):
        """problemId -> {selected, correct, isCorrect} for everything this
        user has already answered."""
        out = {}
        for sub in self._my_results:
            for a in sub.get("answers", []):
                out[str(a.get("problemId"))] = a
        return out

    def _render_quiz(self):
        if self._auth.is_admin:
            self._set_admin_layout()
        else:
            self._set_plain_layout()

        self._cancel_q_timers()
        self._expired = set()
        self._submitting = False

        body = self._body
        body.clear_widgets()
        self._set_status("")

        if self._auth.is_admin:
            body.add_widget(self._post_problem_button())
            if self._carousel is not None and self._carousel.index == 1:
                self._ensure_results_loaded()

        if not self._problems:
            body.add_widget(_label("No questions yet.", halign="center"))
            return

        answered = self._answered_map()
        self._pending_ids = []
        for idx, problem in enumerate(self._problems, 1):
            pid = str(problem.get("id"))
            state = answered.get(pid)
            card = self._question_card(idx, problem, state)
            body.add_widget(card)
            if state is None:
                self._pending_ids.append(pid)
                self._start_q_timer(pid, card)

        if self._pending_ids:
            submit = MDRaisedButton(
                text="SUBMIT ANSWERS",
                md_bg_color=GOLD,
                text_color=(0, 0, 0, 1),
                pos_hint={"center_x": 0.5},
            )
            submit.bind(on_release=lambda *a: self._submit())
            body.add_widget(submit)

    def _question_card(self, number, problem, state=None):
        """state None -> interactive; else a dict from a past answer,
        rendered locked (options coloured, no taps)."""
        card = MDCard(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(6),
            size_hint_y=None,
            adaptive_height=True,
            md_bg_color=(0.12, 0.12, 0.12, 1),
            radius=[dp(12)],
        )
        card.add_widget(
            _label(
                f"{number}. {problem.get('question', '')}",
                text_color=(1, 1, 1, 1),
                bold=True,
            )
        )
        pid = str(problem.get("id"))
        card._pid = pid
        card._timer_label = None
        if state is None:
            card._timer_label = _label(
                self._timer_text(ANSWER_SECONDS),
                text_color=GOLD,
                bold=True,
                font_style="Caption",
                halign="right",
            )
            card.add_widget(card._timer_label)
        options = problem.get("options", {}) or {}
        card._option_buttons = []
        for key in ("A", "B", "C", "D"):
            if key not in options:
                continue
            row = _OptionRow(key, f"{key}.  {options[key]}")
            if state is None:
                row.bind(
                    on_release=lambda r, card=card, pid=pid: self._choose(pid, r, card)
                )
            else:
                sel, cor = state.get("selected"), state.get("correct")
                row.lock("correct" if key == cor else "wrong" if key == sel else "plain")
            card._option_buttons.append(row)
            card.add_widget(row)

        if state is not None:
            ok = state.get("isCorrect")
            tail = (
                "correct"
                if ok
                else f"wrong — answer was {state.get('correct')}"
            )
            card.add_widget(
                _sym_label(
                    f"{MARK_OK if ok else MARK_NO}  You answered "
                    f"{state.get('selected')} — {tail}",
                    color=(0.5, 0.85, 0.5, 1) if ok else (0.9, 0.45, 0.45, 1),
                )
            )
        return card

    def _choose(self, pid, chosen_row, card):
        if pid in self._expired:
            return
        self._answers[pid] = chosen_row._key
        for row in card._option_buttons:
            row.set_selected(row._key == chosen_row._key)

    # ---------------------- per-question timer ----------------------
    def _timer_text(self, seconds):
        return f"{max(seconds, 0)}s to answer"

    def _start_q_timer(self, pid, card):
        card._seconds_left = ANSWER_SECONDS
        ev = Clock.schedule_interval(
            lambda dt, p=pid, c=card: self._tick_q_timer(p, c), 1
        )
        self._q_timers.append(ev)

    def _tick_q_timer(self, pid, card):
        if pid in self._expired or self._submitting:
            return False
        card._seconds_left -= 1
        left = card._seconds_left
        if card._timer_label is not None:
            card._timer_label.text = self._timer_text(left)
            card._timer_label.text_color = (
                (0.9, 0.35, 0.35, 1) if left <= 5 else GOLD
            )
        if left <= 0:
            self._expire_question(pid, card)
            return False
        return True

    def _expire_question(self, pid, card):
        if pid in self._expired:
            return
        self._expired.add(pid)
        for row in card._option_buttons:
            row.disabled = True
        if pid not in self._answers:
            self._answers[pid] = "-"      # no-answer -> scored wrong
        if card._timer_label is not None:
            card._timer_label.text = "Time's up"
            card._timer_label.text_color = (0.9, 0.35, 0.35, 1)
        # Once every pending question's window has closed, send them all.
        if not self._submitting and set(self._pending_ids) <= self._expired:
            self._submit()

    def _cancel_q_timers(self):
        for ev in self._q_timers:
            ev.cancel()
        self._q_timers = []

    def _submit(self):
        if self._submitting:
            return
        # A question is "resolved" once it's answered or its window closed.
        unresolved = [
            p for p in self._pending_ids
            if p not in self._answers and p not in self._expired
        ]
        if unresolved:
            self._set_status(
                f"{len(unresolved)} question(s) still open — answer them "
                f"or let the timer run out."
            )
            return
        self._submitting = True
        self._cancel_q_timers()
        # Anything still unanswered here timed out -> send "-" (wrong).
        payload = {
            pid: self._answers.get(pid, "-") for pid in self._pending_ids
        }
        self._set_status("Submitting…")
        self._api.submit_answers(payload, self._on_submitted)

    def _on_submitted(self, data, error):
        self._submitting = False
        if error:
            self._set_status(error)
            return
        overall = (data or {}).get("overall") or {}
        toast(
            f"Recorded. Your total: {overall.get('correct', 0)}"
            f"/{overall.get('answered', 0)}"
        )
        self._load_problems()

    # ---------------------------- admin ----------------------------
    def _post_problem_button(self):
        """A single gold '+' aligned to the right of the MANAGE tab."""
        bar = AnchorLayout(
            anchor_x="right", size_hint_y=None, height=dp(48)
        )
        add = MDIconButton(
            icon="plus",
            theme_text_color="Custom",
            text_color=GOLD,
        )
        add.bind(
            on_release=lambda *a: PostProblemDialog(
                self._api, on_saved=self._load_problems
            ).open()
        )
        bar.add_widget(add)
        return bar

    # ------------------------- content layout -------------------------
    def _set_plain_layout(self):
        """Single scrolling column -- sign-in and student views."""
        if self._layout_mode == "plain":
            return
        self.ids.content_root.clear_widgets()
        self._carousel = None
        self._tab_buttons = []
        self._results_box = None
        self._results_loaded = False
        scroll, self._body = _scroll_body()
        self.ids.content_root.add_widget(scroll)
        self._layout_mode = "plain"

    def _set_admin_layout(self):
        """MANAGE / RESULTS carousel with a tab header on top."""
        if self._layout_mode == "admin":
            return
        self.ids.content_root.clear_widgets()

        tabs = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(2),
            md_bg_color=(0.08, 0.08, 0.08, 1),
        )
        self._tab_buttons = []
        for i, label in enumerate(("MANAGE", "RESULTS")):
            btn = _TabButton(label)
            btn.set_active(i == 0)
            btn.bind(on_release=lambda b, idx=i: self._show_tab(idx))
            self._tab_buttons.append(btn)
            tabs.add_widget(btn)

        carousel = Carousel(direction="right", ignore_perpendicular_swipes=True)
        manage_scroll, self._body = _scroll_body()
        results_scroll, self._results_box = _scroll_body()
        carousel.add_widget(manage_scroll)
        carousel.add_widget(results_scroll)
        carousel.bind(index=self._on_carousel_index)
        self._carousel = carousel
        self._results_loaded = False

        self.ids.content_root.add_widget(tabs)
        self.ids.content_root.add_widget(carousel)
        self._layout_mode = "admin"

    def _show_tab(self, idx):
        if self._carousel is None:
            return
        if self._carousel.index != idx:
            self._carousel.load_slide(self._carousel.slides[idx])
        self._on_carousel_index(self._carousel, idx)

    def _on_carousel_index(self, carousel, idx):
        for i, btn in enumerate(self._tab_buttons):
            btn.set_active(i == idx)
        if idx == 1:
            self._ensure_results_loaded()

    # ---------------------------- results ----------------------------
    _RESULT_COLS = (
        ("Name", 0.36),
        ("Email", 0.40),
        ("Score", 0.14),
        ("%", 0.10),
    )
    _SORT_KEYS = {"Name": "name", "Email": "email", "%": "percent"}

    def _ensure_results_loaded(self):
        if self._results_loaded:
            return
        self._results_loaded = True
        self._load_results()

    def _load_results(self):
        if self._results_box is None:
            return
        self._results_box.clear_widgets()
        self._results_box.add_widget(_label("Loading results…", halign="center"))
        self._api.scoreboard(self._on_results)

    def _on_results(self, data, error):
        box = self._results_box
        if box is None:
            return
        box.clear_widgets()

        header = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8)
        )
        header.add_widget(
            _label("Final score per student", text_color=GOLD, bold=True)
        )
        refresh = MDIconButton(
            icon="refresh",
            theme_text_color="Custom",
            text_color=GOLD,
            pos_hint={"center_y": 0.5},
        )
        refresh.bind(on_release=lambda *a: self._load_results())
        header.add_widget(refresh)
        box.add_widget(header)

        if error:
            box.add_widget(_label(error, text_color=(0.9, 0.45, 0.45, 1)))
            return
        self._results_rows = data or []
        if not self._results_rows:
            box.add_widget(_label("No submissions yet.", halign="center"))
            return
        self._table_holder = MDBoxLayout(
            orientation="vertical", size_hint_y=None, adaptive_height=True
        )
        box.add_widget(self._table_holder)
        self._render_results_table()

    def _sort_by(self, key):
        if self._sort_key == key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_key = key
            # text columns read best A->Z, percentage best high->low
            self._sort_desc = key == "percent"
        self._render_results_table()

    def _render_results_table(self):
        holder = self._table_holder
        if holder is None:
            return
        holder.clear_widgets()

        rows = list(self._results_rows or [])
        key = self._sort_key
        if key == "percent":
            rows.sort(key=lambda r: r.get("percent", 0), reverse=self._sort_desc)
        else:
            rows.sort(
                key=lambda r: (r.get(key) or r.get("email") or "").lower(),
                reverse=self._sort_desc,
            )

        holder.add_widget(self._header_row())
        holder.add_widget(self._table_divider())
        for r in rows:
            holder.add_widget(
                self._table_row(
                    [
                        r.get("name") or r.get("email") or "—",
                        r.get("email", ""),
                        f"{r.get('correct', 0)}/{r.get('answered', 0)}",
                        f"{r.get('percent', 0)}%",
                    ]
                )
            )
            holder.add_widget(self._table_divider())

    def _header_row(self):
        row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            adaptive_height=True,
            padding=(0, dp(6)),
            spacing=dp(4),
        )
        for name, weight in self._RESULT_COLS:
            key = self._SORT_KEYS.get(name)
            text = name
            if key and self._sort_key == key:
                # DejaVu (QuizSym) font -- Roboto renders these as tofu
                text += "  " + (MARK_DOWN if self._sort_desc else MARK_UP)
            cell = _SortHeader(
                text=text,
                size_hint_x=weight,
                size_hint_y=None,
                theme_text_color="Custom",
                text_color=GOLD,
                bold=True,
                font_style="Caption",
            )
            # set AFTER font_style, which otherwise resets font_name from
            # the theme; QuizSym (DejaVu) has the ▲/▼ marks, Roboto doesn't
            cell.font_name = _SYM_FONT
            cell.bind(
                width=lambda i, w: setattr(i, "text_size", (w, None)),
                texture_size=lambda i, ts: setattr(i, "height", ts[1]),
            )
            if key:
                cell.bind(on_release=lambda c, k=key: self._sort_by(k))
            row.add_widget(cell)
        return row

    def _table_row(self, values):
        row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            adaptive_height=True,
            padding=(0, dp(6)),
            spacing=dp(4),
        )
        for (name, weight), val in zip(self._RESULT_COLS, values):
            cell = MDLabel(
                text=str(val),
                size_hint_x=weight,
                size_hint_y=None,
                theme_text_color="Custom",
                text_color=(0.9, 0.9, 0.9, 1),
                font_style="Caption",
                shorten=name in ("Name", "Email"),
                shorten_from="right",
            )
            cell.bind(
                width=lambda i, w: setattr(i, "text_size", (w, None)),
                texture_size=lambda i, ts: setattr(i, "height", ts[1]),
            )
            row.add_widget(cell)
        return row

    def _table_divider(self):
        return MDBoxLayout(
            size_hint_y=None, height=dp(1), md_bg_color=(0.2, 0.2, 0.2, 1)
        )
