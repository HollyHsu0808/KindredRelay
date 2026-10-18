"""S1 product-path review regressions (R2-F2 both directions, R1-F1, R2-F1, R2-F4, R1-F2 and its cancelled-test
counterpart, R2-F3), independent fictional data. No model or network."""
import copy
import hashlib
import html
import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode
from episode import Episode, event_time
import episode_qa as Q
import timeline_html as T

SCENARIO = {'patient': {'name': 'Sam', 'home': 'at home', 'timezone': 'Europe/London'},
            'members': [{'member_id': 'alex', 'name': 'Alex', 'timezone': 'Europe/London'}], 'updates': []}


def setUpModule():
    print('REVIEW_FIXES_S1_20261017 ' + json.dumps({
        'loaded_episode': episode.__file__, 'episode_sha256': hashlib.sha256(Path(episode.__file__).read_bytes()).hexdigest(),
        'loaded_qa': Q.__file__, 'qa_sha256': hashlib.sha256(Path(Q.__file__).read_bytes()).hexdigest(),
        'loaded_timeline': T.__file__, 'timeline_sha256': hashlib.sha256(Path(T.__file__).read_bytes()).hexdigest()}), flush=True)


def patient(name):
    scenario = copy.deepcopy(SCENARIO)
    scenario['patient']['name'] = name
    return Episode(scenario)


def add(ep, uid, text, facts, *, at, kind='recording', speaker=None, **extra):
    return ep.add_update({'update_id': uid, 'kind': kind, 'author': 'alex', 'at': at, 'text': text,
                          'speaker': speaker or uid, **extra}, facts=copy.deepcopy(facts))


class SameClockAdmissionConfirmation(unittest.TestCase):
    """R2-F2: confirming that an admission happened does not order it against a discharge at the same clock."""
    home = 'Taylor was discharged home on 17 June 2029 at 10:35.'
    admit = 'Taylor was admitted on 17 June 2029 at 10:35.'
    checked = 'The admission record was checked and confirmed: Taylor was admitted on 17 June 2029 at 10:35.'
    still = 'The inpatient record was checked and confirmed: Taylor was still admitted on 17 June 2029 at 10:35.'

    def episode(self, order, confirmation):
        ep = patient('Taylor')
        sources = {'home': (self.home, 'discharged', '2029-06-18T09:00:00+01:00'),
                   'admit': (self.admit, 'admitted', '2029-06-18T09:10:00+01:00')}
        for uid in order:
            text, typ, at = sources[uid]
            add(ep, uid, text, [{'type': typ, 'quote': text}], at=at)
        entry = add(ep, 'checked', confirmation, [{'type': 'admitted', 'quote': confirmation}],
                    at='2029-06-18T10:00:00+01:00', speaker='Clinician')
        return ep, entry

    def test_confirmed_same_clock_admission_keeps_discharge_conflict_open(self):
        for order in (('home', 'admit'), ('admit', 'home')):
            with self.subTest(order=order):
                ep, entry = self.episode(order, self.checked)
                self.assertEqual(ep.phase(), 'Current patient status needs confirmation')
                self.assertEqual(ep.superseded_state_claims, [])
                records = [r for r in ep.slots.values() if r.get('time_uncertain')]
                claims = {r['update_id'] for r in records} | {a['update_id'] for r in records for a in r.get('uncertain_alternatives', [])}
                self.assertTrue({'home', 'checked'} <= claims)   # the discharge stays linked to the open conflict
                states = {u['update_id']: u['state'] for u in Q.sentence_units(ep)}
                self.assertEqual((states['home'], states['checked']), ('time_uncertain', 'time_uncertain'))
                self.assertEqual(Episode.from_snapshot(ep.to_snapshot()).phase(), 'Current patient status needs confirmation')
                if order == ('home', 'admit'):
                    self.assertFalse(entry['lines'][0]['applied'])
                    self.assertEqual(sorted(ep.slots), ['discharged', 'location'])
                    self.assertIn('admit', claims)
        with self.subTest(control='an explicit checked inpatient state still settles the same-clock conflict'):
            ep, entry = self.episode(('home', 'admit'), self.still)
            self.assertTrue(entry['lines'][0]['applied'])
            self.assertEqual(ep.phase(), 'Admitted to hospital')
            self.assertNotIn('discharged', ep.slots)


class SameClockDischargeConfirmation(unittest.TestCase):
    """R2-F2, discharge direction, reversed by the demo product decision of 2026-10-17 (single session, no re-admission
    scenario): a care-team checked discharge confirmation settles a same-clock admission conflict as discharged, with or
    without continuing-state wording. Family wording and a hedged confirmation never settle it; the admission direction
    (SameClockAdmissionConfirmation) stays conservative."""
    home = 'Taylor was discharged home on 17 June 2029 at 10:35.'
    admit = 'Taylor was admitted on 17 June 2029 at 10:35.'
    checked = 'The discharge record was checked and confirmed: Taylor was discharged home on 17 June 2029 at 10:35.'
    settled = ('The discharge record was checked and confirmed: Taylor was discharged home on 17 June 2029 at 10:35 '
               'and she is now at home.')

    def episode(self, order, confirmation, kind='recording'):
        ep = patient('Taylor')
        sources = {'home': (self.home, 'discharged', '2029-06-18T09:00:00+01:00'),
                   'admit': (self.admit, 'admitted', '2029-06-18T09:10:00+01:00')}
        for uid in order:
            text, typ, at = sources[uid]
            add(ep, uid, text, [{'type': typ, 'quote': text}], at=at)
        entry = add(ep, 'checked', confirmation, [{'type': 'discharged', 'quote': confirmation}],
                    at='2029-06-18T10:00:00+01:00', kind=kind, speaker='Clinician')
        return ep, entry

    def test_checked_care_team_discharge_settles_same_clock_admission_conflict(self):
        for confirmation in (self.checked, self.settled):
            for order in (('home', 'admit'), ('admit', 'home')):
                with self.subTest(order=order, confirmation=confirmation):
                    ep, entry = self.episode(order, confirmation)
                    self.assertTrue(entry['lines'][0]['applied'])
                    self.assertEqual(ep.phase(), 'Home after hospital')
                    self.assertEqual(ep.slots['discharged']['update_id'], 'checked')
                    self.assertFalse(any(r.get('time_uncertain') for r in ep.slots.values()))
                    states = {u['update_id']: u['state'] for u in Q.sentence_units(ep)}
                    self.assertEqual(states['checked'], 'current')
                    self.assertNotIn('time_uncertain', states.values())
                    self.assertEqual(Episode.from_snapshot(ep.to_snapshot()).phase(), 'Home after hospital')
        for confirmation, kind in ((self.checked, 'note'),
                                   (self.checked.replace('was checked and confirmed', 'may be confirmed'), 'recording')):
            for order in (('home', 'admit'), ('admit', 'home')):
                with self.subTest(control='family wording or a hedged confirmation never settles it', kind=kind,
                                  confirmation=confirmation, order=order):
                    ep, entry = self.episode(order, confirmation, kind)
                    self.assertEqual(ep.phase(), 'Current patient status needs confirmation')
                    records = [r for r in ep.slots.values() if r.get('time_uncertain')]
                    claims = {r['update_id'] for r in records} | {a['update_id'] for r in records for a in r.get('uncertain_alternatives', [])}
                    self.assertIn('admit', claims)   # the admission stays linked to the open conflict
                    self.assertEqual(Episode.from_snapshot(ep.to_snapshot()).phase(), 'Current patient status needs confirmation')


class FamilyCompletionHeading(unittest.TestCase):
    """R1-F1: a family-only completed procedure is not promoted to the Right-now heading."""
    admitted = 'Jules was admitted on 15 February 2027 at 07:00.'
    done = 'The ankle operation was completed on 16 February 2027 at 11:25.'

    def episode(self, kind):
        ep = patient('Jules')
        add(ep, 'admitted', self.admitted, [{'type': 'admitted', 'quote': self.admitted}], at='2027-02-20T16:00:00+00:00')
        add(ep, 'done', self.done, [{'type': 'procedure_done', 'what': 'ankle operation', 'quote': self.done}],
            at='2027-02-20T16:00:00+00:00', kind=kind)
        return ep

    def test_family_only_completion_does_not_become_recovery_heading(self):
        with self.subTest(source='family note'):
            ep = self.episode('note')
            p, = ep.procedures.values()
            self.assertEqual((p['authority'], p['status']), ('family', 'done'))
            self.assertEqual(ep.phase(), 'Admitted to hospital')
            self.assertEqual(ep.status()['phase'], 'Admitted to hospital')
            self.assertEqual(Episode.from_snapshot(ep.to_snapshot()).phase(), 'Admitted to hospital')
        with self.subTest(control='an unbooked care-team completion still shows recovery'):
            ep = self.episode('recording')
            self.assertEqual(ep.phase(), 'Recovering after ankle operation')


class LocationClarificationKeepsTwoAnswers(unittest.TestCase):
    """R2-F1: settling the location does not relabel a sentence whose going-home answer is still disputed."""
    a = 'Sam was at Pine Hospital on 4 February 2028 at 10:15 and can go home on 6 February 2028.'
    b = 'Sam was at Oak Hospital on 4 February 2028 at 10:15 and can go home on 7 February 2028.'
    c = 'The location record was checked and confirmed: Sam was at Pine Hospital on 4 February 2028 at 10:15.'

    def episode(self, with_discharge=True):
        ep = patient('Sam')
        for uid, hospital, day, speaker, at in (('A', 'Pine Hospital', '6', 'Dr A', '2028-02-05T09:00:00+00:00'),
                                                ('B', 'Oak Hospital', '7', 'Dr B', '2028-02-05T09:10:00+00:00')):
            place = f'Sam was at {hospital} on 4 February 2028 at 10:15'
            going_home = f'can go home on {day} February 2028'
            facts = [{'type': 'location', 'hospital': hospital, 'quote': place}]
            if with_discharge:
                text = f'{place} and {going_home}.'
                facts.append({'type': 'expected_discharge', 'when_text': f'{day} February 2028', 'quote': going_home})
            else:
                text = place + '.'
            add(ep, uid, text, facts, at=at, speaker=speaker)
        add(ep, 'C', self.c, [{'type': 'location', 'hospital': 'Pine Hospital', 'quote': self.c}],
            at='2028-02-05T10:00:00+00:00', speaker='Clinician')
        return ep

    def test_location_clarification_keeps_unresolved_going_home_answers(self):
        ep = self.episode()
        self.assertTrue(ep.slots['expected_discharge'].get('two_answers'))
        self.assertFalse(ep.slots['location'].get('time_uncertain'))
        self.assertEqual(ep.slots['location']['update_id'], 'C')
        units = Q.sentence_units(ep)
        by_sid = {u['sid']: u for u in units}
        self.assertEqual([u['text'] for u in units if u['update_id'] in {'A', 'B'}], [self.a, self.b])
        for sid in ('A.1', 'B.1'):
            with self.subTest(sid=sid):
                self.assertEqual((by_sid[sid]['state'], by_sid[sid]['replaced_by']), ('two_answers', None))
                self.assertIn('two different answers', Q.display_label(by_sid[sid], by_sid, None))
                self.assertNotIn('earlier', Q.display_label(by_sid[sid], by_sid, None))
        self.assertEqual(by_sid['C.1']['state'], 'current')
        with self.subTest(control='a sentence whose only claim is resolved still links to the clarification'):
            ep = self.episode(with_discharge=False)
            by_sid = {u['sid']: u for u in Q.sentence_units(ep)}
            for sid in ('A.1', 'B.1'):
                self.assertEqual((by_sid[sid]['state'], by_sid[sid]['replaced_by']), ('earlier', 'C.1'))


class DatedHeaderMayMonth(unittest.TestCase):
    """R2-F4: the month May in a dated header is not the modal verb 'may'."""

    def timing(self, text, at):
        ep = patient('Jules')
        fact = {'type': 'admitted', 'quote': text}
        update = {'update_id': 'ward', 'kind': 'photo', 'author': 'alex', 'at': at, 'text': text}
        return ep, update, fact, event_time(ep, update, {'fact': fact})

    def test_may_month_in_dated_header_keeps_the_known_admission_day(self):
        for text, at, expected in (('Ward note dated 7 May 2027: Jules was admitted that day.', '2027-05-08T12:00:00+01:00', '2027-05-07'),
                                   ('Ward note dated 7 June 2027: Jules was admitted that day.', '2027-06-08T12:00:00+01:00', '2027-06-07')):
            with self.subTest(text=text):
                ep, update, fact, timing = self.timing(text, at)
                self.assertEqual((timing['when'], timing['status']), (expected, 'confirmed'))
                ep.add_update(update, facts=[fact])
                self.assertEqual(ep.slots['admitted']['event_time']['when'], expected)
        for text in ('The note may be dated 7 June 2027: Jules was admitted that day.',
                     'The note may be dated 7 May 2027: Jules was admitted that day.',
                     'Ward note dated 7 May 2027: Jules may have been admitted that day.'):
            with self.subTest(control='a genuine modal stays pending', text=text):
                timing = self.timing(text, '2027-06-08T12:00:00+01:00')[3]
                self.assertEqual((timing['when'], timing['status']), (None, 'pending_confirmation'))


class RebookedTestStaysNext(unittest.TestCase):
    """R1-F2: a test cancelled or postponed and then re-planned in one statement stays in Right now and What's next."""
    now = '2026-10-17T12:00:00+01:00'

    def view(self, quote):
        ep = patient('Sam')
        add(ep, 'mri', quote, [{'type': 'procedure_planned', 'what': 'MRI', 'quote': quote}],
            at='2026-10-17T10:00:00+01:00', speaker='Doctor')
        return ep, T.presentation_model(ep, 'alex', 'Europe/London', now=self.now)

    def test_replanned_test_after_cancellation_stays_upcoming(self):
        for quote, when in (('MRI was cancelled, but is now planned for tomorrow.', '2026-10-18'),
                            ('MRI was cancelled but has been rebooked for 18 October 2026.', '2026-10-18'),
                            ('MRI was postponed and has been rescheduled for 19 October 2026.', '2026-10-19'),
                            ('MRI has been postponed to 20 October 2026.', '2026-10-20'),
                            ('We cancelled the MRI and moved it to 21 October 2026.', '2026-10-21')):
            with self.subTest(quote=quote):
                ep, view = self.view(quote)
                p = ep.procedures['mri']
                self.assertEqual((p['status'], p['event_time']['when']), ('planned', when))   # the core record
                topic, = view['test_topics']
                self.assertTrue(topic['upcoming'])
                self.assertEqual([(item['target'], item['_sort_when']) for item in view['next']], [(topic['id'], when)])
                state = ep.status('Europe/London')
                for rendered in (T.hero_html(ep, state, 'Europe/London', ep.members['alex'], presentation=view),
                                 T.side_html(ep, state, 'Europe/London', 'alex', presentation=view)):
                    self.assertIn(f'href="#{topic["id"]}"', rendered)
        for quote in ('MRI has been cancelled.',
                      'MRI was cancelled and has not been rebooked for 18 October 2026.',
                      'MRI was cancelled but may be rebooked for 18 October 2026.',
                      'MRI was cancelled and will be rebooked for 18 October 2026 if a slot opens.',
                      'MRI was cancelled; it had been planned for 18 October 2026.',
                      'MRI was cancelled, then rebooked for 18 October 2026, and has now been cancelled again.',
                      'MRI was postponed until further notice.'):
            with self.subTest(control='a cancellation that is not re-planned stays out of What is next', quote=quote):
                ep, view = self.view(quote)
                self.assertFalse(view['test_topics'][0]['upcoming'])
                self.assertEqual(view['next'], [])
                self.assertEqual(ep.procedures['mri']['status'], 'planned')   # display only; the core is unchanged


class CancelledTestNotNext(unittest.TestCase):
    """A test the source says is cancelled (date-qualified subject, elliptical trailing clause) leaves Right now and
    What's next; a negated, modal or conditional cancellation and a negated instruction keep it there."""
    now = '2026-10-17T12:00:00+01:00'

    def view(self, quote):
        ep = patient('Sam')
        add(ep, 'mri', quote, [{'type': 'procedure_planned', 'what': 'MRI', 'quote': quote}],
            at='2026-10-17T10:00:00+01:00', speaker='Doctor')
        return ep, T.presentation_model(ep, 'alex', 'Europe/London', now=self.now)

    def rendered(self, ep, view):
        state = ep.status('Europe/London')
        return (T.hero_html(ep, state, 'Europe/London', ep.members['alex'], presentation=view),
                T.side_html(ep, state, 'Europe/London', 'alex', presentation=view))

    def test_cancelled_test_is_not_upcoming(self):
        for quote in ('The MRI on 18 October 2026 has been cancelled.',
                      'MRI was rebooked for 18 October 2026 but has now been cancelled.',
                      'The MRI scheduled for 18 October 2026 has been cancelled.',
                      'The MRI at 14:00 on 18 October 2026 was cancelled.',
                      'The MRI planned for tomorrow has been cancelled.',
                      'The MRI scan on 18 October 2026 has been cancelled.',
                      'The MRI, booked for 18 October 2026, has been cancelled.',
                      'MRI was booked for 18 October 2026 but it has since been cancelled.',
                      'MRI was rescheduled for 18 October 2026 and was then cancelled.',
                      'MRI and CT were rebooked for 18 October 2026 but have since been cancelled.'):
            with self.subTest(quote=quote):
                ep, view = self.view(quote)
                topic, = view['test_topics']
                self.assertFalse(topic['upcoming'])
                self.assertEqual(view['next'], [])
                for rendered in self.rendered(ep, view):
                    self.assertNotIn(f'href="#{topic["id"]}"', rendered)
                self.assertIn(quote, html.unescape(T.test_topics_html(ep, [topic], 'Europe/London', lambda entry: None)))
                self.assertIn(quote, html.unescape(T.source_archive_html(ep)))   # the source itself is kept
                self.assertEqual(ep.procedures['mri']['status'], 'planned')   # display only; the core is unchanged

    def test_negated_hedged_or_conditional_cancellation_stays_upcoming(self):
        for quote, when in (('The MRI has not been cancelled.', None),
                            ('The MRI may be cancelled if the scanner is down.', None),
                            ('Do not cancel the MRI.', None),
                            ('The MRI on 18 October 2026 has not been cancelled.', '2026-10-18'),
                            ('The MRI on 18 October 2026 might be cancelled.', '2026-10-18'),
                            ('The MRI on 18 October 2026 will be cancelled if the scanner is down.', '2026-10-18'),
                            ('If the scanner is down, the MRI on 18 October 2026 will be cancelled.', '2026-10-18'),
                            ('We may cancel the MRI on 18 October 2026.', '2026-10-18'),
                            ('MRI on 18 October 2026: no contrast, and nothing to eat before the MRI.', '2026-10-18'),
                            ('The MRI on 18 October 2026 is planned; blood tests were requested but have since been cancelled.', '2026-10-18'),
                            ('We rebooked the MRI for 18 October 2026 and cancelled the CT.', '2026-10-18'),
                            ('MRI was rebooked for 18 October 2026 and has not since been cancelled.', '2026-10-18'),
                            ('The MRI on 18 October 2026 has been delayed until 14:00.', '2026-10-18T14:00:00+01:00'),
                            ('We postponed the MRI on 18 October 2026 to 20 October 2026.', None)):
            with self.subTest(quote=quote):
                ep, view = self.view(quote)
                p = ep.procedures['mri']
                self.assertEqual((p['status'], p['event_time']['when']), ('planned', when))   # the core record
                topic, = view['test_topics']
                self.assertTrue(topic['upcoming'])
                self.assertEqual([(item['target'], item['_sort_when']) for item in view['next']], [(topic['id'], when)])
                for rendered in self.rendered(ep, view):
                    self.assertIn(f'href="#{topic["id"]}"', rendered)


class FamilyOwnEventNoteNotPlanned(unittest.TestCase):
    """A member's own negated or otherwise non-arrangement event note stays a visible family row, never 'Planned'."""
    keys = 'I will bring the keys on 18 August 2028 at 11:10.'

    def hero(self, text, *, fact_quote=None, kind='note', topic='plan'):
        ep = patient('Robin')
        quote = fact_quote or text
        add(ep, 'plan', text, [{'type': 'event', 'what': quote, 'quote': quote}],
            at='2028-08-20T09:00:00+01:00', kind=kind, topic=topic, speaker='Nurse Avery')
        return ep, T.hero_html(ep, ep.status('Europe/London'), 'Europe/London', ep.members['alex'])

    def test_member_non_arrangement_event_note_is_not_planned(self):
        for text, fact_quote, topic in (('I will not bring the keys on 18 August 2028 at 11:10.', None, 'plan'),
                                        ('I will not bring the keys on 28 August 2028 at 11:10.', None, 'plan'),
                                        ('If Robin stabilises, ' + self.keys, self.keys, 'plan'),
                                        (self.keys, None, None)):
            with self.subTest(text=text, topic=topic):
                ep, hero = self.hero(text, fact_quote=fact_quote, topic=topic)
                quote = fact_quote or text
                rows = T.event_entries(ep, 'alex', None)
                self.assertTrue(any(line['quote'] == quote for row in rows for line in row['lines']))   # the row stays visible
                self.assertIn('<span class="cr-fact-label">Latest event</span>', hero)
                self.assertNotIn('<span class="cr-fact-label">Planned</span>', hero)
                self.assertIn(quote, html.unescape(hero))
        with self.subTest(control='a care-team planned event is still Planned'):
            hero = self.hero('Physio will see Robin on 18 August 2028 at 11:10.', kind='recording', topic=None)[1]
            self.assertIn('<span class="cr-fact-label">Planned</span>', hero)
        with self.subTest(control="the member's own arrangement is still their family plan"):
            hero = self.hero(self.keys)[1]
            self.assertIn('<span class="cr-fact-label">Family plan</span>', hero)


class WithdrawnSharedPlanSiblingEvent(unittest.TestCase):
    """R2-F3: a family plan's own event fact never returns as a current 'Planned' row after the member withdraws that plan."""
    old = 'I will collect Robin from hospital on 20 June 2027.'
    cancel = 'I cannot collect Robin from hospital on 20 June 2027.'
    fall = 'Robin fell on the ward on 18 June 2027.'

    def episode(self, extra=None):
        ep = patient('Robin')
        facts = [{'type': 'family', 'what': 'I will collect Robin from hospital', 'quote': self.old},
                 {'type': 'event', 'what': 'Collect Robin from hospital', 'quote': self.old}]
        if extra:
            facts.append({'type': 'event', 'what': 'Robin fell on the ward', 'quote': extra})
        add(ep, 'old', ' '.join(filter(None, (self.old, extra))), facts, at='2027-06-18T12:00:00+01:00', kind='note', topic='plan')
        return ep

    def withdraw(self, ep):
        add(ep, 'cancel', self.cancel, [{'type': 'family', 'what': 'I cannot collect Robin from hospital', 'quote': self.cancel}],
            at='2027-06-19T12:00:00+01:00', kind='note', topic='plan')

    def test_withdrawn_plan_sibling_event_is_not_shown_as_planned(self):
        ep = self.episode()
        self.withdraw(ep)
        self.assertEqual([(p['update_id'], p['plan_status']) for p in ep.plans()], [('cancel', 'withdrawn')])
        rows = T.event_entries(ep, 'alex', 'Europe/London')
        self.assertEqual([(row['update_id'], row.get('plan_status')) for row in rows], [('cancel', 'withdrawn')])
        hero = T.hero_html(ep, ep.status('Europe/London'), 'Europe/London', ep.members['alex'])
        self.assertIn('<span class="cr-fact-label">Plan withdrawn</span>', hero)
        self.assertNotIn('<span class="cr-fact-label">Planned</span>', hero)
        self.assertNotIn(self.old, html.unescape(hero))
        timeline = re.sub(r'<details\b.*?</details>', '', T.timeline_html(ep, 'alex', 'Europe/London'), flags=re.S)
        self.assertNotIn(self.old, html.unescape(timeline))
        self.assertIn(self.old, html.unescape(T.source_archive_html(ep)))   # the source itself is kept
        with self.subTest(control='an independent observation in the superseded plan note keeps its own row'):
            ep = self.episode(self.fall)
            self.withdraw(ep)
            rows = T.event_entries(ep, 'alex', 'Europe/London')
            self.assertEqual([row['headline'] for row in rows if row['update_id'] == 'old'], [self.fall])
        with self.subTest(control='the current plan still shows as planned'):
            rows = T.event_entries(self.episode(), 'alex', 'Europe/London')
            self.assertIn(('old', 'planned'), [(row['update_id'], row.get('plan_status')) for row in rows])


if __name__ == '__main__':
    unittest.main(verbosity=2)
