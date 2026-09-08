"""Client for the Quiz backend (Google Apps Script web app).

Every call POSTs JSON {"idToken": ..., "action": ..., "payload": ...} to
quiz_config.BACKEND_URL and expects {"ok": bool, "data"|"error": ...}.
Network runs on a worker thread; callbacks come back on the Kivy thread.
"""

import json
import threading

from kivy.clock import Clock

try:
    import requests
except ImportError:
    requests = None

import quiz_config


class QuizAPI:
    def __init__(self, auth):
        self.auth = auth

    # -- internals --------------------------------------------------------
    def _call(self, action, payload, on_done):
        """on_done(data, error) on the main thread."""
        if requests is None:
            Clock.schedule_once(
                lambda dt: on_done(None, "'requests' library unavailable")
            )
            return
        if not quiz_config.is_configured():
            Clock.schedule_once(
                lambda dt: on_done(None, "Quiz backend not configured (see SETUP_QUIZ.md)")
            )
            return

        def _after_token(token, error):
            if error:
                on_done(None, error)
                return
            threading.Thread(
                target=self._request_worker,
                args=(token, action, payload, on_done),
                daemon=True,
            ).start()

        self.auth.get_valid_id_token(_after_token)

    def _request_worker(self, token, action, payload, on_done):
        try:
            resp = requests.post(
                quiz_config.BACKEND_URL,
                data=json.dumps(
                    {"idToken": token, "action": action, "payload": payload or {}}
                ),
                headers={"Content-Type": "application/json"},
                timeout=45,
            )
            if resp.status_code != 200:
                Clock.schedule_once(
                    lambda dt: on_done(None, f"Server error {resp.status_code}")
                )
                return
            body = resp.json()
            if not body.get("ok"):
                err = body.get("error", "Request failed")
                Clock.schedule_once(lambda dt, e=err: on_done(None, e))
                return
            data = body.get("data")
            Clock.schedule_once(lambda dt: on_done(data, None))
        except Exception as e:  # noqa: BLE001
            Clock.schedule_once(lambda dt, err=e: on_done(None, str(err)))

    # -- student ------------------------------------------------------
    def list_problems(self, on_done):
        """-> list of {id, question, options:{A..D}} (no correct answer)."""
        self._call("list_problems", {}, on_done)

    def submit_answers(self, answers, on_done):
        """answers: {problem_id: "A".."D"}. -> {score, total, breakdown}."""
        self._call("submit_answers", {"answers": answers}, on_done)

    def my_results(self, on_done):
        self._call("my_results", {}, on_done)

    def get_config(self, on_done):
        """-> {quizSecondsPerQuestion, quizTotalSeconds}; 0 == unset.
        Any signed-in user. Older backends without this action just
        return an 'Unknown action' error -- callers fall back to a
        local default."""
        self._call("get_config", {}, on_done)

    # -- admin ------------------------------------------------------
    def create_problem(self, question, options, correct, on_done):
        """options: {"A":..,"B":..,"C":..,"D":..}; correct: "A".."D"."""
        self._call(
            "create_problem",
            {"question": question, "options": options, "correct": correct},
            on_done,
        )

    def delete_problem(self, problem_id, on_done):
        self._call("delete_problem", {"id": problem_id}, on_done)

    def set_config(self, seconds_per_question, total_seconds, on_done):
        """Admin only. Values are clamped server-side to max(0, floor(n));
        0 means 'unset'. -> the stored {quizSecondsPerQuestion,
        quizTotalSeconds}."""
        self._call(
            "set_config",
            {
                "quizSecondsPerQuestion": seconds_per_question,
                "quizTotalSeconds": total_seconds,
            },
            on_done,
        )

    def list_results(self, on_done):
        """-> list of submission dicts across all students (admin only)."""
        self._call("list_results", {}, on_done)

    def scoreboard(self, on_done):
        """-> [{email, name, answered, correct, percent, lastUpdated}]
        one row per student, best first (admin only)."""
        self._call("scoreboard", {}, on_done)
