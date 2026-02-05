# Install Script Tests

This directory contains tests for `install.sh` using Docker-in-Docker (DinD) to simulate a fresh Debian installation.

## How It Works

### Overview

The test system creates an isolated environment that mimics a fresh Raspberry Pi:

```
┌─────────────────────────────────────────────────────────────────┐
│  Host Machine (your dev machine)                                │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Test Container (Debian + systemd)                        │  │
│  │                                                           │  │
│  │  • systemd as PID 1 (like real Raspberry Pi)              │  │
│  │  • Docker daemon running inside                           │  │
│  │  • testuser account (simulates pi user)                   │  │
│  │  • BATS test framework                                    │  │
│  │                                                           │  │
│  │  /home/testuser/BirdNET-PiPy/  ← copy of your project     │  │
│  │  /tests/                        ← test files (read-only)  │  │
│  │                                                           │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  Nested Docker (Docker-in-Docker)                   │  │  │
│  │  │                                                     │  │  │
│  │  │  • birdnet-pipy-api                                 │  │  │
│  │  │  • birdnet-pipy-main                                │  │  │
│  │  │  • birdnet-pipy-model-server                        │  │  │
│  │  │  • etc.                                             │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Test Flow

1. **Build Test Image** (`Dockerfile.test`)
   - Starts from Debian Bookworm (same as Raspberry Pi OS)
   - Installs systemd, Docker, BATS test framework
   - Creates `testuser` with sudo access

2. **Start Container with systemd**
   - Container runs in privileged mode for Docker-in-Docker
   - systemd initializes as PID 1 (realistic init system)
   - Docker daemon starts inside the container

3. **Setup Test Environment**
   - Your project is mounted read-only at `/project`
   - Copied to `/home/testuser/BirdNET-PiPy` (writable)
   - This protects your local code from any changes

4. **Run BATS Tests**
   - Unit tests: Quick checks (help flags, file existence)
   - Integration tests: Run full `install.sh`, verify results

5. **Cleanup**
   - Container is stopped and removed (unless `--keep`)

### Why Docker-in-Docker?

The `install.sh` script:
- Installs Docker and Docker Compose
- Builds application images
- Creates systemd services

Testing this requires a real Docker daemon and systemd, which can't be mocked. DinD provides a complete, isolated Linux environment.

### Key Design Decisions

| Decision | Reason |
|----------|--------|
| Debian base image | Matches Raspberry Pi OS |
| systemd as init | Tests service creation/enabling |
| Privileged mode | Required for nested Docker |
| Read-only project mount | Protects local codebase |
| Copy to writable location | install.sh can modify files |
| VFS storage driver | Works reliably in nested Docker |

### Limitations

- **No BuildKit cache**: Nested overlay filesystems don't support cache mounts
- **No update mode tests**: Feature branch doesn't exist on public remote until merged
- **Slower than mocks**: Full installation takes ~5-10 minutes

## Quick Start

```bash
# Run all tests
./docker-test-install.sh

# Run only unit tests (fast, no installation)
./docker-test-install.sh --unit-only

# Keep container for debugging
./docker-test-install.sh --keep
```

## Test Architecture

### Docker-in-Docker (DinD)

The tests run in a Debian container with:
- **systemd** as init (PID 1) for realistic service management
- **Docker daemon** inside the container for building images
- **Privileged mode** for Docker-in-Docker support

This ensures tests run in an environment matching a real Raspberry Pi.

### Test Categories

Tests are named with prefixes:
- `unit:` - Fast tests that don't require installation (argument parsing, file checks)
- `integration:` - Full installation tests (Docker setup, service creation, image builds)

## Files

| File | Description |
|------|-------------|
| `docker-test-install.sh` | Test runner script |
| `Dockerfile.test` | Debian + systemd + BATS test image |
| `test_install.bats` | Main BATS test file |
| `test_helpers.bash` | Shared helper functions |

## What Gets Tested

### Unit Tests (8 tests)
- `--help` flag works and exits with code 0
- Unknown options are rejected
- Non-root execution is detected
- Required repository files exist (docker-compose.yml, build.sh, etc.)
- build.sh is executable
- `--update` requires local install

### Integration Tests (15 tests, 3 skipped in DinD)
- Full installation completes successfully
- Git and Docker are installed
- Docker Compose plugin is available
- User is added to docker group
- systemd service file is created
- systemd service is enabled
- Service file contains correct User and WorkingDirectory
- sudoers configuration is valid (passes `visudo -c`)
- sudoers file allows pulseaudio commands
- PulseAudio config is installed
- Data directories are created (data/, data/flags/)
- Runtime script is executable

### Skipped in DinD Environment
- **Docker images are built** - BuildKit cache mounts don't work with nested overlay filesystems
- **Update mode tests** - Requires the feature branch to exist on the public remote

These features are tested manually or on real hardware after merging to main.

## Debugging Failed Tests

Keep the container running for debugging:

```bash
./docker-test-install.sh --keep
```

Then access the container:

```bash
# Get a shell
docker exec -it birdnet-install-test-<PID> bash

# Check systemd services
docker exec -it birdnet-install-test-<PID> systemctl status birdnet-pipy

# View install log
docker exec -it birdnet-install-test-<PID> cat /var/log/birdnet-pipy-install.log

# Clean up when done
docker stop birdnet-install-test-<PID>
docker rm birdnet-install-test-<PID>
```

## Writing New Tests

### Helper Functions

The `test_helpers.bash` file provides:

```bash
# File assertions
assert_file_exists <path>
assert_file_contains <path> <string>
assert_file_executable <path>
assert_directory_exists <path>

# Command assertions
assert_command_exists <command>

# Service assertions
assert_service_exists <service>
assert_service_enabled <service>

# User assertions
assert_user_in_group <user> <group>

# Sudoers validation
assert_sudoers_valid <file>

# Docker assertions
assert_docker_images_exist <prefix>
```

### Test Template

```bash
@test "unit: description of test" {
    # Unit tests should be fast and not require installation
    run some_command
    [ "$status" -eq 0 ]
    [[ "$output" == *"expected"* ]]
}

@test "integration: description of test" {
    # Integration tests run after full installation
    assert_file_exists "/some/path"
}
```

## CI/CD Integration

Add to your CI pipeline:

```yaml
test-install:
  script:
    - cd tests/install
    - ./docker-test-install.sh
```

## Requirements

- Docker with privileged container support
- Linux host (for cgroup mounting)
- ~2GB disk space for test image

## Troubleshooting

### "Cannot connect to Docker daemon"

The inner Docker daemon may not have started. Check:

```bash
docker exec <container> systemctl status docker
docker exec <container> journalctl -u docker
```

### "Timeout waiting for systemd"

The container may be missing cgroup access. Ensure:
- `--privileged` flag is used
- `--cgroupns=host` is set
- `/sys/fs/cgroup` is mounted

### Tests hang during image build

Building Docker images in DinD can be slow. The full integration test suite may take 10-15 minutes on first run.
