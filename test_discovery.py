"""Offline regression tests for the PH Consulting opportunity finder.

These guard against known false positives and missed real consultant RFQs.
Tests must not make network requests or modify opportunities.json.
"""
import unittest
import update as finder
import agency_sources as agencies


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

    def test_civicengage_redmond_listing_is_extracted(self):
        # End-to-end agency-page fixture: project title does not say RFQ;
        # its individual card carries the solicitation type.
        html = """
        <html><body>
          <div class="bid-item">
            <a href="/bids.aspx?bidID=362">Transportation Engineering On-Call</a>
            <p>Bid No. RFQ 10922-26. Status: Open.
            Statements of Qualifications for transportation engineering services.</p>
          </div>
          <div class="bid-item">
            <a href="/bids.aspx?bidID=363">Traffic Signal Timing On-Call</a>
            <p>Bid No. RFQ 10923-26. Status: Open.</p>
          </div>
          <div class="bid-item">
            <a href="/bids.aspx?bidID=364">Transportation Engineering Construction Management Only</a>
            <p>Bid No. RFQ 10924-26. Status: Open.</p>
          </div>
        </body></html>
        """
        source = {
            "id": "WA|city|redmond", "name": "Redmond",
            "state": "WA", "kind": "city",
        }
        bids = agencies.scan_agency_bids(
            html, "https://www.redmond.gov/bids.aspx", source,
            finder.Document, finder.absolute, finder.classify_title,
            finder.safe_single_item_scope, finder.safe_listing_due,
            finder.remove_trailing_date, finder.standard_row, "2026-10-15",
        )
        titles = [b["title"] for b in bids]
        self.assertIn("Transportation Engineering On-Call", titles)
        self.assertIn("Traffic Signal Timing On-Call", titles)
        self.assertEqual(len(bids), 2)  # CM-only rejected
        self.assertEqual(len({b["id"] for b in bids}), 2)
        self.assertTrue(any("bidID=362" in b["url"] for b in bids))

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
