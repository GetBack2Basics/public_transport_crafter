# Proposed additions to `ai_anti_mock_hallucination_playbook.md`

Source: NSW Public Transport Crafter session (stop classification, activity checks, GCS-only processing).
Paste under **Section 10.1** (new failure modes, numbered 17-24) and add the recipe + checklist lines below.

---

## New failure modes

17. **The "Name-Keyword Classification" Trap**: Mode/type is inferred from substrings in a free-text name (`"Station" in stop_name` -> train, `"Wharf"` -> ferry). Fire stations, service stations, "Station St" bus stops and "Old Toronto Station" (a *bus* stop) all became "Train Station". **Fix**: classify from the authoritative schema field (GTFS `route_type` of the routes that serve the stop). Keywords may nominate candidates only, never decide the type.

18. **The "Exists != Active" Trap**: Official datasets contain historic, closed or unserved entities (e.g. a heritage railway station with no trains). Presence in a table was treated as "this runs". **Fix**: verify liveness separately - scheduled `stop_times` inside calendar validity, a status field, or a last-seen date - and drop or flag anything that fails.

19. **The "Silent Local Fallback" Trap**: The pipeline claims to run on the cloud lakehouse but rewrites `gs://...` paths to a local mirror (`.replace("gs://bucket/lake/", "data/lake/")`) or falls back to local views when the cloud connection fails. Output looks cloud-backed but is computed from a stale local copy. **Fix**: fail closed. Raise if the engine is not on the target store, make local an explicit opt-in (`ALLOW_LOCAL_LAKE=1`), and log the data source at startup.

20. **The "Default Positive Status String" Trap**: UI falls back to reassuring text ("Active Transit Node", "High Feeder Transfer Volume") when no data exists. **Fix**: unknown must read as unknown ("Opal tap data not published at stop level"); only show a positive status computed from data.

21. **The "Fixed in Code, Stale in Artifact" Trap**: The generator is fixed, but the precomputed JSON the app actually reads is unchanged; merge-on-regenerate also carries stale scenarios forward. **Fix**: after any logic change, regenerate and re-inspect the *published* artifact, and add a read-time guard where the app consumes it.

22. **The "Delete Before Dependency Check" Trap**: A "stale" local file was deleted. It was read by the server, three tests and a deploy script, was gitignored, and the bucket had no versioning - so it could not be restored. **Fix**: before deleting/overwriting, grep every consumer, diff keys against the cloud copy, confirm the cloud copy is a superset, and enable bucket versioning or snapshot first.

23. **The "Tests Pass Against the Wrong Copy" Trap**: Tests read the local file and passed; pointed at the published artifact, one asserted a scenario (`dubbo_train_station`) that no generator produces. **Fix**: tests read the published artifact, and every asserted scenario must map to a generator (orphan-assertion check).

24. **The "Ambiguous Identifier" Trap**: `route_short_name = '99'` resolved to a different agency's route than intended. **Fix**: key on agency + route id, and print what was resolved.

---

## New recipe: classification + liveness gate (Recipe 8)

```python
# tests/lint/test_node_classification_and_liveness.py
SQL = """
WITH served AS (
  SELECT s.stop_name, s.stop_lat, s.stop_lon, r.route_type
  FROM stops s JOIN stop_times st ON st.stop_id = s.stop_id
  JOIN trips t ON t.trip_id = st.trip_id JOIN routes r ON r.route_id = t.route_id
  JOIN calendar c ON c.service_id = t.service_id
  WHERE c.end_date >= strftime(current_date, '%Y%m%d')
  GROUP BY ALL)
SELECT * FROM served
"""
def test_every_node_is_served_and_mode_matches_route_type(engine, infrastructure):
    served = {(r.stop_name, round(r.stop_lat, 4), round(r.stop_lon, 4)): mode_of(r.route_type)
              for r in engine.execute_query(SQL).itertuples()}
    for n in infrastructure:
        key = (n["name"], round(n["lat"], 4), round(n["lon"], 4))
        assert key in served, f"{n['name']} has no active scheduled service"
        assert n["mode"] in served[key] or n["mode"] == served[key], f"{n['name']} mode mismatch"
```

Also add to **Tier 3**: a *source-of-truth probe* asserting the query engine's filesystem is the cloud store before any write-back.

## Process lessons (10.2)

- Run a `--no-upload` dry run and review the output before publishing.
- Publish via temp files; never keep a persistent local mirror of cloud data.
- Check object versioning before any overwrite; say plainly when a destructive step may have lost data.

## New checklist lines

- [ ] **Mode/Type Derived from Schema, Not Names**: no substring-based classification.
- [ ] **Liveness Verified**: every displayed entity has current scheduled service or a status.
- [ ] **No Default Positive Status Text**: unknown data is labelled unknown.
- [ ] **Source Probe Passed**: run executed against the cloud store, no local substitution.
- [ ] **Published Artifact Re-inspected After Regeneration**.
- [ ] **Consumers Grepped and Cloud Superset Confirmed Before Deleting Any Data File**.
- [ ] **Tests Read the Published Artifact; No Orphan Assertions**.

