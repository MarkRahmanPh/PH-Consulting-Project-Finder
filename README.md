# PH Consulting Project Finder

## Make it update daily
1. Create a new GitHub repository (public if using free GitHub Pages).
2. Upload **all files**, including `.github/workflows/daily-update.yml`, to the repository root.
3. In repository **Settings → Pages**, select **Deploy from a branch**, `main`, `/ (root)` and save.
4. In **Actions**, enable workflows if prompted, then open **Daily PH opportunity discovery** and click **Run workflow** once.
5. Open the Pages website at `https://YOUR-USERNAME.github.io/YOUR-REPO/`.

The scheduled workflow refreshes the JSON each day. GitHub Actions scheduled runs may be delayed, and the UTC schedule is 7 AM Pacific standard time / 8 AM Pacific daylight time. To have a consistent 7 AM Pacific time year-round, adjust the UTC cron seasonally or use a timezone-aware scheduler.

## Important limitations
- This is a **lead discovery dashboard**, not a verified list of open RFPs. Search news results can include closed, irrelevant, duplicated or stale solicitations. Due dates are intentionally marked **Not verified**.
- Google News RSS is an unofficial discovery feed; results can be incomplete or unavailable. Agency portals often require login or JS and cannot be reliably searched by this method.
- Running `index.html` directly as a `file://` URL may block JSON fetching. Use GitHub Pages or `python -m http.server 8000` in this folder.
- For production use, add official agency procurement APIs and a review/verification process before labeling any opportunity active.
