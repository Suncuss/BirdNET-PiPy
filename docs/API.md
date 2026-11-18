# API

## Species summary

`GET /api/species/summary` returns detection counts and first/last timestamps
for every species in a date range. Installations with authentication disabled
can call it without signing in. With authentication enabled, it is visible to
anonymous visitors only when the station makes its charts public; otherwise it
requires an authenticated owner session.

| Parameter | Meaning |
|---|---|
| `start_date` | First included station-local date, `YYYY-MM-DD` |
| `end_date` | Last included station-local date, `YYYY-MM-DD` |
| `hours` | Rolling window: detections in the last 1–168 hours |

Supply both dates, or `hours`, or neither for all history; combining `hours`
with dates returns `400`. For longer spans than a week, use dates. Both calendar days are included;
timestamps use the station's local time, identified by the response's IANA
`timezone`. First/last timestamps refer to the requested range, not the species'
lifetime. `hours` counts elapsed time, so a window that crosses a daylight
saving change still covers exactly that many hours. Unused window fields (`start_date`/`end_date` or `hours`) are `null`.

Example request:

```http
GET /api/species/summary?start_date=2026-11-07&end_date=2026-11-13
```

Example response (illustrative data):

```json
{
  "start_date": "2026-11-07",
  "end_date": "2026-11-13",
  "hours": null,
  "timezone": "Australia/Brisbane",
  "species": [
    {
      "scientific_name": "Gymnorhina tibicen",
      "common_name": "Australian Magpie",
      "display_common_name": "Australian Magpie",
      "count": 128,
      "first_detected": "2026-11-07T05:12:30",
      "last_detected": "2026-11-13T16:45:12"
    }
  ]
}
```

Species follow the catalog's scientific-name and taxonomy grouping. Legacy
records without scientific names are grouped by common name. `common_name` is
PiPy's stored English name; `display_common_name` is translated into the
station's bird-name language setting. Counts describe detections, not individual birds.
Results include all matching species, ordered by count descending, then
scientific name and common name ascending for ties. An empty range returns
`200` with `"species": []`.

Malformed dates, a missing date partner, a reversed range or an out-of-range
`hours` return `400` with
an `error` message. Unauthorized requests return `401`. This endpoint returns
no individual detection records, media URLs or station coordinates.
