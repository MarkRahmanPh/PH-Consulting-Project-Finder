# PH Consulting Project Opportunity Finder

Live dashboard: https://markrahmanph.github.io/PH-Consulting-Project-Finder/

## Search coverage and limits

GitHub Actions runs `update.py` at minute **17 of every hour** (UTC and Pacific time both share the minute). It may start late during GitHub scheduling congestion. Each execution attempts up to **40 rotating agency sites** (default configured by `PH_AGENCY_BATCH`), plus the available official index pages and the supplemental public OregonBuys and WSDOT search pages.

Sources and discovery routes:
- Washington OMWBE and WEBS official public listings.
- Oregon Port of Coos Bay notices.
- OregonBuys public open-bid search (public listings only; pre-solicitations are never labeled open RFQs).
- WSDOT consulting opportunities, when exposed in parseable public HTML.
- City, county, port, and transit procurement pages in WA and OR, with WA prioritized and periodic source rotations.
- Search-engine news RSS keyword discovery for eight PH practice areas; these are **unverified leads**, not confirmed open bid requests.
- DJC A/E Wanted and restricted supplier portals appear as **manual-review sources**, not successful automated crawls.

The agency catalog is a directory, **not** proof all municipalities have been scanned. Coverage numbers separate listed agencies, sites with URLs, pages attempted and pages accessed. A fetched page with zero matching notices might mean no results, website layout changes, or JS-only content; it does not establish there are no opportunities.

### Scope filter
Keep engineering design, PS&E, traffic signal/ITS programming and design, planning, railroad/grade-crossing design, ADA/pedestrian design, on-call consultant rosters and safety/transportation studies. Exclude construction-only contractor bid packages, construction-management-only work, inspection-only contracts and general informational webpages. Combined design and construction support is eligible only when design services are specifically named.

### Running and checking
1. In GitHub Actions, open `Daily PH opportunity discovery`; choose **Run workflow** for an immediate run.
2. The workflow first runs `python -m py_compile update.py agency_sources.py procurement_sources.py`, then `python update.py`.
3. Open `opportunities.json` to inspect `last_run_iso`, `agency_coverage`, `source_checks`, `manual_review_sources` and `searchable_agency_targets` after a successful update.
4. On the dashboard press **Refresh data** to load the latest saved data. The button itself does not search procurement sites.

## Known technical limitations
- Many portals require logins, subscriptions, or JavaScript rendering. They cannot be fully crawled from a minimal Python stdlib-only GitHub Action.
- Search indexes and RSS feeds may not contain newly posted solicitations immediately, and may miss them entirely.
- Publication dates are distinct from first-discovered dates and proposal deadlines. A pre-solicitation or RFI should never automatically be labeled an open RFP.
- Wider coverage requires more **valid official procurement URLs, official vendor APIs or licensed feeds**, not merely larger agency counts.
- This is a discovery tool; verify the issuing agency's actual solicitation PDF, addenda, eligibility and closing date before pursuing work.

## Agency coverage repairs (October 2026)

The agency catalog is a geographic directory, not a crawler of all listed cities.
Only rows with independently verified procurement/agency website URLs are scanned.
The actual counts are reported by `searchable_agency_targets` and
`agency_coverage` in `opportunities.json`. A portal may be accessible without
exposing bid records or proposal documents for automated extraction.

`agency_sources.py` now seeds known procurement URLs for additional WA cities
(including Des Moines, SeaTac, Olympia, Snohomish, DuPont, Kent, Renton,
Burien, Shoreline and Puyallup) and OR cities/transit/port agencies.
For CivicEngage `Bids.aspx` sites, the search can verify RFQ/RFP status and
deadline from each individual numeric-ID bid page. PDF-only "Read full RFP"
pages require an actual bid-specific description; global website navigation
does not establish consulting scope. Spokane Transit individual
`/bidding-opportunity/` notices receive separate scope and deadline checks.

**Vendor portal limitation:** Community Transit (ProcureWare), TriMet, Port of
Portland (PlanetBids), Sherwood (Beacon), and other agencies may require
registration or use JavaScript-only vendor portals. Their public procurement
landing pages are useful sources, but a successful fetch does **not** prove
all their open notices were automatically indexed.

Offline regression tests are in `test_discovery.py`; the
`.github/workflows/test-discovery.yml` workflow tests code pushes. The
hourly `daily-update.yml` workflow handles live discovery and publication.
GitHub Actions runs can be delayed or fail; verify the latest completed
run's source status and then use **Refresh data** in the dashboard.
