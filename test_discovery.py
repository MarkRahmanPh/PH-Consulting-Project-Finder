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

    def test_numeric_civicengage_bid_numbers_need_consultant_scope(self):
        """Numeric CivicEngage RFPs qualify with verified consultant scope
        or the city's linked official 'Read full RFP' document notice."""
        from unittest.mock import patch
        index = """
        <a href="/bids.aspx?bidID=3">Safe Streets for All Request for Qualifications</a>
        <a href="/bids.aspx?bidID=4">6th Avenue South Pedestrian Safety Improvement Project</a>
        """
        details = {
            "3": "<p>Bid Number: 26-002</p><p>Status: Open</p>"
                 "<p>Description: The City requests qualifications from consulting firms for "
                 "engineering, planning, demonstration evaluation and design.</p>"
                 "<p>Closing Date/Time: 10/22/2026 4:00 PM</p>",
            "4": "<p>Bid Number: 26-003</p><p>Status: Open</p>"
                 "<p>Description: Read full RFP here</p>"
                 "<p>Closing Date/Time: 11/5/2026 4:00 PM</p>"
        }
        def fake_fetch(url, timeout=9):
            return details[url.split("bidID=")[-1]]
        agency = {"id": "WA|city|des moines", "name": "Des Moines",
                  "state": "WA", "kind": "city"}
        with patch.object(finder, "fetch", side_effect=fake_fetch):
            result = finder.scan_civicengage_bid_details(
                index, "https://www.desmoineswa.gov/Bids.aspx",
                agency, "2026-10-16")
        self.assertEqual(len(result), 2)
        by_bid = {r["url"].split("bidID=")[-1]: r for r in result}
        self.assertEqual(by_bid["3"]["due_date"], "2026-10-22")
        self.assertEqual(by_bid["4"]["due_date"], "2026-11-05")
        self.assertEqual(by_bid["4"]["category"], "ada")

    def test_civicengage_global_navigation_does_not_authorize_rfqs(self):
        """Marketing text elsewhere on the page cannot turn an ITB into an RFQ."""
        from unittest.mock import patch
        index = '<a href="/bids.aspx?bidID=10">Roadway Improvements RFQ</a>'
        detail = (
            "<p>All consultants may register. Request for Proposals are advertised"
            " throughout the year.</p>"
            "<p>Bid Number: 26-010</p><p>Status: Open</p>"
            "<p>Description: Sealed construction bids for asphalt paving.</p>"
            "<p>Publication Date/Time: 10/1/2026</p>"
            "<p>Closing Date/Time: 11/8/2026 3:00 PM</p>")
        agency = {"id": "WA|city|des moines", "name": "Des Moines",
                  "state": "WA", "kind": "city"}
        with patch.object(finder, "fetch", return_value=detail):
            found = finder.scan_civicengage_bid_details(
                index, "https://www.desmoineswa.gov/bids.aspx",
                agency, "2026-10-16")
        self.assertEqual(found, [])

    def test_des_moines_agency_source_is_configured(self):
        catalog = agencies.seeded_catalog([])
        row = catalog["WA|city|des moines"]
        self.assertEqual(row["procurement_url"],
                         "https://www.desmoineswa.gov/Bids.aspx")

    def test_des_moines_legal_notice_finds_pedestrian_design_rfq(self):
        # City lists public engineering RFQs on a legal-notices page, linking
        # directly to DocumentCenter PDFs rather than a conventional bids page.
        html = """
        <html><body><main><ul>
          <li><a href="/DocumentCenter/View/6966">
          Request for Qualifications - 6th Avenue South Pedestrian Safety
          Improvement Project</a> - 11/5/2026</li>
          <li><a href="/DocumentCenter/View/9999">
          Construction-Only Sidewalk Replacement Invitation to Bid</a></li>
        </ul></main></body></html>"""
        agency = {"id": "WA|city|des moines", "name": "Des Moines",
                  "state": "WA", "kind": "city"}
        found = agencies.scan_agency_bids(
            html, "https://www.desmoineswa.gov/171/Public-Hearings-Legal-Notices",
            agency, finder.Document, finder.absolute, finder.classify_title,
            finder.safe_single_item_scope, finder.safe_listing_due,
            finder.remove_trailing_date, finder.standard_row, "2026-10-16")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["category"], "ada")
        self.assertIn("/DocumentCenter/View/6966", found[0]["url"])

    def test_spokane_transit_individual_rfp_detail(self):
        """A project-title-only index must be checked against its own
        future, explicitly advertised, consultant RFP detail."""
        from unittest.mock import patch
        index = """
        <a href="/bidding-opportunity/26-signal-engineering/">
        Signal Timing and Transit Priority Engineering Services</a>
        <a href="/bidding-opportunity/26-staffing/">
        Temporary Staffing Services</a>
        <a href="/bidding-opportunity/25-traffic-old/">
        Traffic Signal Timing Consultant Services (2025)</a>
        """
        detail = (
            "<h1>Signal Timing and Transit Priority Engineering Services</h1>"
            "<p>REQUEST FOR PROPOSALS 2026-101</p>"
            "<p>Proposals will be accepted until November 20, 2026, "
            "4:00 p.m. Pacific Time.</p>")
        old = (
            "<h1>Traffic Signal Timing Consultant Services</h1>"
            "<p>REQUEST FOR PROPOSALS 2025-015</p>"
            "<p>Proposals will be accepted until September 12, 2025.</p>")
        def fake_fetch(url, timeout=9):
            if "26-signal-engineering" in url:
                return detail
            if "25-traffic-old" in url:
                return old
            raise AssertionError("Unrelated staffing bid should not be fetched")
        agency = {"id": "WA|transit|spokane transit", "name": "Spokane Transit",
                  "state": "WA", "kind": "transit"}
        with patch.object(finder, "fetch", side_effect=fake_fetch):
            result = finder.scan_transit_bid_details(
                index, "https://www.spokanetransit.com/bidding-opportunities/",
                agency, "2026-10-16")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["due_date"], "2026-11-20")
        self.assertEqual(result[0]["source_kind"], "official_detail")

    def test_no_duplicate_procurement_seed_sources(self):
        keys = [(state, kind, name)
                for state, kind, name, _ in agencies.VERIFIED_PROCUREMENT_PAGES]
        self.assertEqual(len(keys), len(set(keys)))
        catalog = agencies.seeded_catalog([])
        self.assertIn("WA|city|seatac", catalog)
        self.assertIn("WA|city|olympia", catalog)
        self.assertIn("WA|transit|spokane transit", catalog)
        self.assertIn("OR|city|lake oswego", catalog)

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

    def test_hourly_refresh_preserves_verified_summary_priority_and_time(self):
        url = "https://www.desmoineswa.gov/bids.aspx?bidID=4"
        old = {
            "id": "curated-des-moines", "url": url,
            "title": "RFQ 26-003 — 6th Avenue South Pedestrian Safety Improvement",
            "summary": ("Verified design RFQ for approximately 1,000 feet of "
                        "ADA ramps, sidewalks, crosswalks and bid-ready PS&E."),
            "role": "Potential prime design consultant",
            "due_time": "4:00 PM PT",
            "due_date": "2026-11-05", "priority": "HIGH",
            "verified_on": "2026-10-16", "source_kind": "official_detail",
            "first_seen": "2026-10-16"
        }
        observed = finder.standard_row(
            "6th Avenue South Pedestrian Safety Improvement Project",
            "Des Moines", "WA", url,
            "6th Avenue South Pedestrian Safety Improvement Project",
            "Des Moines individual open RFQ", "2026-10-17",
            listing=True, observed_due="2026-11-05")
        rows = {old["id"]: old}
        result = finder.apply_observation(rows, observed, "2026-10-17")
        self.assertEqual(result["id"], old["id"])
        self.assertEqual(result["summary"], old["summary"])
        self.assertEqual(result["priority"], "HIGH")
        self.assertEqual(result["due_time"], "4:00 PM PT")
        self.assertEqual(result["role"], old["role"])
        self.assertEqual(len(rows), 1)

    def test_guidance_page_is_not_a_procurement(self):
        record = {
            "title": "Land use & transportation planning",
            "url": "https://wsdot.wa.gov/engineering-standards/planning-guidance/land-use-transportation-planning",
        }
        self.assertFalse(finder.is_strictly_relevant_record(record))


if __name__ == "__main__":
    unittest.main()
