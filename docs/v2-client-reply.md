# Client reply — Dashboard v2

Draft. Edit the greeting/sign-off and add the recipient name before sending.

---

Thanks for the notes — these are the right ones, and most are going straight into the next build. Here's what changes, and the one thing I'd like your read on.

**The Kentucky × Paid Search page becomes the template.** You're right that it's the strongest view, so the market page plus channel breakdown plus drilldown becomes the standard model for every market.

**The enterprise Paid Search page gets rebuilt as an exceptions view.** Aggregate ROI across markets doesn't tell anyone what to do next, so we're replacing it with a surface that shows only what's off: markets where cost per new patient is above threshold, campaigns where CPC moved week-over-week beyond a set band, and markets with new-patient volume drops. Everything healthy stays at the market level where it belongs.

**CPC gets a heatmap.** Market by campaign type (brand vs non-brand), colored by week-over-week movement with direction and percentage. Agreed that the trend tells you more than a point-in-time number.

**Organic, GBP, and Direct get their own drilldowns** on every market page. Lighter than Paid Search, since there's no spend or campaign structure under them, but present so the market view is complete.

**The 13-week trend charts move to secondary and collapsible.** Useful context, not the headline, and they were taking space the decisions deserve.

One honest constraint on campaign-level reporting. We can show spend, clicks, CPC, and leads per campaign right away from Google Ads, with leads being your form submits and calls. What we can't do yet is confidently attribute new patients down to the individual campaign. Your intake captures referral source as a self-reported selection (online, word of mouth, direct, and so on), which is solid at the channel level and shows online performing well, but it doesn't resolve to which campaign brought the patient in. Closing that gap means connecting the lead to the patient it becomes, by capturing the click identifier at form submit and call and matching it back at intake. So the campaign view ships with the full media-side funnel now (spend → clicks → leads), and cost-per-new-patient per campaign turns on once that tracking is in place. The end goal is exactly the one you'd want: new patients attributed up and down the full funnel by channel and source. Happy to scope what that tracking would take whenever you want to take it on.

On your question of live/dynamic vs weekly static: my recommendation is weekly static, and not as a compromise. Your new-patient numbers come in on a monthly cadence, so a live page would be querying systems in real time to display data that doesn't change during the day. A Monday-morning refresh matches the real rhythm, costs far less to run, and every new view above works on weekly snapshots without issue. If you ever want it to feel more live, the inexpensive version is an on-demand "refresh now" button rather than rebuilding it as a hosted application. Happy to talk it through if you'd rather go live.

Next build will include the exceptions page, the CPC heatmap, channel drilldowns across markets, collapsible trends, and the campaign view with media metrics. Campaign-level patient attribution stays on the roadmap, tied to getting lead-to-patient tracking in place.
