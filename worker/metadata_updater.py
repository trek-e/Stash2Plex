"""
Metadata update logic for Plex items.

Handles core text field edits, list field syncs (via field_sync),
image uploads, and edit validation. Extracted from SyncWorker
to separate metadata concerns from job orchestration.
"""

import os
import tempfile
import urllib.request
import urllib.error
from typing import Optional

from validation.limits import (
    MAX_TITLE_LENGTH, MAX_STUDIO_LENGTH, MAX_SUMMARY_LENGTH, MAX_TAGLINE_LENGTH,
)
from validation.sanitizers import sanitize_for_plex
from validation.errors import PartialSyncResult
from worker.field_sync import sync_field, PERFORMERS_SPEC, TAGS_SPEC, COLLECTION_SPEC
from shared.log import create_logger

log_trace, log_debug, log_info, log_warn, log_error = create_logger("Updater")


class MetadataUpdater:
    """Applies Stash metadata to Plex items."""

    def __init__(self, config):
        self.config = config

    def update(self, plex_item, data: dict) -> PartialSyncResult:
        """
        Update Plex item metadata from sync job data.

        Implements LOCKED user decision: When Stash provides None/empty for an
        optional field, the existing Plex value is CLEARED (not preserved).
        When a field key is NOT in the data dict, the existing value is preserved.

        Non-critical field failures (performers, tags, poster, background, collection)
        are logged as warnings but don't fail the overall sync.

        Returns:
            PartialSyncResult tracking which fields succeeded and which had warnings
        """
        _dbg = getattr(self.config, 'debug_logging', False)
        result = PartialSyncResult()

        if not getattr(self.config, 'sync_master', True):
            log_debug("Master sync toggle is OFF - skipping all field syncs")
            return result

        # Phase 1: Build and apply core text field edits (CRITICAL)
        edits = self._build_core_edits(plex_item, data)
        _needs_reload = False
        if edits:
            if _dbg:
                log_info(f"[DEBUG] Metadata edits: {edits}")
            else:
                log_debug(f"Updating fields: {list(edits.keys())}")
            plex_item.edit(**edits)
            _needs_reload = True
            mode = "preserved" if self.config.preserve_plex_edits else "overwrite"
            log_info(f"Updated metadata ({mode} mode): {plex_item.title}")
            result.add_success('metadata')
        else:
            if _dbg:
                fields_in_data = [k for k in ('title', 'studio', 'details', 'summary', 'tagline', 'date') if k in data]
                log_info(f"[DEBUG] No core edits for '{plex_item.title}' — "
                         f"data keys present: {fields_in_data}, "
                         f"plex title='{plex_item.title}', stash title='{data.get('title', '<missing>')}'")
            else:
                log_trace(f"No metadata fields to update for: {plex_item.title}")

        # Phase 2: Non-critical field syncs
        if getattr(self.config, 'sync_performers', True) and 'performers' in data:
            _needs_reload |= sync_field(
                PERFORMERS_SPEC, plex_item, data.get('performers'), result, _dbg)

        if getattr(self.config, 'sync_poster', True) and data.get('poster_url'):
            self._upload_image(
                plex_item, data['poster_url'], plex_item.uploadPoster, 'poster', result, _dbg)

        if getattr(self.config, 'sync_background', True) and data.get('background_url'):
            self._upload_image(
                plex_item, data['background_url'], plex_item.uploadArt, 'background', result, _dbg)

        if getattr(self.config, 'sync_tags', True) and 'tags' in data:
            max_tags = getattr(self.config, 'max_tags', None)
            _needs_reload |= sync_field(
                TAGS_SPEC, plex_item, data.get('tags'), result, _dbg,
                max_count_override=max_tags)

        if getattr(self.config, 'sync_collection', True) and data.get('studio'):
            _needs_reload |= sync_field(
                COLLECTION_SPEC, plex_item, [data['studio']], result, _dbg)

        # Single deferred reload after all edits
        if _needs_reload:
            try:
                plex_item.reload()
                if edits:
                    validation_issues = self._validate_edit_result(plex_item, edits)
                    if validation_issues:
                        log_debug(f"Edit validation issues (may be expected): {validation_issues}")
            except Exception as e:
                log_debug(f"Post-edit reload failed (edits already applied): {e}")

        if result.has_warnings:
            log_warn(f"Partial sync for {plex_item.title}: {result.warning_summary}")

        return result

    def _build_core_edits(self, plex_item, data: dict) -> dict:
        """Build dict of core text field edits.

        LOCKED DECISION: Missing optional fields clear existing Plex values.
        - If key exists AND value is None/empty -> CLEAR (set to '')
        - If key exists AND value is present -> sanitize and set
        - If key does NOT exist in data dict -> do nothing (preserve)
        """
        edits = {}

        # Title (always synced — no toggle)
        if 'title' in data:
            title_value = data.get('title')
            if title_value is None or title_value == '':
                log_debug("Stash title is empty — preserving existing Plex title")
            else:
                sanitized = sanitize_for_plex(title_value, max_length=MAX_TITLE_LENGTH)
                if not self.config.preserve_plex_edits or not plex_item.title:
                    if (plex_item.title or '') != sanitized:
                        edits['title.value'] = sanitized

        # Studio
        if getattr(self.config, 'sync_studio', True) and 'studio' in data:
            studio_value = data.get('studio')
            if studio_value is None or studio_value == '':
                if plex_item.studio:
                    edits['studio.value'] = ''
                    log_debug("Clearing studio (Stash value is empty)")
            else:
                sanitized = sanitize_for_plex(studio_value, max_length=MAX_STUDIO_LENGTH)
                if not self.config.preserve_plex_edits or not plex_item.studio:
                    if (plex_item.studio or '') != sanitized:
                        edits['studio.value'] = sanitized

        # Summary (Stash 'details' -> Plex 'summary')
        if getattr(self.config, 'sync_summary', True):
            has_summary_key = 'details' in data or 'summary' in data
            if has_summary_key:
                summary_value = data.get('details') or data.get('summary')
                if summary_value is None or summary_value == '':
                    if plex_item.summary:
                        edits['summary.value'] = ''
                        log_debug("Clearing summary (Stash value is empty)")
                else:
                    sanitized = sanitize_for_plex(summary_value, max_length=MAX_SUMMARY_LENGTH)
                    if not self.config.preserve_plex_edits or not plex_item.summary:
                        if (plex_item.summary or '') != sanitized:
                            edits['summary.value'] = sanitized

        # Tagline
        if getattr(self.config, 'sync_tagline', True) and 'tagline' in data:
            tagline_value = data.get('tagline')
            if tagline_value is None or tagline_value == '':
                if getattr(plex_item, 'tagline', None):
                    edits['tagline.value'] = ''
                    log_debug("Clearing tagline (Stash value is empty)")
            else:
                sanitized = sanitize_for_plex(tagline_value, max_length=MAX_TAGLINE_LENGTH)
                if not self.config.preserve_plex_edits or not getattr(plex_item, 'tagline', None):
                    if (getattr(plex_item, 'tagline', '') or '') != sanitized:
                        edits['tagline.value'] = sanitized

        # Date
        if getattr(self.config, 'sync_date', True) and 'date' in data:
            date_value = data.get('date')
            if date_value is None or date_value == '':
                if getattr(plex_item, 'originallyAvailableAt', None):
                    edits['originallyAvailableAt.value'] = ''
                    log_debug("Clearing date (Stash value is empty)")
            else:
                if not self.config.preserve_plex_edits or not getattr(plex_item, 'originallyAvailableAt', None):
                    current_date = getattr(plex_item, 'originallyAvailableAt', None)
                    current_date_str = current_date.strftime('%Y-%m-%d') if current_date else ''
                    if current_date_str != (date_value or ''):
                        edits['originallyAvailableAt.value'] = date_value

        return edits

    def _upload_image(self, plex_item, url: str, upload_fn, field_name: str, result, _dbg: bool):
        """Download image from Stash and upload to Plex."""
        try:
            if _dbg:
                log_info(f"[DEBUG] Fetching {field_name} image from Stash")
            image_data = self._fetch_stash_image(url)
            if image_data:
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
                    f.write(image_data)
                    temp_path = f.name
                try:
                    upload_fn(filepath=temp_path)
                    log_debug(f"Uploaded {field_name} ({len(image_data)} bytes)")
                    result.add_success(field_name)
                finally:
                    os.unlink(temp_path)
            else:
                result.add_warning(field_name, ValueError(f"No image data returned from Stash"))
        except Exception as e:
            log_warn(f" Failed to upload {field_name}: {e}")
            result.add_warning(field_name, e)

    def _fetch_stash_image(self, url: str) -> Optional[bytes]:
        """Fetch image from Stash URL."""
        try:
            req = urllib.request.Request(url)
            api_key = getattr(self.config, 'stash_api_key', None)
            if api_key:
                req.add_header('ApiKey', api_key)
            session_cookie = getattr(self.config, 'stash_session_cookie', None)
            if session_cookie:
                req.add_header('Cookie', session_cookie)
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read()
        except urllib.error.URLError as e:
            log_warn(f" Failed to fetch image from Stash: {e}")
            return None
        except Exception as e:
            log_warn(f" Image fetch error: {e}")
            return None

    def _validate_edit_result(self, plex_item, expected_edits: dict) -> list:
        """Validate that edit actually applied expected values."""
        issues = []
        field_mapping = {
            'title': 'title',
            'studio': 'studio',
            'summary': 'summary',
            'tagline': 'tagline',
            'originallyAvailableAt': 'originallyAvailableAt',
        }
        for field_key, expected_value in expected_edits.items():
            if '.locked' in field_key or not expected_value:
                continue
            field_name = field_key.replace('.value', '')
            attr_name = field_mapping.get(field_name)
            if not attr_name:
                continue
            actual_value = getattr(plex_item, attr_name, None)
            expected_str = str(expected_value) if expected_value else ''
            actual_str = str(actual_value) if actual_value else ''
            if expected_str and actual_str:
                if expected_str[:50] != actual_str[:50]:
                    issues.append(
                        f"{field_name}: sent '{expected_str[:20]}...', "
                        f"got '{actual_str[:20]}...'"
                    )
            elif expected_str and not actual_str:
                issues.append(f"{field_name}: sent value but field is empty")
        return issues
