"""Portable projection policy regressions; synthetic inputs, no model or gold.

Run: python agent/test_event_selection_round2.py from handoff_day1.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode
from episode import Episode
import timeline_html as T

SCENARIO = {'patient': {'name': 'Robin', 'timezone': 'Europe/London'},
            'members': [{'member_id': 'relative', 'name': 'Alex', 'timezone': 'Europe/London'}], 'updates': []}


def setUpModule():
    print('EVENT_SELECTION_ROUND2 ' + json.dumps({
        'episode_path': episode.__file__, 'episode_sha256': hashlib.sha256(Path(episode.__file__).read_bytes()).hexdigest(),
        'timeline_path': T.__file__, 'timeline_sha256': hashlib.sha256(Path(T.__file__).read_bytes()).hexdigest()}), flush=True)


def add(ep, uid, text, facts, kind='recording', **extra):
    result = ep.add_update({'update_id': uid, 'kind': kind, 'author': 'relative',
                            'at': '2027-06-18T16:00:00+01:00', 'text': text, **extra}, facts=copy.deepcopy(facts))
    if result['rejected']:
        raise AssertionError(result['rejected'])
    return result


def generic(quote, what=None):
    return {'type': 'event', 'what': what or quote, 'quote': quote}


def lines(ep):
    return [line for row in T.event_entries(ep, 'relative', None) for line in row['lines']]


class EventImportance(unittest.TestCase):
    def test_clear_household_and_static_admin_stay_only_in_archive(self):
        for quote in ('I watered the house plants.', 'The kettle is broken.',
                      'The cafeteria opens at 07:30.', 'The Wi-Fi password is bluebird.',
                      'This is a duplicate upload with no new clinical information.'):
            with self.subTest(quote=quote):
                ep = Episode(SCENARIO)
                add(ep, 'noise', quote, [generic(quote)])
                before = copy.deepcopy(ep.to_snapshot())
                self.assertEqual(lines(ep), [])
                self.assertIn(T.esc(quote), T.source_archive_html(ep))
                self.assertEqual(ep.to_snapshot(), before)
                self.assertEqual(Episode.from_snapshot(before).to_snapshot(), before)

    def test_same_subject_with_actual_care_impact_is_kept(self):
        for quote in ('The broken lift prevents Robin reaching the ward.',
                      'The kettle spilled hot water and burned Robin.',
                      'Robin fell beside the cafeteria.',
                      'The router is broken so the nurse cannot review Robin remotely.'):
            with self.subTest(quote=quote):
                ep = Episode(SCENARIO)
                add(ep, 'care', quote, [generic(quote)])
                self.assertEqual(len(lines(ep)), 1)

    def test_symptom_function_safety_and_unknown_observation_are_retained_without_date(self):
        for quote in ('Robin suddenly has worse pain.', 'She walked using a frame.',
                      'He is coughing more.', 'The dressing looks unusual.',
                      'There is a new purple patch.', 'Robin feels unchanged.'):
            with self.subTest(quote=quote):
                ep = Episode(SCENARIO)
                add(ep, 'care', quote, [generic(quote)])
                actual, = lines(ep)
                self.assertEqual(actual['quote'], quote)
                self.assertIsNone(actual['event_time']['when'])

    def test_noncare_clause_does_not_hide_independent_unknown_observation(self):
        quote = 'The kettle is broken. There is a new purple patch.'
        ep = Episode(SCENARIO)
        add(ep, 'mixed', quote, [generic(quote)])
        self.assertEqual(len(lines(ep)), 1)

    def test_explicit_medication_start_change_stop_are_retained_as_history(self):
        ep = Episode(SCENARIO)
        for index, (status, action) in enumerate((('new', 'Start'), ('change', 'Change'), ('stop', 'Stop'))):
            quote = f'{action} Paracetamol 500 mg.'
            add(ep, str(index), quote, [{'type': 'medication', 'name': 'Paracetamol',
                                        'dose': '500 mg', 'status': status, 'quote': quote}])
        self.assertEqual([line['fact']['status'] for line in lines(ep)], ['stop', 'change', 'new'])

    def test_model_new_or_change_label_on_bare_medication_list_does_not_establish_a_change(self):
        for status in ('new', 'change'):
            ep = Episode(SCENARIO)
            quote = 'Paracetamol 500 mg.'
            add(ep, 'list', quote, [{'type': 'medication', 'name': 'Paracetamol',
                                    'dose': '500 mg', 'status': status, 'quote': quote}])
            self.assertEqual(lines(ep), [])
            self.assertIn(quote, T.source_archive_html(ep))


class AssertionDeduplication(unittest.TestCase):
    def test_one_admission_assertion_is_one_typed_event(self):
        ep = Episode(SCENARIO)
        quote = 'Robin was admitted to hospital on 12 June 2027.'
        add(ep, 'admit', quote, [generic(quote, 'Hospital admission'), {'type': 'admitted', 'quote': quote}])
        self.assertEqual([line['type'] for line in lines(ep)], ['admitted'])
        self.assertEqual(len(ep.entries[0]['lines']), 2)
        self.assertIn(quote, T.source_archive_html(ep))

    def test_same_procedure_completion_assertion_is_one_typed_event(self):
        ep = Episode(SCENARIO)
        quote = 'The ankle operation was completed on 13 June 2027 at 10:20.'
        add(ep, 'done', quote, [generic(quote, 'Ankle operation completed'),
                               {'type': 'procedure_done', 'what': 'ankle operation', 'quote': quote}])
        self.assertEqual([line['type'] for line in lines(ep)], ['procedure_done'])

    def test_discharge_restatement_folds_only_with_same_source_quote(self):
        ep = Episode(SCENARIO)
        quote = 'Robin was discharged home on 14 June 2027.'
        add(ep, 'home', quote, [generic(quote, 'Discharge home'), {'type': 'discharged', 'quote': quote}])
        self.assertEqual([line['type'] for line in lines(ep)], ['discharged'])

    def test_different_assertions_in_same_quote_are_not_folded(self):
        for quote, what in (
                ('Robin fell and was admitted on 12 June 2027.', 'Fall'),
                ('Robin fell and was admitted on 12 June 2027.', 'Hospital admission'),
                ('Robin was admitted after she fainted on 12 June 2027.', 'Hospital admission')):
            with self.subTest(quote=quote, what=what):
                ep = Episode(SCENARIO)
                add(ep, 'a', quote, [generic(quote, what), {'type': 'admitted', 'quote': quote}])
                self.assertEqual({line['type'] for line in lines(ep)}, {'event', 'admitted'})

    def test_independent_condition_and_multiple_dates_are_not_folded(self):
        for quote in ('If the bed is ready, Robin will be admitted on 19 June 2027.',
                      'Robin was admitted on 12 June 2027 and discharged on 14 June 2027.'):
            with self.subTest(quote=quote):
                ep = Episode(SCENARIO)
                add(ep, 'a', quote, [generic(quote, 'Hospital admission'), {'type': 'admitted', 'quote': quote}])
                self.assertEqual(len(lines(ep)), 2)

    def test_subquote_and_other_source_are_not_indiscriminately_folded(self):
        ep = Episode(SCENARIO)
        quote = 'Robin was admitted on 12 June 2027.'
        add(ep, 'generic', quote, [generic(quote, 'Hospital admission')])
        add(ep, 'typed', quote, [{'type': 'admitted', 'quote': quote}])
        self.assertEqual(len(lines(ep)), 2)
        other = Episode(SCENARIO)
        add(other, 'sub', quote, [generic('Robin was admitted', 'Hospital admission'), {'type': 'admitted', 'quote': quote}])
        self.assertEqual(len(lines(other)), 2)

    def test_same_quote_different_patient_observation_stays(self):
        ep = Episode(SCENARIO)
        quote = 'Robin was discharged home with a painful ankle on 14 June 2027.'
        add(ep, 'mixed', quote, [generic(quote, 'Painful ankle'), {'type': 'discharged', 'quote': quote}])
        self.assertEqual(len(lines(ep)), 2)

    def test_attached_symptom_is_not_hidden_by_a_generic_discharge_label(self):
        ep = Episode(SCENARIO)
        quote = 'Robin was discharged home with a painful ankle on 14 June 2027.'
        add(ep, 'mixed', quote, [generic(quote, 'Discharge home'), {'type': 'discharged', 'quote': quote}])
        self.assertEqual(len(lines(ep)), 2)

    def test_uncertain_clinical_date_is_not_deduplicated(self):
        ep = Episode(SCENARIO)
        quote = 'Robin was admitted on an unconfirmed date.'
        add(ep, 'unknown', quote, [generic(quote, 'Hospital admission'), {'type': 'admitted', 'quote': quote}])
        self.assertEqual(len(lines(ep)), 2)

    def test_projection_and_archive_do_not_mutate_journal(self):
        ep = Episode(SCENARIO)
        quote = 'Robin was admitted on 12 June 2027.'
        add(ep, 'a', quote, [generic(quote, 'Hospital admission'), {'type': 'admitted', 'quote': quote}])
        snapshot = copy.deepcopy(ep.to_snapshot())
        T.presentation_model(ep, 'relative', None)
        T.source_archive_html(ep)
        self.assertEqual(ep.to_snapshot(), snapshot)
        replayed = Episode.from_snapshot(snapshot)
        self.assertEqual(replayed.to_snapshot(), snapshot)
        self.assertEqual([line['type'] for line in lines(replayed)], ['admitted'])


class FulfilledBookingSelection(unittest.TestCase):
    def booking(self, ep, target='13 June 2027 at 08:20', uid='booking', what='ankle operation', kind='recording'):
        quote = f'The {what} is planned for {target}.'
        add(ep, uid, quote, [{'type': 'procedure_planned', 'what': what, 'quote': quote}], kind=kind)

    def done(self, ep, target='13 June 2027 at 10:20', uid='done', what='ankle operation', kind='recording'):
        quote = f'The {what} was completed on {target}.'
        add(ep, uid, quote, [{'type': 'procedure_done', 'what': what, 'quote': quote}], kind=kind)

    def test_fulfilled_booking_is_archived_but_completed_history_is_retained_in_both_orders(self):
        for done_first in (False, True):
            with self.subTest(done_first=done_first):
                ep = Episode(SCENARIO)
                if done_first:
                    self.done(ep)
                    self.booking(ep)
                else:
                    self.booking(ep)
                    self.done(ep)
                snapshot = copy.deepcopy(ep.to_snapshot())
                self.assertEqual([line['type'] for line in lines(ep)], ['procedure_done'])
                self.assertIn('planned for 13 June 2027 at 08:20', T.source_archive_html(ep))
                self.assertEqual(ep.to_snapshot(), snapshot)
                self.assertEqual([line['type'] for line in lines(Episode.from_snapshot(snapshot))], ['procedure_done'])

    def test_family_completion_does_not_fulfill_care_team_booking(self):
        for done_first in (False, True):
            ep = Episode(SCENARIO)
            if done_first:
                self.done(ep, kind='note')
                self.booking(ep)
            else:
                self.booking(ep)
                self.done(ep, kind='note')
            self.assertEqual({line['type'] for line in lines(ep)}, {'procedure_planned', 'procedure_done'})

    def test_future_and_repeat_and_different_site_booking_remain(self):
        for target, what in (('14 June 2027 at 08:20', 'ankle operation'),
                             ('13 June 2027 at 15:20', 'ankle operation'),
                             ('13 June 2027 at 08:20', 'repeat ankle operation'),
                             ('13 June 2027 at 08:20', 'wrist operation')):
            with self.subTest(target=target, what=what):
                ep = Episode(SCENARIO)
                self.done(ep)
                self.booking(ep, target, what=what)
                self.assertEqual({line['type'] for line in lines(ep)}, {'procedure_planned', 'procedure_done'})

    def test_core_link_to_different_site_is_not_enough_to_hide_booking(self):
        ep = Episode(SCENARIO)
        self.booking(ep, what='left ankle operation')
        self.done(ep, what='right ankle operation')
        self.assertEqual({line['type'] for line in lines(ep)}, {'procedure_planned', 'procedure_done'})

    def test_unknown_booking_or_completion_time_stays(self):
        for target, done_target in (('a date still to be confirmed', '13 June 2027 at 10:20'),
                                    ('13 June 2027 at 08:20', 'an unconfirmed date')):
            with self.subTest(target=target):
                ep = Episode(SCENARIO)
                self.booking(ep, target)
                self.done(ep, done_target)
                self.assertEqual({line['type'] for line in lines(ep)}, {'procedure_planned', 'procedure_done'})

    def test_completed_history_survives_a_later_admission(self):
        ep = Episode(SCENARIO)
        self.booking(ep)
        self.done(ep)
        quote = 'Robin was admitted again on 17 June 2027.'
        add(ep, 'readmit', quote, [{'type': 'admitted', 'quote': quote}])
        self.assertEqual({line['type'] for line in lines(ep)}, {'admitted', 'procedure_done'})

    def test_two_completed_occurrences_both_remain(self):
        ep = Episode(SCENARIO)
        self.booking(ep)
        self.done(ep)
        self.booking(ep, '15 June 2027 at 08:20', uid='booking2')
        self.done(ep, '15 June 2027 at 10:20', uid='done2')
        self.assertEqual([line['type'] for line in lines(ep)], ['procedure_done', 'procedure_done'])


class InitialAdmissionLocation(unittest.TestCase):
    def test_same_initial_assertion_is_one_admission_with_location_in_headline_and_source(self):
        ep = Episode(SCENARIO)
        quote = 'Robin was admitted to Elm Hospital on 12 June 2027 at 09:15.'
        add(ep, 'a', quote, [{'type': 'admitted', 'quote': quote},
                            {'type': 'location', 'hospital': 'Elm Hospital', 'quote': quote}])
        before = copy.deepcopy(ep.to_snapshot())
        row, = T.event_entries(ep, 'relative', None)
        self.assertEqual([line['type'] for line in row['lines']], ['admitted'])
        self.assertIn('Elm Hospital', row['headline'])
        self.assertIn(quote, T.source_archive_html(ep))
        self.assertEqual(ep.to_snapshot(), before)

    def test_actual_transfer_in_same_source_assertion_is_distinct(self):
        ep = Episode(SCENARIO)
        quote = 'Robin was admitted and then transferred to Elm Hospital on 12 June 2027.'
        add(ep, 'a', quote, [{'type': 'admitted', 'quote': quote},
                            {'type': 'location', 'hospital': 'Elm Hospital', 'quote': quote}])
        self.assertEqual({line['type'] for line in lines(ep)}, {'admitted', 'location'})

    def test_ward_move_and_initial_admission_with_distinct_quotes_and_dates_both_remain(self):
        ep = Episode(SCENARIO)
        admitted = 'Robin was admitted to Elm Hospital on 12 June 2027.'
        moved = 'Robin moved to Rowan ward on 13 June 2027.'
        add(ep, 'a', admitted + ' ' + moved,
            [{'type': 'admitted', 'quote': admitted}, {'type': 'location', 'unit': 'Rowan ward', 'quote': moved}])
        self.assertEqual({line['type'] for line in lines(ep)}, {'admitted', 'location'})
        self.assertEqual({line['event_time']['when'] for line in lines(ep)}, {'2027-06-12', '2027-06-13'})

    def test_unknown_chronology_does_not_fold_admission_location(self):
        ep = Episode(SCENARIO)
        quote = 'Robin was admitted to Elm Hospital on an unconfirmed date.'
        add(ep, 'a', quote, [{'type': 'admitted', 'quote': quote},
                            {'type': 'location', 'hospital': 'Elm Hospital', 'quote': quote}])
        self.assertEqual({line['type'] for line in lines(ep)}, {'admitted', 'location'})

    def test_separate_source_same_date_is_not_folded(self):
        ep = Episode(SCENARIO)
        quote = 'Robin was admitted to Elm Hospital on 12 June 2027.'
        add(ep, 'admission', quote, [{'type': 'admitted', 'quote': quote}])
        add(ep, 'location', quote, [{'type': 'location', 'hospital': 'Elm Hospital', 'quote': quote}])
        self.assertEqual({line['type'] for line in lines(ep)}, {'admitted', 'location'})


class WithdrawalDisplay(unittest.TestCase):
    def test_cancelled_target_date_is_labelled_without_claiming_cancellation_occurred_then(self):
        ep = Episode(SCENARIO)
        quote = 'I will visit on 20 June 2027 at 14:30.'
        add(ep, 'old', quote, [{'type': 'family', 'what': 'Family visit', 'quote': quote}], kind='note', topic='plan')
        cancel = 'I cannot come on 20 June 2027 at 14:30.'
        add(ep, 'cancel', cancel, [{'type': 'family', 'what': 'cannot come', 'quote': cancel}], kind='note', topic='plan',
            at='2027-06-19T16:00:00+01:00')
        plan, = ep.plans()
        snapshot = copy.deepcopy(ep.to_snapshot())
        row, = T.event_entries(ep, 'relative', None)
        self.assertEqual(row['event_time']['time_role'], 'withdrawn_target')
        self.assertEqual(row['supporting_sources'], plan['supporting_sources'])
        self.assertIn('Cancelled target', row['headline'])
        self.assertIn('20 Jun', row['headline'])
        self.assertNotIn('Date stated:', row['headline'])
        self.assertTrue(T.event_clock(row, 'Europe/London').startswith('Cancelled target:'))
        self.assertEqual({source['update_id'] for source in row['supporting_sources']}, {'old', 'cancel'})
        self.assertEqual({source['quote'] for source in row['supporting_sources']}, {quote, cancel})
        T.source_archive_html(ep)
        self.assertEqual(ep.to_snapshot(), snapshot)

    def test_unknown_cancellation_target_does_not_get_a_date_or_confirmed_label(self):
        ep = Episode(SCENARIO)
        quote = 'My visit is cancelled.'
        add(ep, 'cancel', quote, [{'type': 'family', 'what': 'visit cancelled', 'quote': quote}], kind='note', topic='plan')
        row, = T.event_entries(ep, 'relative', None)
        self.assertIsNone(row['event_time']['when'])
        self.assertEqual(row['event_time']['time_role'], 'withdrawal_reference')
        self.assertNotIn('Cancelled target:', row['headline'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
