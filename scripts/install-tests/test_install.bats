#!/usr/bin/env bats
# test_install.bats - BATS tests for install.sh
#
# Test naming convention:
#   - "unit: ..." for fast tests that don't require full installation
#   - "integration: ..." for tests that run the full install flow
#
# Run with: bats test_install.bats
# Run unit tests only: bats --filter 'unit:' test_install.bats

# Load test helpers
load 'test_helpers'

# ============================================================================
# Setup and Teardown
# ============================================================================

setup() {
    # Auto-detect PROJECT_DIR from test file location (scripts/install-tests/*.bats)
    export PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)}"

    # Use real SUDO_USER from sudo(8), fall back to current user
    export SUDO_USER="${SUDO_USER:-$(whoami)}"

    # Fix git safe.directory for root user (tests run as root via sudo)
    git config --global --add safe.directory "$PROJECT_DIR" 2>/dev/null || true
}

# ============================================================================
# Unit Tests (fast, no installation required)
# ============================================================================

@test "unit: install.sh exists and is executable" {
    assert_file_exists "$PROJECT_DIR/install.sh"
    assert_file_executable "$PROJECT_DIR/install.sh"
}

@test "unit: --help flag shows usage" {
    run bash "$PROJECT_DIR/install.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" == *"Usage:"* ]]
    [[ "$output" == *"--update"* ]]
    [[ "$output" == *"--branch"* ]]
    [[ "$output" == *"--no-reboot"* ]]
}

@test "unit: --help exits with code 0" {
    run bash "$PROJECT_DIR/install.sh" --help
    [ "$status" -eq 0 ]
}

@test "unit: unknown option exits with error" {
    run bash "$PROJECT_DIR/install.sh" --unknown-option
    [ "$status" -eq 1 ]
    [[ "$output" == *"Unknown option"* ]]
}

@test "unit: detects non-root execution" {
    # Run as the invoking (non-root) user
    run sudo -u "$SUDO_USER" bash "$PROJECT_DIR/install.sh" 2>&1
    [ "$status" -eq 1 ]
    [[ "$output" == *"must be run as root"* ]]
}

@test "unit: required files exist in repository" {
    assert_file_exists "$PROJECT_DIR/docker-compose.yml"
    assert_file_exists "$PROJECT_DIR/build.sh"
    assert_file_exists "$PROJECT_DIR/deployment/birdnet-service.sh"
    assert_file_exists "$PROJECT_DIR/deployment/audio/pulseaudio/system.pa"
    assert_file_exists "$PROJECT_DIR/deployment/audio/pulseaudio/daemon.conf"
}

@test "unit: build.sh is executable" {
    assert_file_executable "$PROJECT_DIR/build.sh"
}

@test "unit: build.sh --services requires a value" {
    run bash "$PROJECT_DIR/build.sh" --services
    [ "$status" -eq 1 ]
    [[ "$output" == *"--services requires a comma-separated value"* ]]
}

@test "unit: build.sh --services rejects unknown service" {
    run bash "$PROJECT_DIR/build.sh" --services "frontend,not-a-service"
    [ "$status" -eq 1 ]
    [[ "$output" == *"Unknown service in --services: not-a-service"* ]]
}

@test "unit: build.sh --services rejects api (shares model-server image)" {
    run bash "$PROJECT_DIR/build.sh" --services "api"
    [ "$status" -eq 1 ]
    [[ "$output" == *"Unknown service in --services: api"* ]]
}

@test "unit: build.sh --services rejects main (shares model-server image)" {
    run bash "$PROJECT_DIR/build.sh" --services "main"
    [ "$status" -eq 1 ]
    [[ "$output" == *"Unknown service in --services: main"* ]]
}

@test "unit: only model-server has build directive for backend image" {
    # Regression test: api and main must NOT have build: directives.
    # When multiple services share the same image tag and all define build:,
    # Docker BuildKit races to tag the same image in parallel, causing
    # "image already exists" failures. Only model-server should build it.
    local compose="$PROJECT_DIR/docker-compose.yml"
    assert_file_exists "$compose"

    # model-server MUST have a build: directive
    run bash -c "docker compose -f '$compose' config --format json | python3 -c \"
import sys, json
cfg = json.load(sys.stdin)
ms = cfg['services'].get('model-server', {})
assert 'build' in ms, 'model-server must have build: directive'
print('model-server: build directive present')
\""
    echo "output: $output"
    [ "$status" -eq 0 ]

    # api and main must NOT have build: directives
    for svc in api main; do
        run bash -c "docker compose -f '$compose' config --format json | python3 -c \"
import sys, json
cfg = json.load(sys.stdin)
svc_cfg = cfg['services'].get('$svc', {})
assert 'build' not in svc_cfg, '$svc must not have build: directive'
print('$svc: no build directive (correct)')
\""
        echo "$svc output: $output"
        [ "$status" -eq 0 ]
    done
}

@test "unit: backend services share the same image tag" {
    # All three backend services must reference the same image
    local compose="$PROJECT_DIR/docker-compose.yml"
    run bash -c "docker compose -f '$compose' config --format json | python3 -c \"
import sys, json
cfg = json.load(sys.stdin)
images = {s: cfg['services'][s]['image'] for s in ('model-server', 'api', 'main')}
unique = set(images.values())
assert len(unique) == 1, f'backend services have different images: {images}'
print(f'all backend services use: {unique.pop()}')
\""
    echo "output: $output"
    [ "$status" -eq 0 ]
}

@test "unit: build.sh --version-only generates version.json" {
    rm -f "$PROJECT_DIR/data/version.json"
    run bash -c "cd \"$PROJECT_DIR\" && ./build.sh --version-only"
    [ "$status" -eq 0 ]
    assert_file_exists "$PROJECT_DIR/data/version.json"
    assert_file_contains "$PROJECT_DIR/data/version.json" "\"commit\""
}

@test "unit: --update requires local install" {
    # Create a temporary directory without .git
    local temp_dir=$(mktemp -d)
    cp "$PROJECT_DIR/install.sh" "$temp_dir/"

    run sudo bash "$temp_dir/install.sh" --update
    [ "$status" -eq 1 ]
    [[ "$output" == *"requires running from existing installation"* ]]

    rm -rf "$temp_dir"
}

@test "unit: set_env_var replaces single-key .env value without duplicates" {
    local temp_dir
    temp_dir=$(mktemp -d)
    printf 'BIRDNET_CHANNEL=main\n' > "$temp_dir/.env"

    run run_install_function "$temp_dir" set_env_var BIRDNET_CHANNEL staging
    [ "$status" -eq 0 ]
    assert_file_contains "$temp_dir/.env" "BIRDNET_CHANNEL=staging"
    assert_file_not_contains "$temp_dir/.env" "BIRDNET_CHANNEL=main"

    local count
    count=$(grep -c '^BIRDNET_CHANNEL=' "$temp_dir/.env")
    [ "$count" -eq 1 ]

    rm -rf "$temp_dir"
}

@test "unit: set_env_var preserves unrelated .env settings while updating key" {
    local temp_dir
    temp_dir=$(mktemp -d)
    cat > "$temp_dir/.env" << 'EOF'
ICECAST_PASSWORD=secret
STREAM_BITRATE=192k
BIRDNET_CHANNEL=main
EOF

    run run_install_function "$temp_dir" set_env_var BIRDNET_CHANNEL staging
    [ "$status" -eq 0 ]
    assert_file_contains "$temp_dir/.env" "ICECAST_PASSWORD=secret"
    assert_file_contains "$temp_dir/.env" "STREAM_BITRATE=192k"
    assert_file_contains "$temp_dir/.env" "BIRDNET_CHANNEL=staging"
    assert_file_not_contains "$temp_dir/.env" "BIRDNET_CHANNEL=main"

    local count
    count=$(grep -c '^BIRDNET_CHANNEL=' "$temp_dir/.env")
    [ "$count" -eq 1 ]

    rm -rf "$temp_dir"
}

# ============================================================================
# Integration Tests (full installation flow)
# ============================================================================

@test "integration: full installation completes successfully" {
    # Run installation with --no-reboot --skip-build
    # --skip-build skips Docker image build (which doesn't work in DinD due to overlay issues)
    # This tests all other installation steps: Docker setup, PulseAudio, systemd, sudoers, etc.
    # SUDO_USER must be set explicitly since we're running as root in the container
    run sudo SUDO_USER=testuser bash "$PROJECT_DIR/install.sh" --no-reboot --skip-build
    echo "Install output: $output"
    [ "$status" -eq 0 ]
}

@test "integration: git is installed" {
    # Depends on installation
    assert_command_exists git
}

@test "integration: Docker is installed" {
    assert_command_exists docker
    run docker --version
    [ "$status" -eq 0 ]
}

@test "integration: Docker Compose plugin is available" {
    run docker compose version
    [ "$status" -eq 0 ]
}

@test "integration: testuser is in docker group" {
    assert_user_in_group testuser docker
}

@test "integration: systemd service file exists" {
    assert_service_exists "birdnet-pipy"
}

@test "integration: systemd service is enabled" {
    assert_service_enabled "birdnet-pipy"
}

@test "integration: service file contains correct user" {
    assert_file_contains "/etc/systemd/system/birdnet-pipy.service" "User=testuser"
}

@test "integration: service file contains correct working directory" {
    assert_file_contains "/etc/systemd/system/birdnet-pipy.service" "WorkingDirectory=/home/testuser/BirdNET-PiPy"
}

@test "integration: sudoers file is valid" {
    assert_sudoers_valid "/etc/sudoers.d/birdnet-pipy"
}

@test "integration: sudoers file allows pulseaudio" {
    assert_file_contains "/etc/sudoers.d/birdnet-pipy" "pulseaudio"
}

@test "integration: PulseAudio config exists" {
    assert_file_exists "/etc/pulse/system.pa"
}

@test "integration: data directory exists" {
    assert_directory_exists "$PROJECT_DIR/data"
}

@test "integration: flags directory exists" {
    assert_directory_exists "$PROJECT_DIR/data/flags"
}

@test "integration: Docker images are built" {
    # Skip this test when using --skip-build (Docker image builds don't work in DinD)
    # The actual Docker builds are tested by backend/docker-test.sh on real hardware
    skip "Docker image builds are tested separately (skipped in DinD environment)"
}

@test "integration: runtime script is executable" {
    assert_file_executable "$PROJECT_DIR/deployment/birdnet-service.sh"
}

# ============================================================================
# Update Mode Tests
# ============================================================================

@test "integration: no-op update reapplies system configs" {
    # Set up local fake git remote (same commit as local - no-op scenario)
    setup_fake_origin

    # Corrupt config artifacts that --update should restore
    rm -f /etc/systemd/system/birdnet-pipy.service
    rm -f /etc/sudoers.d/birdnet-pipy

    # Run update (no code changes, should still refresh configs)
    run sudo SUDO_USER=testuser bash "$PROJECT_DIR/install.sh" --update --skip-build
    echo "Update output: $output"
    [ "$status" -eq 0 ]

    # Assert configs were restored
    assert_service_exists "birdnet-pipy"
    assert_file_contains "/etc/systemd/system/birdnet-pipy.service" "User=testuser"
    assert_sudoers_valid "/etc/sudoers.d/birdnet-pipy"
}

@test "integration: update with new commits fast-forwards and preserves data" {
    # Set up local fake git remote
    setup_fake_origin

    # Create test data that should survive the update
    echo "test-data" > "$PROJECT_DIR/data/test-preserve.txt"

    # Push a synthetic commit to make origin ahead of local
    push_synthetic_commit

    # Record current HEAD
    local old_head
    old_head=$(git -C "$PROJECT_DIR" rev-parse HEAD)

    # Run update (should fast-forward to new commit)
    run sudo SUDO_USER=testuser bash "$PROJECT_DIR/install.sh" --update --skip-build
    echo "Update output: $output"
    [ "$status" -eq 0 ]

    # Assert HEAD moved forward
    local new_head
    new_head=$(git -C "$PROJECT_DIR" rev-parse HEAD)
    [ "$old_head" != "$new_head" ]

    # Assert data was preserved (chown skips data/)
    assert_file_exists "$PROJECT_DIR/data/test-preserve.txt"
    assert_file_contains "$PROJECT_DIR/data/test-preserve.txt" "test-data"
}

@test "integration: update on non-release branch falls back to local build" {
    setup_fake_origin
    push_synthetic_commit "backend/core/test_update_marker.py" "TEST_MARKER = \"$(date +%s)\""

    run sudo SUDO_USER=testuser bash "$PROJECT_DIR/install.sh" --update --skip-build
    echo "Update output: $output"
    [ "$status" -eq 0 ]
    [[ "$output" == *"has no pre-built images, building locally"* ]]
}
