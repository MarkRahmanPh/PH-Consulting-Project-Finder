"""Offline regression tests for the PH Consulting opportunity finder.

These guard against known false positives and missed real consultant RFQs.
Tests must not make network requests or modify opportunities.json.
"""
import unittest
import update as finder
import agency_sources as agencies


class OpportunityDiscoveryTests(unittest.TestCase):
    def test_tsp_rfqs_classify_as_its_and_high_priority(self):
        titles = [
            "RFQ Transit Signal Priority System Integration Services",
            "RFP Bus Signal Priority Engineering and Implementation",
            "On-Call TSP Signal Controller Integration Consultant",
            "RFQ Transit Signal Prioritization Study",
            "RFP Bus Priority at Traffic Signals Design Services",
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertEqual(finder.classify_title(
                    title, require_procurement=True), "its")
                self.assertEqual(finder.priority(title), "HIGH")
                self.assertTrue(finder.is_tsp_record(
                    {"title": title, "summary": "", "url": ""}))

    def test_generic_transit_study_not_marked_as_tsp(self):
        row = {"title": "RFP Transit Service Planning Study",
               "summary": "Transit route network service planning"}
        self.assertFalse(finder.is_tsp_record(row))

    def test_tsp_only_construction_bid_excluded(self):
        title = "Invitation to Bid Construction of Transit Signal Priority Infrastructure"
        self.assertIsNone(finder.classify_title(
            title, require_procurement=True))
        self.assertFalse(finder.is_tsp_record(
            {"title": title, "summary": title}))

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

    def test_live_style_civicengage_bid_detail_verification(self):
        """Listings with project-only titles become confirmed open RFQs only
        after their own individual bid detail page verifies RFQ and Open."""
        from unittest.mock import patch
        index = """
        <div><a href="/bids.aspx?bidID=362">Transportation Engineering On-Call</a></div>
        <div><a href="/bids.aspx?bidID=363">Traffic Signal Timing On-Call</a></div>
        <div><a href="/bids.aspx?bidID=364">Transportation Engineering On-Call II</a></div>
        """
        open_detail = """
        <table><tr><td>Bid Number:</td><td>RFQ 10922-26</td></tr>
        <tr><td>Status:</td><td>Open</td></tr>
        <tr><td>Closing Date/Time:</td><td>11/4/2026 3:00 AM</td></tr>
        </table>
        """
        closed_detail = """
        <table><tr><td>Bid Number:</td><td>RFQ 10923-26</td></tr>
        <tr><td>Status:</td><td>Closed</td></tr></table>
        """
        nonrfq_detail = """
        <table><tr><td>Bid Number:</td><td>ITB 10924-26</td></tr>
        <tr><td>Status:</td><td>Open</td></tr></table>
        """
        def fake_fetch(url, timeout=9):
            bidid = url.split("bidID=")[-1]
            return {"362": open_detail, "363": closed_detail,
                    "364": nonrfq_detail}[bidid]
        agency = {"id": "WA|city|redmond", "name": "Redmond",
                  "state": "WA", "kind": "city"}
        with patch.object(finder, "fetch", side_effect=fake_fetch):
            rows = finder.scan_civicengage_bid_details(
                index, "https://www.redmond.gov/bids.aspx", agency, "2026-10-15"
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Transportation Engineering On-Call")
        self.assertEqual(rows[0]["due_date"], "2026-11-04")
        self.assertEqual(rows[0]["opportunity_stage"], "open_solicitation")
        self.assertEqual(rows[0]["source_kind"], "official_detail")
        self.assertIn("bidID=362", rows[0]["url"])

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
