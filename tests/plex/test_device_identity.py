"""
Unit tests for plex/device_identity.py.

Tests the device identity module including:
- Device ID generation and persistence
- Loading existing device ID
- Handling corrupt JSON files
- plexapi module configuration
"""

import json
import os
import pytest
import plexapi
import plexapi.config

from plex.device_identity import load_or_create_device_id, configure_plex_device_identity


# =============================================================================
# Fixture for plexapi state management
# =============================================================================

@pytest.fixture
def restore_plexapi():
    """
    Fixture that saves and restores plexapi module state.

    This ensures tests don't affect each other by modifying global plexapi variables.
    """
    # Save original values
    original_identifier = getattr(plexapi, 'X_PLEX_IDENTIFIER', None)
    original_product = getattr(plexapi, 'X_PLEX_PRODUCT', None)
    original_device_name = getattr(plexapi, 'X_PLEX_DEVICE_NAME', None)
    original_headers = getattr(plexapi, 'BASE_HEADERS', {}).copy()

    yield

    # Restore original values
    plexapi.X_PLEX_IDENTIFIER = original_identifier
    plexapi.X_PLEX_PRODUCT = original_product
    plexapi.X_PLEX_DEVICE_NAME = original_device_name
    plexapi.BASE_HEADERS = original_headers


# =============================================================================
# load_or_create_device_id Tests
# =============================================================================

class TestLoadOrCreateDeviceId:
    """Tests for load_or_create_device_id function."""

    def test_creates_new_file_when_none_exists(self, tmp_path):
        """Creates device_id.json when no file exists."""
        data_dir = str(tmp_path)
        id_file = tmp_path / 'device_id.json'

        # File should not exist initially
        assert not id_file.exists()

        device_id = load_or_create_device_id(data_dir)

        # File should now exist
        assert id_file.exists()

        # Should be a valid UUID format
        assert len(device_id) == 36  # UUID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        assert device_id.count('-') == 4

    def test_returns_same_id_on_subsequent_calls(self, tmp_path):
        """Returns the same device ID on subsequent calls."""
        data_dir = str(tmp_path)

        # First call creates the ID
        first_id = load_or_create_device_id(data_dir)

        # Second call should return the same ID
        second_id = load_or_create_device_id(data_dir)

        assert first_id == second_id

    def test_loads_existing_device_id_from_file(self, tmp_path):
        """Loads existing device ID from pre-existing file."""
        data_dir = str(tmp_path)
        id_file = tmp_path / 'device_id.json'

        # Pre-create the file with a known ID
        known_id = 'pre-existing-device-id-12345'
        id_file.write_text(json.dumps({'device_id': known_id}))

        device_id = load_or_create_device_id(data_dir)

        assert device_id == known_id

    def test_handles_corrupt_json_gracefully(self, tmp_path):
        """Regenerates device ID when JSON is corrupt."""
        data_dir = str(tmp_path)
        id_file = tmp_path / 'device_id.json'

        # Create corrupt JSON file
        id_file.write_text('{ not valid json }}}')

        device_id = load_or_create_device_id(data_dir)

        # Should generate a new valid UUID
        assert len(device_id) == 36
        assert device_id.count('-') == 4

        # File should be overwritten with valid JSON
        data = json.loads(id_file.read_text())
        assert data['device_id'] == device_id

    def test_handles_missing_device_id_key(self, tmp_path):
        """Regenerates device ID when JSON lacks device_id key."""
        data_dir = str(tmp_path)
        id_file = tmp_path / 'device_id.json'

        # Create JSON without device_id key
        id_file.write_text(json.dumps({'other_key': 'value'}))

        device_id = load_or_create_device_id(data_dir)

        # Should generate a new valid UUID
        assert len(device_id) == 36

    def test_handles_empty_device_id_value(self, tmp_path):
        """Regenerates device ID when value is empty string."""
        data_dir = str(tmp_path)
        id_file = tmp_path / 'device_id.json'

        # Create JSON with empty device_id
        id_file.write_text(json.dumps({'device_id': ''}))

        device_id = load_or_create_device_id(data_dir)

        # Should generate a new valid UUID (empty string is falsy)
        assert len(device_id) == 36

    def test_creates_data_dir_if_not_exists(self, tmp_path):
        """Creates data directory if it doesn't exist."""
        # Use a nested path that doesn't exist
        data_dir = str(tmp_path / 'nested' / 'data' / 'path')

        assert not os.path.exists(data_dir)

        device_id = load_or_create_device_id(data_dir)

        # Directory should now exist
        assert os.path.exists(data_dir)
        assert os.path.isfile(os.path.join(data_dir, 'device_id.json'))

    def test_persists_device_id_in_json_format(self, tmp_path):
        """Device ID is stored in proper JSON format."""
        data_dir = str(tmp_path)
        id_file = tmp_path / 'device_id.json'

        device_id = load_or_create_device_id(data_dir)

        # Read and parse the file
        data = json.loads(id_file.read_text())

        assert 'device_id' in data
        assert data['device_id'] == device_id

    def test_generates_unique_ids(self, tmp_path):
        """Each new generation creates a unique ID."""
        # Create two separate directories
        dir1 = str(tmp_path / 'dir1')
        dir2 = str(tmp_path / 'dir2')

        id1 = load_or_create_device_id(dir1)
        id2 = load_or_create_device_id(dir2)

        # IDs should be different (UUID collision is astronomically unlikely)
        assert id1 != id2


# =============================================================================
# configure_plex_device_identity Tests
# =============================================================================

class TestConfigurePlexDeviceIdentity:
    """Tests for configure_plex_device_identity function."""

    def test_sets_x_plex_identifier(self, tmp_path, restore_plexapi):
        """Sets plexapi.X_PLEX_IDENTIFIER to the device ID."""
        data_dir = str(tmp_path)

        device_id = configure_plex_device_identity(data_dir)

        assert plexapi.X_PLEX_IDENTIFIER == device_id

    def test_sets_x_plex_product(self, tmp_path, restore_plexapi):
        """Sets plexapi.X_PLEX_PRODUCT to 'PlexSync'."""
        data_dir = str(tmp_path)

        configure_plex_device_identity(data_dir)

        assert plexapi.X_PLEX_PRODUCT == 'PlexSync'

    def test_sets_x_plex_device_name(self, tmp_path, restore_plexapi):
        """Sets plexapi.X_PLEX_DEVICE_NAME to 'PlexSync Plugin'."""
        data_dir = str(tmp_path)

        configure_plex_device_identity(data_dir)

        assert plexapi.X_PLEX_DEVICE_NAME == 'PlexSync Plugin'

    def test_rebuilds_base_headers(self, tmp_path, restore_plexapi):
        """Rebuilds BASE_HEADERS to include the new identifier."""
        data_dir = str(tmp_path)

        device_id = configure_plex_device_identity(data_dir)

        # BASE_HEADERS should contain the X-Plex-Client-Identifier
        assert 'X-Plex-Client-Identifier' in plexapi.BASE_HEADERS
        assert plexapi.BASE_HEADERS['X-Plex-Client-Identifier'] == device_id

    def test_base_headers_includes_product_name(self, tmp_path, restore_plexapi):
        """BASE_HEADERS includes X-Plex-Product."""
        data_dir = str(tmp_path)

        configure_plex_device_identity(data_dir)

        assert 'X-Plex-Product' in plexapi.BASE_HEADERS
        assert plexapi.BASE_HEADERS['X-Plex-Product'] == 'PlexSync'

    def test_base_headers_includes_device_name(self, tmp_path, restore_plexapi):
        """BASE_HEADERS includes X-Plex-Device-Name."""
        data_dir = str(tmp_path)

        configure_plex_device_identity(data_dir)

        assert 'X-Plex-Device-Name' in plexapi.BASE_HEADERS
        assert plexapi.BASE_HEADERS['X-Plex-Device-Name'] == 'PlexSync Plugin'

    def test_returns_device_id(self, tmp_path, restore_plexapi):
        """Returns the device ID being used."""
        data_dir = str(tmp_path)

        device_id = configure_plex_device_identity(data_dir)

        # Should return a valid UUID
        assert len(device_id) == 36
        assert device_id.count('-') == 4

    def test_uses_existing_device_id(self, tmp_path, restore_plexapi):
        """Uses existing device ID from file."""
        data_dir = str(tmp_path)
        id_file = tmp_path / 'device_id.json'

        # Pre-create the file with a known ID
        known_id = 'known-device-id-for-test-12345'
        id_file.write_text(json.dumps({'device_id': known_id}))

        device_id = configure_plex_device_identity(data_dir)

        assert device_id == known_id
        assert plexapi.X_PLEX_IDENTIFIER == known_id

    def test_persistence_across_calls(self, tmp_path, restore_plexapi):
        """Device ID persists correctly across multiple configure calls."""
        data_dir = str(tmp_path)

        # First configuration
        device_id_1 = configure_plex_device_identity(data_dir)

        # Second configuration (simulating restart)
        device_id_2 = configure_plex_device_identity(data_dir)

        # Should be the same ID
        assert device_id_1 == device_id_2
        assert plexapi.X_PLEX_IDENTIFIER == device_id_1

    def test_idempotent_calls(self, tmp_path, restore_plexapi):
        """Multiple calls with same data_dir produce consistent state."""
        data_dir = str(tmp_path)

        # Call multiple times
        id1 = configure_plex_device_identity(data_dir)
        id2 = configure_plex_device_identity(data_dir)
        id3 = configure_plex_device_identity(data_dir)

        # All should be the same
        assert id1 == id2 == id3

        # Final plexapi state should be consistent
        assert plexapi.X_PLEX_IDENTIFIER == id1
        assert plexapi.X_PLEX_PRODUCT == 'PlexSync'
        assert plexapi.X_PLEX_DEVICE_NAME == 'PlexSync Plugin'
