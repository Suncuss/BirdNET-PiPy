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
    # Ensure PROJECT_DIR is set
    export PROJECT_DIR="${PROJECT_DIR:-/home/testuser/BirdNET-PiPy}"

    # Set SUDO_USER for install.sh
    export SUDO_USER="testuser"

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
    # Run as testuser (not root)
    run sudo -u testuser bash "$PROJECT_DIR/install.sh" 2>&1
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

@test "unit: --update requires local install" {
    # Create a temporary directory without .git
    local temp_dir=$(mktemp -d)
    cp "$PROJECT_DIR/install.sh" "$temp_dir/"

    run sudo bash "$temp_dir/install.sh" --update
    [ "$status" -eq 1 ]
    [[ "$output" == *"requires running from existing installation"* ]]

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
