#!/usr/bin/env python3
"""Tests of the family timeline's HTML (agent/timeline_html.py) over the demo story: which entries are key events, notes
or ward references, the "you last looked here" line, days in the viewer's zone, escaping, the medicines list, the moved
headline, photos and the right-now card. Stdlib only:
  python agent/test_timeline_html.py
"""
from __future__ import annotations

import html
import copy
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from episode import Episode, load_scenario  # noqa: E402
import timeline_html as T  # noqa: E402

SCENARIO = HERE.parent / "care_cases" / "episode_hip_fracture.json"
TWO_ANSWERS = ("u07b", "u07c")   # the story's two-different-answers pair; the older tests replay the story without it


def without_two_answers(scenario: dict) -> dict:
    return {**scenario, "updates": [u for u in scenario["updates"] if u["update_id"] not in TWO_ANSWERS]}

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


def story(n: int = 99, read_after: dict | None = None) -> Episode:
    """The demo story's first n updates; read_after={member: k} marks the timeline read for that member after k updates."""
    ep = Episode(without_two_answers(load_scenario(SCENARIO)))
    for i in range(n):
        nxt = ep.next_scripted()
        if not nxt:
            break
        ep.add_update(nxt)
        for mid, k in (read_after or {}).items():
            if k == i + 1:
                ep.mark_read(mid)
    return ep


def tz(ep: Episode, mid: str) -> str:
    return ep.members[mid]["timezone"]


def entries(out: str) -> list[tuple[str, str]]:
    """(class, headline) of each entry, in order."""
    return [(c, html.unescape(h)) for c, h in re.findall(r'class="cr-ev (cr-key|cr-note|cr-ref)" data-headline="([^"]*)"', out)]


def block(out: str, headline: str) -> str:
    """The markup of one entry."""
    start = out.index(f'data-headline="{T.esc(headline)}"')
    nxt = re.search(r'class="cr-ev |class="cr-day"|class="cr-seen"', out[start + 1:])
    return out[start:start + 1 + nxt.start()] if nxt else out[start:]


class TestKinds(unittest.TestCase):
    def setUp(self):
        self.ep = story()
        self.out = T.timeline_html(self.ep, "anna", tz(self.ep, "anna"))

    def test_care_team_events_are_key_family_notes_and_ward_facts_are_quiet(self):
        kinds = dict((h, c) for c, h in entries(self.out))
        self.assertEqual(kinds["Admitted to hospital"], "cr-key")
        self.assertEqual(kinds["Half hip replacement done"], "cr-key")
        self.assertEqual(kinds["Going home moved: Fri 23 Oct -> Sat 24 Oct morning"], "cr-key")
        self.assertEqual(kinds["Medication list updated: 0 new, 1 stopped, 0 continued or changed"], "cr-key")
        self.assertEqual(kinds["Discharged from hospital"], "cr-key")
        self.assertEqual(kinds["At St Mary's Hospital, A&E"], "cr-note")   # a family report
        self.assertTrue(any(h.startswith("Mum is home and settled.") and c == "cr-note" for h, c in kinds.items()))
        self.assertNotIn("Visiting hours 11:00 - 13:00 and 17:00 - 20:00; maximum 2 visitors per bed", kinds)
        self.assertNotIn("cr-ref", kinds.values())

    def test_a_changed_plan_is_amber_and_says_what_it_was(self):
        b = block(self.out, "Going home moved: Fri 23 Oct -> Sat 24 Oct morning")
        self.assertIn(f"background:{T.AMBER}", b)
        self.assertIn('Going home moved to <span class="cr-amber">Sat 24 Oct morning</span>', b)
        self.assertIn('<s class="cr-quiet">Fri 23 Oct</s> → Sat 24 Oct morning', b)

    def test_the_body_does_not_repeat_the_headline(self):
        b = block(self.out, "Moved to St Mary's Hospital, Orthopaedic ward 5B, bed 12")
        body = b[b.index('class="cr-body"'):b.index('class="cr-srcrow"')]
        self.assertNotIn("Orthopaedic ward 5B", body)
        self.assertNotIn("Admitted to hospital", body)
        self.assertIn("The doctor said: fracture of the left hip", body)

    def test_medicines_are_listed_by_status(self):
        b = block(self.out, "Medication list updated: 0 new, 1 stopped, 0 continued or changed")
        self.assertIn('<b class="cr-stop">Stopped</b> · <s>Ibuprofen</s>', b)
        side = T.side_html(self.ep, self.ep.status(), "Europe/London", "anna")
        self.assertIn("Paracetamol 1 g four times a day as needed for pain", side)
        self.assertIn("Amlodipine 5 mg once a day", side)

    def test_people_and_the_care_team_are_told_apart(self):
        colors = T.colors_of(self.ep)
        self.assertEqual(len(set(colors.values())), len(colors))
        self.assertIn(f'<b style="color:{colors["david"]}">David</b>', self.out)
        self.assertIn('<span class="cr-care">', block(self.out, "Half hip replacement done"))   # the clinician, by icon


class TestReadLine(unittest.TestCase):
    def test_read_boundary_is_omitted_when_event_dates_interleave_new_and_seen_sources(self):
        ep = story(read_after={"mia": 6})
        out = T.timeline_html(ep, "mia", tz(ep, "mia"))
        self.assertEqual(out.count('class="cr-seen"'), 0)
        self.assertIn('class="cr-new"', out)
        self.assertNotIn("You last looked here ·", out)

    def test_no_line_without_a_read_or_without_anything_new(self):
        ep = story()
        self.assertNotIn('class="cr-seen"', T.timeline_html(ep, "mia", tz(ep, "mia")))   # never marked read: all new
        ep.mark_read("mia")
        self.assertNotIn('class="cr-seen"', T.timeline_html(ep, "mia", tz(ep, "mia")))   # nothing new


class TestZonesAndText(unittest.TestCase):
    def day_of(self, out: str, headline: str) -> str:
        start = out.index(f'data-headline="{T.esc(headline)}"')
        return re.findall(r'<div class="cr-day">([^<]*)</div>', out[:start])[-1]

    def test_date_only_family_event_is_not_shifted_to_a_viewers_date(self):
        ep = story(5)
        ep.revise_update("u04", {"text": "I'll arrive on 2026-10-21 morning"}, expected_revision=1,
                         request_id="dated-family-plan", facts=[])
        david_note = "I'll arrive on 2026-10-21 morning — Date stated: Wed 21 Oct 2026 · morning"
        self.assertEqual(self.day_of(T.timeline_html(ep, "anna", tz(ep, "anna")), david_note), "Wednesday 21 Oct 2026")
        self.assertEqual(self.day_of(T.timeline_html(ep, "mia", tz(ep, "mia")), david_note), "Wednesday 21 Oct 2026")

    def test_update_text_is_escaped_and_stays_one_html_block(self):
        ep = story(1)
        ep.add_update({"update_id": "c01", "at": ep.latest_at(), "kind": "note", "author": "anna",
                       "text": "<script>alert(1)</script> & \"x\"\n\nsecond paragraph\n    indented"}, facts=[])
        out = T.source_archive_html(ep)
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;x&quot;", out)
        self.assertNotIn("\n", out)   # a blank line inside st.markdown's HTML would end the HTML block

    def test_photos_are_inlined_with_their_type(self):
        ep = story(8)
        png = T.source_archive_html(ep, photo_of=lambda e: PNG if e.get("image") else None)
        self.assertIn('src="data:image/png;base64,', png)
        jpg = T.source_archive_html(ep, photo_of=lambda e: JPEG if e.get("image") else None)
        self.assertIn('src="data:image/jpeg;base64,', jpg)
        self.assertNotIn("<img", T.source_archive_html(ep))

    def test_empty(self):
        ep = story(0)
        self.assertIn("Nothing yet", T.timeline_html(ep, "anna", tz(ep, "anna")))


class TestCards(unittest.TestCase):
    def test_right_now_shows_the_change(self):
        ep = story(7)
        s = ep.status(tz=tz(ep, "mia"), now=ep.latest_at())
        hero = T.hero_html(ep, s, tz(ep, "mia"), ep.members["mia"])
        # This fixture never states the admission date, so receipt order cannot
        # establish that the completed operation belongs to the current stay.
        self.assertIn("Current patient status needs confirmation", hero)
        self.assertNotIn("Recovering after hip surgery", hero)
        self.assertIn('<div class="cr-fact cr-chg"><span class="cr-fact-label">Going home</span>', hero)
        self.assertIn("Changed · was <s>Fri 23 Oct</s>", hero)
        self.assertIn("Times in Melbourne time", hero)
        side = T.side_html(ep, s, tz(ep, "mia"), "mia")
        ward = side[side.index('id="cr-ward"'):]
        self.assertIn("Hospital's local time (London)", ward)
        self.assertIn("weekdays 8:30", ward)
        self.assertIn('<a href="tel:02079460123">', ward)
        self.assertIn("Mia · granddaughter (you), Melbourne", side)

    def test_after_discharge_the_ward_is_gone_and_nothing_points_to_it(self):
        ep = story()
        s = ep.status(tz=tz(ep, "anna"), now=ep.latest_at())
        self.assertTrue(T.left_hospital(s))
        self.assertIn("Discharged", T.hero_html(ep, s, tz(ep, "anna"), ep.members["anna"]))
        self.assertIn("Come back straight away", T.hero_html(ep, s, tz(ep, "anna"), ep.members["anna"]))
        self.assertNotIn('id="cr-ward"', T.side_html(ep, s, tz(ep, "anna"), "anna"))
        out = T.timeline_html(ep, "anna", tz(ep, "anna"), ward_shown=False)
        self.assertNotIn('href="#cr-ward"', out)
        self.assertNotIn("photographed the ward notice board", out)
        archive = T.source_archive_html(ep)
        self.assertIn("Visiting hours: 11:00 - 13:00 and 17:00 - 20:00", archive)


def add(ep: Episode, uid: str, kind: str, text: str, facts: list, author: str = "anna", **extra) -> dict:
    return ep.add_update({"update_id": uid, "at": ep.latest_at(), "kind": kind, "author": author, "text": text, **extra}, facts=facts)


class TestReviewFindings(unittest.TestCase):
    """One test per confirmed finding of the review of design A (2026-10-15)."""

    def test_line_breaks_in_facts_never_reach_the_html(self):
        ep = story(3)
        text = "Before she goes home:\n\n    Keep the dressing dry for 2 weeks.\n    No baths."
        e = add(ep, "c01", "recording", text, [{"type": "instruction", "what": "Before she goes home:\n\n    Keep the dressing dry",
                                                "quote": "Before she goes home:\n\n    Keep the dressing dry for 2 weeks."}], speaker="Ward nurse")
        self.assertEqual(len(e["facts"]), 1)   # the grounding check lets it through
        for mid in ("anna", "mia"):
            out = T.timeline_html(ep, mid, tz(ep, mid))
            s = ep.status(tz=tz(ep, mid), now=ep.latest_at())
            for part in (out, T.hero_html(ep, s, tz(ep, mid), ep.members[mid]), T.side_html(ep, s, tz(ep, mid), mid)):
                self.assertNotIn("\n", part)
            self.assertIn(T.lines_br(text), T.source_archive_html(ep))

    def test_only_a_plain_phone_number_is_a_tel_link(self):
        self.assertEqual(T.phone_link("020 7946 0123"), '<a href="tel:02079460123">020 7946 0123</a>')
        self.assertEqual(T.phone_link("+44 (0)20 7946 0123"), '<a href="tel:+442079460123">+44 (0)20 7946 0123</a>')
        self.assertEqual(T.phone_link("020 7946 0123 ext. 4521"), "020 7946 0123 ext. 4521")
        self.assertEqual(T.phone_link("020 7946 0123 (24 hours)"), "020 7946 0123 (24 hours)")

    def test_contact_values_are_escaped_once(self):
        ep = story(2)
        add(ep, "c01", "photo", "Visiting hours: Mon-Fri 2-4pm & weekends 1-5pm", photo_of="Leaflet",
            facts=[{"type": "contact", "what": "Visiting hours", "value": "Mon-Fri 2-4pm & weekends 1-5pm",
                    "quote": "Visiting hours: Mon-Fri 2-4pm & weekends 1-5pm"}])
        side = T.side_html(ep, ep.status(tz=tz(ep, "anna")), tz(ep, "anna"), "anna")
        self.assertIn("Mon-Fri 2-4pm &amp; weekends 1-5pm", side)
        self.assertNotIn("&amp;amp;", side)

    def test_a_repeated_plan_is_not_a_change(self):
        ep = story(7)
        add(ep, "c01", "recording", "Going home is still planned for Saturday morning.", speaker="Ward nurse",
            facts=[{"type": "expected_discharge", "when_text": "Saturday morning", "when": "2026-10-24",
                    "quote": "Going home is still planned for Saturday morning"}])
        s = ep.status(tz=tz(ep, "anna"), now=ep.latest_at())
        self.assertEqual((s["expected_discharge"]["short"], s["expected_discharge"]["was"]), ("Sat 24 Oct morning", "Fri 23 Oct"))
        hero = T.hero_html(ep, s, tz(ep, "anna"), ep.members["anna"])
        self.assertNotIn("was <s>Sat 24 Oct morning</s>", hero)

    def test_was_is_never_a_family_report(self):
        ep = story(5)   # the care team: Friday, if she walks safely
        add(ep, "c01", "note", "David thinks she'll be home Thursday.", author="david",
            facts=[{"type": "expected_discharge", "when_text": "Thursday", "when": "2026-10-22", "quote": "she'll be home Thursday"}])
        s = ep.status(tz=tz(ep, "anna"))
        self.assertNotEqual(s["expected_discharge"]["was"], "Thu 22 Oct")
        ep2 = Episode(without_two_answers(load_scenario(SCENARIO)))
        ep2.add_update(ep2.next_scripted())
        add(ep2, "c01", "note", "She should be home Thursday.", facts=[{"type": "expected_discharge", "when_text": "Thursday",
                                                                         "when": "2026-10-22", "quote": "She should be home Thursday"}])
        add(ep2, "c02", "recording", "She can go home on Saturday.", speaker="Surgeon", facts=[
            {"type": "expected_discharge", "when_text": "Saturday", "when": "2026-10-24", "quote": "She can go home on Saturday"}])
        self.assertIsNone(ep2.status()["expected_discharge"]["was"])   # Thursday was only ever a family report

    def test_the_card_keeps_a_condition_and_says_whose_date(self):
        ep = story(5)
        s = ep.status(tz=tz(ep, "mia"), now=ep.latest_at())
        hero = T.hero_html(ep, s, tz(ep, "mia"), ep.members["mia"])
        self.assertIn("Fri 23 Oct (if she is walking safely with the frame)", hero)
        self.assertIn("the hospital&#x27;s date", hero.replace("the hospital's date", "the hospital&#x27;s date"))
        ep = story(9)
        s = ep.status(tz=tz(ep, "mia"), now=ep.latest_at())
        hero = T.hero_html(ep, s, tz(ep, "mia"), ep.members["mia"])
        self.assertIn("District nurse wound check: Tue 27 Oct, at home</span><span class=\"cr-fact-note\">the hospital's date", hero)

    def test_a_family_reported_discharge_shows_as_one(self):
        ep = story(1)   # only the family's location so far, so a family discharge is taken (flagged)
        add(ep, "c01", "recording", "She can go home on Friday.", speaker="Emergency doctor", facts=[
            {"type": "expected_discharge", "when_text": "Friday", "when": "2026-10-23", "quote": "She can go home on Friday"}])
        add(ep, "c02", "note", "She was discharged and is back home now.",
            facts=[{"type": "discharged", "quote": "She was discharged and is back home now"}])
        s = ep.status(tz=tz(ep, "anna"), now=ep.latest_at())
        self.assertTrue(s["discharged"]["unconfirmed"])
        hero = T.hero_html(ep, s, tz(ep, "anna"), ep.members["anna"])
        self.assertIn("Discharged", hero)
        self.assertIn("reported by family, not confirmed", hero)
        self.assertNotIn(">Going home<", hero)

    def test_ward_hours_say_hospital_time_to_a_remote_viewer(self):
        ep = story(3)
        s = ep.status(tz=tz(ep, "mia"), now=ep.latest_at())
        side = T.side_html(ep, s, tz(ep, "mia"), "mia")
        self.assertIn("Hospital's local time (London)", side)
        self.assertIn("maximum 2 visitors per bed", side)
        ep = story(2)
        add(ep, "c01", "recording", "She moves to ward 6. Visiting there is 14:00 - 16:00.", speaker="Ward nurse", facts=[
            {"type": "location", "unit": "ward 6", "quote": "She moves to ward 6"},
            {"type": "visiting", "hours": "14:00 - 16:00", "quote": "Visiting there is 14:00 - 16:00"}])
        side = T.side_html(ep, ep.status(tz=tz(ep, "mia")), tz(ep, "mia"), "mia")
        self.assertIn("14:00 - 16:00", side)
        self.assertIn("Hospital's local time (London)", side)

    def test_a_note_keeps_every_fact_with_its_own_badge(self):
        ep = story(7)
        add(ep, "c01", "note", "Walked to the window with the frame. Home Friday, I think.", facts=[
            {"type": "event", "what": "Walked to the window with the frame", "quote": "Walked to the window with the frame"},
            {"type": "expected_discharge", "when_text": "Friday", "when": "2026-10-23", "quote": "Home Friday, I think"}])
        b = block(T.timeline_html(ep, "anna", tz(ep, "anna")), "Walked to the window with the frame")
        row = b[b.index('class="cr-rowtext"'):b.index("<details")]
        self.assertNotIn("Expected to go home", row)   # a separate event date has its own row
        self.assertNotRegex(row, r"frame <span class=\"cr-badge")   # the badge is on the Friday claim, not on the walk
        out = T.timeline_html(ep, "anna", tz(ep, "anna"))
        claim = next(h for _, h in entries(out) if h.startswith("Family reports: Expected to go home: Fri 23 Oct"))
        self.assertIn("the care team said otherwise", block(out, claim))
        story_out = T.timeline_html(story(), "anna", "Europe/London")
        self.assertIn("At St Mary&#x27;s Hospital, A&amp;E", story_out)
        self.assertIn("Fell at home and could not stand up", story_out)

    def test_disputed_ward_hours_are_not_said_to_be_under_visiting(self):
        ep = story(3)
        add(ep, "c01", "note", "Visiting hours are 14:00 - 16:00 now.", author="david",
            facts=[{"type": "visiting", "hours": "14:00 - 16:00", "quote": "Visiting hours are 14:00 - 16:00"}])
        out = T.timeline_html(ep, "anna", tz(ep, "anna"))
        kinds = dict((h, c) for c, h in entries(out))
        self.assertFalse(any("14:00 - 16:00" in h for h in kinds))
        self.assertIn("Visiting hours are 14:00 - 16:00 now.", T.source_archive_html(ep))

    def test_what_was_checked_is_said(self):
        ep = story(2)
        e = add(ep, "c01", "recording", "Keep the leg moving.", speaker="Ward nurse", facts=[],
                reading={"method": "asr", "model": "Whisper stub", "confirmed_lines": 0, "changed_lines": []})
        ep2 = story(2)
        add(ep2, "c01", "recording", "She can go home on Friday.", speaker="Ward nurse", facts=[
            {"type": "expected_discharge", "when_text": "Friday", "when": "2026-10-23", "quote": "She can go home on Friday"}],
            reading={"method": "asr", "model": "Whisper stub", "confirmed_lines": 0, "changed_lines": []})
        out = T.timeline_html(ep2, "anna", "Europe/London")
        self.assertIn("recorded by <b style=\"color:var(--cr-p0,#0F766E)\">Anna</b> · written out</span>", out)
        self.assertNotIn("checked line by line", out)

    def test_hand_changed_lines_of_a_recording_without_facts_are_the_familys(self):
        ep = story(2)
        add(ep, "c01", "recording", "She can go home on Saturday.\nKeep the leg moving.", speaker="Ward nurse", facts=[],
            reading={"method": "asr", "model": "Whisper stub", "confirmed_lines": 0,
                     "changed_lines": ["She can go home on Saturday."]})
        row = T.source_archive_html(ep)
        self.assertIn("Keep the leg moving.", row)
        self.assertIn("changed by hand, so shown as reported by family: “She can go home on Saturday.”", row)
        self.assertNotIn("“She can go home on Saturday. Keep", row)


class TestAnswerChat(unittest.TestCase):
    def test_the_answer_is_a_short_chat_and_stays_one_html_block(self):
        import episode_qa as Q
        ep = story(7)
        ep.add_update({"update_id": "c01", "at": ep.latest_at(), "kind": "note", "author": "mia",
                       "text": "Nan says <b>she</b> walked\n\nto the window."}, facts=[])
        r = {**Q.episode_answerer(None)(ep, "Did she <walk> to the window?\n", "mia"), "asked_by": "mia"}   # as the page keeps it
        out = T.answer_html(ep, r, tz(ep, "mia"), "david")
        self.assertNotIn("\n", out)
        self.assertIn('<div class="cr-bubble-me">Did she &lt;walk&gt; to the window?</div><span class="cr-me-who">Mia asked</span>', out)
        self.assertIn("&lt;b&gt;she&lt;/b&gt;", out)
        self.assertRegex(out, r'<li class="cr-qa-fam"><span class="cr-qa-av" style="background:var\(--cr-p2,#[0-9A-F]{6}\)">M</span>')   # Mia's initial
        self.assertIn(f"{T.PRODUCT} picked these sentences by matching your words.", out)
        none = Q.episode_answerer(None)(story(3), "Will she need a wheelchair?", "mia")
        out = T.answer_html(story(3), none, "Europe/London", "mia")
        self.assertIn("The updates don&#x27;t mention this yet.", out)
        self.assertIn("You can save it for the doctor below", out)
        self.assertIn('<span class="cr-me-who">You asked</span>', out)


class TestHello(unittest.TestCase):
    def test_the_greeting_follows_the_viewers_clock(self):
        ep = story(10)   # the newest update: Sat 24 Oct 18:00 in London
        self.assertIn("Good evening, Anna", T.hello_html(ep, ep.members["anna"], "Europe/London", ep.latest_at()))
        self.assertIn("Good afternoon, David", T.hello_html(ep, ep.members["david"], "America/Toronto", ep.latest_at()))   # 13:00
        self.assertIn("Hello, Mia", T.hello_html(ep, ep.members["mia"], "Australia/Melbourne", ep.latest_at()))   # 04:00
        ep = story(2)   # Mon 19 Oct 11:15 in London
        out = T.hello_html(ep, {**ep.members["anna"], "name": "<Anna>"}, "Europe/London", ep.latest_at())
        self.assertIn("Good morning, &lt;Anna&gt;", out)
        self.assertIn("What would you like to do for Elena today?", out)
        self.assertNotIn("\n", out)
        self.assertRegex(T.hello_html(story(0), ep.members["anna"], "Europe/London", None),   # no updates yet: the clock now
                         r"(Good (morning|afternoon|evening)|Hello), Anna")


class TestTextSize(unittest.TestCase):
    def test_every_font_size_scales_with_the_text_size(self):
        import re as _re
        page = (HERE.parent / "ui" / "pages" / "1_Family_timeline.py").read_text()
        for name, css in (("timeline_html.CSS", T.CSS), ("the page", page)):
            self.assertEqual(_re.findall(r"font-size:\s*\d+(?:\.\d+)?px", css), [], name)   # a fixed size would not grow



class TestTwoAnswers(unittest.TestCase):
    def test_the_card_shows_both_answers_and_the_question_says_who_added_it(self):
        ep = Episode(load_scenario(SCENARIO))
        for u in ep.scripted():
            ep.add_update(u)
            if u["update_id"] == "u07b":
                break
        out = T.hero_html(ep, ep.status("Europe/London"), "Europe/London", ep.members["anna"])
        self.assertIn("cr-conflict", out)
        self.assertIn("Sat 24 Oct morning or Fri 23 Oct?", out)
        self.assertIn("Going home is now planned for Saturday morning", out)
        self.assertIn("You can go home today, once the pharmacy has your medicines ready", out)
        q = T.question_html(ep, ep.questions[0], "Europe/London")
        self.assertIn("added automatically", q)
        self.assertNotIn("asked by", q)

class TestSharedPlanTiming(unittest.TestCase):
    RECEIVED = "2026-10-19T08:00:00+01:00"

    def episode(self, text="I'll be there on 10/20 afternoon", at=None, facts=None):
        ep = Episode(load_scenario(SCENARIO))
        ep.add_update({"update_id": "c01", "at": at or self.RECEIVED, "kind": "note", "author": "anna",
                       "topic": "plan", "text": text}, facts=facts or [])
        return ep

    def surfaces(self, ep, zone):
        s = ep.status(zone)
        return (T.timeline_html(ep, "anna", zone), T.hero_html(ep, s, zone, ep.members["anna"]),
                T.side_html(ep, s, zone, "anna"))

    def test_existing_generic_extraction_cannot_hide_the_stated_arrival(self):
        text = "I'll be there on 10/20 afternoon"
        ep = self.episode(text, facts=[{"type": "event", "what": "family member will be there", "quote": text}])
        before = ep.to_snapshot()
        for zone in ("Europe/London", "America/Los_Angeles", "Australia/Melbourne"):
            for surface in self.surfaces(ep, zone):
                with self.subTest(zone=zone, surface=surface[:50]):
                    visible = html.unescape(re.sub(r"<details\b.*?</details>", "", surface))
                    self.assertIn(text, visible)
                    self.assertIn("Date stated: Tue 20 Oct 2026 · afternoon", visible)
                    self.assertNotIn("Added ", visible)
                    self.assertNotIn("08:00", visible)
                    self.assertNotIn("19 Oct", visible)
                    self.assertNotIn("family member will be there", visible)
                    self.assertNotIn("20 Oct 2026 08:00", visible)
        self.assertEqual(ep.to_snapshot(), before)   # existing journal/proposals/checks remain untouched

    def test_date_formats_resolve_only_unambiguous_source_dates(self):
        for date in ("10/20", "20/10", "2026-10-20", "20 October 2026", "October 20, 2026", "20 Oct"):
            with self.subTest(date=date):
                out = self.surfaces(self.episode(f"I'll be there on {date} afternoon"), "America/Los_Angeles")[1]
                self.assertIn("Date stated: Tue 20 Oct 2026 · afternoon", html.unescape(out))

    def test_ambiguous_invalid_and_multiple_dates_stay_as_written(self):
        for text in ("I'll be there on 10/11 afternoon", "I'll be there on 31/02 afternoon",
                     "I'll arrive on 10/20 and leave on 10/22 afternoon", "I'll be there in the afternoon"):
            for surface in self.surfaces(self.episode(text), "Australia/Melbourne"):
                with self.subTest(text=text, surface=surface[:50]):
                    self.assertIn(text, html.unescape(surface))
                    self.assertNotIn("Date stated:", surface)
                    self.assertIn("Event date/time", surface)
                    self.assertNotIn("Time to confirm", surface)

    def test_negation_and_completion_are_kept_in_the_family_members_words(self):
        for text in ("I can't be there on 10/20 afternoon", "I arrived on 10/20 afternoon",
                     "I will arrive on 10/20 afternoon if the flight is on time"):
            for surface in self.surfaces(self.episode(text), "Europe/London"):
                self.assertIn(text, html.unescape(surface))
                self.assertNotIn("family member will be there", surface)

    def test_date_uses_the_source_year_and_preserves_an_explicit_year(self):
        ep = self.episode("I'll be there on 10/20 afternoon", at="2027-10-19T08:00:00+01:00")
        self.assertIn("Date stated: Wed 20 Oct 2027 · afternoon", html.unescape(self.surfaces(ep, "Europe/London")[1]))
        ep = self.episode("I arrived on 20 October 2025 afternoon")
        self.assertIn("Date stated: Mon 20 Oct 2025 · afternoon", html.unescape(self.surfaces(ep, "Europe/London")[1]))

    def test_multiple_parts_of_day_remain_pending(self):
        for text in ("I'll arrive 10/20 afternoon and can help in the evening",):
            out = html.unescape(self.surfaces(self.episode(text), "Australia/Melbourne")[1])
            self.assertIn(text, out)
            self.assertIn("Event date/time unclear", out)
            self.assertNotIn("Date stated:", out)

    def test_other_notes_keep_their_original_fact_headline(self):
        ep = self.episode()
        ep.add_update({"update_id": "c02", "at": self.RECEIVED, "kind": "note", "author": "anna",
                       "text": "She walked to the window."}, facts=[
                           {"type": "event", "what": "Walked to the window", "quote": "She walked to the window"}])
        row = block(self.surfaces(ep, "Europe/London")[0], "Walked to the window")
        self.assertIn("Walked to the window", row)
        self.assertNotIn("Date stated:", row)


class TestEventOnlyTimeline(unittest.TestCase):
    def setUp(self):
        self.ep = Episode(load_scenario(SCENARIO))

    def test_unknown_date_labels_distinguish_missing_from_ambiguous_without_changing_precise_dates(self):
        missing = {"status": "pending_confirmation", "when": None,
                   "reason": "The source does not state an event date."}
        unclear = {**missing, "reason": "The quote gives multiple event dates."}
        self.assertEqual(T.event_time_text(missing, "Europe/London"), "Event date/time not stated")
        self.assertEqual(T.event_time_text(unclear, "Europe/London"), "Event date/time unclear")
        self.assertEqual(T.event_time_text({"status": "confirmed", "when": "2026-10-20", "precision": "date"},
                                          "Australia/Melbourne"), "Tue 20 Oct 2026")
        self.assertEqual(T.event_time_text({"status": "confirmed", "when": "2026-10-20", "precision": "part_of_day",
                                           "when_text": "20 October afternoon"}, "America/Los_Angeles"),
                         "Tue 20 Oct 2026 · afternoon")

    def test_family_recorded_hospital_event_is_on_timeline_without_clinician_or_plan_attribution(self):
        from episode_qa import sentence_units, who_of
        text = "She was admitted on 16 October 2026."
        self.ep.add_update({"update_id": "family-event", "kind": "recording", "speaker_type": "family",
                            "speaker": "Anna", "author": "anna", "at": "2026-10-17T08:00:00+01:00", "text": text},
                           facts=[{"type": "admitted", "quote": text}])
        out = T.timeline_html(self.ep, "anna", "Europe/London")
        self.assertIn("Admitted to hospital", out)
        self.assertIn("reported by family", out)
        self.assertIn("Anna (family, recorded by", out)
        self.assertNotIn('class="cr-care"', out)
        self.assertEqual(self.ep.plans(), [])
        archive = T.source_archive_html(self.ep)
        self.assertIn("Family recording · Anna", archive)
        unit = sentence_units(self.ep)[0]
        self.assertEqual(unit["authority"], "family")
        self.assertNotIn("cr-av-care", T.quote_avatar(self.ep, unit, T.colors_of(self.ep)))
        self.assertNotIn("care team", who_of(unit))

    def test_mixed_source_is_split_by_event_dates_and_not_the_upload_date(self):
        text = "She was admitted on 16 October 2026. Surgery is planned for 20 October 2026 morning."
        self.ep.add_update({"update_id": "mixed", "kind": "recording", "author": "anna", "speaker": "Doctor",
                            "at": "2026-10-17T08:00:00+01:00", "text": text}, facts=[
            {"type": "admitted", "when": "2026-10-16", "quote": "She was admitted on 16 October 2026"},
            {"type": "procedure_planned", "what": "Surgery", "when": "2026-10-20", "when_text": "20 October 2026 morning",
             "quote": "Surgery is planned for 20 October 2026 morning"}])
        out = T.timeline_html(self.ep, "anna", "Europe/London")
        self.assertIn("Tuesday 20 Oct 2026", out)
        self.assertIn("Friday 16 Oct 2026", out)
        self.assertLess(out.index("Tuesday 20 Oct 2026"), out.index("Friday 16 Oct 2026"))
        self.assertNotIn("17 Oct", out)
        self.assertNotIn("08:00", out)
        self.assertEqual(len(entries(out)), 2)

    def test_important_event_with_no_date_does_not_use_the_model_or_upload_clock(self):
        self.ep.add_update({"update_id": "unknown", "kind": "recording", "author": "anna", "speaker": "Doctor",
                            "at": "2026-10-17T11:15:00+01:00", "text": "She was admitted to the orthopaedic ward."}, facts=[
            {"type": "admitted", "when": "2026-10-17T11:15:00+01:00", "quote": "She was admitted to the orthopaedic ward"}])
        out = T.timeline_html(self.ep, "anna", "Europe/London")
        self.assertIn("Event date/time not stated", out)
        self.assertIn("The source does not state an event date.", out)
        self.assertIn("separately from checking the source words", out)
        self.assertNotIn("Time to confirm", out)
        self.assertIn("Admitted to hospital", out)
        self.assertNotIn("17 Oct", out)
        self.assertNotIn("11:15", out)

    def test_only_an_explicit_event_clock_is_converted_to_the_viewers_zone(self):
        text = "She was admitted on 16 October 2026 at 23:30."
        self.ep.add_update({"update_id": "clock", "kind": "recording", "author": "anna", "speaker": "Doctor",
                            "at": "2026-10-17T12:00:00+01:00", "text": text}, facts=[
            {"type": "admitted", "when": "2026-10-16T23:30:00+01:00", "quote": text}])
        out = T.timeline_html(self.ep, "anna", "Australia/Melbourne")
        self.assertIn("Saturday 17 Oct 2026", out)
        self.assertIn('class="cr-time">09:30<', out)
        self.assertNotIn('class="cr-time">22:00<', out)

    def test_latest_family_plan_replaces_the_old_one_but_archive_keeps_both(self):
        for i, text in enumerate(("I'll arrive on 10/20 afternoon", "I can't be there on 10/20 afternoon")):
            self.ep.add_update({"update_id": f"plan-{i}", "kind": "note", "topic": "plan", "author": "anna",
                                "at": "2026-10-17T12:00:00+01:00", "text": text}, facts=[])
        out = html.unescape(T.timeline_html(self.ep, "anna", "Europe/London"))
        self.assertNotIn("I'll arrive on 10/20 afternoon", out)
        self.assertIn("I can't be there on 10/20 afternoon", out)
        archive = html.unescape(T.source_archive_html(self.ep))
        self.assertIn("I'll arrive on 10/20 afternoon", archive)
        self.assertIn("I can't be there on 10/20 afternoon", archive)

    def test_reference_documents_and_static_lists_are_archived_without_timeline_events(self):
        self.ep.add_update({"update_id": "hours", "kind": "photo", "author": "anna", "photo_of": "Ward notice",
                            "at": "2026-10-17T12:00:00+01:00", "text": "Visiting hours are 14:00 - 16:00."}, facts=[
            {"type": "visiting", "hours": "14:00 - 16:00", "quote": "Visiting hours are 14:00 - 16:00"}])
        self.ep.add_update({"update_id": "list", "kind": "photo", "author": "anna", "photo_of": "Medicine list",
                            "at": "2026-10-17T12:00:00+01:00", "text": "Continue paracetamol 1 g twice daily."}, facts=[
            {"type": "medication", "name": "paracetamol", "status": "continue", "dose": "1 g", "frequency": "twice daily",
             "quote": "Continue paracetamol 1 g twice daily"}])
        out = T.timeline_html(self.ep, "anna", "Europe/London")
        self.assertEqual(entries(out), [])
        archive = T.source_archive_html(self.ep)
        self.assertIn("Photo of ward notice", archive)
        self.assertIn("Photo of medicine list", archive)

    def test_conflicting_undated_states_are_visibly_unresolved(self):
        for index, ward in enumerate(("Ward 1", "Ward 2")):
            text = f"She is in {ward}."
            self.ep.add_update({"update_id": f"ward-{index}", "kind": "recording", "author": "anna", "speaker": "Doctor",
                                "at": "2026-10-17T12:00:00+01:00", "text": text}, facts=[
                {"type": "location", "unit": ward, "quote": text}])
        out = T.hero_html(self.ep, self.ep.status(), "Europe/London", self.ep.members["anna"])
        self.assertIn("Current state needs confirmation", out)
        self.assertIn("Location needs confirmation", out)
        self.assertIn("She is in Ward 2", out)
        self.assertIn("Event date/time not stated", T.timeline_html(self.ep, "anna", "Europe/London"))


class TestExaminationTopics(unittest.TestCase):
    """Display consolidation preserves separate evidence, dates and trust."""

    def setUp(self):
        self.ep = story(0)

    def source(self, uid, facts, text=None, **extra):
        return self.ep.add_update({"update_id": uid, "at": "2026-10-17T10:00:00+01:00",
                                   "kind": "recording", "speaker": "Doctor", "author": "anna",
                                   "text": text or ". ".join(f["quote"] for f in facts), **extra}, facts=facts)

    def plan(self, what, quote):
        return {"type": "procedure_planned", "what": what, "quote": quote}

    def test_two_facts_and_an_earlier_generic_source_become_one_topic_in_all_three_views(self):
        self.source("vague", [self.plan("some examinations", "She needs some examinations")])
        self.source("specific", [self.plan("X-ray and MRI", "She needs X-ray and MRI"),
                                  self.plan("examination", "An examination is planned for tomorrow")])
        before = copy.deepcopy(self.ep.to_snapshot())
        view = T.presentation_model(self.ep, "anna", "Europe/London")
        self.assertEqual(len(view["test_topics"]), 1)
        topic = view["test_topics"][0]
        self.assertEqual(topic["source_count"], 2)   # two facts from one source count once
        self.assertEqual(len(topic["claims"]), 3)
        self.assertEqual([c["fact"]["what"] for c in topic["visible"]], ["X-ray and MRI"])
        named = next(c for c in topic["claims"] if c["fact"]["what"] == "X-ray and MRI")
        dated = next(c for c in topic["claims"] if c["fact"]["what"] == "examination")
        self.assertIsNone(named["event_time"]["when"])
        self.assertEqual(dated["event_time"]["when"], "2026-10-18")
        self.assertEqual(view["entries"], [])
        state = self.ep.status()
        timeline = T.timeline_html(self.ep, "anna", "Europe/London", presentation=view)
        hero = T.hero_html(self.ep, state, "Europe/London", self.ep.members["anna"], presentation=view)
        side = T.side_html(self.ep, state, "Europe/London", "anna", presentation=view)
        self.assertEqual(timeline.count('class="cr-test-topic"'), 1)
        self.assertLess(timeline.index('class="cr-test-topic"'), timeline.index('class="cr-rail"'))
        self.assertNotIn('class="cr-day"', timeline)
        self.assertIn("sources do not link that date", timeline)
        for rendered in (hero, side):
            self.assertIn('href="#' + topic["id"] + '"', rendered)
            self.assertIn("Tests and examinations · 2 sources", rendered)
            self.assertNotIn("X-ray and MRI planned", rendered)
        self.assertEqual(self.ep.to_snapshot(), before)

    def test_distinct_named_dates_stay_separate_and_recorded_stays_do_not_mix(self):
        self.source("admit-a", [{"type": "admitted", "quote": "She was admitted on 16 October 2026"}])
        self.source("mri-a", [self.plan("MRI", "MRI is planned for 18 October 2026")])
        self.source("xray-a", [self.plan("X-ray", "X-ray is planned for 19 October 2026")])
        self.source("home", [{"type": "discharged", "quote": "She was discharged on 20 October 2026"}],
                    at="2026-10-21T10:00:00+01:00")
        self.source("admit-b", [{"type": "admitted", "quote": "She was admitted on 22 October 2026"}],
                    at="2026-10-23T10:00:00+01:00")
        self.source("blood-b", [self.plan("Blood tests", "Blood tests are planned for 23 October 2026")],
                    at="2026-10-23T11:00:00+01:00")
        view = T.presentation_model(self.ep, "anna", "Europe/London")
        topics = {topic["stay_id"]: topic for topic in view["test_topics"]}
        self.assertEqual(set(topics), {"admit-a", "admit-b"})
        self.assertEqual({c["event_time"]["when"] for c in topics["admit-a"]["visible"]}, {"2026-10-18", "2026-10-19"})
        self.assertEqual(topics["admit-b"]["source_count"], 1)
        self.assertFalse(topics["admit-a"]["upcoming"])

    def test_unscoped_claims_are_not_assigned_to_a_later_admission(self):
        self.source("unscoped", [self.plan("MRI", "MRI is planned")])
        self.source("admit", [{"type": "admitted", "quote": "She was admitted on 16 October 2026"}])
        self.source("scoped", [self.plan("X-ray", "X-ray is planned")])
        view = T.presentation_model(self.ep, "anna", "Europe/London")
        self.assertEqual({topic["stay_id"] for topic in view["test_topics"]}, {None, "admit"})

    def test_imaging_guided_surgery_keeps_its_procedure_event(self):
        for what in ("MRI-guided surgery", "CT-guided operation", "MRI-guided operative procedure"):
            with self.subTest(what=what):
                self.ep = story(0)
                self.source("surgery", [self.plan(what, f"{what} is planned for tomorrow")])
                view = T.presentation_model(self.ep, "anna", "Europe/London")
                self.assertEqual(view["test_topics"], [])
                self.assertEqual(len(view["entries"]), 1)
                self.assertEqual(T.kind_of(view["entries"][0]), "key")
                self.assertIn(what, view["next"][0]["text"])

    def test_topic_links_and_other_plans_share_chronological_next_order(self):
        for mri_quote, surgery_day, expected_topic_first, expected_order in (
                ("MRI is planned for 18 October 2026", 20, True, ["2026-10-18", "2026-10-20"]),
                ("MRI is planned for 20 October 2026", 18, False, ["2026-10-18", "2026-10-20"]),
                ("MRI is planned", 20, False, ["2026-10-20", None])):   # an undated topic link goes last
            with self.subTest(mri=mri_quote, surgery=surgery_day):
                self.ep = story(0)
                self.source("mri", [self.plan("MRI", mri_quote)])
                self.source("surgery", [self.plan("Surgery", f"Surgery is planned for {surgery_day} October 2026")])
                view = T.presentation_model(self.ep, "anna", "Europe/London", now="2026-10-17T12:00:00+01:00")
                topic = view["test_topics"][0]
                self.assertEqual(bool(view["next"][0]["target"]), expected_topic_first)
                self.assertEqual({item["target"] for item in view["next"]}, {None, topic["id"]})
                self.assertNotIn("event_time", topic)  # no invented whole-topic appointment date
                self.assertEqual([item["_sort_when"] for item in view["next"]], expected_order)

    def test_negative_instructions_do_not_cancel_a_test_but_explicit_plan_changes_do(self):
        for quote, upcoming in (
                ("MRI is planned for 18 October 2026, no contrast is needed", True),
                ("MRI is planned for 18 October 2026, fasting is not required", True),
                ("MRI is planned for 18 October 2026 and has not been cancelled", True),
                ("MRI is planned for 18 October 2026; we have not cancelled the MRI", True),
                ("MRI is planned for 18 October 2026; do not cancel the MRI", True),
                ("MRI is planned for 18 October 2026; we have not postponed the MRI", True),
                ("MRI is planned for 18 October 2026; blood tests are cancelled", True),
                ("MRI is not required", False),
                ("No MRI is planned", False),
                ("MRI is no longer booked", False),
                ("MRI has been cancelled", False),
                ("We postponed the MRI", False),
                ("MRI is delayed", False)):
            with self.subTest(quote=quote):
                self.ep = story(0)
                self.source("mri", [self.plan("MRI", quote)])
                view = T.presentation_model(self.ep, "anna", "Europe/London", now="2026-10-17T12:00:00+01:00")
                topic = view["test_topics"][0]
                self.assertEqual(topic["upcoming"], upcoming)
                self.assertEqual(bool(view["next"]), upcoming)
                visible = T.test_topics_html(self.ep, [topic], "Europe/London", lambda entry: None).split('<details>')[0]
                self.assertIn(T.esc(quote), visible)
                self.assertEqual(self.ep.procedures["mri"]["status"], "planned")

    def test_family_and_hand_changed_claims_cannot_become_care_team_statements(self):
        self.source("medical", [self.plan("MRI", "MRI is planned for 18 October 2026")])
        for uid in ("family-a", "family-b"):
            self.source(uid, [self.plan("MRI", "MRI is planned for 19 October 2026")], speaker_type="family", speaker="Anna")
        changed = "Blood tests are planned for tomorrow"
        self.source("changed", [self.plan("Blood tests", changed)], reading={"method": "asr", "changed_lines": [changed]})
        view = T.presentation_model(self.ep, "anna", "Europe/London")
        claims = [c for topic in view["test_topics"] for c in topic["claims"]]
        self.assertEqual({c["authority"] for c in claims if c["update_id"] != "medical"}, {"family"})
        self.assertEqual(self.ep.procedures["mri"]["fact"]["when"], "2026-10-18")
        # Identical display statements fold; their distinct evidence is retained.
        topic = view["test_topics"][0]
        family_visible = [c for c in topic["visible"] if c["update_id"].startswith("family-")]
        self.assertEqual(len(family_visible), 1)
        self.assertEqual(topic["source_count"], 4)
        rendered = T.timeline_html(self.ep, "anna", "Europe/London", presentation=view)
        self.assertIn("Conflicting source statements", rendered)
        self.assertIn("reported by family", rendered)

    def test_generic_conflicts_and_cancellation_are_visible_beside_named_tests(self):
        self.source("g1", [self.plan("examination", "An examination is planned for 18 October 2026")])
        self.source("g2", [self.plan("examination", "An examination is planned for 19 October 2026")], speaker="Ward nurse")
        self.source("named", [self.plan("MRI", "MRI is planned")])
        cancel = "Some tests are cancelled"
        self.source("cancel", [self.plan("some tests", cancel)])
        view = T.presentation_model(self.ep, "anna", "Europe/London")
        topic = view["test_topics"][0]
        self.assertTrue(topic["conflict"])
        self.assertEqual({c["update_id"] for c in topic["visible"]}, {"g1", "g2", "named", "cancel"})
        visible = T.test_topics_html(self.ep, [topic], "Europe/London", lambda entry: None).split('<details>')[0]
        self.assertIn(cancel, visible)
        self.assertIn("Conflicting source statements", visible)
        # The display does not manufacture a cancellation lifecycle in the core.
        self.assertEqual(self.ep.procedures["some tests"]["status"], "planned")

    def test_completion_does_not_complete_another_named_test_and_keeps_its_event(self):
        self.source("mri", [self.plan("MRI", "MRI is planned for 18 October 2026")])
        self.source("xray", [self.plan("X-ray", "X-ray is planned for 19 October 2026")])
        self.source("done", [{"type": "procedure_done", "what": "MRI", "quote": "MRI was done on 18 October 2026"}],
                    at="2026-10-19T10:00:00+01:00")
        view = T.presentation_model(self.ep, "anna", "Europe/London")
        self.assertEqual(self.ep.procedures["mri"]["status"], "done")
        self.assertEqual(self.ep.procedures["x ray"]["status"], "planned")
        self.assertTrue(any(e["headline"] == "MRI done" for e in view["entries"]))
        topic = view["test_topics"][0]
        self.assertEqual([c["fact"]["what"] for c in topic["visible"]], ["X-ray"])
        self.assertEqual(next(c for c in topic["claims"] if c["fact"]["what"] == "MRI")["state"], "completed")

    def test_corrected_and_deleted_sources_reproject_without_stale_claims(self):
        self.source("source", [self.plan("MRI", "MRI is planned for 18 October 2026")])
        replacement = "X-ray is planned for 19 October 2026"
        self.ep.revise_update("source", {"text": replacement}, expected_revision=1,
                              request_id="fix-test", facts=[self.plan("X-ray", replacement)])
        view = T.presentation_model(self.ep, "anna", "Europe/London")
        claims = view["test_topics"][0]["claims"]
        self.assertEqual([(c["source_revision"], c["fact"]["what"]) for c in claims], [(2, "X-ray")])
        self.ep.delete_update("source", expected_revision=2, request_id="remove-test")
        self.assertEqual(T.presentation_model(self.ep, "anna", "Europe/London")["test_topics"], [])

    def test_only_test_only_supplements_fold_and_other_observations_stay_quiet(self):
        quote = "She needs X-ray and MRI"
        self.source("mixed", [self.plan("X-ray and MRI", quote),
                              {"type": "event", "what": "She needs X-ray and MRI", "quote": quote},
                              {"type": "event", "what": "Her hip is painful", "quote": "Her hip is painful"}])
        view = T.presentation_model(self.ep, "anna", "Europe/London")
        self.assertEqual(len(view["entries"]), 1)
        self.assertEqual([line["fact"]["what"] for line in view["entries"][0]["lines"]], ["Her hip is painful"])
        self.assertEqual(T.kind_of(view["entries"][0]), "note")
        self.assertEqual(len(view["test_topics"][0]["supplements"]), 1)
        self.assertFalse(T._test_supplement({"type": "event", "quote": quote,
                                            "fact": {"what": "Hip pain needs X-ray and MRI"}}, [{"quote": quote}]))

    def test_new_markers_escaping_and_photos_follow_sources_without_mutation(self):
        self.source("photo", [self.plan("MRI", "MRI is planned")], kind="photo", photo_of="MRI request", image="image-key")
        self.ep.mark_read("anna")
        self.source("new", [self.plan("some examinations", "She needs some examinations")], speaker="<script>doctor</script>")
        before = copy.deepcopy((self.ep.events, self.ep.procedures, self.ep.entries))
        view = T.presentation_model(self.ep, "anna", "Europe/London")
        out = T.timeline_html(self.ep, "anna", "Europe/London", photo_of=lambda e: PNG if e["kind"] == "photo" else None, presentation=view)
        self.assertEqual(out.count('class="cr-new"'), 1)
        self.assertIn("&lt;script&gt;doctor&lt;/script&gt;", out)
        self.assertNotIn("<script>", out)
        self.assertIn("data:image/png;base64,", out)
        self.assertEqual((self.ep.events, self.ep.procedures, self.ep.entries), before)
        self.ep.mark_read("anna")
        self.assertNotIn('class="cr-new"', T.timeline_html(self.ep, "anna", "Europe/London"))


class TestSourceArchive(unittest.TestCase):
    def test_every_original_source_and_photo_remain_available_without_upload_times(self):
        ep = story(3)
        out = T.source_archive_html(ep, photo_of=lambda e: PNG if e["kind"] == "photo" else None)
        self.assertIn("Source documents and messages", out)
        self.assertIn('src="data:image/png;base64,', out)
        for source in ep.updates:
            self.assertIn(T.lines_br(source["text"]), out)
            self.assertNotIn(source["at"], out)
        self.assertNotIn("19 Oct 13:05", out)
        self.assertNotIn("\n", out)

    def test_family_speech_does_not_claim_a_person_checked_the_recognized_words(self):
        ep = story(0)
        ep.add_update({"update_id": "voice-plan", "at": "2026-10-17T09:00:00+01:00", "kind": "note", "topic": "plan",
                       "author": "anna", "text": "I'll arrive on 10/20 afternoon",
                       "reading": {"method": "asr", "model": "speech-stub", "model_text": "I'll arrive on 10/20 afternoon",
                                   "changed_lines": [], "removed_lines": []}}, facts=[])
        out = T.source_archive_html(ep)
        self.assertIn("Family words recognized by speech-to-text (speech-stub)", out)
        self.assertIn("Correct an update", out)
        self.assertNotIn("ticked", out)
        self.assertNotIn("checked against", out)


class TestDischargeTiming(unittest.TestCase):
    RECEIVED = "2026-10-19T08:00:00+01:00"
    PAPER = "Hospital discharge summary.\nDate of discharge: 16 October 2026.\nDischarge destination: Home."

    def episode(self, text, when=None):
        ep = Episode(load_scenario(SCENARIO))
        fact = {"type": "discharged", "quote": text}
        if when is not None:
            fact["when"] = when
        entry = ep.add_update({"update_id": "notice", "at": self.RECEIVED, "kind": "photo", "author": "anna",
                               "photo_of": "Hospital discharge summary", "text": text}, facts=[fact])
        self.assertEqual(entry["rejected"], [])
        return ep

    def discharge_cell(self, ep, zone):
        out = T.hero_html(ep, ep.status(tz=zone), zone, ep.members["mia"])
        return re.search(r'<span class="cr-fact-label">Discharged</span>(.*?)</div>', out).group(1)

    def test_date_only_discharge_is_the_document_date_not_received_time_in_any_zone(self):
        for when in ("2026-10-16", None):
            ep = self.episode(self.PAPER, when)
            self.assertEqual(ep.status()["discharged"]["when"], "2026-10-16")
            self.assertEqual(ep.status()["discharged"]["at"], self.RECEIVED)
            for zone in ("Australia/Melbourne", "America/Los_Angeles"):
                with self.subTest(when=when, zone=zone):
                    cell = self.discharge_cell(ep, zone)
                    self.assertIn('>Fri 16 Oct 2026</span>', cell)
                    self.assertIn("the hospital's date", cell)
                    self.assertNotIn("19 Oct", cell)

    def test_discharge_clock_time_uses_the_viewers_zone(self):
        ep = self.episode("She has been discharged at 23:30 on 16 October 2026.", "2026-10-16T23:30")
        cell = self.discharge_cell(ep, "Australia/Melbourne")
        self.assertIn(">Sat 17 Oct 09:30</span>", cell)
        self.assertIn("your time", cell)
        self.assertNotIn("19 Oct", cell)

    def test_a_model_cannot_add_a_clock_time_to_date_only_discharge_fields(self):
        ep = self.episode(self.PAPER, "2026-10-16T23:30")
        self.assertEqual(ep.slots["discharged"]["fact"]["when"], "2026-10-16")
        self.assertEqual(ep.status()["discharged"]["when"], "2026-10-16")
        cell = self.discharge_cell(ep, "Australia/Melbourne")
        self.assertIn(">Fri 16 Oct 2026</span>", cell)
        self.assertNotIn("17 Oct", cell)
        self.assertNotIn("23:30", cell)

    def test_unknown_discharge_date_stays_pending_without_a_received_time(self):
        ep = self.episode("She has been discharged.")
        cell = self.discharge_cell(ep, "Australia/Melbourne")
        self.assertIn(">Event date/time not stated</span>", cell)
        self.assertNotIn("19 Oct", cell)
        self.assertNotIn("18:00", cell)


class TestPlanClockLabels(unittest.TestCase):
    def test_remote_plan_clock_keeps_its_hospital_zone_label(self):
        ep = story(0)
        words = "I'll visit on 18 October 2026 at 9 am."
        ep.add_update({"update_id": "remote-plan", "kind": "note", "topic": "plan", "author": "anna",
                       "at": "2026-10-17T12:00:00+01:00", "text": words}, facts=[])
        zone = "America/Toronto"
        state = ep.status(tz=zone)
        surfaces = {
            "hero": T.hero_html(ep, state, zone, ep.members["david"]),
            "timeline": T.timeline_html(ep, "david", zone),
            "plans": T.side_html(ep, state, zone, "david"),
        }
        for name, markup in surfaces.items():
            with self.subTest(surface=name):
                visible = html.unescape(markup)
                self.assertIn(words, visible)
                self.assertIn("Date stated: Sun 18 Oct 09:00 (hospital time)", visible)
        self.assertIn("Sun 18 Oct 04:00", surfaces["hero"])
        self.assertIn('class="cr-time">04:00<', surfaces["timeline"])


class TestInfoStrip(unittest.TestCase):
    def test_strip_under_right_now(self):
        ep = story(3)   # the ward's hours and phone are in
        s = ep.status(tz="Europe/London", now=ep.latest_at())
        out = T.hero_html(ep, s, "Europe/London", ep.members["anna"])
        self.assertIn('class="cr-strip"', out)
        self.assertIn("Visiting hours", out)
        self.assertIn('href="tel:', out)
        self.assertIn("Family in the loop", out)
        self.assertIn('href="#cr-family"', out)
        ep.mark_read("anna")
        out = T.hero_html(ep, s, "Europe/London", ep.members["anna"])
        self.assertIn(f"1 of {len(ep.members)} read the latest", out)

    def test_at_home_no_ward(self):
        ep = story()
        s = ep.status(tz="Europe/London", now=ep.latest_at())
        out = T.hero_html(ep, s, "Europe/London", ep.members["anna"])
        self.assertNotIn("Visiting hours", out)
        self.assertIn("Medicines", out)
        self.assertIn('href="#cr-meds"', out)
        self.assertIn('id="cr-meds"', T.side_html(ep, s, "Europe/London", "anna"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
