#!/usr/bin/env python3
"""Headless test of the family timeline page (ui/pages/1_Family_timeline.py) with Streamlit's AppTest: the demo story
added step by step, viewers in three time zones, read state, a typed update without a model. Needs the packages in
requirements-ui.txt:
  python ui/test_timeline_page.py
"""
from __future__ import annotations

import html
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from pathlib import Path
from zoneinfo import ZoneInfo

from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.util import patch_config_options

PAGE = str(Path(__file__).resolve().parent / "pages" / "1_Family_timeline.py")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from episode import llm_extractor, photo_reader  # noqa: E402
from episode_qa import episode_answerer  # noqa: E402
from timeline_html import PRODUCT  # noqa: E402

# Most tests step through the demo story by count, so they replay it without the two-different-answers pair (u07b,
# u07c); TestTwoAnswersOnThePage replays the whole story. The page reads its story from CARERELAY_STORY.
FULL_STORY = Path(__file__).resolve().parents[1] / "care_cases" / "episode_hip_fracture.json"
_story = json.loads(FULL_STORY.read_text())
_story["updates"] = [u for u in _story["updates"] if u["update_id"] not in ("u07b", "u07c")]
SHORT_STORY = Path(tempfile.mkdtemp()) / "episode_without_two_answers.json"
SHORT_STORY.write_text(json.dumps(_story))
os.environ["CARERELAY_STORY"] = str(SHORT_STORY)


def setUpModule() -> None:
    # Saved timelines go to a throwaway store, never the page's default ~/.kindredrelay on the developer's machine.
    state = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    unittest.addModuleCleanup(state.cleanup)
    environment = patch.dict(os.environ, {"CARERELAY_STATE_DIR": state.name})
    environment.start()
    unittest.addModuleCleanup(environment.stop)


def adopt_session(new: AppTest, old: AppTest) -> AppTest:
    """Make `new` run in `old`'s session on Streamlit 1.58 and 1.64 alike. 1.58's AppTest runs whatever object
    AppTest.session_state holds, so assigning it hands the session over. 1.64 wraps the session it runs
    (AppTest._session_state) in a tester view: assigning session_state alone swaps the view, and the fresh AppTest
    then runs in an empty session of its own while the test reads the old one."""
    new.session_state = old.session_state
    if hasattr(old, "_session_state"):   # Streamlit >= 1.64: the state the script runner is given
        new._session_state = old._session_state
    return new


def state_get(at: AppTest, key: str, default=None):
    """at.session_state.filtered_state.get(key, default) without filtered_state, which 1.64's tester view lacks."""
    return at.session_state[key] if key in at.session_state else default


def fresh() -> AppTest:
    for k in ("CARERELAY_LLM_BASE_URL", "CARERELAY_LLM_MODEL"):   # no live model: replay only
        os.environ.pop(k, None)
    at = AppTest.from_file(PAGE, default_timeout=30).run()
    assert not at.exception, at.exception
    return at


def reload_view(at: AppTest) -> AppTest:
    """Explicit fresh-view coverage after a committed submit.

    Streamlit 1.58 AppTest can merge deltas from before/after st.rerun and retain
    removed widgets. Use public AppTest state handoff to check a reload of the
    same backend episode, without patching its parser or suppressing assertions.
    This does not validate that framework's in-place transition rendering.
    """
    episode = at.session_state["episode"]
    new = adopt_session(AppTest.from_file(PAGE, default_timeout=30), at)
    new.query_params.update(at.query_params)
    new.run()
    assert not new.exception, new.exception
    assert new.session_state["episode"] is episode
    return new


def add_story(at: AppTest, n: int) -> None:
    for _ in range(n):
        next(b for b in at.button if b.label == "Add this update").click().run()
        assert not at.exception, at.exception


def texts(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown]


def page(at: AppTest) -> str:
    return "\n".join(texts(at))


def heads(at: AppTest) -> list[str]:
    """The headline of every timeline entry, newest first."""
    return [html.unescape(h) for h in re.findall(r'data-headline="([^"]*)"', page(at))]


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def open_panel(at: AppTest, which: str, speaker: str = "Ward nurse") -> None:
    """Open a tile; existing medical-recording cases explicitly choose the care team."""
    if which == "recording":
        at.session_state["rec_speaker_type"] = "Doctor / nurse"
        at.session_state["rec_speaker"] = speaker
    at.button(key=f"add_{which}").click().run()
    assert not at.exception, at.exception


def ticks(at: AppTest) -> list:
    """The boxes to tick for each checked line (not the consent box, not "said earlier")."""
    return [c for c in at.checkbox if not (c.key or "").endswith("_earlier")
            and not (c.key or "").startswith(("rec_consent_", "rec_family_consent_", "correction_checked_"))]


def open_photo(at: AppTest) -> None:
    """Share news from the hospital, then choose to photograph a paper."""
    open_panel(at, "recording")
    at.radio(key="hosp_how").set_value("📷 Photograph a paper").run()
    assert not at.exception, at.exception


def note(at: AppTest, text: str) -> None:
    open_panel(at, "paper")
    at.text_area(key="note_text").set_value(text).run()
    button(at, "Share with the family").click().run()
    assert not at.exception, at.exception


@contextmanager
def observe_working_hints():
    """Observe real outbound UI messages without changing AppTest's parser."""
    from streamlit.runtime.scriptrunner_utils.script_run_context import ScriptRunContext
    original = ScriptRunContext.enqueue
    active, shown = {}, []
    def enqueue(context, message):
        if message.HasField("delta") and message.delta.WhichOneof("type") == "new_element":
            element = message.delta.new_element
            path = tuple(message.metadata.delta_path)
            if element.WhichOneof("type") == "markdown" and 'class="cr-working"' in element.markdown.body:
                active[path] = element.markdown.body
                shown.append(element.markdown.body)
            elif path in active:
                active.pop(path)
        return original(context, message)
    with patch.object(ScriptRunContext, "enqueue", enqueue):
        yield active, shown


class TestTimelinePage(unittest.TestCase):
    def test_empty_then_story(self):
        at = fresh()
        self.assertIn("Elena Novak, 82</div>", page(at))
        self.assertIn("Nothing yet", page(at))
        add_story(at, 10)
        self.assertEqual(len(at.session_state["episode"].updates), 10)
        self.assertEqual(len(heads(at)), 19)   # u10 keeps its independent home event and family plan separate
        self.assertEqual(heads(at)[0], "Fracture clinic appointment: Mon 30 Nov 10:30")
        self.assertTrue(any(h.startswith("Mum is home and settled.") for h in heads(at)))
        self.assertEqual([h for h in heads(at) if h.startswith("Mum is home and settled.")],
                         ["Mum is home and settled."])
        self.assertEqual([h for h in heads(at) if h.startswith("Joy will do the morning visits")],
                         ["Joy will do the morning visits from tomorrow, I'll do evenings, David is staying until Thursday. — Event date/time unclear"])
        self.assertEqual(heads(at)[-1], "At St Mary's Hospital, A&E")
        self.assertIn('aria-level="2">Home after hospital</div>', page(at))
        self.assertIn("<b>Warning signs:</b> Come back straight away", page(at))
        self.assertTrue(any(s.value == "The demo story is complete." for s in at.sidebar.success))

    def test_viewer_time_zone_and_read_state(self):
        at = fresh()
        add_story(at, 2)
        at.selectbox[0].set_value("mia").run()
        self.assertFalse(at.exception)
        self.assertIn("Times in Melbourne time", page(at))
        self.assertIn("Tue 20 Oct 19:00", page(at))       # surgery 09:00 London
        self.assertNotIn("Tue 20 Oct 09:00", page(at))
        self.assertEqual(page(at).count('class="cr-new"'), 5)   # two sources contain five important events
        button(at, "Mark 2 new as read").click().run()
        self.assertTrue(button(at, "All read").disabled)
        self.assertNotIn('class="cr-new"', page(at))
        add_story(at, 1)
        self.assertIn("Mark 1 new as read", [b.label for b in at.button])
        self.assertNotIn('role="separator">You last looked here', page(at))   # practical source is archived, not an event
        at.selectbox[0].set_value("david").run()
        self.assertIn("Tue 20 Oct 04:00", page(at))       # Toronto
        self.assertIn("Mark 3 new as read", [b.label for b in at.button])
        self.assertNotIn("You last looked here", page(at))   # David never marked it read

    def test_three_big_buttons(self):
        at = fresh()
        tiles = [b for b in at.button if b.key in ("add_paper", "add_recording", "add_ask")]   # the big one first, like Plus
        self.assertEqual([b.label.split("\n\n")[0] for b in tiles], ["Ask about Elena", "Share news from the hospital", "Share my plans"])
        import asr_local
        voice = not asr_local.missing()   # a laptop with Whisper: the tiles offer talking
        self.assertEqual([b.label.split("\n\n")[1] for b in tiles],
                         ["See the latest, or " + ("talk or type a question." if voice else "type a question.") + " We answer from the updates.",
                          ("Record or type an update" if voice else "Type an update") + " from you or the care team, or photograph a paper.",
                          "When you'll be there, how you can help, how Elena was."])
        self.assertEqual([b.icon for b in tiles], [":material/mic:" if voice else ":material/search:", ":material/medical_services:",
                                                   ":material/event_available:"])
        self.assertIn("What would you like to do for Elena today?", page(at))
        open_panel(at, "paper")
        self.assertIn("Share with the family", [b.label for b in at.button])
        self.assertFalse(any(b.key == "add_recording" for b in at.button))   # one panel at a time
        button(at, "Cancel").click().run()
        self.assertTrue(any(b.key == "add_recording" for b in at.button))

    def test_text_size(self):
        at = fresh()
        css = lambda: next(m.value for m in at.markdown if "--cr-fs" in m.value)  # noqa: E731
        self.assertIn("--cr-fs:1.0}", css())
        at.session_state["text_size"] = "A++"   # as tapping A++ does
        at.run()
        self.assertIn("--cr-fs:1.36}", css())
        self.assertEqual(at.query_params["text"], ["A++"])   # a bookmark keeps it
        at.session_state["text_size"] = None   # the chosen size tapped again: it stays chosen (never no size)
        at.run()
        self.assertIn("--cr-fs:1.36}", css())
        at = AppTest.from_file(PAGE, default_timeout=60)
        at.query_params["text"] = "A+"
        at.run()
        self.assertIn("--cr-fs:1.18}", css())

    def test_note_without_a_model(self):
        at = fresh()
        add_story(at, 1)
        note(at, "The neighbour is feeding the cat.")
        self.assertTrue(any(h.startswith("The neighbour is feeding the cat.") for h in heads(at)))
        self.assertIn("The neighbour is feeding the cat.", page(at))
        self.assertTrue(any(b.key == "add_paper" for b in at.button))   # the panel closed once added
        self.assertEqual(at.session_state["episode"].updates[-1]["text"], "The neighbour is feeding the cat.")
        at = reload_view(at)
        note(at, "The neighbour is feeding the cat.")   # the same text sent twice
        self.assertEqual(sum(u["text"] == "The neighbour is feeding the cat." for u in at.session_state["episode"].updates), 1)

    def test_an_update_is_added_as_the_person_viewing(self):
        at = fresh()
        add_story(at, 1)
        at.selectbox[0].set_value("mia").run()
        note(at, "Called Nan, she sounded tired but cheerful.")
        self.assertEqual(at.session_state["episode"].updates[-1]["author"], "mia")
        self.assertIn('<b style="color:var(--cr-p2,#6D28D9)">Mia</b>: Called Nan', page(at))

    @patch("asr_local.missing", return_value=["openai-whisper"])
    def test_recording_typed_without_speech_to_text(self, _missing):
        at = fresh()
        add_story(at, 1)
        open_panel(at, "recording", speaker="")
        self.assertTrue(any("Speech-to-text is not connected" in i.value for i in at.info))
        add = lambda: at.button(key="rec_add")  # noqa: E731
        at.text_area(key="rec_text").set_value("She can go home on Friday if she walks safely.").run()
        self.assertTrue(add().disabled)   # who is speaking?
        at.text_input(key="rec_speaker").set_value("Ward nurse").run()
        self.assertEqual(at.text_area(key="rec_text").value, "")   # the old, unnamed source is not relabelled
        at.text_area(key="rec_text").set_value("She can go home on Friday if she walks safely.").run()
        self.assertFalse(add().disabled)
        add().click().run()
        self.assertFalse(at.exception)
        self.assertNotIn("Recording added", heads(at))   # no extracted event; the source remains accessible
        self.assertIn("Source documents and messages", page(at))
        self.assertIn("Ward nurse", page(at))
        self.assertIn("She can go home on Friday if she walks safely.", page(at))
        self.assertEqual(len(at.session_state["episode"].updates), 2)
        self.assertIn("No facts were read from it (no model connected).", page(at))

    def test_recording_said_earlier_goes_in_at_that_time(self):
        import datetime as dt
        at = fresh()
        add_story(at, 3)
        open_panel(at, "recording")
        at.text_area(key="rec_text").set_value("Visiting is open all day for her.").run()
        at.text_input(key="rec_speaker").set_value("Ward nurse").run()
        at.checkbox(key="rec_0_earlier").check().run()
        day = dt.datetime.now(ZoneInfo("Europe/London")).date() - dt.timedelta(days=1)
        at.date_input(key="rec_0_day").set_value(day).run()
        at.time_input(key="rec_0_time").set_value(dt.time(12, 0)).run()
        at.button(key="rec_add").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["episode"].updates[-1]["at"],
                         dt.datetime.combine(day, dt.time(12), ZoneInfo("Europe/London")).isoformat())

    def test_info_strip_under_right_now(self):
        at = fresh()
        add_story(at, 3)
        self.assertIn('class="cr-strip"', page(at))
        self.assertIn("Family in the loop", page(at))

    def test_ward_hours_are_labelled_for_remote_viewers(self):
        at = fresh()
        add_story(at, 3)
        at.selectbox[0].set_value("mia").run()
        ward = page(at)[page(at).index('id="cr-ward"'):]
        ward = ward[:ward.index("</section>")]
        self.assertIn("Hospital's local time (London)", ward)
        self.assertIn("weekdays 8:30", ward)
        self.assertIn("11:00 - 13:00 and 17:00 - 20:00", ward)
        self.assertFalse(any("Visiting hours" in h or "Consultant ward round" in h for h in heads(at)))
        self.assertIn("Source documents and messages", page(at))

    def test_family_report_is_flagged_on_the_headline(self):
        at = fresh()
        add_story(at, 1)
        self.assertEqual(heads(at), ["Fell at home and could not stand up", "At St Mary's Hospital, A&E"])
        self.assertIn("A&amp;E <span class=\"cr-badge \">reported by family</span>", page(at))

    def test_restart(self):
        at = fresh()
        add_story(at, 3)
        next(b for b in at.sidebar.button if b.label == "Restart the demo").click().run()
        self.assertIn("Nothing yet", page(at))


def ask(at: AppTest, question: str) -> str:
    open_panel(at, "ask")
    at.text_input(key="qa_text").set_value(question).run()
    button(at, "Find out").click().run()
    assert not at.exception, at.exception
    return next(m.value for m in at.markdown if 'class="cr-chat cr-qa"' in m.value)


class TestAsk(unittest.TestCase):
    def tearDown(self):
        for k in ("CARERELAY_LLM_BASE_URL", "CARERELAY_LLM_MODEL"):
            os.environ.pop(k, None)

    def test_answered_from_the_updates_without_a_model(self):
        at = fresh()
        add_story(at, 8)
        n = len(at.session_state["episode"].updates)
        card = ask(at, "Which medicines did they stop?")
        self.assertIn('<div class="cr-bubble-me">Which medicines did they stop?</div><span class="cr-me-who">You asked</span>', card)
        self.assertIn("“STOP taking Ibuprofen.”", card)
        self.assertIn(f"{PRODUCT} picked these sentences by matching your words.", card)
        self.assertEqual(len(at.session_state["episode"].updates), n)   # an answer is never an update

    def test_a_replaced_plan_is_marked_and_a_family_report_is_one(self):
        at = fresh()
        add_story(at, 7)
        at.selectbox[0].set_value("mia").run()
        card = ask(at, "When is she going home?")
        self.assertIn("“Going home is now planned for Saturday morning.”", card)
        self.assertRegex(card, r"could go home on Friday\.”.*earlier; replaced by a later update")
        self.assertNotIn("Fri 23 Oct 02:20", card)   # source receipt time is never an event timestamp

    def test_answered_by_the_model_and_checked(self):
        at = fresh()
        add_story(at, 7)
        os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")   # never called
        at.session_state["answerer"] = episode_answerer(StubModel({"covered": "partly", "citations": ["u07.2", "u05.4"]}))
        at.run()
        card = ask(at, "When is she going home?")
        self.assertIn("Here&#x27;s what the updates say. Some of it was said earlier and has since changed, as marked.", card)
        self.assertIn(f"The model picked these sentences from the updates, and {PRODUCT} double-checked them.", card)

    def test_a_model_answer_that_fails_the_checks_is_not_shown(self):
        at = fresh()
        add_story(at, 7)
        os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")
        at.session_state["answerer"] = episode_answerer(StubModel({
            "answer": "Yes, she can get out of bed on her own now.", "covered": "yes", "citations": ["u99.9"]}))
        at.run()
        card = ask(at, "Can she get out of bed on her own?")
        self.assertNotIn("Yes, she can", card)   # a model's words are never shown
        self.assertIn("Only the care team can decide what Elena may do.", card)
        self.assertIn("(the model's pick did not pass the checks)", card)


class TestQuestionsForTheDoctor(unittest.TestCase):
    def test_a_question_the_updates_do_not_answer_goes_on_the_list_once(self):
        at = fresh()
        add_story(at, 10)
        at.selectbox[0].set_value("mia").run()
        card = ask(at, "Will she need a wheelchair?")
        self.assertIn("The updates don&#x27;t mention this yet.", card)
        self.assertIn("You can save it for the doctor below", card)
        button(at, "💬 Save it for the doctor").click().run()
        self.assertFalse(at.exception)
        side = page(at)
        self.assertIn("Questions for the doctor", side)
        self.assertIn('<div class="cr-qtext">Will she need a wheelchair?</div>', side)
        self.assertIn('asked by <b style="color:var(--cr-p2,#6D28D9)">Mia</b>', side)
        self.assertIn("✓ Saved for the doctor.", [c.value for c in at.caption])
        at.selectbox[0].set_value("david").run()
        ask(at, "will she need a wheelchair")
        button(at, "💬 Save it for the doctor").click().run()
        self.assertEqual([t.value for t in at.toast], ["That question is already saved for the doctor; your name was added."])
        self.assertEqual(len(at.session_state["episode"].questions), 1)
        self.assertIn('asked by <b style="color:var(--cr-p2,#6D28D9)">Mia</b>, <b style="color:var(--cr-p1,#9A3412)">David</b>', page(at))

    def test_a_later_update_may_answer_it_and_the_family_marks_it(self):
        at = fresh()
        add_story(at, 6)
        ask(at, "Will she get injections at home?")
        button(at, "💬 Save it for the doctor").click().run()
        add_story(at, 4)   # the medication list arrives
        self.assertIn("Maybe answered: “Enoxaparin 40 mg injection once a day for 28 days", page(at))
        button(at, "✓ That answers it").click().run()   # the family confirms the hint
        q = at.session_state["episode"].questions[0]
        self.assertEqual((q["status"], q["answered_by"], q["marked_by"]), ("answered", "u08", "anna"))
        self.assertTrue(any(e.label == "Answered (1)" for e in at.expander))
        self.assertIn('marked answered by <b style="color:var(--cr-p0,#0F766E)">Anna</b>', page(at))
        button(at, "Reopen").click().run()
        self.assertEqual((q["status"], q["answered_by"]), ("open", None))
        button(at, "✓ Answered").click().run()   # answered at the visit: no update is named
        self.assertEqual((q["status"], q["answered_by"], q["marked_by"]), ("answered", None, "anna"))
        self.assertEqual([t.value for t in at.toast], ["Marked answered. You can reopen it under Answered."])

    def test_saving_again_and_for_someone_else(self):
        at = fresh()
        add_story(at, 10)
        at.selectbox[0].set_value("mia").run()
        ask(at, "Will she need a wheelchair?")
        at.selectbox[0].set_value("david").run()   # David sees Mia's answer and saves it
        open_panel(at, "ask")
        button(at, "💬 Save it for the doctor").click().run()
        self.assertEqual(at.session_state["episode"].questions[0]["askers"], ["mia", "david"])
        self.assertEqual([t.value for t in at.toast], ["Saved for the doctor, for Mia and you."])   # his press saved it
        at.text_input(key="qa_text").set_value("Will she need a wheelchair?").run()   # the panel is still open
        button(at, "Find out").click().run()
        next(b for b in at.button if b.label == "💬 Save it for the doctor").click().run()
        self.assertEqual([t.value for t in at.toast], ["You already saved this question for the doctor."])
        self.assertEqual(len(at.session_state["episode"].questions), 1)

    def test_the_recording_panel_lists_the_questions_to_ask(self):
        at = fresh()
        add_story(at, 6)
        ask(at, "Will she need a wheelchair?")
        button(at, "💬 Save it for the doctor").click().run()
        button(at, "🎙️ Record the doctor's answers").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any(m.value.startswith("**Questions to ask**") and "Will she need a wheelchair?" in m.value for m in at.markdown))
        self.assertTrue(any(b.key == "rec_add" for b in at.button))
        self.assertFalse(any(b.key == "q_record" for b in at.button))   # pressing it again would throw the recording away

    def test_recording_the_answers_keeps_a_note_being_written(self):
        at = fresh()
        add_story(at, 6)
        ask(at, "Will she need a wheelchair?")
        button(at, "💬 Save it for the doctor").click().run()
        button(at, "Close").click().run()
        open_panel(at, "paper")   # in a browser, words typed in the note box are not sent until Share with the family: it must not matter
        button(at, "🎙️ Record the doctor's answers").click().run()
        self.assertEqual(at.session_state["adding"], "paper")
        self.assertEqual([t.value for t in at.toast], ["Finish or cancel what you are adding first, then record the doctor's answers."])

    def test_a_leaflet_comes_with_the_answer(self):
        at = fresh()
        add_story(at, 10)
        card = ask(at, "How do I give the injection?")
        self.assertIn("📄 A helpful leaflet: Blood-thinning injections at home", card)
        self.assertIn("General information, not about Elena in particular.", card)
        self.assertIn("“Enoxaparin 40 mg injection once a day for 28 days (to prevent blood clots).”", card)

    def test_a_said_question_fills_the_box_to_be_checked(self):
        at = fresh()
        add_story(at, 7)
        open_panel(at, "ask")
        at.session_state["qa_heard"] = {"rec-1": "When is she going home?", "_new": "rec-1"}   # what Whisper wrote out
        at.run()
        self.assertEqual(at.text_input(key="qa_text").value, "When is she going home?")
        self.assertIn("Check the words below, then press Find out.", [c.value for c in at.caption])
        at.session_state["qa_heard"] = {"rec-1": "When is she going home?", "rec-2": ""}   # silence: nothing goes in the box
        at.run()
        self.assertEqual(at.text_input(key="qa_text").value, "When is she going home?")
        button(at, "Find out").click().run()
        self.assertIn("“Going home is now planned for Saturday morning.”", next(m.value for m in at.markdown if 'class="cr-chat cr-qa"' in m.value))


class StubModel:
    def __init__(self, reply):
        self.reply = reply

    def chat(self, messages, json_schema=None, schema_name="reply"):
        return {"text": "...", "json": self.reply, "latency_s": 0.1, "json_mode": "prompted_json", "finish_reason": "stop"}


class TestLiveModelPath(unittest.TestCase):
    def tearDown(self):
        for k in ("CARERELAY_LLM_BASE_URL", "CARERELAY_LLM_MODEL"):
            os.environ.pop(k, None)

    def typed(self, reply) -> AppTest:
        at = fresh()
        add_story(at, 1)
        os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")   # never called
        at.session_state["extractor"] = llm_extractor(StubModel(reply))
        at.run()
        open_panel(at, "recording")
        at.text_input(key="rec_speaker").set_value("Ward nurse").run()
        at.text_area(key="rec_text").set_value("Keep her nil by mouth from midnight tonight please.").run()
        at.button(key="rec_add").click().run()
        self.assertFalse(at.exception)
        return at

    def test_model_instruction_reaches_sources_without_becoming_an_important_event(self):
        at = self.typed({"facts": [{"type": "instruction", "what": "Nil by mouth from midnight",
                                    "quote": "Keep her nil by mouth from midnight"}]})
        self.assertEqual([t.value for t in at.toast], ["Timeline updated: Nil by mouth from midnight"])
        self.assertNotIn("Nil by mouth from midnight", heads(at))
        self.assertIn("Keep her nil by mouth from midnight tonight please.", page(at))
        self.assertEqual(at.session_state["episode"].entries[-1]["facts"][0]["type"], "instruction")

    def test_unreadable_reply_is_said(self):
        at = self.typed(None)
        self.assertEqual([t.value for t in at.toast], ["The model's reply could not be read, so the update was added without facts."])


class VisionStub:
    model = "vision-stub"

    def __init__(self, text):
        self.text, self.calls = text, 0

    def chat(self, messages, json_schema=None, schema_name="reply"):
        self.calls += 1
        return {"text": self.text, "json": None, "latency_s": 3.0, "json_mode": "text", "finish_reason": "stop"}


class TestPhotos(unittest.TestCase):
    MISREAD = ("DISCHARGE MEDICATIONS\nLansoprazole 1.5 mg once a day.\nSTOP taking Ibuprofen.")   # 15 mg misread

    def tearDown(self):
        for k in ("CARERELAY_LLM_BASE_URL", "CARERELAY_LLM_MODEL"):
            os.environ.pop(k, None)

    def test_demo_story_photo_shows_the_recorded_reading(self):
        at = fresh()
        add_story(at, 7)
        self.assertTrue(any("DISCHARGE MEDICATIONS" in c.value for c in at.sidebar.caption))   # the next update's text
        add_story(at, 1)
        self.assertIn("Text read from the photo: recorded for the demo", page(at))
        self.assertIn("Medication list updated: 0 new, 1 stopped, 0 continued or changed", heads(at))
        self.assertIn('class="cr-thumb" src="data:image/jpeg;base64,', page(at))
        open_photo(at)
        self.assertTrue(any("Reading a photo needs a vision model" in i.value for i in at.info))   # no model here

    def test_photo_read_checked_corrected_and_added(self):
        at = fresh()
        add_story(at, 7)
        os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")   # never called
        vision = VisionStub(self.MISREAD)
        at.session_state["photo_reader"] = photo_reader(vision)
        at.session_state["extractor"] = llm_extractor(StubModel({"facts": [
            {"type": "medication", "name": "Lansoprazole", "dose": "15 mg", "frequency": "once a day", "status": "new",
             "quote": "Lansoprazole 15 mg once a day"},
            {"type": "medication", "name": "Ibuprofen", "status": "stop", "quote": "STOP taking Ibuprofen"}]}))
        at.run()
        open_photo(at)
        self.assertTrue(any("never photograph a real patient" in w.value for w in at.warning))
        next(b for b in at.button if b.label == "Use the sample photo (discharge medication list)").click().run()
        next(b for b in at.button if b.label == "Read the text on the photo").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(vision.calls, 1)
        box = at.text_area(key="photo_text")
        self.assertEqual(box.value, self.MISREAD)
        add = lambda: next(b for b in at.button if b.label == "Add to the timeline")  # noqa: E731
        self.assertTrue(add().disabled)   # nothing ticked, no label yet
        box.set_value(self.MISREAD.replace("1.5 mg", "15 mg")).run()   # the caregiver corrects the misread dose
        self.assertIn("Discard my corrections and read again", [b.label for b in at.button])   # no silent overwrite
        self.assertEqual([c.label for c in ticks(at)], ["Lansoprazole 15 mg once a day.", "STOP taking Ibuprofen."])
        for c in ticks(at):
            c.check()
        at.text_input(key="photo_of_text").set_value("Medication list").run()
        self.assertFalse(add().disabled)
        add().click().run()
        self.assertFalse(at.exception)
        self.assertIn("Medication list updated: 0 new, 1 stopped, 0 continued or changed", heads(at))
        self.assertIn("Anna ticked 2 line(s)", page(at))
        self.assertIn("so shown as reported by family: “Lansoprazole 15 mg once a day.”", page(at))
        self.assertIn("Lansoprazole 15 mg once a day", page(at))
        self.assertEqual(at.session_state["episode"].meds["lansoprazole"]["authority"], "family")
        self.assertEqual([t.value for t in at.toast],
                         ["Timeline updated: Medication list updated: 1 new, 1 stopped, 0 continued or changed (reported by family, not confirmed)"])

        self.assertIsNone(at.session_state["adding"])
        at = reload_view(at)
        self.assertFalse(any(b.label == "Add to the timeline" for b in at.button))   # cleared: no second add after reload

    def live(self, reading: str) -> AppTest:
        at = fresh()
        os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")
        at.session_state["photo_reader"] = photo_reader(VisionStub(reading))
        at.session_state["extractor"] = llm_extractor(StubModel({"facts": []}))
        at.run()
        open_photo(at)
        next(b for b in at.button if b.label == "Use the sample photo (discharge medication list)").click().run()
        next(b for b in at.button if b.label == "Read the text on the photo").click().run()
        return at

    def test_unreadable_word_blocks_add(self):
        at = self.live("DISCHARGE MEDICATIONS\nLansoprazole [unreadable] once a day.")
        for c in ticks(at):
            c.check()
        at.text_input(key="photo_of_text").set_value("Medication list").run()
        self.assertTrue(next(b for b in at.button if b.label == "Add to the timeline").disabled)
        self.assertTrue(any("[unreadable]" in c.value for c in at.caption))

    def completion_box(self, at: AppTest):
        boxes = [block for block in at.get("flex_container")
                 if any(child.type == "markdown" and "Finish and add to timeline" in child.value
                        for child in block.children.values())]
        self.assertEqual(len(boxes), 1, "The required title and Add action need one visible finish block")
        self.assertTrue(boxes[0].proto.flex_container.border)
        return boxes[0]

    def test_completion_box_groups_required_title_and_all_blockers(self):
        reading = "Lansoprazole [unreadable] once a day.\nSTOP taking Ibuprofen."
        at = self.live(reading)
        box = self.completion_box(at)
        title = box.text_input(key="photo_of_text")
        self.assertEqual(title.label, "Document title (required)")
        self.assertEqual(title.proto.label_visibility.value, 0)   # visible label, not a tooltip
        self.assertIn("Medication list", " ".join(c.value for c in box.caption))
        self.assertTrue(next(b for b in box.button if b.label == "Add to the timeline").disabled)
        pending = "\n".join(c.value for c in box.caption)
        self.assertIn("Enter a document title", pending)
        self.assertIn("[unreadable]", pending)
        self.assertIn("2 line(s) still need checking", pending)
        nodes = list(at.main)
        checklist = next(i for i, node in enumerate(nodes) if node.type == "checkbox" and (node.key or "").startswith("photo_ok_"))
        self.assertTrue(any(node.type == "markdown" and "2. Compare and tick each line" in node.value
                            for node in nodes[:checklist]))
        original_photo = at.session_state["photo"]["bytes"]
        original_seq = at.session_state["episode"].seq
        title.set_value("My medication list").run()
        pending = "\n".join(c.value for c in self.completion_box(at).caption)
        self.assertNotIn("Enter a document title", pending)
        self.assertIn("[unreadable]", pending)
        self.assertIn("2 line(s) still need checking", pending)
        self.assertFalse(any(c.value for c in ticks(at)))
        self.assertEqual(at.text_area(key="photo_text").value, reading)
        self.assertEqual(at.session_state["photo"]["bytes"], original_photo)
        at.text_area(key="photo_text").set_value(reading.replace("[unreadable]", "15 mg")).run()
        self.assertEqual(at.text_input(key="photo_of_text").value, "My medication list")
        ticks(at)[0].check().run()
        pending = "\n".join(c.value for c in self.completion_box(at).caption)
        self.assertIn("1 line(s) still need checking", pending)
        self.assertNotIn("[unreadable]", pending)
        self.assertTrue(button(at, "Add to the timeline").disabled)
        ticks(at)[1].check().run()
        self.assertFalse(button(at, "Add to the timeline").disabled)
        self.assertEqual(at.text_input(key="photo_of_text").value, "My medication list")
        self.assertEqual(at.session_state["episode"].seq, original_seq)   # readiness never auto-adds

    def test_completion_box_reports_empty_text_and_missing_title_together(self):
        at = self.live("Lansoprazole 15 mg once a day.")
        at.text_area(key="photo_text").set_value("   ").run()
        box = self.completion_box(at)
        pending = "\n".join(c.value for c in box.caption)
        self.assertIn("Enter a document title", pending)
        self.assertIn("Source text is empty", pending)
        self.assertTrue(button(at, "Add to the timeline").disabled)
        self.assertEqual(at.text_input(key="photo_of_text").value, "")

    def test_failed_reread_keeps_the_corrected_text(self):
        at = self.live("Lansoprazole 1.5 mg once a day.")
        at.text_area(key="photo_text").set_value("Lansoprazole 15 mg once a day.").run()

        class Down:
            model = "stub"

            def chat(self, *a, **k):
                raise TimeoutError("no reply in 400 s")
        at.session_state["photo_reader"] = photo_reader(Down())
        next(b for b in at.button if b.label == "Discard my corrections and read again").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("Could not read the photo" in e.value for e in at.error))
        at.run()
        self.assertEqual(at.text_area(key="photo_text").value, "Lansoprazole 15 mg once a day.")

    def test_photo_wait_hints_cover_read_and_add_without_duplicate_calls(self):
        observed, calls, hint_paths = [], [], []
        with observe_working_hints() as (active, shown):
            class Reader(VisionStub):
                def chat(reader, *args, **kwargs):
                    calls.append("read")
                    observed.append(("read", list(active.values())))
                    hint_paths.extend(active)
                    time.sleep(0.6)   # a real blocked model boundary with only a local stand-in
                    return super().chat(*args, **kwargs)
            class Extractor(StubModel):
                def chat(extractor, *args, **kwargs):
                    calls.append("facts")
                    observed.append(("facts", list(active.values())))
                    hint_paths.extend(active)
                    return super().chat(*args, **kwargs)
            at = fresh()
            os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")
            at.session_state["photo_reader"] = photo_reader(Reader("Lansoprazole 15 mg once a day."))
            at.session_state["extractor"] = llm_extractor(Extractor({"facts": []}))
            at.run(); open_photo(at)
            button(at, "Use the sample photo (discharge medication list)").click().run()
            button(at, "Read the text on the photo").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(active, {})
            at.text_input(key="photo_of_text").set_value("My paper").run()
            for checkbox in ticks(at): checkbox.check()
            at.run()
            button(at, "Add to the timeline").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(calls, ["read", "facts"])
            self.assertEqual(active, {})
            self.assertEqual(len(at.session_state["episode"].updates), 1)
        self.assertEqual([name for name, messages in observed if messages], ["read", "facts"])
        self.assertEqual(hint_paths, [(0, 0), (0, 0)], "Waiting banners must use the root slot outside filtered panels")
        self.assertIn("Reading the words on your photo", " ".join(observed[0][1]))
        self.assertIn("Checking your photo for the timeline", " ".join(observed[1][1]))
        self.assertTrue(all('role="status"' in message for _, messages in observed for message in messages))

    def test_failed_photo_wait_clears_hint_and_keeps_checked_draft(self):
        at = self.live("Lansoprazole 1.5 mg once a day.")
        at.text_area(key="photo_text").set_value("Lansoprazole 15 mg once a day.").run()
        at.text_input(key="photo_of_text").set_value("Keep this title").run()
        ticks(at)[0].check().run()
        calls, observed = [], []
        with observe_working_hints() as (active, shown):
            class Down:
                def __call__(reader, *args):
                    calls.append("read")
                    observed.extend(active.values())
                    raise TimeoutError("injected local failure")
            at.session_state["photo_reader"] = Down()
            button(at, "Discard my corrections and read again").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(active, {})
        self.assertEqual(calls, ["read"])
        self.assertTrue(observed)
        self.assertTrue(any("Could not read the photo" in error.value for error in at.error))
        self.assertEqual(at.text_input(key="photo_of_text").value, "Keep this title")
        self.assertEqual(at.text_area(key="photo_text").value, "Lansoprazole 15 mg once a day.")
        self.assertTrue(ticks(at)[0].value)


def own_photo(text: str = "MY OWN PHOTO") -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (600, 300), "white")
    ImageDraw.Draw(img).text((20, 20), text, fill="black")
    out = io.BytesIO()
    img.save(out, "JPEG")
    return out.getvalue()


class TestUploads(unittest.TestCase):
    """The caregiver's own photo (the uploader), not only the sample: these paths broke without any sample-only test noticing."""
    READING = "Lansoprazole 15 mg once a day.\nSTOP taking Ibuprofen."

    def tearDown(self):
        for k in ("CARERELAY_LLM_BASE_URL", "CARERELAY_LLM_MODEL"):
            os.environ.pop(k, None)

    def app(self):
        at = fresh()
        add_story(at, 7)
        os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")
        self.vision = VisionStub(self.READING)
        at.session_state["photo_reader"] = photo_reader(self.vision)
        at.session_state["extractor"] = llm_extractor(StubModel({"facts": [
            {"type": "medication", "name": "Lansoprazole", "dose": "15 mg", "frequency": "once a day", "status": "new",
             "quote": "Lansoprazole 15 mg once a day"}]}))
        at.run()
        open_photo(at)
        return at

    def test_own_photo_is_read_checked_and_added(self):
        at = self.app()
        at.file_uploader[0].set_value(("list.jpg", own_photo(), "image/jpeg")).run()
        next(b for b in at.button if b.label == "Read the text on the photo").click().run()
        self.assertEqual(at.text_area(key="photo_text").value, self.READING)   # the reading survives the rerun
        at.run()
        self.assertEqual(at.text_area(key="photo_text").value, self.READING)   # and the next one
        self.assertEqual(self.vision.calls, 1)
        for c in ticks(at):
            c.check()
        at.text_input(key="photo_of_text").set_value("Medication list").run()
        next(b for b in at.button if b.label == "Add to the timeline").click().run()
        self.assertFalse(at.exception)
        self.assertNotIn("Medication list updated: 1 new, 0 stopped, 0 continued or changed", heads(at))
        self.assertEqual(at.session_state["episode"].updates[-1]["text"], self.READING)
        self.assertIn("Source documents and messages", page(at))
        self.assertEqual(len(at.session_state["photos"]), 1)

    def test_invalid_replacement_cannot_keep_the_previous_photo_or_reading(self):
        at = self.app()
        at.file_uploader[0].set_value(("first.jpg", own_photo("FIRST PAPER"), "image/jpeg")).run()
        button(at, "Read the text on the photo").click().run()
        for c in ticks(at):
            c.check()
        at.text_input(key="photo_of_text").set_value("First medication list").run()
        self.assertFalse(button(at, "Add to the timeline").disabled)
        seq = at.session_state["episode"].seq

        at.file_uploader[0].set_value(("broken.jpg", b"not a decodable image", "image/jpeg")).run()
        self.assertFalse(at.exception)
        self.assertTrue(any("could not be opened as a photo" in e.value for e in at.error))
        for key in ("photo", "photo_reading", "photo_text", "photo_of_text"):
            self.assertNotIn(key, at.session_state, f"Rejected replacement retained {key}")
        self.assertFalse(any(b.label == "Add to the timeline" for b in at.button))
        self.assertEqual(at.session_state["episode"].seq, seq)
        self.assertEqual(self.vision.calls, 1)

        # A valid replacement must still be accepted after the rejection.
        self.vision.text = "Paracetamol one tablet twice daily."
        at.file_uploader[0].set_value(("second.jpg", own_photo("SECOND PAPER"), "image/jpeg")).run()
        button(at, "Read the text on the photo").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.text_area(key="photo_text").value, self.vision.text)
        self.assertEqual(self.vision.calls, 2)

    def test_photo_spelled_dose_and_frequency_require_confirmation(self):
        at = self.app()
        self.vision.text = "Paracetamol one tablet twice daily.\nKeep the leg moving."
        at.file_uploader[0].set_value(("worded-list.jpg", own_photo(self.vision.text), "image/jpeg")).run()
        button(at, "Read the text on the photo").click().run()
        at.text_input(key="photo_of_text").set_value("Medication list").run()
        self.assertEqual([c.label for c in ticks(at)], ["Paracetamol one tablet twice daily."])
        self.assertTrue(button(at, "Add to the timeline").disabled)
        ticks(at)[0].check().run()
        self.assertFalse(button(at, "Add to the timeline").disabled)
        self.assertEqual(at.text_area(key="photo_text").value, self.vision.text)

    def test_sample_choice_sticks_and_removing_the_upload_clears_it(self):
        at = self.app()
        at.file_uploader[0].set_value(("list.jpg", own_photo(), "image/jpeg")).run()
        next(b for b in at.button if b.label == "Use the sample photo (discharge medication list)").click().run()
        next(b for b in at.button if b.label == "Read the text on the photo").click().run()
        self.assertEqual(at.session_state["photo"]["id"], "sample")
        at2 = self.app()
        at2.file_uploader[0].set_value(("list.jpg", own_photo(), "image/jpeg")).run()
        self.assertIsNotNone(at2.session_state["photo"])
        at2.file_uploader[0].set_value(None).run()
        self.assertFalse("photo" in at2.session_state and at2.session_state["photo"])

    def test_results_of_interrupted_runs_are_picked_up(self):
        at = self.app()
        next(b for b in at.button if b.label == "Use the sample photo (discharge medication list)").click().run()
        at.session_state["photo"]["reading"] = {"text": self.READING, "image_sha256": "x", "model": "vision-stub"}   # a read whose run was stopped
        at.run()
        self.assertEqual(at.text_area(key="photo_text").value, self.READING)
        ep = at.session_state["episode"]   # an Add whose run was stopped after the update went in
        at.session_state["photo"]["add_started"] = True   # set in place by the Add before its slow call
        ep.add_update({"update_id": "c01", "at": ep.latest_at(), "kind": "photo", "author": "anna", "photo_of": "Medication list",
                       "text": self.READING, "image": None, "reading": {"method": "model", "image_sha256": "x"}}, facts=[])
        at.run()
        self.assertFalse(at.exception)
        self.assertIn("c01", at.session_state["photos"])
        self.assertFalse(any(b.label == "Add to the timeline" for b in at.button))


class TestRecordings(unittest.TestCase):
    """A recording written out by speech-to-text (a stub here; Whisper where installed), checked line by line, corrected."""
    HEARD = "She can go home on Friday.\nStop the ibuprofen.\nKeep the leg moving."

    def tearDown(self):
        for k in ("CARERELAY_LLM_BASE_URL", "CARERELAY_LLM_MODEL"):
            os.environ.pop(k, None)

    def test_written_out_checked_corrected_and_added(self):
        at = fresh()
        add_story(at, 3)
        os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")   # never called
        calls = []

        def transcribe(data, suffix):
            calls.append((len(data), suffix))
            return {"text": self.HEARD, "model": "Whisper stub", "latency_s": 1.0}
        at.session_state["transcriber"] = transcribe
        at.session_state["extractor"] = llm_extractor(StubModel({"facts": [
            {"type": "medication", "name": "Ibuprofen", "status": "stop", "quote": "Stop the ibuprofen"}]}))
        at.run()
        open_panel(at, "recording")
        self.assertFalse(any(b.label == "Write out the recording" for b in at.button))   # nothing recorded yet
        self.assertFalse(any(u.key == "rec_upload_0" for u in at.get("file_uploader")))   # no recorder before consent
        at.checkbox(key="rec_consent_0").check().run()   # they agreed to be recorded
        at.file_uploader(key="rec_upload_0").set_value(("nurse.wav", b"RIFF0000WAVEfmt fake", "audio/wav")).run()
        button(at, "Write out the recording").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(calls, [(20, ".wav")])
        self.assertEqual(at.text_area(key="rec_text").value, self.HEARD)
        at.run()
        self.assertEqual(at.text_area(key="rec_text").value, self.HEARD)   # kept on the next run, no second call
        self.assertEqual(len(calls), 1)
        corrected = self.HEARD.replace("on Friday", "on Saturday")   # misheard, corrected by hand
        at.text_area(key="rec_text").set_value(corrected).run()
        self.assertIn("Discard my corrections and write it out again", [b.label for b in at.button])
        at.text_input(key="rec_speaker").set_value("Ward nurse").run()
        self.assertEqual([c.label for c in ticks(at)],   # a day, a stop / continue or a number
                         ["She can go home on Saturday.", "Stop the ibuprofen."])
        self.assertTrue(at.button(key="rec_add").disabled)
        for c in ticks(at):
            c.check()
        at.run()
        at.button(key="rec_add").click().run()
        self.assertFalse(at.exception)
        upd = at.session_state["episode"].updates[-1]
        self.assertEqual((upd["kind"], upd["speaker"], upd["text"]), ("recording", "Ward nurse", corrected))
        self.assertEqual(upd["reading"]["changed_lines"], ["She can go home on Saturday."])
        self.assertIn("Written out from the recording by Whisper stub; Anna ticked 2 line(s)", page(at))
        self.assertIn("written out, 2 line(s) with numbers or stop / continue checked", page(at))
        self.assertTrue(any(b.key == "add_recording" for b in at.button))   # closed once added

    def test_spelled_doses_and_frequencies_require_each_line_to_be_checked(self):
        heard = "Take one tablet twice daily.\nTake half a tablet once weekly.\nKeep the leg moving."
        at = fresh()
        calls = []

        def transcribe(data, suffix):
            calls.append((data, suffix))
            return {"text": heard, "model": "Whisper stub", "latency_s": 1.0,
                    "needs_check": ["numbers", "times"]}

        at.session_state["transcriber"] = transcribe
        at.run()
        open_panel(at, "recording")
        at.checkbox(key="rec_consent_0").check().run()
        audio = b"uploaded English recording stand-in"
        at.file_uploader(key="rec_upload_0").set_value(("own-recording.m4a", audio, "audio/mp4")).run()
        button(at, "Write out the recording").click().run()
        at.text_input(key="rec_speaker").set_value("Ward nurse").run()
        self.assertFalse(at.exception)
        self.assertEqual(calls, [(audio, ".m4a")])
        self.assertEqual([c.label for c in ticks(at)], heard.splitlines()[:2])
        self.assertTrue(at.button(key="rec_add").disabled)
        ticks(at)[0].check().run()
        self.assertTrue(at.button(key="rec_add").disabled)
        ticks(at)[1].check().run()
        self.assertFalse(at.button(key="rec_add").disabled)
        self.assertEqual(at.text_area(key="rec_text").value, heard)
        at.button(key="rec_add").click().run()
        self.assertFalse(at.exception)
        update = at.session_state["episode"].updates[-1]
        self.assertEqual(update["text"], heard)
        self.assertEqual(update["reading"]["confirmed_lines"], 2)
        self.assertEqual(update["reading"]["changed_lines"], [])
        self.assertEqual(update["reading"]["model_text"], heard)

    def test_removing_the_recording_removes_its_text(self):
        at = fresh()
        at.session_state["transcriber"] = lambda data, suffix: {"text": self.HEARD, "model": "Whisper stub", "latency_s": 1.0}
        at.run()
        open_panel(at, "recording")
        at.checkbox(key="rec_consent_0").check().run()   # they agreed to be recorded
        at.file_uploader(key="rec_upload_0").set_value(("nurse.wav", b"RIFF0000WAVE", "audio/wav")).run()
        button(at, "Write out the recording").click().run()
        at.text_area(key="rec_text").set_value(self.HEARD.replace("Friday", "Saturday")).run()
        at.file_uploader(key="rec_upload_0").set_value(None).run()
        self.assertFalse(at.exception)
        self.assertEqual(at.text_area(key="rec_text").value, "")
        self.assertEqual(at.session_state["rec"], {})

    def test_a_failed_write_out_says_so_and_leaves_typing(self):
        at = fresh()

        def down(data, suffix):
            raise FileNotFoundError("ffmpeg")
        at.session_state["transcriber"] = down
        at.run()
        open_panel(at, "recording")
        at.checkbox(key="rec_consent_0").check().run()   # they agreed to be recorded
        at.file_uploader(key="rec_upload_0").set_value(("nurse.wav", b"RIFF0000WAVE", "audio/wav")).run()
        button(at, "Write out the recording").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("Could not write out the recording" in e.value for e in at.error))
        self.assertEqual(at.text_area(key="rec_text").value, "")


class TestWaitingHints(unittest.TestCase):
    def tearDown(self):
        for key in ("CARERELAY_LLM_BASE_URL", "CARERELAY_LLM_MODEL"):
            os.environ.pop(key, None)

    def test_recording_typed_update_and_question_show_actual_wait(self):
        observed, calls = [], []
        with observe_working_hints() as (active, shown):
            def transcribe(data, suffix):
                calls.append("speech"); observed.append(("speech", list(active.values())))
                return {"text": "Keep the leg moving.", "model": "local speech fixture"}
            class Extractor(StubModel):
                def chat(extractor, *args, **kwargs):
                    calls.append("update"); observed.append(("update", list(active.values())))
                    return super().chat(*args, **kwargs)
            def answer(episode, question, member):
                calls.append("answer"); observed.append(("answer", list(active.values())))
                return episode_answerer(None)(episode, question, member)
            at = fresh()
            at.session_state["transcriber"] = transcribe
            os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")
            at.session_state["extractor"] = llm_extractor(Extractor({"facts": []}))
            at.session_state["answerer"] = answer
            at.run(); open_panel(at, "recording")
            at.checkbox(key="rec_consent_0").check().run()
            at.file_uploader(key="rec_upload_0").set_value(("local.wav", b"RIFF fixture", "audio/wav")).run()
            button(at, "Write out the recording").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(active, {})
            self.assertEqual(at.text_area(key="rec_text").value, "Keep the leg moving.")
            at.text_input(key="rec_speaker").set_value("Ward nurse").run()
            at.button(key="rec_add").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(active, {})
            self.assertEqual(at.session_state["episode"].updates[-1]["text"], "Keep the leg moving.")
            at = reload_view(at)
            ask(at, "How is she doing?")
            self.assertFalse(at.exception)
            self.assertEqual(active, {})
        self.assertEqual(calls, ["speech", "update", "answer"])
        self.assertEqual([name for name, messages in observed if messages], calls)
        for (_, messages), expected in zip(observed, ("Writing out your recording", "Adding your update to the timeline", "Looking through the updates")):
            self.assertIn(expected, " ".join(messages))

    def test_story_and_source_correction_show_wait_before_verification(self):
        observed, calls, hint_paths = [], [], []
        with observe_working_hints() as (active, shown):
            def checker(update, fact):
                calls.append("story"); observed.append(("story", list(active.values())))
                hint_paths.extend(active)
                return {"mode": "shadow", "status": "supported_by_model", "model_id": "injected-system-fixture"}
            class Extractor(StubModel):
                def chat(extractor, *args, **kwargs):
                    calls.append("correction"); observed.append(("correction", list(active.values())))
                    hint_paths.extend(active)
                    return super().chat(*args, **kwargs)
            at = fresh()   # bootstrap project modules before installing a factory double
            with patch("evidence_gate.checker_from_env", return_value=checker):
                at.run(); add_story(at, 1)
                self.assertEqual(active, {})
                os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")
                at.session_state["extractor"] = llm_extractor(Extractor({"facts": []}))
                at.run()
                at.text_area(key="correction_text_u01_1").set_value("These are the checked source words.").run()
                at.checkbox(key="correction_checked_u01_1").check().run()
                at.button(key="correction_save_u01_1").click().run()
                self.assertFalse(at.exception)
                self.assertEqual(active, {})
                self.assertEqual(at.session_state["episode"].source_revision("u01"), 2)
        self.assertTrue(any(name == "story" for name in calls))
        self.assertEqual(calls.count("correction"), 1)
        self.assertTrue(hint_paths)
        self.assertTrue(all(path == (0, 0) for path in hint_paths), "Callbacks and corrections must share the root waiting slot")
        for name, messages in observed:
            self.assertTrue(messages)
            self.assertIn("Adding the next story update" if name == "story" else "Updating the corrected source", " ".join(messages))


class TestLooks(unittest.TestCase):
    def test_each_look_is_one_style_block_and_only_its_own_css(self):
        for look in ("sunlit", "pastel", "honey", "oat", "nonsense", None):
            at = AppTest.from_file(PAGE, default_timeout=60)
            if look:
                at.query_params["look"] = look
            at.run()
            css = next(m.value for m in at.markdown if "--cr-fs" in m.value)
            self.assertEqual((css.count("<style>"), css.count("</style>")), (1, 1), look)
            self.assertNotIn("\n\n", css, look)   # a blank line would end st.markdown's HTML block
            self.assertEqual("--cr-now:#8E4518" in css, look == "sunlit", look)   # sunlit: only when asked for

    def test_frostsky_is_one_style_block_and_its_css_only_for_its_key(self):
        for look in ("frostsky", "sunlit", "oat", "nonsense", None):
            at = AppTest.from_file(PAGE, default_timeout=60)
            if look:
                at.query_params["look"] = look
            at.run()
            self.assertFalse(at.exception, look)
            css = next(m.value for m in at.markdown if "--cr-fs" in m.value)
            self.assertEqual((css.count("<style>"), css.count("</style>")), (1, 1), look)
            self.assertNotIn("\n\n", css, look)   # a blank line would end st.markdown's HTML block
            self.assertEqual("--fs-orb" in css, look in ("frostsky", "nonsense", None), look)   # the frosted tiles: the default
            self.assertEqual("--cr-now:#FFEFDF" in css, look in ("frostsky", "nonsense", None), look)   # its tokens


class TestTwoAnswersOnThePage(unittest.TestCase):
    """The whole demo story: the consultant's 'today' after the nurse's 'Saturday' is two answers, not an update."""

    def setUp(self):
        os.environ["CARERELAY_STORY"] = str(FULL_STORY)

    def tearDown(self):
        os.environ["CARERELAY_STORY"] = str(SHORT_STORY)

    def test_two_answers_are_shown_asked_and_settled(self):
        at = fresh()
        add_story(at, 8)   # ... u07 (Saturday, ward nurse), u07b (today, Mr Okafor)
        self.assertIn("Two different answers about going home: Sat 24 Oct morning or Fri 23 Oct?", heads(at))
        html = page(at)
        self.assertIn('class="cr-alert cr-conflict"', html)
        self.assertIn("Sat 24 Oct morning or Fri 23 Oct?", html)
        self.assertIn("added automatically: the care team gave two different answers", html)
        self.assertIn("Which is right?", html)   # on the list for the doctor
        add_story(at, 1)   # u07c: the nurse checked with the team: Saturday
        self.assertEqual(heads(at)[0], "Settled, going home: Sat 24 Oct morning")
        self.assertNotIn('class="cr-alert cr-conflict"', page(at))
        q = at.session_state["episode"].questions[0]
        self.assertEqual((q["status"], q["answered_by"]), ("answered", "u07c"))

    def test_the_family_confirms_which_is_right(self):
        at = fresh()
        add_story(at, 8)
        episode = at.session_state["episode"]
        pair = next(p for p in episode.two_answers() if p["type"] == "expected_discharge")
        qid = pair["qid"]
        self.assertEqual({a["update_id"] for a in pair["answers"]}, {"u07", "u07b"})
        self.assertEqual(next(q for q in episode.questions if q["qid"] == qid)["status"], "open")
        self.assertFalse(any(b.key == f"qdone_{qid}" for b in at.button))   # no plain "answered" for two answers
        at.button(key=f"qpick_{qid}_u07").click().run()
        self.assertFalse(at.exception)
        question = next(q for q in episode.questions if q["qid"] == qid)
        self.assertEqual((question["status"], question["answered_by"], question["marked_by"]), ("answered", "u07", "anna"))
        self.assertEqual([t.value for t in at.toast], ["Confirmed: going home Sat 24 Oct morning. Everyone sees it now."])
        self.assertNotIn('class="cr-alert cr-conflict"', page(at))
        self.assertIn("Confirmed with the care team by Anna", page(at))



class TestPlans(unittest.TestCase):
    def test_plans_show_who_is_coming(self):
        at = fresh()
        self.assertNotIn("Who's coming, who's helping", html.unescape(page(at)))   # no one has shared a plan yet
        add_story(at, 4)
        side = html.unescape(page(at))
        self.assertIn("Who's coming, who's helping", side)
        self.assertIn("Booked a flight from Toronto, landing at Heathrow on Wednesday morning.", side)

    def test_tagline_and_about(self):
        at = fresh()
        self.assertIn("One place to understand what&#x27;s happening, and be there for each other.", page(at))
        self.assertTrue(any("doesn't have to carry every conversation alone" in m.value for m in at.sidebar.markdown))

    def test_share_my_plan_from_a_starter(self):
        at = fresh()
        open_panel(at, "paper")
        button(at, "I'm coming…").click().run()
        self.assertEqual(at.text_area(key="note_text").value, "I'll be there on ")
        at.text_area(key="note_text").set_value("I'll be there on Thursday evening and can bring her glasses.").run()
        button(at, "Share with the family").click().run()
        self.assertFalse(at.exception)
        side = html.unescape(page(at))
        self.assertIn("(you)</b>: I'll be there on Thursday evening and can bring her glasses.", side)
        self.assertIsNone(at.session_state["adding"])


class FakeCapture(io.BytesIO):
    """Public capture-widget boundary double; AppTest has no audio/camera setters."""
    def __init__(self, data, name, file_id):
        super().__init__(data)
        self.name, self.file_id = name, file_id


class TestLiveModuleBootstrap(unittest.TestCase):
    def test_stale_cached_modules_reload_once_and_keep_the_existing_anna_source(self):
        code = r'''
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path("handoff_day1/ui").resolve()))
sys.path.insert(0, str(Path("handoff_day1/agent").resolve()))
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.util import patch_config_options
import episode, episode_qa, timeline_html, evidence_gate
from test_timeline_page import PAGE, SHORT_STORY
ep = episode.Episode(episode.load_scenario(SHORT_STORY))
ep.add_update({"update_id": "c01", "at": "2026-10-19T08:00:00+01:00", "kind": "note",
               "author": "anna", "topic": "plan", "text": "I'll be there on 10/20 afternoon."}, facts=[])
ep.mark_read("anna")
events, updates, seen = ep.events, ep.updates.copy(), ep.seen.copy()
del episode.upgrade_episode
del timeline_html.source_archive_html
episode_qa.QA_VERSION = "stale-module-fixture"
evidence_gate._identity = lambda *args: {"stale": True}
for name in ("episode_events", "evidence_gate", "episode", "episode_qa", "timeline_html"):
    vars(sys.modules[name]).pop("_kindred_page_source_sha256", None)
with patch_config_options({"secrets.files": []}):
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["episode"] = ep
    at.run()
    assert not at.exception, [(e.type, e.message) for e in at.exception]
    assert at.session_state["episode"] is ep
    assert (ep.events, ep.updates, ep.seen) == (events, updates, seen)
    assert len(ep.updates) == 1 and ep.updates[0]["update_id"] == "c01"
    assert callable(episode.upgrade_episode) and callable(timeline_html.source_archive_html)
    assert episode_qa.QA_VERSION != "stale-module-fixture"
    source = {"update_id": "gate-probe", "kind": "recording", "speaker_type": "family", "speaker": "Anna",
              "at": "2026-10-19T08:00:00+01:00", "text": "She is awake in hospital."}
    fact = {"type": "event", "what": "She is awake", "quote": source["text"], "fact_id": "gate-probe@1:f1"}
    bound = evidence_gate.bind_check(source, fact, {"mode": "shadow", "status": "supported_by_model"})
    assert evidence_gate.check_is_fresh(source, fact, bound)
    assert not evidence_gate.check_is_fresh({**source, "speaker_type": "care_team"}, fact, bound)
    loaded = episode.Episode, episode_qa.refresh, timeline_html.timeline_html, evidence_gate._identity
    at.run()
    assert not at.exception, [(e.type, e.message) for e in at.exception]
    assert (episode.Episode, episode_qa.refresh, timeline_html.timeline_html, evidence_gate._identity) == loaded
    assert at.session_state["episode"] is ep and ep.events == events
print("BOOTSTRAP PASS: cached modules replaced once; same Anna c01, journal and read state retained")
'''
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "KINDRED_VERIFIER_MODE": "off"}
        for name in tuple(env):
            if name.startswith(("CARERELAY_LLM_", "CARERELAY_PHOTO_", "KINDRED_VERIFIER_")):
                env.pop(name)
        env["KINDRED_VERIFIER_MODE"] = "off"
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2],
                                env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BOOTSTRAP PASS", result.stdout)


class TestExtractorCache(unittest.TestCase):
    def tearDown(self):
        for name in ("CARERELAY_LLM_BASE_URL", "CARERELAY_LLM_MODEL"):
            os.environ.pop(name, None)

    def test_legacy_and_stale_app_owned_extractors_are_replaced_lazily(self):
        for legacy in (True, False):
            with self.subTest(legacy=legacy):
                at = fresh()
                old_calls, prompts = [], []
                def old_extract(update, episode):
                    old_calls.append(update)
                    return []
                old_extract.log = []
                if not legacy:
                    old_extract._kindred_explicit_factory = True
                    old_extract._kindred_app_owned = True
                    old_extract._kindred_source_sha256 = "older-source-fixture"
                at.session_state["extractor"] = old_extract
                class Model(StubModel):
                    def chat(self, messages, **kwargs):
                        prompts.append(messages[-1]["content"])
                        return super().chat(messages, **kwargs)
                model = Model({"facts": []})
                os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")
                with patch("llm_client.make_client", return_value=model) as factory:
                    at.run()
                    at.button(key="add_recording").click().run()
                    at.text_area(key="rec_text").set_value("She is awake in hospital.").run()
                    self.assertEqual(factory.call_count, 0)   # rendering does not create clients or call a model
                    at.button(key="rec_add").click().run()
                    self.assertFalse(at.exception)
                    factory.assert_called_once_with(max_tokens=2000)
                    self.assertEqual(old_calls, [])
                    self.assertEqual(len(prompts), 1)
                    self.assertIn("family recording by Anna", prompts[0])
                    cached = at.session_state["extractor"]
                    self.assertIsNot(cached, old_extract)
                    self.assertTrue(cached._kindred_app_owned)
                    self.assertEqual(cached._kindred_source_sha256, sys.modules["episode"]._kindred_page_source_sha256)
                    at = reload_view(at)   # the completed submit removed the recording widgets
                    self.assertIs(at.session_state["extractor"], cached)
                    self.assertEqual(factory.call_count, 1)

    def test_an_explicit_factory_built_stand_in_remains_usable(self):
        at = fresh()
        explicit = llm_extractor(StubModel({"facts": []}))
        at.session_state["extractor"] = explicit
        os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")
        with patch("llm_client.make_client", side_effect=AssertionError("must retain the explicit stand-in")):
            at.run()
            at.button(key="add_recording").click().run()
            at.text_area(key="rec_text").set_value("She is awake in hospital.").run()
            at.button(key="rec_add").click().run()
            self.assertFalse(at.exception)
            self.assertIs(at.session_state["extractor"], explicit)
            self.assertEqual(len(explicit.log), 1)
            self.assertEqual(at.session_state["episode"].entries[-1]["authority"], "family")


class TestInputClock(unittest.TestCase):
    def test_annas_explicit_plan_shows_only_its_event_date(self):
        at = fresh()
        note(at, "I'll be there on 10/20 afternoon.")
        source = at.session_state["episode"].updates[-1]
        receipt = dt.datetime.fromisoformat(source["at"]).strftime("%a %d %b %H:%M")
        rendered = html.unescape(page(at))
        self.assertIn("Tuesday 20 Oct 2026", rendered)
        self.assertIn("afternoon", rendered)
        self.assertNotIn("Mon 19 Oct 08:00", rendered)
        self.assertNotIn(receipt, rendered)
        self.assertNotRegex(rendered, r"(?:Added|Received|Uploaded)\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b")

    def test_manual_plan_uses_wall_clock_even_after_future_demo_updates(self):
        at = fresh()
        before = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        note(at, "I'll be there on 10/20 afternoon.")
        first = dt.datetime.fromisoformat(at.session_state["episode"].updates[-1]["at"])
        self.assertIsNotNone(first.utcoffset())
        self.assertGreaterEqual(first, before)
        self.assertLessEqual(first, dt.datetime.now(dt.timezone.utc))
        at = reload_view(at)
        add_story(at, 3)
        before = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        note(at, "I'll be there tomorrow afternoon.")
        latest = dt.datetime.fromisoformat(at.session_state["episode"].updates[-1]["at"])
        self.assertGreaterEqual(latest, before)
        self.assertLessEqual(latest, dt.datetime.now(dt.timezone.utc))

    def test_earlier_source_picker_uses_actual_hospital_today(self):
        at = fresh()
        add_story(at, 3)
        open_panel(at, "recording")
        at.checkbox(key="rec_0_earlier").check().run()
        today = dt.datetime.now(ZoneInfo("Europe/London")).date()
        self.assertEqual(at.date_input(key="rec_0_day").value, today)
        earlier = today - dt.timedelta(days=1)
        at.date_input(key="rec_0_day").set_value(earlier).run()
        at.time_input(key="rec_0_time").set_value(dt.time(12)).run()
        at.text_input(key="rec_speaker").set_value("Ward nurse").run()
        at.text_area(key="rec_text").set_value("Keep the leg moving.").run()
        at.button(key="rec_add").click().run()
        self.assertFalse(at.exception)
        actual = dt.datetime.fromisoformat(at.session_state["episode"].updates[-1]["at"])
        self.assertEqual(actual, dt.datetime.combine(earlier, dt.time(12), ZoneInfo("Europe/London")))

    def test_rerun_upgrades_an_old_session_in_place_and_preserves_its_journal(self):
        from episode import Episode
        at = fresh()
        add_story(at, 3)
        episode = at.session_state["episode"]
        words = "I'll be there on 10/20 afternoon."
        episode.add_update({"update_id": "c01", "at": "2026-10-19T08:00:00+01:00", "kind": "note",
                            "author": "anna", "topic": "plan", "text": words}, facts=[])
        question, _ = episode.add_question("Who can bring her glasses?", "anna")
        episode.mark_read("anna")
        before, sources, seen = episode.events, [u.copy() for u in episode.updates], episode.seen.copy()
        episode.__class__ = type("PreEventTimeEpisode", (Episode,), {})
        del episode._temporal_projection
        at.run()
        self.assertFalse(at.exception)
        self.assertIs(at.session_state["episode"], episode)
        self.assertIs(type(episode), Episode)
        self.assertEqual((episode.events, episode.updates, episode.seen), (before, sources, seen))
        self.assertIs(episode.questions[-1], question)
        self.assertIn(words.replace("'", "&#x27;"), page(at))
        self.assertIn("Source documents and messages", page(at))


class TestSpokenPlans(unittest.TestCase):
    HEARD = "I'll be there on 10/20 afternoon."

    def tearDown(self):
        for key in ("CARERELAY_LLM_BASE_URL", "CARERELAY_LLM_MODEL"):
            os.environ.pop(key, None)

    def app(self, transcribe):
        at = fresh()
        at.session_state["transcriber"] = transcribe
        at.run()
        at.selectbox[0].set_value("david").run()
        open_panel(at, "paper")
        return at

    def test_one_save_transcribes_extracts_and_adds_as_the_current_family_member(self):
        calls, hints = [], []
        with observe_working_hints() as (active, shown):
            def transcribe(data, suffix):
                calls.append((data, suffix))
                hints.extend(active.values())
                return {"text": self.HEARD, "model": "English speech fixture"}
            at = self.app(transcribe)
            self.assertIn("Record your plan in English, stop, then select Save my plan.", [c.value for c in at.caption])
            os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")
            extracted = []
            class Extractor(StubModel):
                def chat(extractor, *args, **kwargs):
                    extracted.extend(active.values())
                    return super().chat(*args, **kwargs)
            at.session_state["extractor"] = llm_extractor(Extractor({"facts": []}))
            capture = FakeCapture(b"English spoken plan", "plan.wav", "plan-1")
            with patch("streamlit.audio_input", return_value=capture) as microphone:
                at.run()
                self.assertEqual(microphone.call_args.args[0], "Record your plan in English")
                self.assertTrue(microphone.call_args.kwargs["key"].startswith("plan_audio_david_"))
                self.assertFalse(at.button(key="plan_save").disabled)
                at.button(key="plan_save").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(active, {})
        self.assertEqual(calls, [(b"English spoken plan", ".wav")])
        self.assertTrue(hints)
        self.assertTrue(extracted)
        update = at.session_state["episode"].updates[-1]
        self.assertEqual((update["kind"], update["topic"], update["author"], update["text"]),
                         ("note", "plan", "david", self.HEARD))
        self.assertEqual(at.session_state["episode"].entries[-1]["authority"], "family")
        self.assertIn("speech-to-text", page(at))
        self.assertIn("Tue 20 Oct", html.unescape(page(at)))
        self.assertIn("afternoon", html.unescape(page(at)))
        self.assertIn("Correct an update", [e.label for e in at.expander])

    def test_same_recording_rerun_or_repeat_save_does_not_add_twice(self):
        calls = []
        def transcribe(data, suffix):
            calls.append(data)
            return {"text": self.HEARD, "model": "speech fixture"}
        at = self.app(transcribe)
        capture = FakeCapture(b"one spoken plan", "plan.wav", "plan-2")
        with patch("streamlit.audio_input", return_value=capture):
            at.run()
            at.run()
            self.assertEqual(calls, [])
            at.button(key="plan_save").click().run()
            at = reload_view(at)
            at.selectbox[0].set_value("david").run()
            open_panel(at, "paper")
            at.button(key="plan_save").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.session_state["episode"].updates), 1)
        self.assertEqual(len(calls), 1)

    def test_a_new_recording_with_the_same_words_is_a_new_save_intent(self):
        calls = []
        def transcribe(data, suffix):
            calls.append(data)
            return {"text": self.HEARD, "model": "speech fixture"}
        at = self.app(transcribe)
        with patch("streamlit.audio_input", return_value=FakeCapture(b"same bytes", "plan.wav", "intent-1")):
            at.run()
            at.button(key="plan_save").click().run()
        at = reload_view(at)
        at.selectbox[0].set_value("david").run()
        open_panel(at, "paper")
        with patch("streamlit.audio_input", return_value=FakeCapture(b"same bytes", "plan.wav", "intent-2")):
            at.run()
            at.button(key="plan_save").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.session_state["episode"].updates), 2)
        self.assertEqual(len(calls), 2)

    def test_failed_speech_and_empty_speech_keep_the_recording_without_adding(self):
        calls = []
        def transcribe(data, suffix):
            calls.append(data)
            if len(calls) == 1:
                raise ValueError("speech fixture unavailable")
            return {"text": "  ", "model": "speech fixture"}
        at = self.app(transcribe)
        with observe_working_hints() as (active, shown):
            with patch("streamlit.audio_input", return_value=FakeCapture(b"retry", "plan.wav", "plan-3")):
                at.run()
                at.button(key="plan_save").click().run()
                self.assertFalse(at.exception)
                self.assertTrue(any("Could not save your spoken plan" in e.value for e in at.error))
                self.assertEqual(active, {})
                self.assertFalse(at.button(key="plan_save").disabled)
                at.button(key="plan_save").click().run()
                self.assertTrue(any("No words were heard" in w.value for w in at.warning))
                self.assertEqual(active, {})
        self.assertEqual(at.session_state["episode"].updates, [])

    def test_ambiguous_spoken_date_stays_pending_instead_of_using_receipt_time(self):
        from episode import event_time
        at = self.app(lambda data, suffix: {"text": "I'll be there on 10/11 afternoon.", "model": "speech fixture"})
        with patch("streamlit.audio_input", return_value=FakeCapture(b"ambiguous", "plan.wav", "plan-ambiguous")):
            at.run()
            at.button(key="plan_save").click().run()
        self.assertFalse(at.exception)
        timing = event_time(at.session_state["episode"], at.session_state["episode"].entries[-1])
        self.assertIsNone(timing["when"])
        self.assertEqual(timing["status"], "pending_confirmation")
        self.assertIn("10/11 afternoon", html.unescape(page(at)))

    def test_extraction_failure_retries_cached_words_without_transcribing_again(self):
        calls = []
        def transcribe(data, suffix):
            calls.append(data)
            return {"text": self.HEARD, "model": "speech fixture"}
        at = self.app(transcribe)
        os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")
        class FlakyExtractor(StubModel):
            attempts = 0
            def chat(extractor, *args, **kwargs):
                extractor.attempts += 1
                if extractor.attempts == 1:
                    raise RuntimeError("extraction fixture unavailable")
                return super().chat(*args, **kwargs)
        at.session_state["extractor"] = llm_extractor(FlakyExtractor({"facts": []}))
        with observe_working_hints() as (active, shown):
            with patch("streamlit.audio_input", return_value=FakeCapture(b"retry extraction", "plan.wav", "retry-extract")):
                at.run()
                at.button(key="plan_save").click().run()
                self.assertFalse(at.exception)
                self.assertEqual(at.session_state["episode"].updates, [])
                self.assertEqual(at.session_state["plan_recording"]["transcript"]["text"], self.HEARD)
                self.assertTrue(at.error)
                self.assertEqual(active, {})
                at.button(key="plan_save").click().run()
                self.assertFalse(at.exception)
                self.assertEqual(active, {})
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(at.session_state["episode"].updates), 1)

    def test_switching_member_discards_the_previous_members_recording(self):
        at = self.app(lambda data, suffix: {"text": self.HEARD, "model": "speech fixture"})
        with patch("streamlit.audio_input", return_value=FakeCapture(b"David only", "plan.wav", "david-draft")):
            at.run()
        self.assertEqual(at.session_state["plan_recording"]["member"], "david")
        at.selectbox[0].set_value("anna").run()
        self.assertFalse(at.exception)
        self.assertNotIn("plan_recording", at.session_state)
        with patch("streamlit.audio_input", return_value=None) as microphone:
            open_panel(at, "paper")
            self.assertTrue(microphone.call_args.kwargs["key"].startswith("plan_audio_anna_"))
            self.assertTrue(at.button(key="plan_save").disabled)
        self.assertEqual(at.session_state["episode"].updates, [])


class TestCameraCapture(unittest.TestCase):
    READING = TestUploads.READING
    app = TestUploads.app
    tearDown = TestUploads.tearDown

    def test_camera_capture_uses_existing_checked_photo_path_and_upload_stays_available(self):
        with patch("streamlit.camera_input", return_value=None) as camera:
            at = self.app()
            self.assertEqual(camera.call_args.args[0], "Take a photo")
        data = own_photo("CAMERA DOCUMENT")
        capture = FakeCapture(data, "camera.jpg", "camera-1")
        with patch("streamlit.camera_input", return_value=capture):
            at.run()
            self.assertFalse(at.exception)
            self.assertTrue(at.file_uploader(key="photo_upload_0"))
            self.assertEqual(at.session_state["photo"]["id"], "camera:camera-1")
            self.assertEqual(self.vision.calls, 0)
            button(at, "Read the text on the photo").click().run()
            self.assertEqual(at.text_area(key="photo_text").value, self.READING)
            self.assertEqual(self.vision.calls, 1)
            for checkbox in ticks(at):
                checkbox.check()
            at.text_input(key="photo_of_text").set_value("Camera medication list").run()
            before = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
            button(at, "Add to the timeline").click().run()
        self.assertFalse(at.exception)
        source = at.session_state["episode"].updates[-1]
        self.assertEqual((source["kind"], source["text"], source["photo_of"]),
                         ("photo", self.READING, "Camera medication list"))
        actual = dt.datetime.fromisoformat(source["at"])
        self.assertGreaterEqual(actual, before)
        self.assertLessEqual(actual, dt.datetime.now(dt.timezone.utc))
        self.assertIn(source["update_id"], at.session_state["photos"])


class TestFamilySpace(unittest.TestCase):
    """The primary caregiver invites the family: everyone's link opens one shared timeline."""

    def open_as(self, sid, member):
        at = AppTest.from_file(PAGE, default_timeout=60)
        at.query_params["family"], at.query_params["as"] = sid, member
        at.run()
        self.assertFalse(at.exception)
        return at

    def test_invite_links_open_one_shared_timeline(self):
        anna = fresh()
        add_story(anna, 2)
        button(anna, "👪 Invite the family").click().run()
        sid = anna.query_params["family"]
        sid = sid[0] if isinstance(sid, list) else sid
        links = [c.value for c in anna.code]
        self.assertEqual(len(links), 4)
        self.assertTrue(all(f"?family={sid}&as=" in x for x in links))
        david = self.open_as(sid, "david")
        self.assertEqual(david.selectbox[0].value, "david")
        self.assertEqual(len(heads(david)), 5)   # two invited sources contain five important events
        note(david, "I land at Heathrow on Wednesday morning and can be at the hospital in the afternoon.")
        anna.run()
        self.assertIn("I land at Heathrow on Wednesday morning", page(anna))   # Anna sees David's news
        self.assertEqual(len(heads(anna)), 6)

    def test_a_link_to_an_ended_space_opens_a_fresh_demo(self):
        at = self.open_as("no-such-space", "mia")
        self.assertNotIn("family", at.query_params)
        self.assertTrue(any("That family link has ended" in t.value for t in at.toast))

class TestRevisionWiring(unittest.TestCase):
    def tearDown(self):
        for key in ("CARERELAY_LLM_BASE_URL", "CARERELAY_LLM_MODEL", "KINDRED_VERIFIER_MODE"):
            os.environ.pop(key, None)

    def test_story_and_typed_upload_use_same_verifier_factory(self):
        at = fresh()   # bootstrap before patching the module's real factory
        from evidence_gate import FactChecker
        from test_episode_revisions import DeterministicVerifier
        verifier = DeterministicVerifier()
        with patch("evidence_gate.checker_from_env", return_value=FactChecker(verifier, "shadow")) as factory:
            at.run(); add_story(at, 1)
            first = at.session_state["episode"].entries[0]
            self.assertTrue(first["evidence_checks"])
            calls = len(verifier.calls)
            os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")
            at.session_state["extractor"] = llm_extractor(StubModel({"facts": [
                {"type": "instruction", "what": "Keep her nil by mouth from midnight",
                 "quote": "Keep her nil by mouth from midnight"}]}))
            at.run(); open_panel(at, "recording")
            at.text_input(key="rec_speaker").set_value("Ward nurse").run()
            at.text_area(key="rec_text").set_value("Keep her nil by mouth from midnight please.").run()
            at.button(key="rec_add").click().run()
            self.assertFalse(at.exception)
            self.assertGreater(len(verifier.calls), calls)
            self.assertGreaterEqual(factory.call_count, 2)
            self.assertTrue(at.session_state["episode"].entries[-1]["evidence_checks"])

    def test_correction_preserves_metadata_and_rebuilds_without_model(self):
        at = fresh(); add_story(at, 2)
        episode = at.session_state["episode"]
        source = next(u for u in episode.updates if u["update_id"] == "u02").copy()
        self.assertIn("No extraction model is connected. Saving corrected words removes the old extracted facts for this update.",
                      [c.value for c in at.caption])
        at.selectbox(key="correction_source").set_value("u02").run()
        at.text_area(key="correction_text_u02_1").set_value("The checked words now contain no extracted facts.").run()
        at.checkbox(key="correction_checked_u02_1").check().run()
        at.button(key="correction_save_u02_1").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(episode.source_revision("u02"), 2)
        changed = next(u for u in episode.updates if u["update_id"] == "u02")
        self.assertEqual((source["at"], source["kind"], source["author"]),
                         (changed["at"], changed["kind"], changed["author"]))
        self.assertEqual(next(e for e in episode.entries if e["update_id"] == "u02")["facts"], [])
        self.assertEqual([t.value for t in at.toast],
                         ["Source words saved. No structured facts were added; the previous facts from this update were removed."])
        self.assertIn("Source words corrected and checked by the family.", page(at))

    def test_gate_error_is_visible_and_raw_source_remains(self):
        at = fresh()
        from evidence_gate import FactChecker
        from test_episode_revisions import DeterministicVerifier
        with patch.dict(os.environ, {"KINDRED_VERIFIER_MODE": "gate"}):
            with patch("evidence_gate.checker_from_env", return_value=FactChecker(DeterministicVerifier(error=True), "gate")):
                at.run(); add_story(at, 1)
                entry = at.session_state["episode"].entries[0]
                self.assertFalse(entry["facts"])
                self.assertTrue(entry["text"])
                self.assertTrue(any("Verification unavailable" in w.value for w in at.warning))
                self.assertTrue(all(c["withhold"] for c in entry["evidence_checks"]))

    def test_correcting_one_line_preserves_other_source_authority(self):
        from episode_qa import sentence_units
        at = fresh(); add_story(at, 1)
        episode = at.session_state["episode"]
        medicine = "Continue Amlodipine 5 mg once a day."
        old_garden = "The ward garden is open after lunch."
        new_garden = "The ward garden is open after breakfast."
        prior_family = "Anna brings clean clothes on Friday."
        facts = [{"type": "medication", "name": "Amlodipine", "status": "continue", "dose": "5 mg", "frequency": "once a day", "quote": medicine},
                 {"type": "event", "what": old_garden, "quote": old_garden},
                 {"type": "family", "who": "Anna", "what": "brings clean clothes on Friday", "quote": prior_family}]
        episode.add_update({"update_id": "authority", "kind": "photo", "at": episode.latest_at(), "author": "anna",
                            "photo_of": "Ward sheet", "text": "\n".join((medicine, old_garden, prior_family)),
                            "reading": {"method": "model", "changed_lines": [prior_family]}}, facts=facts)
        self.assertEqual(episode.meds["amlodipine"]["authority"], "care_team")
        facts[1] = {"type": "event", "what": new_garden, "quote": new_garden}
        os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")
        at.session_state["extractor"] = llm_extractor(StubModel({"facts": facts}))
        at.run()
        at.selectbox(key="correction_source").set_value("authority").run()
        at.text_area(key="correction_text_authority_1").set_value("\n".join((medicine, new_garden, prior_family))).run()
        at.checkbox(key="correction_checked_authority_1").check().run()
        at.button(key="correction_save_authority_1").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(episode.source_revision("authority"), 2)
        self.assertEqual(episode.meds["amlodipine"]["authority"], "care_team")
        entry = next(e for e in episode.entries if e["update_id"] == "authority")
        self.assertEqual(entry["reading"]["changed_lines"], [new_garden, prior_family])
        self.assertIn(old_garden, entry["reading"]["removed_lines"])
        units = {u["text"]: u for u in sentence_units(episode) if u["update_id"] == "authority"}
        self.assertEqual(units[medicine]["authority"], "care_team")
        self.assertEqual(units[new_garden]["authority"], "family")
        self.assertEqual(units[prior_family]["authority"], "family")
        self.assertEqual([t.value for t in at.toast], ["Source updated. Answers and the timeline now use the corrected words."])


class TestFamilyHospitalRecordings(unittest.TestCase):
    def tearDown(self):
        for key in ("CARERELAY_LLM_BASE_URL", "CARERELAY_LLM_MODEL"):
            os.environ.pop(key, None)

    def family_panel(self, heard="She was admitted to hospital."):
        at = fresh()
        at.session_state["transcriber"] = lambda data, suffix: {"text": heard, "model": "Family ASR stub"}
        at.run()
        at.button(key="add_recording").click().run()   # exercise the actual family default
        self.assertFalse(at.exception)
        return at

    def test_self_recording_is_a_family_hospital_event_with_missing_date_explained(self):
        heard = "She was admitted to hospital."
        at = self.family_panel(heard)
        self.assertEqual(at.radio(key="rec_speaker_type").value, "Me / a family member")
        self.assertEqual(at.selectbox(key="rec_family_member").value, "anna")
        self.assertFalse(any((c.key or "").startswith("rec_consent_") for c in at.checkbox))
        self.assertTrue(any("Sharing as Anna" in caption.value for caption in at.caption))
        os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")
        at.session_state["extractor"] = llm_extractor(StubModel({"facts": [{"type": "admitted", "quote": heard}]}))
        at.file_uploader(key="rec_upload_0").set_value(("family.wav", b"fictional recording", "audio/wav")).run()
        button(at, "Write out the recording").click().run()
        for checkbox in ticks(at):
            checkbox.check()
        at.run()
        at.button(key="rec_add").click().run()
        self.assertFalse(at.exception)
        episode = at.session_state["episode"]
        self.assertEqual((episode.updates[-1]["kind"], episode.updates[-1]["speaker_type"], episode.updates[-1]["speaker"]),
                         ("recording", "family", "Anna"))
        self.assertEqual(episode.entries[-1]["authority"], "family")
        self.assertEqual(episode.plans(), [])
        self.assertIn("Admitted to hospital", page(at))
        self.assertIn("Event date/time not stated", page(at))
        self.assertIn("separately from checking the source words", page(at))
        self.assertNotIn("Time to confirm", page(at))

    def test_other_family_and_clinician_recordings_require_their_own_consent(self):
        at = self.family_panel()
        at.selectbox(key="rec_family_member").set_value("david").run()
        name = at.session_state["episode"].members["david"]["name"]
        n = at.session_state["rec_n"]
        self.assertFalse(any(u.key == f"rec_upload_{n}" for u in at.get("file_uploader")))
        at.checkbox(key=f"rec_family_consent_{name}_{n}").check().run()
        self.assertTrue(any(u.key == f"rec_upload_{n}" for u in at.get("file_uploader")))
        at.radio(key="rec_speaker_type").set_value("Doctor / nurse").run()
        n = at.session_state["rec_n"]
        self.assertFalse(at.checkbox(key=f"rec_consent_{n}").value)
        self.assertFalse(any(u.key == f"rec_upload_{n}" for u in at.get("file_uploader")))
        self.assertTrue(any(c.key == "rec_speaker" for c in at.text_input))
        at.checkbox(key=f"rec_consent_{n}").check().run()
        self.assertTrue(any(u.key == f"rec_upload_{n}" for u in at.get("file_uploader")))

    def test_changing_speaker_explicitly_clears_the_visible_typed_draft_in_both_directions(self):
        at = self.family_panel()
        for choice, words in (("Doctor / nurse", "Fictional unsaved family draft."),
                              ("Me / a family member", "Fictional unsaved clinician draft.")):
            with self.subTest(choice=choice):
                at.text_area(key="rec_text").set_value(words).run()
                self.assertEqual(at.text_area(key="rec_text").value, words)
                before = state_get(at, "rec_n", 0)
                at.radio(key="rec_speaker_type").set_value(choice).run()
                self.assertFalse(at.exception)
                self.assertEqual(at.radio(key="rec_speaker_type").value, choice)
                self.assertEqual(at.text_area(key="rec_text").value, "")
                self.assertEqual(at.session_state["rec_text"], "")
                self.assertEqual(at.session_state["rec_n"], before + 1)
                self.assertTrue(at.button(key="rec_add").disabled)
                self.assertEqual(at.session_state["episode"].updates, [])

    def test_checked_recording_and_pending_add_do_not_follow_a_changed_speaker(self):
        for origin in ("clinician", "other_family", "renamed_clinician"):
            with self.subTest(origin=origin):
                captures = {}
                with patch("streamlit.audio_input", side_effect=lambda label, **kw: captures.get(kw["key"])):
                    at = self.family_panel("Give one tablet twice daily.")
                    if origin in ("clinician", "renamed_clinician"):
                        at.radio(key="rec_speaker_type").set_value("Doctor / nurse").run()
                        at.text_input(key="rec_speaker").set_value("Ward nurse").run()
                        n = at.session_state["rec_n"]
                        consent = f"rec_consent_{n}"
                    else:
                        at.selectbox(key="rec_family_member").set_value("david").run()
                        n = at.session_state["rec_n"]
                        consent = f"rec_family_consent_{at.session_state['episode'].members['david']['name']}_{n}"
                    at.checkbox(key=consent).check().run()
                    captures[f"rec_audio_{n}"] = FakeCapture(b"old fictional voice", "old.wav", "old-voice")
                    at.run()
                    button(at, "Write out the recording").click().run()
                    self.assertTrue(ticks(at))
                    for checkbox in ticks(at):
                        checkbox.check()
                    at.run()
                    self.assertFalse(at.button(key="rec_add").disabled)
                    old_draft = at.session_state["rec"]
                    old_draft["add_started"] = True
                    if origin == "renamed_clinician":
                        at.text_input(key="rec_speaker").set_value("Orthopaedic surgeon").run()
                    elif origin == "clinician":
                        at.radio(key="rec_speaker_type").set_value("Me / a family member").run()
                    else:
                        at.selectbox(key="rec_family_member").set_value("anna").run()
                    self.assertFalse(at.exception)
                    self.assertEqual(at.session_state["rec_n"], n + 1)
                    self.assertIsNot(at.session_state["rec"], old_draft)
                    self.assertNotIn("bytes", at.session_state["rec"])
                    self.assertNotIn("add_started", at.session_state["rec"])
                    self.assertEqual(at.text_area(key="rec_text").value, "")
                    self.assertEqual(ticks(at), [])
                    self.assertTrue(at.button(key="rec_add").disabled)
                    self.assertEqual(at.session_state["episode"].updates, [])
                    if origin == "renamed_clinician":
                        self.assertFalse(at.checkbox(key=f"rec_consent_{n + 1}").value)

    def test_a_new_self_recording_cannot_reuse_an_earlier_clinician_consent(self):
        captures = {}
        with patch("streamlit.audio_input", side_effect=lambda label, **kw: captures.get(kw["key"])):
            at = self.family_panel()
            at.radio(key="rec_speaker_type").set_value("Doctor / nurse").run()
            at.text_input(key="rec_speaker").set_value("Ward nurse").run()
            consent_n = at.session_state["rec_n"]
            at.checkbox(key=f"rec_consent_{consent_n}").check().run()
            at.radio(key="rec_speaker_type").set_value("Me / a family member").run()
            own_n = at.session_state["rec_n"]
            captures[f"rec_audio_{own_n}"] = FakeCapture(b"my fictional voice", "me.wav", "my-voice")
            at.run()
            button(at, "Write out the recording").click().run()
            self.assertTrue(at.session_state["rec"].get("bytes"))
            at.radio(key="rec_speaker_type").set_value("Doctor / nurse").run()
            new_n = at.session_state["rec_n"]
            self.assertGreater(new_n, consent_n)
            self.assertFalse(at.checkbox(key=f"rec_consent_{new_n}").value)
            self.assertFalse(any(u.key == f"rec_upload_{new_n}" for u in at.get("file_uploader")))
            self.assertNotIn("bytes", at.session_state["rec"])
            self.assertEqual(at.text_area(key="rec_text").value, "")

    def test_an_unbound_legacy_clinician_draft_survives_the_first_render(self):
        at = fresh()
        draft = {"bytes": b"legacy fictional voice", "id": "legacy-voice", "suffix": ".wav",
                 "transcript": {"text": "She is awake in hospital.", "model": "Legacy ASR"}, "shown": True}
        at.session_state["rec"] = draft
        at.session_state["rec_text"] = "She is awake in hospital."
        at.session_state["rec_speaker"] = "Ward nurse"
        at.session_state["transcriber"] = lambda *args: {"text": "unused"}
        at.session_state["adding"], at.session_state["adding_as"] = "recording", "anna"
        with patch("streamlit.audio_input", return_value=None):
            at.run()
            self.assertFalse(at.exception)
            self.assertEqual(at.radio(key="rec_speaker_type").value, "Doctor / nurse")
            self.assertIs(at.session_state["rec"], draft)
            self.assertEqual(draft["bytes"], b"legacy fictional voice")
            self.assertEqual(at.text_area(key="rec_text").value, "She is awake in hospital.")
            self.assertTrue(at.button(key="rec_add").disabled)   # retained bytes still need permission
            at.run()
            self.assertIs(at.session_state["rec"], draft)

    def test_a_preserved_legacy_recording_can_still_be_removed_once_its_widget_returns(self):
        at = fresh()
        draft = {"bytes": b"legacy fictional voice", "id": "legacy-voice", "suffix": ".wav",
                 "transcript": {"text": "She is awake in hospital.", "model": "Legacy ASR"}, "shown": True}
        at.session_state["rec"] = draft
        at.session_state["rec_seen"] = ["legacy-voice"]
        at.session_state["rec_text"] = "She is awake in hospital."
        at.session_state["rec_speaker"] = "Ward nurse"
        at.session_state["transcriber"] = lambda *args: {"text": "unused"}
        at.session_state["adding"], at.session_state["adding_as"] = "recording", "anna"
        with patch("streamlit.audio_input", return_value=None) as capture:
            at.run()
            self.assertTrue(draft["preserve_legacy_capture"])
            capture.return_value = FakeCapture(draft["bytes"], "legacy.wav", "legacy-voice")
            at.checkbox(key="rec_consent_0").check().run()
            self.assertNotIn("preserve_legacy_capture", draft)
            capture.return_value = None
            at.run()
            self.assertFalse(at.exception)
            self.assertNotIn("bytes", at.session_state["rec"])
            self.assertEqual(at.text_area(key="rec_text").value, "")
            self.assertTrue(at.button(key="rec_add").disabled)

    def test_same_named_family_members_still_start_distinct_drafts(self):
        at = self.family_panel()
        at.session_state["episode"].members["david"]["name"] = "Anna"
        at.run()
        at.text_area(key="rec_text").set_value("She is awake in hospital.").run()
        before = state_get(at, "rec_n", 0)
        at.selectbox(key="rec_family_member").set_value("david").run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["rec_n"], before + 1)
        self.assertEqual(at.selectbox(key="rec_family_member").value, "david")
        self.assertEqual(at.text_area(key="rec_text").value, "")

    def test_existing_me_recording_can_be_explicitly_corrected_to_family_without_changing_words(self):
        at = fresh()
        episode = at.session_state["episode"]
        text = "She was admitted to hospital."
        episode.add_update({"update_id": "legacy", "at": "2026-10-17T09:00:00+01:00", "kind": "recording",
                            "speaker": "me", "author": "anna", "text": text}, facts=[])
        at.run()
        self.assertEqual(episode.entries[-1]["authority"], "care_team")
        at.radio(key="correction_legacy_1_speaker_type").set_value("Me / a family member").run()
        at.checkbox(key="correction_checked_legacy_1").check().run()
        self.assertFalse(at.button(key="correction_save_legacy_1").disabled)
        at.button(key="correction_save_legacy_1").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(episode.source_revision("legacy"), 2)
        source = episode.updates[-1]
        self.assertEqual((source["text"], source["speaker_type"], source["speaker"]), (text, "family", "Anna"))
        self.assertEqual(episode.entries[-1]["authority"], "family")
        self.assertEqual(source["reading"], None)   # no unchanged words labelled as hand corrections


class TestExaminationTopicOnPage(unittest.TestCase):
    def test_repeated_examination_sources_share_a_topic_and_links_without_losing_originals(self):
        at = fresh()
        episode = at.session_state["episode"]
        sources = [
            ("vague", "She needs some examinations", [
                {"type": "procedure_planned", "what": "some examinations", "quote": "She needs some examinations"}]),
            ("specific", "She needs X-ray and MRI. An examination is planned for tomorrow", [
                {"type": "procedure_planned", "what": "X-ray and MRI", "quote": "She needs X-ray and MRI"},
                {"type": "procedure_planned", "what": "examination", "quote": "An examination is planned for tomorrow"}]),
        ]
        for uid, text, facts in sources:
            episode.add_update({"update_id": uid, "kind": "recording", "author": "anna", "speaker": "Doctor",
                                "at": "2026-10-17T10:00:00+01:00", "text": text}, facts=facts)
        journal = episode.events
        at.run()
        self.assertFalse(at.exception)
        rendered = page(at)
        self.assertEqual(rendered.count('class="cr-test-topic"'), 1)
        self.assertEqual(rendered.count('href="#cr-tests-1"'), 2)  # Right now and What's next
        self.assertIn("Tests and examinations · 2 sources", rendered)
        self.assertIn("<b>X-ray and MRI</b> · Event date/time not stated", rendered)
        self.assertIn("sources do not link that date to the named tests", rendered)
        archive = next(value for value in texts(at) if 'cr-source-archive' in value)
        self.assertIn("She needs some examinations", archive)
        self.assertIn("An examination is planned for tomorrow", archive)
        self.assertEqual(episode.events, journal)
        self.assertEqual(len(episode.updates), 2)


class TestSavedTimelineStore(unittest.TestCase):
    def test_saved_timelines_go_to_a_temporary_store_not_the_home_store(self):
        state = os.environ.get("CARERELAY_STATE_DIR")
        self.assertTrue(state, "the page must not fall back to the developer's ~/.kindredrelay store")
        self.assertNotEqual(Path(state).resolve(), (Path.home() / ".kindredrelay").resolve())
        path = fresh().session_state["persistent_private"].store.path
        self.assertTrue(path.is_relative_to(Path(state).resolve()), path)
        self.assertTrue(path.is_file())


if __name__ == "__main__":
    # Keep workstation credentials out of every AppTest run in this lifecycle.
    # Clearing process env alone does not prevent Streamlit from loading secrets.
    with patch_config_options({"secrets.files": []}):
        unittest.main(verbosity=1)
