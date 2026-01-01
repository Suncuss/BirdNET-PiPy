"""Tests for the eBird taxonomy download script."""

import csv
import json
import os
import tempfile
import pytest
import sys

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

from download_ebird_taxonomy import parse_ebird_csv, save_json


class TestParseEbirdCsv:
    """Test parsing of eBird taxonomy CSV format."""

    @pytest.fixture
    def sample_csv_file(self):
        """Create a sample eBird taxonomy CSV file for testing."""
        rows = [
            # Header row matching actual eBird CSV format
            {
                'sort v2024': '1',
                'species_code': 'ostric2',
                'category': 'species',
                'English name': 'Common Ostrich',
                'scientific name': 'Struthio camelus',
                'range': 'Africa',
                'order': 'Struthioniformes',
                'family': 'Struthionidae',
            },
            {
                'sort v2024': '2',
                'species_code': 'amerob',
                'category': 'species',
                'English name': 'American Robin',
                'scientific name': 'Turdus migratorius',
                'range': 'North America',
                'order': 'Passeriformes',
                'family': 'Turdidae',
            },
            {
                'sort v2024': '3',
                'species_code': 'norcar',
                'category': 'species',
                'English name': 'Northern Cardinal',
                'scientific name': 'Cardinalis cardinalis',
                'range': 'North America',
                'order': 'Passeriformes',
                'family': 'Cardinalidae',
            },
            # Subspecies - should be skipped
            {
                'sort v2024': '4',
                'species_code': 'amerob1',
                'category': 'subspecies',
                'English name': 'American Robin (Eastern)',
                'scientific name': 'Turdus migratorius migratorius',
                'range': 'Eastern North America',
                'order': 'Passeriformes',
                'family': 'Turdidae',
            },
            # Group - should be skipped
            {
                'sort v2024': '5',
                'species_code': 'y00478',
                'category': 'issf',
                'English name': 'American Robin (migratorius Group)',
                'scientific name': 'Turdus migratorius [migratorius Group]',
                'range': 'North America',
                'order': 'Passeriformes',
                'family': 'Turdidae',
            },
        ]

        fd, path = tempfile.mkstemp(suffix='.csv')
        with os.fdopen(fd, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['sort v2024', 'species_code', 'category', 'English name',
                          'scientific name', 'range', 'order', 'family']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

        yield path
        os.unlink(path)

    def test_parse_ebird_csv_species_only(self, sample_csv_file):
        """Test that only species (not subspecies or groups) are included."""
        mapping = parse_ebird_csv(sample_csv_file)

        assert len(mapping) == 3
        assert 'Struthio camelus' in mapping
        assert 'Turdus migratorius' in mapping
        assert 'Cardinalis cardinalis' in mapping
        # Subspecies should not be included
        assert 'Turdus migratorius migratorius' not in mapping

    def test_parse_ebird_csv_correct_codes(self, sample_csv_file):
        """Test that species codes are correctly extracted."""
        mapping = parse_ebird_csv(sample_csv_file)

        assert mapping['Struthio camelus'] == 'ostric2'
        assert mapping['Turdus migratorius'] == 'amerob'
        assert mapping['Cardinalis cardinalis'] == 'norcar'

    def test_parse_empty_csv(self):
        """Test parsing an empty CSV file (header only)."""
        fd, path = tempfile.mkstemp(suffix='.csv')
        with os.fdopen(fd, 'w', newline='', encoding='utf-8') as f:
            f.write('sort v2024,species_code,category,English name,scientific name\n')

        try:
            mapping = parse_ebird_csv(path)
            assert mapping == {}
        finally:
            os.unlink(path)

    def test_parse_csv_with_missing_fields(self):
        """Test parsing CSV with missing scientific name or species code."""
        fd, path = tempfile.mkstemp(suffix='.csv')
        with os.fdopen(fd, 'w', newline='', encoding='utf-8') as f:
            f.write('sort v2024,species_code,category,English name,scientific name\n')
            f.write('1,,species,Test Bird,\n')  # Missing both code and name
            f.write('2,testcd,species,Test Bird 2,Testus birdus\n')  # Valid

        try:
            mapping = parse_ebird_csv(path)
            assert len(mapping) == 1
            assert mapping['Testus birdus'] == 'testcd'
        finally:
            os.unlink(path)


class TestSaveJson:
    """Test JSON output generation."""

    def test_save_json_creates_file(self):
        """Test that save_json creates the output file."""
        mapping = {'Turdus migratorius': 'amerob'}

        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.unlink(path)  # Remove so save_json creates it

        from pathlib import Path
        save_json(mapping, Path(path))

        assert os.path.exists(path)
        os.unlink(path)

    def test_save_json_valid_json(self):
        """Test that save_json produces valid JSON."""
        mapping = {
            'Turdus migratorius': 'amerob',
            'Cardinalis cardinalis': 'norcar',
        }

        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)

        from pathlib import Path
        save_json(mapping, Path(path))

        with open(path, 'r', encoding='utf-8') as f:
            loaded = json.load(f)

        assert loaded == mapping
        os.unlink(path)

    def test_save_json_creates_parent_dirs(self):
        """Test that save_json creates parent directories if needed."""
        mapping = {'Turdus migratorius': 'amerob'}

        with tempfile.TemporaryDirectory() as tmpdir:
            from pathlib import Path
            output_path = Path(tmpdir) / 'subdir' / 'nested' / 'ebird_codes.json'

            save_json(mapping, output_path)

            assert output_path.exists()
            with open(output_path, 'r') as f:
                loaded = json.load(f)
            assert loaded == mapping

    def test_save_json_unicode_support(self):
        """Test that save_json handles unicode characters correctly."""
        # Some bird names have accented characters
        mapping = {
            'Turdus philomelos': 'songthr1',  # Song Thrush
            'Erithacus rubecula': 'eurrob1',  # European Robin
        }

        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)

        from pathlib import Path
        save_json(mapping, Path(path))

        with open(path, 'r', encoding='utf-8') as f:
            loaded = json.load(f)

        assert loaded == mapping
        os.unlink(path)
