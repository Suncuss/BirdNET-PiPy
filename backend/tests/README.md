# BirdNET-PiPy Test Suite

This directory contains all tests for the BirdNET-PiPy backend, organized by functionality.

## Test Structure

```
tests/
├── database/          # Database layer tests (87% coverage)
├── api/              # API endpoint tests
├── integration/      # Full system integration tests
├── unit/            # Individual function unit tests
├── performance/     # Performance benchmarks
├── fixtures/        # Shared test data and configuration
└── legacy_tests/    # Old tests kept for reference
```

## Running Tests

### Using the test script (recommended):

```bash
# Run all tests
./run-tests.sh

# Run specific test categories
./run-tests.sh database    # Database tests only
./run-tests.sh api        # API tests only
./run-tests.sh coverage   # All tests with coverage report

# Pass additional pytest arguments
./run-tests.sh database -k "test_insert"  # Run specific test
./run-tests.sh -x                         # Stop on first failure
```

### Using Docker (ensures same environment as production):

```bash
# Run tests in Docker container
./docker-test.sh

# Run specific category in Docker
./docker-test.sh database
./docker-test.sh coverage
```

### Direct pytest commands:

```bash
# Run all tests
python -m pytest

# Run specific directory
python -m pytest tests/database/ -v

# Run with coverage
python -m pytest --cov=core --cov-report=term-missing
```


## Writing Tests

Each test category has its own `conftest.py` with relevant fixtures:

- **Database tests**: Use `test_db_manager` fixture for temporary database
- **API tests**: Use `api_client` and `mock_db_manager` fixtures
- **Shared fixtures**: Available in main `conftest.py`

### Example Database Test:
```python
def test_bird_detection(test_db_manager, sample_detection):
    """Test inserting and retrieving bird detection."""
    row_id = test_db_manager.insert_detection(sample_detection)
    assert isinstance(row_id, int)
    
    results = test_db_manager.get_latest_detections(1)
    assert len(results) == 1
    assert results[0]['common_name'] == sample_detection['common_name']
```

### Example API Test:
```python
def test_get_species(api_client, mock_db_manager):
    """Test species endpoint."""
    # Arrange: Set up mock
    mock_db_manager.get_all_unique_species.return_value = [
        {'common_name': 'Blue Jay', 'scientific_name': 'Cyanocitta cristata'}
    ]
    
    # Act: Make request
    response = api_client.get('/api/species')
    
    # Assert: Verify response
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data) == 1
    assert data[0]['common_name'] == 'Blue Jay'
```

## Key Testing Concepts

### Fixtures
Provide reusable test data and setup:
- `test_db_manager` - Temporary database for testing
- `api_client` - Flask test client
- `mock_db_manager` - Mocked database for API tests
- `sample_detection` - Standard bird detection data

### Mocking
Isolate components by mocking dependencies:
```python
mock_db_manager.get_species_count.return_value = [
    {'common_name': 'Robin', 'count': 5}
]
```

### Test Organization
- Group related tests in classes
- Use descriptive test names
- Follow Arrange-Act-Assert pattern
- Test both success and error cases

## Coverage Goals

- Database: ✅ 87% (achieved)
- API: 🚧 In progress
- Overall target: 80%+

## Common Issues

1. **Import errors**: Run tests from `backend/` directory
2. **Database tests failing**: Check temporary file permissions
3. **Mock not working**: Ensure patching correct import path

## Next Steps

Now that tests are organized, the workflow is:

1. Run tests before making changes: `./run-tests.sh`
2. Make your changes
3. Run tests to ensure nothing broke
4. Add tests for new functionality
5. Run coverage to check: `./run-tests.sh coverage`

Happy testing! 🧪