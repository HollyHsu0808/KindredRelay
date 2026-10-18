"""Independent family withdrawal/replacement regressions; no model or answer key."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode
from episode import Episode, event_time

SCENARIO = {'patient': {'name': 'Sam', 'home': 'at home', 'timezone': 'Europe/London'},
            'members': [{'member_id': 'alex', 'name': 'Alex'}, {'member_id': 'rory', 'name': 'Rory'}], 'updates': []}
OLD = 'I will visit on 14 April 2028 at 16:25.'
NEW = 'My new arrival is 17 April 2028 at 11:45; replace my 14 April visit.'
CANCEL = 'I have cancelled my 14 April visit. I do not have another visit booked yet.'


def setUpModule():
    print('TEMPORAL_ROUND2_WITHDRAWAL_REPLACEMENT_V1 ' + json.dumps({
        'loaded_episode': episode.__file__, 'sha256': hashlib.sha256(Path(episode.__file__).read_bytes()).hexdigest(),
        'projection': episode.TEMPORAL_PROJECTION}), flush=True)


def add(ep, uid, text, *, author='alex', facts=None, at='2028-04-10T09:00:00+01:00'):
    return ep.add_update({'update_id': uid, 'kind': 'note', 'author': author, 'at': at, 'topic': 'plan', 'text': text},
                         facts=copy.deepcopy(facts if facts is not None else [{'type': 'family', 'what': 'Family plan', 'quote': text}]))


def current(ep, member='alex'):
    return next(plan for plan in ep.plans() if plan['member_id'] == member)


def refs(plan):
    return {(source['update_id'], source['source_revision']) for source in plan['supporting_sources']}


class Withdrawals(unittest.TestCase):
    def test_old_reference_is_not_a_new_confirmed_arrival(self):
        ep = Episode(SCENARIO)
        add(ep, 'old', OLD)
        entry = add(ep, 'cancel', CANCEL)
        plan = current(ep)
        self.assertEqual(plan['plan_status'], 'withdrawn')
        self.assertEqual(plan['event_time']['when'], '2028-04-14T16:25:00+01:00')
        self.assertEqual(plan['event_time']['temporal_status'], 'unknown')
        self.assertEqual(plan['event_time']['status'], 'confirmed')
        self.assertEqual(plan['event_time']['time_role'], 'withdrawn_target')
        target = plan['cancellation_reference']
        self.assertEqual(target['time']['when'], '2028-04-14T16:25:00+01:00')
        self.assertEqual(target['role'], 'withdrawn_target')
        self.assertEqual(refs(plan), {('old', 1), ('cancel', 1)})
        self.assertEqual(entry['lines'][0]['event_time']['time_role'], 'withdrawn_target')
        self.assertIn('14 April', plan['source_text'])

    def test_full_explicit_cancellation_date_is_still_a_reference(self):
        ep = Episode(SCENARIO)
        add(ep, 'cancel', 'I cannot come on 14 April 2028 at 16:25.')
        plan = current(ep)
        self.assertEqual(plan['plan_status'], 'withdrawn')
        self.assertIsNone(plan['event_time']['when'])
        self.assertIsNone(plan['cancellation_reference'])
        self.assertEqual(refs(plan), {('cancel', 1)})

    def test_short_fact_retains_cancellation_governor(self):
        ep = Episode(SCENARIO)
        add(ep, 'old', OLD)
        text = 'I have cancelled my 14 April visit.'
        add(ep, 'cancel', text, facts=[{'type': 'family', 'what': 'Visit', 'quote': 'my 14 April visit'}])
        plan = current(ep)
        self.assertEqual(plan['plan_status'], 'withdrawn')
        self.assertEqual(plan['event_time']['when'], '2028-04-14T16:25:00+01:00')
        self.assertEqual(plan['cancellation_reference']['time']['when'], '2028-04-14T16:25:00+01:00')
        self.assertEqual(plan['supporting_sources'][0]['quote'], text)

    def test_missing_or_mismatched_old_source_does_not_supply_clock(self):
        for old in (None, 'I will visit on 15 April 2028 at 16:25.', 'I might visit on 14 April 2028 at 16:25.'):
            with self.subTest(old=old):
                ep = Episode(SCENARIO)
                if old:
                    add(ep, 'old', old)
                add(ep, 'cancel', CANCEL)
                plan = current(ep)
                self.assertIsNone(plan['event_time']['when'])
                self.assertIsNone(plan['cancellation_reference'])
                self.assertEqual(refs(plan), {('cancel', 1)})

    def test_other_actor_does_not_supply_cancelled_target(self):
        ep = Episode(SCENARIO)
        add(ep, 'other', OLD, author='rory')
        add(ep, 'cancel', CANCEL)
        self.assertIsNone(current(ep)['cancellation_reference'])
        self.assertEqual(refs(current(ep)), {('cancel', 1)})
        self.assertEqual(current(ep, 'rory')['plan_status'], 'planned')

    def test_same_uploader_reporting_another_person_does_not_supply_target(self):
        ep = Episode(SCENARIO)
        add(ep, 'old', 'Rory will visit on 14 April 2028 at 16:25.')
        add(ep, 'cancel', CANCEL)
        self.assertIsNone(current(ep)['cancellation_reference'])
        self.assertIsNone(current(ep)['event_time']['when'])

    def test_multiple_old_targets_are_not_chosen(self):
        ep = Episode(SCENARIO)
        add(ep, 'old', 'I will visit on 14 April 2028 at 16:25 or 15 April 2028 at 10:30.')
        add(ep, 'cancel', CANCEL)
        self.assertIsNone(current(ep)['cancellation_reference'])
        self.assertIsNone(current(ep)['event_time']['when'])

    def test_cross_year_reference_is_not_inferred(self):
        ep = Episode(SCENARIO)
        add(ep, 'old', 'I will visit on 14 April 2029 at 16:25.')
        add(ep, 'cancel', CANCEL)
        self.assertIsNone(current(ep)['cancellation_reference'])
        self.assertEqual(refs(current(ep)), {('cancel', 1)})

    def test_conditional_cancellation_is_not_a_completed_withdrawal(self):
        ep = Episode(SCENARIO)
        add(ep, 'old', OLD)
        add(ep, 'conditional', 'If the train is cancelled, I will cancel my 14 April visit.')
        plan = current(ep)
        self.assertEqual(plan['plan_status'], 'pending_confirmation')
        self.assertIsNone(plan['cancellation_reference'])
        self.assertIsNone(plan['event_time']['when'])

    def test_unrelated_clinical_date_cannot_become_a_cancellation_target(self):
        ep = Episode(SCENARIO)
        add(ep, 'old', OLD)
        clinical = 'Sam was admitted on 12 April 2028 at 08:10.'
        cancel = 'I have cancelled my 14 April visit.'
        add(ep, 'cancel', clinical + ' ' + cancel, facts=[{'type': 'admitted', 'quote': clinical},
                                                       {'type': 'family', 'what': 'Cancelled visit', 'quote': cancel}])
        plan = current(ep)
        self.assertEqual(plan['text'], cancel)
        self.assertEqual(plan['event_time']['when'], '2028-04-14T16:25:00+01:00')
        self.assertEqual(plan['cancellation_reference']['time']['when'], '2028-04-14T16:25:00+01:00')


class Replacements(unittest.TestCase):
    def episode(self, text=NEW):
        ep = Episode(SCENARIO)
        add(ep, 'old', OLD)
        add(ep, 'new', text)
        return ep

    def test_explicit_new_arrival_and_matching_prior_target_resolve(self):
        ep = self.episode()
        plan = current(ep)
        self.assertEqual(plan['plan_status'], 'planned')
        self.assertEqual(plan['event_time']['when'], '2028-04-17T11:45:00+01:00')
        self.assertEqual(plan['event_time']['when_text'], '17 April 2028 at 11:45')
        self.assertEqual(refs(plan), {('old', 1), ('new', 1)})
        self.assertEqual(plan['replacement_reference']['role'], 'replaced_target')
        self.assertEqual(plan['replacement_reference']['time']['when'], '2028-04-14T16:25:00+01:00')
        self.assertIsNone(plan['cancellation_reference'])

    def test_explicit_self_contained_new_target_does_not_need_old_clock(self):
        for old in (None, 'I will visit on 15 April 2028.', 'I might visit on 14 April 2028.'):
            with self.subTest(old=old):
                ep = Episode(SCENARIO)
                if old:
                    add(ep, 'old', old)
                add(ep, 'new', NEW)
                self.assertEqual(current(ep)['plan_status'], 'planned')
                self.assertEqual(current(ep)['event_time']['when'], '2028-04-17T11:45:00+01:00')
                self.assertIsNone(current(ep)['replacement_reference'])

    def test_new_date_precision_does_not_inherit_old_clock(self):
        ep = self.episode('My new arrival is 17 April 2028 in the afternoon; replace my 14 April visit.')
        plan = current(ep)
        self.assertEqual(plan['event_time']['when'], '2028-04-17')
        self.assertEqual(plan['event_time']['precision'], 'part_of_day')
        self.assertEqual(plan['event_time']['when_text'], '17 April 2028 in the afternoon')
        self.assertNotIn('16:25', plan['event_time']['when_text'])

    def test_conditional_uncertain_cancelled_new_target_remains_pending(self):
        for text in ('If the train runs, ' + NEW,
                     NEW[:-1] + ' Only if the road opens.',
                     NEW[:-1] + ' That arrival is cancelled.',
                     NEW[:-1] + ' The new plan is not confirmed.',
                     NEW[:-1] + '?',
                     'My new arrival might be 17 April 2028 at 11:45; replace my 14 April visit.'):
            with self.subTest(text=text):
                plan = current(self.episode(text))
                self.assertNotEqual(plan['plan_status'], 'planned')
                self.assertIsNone(plan['event_time']['when'])
                self.assertIsNone(plan['replacement_reference'])

    def test_unrelated_clinical_assertion_does_not_pollute_new_arrival(self):
        ep = Episode(SCENARIO)
        add(ep, 'old', OLD)
        clinical = 'Sam was discharged on 9 April 2028 at 15:05.'
        arrival = 'My new arrival is 17 April 2028 at 11:45'
        add(ep, 'new', clinical + ' ' + NEW, facts=[{'type': 'discharged', 'quote': clinical},
                                                  {'type': 'family', 'what': 'New arrival', 'quote': arrival}])
        plan = current(ep)
        self.assertEqual(plan['text'], NEW)
        self.assertEqual(plan['event_time']['when'], '2028-04-17T11:45:00+01:00')
        self.assertEqual(plan['supporting_sources'][0]['quote'], NEW)

    def test_other_person_or_multiple_targets_cannot_bind_my_arrival(self):
        for text in ('My new arrival is 17 April 2028 at 11:45; replace Rory\'s 14 April visit.',
                     'Our new arrival is 17 April 2028 at 11:45; replace my 14 April visit.',
                     'My new arrival is 17 April or 18 April 2028; replace my 14 April visit.',
                     'My new arrival is 17 April 2028; replace my 14 April or 15 April visit.',
                     'My new arrival is 17 April 2028; replace my 14 April visit and Rory\'s 15 April visit.'):
            with self.subTest(text=text):
                plan = current(self.episode(text))
                self.assertIsNone(plan['event_time']['when'])
                self.assertIsNone(plan['replacement_reference'])

    def test_explicit_cross_year_pair_can_resolve_but_omitted_year_cannot(self):
        ep = Episode(SCENARIO)
        add(ep, 'old', 'I will visit on 30 December 2028 at 16:25.', at='2028-12-20T09:00:00+00:00')
        text = 'My new arrival is 3 January 2029 at 11:45; replace my 30 December 2028 visit.'
        add(ep, 'new', text, at='2028-12-20T10:00:00+00:00')
        self.assertEqual(current(ep)['event_time']['when'], '2029-01-03T11:45:00+00:00')
        ep.revise_update('new', {'text': text.replace('30 December 2028', '30 December')},
                         expected_revision=1, request_id='omit-year', facts=[])
        self.assertIsNone(current(ep)['event_time']['when'])

    def test_same_day_changed_clock_uses_only_new_clock(self):
        ep = self.episode('My new arrival is 14 April 2028 at 11:45; replace my 14 April visit.')
        self.assertEqual(current(ep)['event_time']['when'], '2028-04-14T11:45:00+01:00')

    def test_old_explicit_clock_must_match_original_target(self):
        ep = self.episode('My new arrival is 17 April 2028 at 11:45; replace my 14 April at 12:25 visit.')
        self.assertEqual(current(ep)['event_time']['when'], '2028-04-17T11:45:00+01:00')
        self.assertIsNone(current(ep)['replacement_reference'])

    def test_prior_other_actor_does_not_bind(self):
        ep = Episode(SCENARIO)
        add(ep, 'old', OLD, author='rory')
        add(ep, 'new', NEW)
        self.assertEqual(current(ep)['event_time']['when'], '2028-04-17T11:45:00+01:00')
        self.assertEqual(refs(current(ep)), {('new', 1)})


class ReferenceLifecycle(unittest.TestCase):
    def episode(self, latest):
        ep = Episode(SCENARIO)
        add(ep, 'old', OLD)
        add(ep, 'latest', latest)
        return ep

    def test_snapshot_preserves_cancelled_reference_without_journal_mutation(self):
        ep = self.episode(CANCEL)
        events = copy.deepcopy(ep.events)
        expected = current(ep)
        restored = Episode.from_snapshot(ep.to_snapshot())
        self.assertEqual(current(restored), expected)
        self.assertEqual(restored.events, events)
        self.assertEqual(refs(expected), {('old', 1), ('latest', 1)})

    def test_revising_old_target_invalidates_cancelled_reference(self):
        ep = self.episode(CANCEL)
        corrected = 'I will visit on 15 April 2028 at 16:25.'
        ep.revise_update('old', {'text': corrected}, expected_revision=1, request_id='correct-old',
                         facts=[{'type': 'family', 'what': 'Visit', 'quote': corrected}])
        self.assertEqual(current(ep)['update_id'], 'old')  # edits are new plan statements in the existing journal contract
        ep.revise_update('latest', {}, expected_revision=1, request_id='reaffirm-cancel')
        plan = current(Episode.from_snapshot(ep.to_snapshot()))
        self.assertIsNone(plan['cancellation_reference'])
        self.assertEqual(refs(plan), {('latest', 2)})

    def test_revising_old_clock_refreshes_matching_reference_revision(self):
        ep = self.episode(CANCEL)
        corrected = OLD.replace('16:25', '17:20')
        ep.revise_update('old', {'text': corrected}, expected_revision=1, request_id='correct-clock',
                         facts=[{'type': 'family', 'what': 'Visit', 'quote': corrected}])
        ep.revise_update('latest', {}, expected_revision=1, request_id='reaffirm-cancel')
        plan = current(Episode.from_snapshot(ep.to_snapshot()))
        self.assertEqual(plan['cancellation_reference']['time']['when'], '2028-04-14T17:20:00+01:00')
        self.assertEqual(refs(plan), {('old', 2), ('latest', 2)})

    def test_deleting_old_source_removes_reference_but_preserves_explicit_new_target(self):
        ep = self.episode(NEW)
        self.assertEqual(current(ep)['plan_status'], 'planned')
        ep.delete_update('old', expected_revision=1, request_id='delete-old')
        plan = current(Episode.from_snapshot(ep.to_snapshot()))
        self.assertEqual(plan['plan_status'], 'planned')
        self.assertEqual(plan['event_time']['when'], '2028-04-17T11:45:00+01:00')
        self.assertIsNone(plan['replacement_reference'])
        self.assertEqual(refs(plan), {('latest', 1)})

    def test_other_members_order_does_not_change_target_binding(self):
        observations = []
        for other_first in (False, True):
            ep = Episode(SCENARIO)
            if other_first:
                add(ep, 'other', OLD, author='rory')
            add(ep, 'old', OLD)
            if not other_first:
                add(ep, 'other', OLD, author='rory')
            add(ep, 'latest', NEW)
            plan = current(ep)
            observations.append((plan['event_time']['when'], refs(plan)))
        self.assertEqual(observations[0], observations[1])
        self.assertEqual(observations[0][0], '2028-04-17T11:45:00+01:00')


if __name__ == '__main__':
    unittest.main(verbosity=2)
