"""Source-grounded discharge/current-hospital conflicts, independent fictional data."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode
from episode import Episode, grounding_problem
import episode_qa as Q

SCENARIO = {'patient': {'name': 'Sam', 'home': 'at home', 'timezone': 'Europe/London'},
            'members': [{'member_id': 'alex', 'name': 'Alex'}], 'updates': []}
HOME = 'Sam left for home on 4 May 2028 at 10:15.'
STILL = 'Sam was still admitted at 10:15 on 4 May 2028 and had not left the hospital.'


def setUpModule():
    print('STATE_CONFLICTS_ROUND2_LEFT_FOR_HOME_V1 ' + json.dumps({
        'loaded_episode': episode.__file__, 'sha256': hashlib.sha256(Path(episode.__file__).read_bytes()).hexdigest()}), flush=True)


def add(ep, uid, text, typ, *, at='2028-05-05T11:00:00+01:00', kind='recording', speaker=None):
    return ep.add_update({'update_id': uid, 'kind': kind, 'author': 'alex', 'at': at, 'text': text,
                          'speaker': speaker or uid}, facts=[{'type': typ, 'quote': text}])


def conflict(order):
    ep = Episode(SCENARIO)
    for uid in order:
        add(ep, uid, HOME if uid == 'home' else STILL, 'discharged' if uid == 'home' else 'admitted')
    return ep


class CompletedDepartureWords(unittest.TestCase):
    def test_numbered_may_calendar_is_not_uncertain_confirmation(self):
        for date in ('4 May 2028', 'May 4, 2028', '14th of May 2028'):
            with self.subTest(date=date):
                text = f'The record was checked and confirmed: Sam left for home on {date}.'
                self.assertEqual(Episode._confirmation({'type': 'discharged', 'quote': text}, {'text': text}), (True, False))

    def test_true_modal_may_survives_numbered_may_date(self):
        for text in ('The record may be confirmed: Sam left for home on 4 May 2028.',
                     'Sam may have left for home on May 4, 2028; the record is confirmed.',
                     'The record is confirmed if Sam left for home on 4 May 2028.'):
            with self.subTest(text=text):
                self.assertEqual(Episode._confirmation({'type': 'discharged', 'quote': text}, {'text': text}), (False, True))

    def test_may_name_and_invalid_calendar_are_not_erased(self):
        for text in ('May confirmed the discharge record on 4 June 2028.',
                     'The record was confirmed: Sam left for home on 32 May 2028.'):
            with self.subTest(text=text):
                self.assertEqual(Episode._confirmation({'type': 'discharged', 'quote': text}, {'text': text}), (False, True))

    def test_left_for_home_is_completed_departure(self):
        ep = Episode(SCENARIO)
        entry = add(ep, 'home', HOME, 'discharged')
        self.assertEqual(entry['rejected'], [])
        self.assertEqual(ep.phase(), 'Home after hospital')
        self.assertEqual(ep.slots['discharged']['event_time']['when'], '2028-05-04T10:15:00+01:00')

    def test_left_home_for_hospital_is_not_a_discharge(self):
        ep = Episode(SCENARIO)
        entry = add(ep, 'inbound', 'Sam left home for the hospital on 4 May 2028 at 10:15.', 'discharged')
        self.assertTrue(entry['rejected'])
        self.assertNotIn('discharged', ep.slots)

    def test_negation_future_and_condition_are_not_completed_departures(self):
        for text in ('Sam has not left for home on 4 May 2028.',
                     'Sam never left for home on 4 May 2028.',
                     'Sam will leave for home on 4 May 2028.',
                     'Sam will have left for home on 4 May 2028.',
                     'If transport comes, Sam left for home on 4 May 2028.',
                     'Sam left for home on 4 May 2028 if transport comes.'):
            with self.subTest(text=text):
                ep = Episode(SCENARIO)
                entry = add(ep, 'unconfirmed', text, 'discharged')
                self.assertTrue(entry['rejected'])
                self.assertNotIn('discharged', ep.slots)

    def test_future_dated_completed_departure_stays_pending(self):
        ep = Episode(SCENARIO)
        entry = add(ep, 'future', HOME.replace('4 May', '8 May'), 'discharged')
        self.assertTrue(entry['rejected'] or not entry['lines'][0]['applied'])
        self.assertNotIn('discharged', ep.slots)


class CurrentStateConflicts(unittest.TestCase):
    def test_same_clock_current_hospital_and_departure_are_pending_in_both_orders(self):
        for order in (('home', 'hospital'), ('hospital', 'home')):
            with self.subTest(order=order):
                ep = conflict(order)
                self.assertEqual(ep.phase(), 'Current patient status needs confirmation')
                records = [r for r in ep.slots.values() if r.get('time_uncertain')]
                claims = {(r['update_id'], r['fact']['quote']) for r in records}
                claims.update((alt['update_id'], alt['fact']['quote']) for r in records for alt in r.get('uncertain_alternatives', []))
                self.assertIn(('home', HOME), claims)
                self.assertIn(('hospital', STILL), claims)

    def test_both_sources_are_linked_in_question_evidence(self):
        for order in (('home', 'hospital'), ('hospital', 'home')):
            with self.subTest(order=order):
                units = Q.sentence_units(conflict(order))
                affected = [u for u in units if u['update_id'] in {'home', 'hospital'}]
                self.assertEqual({u['state'] for u in affected}, {'time_uncertain'})
                self.assertEqual({u['update_id'] for u in affected}, {'home', 'hospital'})
                self.assertTrue(all(u['siblings'] for u in affected))

    def test_date_only_same_day_order_is_not_invented(self):
        for first in ('home', 'hospital'):
            with self.subTest(first=first):
                ep = Episode(SCENARIO)
                texts = {'home': ('Sam was discharged home on 4 May 2028.', 'discharged'),
                         'hospital': ('Sam was admitted on 4 May 2028.', 'admitted')}
                for uid in (first, 'hospital' if first == 'home' else 'home'):
                    add(ep, uid, *texts[uid])
                self.assertEqual(ep.phase(), 'Current patient status needs confirmation')

    def test_confirmed_later_event_dates_establish_order_in_both_arrival_orders(self):
        for order in (('home', 'hospital'), ('hospital', 'home')):
            with self.subTest(order=order):
                ep = Episode(SCENARIO)
                for uid in order:
                    if uid == 'home':
                        add(ep, uid, 'Sam was discharged home on 3 May 2028 at 10:15.', 'discharged')
                    else:
                        add(ep, uid, 'Sam was readmitted on 4 May 2028 at 08:25.', 'admitted')
                self.assertEqual(ep.phase(), 'Admitted to hospital')
                self.assertNotIn('discharged', ep.slots)

    def test_later_discharge_after_old_admission_is_home(self):
        ep = Episode(SCENARIO)
        add(ep, 'old', 'Sam was admitted on 3 May 2028 at 08:25.', 'admitted')
        add(ep, 'home', HOME, 'discharged')
        self.assertEqual(ep.phase(), 'Home after hospital')

    def test_explicit_later_clinical_discharge_clarification_resolves_both_orders(self):
        text = 'The discharge record was checked and confirmed: Sam left for home on 4 May 2028 at 10:15 and she is now at home.'
        plain = 'The discharge record was checked and confirmed: Sam left for home on 4 May 2028 at 10:15.'
        # Demo product decision (2026-10-17): a care-team checked departure settles the same-clock
        # inpatient claim with or without the continuing post-discharge wording.
        for order in (('home', 'hospital'), ('hospital', 'home')):
            for wording in (text, plain):
                with self.subTest(order=order, wording=wording):
                    ep = conflict(order)
                    entry = add(ep, 'clarified', wording, 'discharged', at='2028-05-05T12:00:00+01:00')
                    self.assertEqual(entry['rejected'], [])
                    self.assertEqual(ep.phase(), 'Home after hospital')
                    self.assertEqual(ep.slots['discharged']['update_id'], 'clarified')
                    self.assertFalse(any(r.get('time_uncertain') for r in ep.slots.values()))
                    self.assertEqual(Episode.from_snapshot(ep.to_snapshot()).phase(), 'Home after hospital')

    def test_repeating_discharge_without_clarification_does_not_settle(self):
        ep = conflict(('home', 'hospital'))
        add(ep, 'repeated', HOME, 'discharged', at='2028-05-05T12:00:00+01:00')
        self.assertEqual(ep.phase(), 'Current patient status needs confirmation')

    def test_conditional_or_negated_confirmation_cannot_resolve(self):
        for prefix in ('The discharge record has not been confirmed: ',
                       'If the record is confirmed, ', 'The discharge record will be confirmed: '):
            with self.subTest(prefix=prefix):
                ep = conflict(('hospital', 'home'))
                add(ep, 'unresolved', prefix + HOME, 'discharged', at='2028-05-05T12:00:00+01:00')
                self.assertEqual(ep.phase(), 'Current patient status needs confirmation')

    def test_family_report_does_not_override_a_care_team_hospital_state(self):
        ep = Episode(SCENARIO)
        add(ep, 'hospital', STILL, 'admitted')
        entry = add(ep, 'family-home', HOME, 'discharged', kind='note', speaker='Nurse in note')
        self.assertEqual(entry['authority'], 'family')
        self.assertEqual(entry['rejected'], [])
        self.assertFalse(entry['lines'][0]['applied'])
        self.assertNotEqual(ep.phase(), 'Home after hospital')

    def test_family_hospital_report_does_not_create_clinical_conflict_with_home(self):
        ep = Episode(SCENARIO)
        add(ep, 'home', HOME, 'discharged')
        add(ep, 'family-hospital', STILL, 'admitted', kind='note')
        self.assertEqual(ep.phase(), 'Home after hospital')

    def test_deleting_one_conflicting_source_rebuilds_remaining_state(self):
        ep = conflict(('home', 'hospital'))
        ep.delete_update('hospital', expected_revision=1, request_id='remove-wrong-record')
        self.assertEqual(ep.phase(), 'Home after hospital')
        self.assertEqual(Episode.from_snapshot(ep.to_snapshot()).phase(), 'Home after hospital')

    def test_revision_changes_collision_into_ordered_readmission(self):
        ep = conflict(('home', 'hospital'))
        corrected = 'Sam was readmitted on 5 May 2028 at 08:25.'
        ep.revise_update('hospital', {'text': corrected}, expected_revision=1, request_id='correct-readmission',
                         facts=[{'type': 'admitted', 'quote': corrected}])
        self.assertEqual(ep.phase(), 'Admitted to hospital')
        self.assertNotIn('discharged', ep.slots)


class ClarificationQuestions(unittest.TestCase):
    # A care-team checked discharge settles the same-clock collision; this
    # fixture also asserts the continuing post-discharge state.
    text = 'The discharge record was checked and confirmed: Sam left for home on 4 May 2028 at 10:15 and she is now at home.'

    def clarified(self):
        ep = conflict(('home', 'hospital'))
        add(ep, 'clarified', self.text, 'discharged', at='2028-05-05T12:00:00+01:00')
        return ep

    def test_resolved_old_sentence_links_to_current_clinical_confirmation(self):
        ep = self.clarified()
        self.assertEqual(ep.phase(), 'Home after hospital')
        units = Q.sentence_units(ep)
        self.assertEqual(next(u for u in units if u['update_id'] == 'clarified')['state'], 'current')
        self.assertTrue(all(u['state'] != 'time_uncertain' for u in units))
        old = next(u for u in units if u['update_id'] == 'hospital')
        by_sid = {u['sid']: u for u in units}
        cited = Q.complete([old['sid']], units, 'Where is Sam now?')
        self.assertIn('clarified', {by_sid[sid]['update_id'] for sid in cited})

    def test_forced_old_model_citation_brings_new_confirmation_and_no_stale_pending(self):
        ep = self.clarified()
        class SelectOld:
            model = 'injected-old-state-citation'
            def chat(self, *args, **kwargs):
                prop = {'covered': 'yes', 'citations': ['hospital.1']}
                return {'json': prop, 'text': json.dumps(prop), 'finish_reason': 'stop', 'usage': {}}
        result = Q.episode_answerer(SelectOld())(ep, 'Where is Sam now?', 'alex')
        self.assertIn('clarified', {u['update_id'] for u in result['quotes']})
        self.assertNotIn('need confirmation', result['answer'])
        self.assertNotIn('needs confirmation', result['answer'])
        self.assertTrue(all(u['state'] != 'time_uncertain' for u in result['quotes']))

    def test_deleting_confirmation_reopens_uncertainty_and_invalidates_old_answer(self):
        ep = self.clarified()
        result = Q.episode_answerer(None)(ep, 'Where is Sam now?', 'alex')
        ep.delete_update('clarified', expected_revision=1, request_id='withdraw-clarification')
        refreshed = Q.refresh(ep, result)
        self.assertEqual(ep.phase(), 'Current patient status needs confirmation')
        self.assertEqual({u['update_id'] for u in refreshed['quotes']}, {'home', 'hospital'})
        self.assertTrue(all(u['state'] == 'time_uncertain' for u in refreshed['quotes']))
        self.assertIn('need confirmation', refreshed['answer'])

    def test_correcting_confirmation_reopens_uncertainty_with_new_revision(self):
        ep = self.clarified()
        result = Q.episode_answerer(None)(ep, 'Where is Sam now?', 'alex')
        text = 'The discharge record has not been confirmed: Sam left for home on 4 May 2028 at 10:15.'
        ep.revise_update('clarified', {'text': text}, expected_revision=1, request_id='correct-confirmation',
                         facts=[{'type': 'discharged', 'quote': text}])
        refreshed = Q.refresh(ep, result)
        self.assertEqual(ep.phase(), 'Current patient status needs confirmation')
        self.assertIn('need confirmation', refreshed['answer'])
        self.assertTrue(all(u.get('source_revision') == 2 for u in refreshed['quotes'] if u['update_id'] == 'clarified'))


class ReverseClarification(unittest.TestCase):
    home = 'Taylor left for home on 17 June 2029 at 10:35.'
    hospital = 'Taylor was still admitted on 17 June 2029 at 10:35.'
    clarified = 'The inpatient record was checked and confirmed: Taylor was still admitted on 17 June 2029 at 10:35.'
    place = 'The inpatient record was checked and confirmed: Taylor was an inpatient at Pine Hospital on 17 June 2029 at 10:35.'

    def episode(self, order=('home', 'hospital')):
        scenario = copy.deepcopy(SCENARIO)
        scenario['patient']['name'] = 'Taylor'
        ep = Episode(scenario)
        for uid in order:
            add(ep, uid, self.home if uid == 'home' else self.hospital,
                'discharged' if uid == 'home' else 'admitted', at='2029-06-18T09:00:00+01:00')
        return ep

    def confirm(self, ep, text=None, kind='recording', typ='admitted'):
        text = text or self.clarified
        facts = [{'type': typ, 'quote': text}]
        if typ == 'location':
            facts[0]['hospital'] = 'Pine Hospital'
        return ep.add_update({'update_id': 'checked', 'kind': kind, 'author': 'alex', 'speaker': 'Clinician',
                              'at': '2029-06-18T10:00:00+01:00', 'text': text}, facts=facts)

    def test_checked_hospital_state_retires_discharge_in_both_orders(self):
        for order in (('home', 'hospital'), ('hospital', 'home')):
            with self.subTest(order=order):
                ep = self.episode(order)
                entry = self.confirm(ep)
                self.assertTrue(entry['lines'][0]['applied'])
                self.assertEqual(ep.phase(), 'Admitted to hospital')
                self.assertNotIn('discharged', ep.slots)
                self.assertNotIn('location', ep.slots)  # the derived home location is also retired
                self.assertTrue(any(u['text'] == self.home for u in ep.updates))
                self.assertEqual(Episode.from_snapshot(ep.to_snapshot()).phase(), 'Admitted to hospital')

    def test_checked_inpatient_location_retires_home_without_inventing_admission_fact(self):
        for order in (('home', 'hospital'), ('hospital', 'home')):
            with self.subTest(order=order):
                ep = self.episode(order)
                self.confirm(ep, self.place, typ='location')
                self.assertNotIn('discharged', ep.slots)
                self.assertEqual(ep.slots['location']['fact']['hospital'], 'Pine Hospital')
                self.assertEqual(ep.phase(), 'Admitted to hospital')
                self.assertFalse(any(r.get('time_uncertain') for r in ep.slots.values()))

    def test_bare_clinical_hospital_location_does_not_invent_inpatient_status(self):
        ep = self.episode()
        text = 'The location record was checked and confirmed: Taylor was at Pine Hospital on 17 June 2029 at 10:35.'
        self.confirm(ep, text, typ='location')
        # Being at the hospital at the departure clock neither orders nor
        # retracts that departure: the care-team discharge stays unresolved.
        self.assertIn('discharged', ep.slots)
        self.assertEqual(ep.phase(), 'Current patient status needs confirmation')
        self.assertNotEqual(ep.phase(), 'Admitted to hospital')
        self.assertNotIn('admitted', ep.slots)

    def test_uncertain_negated_family_or_other_subject_inpatient_does_not_promote_hospital(self):
        for text, kind in ((self.place, 'note'),
                           (self.place.replace('was an inpatient', 'might be an inpatient'), 'recording'),
                           (self.place.replace('was an inpatient', 'was not an inpatient'), 'recording'),
                           (self.place.replace('was an inpatient', 'will be an inpatient'), 'recording'),
                           (self.place.replace('Taylor was', 'If Taylor was'), 'recording'),
                           (self.place.replace('Taylor was', 'Rory was'), 'recording')):
            with self.subTest(text=text, kind=kind):
                scenario = copy.deepcopy(SCENARIO)
                scenario['patient']['name'] = 'Taylor'
                ep = Episode(scenario)
                self.confirm(ep, text, kind, 'location')
                self.assertNotEqual(ep.phase(), 'Admitted to hospital')

    def test_forced_old_home_citation_brings_checked_hospital_statement(self):
        ep = self.episode()
        self.confirm(ep)
        class SelectOld:
            model = 'injected-old-home-citation'
            def chat(self, *args, **kwargs):
                prop = {'covered': 'yes', 'citations': ['home.1']}
                return {'json': prop, 'text': json.dumps(prop), 'finish_reason': 'stop', 'usage': {}}
        result = Q.episode_answerer(SelectOld())(ep, 'Where is Taylor now?', 'alex')
        self.assertIn('checked', {u['update_id'] for u in result['quotes']})
        self.assertTrue(all(u['state'] != 'time_uncertain' for u in result['quotes']))
        old = next(u for u in result['quotes'] if u['update_id'] == 'home')
        self.assertEqual(old['state'], 'earlier')

    def test_false_or_family_confirmation_does_not_retire_discharge(self):
        for text, kind in ((self.clarified, 'note'),
                           (self.clarified.replace('was checked and confirmed', 'might be confirmed'), 'recording'),
                           (self.clarified.replace('17 June', '16 June'), 'recording')):
            with self.subTest(text=text, kind=kind):
                ep = self.episode()
                self.confirm(ep, text, kind)
                self.assertEqual(ep.phase(), 'Current patient status needs confirmation')
                self.assertIn('discharged', ep.slots)

    def test_deleting_hospital_clarification_reopens_both_claims(self):
        ep = self.episode()
        self.confirm(ep)
        ep.delete_update('checked', expected_revision=1, request_id='delete-checked')
        restored = Episode.from_snapshot(ep.to_snapshot())
        self.assertEqual(restored.phase(), 'Current patient status needs confirmation')
        self.assertEqual({u['state'] for u in Q.sentence_units(restored)}, {'time_uncertain'})


class HistoricalClarificationLinks(unittest.TestCase):
    text = ClarificationQuestions.text

    def episode(self):
        ep = conflict(('home', 'hospital'))
        add(ep, 'clarified', self.text, 'discharged', at='2028-05-05T12:00:00+01:00')
        add(ep, 'readmitted', 'Sam was readmitted on 6 May 2028 at 08:20.', 'admitted', at='2028-05-07T09:00:00+01:00')
        return ep

    def test_later_readmission_keeps_old_conflict_resolved_and_links_current_hospital(self):
        for restore in (False, True):
            with self.subTest(restore=restore):
                ep = self.episode()
                if restore:
                    ep = Episode.from_snapshot(ep.to_snapshot())
                self.assertEqual(ep.phase(), 'Admitted to hospital')
                units = Q.sentence_units(ep)
                self.assertTrue(all(u['state'] != 'time_uncertain' for u in units))
                old = next(u for u in units if u['update_id'] == 'hospital')
                by_sid = {u['sid']: u for u in units}
                cited = Q.complete([old['sid']], units, 'Where is Sam now?')
                self.assertIn('readmitted', {by_sid[sid]['update_id'] for sid in cited})

    def test_deleting_readmission_restores_the_still_valid_home_clarification(self):
        ep = self.episode()
        ep.delete_update('readmitted', expected_revision=1, request_id='remove-readmission')
        self.assertEqual(ep.phase(), 'Home after hospital')
        self.assertTrue(all(u['state'] != 'time_uncertain' for u in Q.sentence_units(ep)))

    def test_second_checked_resolution_keeps_oldest_claim_linked_to_latest_confirmation(self):
        for order in (('home', 'hospital'), ('hospital', 'home')):
            for restore in (False, True):
                with self.subTest(order=order, restore=restore):
                    ep = conflict(order)
                    add(ep, 'clarified', self.text, 'discharged', at='2028-05-05T12:00:00+01:00')
                    add(ep, 'second-hospital', STILL, 'admitted', at='2028-05-05T13:00:00+01:00')
                    self.assertEqual(ep.phase(), 'Current patient status needs confirmation')
                    add(ep, 'second-checked', self.text, 'discharged', at='2028-05-05T14:00:00+01:00')
                    if restore:
                        ep = Episode.from_snapshot(ep.to_snapshot())
                    self.assertEqual(ep.phase(), 'Home after hospital')
                    class SelectOld:
                        model = 'injected-oldest-hospital-citation'
                        def chat(self, *args, **kwargs):
                            prop = {'covered': 'yes', 'citations': ['hospital.1']}
                            return {'json': prop, 'text': json.dumps(prop), 'finish_reason': 'stop', 'usage': {}}
                    result = Q.episode_answerer(SelectOld())(ep, 'Where is Sam now?', 'alex')
                    self.assertIn('second-checked', {u['update_id'] for u in result['quotes']})
                    self.assertTrue(all(u['state'] != 'time_uncertain' for u in result['quotes']))
                    self.assertNotIn('need confirmation', result['answer'])

    def test_revised_hospital_claim_preserves_real_revision_through_resolution(self):
        ep = conflict(('home', 'hospital'))
        ep.revise_update('hospital', {'text': STILL + ' The inpatient copy was corrected.'},
                         expected_revision=1, request_id='correct-hospital-copy',
                         facts=[{'type': 'admitted', 'quote': STILL}])
        add(ep, 'clarified', self.text, 'discharged', at='2028-05-05T12:00:00+01:00')
        references = ep.slots['discharged']['resolved_state_claims']
        self.assertEqual({r['source_revision'] for r in references if r['update_id'] == 'hospital'}, {2})
        restored = Episode.from_snapshot(ep.to_snapshot())
        self.assertTrue(all(u['state'] != 'time_uncertain' for u in Q.sentence_units(restored)))
        restored.delete_update('clarified', expected_revision=1, request_id='withdraw-corrected-clarification')
        self.assertEqual(restored.phase(), 'Current patient status needs confirmation')
        hospital = [u for u in Q.sentence_units(restored) if u['update_id'] == 'hospital' and 'admitted' in u['types']]
        self.assertTrue(hospital)
        self.assertTrue(all(u['source_revision'] == 2 and u['state'] == 'time_uncertain' for u in hospital))

    def test_waiting_procedure_does_not_reopen_resolved_hospital_collision(self):
        ep = ReverseClarification().episode()
        ReverseClarification().confirm(ep)
        quote = 'The operation is planned for 19 June 2029 at 11:00.'
        ep.add_update({'update_id': 'booking', 'kind': 'recording', 'author': 'alex', 'speaker': 'Doctor',
                       'at': '2029-06-18T11:00:00+01:00', 'text': quote},
                      facts=[{'type': 'procedure_planned', 'what': 'Operation', 'quote': quote}])
        self.assertEqual(ep.phase(), 'Waiting for operation')
        self.assertTrue(all(u['state'] != 'time_uncertain' for u in Q.sentence_units(ep)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
