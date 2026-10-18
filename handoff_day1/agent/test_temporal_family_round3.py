"""Bounded explicit English family rescheduling; independent fictional regressions."""
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
            'members': [{'member_id': 'alex', 'name': 'Alex'}, {'member_id': 'rory', 'name': 'Rory'}], 'updates': []}
OLD = 'I will visit on 14 April 2028 at 16:25.'
NEW = 'I have postponed my visit from 14 April 2028 at 16:25 to 17 April 2028 at 11:45.'


def setUpModule():
    print('TEMPORAL_FAMILY_ROUND3_V1 ' + json.dumps({
        module.__name__: {'path': module.__file__, 'sha256': hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
        for module in (episode, T)}), flush=True)


def add(ep, uid, text, *, author='alex', facts=None, at='2028-04-10T09:00:00+01:00'):
    result = ep.add_update({'update_id': uid, 'kind': 'note', 'author': author, 'at': at,
                            'topic': 'plan', 'text': text}, facts=copy.deepcopy(facts or [
                                {'type': 'family', 'what': 'Family plan', 'quote': text}]))
    if result['rejected']:
        raise AssertionError(result['rejected'])
    return result


def current(ep):
    return next(plan for plan in ep.plans() if plan['member_id'] == 'alex')


class ExplicitRescheduling(unittest.TestCase):
    def episode(self, text=NEW):
        ep = Episode(SCENARIO)
        add(ep, 'old', OLD)
        add(ep, 'new', text)
        return ep

    def test_positive_moved_postponed_rescheduled_from_to_forms(self):
        for verb in ('moved', 'postponed', 'rescheduled'):
            with self.subTest(verb=verb):
                plan = current(self.episode(NEW.replace('postponed', verb)))
                self.assertEqual((plan['plan_status'], plan['event_time']['when']), ('planned', '2028-04-17T11:45:00+01:00'))
                self.assertEqual(plan['replacement_reference']['time']['when'], '2028-04-14T16:25:00+01:00')
                self.assertEqual({ref['update_id'] for ref in plan['supporting_sources']}, {'old', 'new'})

    def test_date_only_new_target_never_inherits_old_clock(self):
        text = 'I moved my arrival from 14 April 2028 at 16:25 to 17 April 2028 in the afternoon.'
        plan = current(self.episode(text))
        self.assertEqual((plan['event_time']['when'], plan['event_time']['precision']), ('2028-04-17', 'part_of_day'))
        self.assertEqual(plan['event_time']['when_text'], '17 April 2028 in the afternoon')

    def test_negation_condition_alternative_and_extra_actor_remain_pending(self):
        for text in (NEW.replace('have postponed', 'have not postponed'),
                     'If the train runs, ' + NEW,
                     NEW[:-1] + ' Only if the train runs.',
                     NEW.replace('I have', 'We have'),
                     NEW.replace('my visit', "Rory's visit"),
                     NEW.replace('17 April 2028', '17 April or 18 April 2028'),
                     NEW[:-1] + ' and Rory will come too.',
                     NEW[:-1] + '?'):
            with self.subTest(text=text):
                plan = current(self.episode(text))
                self.assertNotEqual(plan['plan_status'], 'planned')
                self.assertIsNone(plan['event_time']['when'])

    def test_missing_new_year_crossyear_does_not_inherit_old_year(self):
        for text in ('I moved my visit from 30 December 2028 to 3 January.',
                     'I moved my visit from 30 December to 3 January 2029.'):
            ep = Episode(SCENARIO)
            add(ep, 'new', text, at='2028-12-20T09:00:00+00:00')
            self.assertIsNone(current(ep)['event_time']['when'])

    def test_explicit_crossyear_pair_uses_new_target(self):
        ep = Episode(SCENARIO)
        add(ep, 'old', 'I will visit on 30 December 2028 at 16:25.', at='2028-12-20T09:00:00+00:00')
        add(ep, 'new', 'I rescheduled my visit from 30 December 2028 at 16:25 to 3 January 2029 at 11:45.',
            at='2028-12-20T10:00:00+00:00')
        self.assertEqual(current(ep)['event_time']['when'], '2029-01-03T11:45:00+00:00')

    def test_old_source_correction_and_delete_change_only_old_reference(self):
        for operation in ('revise', 'delete'):
            ep = self.episode()
            if operation == 'delete':
                ep.delete_update('old', expected_revision=1, request_id='remove-old')
            else:
                text = 'I will visit on 15 April 2028 at 16:25.'
                ep.revise_update('old', {'text': text}, expected_revision=1, request_id='correct-old',
                                 facts=[{'type': 'family', 'what': 'Family plan', 'quote': text}])
            # Inspect this source's new target. Revising an older source may
            # promote that edited source under the existing latest-intent rule.
            entry = next(e for e in ep.entries if e['update_id'] == 'new')
            timing = episode.event_time(ep, entry, entry['lines'][0])
            self.assertEqual(timing['when'], '2028-04-17T11:45:00+01:00')
            self.assertIsNone(timing['replacement_reference'])

    def test_rescheduled_plan_can_supply_later_cancelled_target(self):
        ep = self.episode()
        add(ep, 'cancel', 'I have cancelled my 17 April 2028 visit.')
        plan = current(ep)
        self.assertEqual((plan['plan_status'], plan['event_time']['when']), ('withdrawn', '2028-04-17T11:45:00+01:00'))
        self.assertEqual(plan['event_time']['time_role'], 'withdrawn_target')

    def test_unrelated_member_interleaving_and_snapshot_preserve_result(self):
        results = []
        for other_first in (True, False):
            ep = Episode(SCENARIO)
            add(ep, 'old', OLD)
            if other_first:
                add(ep, 'other', 'I will visit on 16 April 2028.', author='rory')
            add(ep, 'new', NEW)
            if not other_first:
                add(ep, 'other', 'I will visit on 16 April 2028.', author='rory')
            restored = Episode.from_snapshot(ep.to_snapshot())
            results.append((current(ep)['event_time']['when'], current(restored)['event_time']['when']))
        self.assertEqual(results, [('2028-04-17T11:45:00+01:00', '2028-04-17T11:45:00+01:00')] * 2)

    def test_generic_same_reschedule_assertion_is_one_family_row(self):
        ep = Episode(SCENARIO)
        add(ep, 'old', OLD)
        add(ep, 'new', NEW, facts=[{'type': 'family', 'what': 'Family plan', 'quote': NEW},
                                  {'type': 'event', 'what': 'Visit rescheduled', 'quote': NEW}])
        rows = [row for row in T.event_entries(ep, 'alex', None) if row['update_id'] == 'new']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['event_time']['when'], '2028-04-17T11:45:00+01:00')
        self.assertIn(NEW, T.source_archive_html(ep))

    def test_independent_clinical_clause_is_retained(self):
        ep = Episode(SCENARIO)
        clinical = 'Robin has new severe pain.'
        add(ep, 'new', NEW + ' ' + clinical,
            facts=[{'type': 'family', 'what': 'Family plan', 'quote': NEW},
                   {'type': 'event', 'what': 'New severe pain', 'quote': clinical}])
        rows = T.event_entries(ep, 'alex', None)
        self.assertTrue(any(any(line['type'] == 'event' and line['quote'] == clinical for line in row['lines']) for row in rows))
        self.assertEqual(current(ep)['event_time']['when'], '2028-04-17T11:45:00+01:00')


if __name__ == '__main__':
    unittest.main(verbosity=2)
