"""Source-grounded selection regressions; fictional cases, no model calls."""
import copy
import hashlib
import html
import itertools
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode
from episode import Episode
import episode_qa as Q
import timeline_html as T

SCENARIO = {'patient': {'name': 'Robin', 'home': 'at home', 'timezone': 'Europe/London'},
            'members': [{'member_id': 'alex', 'name': 'Alex'}], 'updates': []}


def setUpModule():
    print('EVENT_SELECTION_ROUND4_SOURCE_V1 ' + json.dumps({module.__name__: {
        'path': module.__file__, 'sha256': hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
        for module in (episode, Q, T)}), flush=True)


def add(ep, uid, text, facts=None, **extra):
    result = ep.add_update({'update_id': uid, 'kind': 'recording', 'author': 'alex',
                            'speaker': 'Nurse Avery', 'at': '2028-08-20T09:00:00+01:00',
                            'text': text, **extra}, facts=copy.deepcopy(facts if facts is not None else [
                                {'type': 'event', 'what': text, 'quote': text}]))
    if result['rejected']:
        raise AssertionError(result['rejected'])
    return result


def visible(ep):
    return [line for row in T.event_entries(ep, 'alex', None) for line in row['lines']]


class EventSelection(unittest.TestCase):
    def test_complete_peripheral_tasks_are_archived_even_with_hospital_context(self):
        cases = ('The lift near reception is working again.', 'The hospital printer is out of paper.',
                 'I collected the laundry from the hospital.', 'The cafeteria coffee prices have changed.',
                 'The ward Wi-Fi password is garden42.')
        for text in cases:
            with self.subTest(text=text):
                ep = Episode(SCENARIO)
                add(ep, 'admin', text)
                before = ep.to_snapshot()
                self.assertEqual(visible(ep), [])
                self.assertIn(html.escape(text, quote=True), T.source_archive_html(ep))
                self.assertEqual(ep.to_snapshot(), before)

    def test_equipment_and_household_effects_on_care_stay_visible(self):
        for text in ('The lift is broken, so Robin cannot get to the appointment.',
                     'The printer is out of paper and the medication instructions are missing.',
                     'I collected the laundry and Robin fainted at the hospital.',
                     'The lift is working again but Robin is blue.',
                     'The nurse says the router is broken and the alarm will not work.',
                     'The cafeteria coffee prices have changed; Robin cannot afford meals.',
                     'The lift is broken because a patient fell inside it.'):
            with self.subTest(text=text):
                ep = Episode(SCENARIO)
                add(ep, 'care', text)
                self.assertEqual([ln['quote'] for ln in visible(ep)], [text])

    def test_document_housekeeping_is_not_a_patient_event(self):
        text = 'That discharge photo was from the wrong folder. I am removing it; there is no new discharge news.'
        facts = [{'type': 'event', 'what': quote, 'quote': quote} for quote in (
            'That discharge photo was from the wrong folder.', 'I am removing it', 'there is no new discharge news')]
        ep = Episode(SCENARIO)
        add(ep, 'admin', text, facts)
        self.assertEqual(visible(ep), [])
        self.assertIn('wrong folder', T.source_archive_html(ep))
        self.assertEqual(len(Q.sentence_units(ep)), 2)

    def test_pure_no_change_message_is_archived_but_unchanged_symptoms_are_retained(self):
        for text in ('No care or visit changes.', 'There is no new discharge news.', 'No new clinical updates.'):
            ep = Episode(SCENARIO)
            add(ep, 'meta', text)
            self.assertEqual(visible(ep), [], text)
        for text in ('No care or visit changes, but Robin has severe pain.',
                     'There is no new discharge news because she is unresponsive.',
                     'Her severe pain is unchanged.', 'He is blue.', 'She is unresponsive.',
                     'The wound smells different.', 'Robin cannot swallow.',
                     'The doctor corrected the insulin dose and stopped it.',
                     'I am removing it from her wound.', 'Birch House was a clerical error.'):
            ep = Episode(SCENARIO)
            add(ep, 'care', text)
            self.assertEqual([ln['quote'] for ln in visible(ep)], [text], text)

    def test_unresolved_pronoun_removal_is_not_automatically_document_housekeeping(self):
        ep = Episode(SCENARIO)
        add(ep, 'unknown', 'I am removing it.')
        self.assertEqual(len(visible(ep)), 1)

    def test_clinical_safety_function_unknown_observations_and_medication_changes_remain(self):
        for text in ('Robin is much quieter than usual.', 'She cannot lift her right hand.',
                     'He is eating less.', 'Her examination found a new lump.',
                     'Her symptoms have not changed.', 'She dropped the cup twice.',
                     'The keys are needed so the carer can reach the patient.',
                     'The photo shows a bleeding wound.', 'The doctor corrected the diagnosis.',
                     'The printer caught fire.', 'The lift alarm is broken.'):
            ep = Episode(SCENARIO)
            add(ep, 'care', text)
            self.assertEqual([ln['quote'] for ln in visible(ep)], [text], text)
        ep = Episode(SCENARIO)
        text = 'Stop metformin because of the rash.'
        add(ep, 'med', text, [{'type': 'medication', 'name': 'metformin', 'status': 'stop', 'quote': text}])
        self.assertEqual([ln['type'] for ln in visible(ep)], ['medication'])
        self.assertFalse(ep.status()['medicines'][0]['active'])

    def test_simple_admission_and_ongoing_stay_has_one_typed_event(self):
        text = 'Robin was admitted to Elm Hospital on 4 August 2028 at 08:35 and remains there.'
        ep = Episode(SCENARIO)
        add(ep, 'admit', text, [{'type': 'admitted', 'quote': text},
                               {'type': 'event', 'what': text, 'quote': text}])
        self.assertEqual([ln['type'] for ln in visible(ep)], ['admitted'])
        self.assertIn(text, T.source_archive_html(ep))
        self.assertEqual(ep.phase(), 'Admitted to hospital')

    def test_admission_supplement_never_erases_distinct_clinical_or_uncertain_content(self):
        for tail in (' and has severe pain.', ' and cannot walk.', ' if a bed is available.',
                     ' and then moved to another ward.', ' and remains there because of bleeding.'):
            text = 'Robin was admitted to Elm Hospital on 4 August 2028 at 08:35' + tail
            ep = Episode(SCENARIO)
            add(ep, 'mixed', text, [{'type': 'admitted', 'quote': text},
                                   {'type': 'event', 'what': text, 'quote': text}])
            self.assertEqual({ln['type'] for ln in visible(ep)}, {'admitted', 'event'}, tail)
        ep = Episode(SCENARIO)
        text = 'Robin was admitted to Elm Hospital.'
        add(ep, 'unknown', text, [{'type': 'admitted', 'quote': text},
                                 {'type': 'event', 'what': 'Admitted', 'quote': text}])
        self.assertEqual(len(visible(ep)), 2)

    def test_cancelled_family_plan_and_logistics_have_no_generic_duplicate(self):
        ep = Episode(SCENARIO)
        old = 'I will visit on 13 August 2028 at 10:20.'
        add(ep, 'old', old, [{'type': 'family', 'what': 'Family visit', 'quote': old}], kind='note', topic='plan')
        cancel = 'I have cancelled my 13 August visit.'
        text = cancel + ' I do not have another visit booked yet.'
        add(ep, 'new', text, [{'type': 'family', 'what': 'Cancelled family visit', 'quote': cancel},
                             {'type': 'event', 'what': 'Cancelled family visit', 'quote': cancel}], kind='note', topic='plan')
        self.assertEqual(ep.plans()[0]['plan_status'], 'withdrawn')
        self.assertEqual(ep.plans()[0]['event_time']['time_role'], 'withdrawn_target')
        self.assertEqual(visible(ep), [])
        self.assertEqual(len(T.event_entries(ep, 'alex', None)), 1)
        self.assertIn('Cancelled target', T.timeline_html(ep, 'alex', None))
        for quote in ('I will bring the keys on 18 August 2028 at 11:10.',
                      'I will collect the clothes on 18 August 2028 in the afternoon.'):
            current = Episode(SCENARIO)
            add(current, 'plan', quote, [{'type': 'family', 'what': quote, 'quote': quote},
                                        {'type': 'event', 'what': quote, 'quote': quote}], kind='note', topic='plan')
            self.assertEqual(len(T.event_entries(current, 'alex', None)), 1)
            self.assertEqual(len(current.plans()), 1)
            self.assertEqual(visible(current), [])

    def test_family_logistics_does_not_hide_care_clause_or_other_speaker(self):
        for text in ('I will bring the keys on 18 August 2028, and Robin has a fever.',
                     'I have cancelled my visit because Robin is unresponsive.',
                     'Rory will bring the keys on 18 August 2028.'):
            ep = Episode(SCENARIO)
            add(ep, 'plan', text, [{'type': 'family', 'what': text, 'quote': text},
                                  {'type': 'event', 'what': text, 'quote': text}], kind='note', topic='plan')
            self.assertTrue(visible(ep), text)

    def test_family_date_suffix_is_closed_grammar_not_arbitrary_care_text(self):
        for text in ('I will bring the keys on 18 August 2028 with oxygen.',
                     'I will bring the keys on 18 August 2028 after a collapse.',
                     'I cancelled my 18 August visit when Robin deteriorated.',
                     'I will bring the keys on 18 August 2028 for urgent wound care.'):
            ep = Episode(SCENARIO)
            add(ep, 'mixed', text, [{'type': 'family', 'what': text, 'quote': text},
                                   {'type': 'event', 'what': text, 'quote': text}], kind='note', topic='plan')
            self.assertTrue(visible(ep), text)

    def test_changed_plan_keeps_latest_target_and_earlier_source_provenance(self):
        ep = Episode(SCENARIO)
        old = 'The hip operation is planned for 8 August 2028 at 09:10.'
        new = 'The hip operation has been moved to 9 August 2028 at 12:40.'
        add(ep, 'old', old, [{'type': 'procedure_planned', 'what': 'Hip operation', 'quote': old}],
            at='2028-08-01T09:00:00+01:00')
        reference = 'The same hip operation was previously booked for 8 August 2028 at 09:10.'
        add(ep, 'new', reference + ' ' + new, [{'type': 'procedure_planned', 'what': 'Hip operation', 'quote': new}],
            at='2028-08-02T09:00:00+01:00')
        self.assertEqual([ln['fact']['when'] for ln in visible(ep)], ['2028-08-09T12:40:00+01:00'])
        self.assertEqual(len(ep.procedures['hip operation']['history']), 1)
        units = Q.sentence_units(ep)
        self.assertEqual((units[0]['state'], units[0]['replaced_by']), ('earlier', 'new.2'))
        view = T.presentation_model(ep, 'alex', None)
        self.assertEqual(len(view['next']), 1)
        self.assertIn('09 Aug', view['next'][0]['text'])
        self.assertIn('08 Aug', T.timeline_html(ep, 'alex', None))
        self.assertIn(old, T.source_archive_html(ep))

    def test_plan_conflicts_different_body_part_and_repeat_intent_are_retained(self):
        ep = Episode(SCENARIO)
        for uid, speaker, day in (('one', 'Nurse Avery', '8'), ('two', 'Doctor Lee', '9')):
            text = f'The hip operation is planned for {day} August 2028 at 09:10.'
            add(ep, uid, text, [{'type': 'procedure_planned', 'what': 'Hip operation', 'quote': text}],
                speaker=speaker, at=f'2028-08-0{1 if uid == "one" else 2}T09:00:00+01:00')
        self.assertEqual(len(visible(ep)), 2)
        self.assertTrue(ep.procedures['hip operation']['two_answers'])
        extra = 'Another knee operation has been moved to 11 August 2028 at 09:10.'
        add(ep, 'different', extra, [{'type': 'procedure_planned', 'what': 'Knee operation', 'quote': extra}])
        self.assertEqual(len(visible(ep)), 3)

    def test_revision_and_delete_restore_previous_plan_and_keep_clinical_history(self):
        ep = Episode(SCENARIO)
        actual = 'Robin was admitted on 3 August 2028 at 08:25.'
        add(ep, 'admission', actual, [{'type': 'admitted', 'quote': actual}])
        old = 'Hip operation is planned for 8 August 2028 at 09:10.'
        new = 'Hip operation has been rescheduled to 9 August 2028 at 12:40.'
        for uid, text, at in (('old', old, '2028-08-01T09:00:00+01:00'), ('new', new, '2028-08-02T09:00:00+01:00')):
            source_text = ('The same hip operation was previously booked for 8 August 2028 at 09:10. ' + text
                           if uid == 'new' else text)
            add(ep, uid, source_text, [{'type': 'procedure_planned', 'what': 'Hip operation', 'quote': text}], at=at)
        self.assertEqual(len(visible(ep)), 2)
        ep.delete_update('new', expected_revision=1, request_id='remove-change')
        self.assertEqual({ln['fact'].get('when') for ln in visible(ep)}, {'2028-08-03T08:25:00+01:00', '2028-08-08T09:10:00+01:00'})
        revised = 'Hip operation is planned for 10 August 2028 in the afternoon.'
        ep.revise_update('old', {'text': revised}, expected_revision=1, request_id='revise-old',
                         facts=[{'type': 'procedure_planned', 'what': 'Hip operation', 'quote': revised}])
        lines = visible(Episode.from_snapshot(ep.to_snapshot()))
        self.assertEqual({ln['fact']['fact_id'].split('@')[1].split(':')[0] for ln in lines if ln['type'] == 'procedure_planned'}, {'2'})
        self.assertEqual(next(ln['event_time']['precision'] for ln in lines if ln['type'] == 'procedure_planned'), 'part_of_day')
        self.assertTrue(any(ln['type'] == 'admitted' for ln in lines))

    def test_old_booking_and_same_completed_procedure_are_order_independent(self):
        planned = 'The hip operation is planned for 7 August 2028 at 08:10.'
        completed = 'The hip operation was completed on 7 August 2028 at 11:45.'
        for order in itertools.permutations(('old', 'done')):
            ep = Episode(SCENARIO)
            for uid in order:
                add(ep, uid, planned if uid == 'old' else completed,
                    [{'type': 'procedure_planned' if uid == 'old' else 'procedure_done',
                      'what': 'Hip operation', 'quote': planned if uid == 'old' else completed}],
                    at='2028-08-06T09:00:00+01:00' if uid == 'old' else '2028-08-08T09:00:00+01:00')
            self.assertEqual([ln['type'] for ln in visible(ep)], ['procedure_done'])
            self.assertEqual(ep.procedures['hip operation']['status'], 'done')
            self.assertIn(planned, T.source_archive_html(ep))

    def test_family_completion_never_retires_care_team_booking_in_either_order(self):
        planned = 'The hip operation is planned for 7 August 2028 at 08:10.'
        completed = 'The hip operation was completed on 7 August 2028 at 11:45.'
        for order in itertools.permutations(('old', 'done')):
            ep = Episode(SCENARIO)
            for uid in order:
                add(ep, uid, planned if uid == 'old' else completed,
                    [{'type': 'procedure_planned' if uid == 'old' else 'procedure_done',
                      'what': 'Hip operation', 'quote': planned if uid == 'old' else completed}],
                    kind='recording' if uid == 'old' else 'note',
                    at='2028-08-06T09:00:00+01:00' if uid == 'old' else '2028-08-08T09:00:00+01:00')
            self.assertEqual({ln['type'] for ln in visible(ep)}, {'procedure_done', 'procedure_planned'})
            self.assertTrue(ep.procedures['hip operation']['time_uncertain'])
            self.assertIn('needs confirmation', ep.phase())

    def test_different_and_explicit_repeat_bookings_stay_after_completion(self):
        for what, text in (('Knee operation', 'The knee operation is planned for 8 August 2028 at 08:10.'),
                           ('Hip operation', 'Another hip operation is planned for 10 August 2028 at 08:10.')):
            ep = Episode(SCENARIO)
            completed = 'The hip operation was completed on 7 August 2028 at 11:45.'
            add(ep, 'done', completed, [{'type': 'procedure_done', 'what': 'Hip operation', 'quote': completed}])
            add(ep, 'future', text, [{'type': 'procedure_planned', 'what': what, 'quote': text}])
            self.assertEqual({ln['type'] for ln in visible(ep)}, {'procedure_done', 'procedure_planned'})

    def test_past_actual_transitions_are_not_removed_by_a_later_state(self):
        ep = Episode(SCENARIO)
        for uid, kind, text in (
                ('admit', 'admitted', 'Robin was admitted on 2 August 2028 at 08:20.'),
                ('done', 'procedure_done', 'Hip operation was completed on 3 August 2028 at 11:30.'),
                ('discharge', 'discharged', 'Robin was discharged home on 5 August 2028 at 14:40.'),
                ('readmit', 'admitted', 'Robin was admitted on 8 August 2028 at 10:50.')):
            fact = {'type': kind, 'quote': text}
            if kind == 'procedure_done':
                fact['what'] = 'Hip operation'
            add(ep, uid, text, [fact])
        self.assertEqual(sorted(ln['type'] for ln in visible(ep)), ['admitted', 'admitted', 'discharged', 'procedure_done'])
        self.assertIn('Admitted', ep.phase())


class PhaseTwoSelection(unittest.TestCase):
    def test_folded_admission_keeps_verbatim_place_in_main_headline_without_location_fact(self):
        quote = 'Robin was admitted to Elm Hospital on 4 August 2028 at 08:35 and remains there.'
        for what in (quote, 'Robin was admitted to Elm Hospital'):
            for kind in ('recording', 'note'):
                ep = Episode(SCENARIO)
                add(ep, 'admit', quote, [{'type': 'event', 'what': what, 'quote': quote},
                                        {'type': 'admitted', 'quote': quote}], kind=kind)
                before = ep.to_snapshot()
                row, = T.event_entries(ep, 'alex', None)
                self.assertEqual([ln['type'] for ln in row['lines']], ['admitted'])
                self.assertIn('Elm Hospital', row['headline'])
                self.assertEqual(row['headline_flag'], 'unconfirmed' if kind == 'note' else None)
                self.assertNotIn('location', ep.slots)
                self.assertEqual(ep.to_snapshot(), before)
                main = T.timeline_html(ep, 'alex', None).split('<details class="cr-src"')[0]
                self.assertIn('Elm Hospital', main)

    def test_untrusted_admission_place_remains_escaped_visible_and_not_promoted(self):
        quote = 'Robin was admitted to <Elm & Bay> on 4 August 2028 at 08:35.'
        ep = Episode(SCENARIO)
        add(ep, 'admit', quote, [{'type': 'event', 'what': 'Admitted', 'quote': quote},
                                {'type': 'admitted', 'quote': quote}])
        before = ep.to_snapshot()
        row, = T.event_entries(ep, 'alex', None)
        self.assertEqual([line['type'] for line in row['lines']], ['admitted'])
        self.assertIn('<Elm & Bay>', row['headline'])
        rendered = T.timeline_html(ep, 'alex', None)
        main = rendered.split('<details class="cr-src"')[0]
        self.assertIn('&lt;Elm &amp; Bay&gt;', main)
        self.assertNotIn('<Elm & Bay>', main)
        self.assertNotIn('location', ep.slots)
        self.assertEqual(ep.to_snapshot(), before)

    def test_cross_admission_discharge_plan_is_not_retired_by_another_stay_change(self):
        ep = Episode(SCENARIO)
        for uid, kind, text in (
                ('admit-one', 'admitted', 'Robin was admitted on 1 August 2028 at 08:20.'),
                ('plan-one', 'expected_discharge', 'Discharge is expected on 4 August 2028.'),
                ('home', 'discharged', 'Robin was discharged home on 5 August 2028 at 14:30.'),
                ('admit-two', 'admitted', 'Robin was admitted on 8 August 2028 at 09:20.'),
                ('plan-two', 'expected_discharge', 'The expected discharge has been moved to 11 August 2028.')):
            fact = {'type': kind, 'quote': text}
            if kind == 'expected_discharge':
                fact['when_text'] = '4 August 2028' if uid == 'plan-one' else '11 August 2028'
            add(ep, uid, text, [fact], at='2028-08-10T09:00:00+01:00')
        self.assertEqual({ln['fact']['fact_id'] for ln in visible(ep) if ln['type'] == 'expected_discharge'},
                         {'plan-one@1:f1', 'plan-two@1:f1'})

    def test_same_name_followups_do_not_prove_one_occurrence(self):
        ep = Episode(SCENARIO)
        for index, quote in enumerate(('Physiotherapy is planned for 6 August 2028.',
                                       'Physiotherapy is planned for 13 August 2028.',
                                       'Physiotherapy has been moved to 14 August 2028.')):
            add(ep, f'follow-{index}', quote, [{'type': 'follow_up', 'what': 'Physiotherapy', 'quote': quote}],
                at=f'2028-08-0{index+1}T09:00:00+01:00')
        self.assertEqual(len([ln for ln in visible(ep) if ln['type'] == 'follow_up']), 3)

    def test_unlinked_same_name_procedure_history_is_not_all_retired(self):
        ep = Episode(SCENARIO)
        for index, quote in enumerate(('The hip operation is planned for 6 August 2028 at 10:10.',
                                       'The hip operation is planned for 7 August 2028 at 10:10.',
                                       'The hip operation has been moved to 8 August 2028 at 10:10.')):
            add(ep, f'procedure-{index}', quote, [{'type': 'procedure_planned', 'what': 'Hip operation', 'quote': quote}],
                at=f'2028-08-0{index+1}T09:00:00+01:00')
        self.assertEqual(len([ln for ln in visible(ep) if ln['type'] == 'procedure_planned']), 3)

    def test_explicit_procedure_reference_retires_only_exact_preceding_target(self):
        ep = Episode(SCENARIO)
        for index, quote in enumerate(('The hip operation is planned for 6 August 2028 at 10:10.',
                                       'The hip operation is planned for 7 August 2028 at 10:10.')):
            add(ep, f'procedure-{index}', quote, [{'type': 'procedure_planned', 'what': 'Hip operation', 'quote': quote}],
                at=f'2028-08-0{index+1}T09:00:00+01:00')
        quote = 'The hip operation has been moved to 8 August 2028 at 10:10.'
        text = 'The same hip operation was previously booked for 7 August 2028 at 10:10. ' + quote
        add(ep, 'change', text, [{'type': 'procedure_planned', 'what': 'Hip operation', 'quote': quote}],
            at='2028-08-03T09:00:00+01:00')
        self.assertEqual({ln['fact']['fact_id'] for ln in visible(ep)}, {'procedure-0@1:f1', 'change@1:f1'})
        self.assertEqual(len(ep.procedures['hip operation']['history']), 2)

    def test_unproven_or_changed_by_hand_occurrence_reference_is_retained(self):
        old = 'The hip operation is planned for 6 August 2028 at 10:10.'
        new = 'The hip operation has been moved to 8 August 2028 at 10:10.'
        reference = 'The same hip operation was previously booked for 6 August 2028 at 10:10.'
        cases = [(reference.replace('6 August', '7 August') + ' ' + new, {}),
                 (reference + ' ' + new + ' This concerns Rory.', {}),
                 ('If transport comes, ' + reference + ' ' + new, {}),
                 (reference.replace('same hip', 'same knee') + ' ' + new, {}),
                 (reference + ' ' + new, {'reading': {'changed_lines': [reference]}}),
                 (reference + '\n' + new, {'reading': {'changed_lines': [new]}})]
        for source_text, extra in cases:
            ep = Episode(SCENARIO)
            add(ep, 'old', old, [{'type': 'procedure_planned', 'what': 'Hip operation', 'quote': old}], at='2028-08-01T09:00:00+01:00')
            add(ep, 'new', source_text, [{'type': 'procedure_planned', 'what': 'Hip operation', 'quote': new}],
                at='2028-08-02T09:00:00+01:00', **extra)
            self.assertEqual(len(visible(ep)), 2, source_text)

    def test_event_only_current_family_arrangements_have_one_owned_row(self):
        ep = Episode(SCENARIO)
        old = 'I am coming on 16 August 2028 at 14:15.'
        add(ep, 'old', old, [{'type': 'event', 'what': "family member's planned visit", 'quote': old}], kind='note', topic='plan')
        cancel = 'I have cancelled my 16 August visit.'
        text = cancel + ' I do not have another visit booked yet.'
        add(ep, 'cancel', text, [{'type': 'event', 'what': 'cancelled visit', 'quote': cancel},
                                {'type': 'next_step', 'what': 'I do not have another visit booked yet',
                                 'quote': 'I do not have another visit booked yet.'}], kind='note', topic='plan')
        self.assertEqual(visible(ep), [])
        self.assertEqual(len(T.event_entries(ep, 'alex', None)), 1)
        self.assertEqual(ep.plans()[0]['plan_status'], 'withdrawn')
        for quote in ('I will bring the keys on 18 August 2028 at 11:10.',
                      'I will collect the clothes on 18 August 2028 in the afternoon.'):
            ep = Episode(SCENARIO)
            add(ep, 'logistics', quote, [{'type': 'event', 'what': quote.split(' on ')[0], 'quote': quote}], kind='note', topic='plan')
            self.assertEqual(visible(ep), [], quote)
            self.assertEqual(len(T.event_entries(ep, 'alex', None)), 1)

    def test_event_only_arrangements_need_member_owner_and_full_semantic_scope(self):
        quote = 'I will bring the keys on 18 August 2028 at 11:10.'
        for text, extra in ((quote, {'author': 'unknown'}),
                            (quote, {'topic': None}),
                            ('If Robin stabilises, ' + quote, {}),
                            ('I will not bring the keys on 18 August 2028 at 11:10.', {}),
                            (quote[:-1] + ' because Robin is blue.', {})):
            ep = Episode(SCENARIO)
            fact_quote = quote if text.startswith('If ') else text
            add(ep, 'plan', text, [{'type': 'event', 'what': fact_quote, 'quote': fact_quote}],
                kind='note', topic=extra.pop('topic', 'plan'), **extra)
            self.assertTrue(visible(ep), text)

    def test_date_trimmed_admission_paraphrase_is_same_source_assertion(self):
        ep = Episode(SCENARIO)
        quote = 'Robin was admitted to Elm Hospital on 4 August 2028 at 08:35 and remains there.'
        add(ep, 'admit', quote, [{'type': 'event', 'what': 'Robin was admitted to Elm Hospital', 'quote': quote},
                                {'type': 'admitted', 'quote': quote}])
        self.assertEqual([ln['type'] for ln in visible(ep)], ['admitted'])

    def test_date_trimmed_admission_keeps_other_actor_repeated_and_clinical_assertions(self):
        base = 'Robin was admitted to Elm Hospital on 4 August 2028 at 08:35'
        for quote, what, generic_quote in (
                (base + ' and has new weakness.', 'Robin was admitted to Elm Hospital', None),
                (base + ' and remains there.', 'Rory was admitted to Elm Hospital', None),
                (base + '.', 'Robin was admitted to Elm Hospital', 'Robin was admitted to Elm Hospital'),
                (base + '. ' + base + '.', 'Robin was admitted to Elm Hospital', base + '.'),
                (base.replace('was admitted', 'was admitted again') + '.', 'Robin was admitted again to Elm Hospital', None),
                (base.replace('was admitted', 'might be admitted') + '.', 'Robin might be admitted to Elm Hospital', None)):
            ep = Episode(SCENARIO)
            actual_quote = quote.split('. ')[0] + '.' if '. ' in quote else quote
            add(ep, 'admit', quote, [{'type': 'event', 'what': what, 'quote': generic_quote or actual_quote},
                                    {'type': 'admitted', 'quote': actual_quote}])
            self.assertEqual(len(visible(ep)), 2, quote)


if __name__ == '__main__':
    unittest.main(verbosity=2)
