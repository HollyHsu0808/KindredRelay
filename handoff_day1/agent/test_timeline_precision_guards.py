"""Clinical source scope must survive visit-like model paraphrases."""
import unittest

from test_timeline_precision import CANCEL, add, fact, preceding_plans, setUpModule
import timeline_html as T


class CancellationScopeGuards(unittest.TestCase):
    def test_visit_paraphrase_does_not_hide_independent_clinical_source_words(self):
        ep = preceding_plans()
        mixed = CANCEL + " Elena is unresponsive."
        add(ep, "cancel", mixed,
            [fact("family", CANCEL), fact("event", mixed, "No longer coming; cancel visit")])
        self.assertTrue(any(line["quote"] == mixed for row in T.event_entries(ep, "anna", None)
                            for line in row["lines"]))

    def test_short_request_does_not_erase_its_clinical_governor(self):
        ep = preceding_plans()
        text = "Please cancel my visit because Elena is blue."
        add(ep, "cancel", text, [fact("family", text), fact("event", "Please cancel my visit", "Cancel visit")])
        self.assertTrue(any(line["quote"] == "Please cancel my visit" for row in T.event_entries(ep, "anna", None)
                            for line in row["lines"]))

    def test_another_persons_withdrawal_is_not_the_authors_arrangement(self):
        ep = preceding_plans()
        text = "David can no longer come on October 21, 2026."
        add(ep, "cancel", text, [fact("family", text), fact("event", text, "No longer coming")])
        self.assertTrue(any(line["quote"] == text for row in T.event_entries(ep, "anna", None)
                            for line in row["lines"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
