# API

## Species summary

`GET /api/species/summary` returns detection counts and first/last timestamps
for every species in a date range. It follows the station's public-visibility
setting: public stations allow anonymous requests; private stations require an
authenticated owner session.
The separate public-charts setting does not affect this endpoint.
Authentication-disabled installations can call it without signing in.

| Parameter | Meaning |
|---|---|
| `start_date` | First included station-local date, `YYYY-MM-DD` |
| `end_date` | Last included station-local date, `YYYY-MM-DD` |

Supply both dates or omit both for all history. Both calendar days are included;
timestamps use the station's local time, identified by the response's IANA
`timezone`. First/last timestamps refer to the requested range, not the species'
lifetime. With no dates, both response date fields are `null`.

Example request:

```http
GET /api/species/summary?start_date=2026-11-07&end_date=2026-11-13
```

Example response (illustrative data):

```json
{
  "start_date": "2026-11-07",
  "end_date": "2026-11-13",
  "timezone": "Australia/Brisbane",
  "species": [
    {
      "scientific_name": "Gymnorhina tibicen",
      "common_name": "Australian Magpie",
      "count": 128,
      "first_detected": "2026-11-07T05:12:30",
      "last_detected": "2026-11-13T16:45:12"
    }
  ]
}
```

Species follow the catalog's scientific-name and taxonomy grouping. Legacy
records without scientific names are grouped by common name. Common names use
PiPy's stored English names. Counts describe detections, not individual birds.
Results include all matching species, ordered by count descending, then
scientific name and common name ascending for ties. An empty range returns
`200` with `"species": []`.

Malformed dates, a missing date partner or a reversed range return `400` with
an `error` message. Unauthorized requests return `401`. This endpoint returns
no individual detection records, media URLs or station coordinates.
