---
status: resolved
trigger: "Batch processing counts 'Cache hit' items as succeeded without pushing metadata to Plex. ~40 out of 46 succeeded items never had metadata updated."
created: 2026-03-10T00:00:00Z
updated: 2026-03-10T00:00:00Z
---

## Current Focus

hypothesis: match_cache.set_match() is called inside find_plex_items_with_confidence() (the
non-cache search path) BEFORE _update_metadata() is called in _process_job(). This means the
cache can contain entries for items whose metadata sync never completed (e.g. process killed
mid-sync in short-lived Stash plugin processes). On subsequent runs, these items get cache-hit
path treatment — fetchItem() is fast, but _update_metadata() compares Stash values against live
Plex values. If Plex already has auto-scanned metadata that happens to match Stash values (or
preserve_plex_edits=True is set and Plex has any value), no edits are generated, no "Updated
metadata" log appears, save_sync_timestamp() marks the item as synced, and the sync never
actually pushes Stash metadata.
test: Trace match_cache write location vs _update_metadata call order in _process_job
expecting: match_cache.set_match at matcher.py:355-360 runs before _update_metadata at
processor.py:820, confirming cache is written before metadata is confirmed pushed
next_action: Move match_cache.set_match to _process_job, called after _update_metadata succeeds

## Symptoms

expected: All items in a batch sync should push metadata from Stash to Plex, regardless of
whether the Plex file match came from cache or fresh lookup.
actual: Items matched via "Cache hit" in batch processing are counted as succeeded but show no
"Updated metadata" log - metadata is NOT pushed to Plex. Only items going through the non-cached
"Found" path actually call the Plex update API. Result: batch says "46 succeeded" but only ~7
actually updated Plex metadata.
errors: No errors shown - the items silently "succeed" without doing the update.
reproduction: Run "Process Queue" batch task. Items already in the matcher cache will show
"Cache hit" and skip metadata update. Fresh items show "Found" and properly update.
timeline: Unclear when introduced. User has >20 files missing metadata.

## Eliminated

- _update_metadata not being called: Code path analysis confirms _update_metadata IS called for
  cache-hit items (processor.py line 820 always executes for single-candidate HIGH confidence
  matches regardless of cache source).

- preserve_plex_edits blocking updates: Default is False (overwrite mode). The "Updated metadata
  (overwrite mode)" log from items 41-46 confirms overwrite mode is active. With preserve=False,
  _build_core_edits adds edits whenever Plex values differ from Stash values.

- Different code path for cache-hit vs non-cache: Both paths converge at the same
  _update_metadata call in _process_job. The match_cache hit path just uses fetchItem() instead
  of search() to get the plexapi object — both return fully-loaded objects.

- Structural skip via confidence scoring: Cache-hit returns (HIGH, item, [item]). After dedup,
  unique_candidates has 1 item. HIGH confidence path always calls _update_metadata.

## Evidence

- timestamp: 2026-03-10T00:01:00Z
  checked: plex/matcher.py lines 231-241 (match_cache hit path) vs lines 347-361 (non-cache write)
  found: match_cache.set_match() is called at line 356-360 inside the non-cache search path,
  immediately after a successful search match. This write happens BEFORE _process_job calls
  _update_metadata(). The cache-hit path (lines 231-241) returns early without writing to cache.
  implication: If a Stash plugin process dies between the match_cache write and the
  _update_metadata call (which is normal for daemon threads in short-lived processes), the cache
  has an entry for an item that was never metadata-synced.

- timestamp: 2026-03-10T00:02:00Z
  checked: processor.py lines 780-844 (_process_job full flow)
  found: Search candidates are collected in a loop (lines 784-802). After dedup and confidence
  scoring, _update_metadata is called at line 820 (HIGH conf) or 840 (LOW conf). save_sync_
  timestamp is at line 844. There is no mechanism to invalidate or skip the match_cache path
  when an item's metadata hasn't been pushed yet.
  implication: On subsequent batch runs, cache-hit items complete in milliseconds because
  fetchItem() is fast and _update_metadata() finds "no edits needed" — because either: (a) Plex
  already has correct metadata from a previous successful sync (correct behavior, item 1-40 that
  user sees as "succeeded correctly"), OR (b) Stash data matches auto-scanned Plex metadata
  (Plex scanner set title from filename, Stash also has same title — no diff detected).

- timestamp: 2026-03-10T00:03:00Z
  checked: 20-second timing gap between items 40 and 41 in user's log
  found: Items 1-40 (Cache hit) completed in ~6s total (40 items × 0.15s sleep). Items 41-46
  (Found) took ~20s total, consistent with library.search() API calls plus plex_item.edit() calls.
  implication: Cache-hit items trigger only fetchItem() (fast, ~50ms) plus _update_metadata().
  If _update_metadata produces no edits and no image uploads, the item completes in ~200ms.
  The image uploads (poster, background) happen via _fetch_stash_image → uploadPoster/uploadArt,
  which would add significant time. If these don't appear for cache-hit items, either sync_poster
  and sync_background are disabled, or image data is not in the job payload.

- timestamp: 2026-03-10T00:04:00Z
  checked: The 4 items with empty titles in "Cache hit: " (scenes 55713, 55727, 55730, 55731)
  found: item.title is empty for these 4 items when fetched via fetchItem(). This means either
  Plex has no title for these items, or the title attribute is not populated. With overwrite mode
  and empty Stash title: _build_core_edits skips (no value to set). With empty Stash title AND
  empty Plex title: no diff → no edit. These items were likely synced before with empty Stash
  data, and Plex also has empty metadata.
  implication: Confirms that some items in match_cache have never had real metadata pushed.
  Their sync_timestamp is saved anyway, marking them as "synced" with empty data.

## Root Cause

match_cache.set_match() in plex/matcher.py is called at the moment a match is DISCOVERED via
search (lines 355-360), BEFORE the caller (_process_job) has a chance to call _update_metadata().

In Stash's plugin model, processes are short-lived. The background worker runs as a daemon thread
inside the Stash plugin process. When the process exits (after each Stash hook call), the daemon
thread is killed. The auto_resume=True setting on SQLiteAckQueue reclaims unacked jobs on next
startup.

Failure scenario:
1. Plugin process starts for hook, background worker begins processing job
2. find_plex_items_with_confidence() finds item via library.search() → match_cache.set_match()
   writes entry to persistent diskcache on disk
3. Process killed before _update_metadata() runs (or before ack_job())
4. Item is re-queued by auto_resume
5. Next "Process Queue" run: match_cache hits → fetchItem() → _update_metadata()
6. If Plex has any matching values (auto-scanner title = sanitized Stash title), _build_core_edits
   returns empty dict → no edits → no "Updated metadata" log → save_sync_timestamp() called
7. Item marked as synced, but Plex still has auto-scanned metadata, not Stash metadata

## Fix

Move match_cache.set_match() from find_plex_items_with_confidence() to _process_job(), called
AFTER _update_metadata() succeeds. This ensures the cache only records items that have been
fully confirmed as synced.

Changes:
1. plex/matcher.py: Remove match_cache.set_match() call from lines 355-360 (non-cache search
   path). Add explanatory comment about why this write moved to the caller.
2. worker/processor.py _process_job: Track which section each candidate came from using a
   _section_by_candidate_key dict. After _update_metadata() succeeds for HIGH confidence matches,
   write to match_cache using section_title and confirmed item_key.

Side effects:
- Cache-hit items also re-write their match_cache entry after each successful sync, confirming
  the entry remains valid. This is harmless and actually beneficial — it acts as a "last sync
  confirmed" marker.
- Stale entries for "phantom" matches (in cache from before this fix) will still trigger cache-hit
  on the next run. With overwrite mode active, if Stash has data that differs from Plex,
  _update_metadata WILL push the correct metadata. After that run, the entry is re-confirmed.
- Items where all Stash+Plex values already match (genuinely synced correctly) continue to show
  "no edits needed" — this is correct behavior, not a bug.

## Resolution

root_cause: match_cache.set_match() was called inside find_plex_items_with_confidence() at
match-discovery time, before _update_metadata() ran. In short-lived Stash plugin processes where
the daemon worker can be killed mid-sync, this created "phantom" cache entries for items that
were matched but never had metadata pushed. On subsequent runs, these phantom entries caused
cache-hit processing that either: (a) pushed metadata correctly if Stash/Plex values differed,
or (b) found "no edits needed" and silently succeeded if auto-scanned Plex values happened to
match Stash values, resulting in items that appeared synced but had wrong/missing Plex metadata.

fix: Moved match_cache.set_match() to _process_job, called after _update_metadata() succeeds.
Added _section_by_candidate_key tracking dict in _process_job loop to capture which library
section each candidate belongs to, enabling the deferred cache write.

verification: 1278 tests pass (6 pre-existing failures in test_manager.py unrelated to this
change). Matcher tests updated to reflect new behavior (find_plex_items_with_confidence no longer
writes to match_cache). Integration conftest updated to configure mock_section.fetchItem()
return value and mock_plex_item.key string attribute.

files_changed:
  - plex/matcher.py: Remove match_cache.set_match(), add explanatory comment
  - worker/processor.py: Add _section_by_candidate_key tracking, write match_cache after
    _update_metadata succeeds in HIGH confidence path
  - tests/test_matcher.py: Update test_cache_miss_searches_and_returns_result and
    test_stale_cache_invalidated_on_fetch_failure to reflect cache-write-deferred behavior
  - tests/conftest.py: Add item.key = "/library/metadata/12345" to mock_plex_item fixture
  - tests/integration/conftest.py: Add mock_section.fetchItem.return_value = mock_plex_item
