"""Independent source-local stay relation regressions; no model or benchmark answers."""
import copy
import hashlib
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
ADMIT = 'Robin was admitted on 2 August 2028 at 09:15.'
PLAN = 'For this admission, discharge is expected on 10 August 2028.'
DONE = 'Robin was discharged home on 8 August 2028 at 14:20.'
FUTURE = 'For the next planned admission on 20 August 2028, discharge is expected on 22 August 2028.'


def setUpModule():
    print('TEMPORAL_ROUND3_SOURCE_LOCAL_STAY_V1 ' + json.dumps({
        module.__name__: {'path': module.__file__, 'sha256': hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
        for module in (episode, Q, T)}), flush=True)


def add(ep, uid, text, facts, **kwargs):
    result = ep.add_update({'update_id': uid, 'author': 'alex', 'kind': 'recording',
                            'at': '2028-08-25T09:00:00+01:00', 'text': text, **kwargs}, facts=copy.deepcopy(facts))
    if result['rejected']:
        raise AssertionError(result['rejected'])
    return result


def plan_fact(text=PLAN, target='10 August 2028'):
    return {'type': 'expected_discharge', 'when_text': target, 'quote': text}


def bound(ep, uid='plan', *, admission=ADMIT, plan=PLAN, **kwargs):
    return add(ep, uid, admission + ' ' + plan,
               [{'type': 'admitted', 'quote': admission}, plan_fact(plan)], **kwargs)


def done(ep, uid='done', text=DONE, **kwargs):
    return add(ep, uid, text, [{'type': 'discharged', 'quote': text}], **kwargs)


def visible(ep):
    return [line for row in T.event_entries(ep, 'alex', None) for line in row['lines']]


def plan_unit(ep):
    return next(u for u in Q.sentence_units(ep) if u['update_id'] == 'plan' and 'expected_discharge' in u['types'])


class DischargePlanRelation(unittest.TestCase):
    def test_bare_plan_is_not_fulfilled_by_equal_missing_stay_ids(self):
        ep = Episode(SCENARIO)
        done(ep)
        add(ep, 'plan', FUTURE, [plan_fact(FUTURE, '22 August 2028')])
        self.assertEqual(ep.slots['expected_discharge']['stay_id'], ep.slots['discharged']['stay_id'])
        self.assertNotEqual(plan_unit(ep)['state'], 'past')
        self.assertIsNone(plan_unit(ep)['replaced_by'])
        self.assertTrue(any('22 Aug' in text for text in ep.status()['next']))

    def test_projection_stay_id_leaking_past_discharge_does_not_fulfil_next_stay(self):
        ep = Episode(SCENARIO)
        add(ep, 'admit', ADMIT, [{'type': 'admitted', 'quote': ADMIT}])
        done(ep)
        add(ep, 'plan', FUTURE, [plan_fact(FUTURE, '22 August 2028')])
        self.assertEqual(ep.slots['expected_discharge']['stay_id'], ep.slots['discharged']['stay_id'])
        self.assertNotEqual(plan_unit(ep)['state'], 'past')
        self.assertTrue(any('22 Aug' in item['text'] for item in T.presentation_model(ep, 'alex', None)['next']))

    def test_positive_bound_plan_folds_but_actual_history_and_archive_remain(self):
        ep = Episode(SCENARIO)
        bound(ep)
        done(ep)
        self.assertEqual({ln['type'] for ln in visible(ep)}, {'admitted', 'discharged'})
        self.assertIn(PLAN, T.source_archive_html(ep))
        self.assertEqual((plan_unit(ep)['state'], plan_unit(ep)['replaced_by']), ('past', 'done.1'))
        self.assertFalse(ep.status()['next'])

    def test_upload_order_and_late_admission_are_invariant(self):
        signatures = []
        for order in itertools.permutations(('plan', 'done', 'noise')):
            ep = Episode(SCENARIO)
            for uid in order:
                if uid == 'plan':
                    bound(ep)
                elif uid == 'done':
                    done(ep)
                else:
                    text = 'Robin walked using a frame.'
                    add(ep, uid, text, [{'type': 'event', 'what': text, 'quote': text}])
            signatures.append((ep.phase(), sorted(ln['type'] for ln in visible(ep)),
                               plan_unit(ep)['state'], plan_unit(ep)['replaced_by'], ep.status()['next']))
        self.assertTrue(all(signature == signatures[0] for signature in signatures))
        self.assertEqual(signatures[0][2], 'past')

    def test_snapshot_roundtrip_and_readonly_views_agree(self):
        ep = Episode(SCENARIO)
        done(ep)
        bound(ep)
        snapshot = copy.deepcopy(ep.to_snapshot())
        restored = Episode.from_snapshot(snapshot)
        for current in (ep, restored):
            self.assertEqual(plan_unit(current)['state'], 'past')
            self.assertFalse(any(ln['type'] == 'expected_discharge' for ln in visible(current)))
            self.assertFalse(current.status()['next'])
            self.assertEqual(current.to_snapshot(), snapshot)

    def test_revision_removing_admission_invalidates_old_relation(self):
        ep = Episode(SCENARIO)
        bound(ep)
        done(ep)
        prior = copy.deepcopy(ep.slots['expected_discharge'])
        ep.revise_update('plan', {'text': PLAN}, expected_revision=1, request_id='remove-admission', facts=[plan_fact()])
        self.assertNotEqual(plan_unit(ep)['state'], 'past')
        self.assertTrue(any(ln['type'] == 'expected_discharge' for ln in visible(ep)))
        self.assertNotEqual(ep.discharge_plan_relation(prior, ep.slots['discharged'])['status'], 'fulfilled')

    def test_discharge_revision_and_deletion_reopen_bound_plan(self):
        for operation in ('revise', 'delete'):
            ep = Episode(SCENARIO)
            bound(ep)
            done(ep)
            if operation == 'delete':
                ep.delete_update('done', expected_revision=1, request_id='remove-discharge')
            else:
                text = 'Robin might be discharged on 8 August 2028.'
                ep.revise_update('done', {'text': text}, expected_revision=1, request_id='uncertain-discharge', facts=[])
            self.assertNotEqual(plan_unit(ep)['state'], 'past')
            self.assertTrue(any(ln['type'] == 'expected_discharge' for ln in visible(ep)))

    def test_future_plan_is_present_in_hero_and_next_without_changing_home_phase(self):
        ep = Episode(SCENARIO)
        done(ep)
        add(ep, 'plan', FUTURE, [plan_fact(FUTURE, '22 August 2028')])
        self.assertEqual(ep.phase(), 'Home after hospital')
        status = ep.status()
        html = T.hero_html(ep, status, None, {'member_id': 'alex'})
        self.assertIn('22 Aug', html)
        self.assertIn('confirm which admission', html)

    def test_unscoped_earlier_or_unknown_plan_has_no_date_only_fulfilment_fallback(self):
        for text, target in [('Discharge is expected on 5 August 2028.', '5 August 2028'),
                             ('Discharge is expected soon.', 'soon')]:
            ep = Episode(SCENARIO)
            add(ep, 'plan', text, [plan_fact(text, target)])
            done(ep)
            self.assertNotEqual(plan_unit(ep)['state'], 'past')
            self.assertIsNone(plan_unit(ep)['replaced_by'])

    def test_bound_admission_after_discharge_cannot_close_plan(self):
        ep = Episode(SCENARIO)
        bound(ep, admission='Robin was admitted on 12 August 2028 at 09:15.')
        done(ep)
        self.assertNotEqual(plan_unit(ep)['state'], 'past')
        self.assertTrue(any(ln['type'] == 'expected_discharge' for ln in visible(ep)))

    def test_later_actual_readmission_blocks_old_plan_from_matching_later_discharge(self):
        ep = Episode(SCENARIO)
        bound(ep)
        admission = 'Robin was admitted on 6 August 2028 at 10:20.'
        add(ep, 'second', admission, [{'type': 'admitted', 'quote': admission}])
        done(ep)
        self.assertNotEqual(plan_unit(ep)['state'], 'past')
        self.assertTrue(any(ln['type'] == 'expected_discharge' for ln in visible(ep)))

    def test_multiple_actual_discharges_in_interval_are_not_selected(self):
        ep = Episode(SCENARIO)
        bound(ep)
        done(ep, 'first', 'Robin was discharged home on 7 August 2028 at 14:20.')
        done(ep)
        self.assertNotEqual(plan_unit(ep)['state'], 'past')

    def test_same_day_date_precision_does_not_establish_order(self):
        ep = Episode(SCENARIO)
        bound(ep, admission='Robin was admitted on 8 August 2028.')
        done(ep, text='Robin was discharged home on 8 August 2028.')
        self.assertNotEqual(plan_unit(ep)['state'], 'past')

    def test_two_answers_and_uncertainty_are_not_folded(self):
        ep = Episode(SCENARIO)
        bound(ep, speaker='Nurse Avery')
        other = 'For this admission, discharge is expected on 11 August 2028.'
        add(ep, 'other', other, [plan_fact(other, '11 August 2028')], speaker='Doctor Lee')
        done(ep)
        self.assertTrue(any(ln['type'] == 'expected_discharge' for ln in visible(ep)))
        self.assertEqual(plan_unit(ep)['state'], 'two_answers')

    def test_family_source_and_hand_edited_admission_do_not_supply_scope(self):
        for kwargs in ({'speaker_type': 'family'}, {'reading': {'changed_lines': [ADMIT]}}):
            ep = Episode(SCENARIO)
            add(ep, 'plan', ADMIT + '\n' + PLAN,
                [{'type': 'admitted', 'quote': ADMIT}, plan_fact()], **kwargs)
            done(ep)
            self.assertNotEqual(plan_unit(ep)['state'], 'past')

    def test_conditional_future_other_person_and_multistay_sources_are_not_folded(self):
        cases = [
            ('Robin was not admitted on 2 August 2028 at 09:15.', PLAN),
            ('Robin might be admitted on 2 August 2028 at 09:15.', PLAN),
            ('Rory was admitted on 2 August 2028 at 09:15.', PLAN),
            (ADMIT, 'For the next admission, discharge is expected on 10 August 2028.'),
            (ADMIT, 'For this admission, discharge is expected on 10 August 2028 if the bed is ready.'),
            (ADMIT, PLAN + ' A second admission is booked for 20 August 2028.'),
        ]
        for admission, plan in cases:
            with self.subTest(admission=admission, plan=plan):
                ep = Episode(SCENARIO)
                fact = plan_fact(plan)
                if ' if ' in plan:
                    fact['condition'] = 'if the bed is ready'
                add(ep, 'plan', admission + ' ' + plan, [{'type': 'admitted', 'quote': admission}, fact])
                done(ep)
                self.assertNotEqual(plan_unit(ep)['state'], 'past')
                self.assertTrue(any(ln['type'] == 'expected_discharge' for ln in visible(ep)))

    def test_other_person_negated_and_conditional_departure_do_not_close_plan(self):
        for text in ('Rory was discharged home on 8 August 2028 at 14:20.',
                     'Robin was not discharged home on 8 August 2028 at 14:20.',
                     'If transport comes, Robin was discharged home on 8 August 2028 at 14:20.'):
            with self.subTest(text=text):
                ep = Episode(SCENARIO)
                bound(ep)
                result = ep.add_update({'update_id': 'done', 'kind': 'recording', 'author': 'alex',
                                        'at': '2028-08-25T09:00:00+01:00', 'text': text},
                                       facts=[{'type': 'discharged', 'quote': text}])
                if 'not discharged' in text or text.startswith('If '):
                    self.assertTrue(result['rejected'])
                self.assertNotEqual(plan_unit(ep)['state'], 'past')
                self.assertTrue(any(ln['type'] == 'expected_discharge' for ln in visible(ep)))

    def test_next_filter_does_not_relabel_another_item_or_index_empty_list(self):
        ep = Episode(SCENARIO)
        done(ep)
        future = 'For the next admission, discharge is expected on 22 August 2028.'
        add(ep, 'plan', future, [plan_fact(future, '22 August 2028')])
        view = T.presentation_model(ep, 'alex', None, now='2028-08-23T09:00:00+01:00')
        self.assertEqual(view['next'], [])

    def test_source_local_other_person_discharge_plan_does_not_belong_to_patient(self):
        for plan in ("For this admission, Rory's discharge is expected on 10 August 2028.",
                     "For this admission, her sister's discharge is expected on 10 August 2028.",
                     "For this admission, Rory can go home on 10 August 2028."):
            with self.subTest(plan=plan):
                ep = Episode(SCENARIO)
                bound(ep, plan=plan)
                done(ep)
                self.assertNotEqual(plan_unit(ep)['state'], 'past')
                self.assertTrue(any(ln['type'] == 'expected_discharge' for ln in visible(ep)))

    def test_unlinked_superseded_plan_keeps_latest_target_chain(self):
        ep = Episode(SCENARIO)
        done(ep)
        old = 'Discharge is expected on 22 August 2028.'
        new = 'Discharge is now expected on 23 August 2028.'
        add(ep, 'plan', old, [plan_fact(old, '22 August 2028')], at='2028-08-09T09:00:00+01:00')
        add(ep, 'changed', new, [plan_fact(new, '23 August 2028')], at='2028-08-09T10:00:00+01:00')
        units = Q.sentence_units(ep)
        old_unit = next(u for u in units if u['sid'] == 'plan.1')
        self.assertEqual((old_unit['state'], old_unit['replaced_by']), ('earlier', 'changed.1'))
        self.assertEqual(Q.complete(['plan.1'], units, 'When is discharge planned?')[0], 'changed.1')

    def test_unlinked_plan_labels_do_not_claim_current_home_state_is_unknown(self):
        ep = Episode(SCENARIO)
        done(ep)
        future = 'For the next admission, discharge is expected on 22 August 2028.'
        add(ep, 'plan', future, [plan_fact(future, '22 August 2028')])
        units = Q.sentence_units(ep)
        item = plan_unit(ep)
        by_sid = {u['sid']: u for u in units}
        self.assertEqual(item['state'], 'current')
        self.assertTrue(item.get('plan_link_unresolved'))
        for text in (Q.label_text(item, by_sid), Q.display_label(item, by_sid, None),
                     Q.lead_for([item], 'When is discharge planned?', 'partly', ep)):
            self.assertIn('confirm which admission', text.lower())
            self.assertNotIn('current state needs confirmation', text.lower())
        self.assertEqual(ep.phase(), 'Home after hospital')

    def test_hand_edited_plan_agreeing_with_care_team_is_still_family_scope_evidence(self):
        ep = Episode(SCENARIO)
        bare = 'Discharge is expected on 10 August 2028.'
        add(ep, 'original', bare, [plan_fact(bare)], at='2028-08-04T08:00:00+01:00')
        add(ep, 'plan', ADMIT + '\n' + PLAN, [{'type': 'admitted', 'quote': ADMIT}, plan_fact()],
            at='2028-08-04T09:00:00+01:00', reading={'changed_lines': [PLAN]})
        done(ep)
        fact_id = next(ln['fact']['fact_id'] for e in ep.entries if e['update_id'] == 'plan'
                       for ln in e['lines'] if ln['type'] == 'expected_discharge')
        self.assertNotIn(fact_id, {record['fact']['fact_id'] for record in ep._stay_source_records({'expected_discharge'})})
        self.assertIn(fact_id, {ln['fact']['fact_id'] for ln in visible(ep)})

    def test_unextracted_other_person_context_does_not_give_bare_plan_patient_scope(self):
        ep = Episode(SCENARIO)
        add(ep, 'plan', ADMIT + ' Rory is also an inpatient. ' + PLAN,
            [{'type': 'admitted', 'quote': ADMIT}, plan_fact()])
        done(ep)
        self.assertNotEqual(plan_unit(ep)['state'], 'past')
        self.assertTrue(any(ln['type'] == 'expected_discharge' for ln in visible(ep)))

    def test_two_source_assertions_and_fact_array_can_be_reordered(self):
        for plan_first in (True, False):
            ep = Episode(SCENARIO)
            pieces = [(PLAN, plan_fact()), (ADMIT, {'type': 'admitted', 'quote': ADMIT})]
            if not plan_first:
                pieces.reverse()
            add(ep, 'plan', ' '.join(text for text, fact in pieces), [fact for text, fact in pieces])
            done(ep)
            self.assertEqual(plan_unit(ep)['state'], 'past')
            self.assertFalse(any(ln['type'] == 'expected_discharge' for ln in visible(ep)))

    def test_completion_source_other_person_or_duplicate_context_cannot_close_patient_plan(self):
        departure = 'She was discharged home on 8 August 2028 at 14:20.'
        for text in ('Rory is also an inpatient. ' + departure,
                     departure + ' Rory is also an inpatient.',
                     departure + ' ' + departure):
            with self.subTest(text=text):
                ep = Episode(SCENARIO)
                bound(ep)
                add(ep, 'done', text, [{'type': 'discharged', 'quote': departure}])
                self.assertNotEqual(plan_unit(ep)['state'], 'past')
                self.assertTrue(any(ln['type'] == 'expected_discharge' for ln in visible(ep)))
                self.assertIn(text, T.source_archive_html(ep))

    def test_completion_source_context_revision_invalidates_previous_relation(self):
        ep = Episode(SCENARIO)
        bound(ep)
        done(ep)
        self.assertEqual(plan_unit(ep)['state'], 'past')
        text = 'Rory is also an inpatient. ' + DONE
        ep.revise_update('done', {'text': text}, expected_revision=1, request_id='add-other-patient-context',
                         facts=[{'type': 'discharged', 'quote': DONE}])
        for current in (ep, Episode.from_snapshot(ep.to_snapshot())):
            self.assertEqual(current.phase(), 'Home after hospital')
            self.assertNotEqual(plan_unit(current)['state'], 'past')
            self.assertTrue(any(ln['type'] == 'expected_discharge' for ln in visible(current)))
            self.assertIn(text, T.source_archive_html(current))


if __name__ == '__main__':
    unittest.main(verbosity=2)
