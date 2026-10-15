"""Offline regression tests for the PH Consulting opportunity finder.

These guard against known false positives and missed real consultant RFQs.
Tests must not make network requests or modify opportunities.json.
"""
import unittest
import update as finder


class OpportunityDiscoveryTests(unittest.TestCase):
    def test_transportation_engineering_on_call_is_relevant(self):
        self.assertEqual(
            finder.classify_title(
                "Transportation Engineering On-Call",
                require_procurement=True,
            ),
            "civil",
        )

    def test_distinct_civicengage_bids_have_distinct_ids(self):
        a = "https://www.redmond.gov/bids.aspx?bidID=362"
        b = "https://www.redmond.gov/bids.aspx?bidID=363"
        self.assertNotEqual(finder.ident(a), finder.ident(b))

    def test_tracking_query_does_not_change_bid_id(self):
        a = "https://www.redmond.gov/bids.aspx?bidID=362"
        b = a + "&utm_source=github"
        self.assertEqual(finder.ident(a), finder.ident(b))

    def test_construction_management_only_is_excluded(self):
        self.assertIsNone(finder.classify_title(
            "RFQ Construction Management Services for Roadway Safety Improvements",
            require_procurement=True,
        ))

    def test_design_and_construction_support_can_be_included(self):
        self.assertEqual(finder.classify_title(
            "RFQ Traffic Signal Design Services and Construction Administration",
            require_procurement=True,
        ), "signal")

    def test_guidance_page_is_not_a_procurement(self):
        record = {
            "title": "Land use & transportation planning",
            "url": "https://wsdot.wa.gov/engineering-standards/planning-guidance/land-use-transportation-planning",
        }
        self.assertFalse(finder.is_strictly_relevant_record(record))


if __name__ == "__main__":
    unittest.main()
