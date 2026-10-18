"""Portable source-time and projection regressions. No model, network or gold."""
import copy
import hashlib
import html
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode
from episode import Episode, event_time, upgrade_episode
import episode_qa as Q
import timeline_html as T

SCENARIO = {'patient': {'name': 'Jules', 'home': 'at home', 'timezone': 'Europe/London'},
            'members': [{'member_id': 'relative', 'name': 'Alex', 'timezone': 'Europe/London'}], 'updates': []}


def setUpModule():
    print('TEMPORAL_PROGRAM_REPAIR_20261017_4FAMILIES ' + json.dumps({
        'loaded_episode': episode.__file__, 'episode_sha256': hashlib.sha256(Path(episode.__file__).read_bytes()).hexdigest(),
        'loaded_timeline': T.__file__, 'timeline_sha256': hashlib.sha256(Path(T.__file__).read_bytes()).hexdigest()}), flush=True)


def add(ep, uid, text, facts, *, plan=False, kind='recording', at='2027-02-20T16:00:00+00:00'):
    update = {'update_id': uid, 'kind': kind, 'author': 'relative', 'at': at, 'text': text}
    if plan:
        update['topic'] = 'plan'
    return ep.add_update(update, facts=copy.deepcopy(facts))


def family(text, quote=None):
    return {'type': 'family', 'what': 'Family visit', 'quote': quote or text}


class AssertionProjection(unittest.TestCase):
    def mixed(self):
        ep = Episode(SCENARIO)
        discharge = 'Jules left hospital and got home on 18 February 2027 at 15:35.'
        visit = 'I will visit on 23 February 2027 in the afternoon.'
        add(ep, 'mixed', discharge + ' ' + visit,
            [{'type': 'discharged', 'quote': discharge}, family(visit)], plan=True, kind='note')
        return ep, discharge, visit

    def test_mixed_assertions_have_distinct_dates_and_no_duplicated_clinical_headline(self):
        ep, discharge, visit = self.mixed()
        timing = event_time(ep, ep.entries[0], ep.entries[0]['lines'][1])
        self.assertEqual((timing['when'], timing['precision']), ('2027-02-23', 'part_of_day'))
        plan, = ep.plans()
        self.assertEqual((plan['text'], plan['event_time']['when']), (visit, '2027-02-23'))
        rows = T.event_entries(ep, 'relative', 'America/Toronto')
        self.assertEqual(len(rows), 2)
        clinical = next(row for row in rows if any(line['type'] == 'discharged' for line in row['lines']))
        self.assertEqual(clinical['event_time']['when'], '2027-02-18T15:35:00+00:00')
        self.assertFalse(T.shared_plan(clinical))
        planned = next(row for row in rows if T.shared_plan(row))
        self.assertNotIn(discharge, T.plan_headline(ep, planned))
        self.assertIn(discharge, T.source_details(planned))
        for zone in ('Europe/London', 'America/Toronto'):
            rendered = T.timeline_html(ep, 'relative', zone)
            self.assertIn('23 Feb 2027', rendered)
            self.assertIn('18 Feb 2027', rendered)
            self.assertIn('Discharged from hospital', rendered)

    def test_unextracted_second_intent_cannot_be_discarded(self):
        ep = Episode(SCENARIO)
        first = 'I will visit on 23 February 2027.'
        add(ep, 'p', first + ' I may come on 24 February 2027 instead.', [family(first)], plan=True, kind='note')
        self.assertEqual(ep.plans()[0]['event_time']['status'], 'pending_confirmation')

    def test_patient_observation_stays_visible_with_family_plan(self):
        ep = Episode(SCENARIO)
        patient = 'Jules slipped at home on 18 February 2027.'
        visit = 'I will visit on 23 February 2027.'
        add(ep, 'p', patient + ' ' + visit,
            [{'type': 'event', 'what': 'Slipped at home', 'quote': patient}, family(visit)], plan=True, kind='note')
        rows = T.event_entries(ep, 'relative', None)
        actual = next(row for row in rows if not T.shared_plan(row))
        self.assertEqual(actual['event_time']['when'], '2027-02-18')
        self.assertEqual(actual['headline'], patient)
        self.assertEqual(len(rows), 2)

    def test_generic_headline_uses_only_adjacent_original_terminal_punctuation(self):
        visit = 'I will visit on 23 February 2027.'
        quote = 'Jules is home and settled'
        for suffix, expected in (('. ', quote + '.'), ('! ', quote + '!'), (' at home. ', quote), (' ', quote)):
            with self.subTest(suffix=suffix):
                ep = Episode(SCENARIO)
                add(ep, 'p', quote + suffix + visit,
                    [{'type': 'event', 'what': 'Home and settled', 'quote': quote}, family(visit)], plan=True, kind='note')
                row = next(row for row in T.event_entries(ep, 'relative', None) if not T.shared_plan(row))
                self.assertEqual(row['headline'], expected)
                self.assertEqual(row['lines'][0]['fact']['quote'], quote)
                self.assertNotIn('23 February', row['headline'])

    def test_unrelated_negative_does_not_withdraw_affirmative_visit(self):
        ep = Episode(SCENARIO)
        first = 'Jules cannot drive on 20 February 2027.'
        visit = 'I will visit on 23 February 2027.'
        add(ep, 'p', first + ' ' + visit, [{'type': 'instruction', 'what': first, 'quote': first}, family(visit)], plan=True, kind='note')
        self.assertEqual(ep.plans()[0]['plan_status'], 'planned')
        self.assertEqual(ep.plans()[0]['event_time']['when'], '2027-02-23')

    def test_negation_and_condition_outside_short_quote_remain_in_assertion(self):
        for text, quote, expected in (
                ("I cannot come on 23 February 2027.", 'come on 23 February 2027', 'withdrawn'),
                ('If the road opens, I will visit on 23 February 2027.', 'I will visit on 23 February 2027', 'pending_confirmation')):
            with self.subTest(text=text):
                ep = Episode(SCENARIO)
                add(ep, 'p', text, [family(text, quote)], plan=True, kind='note')
                plan, = ep.plans()
                self.assertEqual(plan['text'], text)
                self.assertEqual(plan['plan_status'], expected)
                self.assertIn(quote, plan['text'])

    def test_multiple_targets_in_one_assertion_stay_pending(self):
        ep = Episode(SCENARIO)
        text = 'I will visit on 23 February or 24 February 2027.'
        add(ep, 'p', text, [family(text)], plan=True, kind='note')
        self.assertEqual(ep.plans()[0]['event_time']['status'], 'pending_confirmation')

    def test_adjacent_withdrawal_and_condition_keep_their_plan_referent(self):
        visit = 'I will visit on 23 February 2027.'
        for qualifier, expected in (('That visit is cancelled.', 'withdrawn'),
                                     ('It is cancelled.', 'withdrawn'),
                                     ('Only if the road opens.', 'pending_confirmation'),
                                     ('That plan is not confirmed.', 'pending_confirmation')):
            with self.subTest(qualifier=qualifier):
                ep = Episode(SCENARIO)
                text = visit + ' ' + qualifier
                add(ep, 'p', text, [family(visit)], plan=True, kind='note')
                plan, = ep.plans()
                self.assertEqual(plan['text'], text)
                self.assertEqual(plan['plan_status'], expected)
                timing = event_time(ep, ep.entries[0], ep.entries[0]['lines'][0])
                self.assertIn(qualifier, timing['source_context']['quote'])

    def test_separate_clinical_cancellation_does_not_cancel_visit(self):
        ep = Episode(SCENARIO)
        visit = 'I will visit on 23 February 2027.'
        clinical = 'The operation is cancelled on 20 February 2027.'
        add(ep, 'p', visit + ' ' + clinical, [family(visit)], plan=True, kind='note')
        self.assertEqual(ep.plans()[0]['text'], visit)
        self.assertEqual(ep.plans()[0]['plan_status'], 'planned')

    def test_revision_delete_and_snapshot_do_not_reuse_old_assertion(self):
        ep, discharge, visit = self.mixed()
        newer = 'I will visit on 25 February 2027 at 11:40.'
        ep.revise_update('mixed', {'text': discharge + ' ' + newer}, expected_revision=1, request_id='correction',
                         facts=[{'type': 'discharged', 'quote': discharge}, family(newer)])
        restored = Episode.from_snapshot(ep.to_snapshot())
        self.assertEqual(restored.plans()[0]['text'], newer)
        self.assertEqual(restored.plans()[0]['event_time']['when'], '2027-02-25T11:40:00+00:00')
        self.assertEqual(restored.plans()[0]['source_revision'], 2)
        restored.delete_update('mixed', expected_revision=2, request_id='delete')
        self.assertEqual(restored.plans(), [])
        self.assertEqual(T.event_entries(restored, 'relative', None), [])


class FamilyAssertionSupplementProjection(unittest.TestCase):
    def rows(self, ep):
        return T.event_entries(ep, 'relative', None)

    def test_ambiguous_arrival_assertion_does_not_duplicate_family_row(self):
        ep = Episode(SCENARIO)
        arrival = 'I will arrive on 08/09 in the evening.'
        text = arrival + ' I have not specified the date order.'
        add(ep, 'ambiguous', text, [{'type': 'event', 'what': 'arrival', 'quote': arrival}], plan=True, kind='note')
        rows = self.rows(ep)
        self.assertEqual(len(rows), 1)
        self.assertTrue(T.shared_plan(rows[0]))
        self.assertEqual(rows[0]['plan_status'], 'pending_confirmation')
        self.assertEqual(rows[0]['lines'], [])
        self.assertIn(arrival, T.source_details(rows[0]))

    def test_withdrawn_visit_does_not_resurface_as_an_old_generic_event(self):
        ep = Episode(SCENARIO)
        old = 'I am coming on 25 March 2027 at 16:10.'
        add(ep, 'old', old, [{'type': 'event', 'what': "family member's planned visit", 'quote': old}], plan=True, kind='note')
        cancel = 'I have cancelled my 25 March visit. I do not have another visit booked.'
        add(ep, 'withdrawn', cancel, [], plan=True, kind='note')
        events = copy.deepcopy(ep.events)
        rows = self.rows(ep)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['update_id'], 'withdrawn')
        self.assertEqual(rows[0]['plan_status'], 'withdrawn')
        self.assertEqual(rows[0]['lines'], [])
        self.assertEqual(ep.events, events)
        self.assertIn(old, T.source_archive_html(ep))

    def test_explicit_possessive_arrival_and_replacement_are_one_planned_family_assertion(self):
        ep = Episode(SCENARIO)
        arrival = 'My new arrival is 27 March 2027 at 12:45'
        replacement = 'replace my 25 March visit'
        text = arrival + '; ' + replacement + '.'
        add(ep, 'replacement', text, [{'type': 'event', 'what': 'new arrival', 'quote': arrival},
                                      {'type': 'event', 'what': 'replace 25 March visit', 'quote': replacement}], plan=True, kind='note')
        rows = self.rows(ep)
        self.assertEqual(len(rows), 1)
        self.assertTrue(T.shared_plan(rows[0]))
        self.assertEqual(rows[0]['plan_status'], 'planned')
        self.assertEqual(rows[0]['event_time']['when'], '2027-03-27T12:45:00+00:00')
        self.assertEqual(rows[0]['event_time']['temporal_status'], 'planned')
        self.assertEqual(rows[0]['lines'], [])
        self.assertIn(arrival, T.source_details(rows[0]))
        self.assertIn(replacement, T.source_details(rows[0]))

    def test_calendar_words_in_family_paraphrase_do_not_create_another_event(self):
        ep = Episode(SCENARIO)
        visit = 'I will visit on 25 March 2027 in the afternoon.'
        add(ep, 'p', visit, [{'type': 'event', 'what': 'Family visit on 25 March in the afternoon', 'quote': visit}], plan=True, kind='note')
        rows = self.rows(ep)
        self.assertEqual(len(rows), 1)
        self.assertTrue(T.shared_plan(rows[0]))
        self.assertEqual(rows[0]['event_time']['when'], '2027-03-25')

    def test_clinical_generic_events_remain_even_with_matching_family_words(self):
        for quote, what, extra in (
                ('Jules slipped at home on 18 February 2027.', 'Slipped at home', 'I will visit on 25 March 2027.'),
                ('The nurse visits Jules on 18 February 2027.', 'Nurse visit', 'I will visit on 25 March 2027.'),
                ('My nurse will visit on 18 February 2027.', 'visit', 'I will visit on 25 March 2027.'),
                ('I will visit Jules after the procedure on 25 March 2027.', 'Procedure follow-up visit', '')):
            with self.subTest(quote=quote):
                ep = Episode(SCENARIO)
                text = quote + (' ' + extra if extra else '')
                add(ep, 'p', text, [{'type': 'event', 'what': what, 'quote': quote}], plan=True, kind='note')
                rows = self.rows(ep)
                self.assertTrue(any(not T.shared_plan(row) and any(line['quote'] == quote for line in row['lines']) for row in rows))


class CompletedProcedureProjection(unittest.TestCase):
    what = 'ankle operation'

    def test_pending_procedure_label_escapes_untrusted_html(self):
        ep = Episode(SCENARIO)
        malicious = '<img src=x onerror="alert(1)"> ankle operation'
        completed = f'The {malicious} was completed on 16 February 2027 at 11:25.'
        done = add(ep, 'done', completed, [{'type': 'procedure_done', 'what': malicious, 'quote': completed}])
        self.assertEqual(done['rejected'], [])
        booking = f'The {malicious} is planned for a date still to be confirmed.'
        planned = add(ep, 'booking', booking, [{'type': 'procedure_planned', 'what': malicious, 'quote': booking}], kind='photo')
        self.assertEqual(planned['rejected'], [])
        self.assertEqual(ep.phase(), 'Current patient status needs confirmation')
        rendered = T.hero_html(ep, ep.status(), None, ep.members['relative'])
        self.assertIn(html.escape(malicious, quote=True), rendered)
        self.assertIn(html.escape(booking, quote=True), rendered)
        self.assertNotIn(malicious, rendered)
        self.assertNotIn('<img src=x', rendered)

    def completed(self, *, planned_first=False, kind='recording'):
        ep = Episode(SCENARIO)
        admitted = 'Jules was admitted on 15 February 2027 at 07:00.'
        add(ep, 'admitted', admitted, [{'type': 'admitted', 'quote': admitted}])
        if planned_first:
            self.booking(ep, 'booking', '16 February 2027 at 09:20')
        done = 'The ankle operation was completed on 16 February 2027 at 11:25.'
        add(ep, 'done', done, [{'type': 'procedure_done', 'what': self.what, 'quote': done}], kind=kind)
        return ep

    def booking(self, ep, uid, target, what=None):
        what = what or self.what
        quote = f'The {what} is planned for {target}.'
        return add(ep, uid, quote, [{'type': 'procedure_planned', 'what': what, 'quote': quote}], kind='photo')

    def test_late_earlier_booking_stays_history_and_recovery_is_current(self):
        for planned_first in (False, True):
            with self.subTest(planned_first=planned_first):
                ep = self.completed(planned_first=planned_first)
                result = self.booking(ep, 'old', '16 February 2027 at 09:20')
                self.assertEqual(ep.phase(), 'Recovering after ankle operation')
                self.assertEqual(len(ep.procedures), 1)
                self.assertEqual(ep.status()['next'], [])
                self.assertTrue(result['lines'][0]['late'])
                self.assertFalse(result['lines'][0]['applied'])
                self.assertIn('old', [record['update_id'] for record in next(iter(ep.procedures.values()))['history']])
                rows = T.event_entries(ep, 'relative', None)
                self.assertFalse(any(row['update_id'] == 'old' for row in rows))
                self.assertIn('16 February 2027 at 09:20', T.source_archive_html(ep))
                self.assertEqual(Episode.from_snapshot(ep.to_snapshot()).phase(), ep.phase())

    def test_late_booking_needs_confirmation_of_a_family_reported_completion(self):
        ep = self.completed(kind='note')
        self.booking(ep, 'late-clinician-booking', '16 February 2027 at 09:20')
        self.assertEqual(ep.phase(), 'Current patient status needs confirmation')
        self.assertEqual(len(ep.procedures), 1)
        self.assertTrue(ep.entries[-1]['lines'][0]['time_uncertain'])

    def test_completion_and_old_booking_are_authority_consistent_in_either_order(self):
        for kind in ('recording', 'note'):
            for done_first in (True, False):
                with self.subTest(kind=kind, done_first=done_first):
                    ep = Episode(SCENARIO)
                    quote = 'The ankle operation was completed on 16 February 2027 at 11:25.'
                    if not done_first:
                        self.booking(ep, 'booking', '16 February 2027 at 09:20')
                    add(ep, 'done', quote, [{'type': 'procedure_done', 'what': self.what, 'quote': quote}], kind=kind)
                    if done_first:
                        self.booking(ep, 'booking', '16 February 2027 at 09:20')
                    expected = ('Recovering after ankle operation' if kind == 'recording' else 'Current patient status needs confirmation')
                    self.assertEqual(ep.phase(), expected)
                    self.assertEqual(Episode.from_snapshot(ep.to_snapshot()).phase(), expected)
                    self.assertEqual(len(ep.procedures), 1)
                    self.assertEqual({e['authority'] for e in ep.entries}, {'care_team'} if kind == 'recording' else {'care_team', 'family'})
                    if kind == 'note':
                        p, = ep.procedures.values()
                        self.assertTrue(p['time_uncertain'])
                        self.assertEqual({p['update_id'], *(a['update_id'] for a in p['uncertain_alternatives'])}, {'booking', 'done'})
                        hero = T.hero_html(ep, ep.status(), None, ep.members['relative'])
                        self.assertIn('Completion is reported by family', hero)
                        self.assertIn('confirm', hero.lower())
                        self.assertIn('16 February 2027 at 09:20', hero)
                        self.assertIn('16 February 2027 at 11:25', hero)

    def test_care_team_can_confirm_the_same_family_reported_completion(self):
        for done_first in (True, False):
            with self.subTest(done_first=done_first):
                ep = Episode(SCENARIO)
                quote = 'The ankle operation was completed on 16 February 2027 at 11:25.'
                if not done_first:
                    self.booking(ep, 'booking', '16 February 2027 at 09:20')
                add(ep, 'done', quote, [{'type': 'procedure_done', 'what': self.what, 'quote': quote}], kind='note')
                if done_first:
                    self.booking(ep, 'booking', '16 February 2027 at 09:20')
                add(ep, 'confirmed', quote, [{'type': 'procedure_done', 'what': self.what, 'quote': quote}], kind='recording')
                self.assertEqual(ep.phase(), 'Recovering after ankle operation')
                self.assertEqual(len(ep.procedures), 1)
                self.assertFalse(next(iter(ep.procedures.values())).get('time_uncertain'))
                units = Q.sentence_units(ep)
                old_report = next(u for u in units if u['update_id'] == 'done')
                self.assertNotEqual(old_report['state'], 'time_uncertain')
                cited = Q.complete([old_report['sid']], units, 'Was the ankle operation completed?')
                by_sid = {u['sid']: u for u in units}
                self.assertIn('confirmed', {by_sid[sid]['update_id'] for sid in cited})

    def test_uncertain_old_booking_does_not_hide_later_clinical_discharge(self):
        ep = self.completed()
        self.booking(ep, 'undated', 'a date still to be confirmed')
        self.assertEqual(ep.phase(), 'Current patient status needs confirmation')
        quote = 'Jules was discharged home on 19 February 2027 at 14:20.'
        add(ep, 'home', quote, [{'type': 'discharged', 'quote': quote}])
        self.assertEqual(ep.phase(), 'Home after hospital')
        self.assertNotIn('Current state needs confirmation', T.hero_html(ep, ep.status(), None, ep.members['relative']))

    def test_clinical_completion_can_resolve_unknown_old_booking(self):
        ep = self.completed()
        self.booking(ep, 'undated', 'a date still to be confirmed')
        quote = 'The ankle operation was completed on 16 February 2027 at 11:25.'
        add(ep, 'confirmed', quote, [{'type': 'procedure_done', 'what': self.what, 'quote': quote}])
        self.assertEqual(ep.phase(), 'Recovering after ankle operation')
        self.assertFalse(next(iter(ep.procedures.values())).get('time_uncertain'))

    def test_qa_cannot_choose_only_one_uncertain_procedure_source(self):
        for done_first in (True, False):
            with self.subTest(done_first=done_first):
                ep = Episode(SCENARIO)
                quote = 'The ankle operation was completed on 16 February 2027 at 11:25.'
                if not done_first:
                    self.booking(ep, 'booking', '16 February 2027 at 09:20')
                add(ep, 'done', quote, [{'type': 'procedure_done', 'what': self.what, 'quote': quote}], kind='note')
                if done_first:
                    self.booking(ep, 'booking', '16 February 2027 at 09:20')
                units = Q.sentence_units(ep)
                relevant = [u for u in units if u['update_id'] in {'booking', 'done'}]
                self.assertEqual({u['state'] for u in relevant}, {'time_uncertain'})
                class OneCitation:
                    model = 'injected-one-citation-fixture'
                    def chat(self, *args, **kwargs):
                        proposal = {'covered': 'yes', 'citations': ['done.1']}
                        return {'json': proposal, 'text': json.dumps(proposal), 'finish_reason': 'stop', 'usage': {}}
                answer = Q.episode_answerer(OneCitation())(ep, 'Was the ankle operation completed?', 'relative')
                self.assertEqual({u['update_id'] for u in answer['quotes']}, {'booking', 'done'})
                self.assertIn('Completion is reported by family', answer['answer'])
                by_sid = {u['sid']: u for u in relevant}
                self.assertIn('CONFIRMATION', Q.label_text(by_sid['done.1'], by_sid))
                self.assertIn('confirm', Q.display_label(by_sid['done.1'], by_sid, None).lower())
                self.assertEqual(Episode.from_snapshot(ep.to_snapshot()).phase(), ep.phase())

    def test_a_genuinely_later_booking_does_not_confirm_or_erase_prior_family_completion(self):
        ep = self.completed(kind='note')
        self.booking(ep, 'next-operation', '18 February 2027 at 09:20')
        self.assertEqual(ep.phase(), 'Waiting for ankle operation')
        self.assertEqual([p['status'] for p in ep.procedures.values()], ['done', 'planned'])

    def test_a_new_later_occurrence_and_distinct_procedure_remain_planned(self):
        for target, what in (('18 February 2027 at 09:20', None),
                             ('16 February 2027 at 15:20', None),
                             ('18 February 2027 at 09:20', 'wrist operation')):
            with self.subTest(target=target, what=what):
                ep = self.completed()
                self.booking(ep, 'new', target, what)
                self.assertEqual(len(ep.procedures), 2)
                self.assertTrue(ep.phase().startswith('Waiting for'))

    def test_second_occurrence_can_complete_without_losing_first_history(self):
        ep = self.completed()
        self.booking(ep, 'second', '18 February 2027 at 09:20')
        quote = 'The ankle operation was completed on 18 February 2027 at 11:25.'
        add(ep, 'done2', quote, [{'type': 'procedure_done', 'what': self.what, 'quote': quote}])
        self.assertEqual([p['status'] for p in ep.procedures.values()], ['done', 'done'])
        self.assertEqual(ep.status()['next'], [])
        self.assertEqual(ep.phase(), 'Recovering after ankle operation')

    def test_unknown_target_cannot_establish_a_second_operation(self):
        ep = self.completed()
        self.booking(ep, 'unclear', 'a date still to be confirmed')
        self.assertEqual(ep.phase(), 'Current patient status needs confirmation')
        self.assertFalse(ep.entries[-1]['lines'][0]['applied'])

    def test_correcting_or_deleting_old_booking_rebuilds_occurrence_decision(self):
        ep = self.completed()
        self.booking(ep, 'booking', '16 February 2027 at 09:20')
        quote = 'The ankle operation is planned for 18 February 2027 at 09:20.'
        ep.revise_update('booking', {'text': quote}, expected_revision=1, request_id='new-date',
                         facts=[{'type': 'procedure_planned', 'what': self.what, 'quote': quote}])
        self.assertEqual(ep.phase(), 'Waiting for ankle operation')
        ep.delete_update('booking', expected_revision=2, request_id='remove-booking')
        self.assertEqual(ep.phase(), 'Recovering after ankle operation')
        self.assertEqual(len(ep.procedures), 1)

    def test_upgrade_rebuilds_stale_live_projection_and_qa_cache(self):
        ep = self.completed()
        self.booking(ep, 'old', '16 February 2027 at 09:20')
        answer = Q.episode_answerer(None)(ep, 'What happened with the operation?', 'relative')
        answer['identity']['version'] = 'revision-bound-event-time-v2'
        ep._temporal_projection = 'source-event-time-v2'
        ep.procedures['stale_planned_fixture'] = {'status': 'planned', 'what': 'stale fixture'}
        restored = upgrade_episode(ep)
        self.assertIs(restored, ep)
        self.assertNotIn('stale_planned_fixture', ep.procedures)
        self.assertEqual(ep.phase(), 'Recovering after ankle operation')
        self.assertNotEqual(Q.refresh(ep, answer)['identity']['version'], 'revision-bound-event-time-v2')


if __name__ == '__main__':
    unittest.main(verbosity=2)
