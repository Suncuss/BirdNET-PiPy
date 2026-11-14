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
    [[ "$output" == *"--unattended"* ]]
    [[ "$output" == *"--user NAME"* ]]
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

@test "unit: direct root without --user is refused" {
    # No sudo means no SUDO_USER, so nothing says whose install this is
    run env -u SUDO_USER bash "$PROJECT_DIR/install.sh" --no-reboot
    [ "$status" -eq 1 ]
    [[ "$output" == *"not as direct root"* ]]
    [[ "$output" == *"--user NAME"* ]]
}

@test "unit: --user rejects a missing value, an unknown account and root" {
    run env -u SUDO_USER bash "$PROJECT_DIR/install.sh" --user
    [ "$status" -eq 1 ]
    [[ "$output" == *"--user requires an account name"* ]]

    run env -u SUDO_USER bash "$PROJECT_DIR/install.sh" --unattended --user no-such-user-xyz
    [ "$status" -eq 1 ]
    [[ "$output" == *"no account named 'no-such-user-xyz'"* ]]

    run env -u SUDO_USER bash "$PROJECT_DIR/install.sh" --unattended --user root
    [ "$status" -eq 1 ]
    [[ "$output" == *"not root"* ]]
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

@test "unit: build.sh stamps one build ID in .env, keeping its other keys and mode" {
    # The backend image no longer changes with the code, so this stamp (a
    # label in docker-compose.yml) is what makes `compose up -d` recreate the
    # backend after a build.
    local saved=""
    if [ -f "$PROJECT_DIR/.env" ]; then
        saved=$(mktemp)
        cp -p "$PROJECT_DIR/.env" "$saved"
    fi
    printf 'BIRDNET_CHANNEL=staging\nICECAST_PASSWORD=secret\nBIRDNET_BUILD_ID=old\n' > "$PROJECT_DIR/.env"
    chmod 640 "$PROJECT_DIR/.env"

    run bash -c "cd \"$PROJECT_DIR\" && ./build.sh --version-only && ./build.sh --version-only"
    local env_mode env_count env_body build_id
    env_mode=$(stat -c '%a' "$PROJECT_DIR/.env")
    env_count=$(grep -c '^BIRDNET_BUILD_ID=' "$PROJECT_DIR/.env")
    env_body=$(cat "$PROJECT_DIR/.env")
    build_id=$(grep '^BIRDNET_BUILD_ID=' "$PROJECT_DIR/.env" | cut -d= -f2)

    if [ -n "$saved" ]; then
        mv "$saved" "$PROJECT_DIR/.env"
    else
        rm -f "$PROJECT_DIR/.env"
    fi

    [ "$status" -eq 0 ]
    [ "$env_mode" = "640" ]
    [ "$env_count" -eq 1 ]
    [[ "$env_body" == *"BIRDNET_CHANNEL=staging"* ]]
    [[ "$env_body" == *"ICECAST_PASSWORD=secret"* ]]
    [[ "$env_body" != *"BIRDNET_BUILD_ID=old"* ]]
    # Same value as version.json's build_time, so the two can be matched up
    assert_file_contains "$PROJECT_DIR/data/version.json" "\"build_time\": \"$build_id\""
    [ -z "$(find "$PROJECT_DIR" -maxdepth 1 -name '.env.*')" ]
}

@test "unit: build.sh works from any cwd without leaving stray files" {
    rm -f "$PROJECT_DIR/data/version.json"
    local temp_dir
    temp_dir=$(mktemp -d)

    run bash -c "cd \"$temp_dir\" && \"$PROJECT_DIR/build.sh\" --version-only"
    [ "$status" -eq 0 ]
    # version.json lands in the repo, not in the caller's cwd
    assert_file_exists "$PROJECT_DIR/data/version.json"
    [ ! -e "$temp_dir/data" ]

    rm -rf "$temp_dir"
}

@test "unit: build.sh cleanup reports reclaimed space and falls back for older engines" {
    local temp_dir
    temp_dir=$(mktemp -d)
    local shim_log="$temp_dir/docker-calls.log"

    # Fake docker on PATH: build succeeds instantly; image prune emits the
    # legacy summary format; builder prune rejects --max-used-space (like a
    # pre-buildx-0.17 engine) but accepts --keep-storage and emits the modern
    # "Total:" format. Exercises both parse formats and the fallback chain
    # without touching the real engine.
    cat > "$temp_dir/docker" << 'SHIM'
#!/bin/bash
echo "docker $*" >> "$DOCKER_SHIM_LOG"
case "$1 $2" in
    "compose build")
        exit 0
        ;;
    "image prune")
        echo "Total reclaimed space: 123MB"
        exit 0
        ;;
    "builder prune")
        for arg in "$@"; do
            if [[ "$arg" == --max-used-space=* ]]; then
                echo "unknown flag: --max-used-space" >&2
                exit 125
            fi
        done
        printf 'Total:\t1.5GB\n'
        exit 0
        ;;
esac
exit 0
SHIM
    chmod +x "$temp_dir/docker"

    # Neutralize build.sh's low-memory swap setup: on a <1GB-RAM host this
    # suite's privileged DinD container shares the kernel, so an unshimmed
    # swapon here would register REAL host swap from inside the test.
    local tool
    for tool in fallocate mkswap swapon; do
        printf '#!/bin/bash\nexit 0\n' > "$temp_dir/$tool"
        chmod +x "$temp_dir/$tool"
    done

    run env PATH="$temp_dir:$PATH" DOCKER_SHIM_LOG="$shim_log" BUILD_CACHE_LIMIT=2GB \
        bash "$PROJECT_DIR/build.sh" --services icecast
    echo "output: $output"
    [ "$status" -eq 0 ]

    # Both engine output formats parse into real numbers (not a fallback 0B)
    [[ "$output" == *"reclaimed 123MB from dangling images"* ]]
    [[ "$output" == *"reclaimed 1.5GB from build cache (cap: 2GB)"* ]]

    # The cap flag was attempted first, then the fallback engaged
    assert_file_contains "$shim_log" "max-used-space=2GB"
    assert_file_contains "$shim_log" "keep-storage=2GB"

    rm -rf "$temp_dir"
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

@test "unit: validate_web_port accepts valid ports and rejects bad values" {
    local temp_dir
    temp_dir=$(mktemp -d)

    local port
    for port in 1 80 8080 65535; do
        run run_install_function "$temp_dir" validate_web_port "$port"
        [ "$status" -eq 0 ]
    done

    # Non-numeric, out of range, and the loopback ports the backend
    # services already publish (docker-compose.yml)
    for port in abc "" 0 65536 5001 5002 8888; do
        run run_install_function "$temp_dir" validate_web_port "$port"
        [ "$status" -ne 0 ]
    done

    rm -rf "$temp_dir"
}

@test "unit: persist_web_port records BIRDNET_WEB_PORT preserving other .env keys" {
    local temp_dir
    temp_dir=$(mktemp -d)
    printf 'BIRDNET_CHANNEL=main\n' > "$temp_dir/.env"

    run run_install_function "$temp_dir" persist_web_port 8080
    [ "$status" -eq 0 ]
    assert_file_contains "$temp_dir/.env" "BIRDNET_WEB_PORT=8080"
    assert_file_contains "$temp_dir/.env" "BIRDNET_CHANNEL=main"

    rm -rf "$temp_dir"
}

@test "unit: effective_web_port resolves flag, then .env, then default 80" {
    local temp_dir
    temp_dir=$(mktemp -d)

    # No flag, no .env entry -> default
    run run_install_function "$temp_dir" effective_web_port
    [ "$status" -eq 0 ]
    [ "$output" = "80" ]

    # .env entry wins over the default
    printf 'BIRDNET_WEB_PORT=8080\n' > "$temp_dir/.env"
    run run_install_function "$temp_dir" effective_web_port
    [ "$status" -eq 0 ]
    [ "$output" = "8080" ]

    # This run's --port (WEB_PORT) wins over .env
    run run_install_function "$temp_dir" eval 'WEB_PORT=9090; effective_web_port'
    [ "$status" -eq 0 ]
    [ "$output" = "9090" ]

    rm -rf "$temp_dir"
}

@test "unit: install.sh rejects an invalid --port before doing any work" {
    local temp_dir
    temp_dir=$(mktemp -d)
    cp "$PROJECT_DIR/install.sh" "$temp_dir/"

    run bash "$temp_dir/install.sh" --port abc
    [ "$status" -eq 1 ]
    [[ "$output" == *"Invalid --port value"* ]]

    run bash "$temp_dir/install.sh" --port 5002
    [ "$status" -eq 1 ]
    [[ "$output" == *"used internally"* ]]

    rm -rf "$temp_dir"
}

@test "unit: compose frontend host port follows BIRDNET_WEB_PORT with default 80" {
    local compose="$PROJECT_DIR/docker-compose.yml"

    # Explicit empty override so a BIRDNET_WEB_PORT in the repo's own .env
    # (shell env beats .env in compose) can't skew the default check
    run bash -c "BIRDNET_WEB_PORT= docker compose -f '$compose' config --format json | python3 -c \"
import sys, json
cfg = json.load(sys.stdin)
ports = cfg['services']['frontend']['ports']
assert any(str(p.get('published')) == '80' and p.get('target') == 80 for p in ports), ports
print('default: frontend publishes 80')
\""
    echo "output: $output"
    [ "$status" -eq 0 ]

    run bash -c "BIRDNET_WEB_PORT=8080 docker compose -f '$compose' config --format json | python3 -c \"
import sys, json
cfg = json.load(sys.stdin)
ports = cfg['services']['frontend']['ports']
assert any(str(p.get('published')) == '8080' and p.get('target') == 80 for p in ports), ports
print('override: frontend publishes 8080')
\""
    echo "output: $output"
    [ "$status" -eq 0 ]
}

@test "unit: apply_gpu_mem_to_config reopens [all] when last section is board-filtered" {
    local temp_dir
    temp_dir=$(mktemp -d)
    printf '[pi4]\nx=1\n\n[cm5]\ndtoverlay=dwc2\n' > "$temp_dir/config.txt"

    run run_install_function "$temp_dir" apply_gpu_mem_to_config "$temp_dir/config.txt"
    [ "$status" -eq 0 ]
    assert_file_contains "$temp_dir/config.txt" "gpu_mem=16"

    # The last three lines must be: [all], marker comment, gpu_mem=16 —
    # otherwise the setting would be scoped to the [cm5] section
    local tail3
    tail3=$(tail -3 "$temp_dir/config.txt" | tr '\n' '|')
    [[ "$tail3" == "[all]|#"*"|gpu_mem=16|" ]]

    rm -rf "$temp_dir"
}

@test "unit: apply_gpu_mem_to_config is idempotent and adds no duplicate [all] header" {
    local temp_dir
    temp_dir=$(mktemp -d)
    printf 'enable_uart=1\n\n[all]\nenable_uart=1\n' > "$temp_dir/config.txt"

    run run_install_function "$temp_dir" apply_gpu_mem_to_config "$temp_dir/config.txt"
    [ "$status" -eq 0 ]
    run run_install_function "$temp_dir" apply_gpu_mem_to_config "$temp_dir/config.txt"
    [ "$status" -eq 0 ]

    local gpu_count all_count
    gpu_count=$(grep -c '^gpu_mem=16$' "$temp_dir/config.txt")
    all_count=$(grep -cx '\[all\]' "$temp_dir/config.txt")
    [ "$gpu_count" -eq 1 ]
    [ "$all_count" -eq 1 ]

    rm -rf "$temp_dir"
}

@test "unit: apply_gpu_mem_to_config respects an existing gpu_mem setting" {
    local temp_dir
    temp_dir=$(mktemp -d)
    printf 'gpu_mem=128\n[all]\nenable_uart=1\n' > "$temp_dir/config.txt"

    run run_install_function "$temp_dir" apply_gpu_mem_to_config "$temp_dir/config.txt"
    [ "$status" -eq 0 ]
    assert_file_contains "$temp_dir/config.txt" "gpu_mem=128"
    assert_file_not_contains "$temp_dir/config.txt" "gpu_mem=16"

    rm -rf "$temp_dir"
}

@test "unit: setup_gpu_mem is a safe no-op outside a low-RAM headless Pi" {
    # In the test container at least one gate (Pi hardware / RAM / headless /
    # boot config presence) fails, so the function must return 0 untouched
    local temp_dir
    temp_dir=$(mktemp -d)

    run run_install_function "$temp_dir" setup_gpu_mem
    [ "$status" -eq 0 ]

    rm -rf "$temp_dir"
}

@test "unit: uninstall removes only the BirdNET gpu_mem block" {
    local temp_dir
    temp_dir=$(mktemp -d)
    printf 'enable_uart=1\n\n[all]\nenable_uart=1\n' > "$temp_dir/config.txt"

    run run_install_function "$temp_dir" apply_gpu_mem_to_config "$temp_dir/config.txt"
    [ "$status" -eq 0 ]
    assert_file_contains "$temp_dir/config.txt" "gpu_mem=16"

    run run_uninstall_function remove_gpu_mem_from_config "$temp_dir/config.txt"
    [ "$status" -eq 0 ]
    assert_file_not_contains "$temp_dir/config.txt" "gpu_mem=16"
    assert_file_not_contains "$temp_dir/config.txt" "BirdNET-PiPy:"
    assert_file_contains "$temp_dir/config.txt" "enable_uart=1"

    rm -rf "$temp_dir"
}

@test "unit: uninstall leaves a user-set gpu_mem line untouched" {
    local temp_dir
    temp_dir=$(mktemp -d)
    printf 'gpu_mem=128\n[all]\nenable_uart=1\n' > "$temp_dir/config.txt"

    run run_uninstall_function remove_gpu_mem_from_config "$temp_dir/config.txt"
    [ "$status" -eq 1 ]
    assert_file_contains "$temp_dir/config.txt" "gpu_mem=128"

    rm -rf "$temp_dir"
}

@test "unit: uninstall preserves a user-edited gpu_mem value below our marker" {
    # raspi-config edits an existing gpu_mem line in place, leaving our marker
    # comment above the user's new value — only the marker may be removed
    local temp_dir
    temp_dir=$(mktemp -d)
    printf 'enable_uart=1\n# BirdNET-PiPy: headless low-RAM device, reclaim GPU memory for the OS\ngpu_mem=128\ndtparam=audio=on\n' > "$temp_dir/config.txt"

    run run_uninstall_function remove_gpu_mem_from_config "$temp_dir/config.txt"
    [ "$status" -eq 0 ]
    assert_file_not_contains "$temp_dir/config.txt" "BirdNET-PiPy:"
    assert_file_contains "$temp_dir/config.txt" "gpu_mem=128"
    assert_file_contains "$temp_dir/config.txt" "dtparam=audio=on"

    rm -rf "$temp_dir"
}

@test "unit: uninstall never deletes an unrelated line after a lone marker" {
    local temp_dir
    temp_dir=$(mktemp -d)
    printf '# BirdNET-PiPy: headless low-RAM device, reclaim GPU memory for the OS\ndtoverlay=disable-wifi\n' > "$temp_dir/config.txt"

    run run_uninstall_function remove_gpu_mem_from_config "$temp_dir/config.txt"
    [ "$status" -eq 0 ]
    assert_file_not_contains "$temp_dir/config.txt" "BirdNET-PiPy:"
    assert_file_contains "$temp_dir/config.txt" "dtoverlay=disable-wifi"

    rm -rf "$temp_dir"
}

@test "unit: uninstall handles CRLF line endings from Windows-edited configs" {
    local temp_dir
    temp_dir=$(mktemp -d)
    printf 'enable_uart=1\r\n# BirdNET-PiPy: headless low-RAM device, reclaim GPU memory for the OS\r\ngpu_mem=16\r\n' > "$temp_dir/config.txt"

    run run_uninstall_function remove_gpu_mem_from_config "$temp_dir/config.txt"
    [ "$status" -eq 0 ]
    assert_file_not_contains "$temp_dir/config.txt" "gpu_mem=16"
    assert_file_not_contains "$temp_dir/config.txt" "BirdNET-PiPy:"
    assert_file_contains "$temp_dir/config.txt" "enable_uart=1"

    rm -rf "$temp_dir"
}

@test "unit: uninstall cleans up the [all] header it added once the section is empty" {
    local temp_dir
    temp_dir=$(mktemp -d)
    printf '[pi4]\nx=1\n\n[cm5]\ndtoverlay=dwc2\n' > "$temp_dir/config.txt"

    run run_install_function "$temp_dir" apply_gpu_mem_to_config "$temp_dir/config.txt"
    [ "$status" -eq 0 ]
    assert_file_contains "$temp_dir/config.txt" "gpu_mem=16"

    run run_uninstall_function remove_gpu_mem_from_config "$temp_dir/config.txt"
    [ "$status" -eq 0 ]
    assert_file_not_contains "$temp_dir/config.txt" "gpu_mem=16"
    assert_file_not_contains "$temp_dir/config.txt" "\[all\]"
    assert_file_contains "$temp_dir/config.txt" "dtoverlay=dwc2"

    rm -rf "$temp_dir"
}

@test "unit: uninstall --remove-project keeps data/ without --remove-data" {
    local temp_dir project
    temp_dir=$(mktemp -d)
    project="$temp_dir/BirdNET-PiPy"
    create_fake_project "$project"

    run run_uninstall_function uninstall_removal_steps "$project" false <<< "DELETE"
    [ "$status" -eq 0 ]
    assert_file_exists "$project/data/db/birds.db"
    [ ! -e "$project/install.sh" ]
    [ ! -e "$project/backend" ]
    [ ! -e "$project/.git" ]
    [[ "$output" == *"User data preserved at: $project/data"* ]]

    rm -rf "$temp_dir"
}

@test "unit: uninstall --full keeps data/ when its DELETE prompt is declined" {
    local temp_dir project
    temp_dir=$(mktemp -d)
    project="$temp_dir/BirdNET-PiPy"
    create_fake_project "$project"

    # Decline the data prompt, confirm the project prompt
    run run_uninstall_function uninstall_removal_steps "$project" true <<< $'no\nDELETE'
    [ "$status" -eq 0 ]
    assert_file_exists "$project/data/db/birds.db"
    [ ! -e "$project/install.sh" ]
    [[ "$output" == *"User data preserved at: $project/data"* ]]

    rm -rf "$temp_dir"
}

@test "unit: uninstall --remove-project follows a symlinked project directory" {
    local temp_dir project link
    temp_dir=$(mktemp -d)
    project="$temp_dir/ssd/BirdNET-PiPy"
    link="$temp_dir/BirdNET-PiPy"
    create_fake_project "$project"
    ln -s "$project" "$link"

    run run_uninstall_function uninstall_removal_steps "$link" false <<< "DELETE"
    [ "$status" -eq 0 ]
    assert_file_exists "$project/data/db/birds.db"
    [ ! -e "$project/install.sh" ]
    [ ! -e "$project/backend" ]
    [ ! -e "$project/.git" ]

    # Without data/ to keep, both the directory and the link go
    rm -rf "$project/data"
    touch "$project/install.sh"
    run run_uninstall_function uninstall_removal_steps "$link" false <<< "DELETE"
    [ "$status" -eq 0 ]
    [ ! -e "$project" ]
    [ ! -L "$link" ]

    rm -rf "$temp_dir"
}

@test "unit: uninstall --full removes the whole project directory" {
    local temp_dir project
    temp_dir=$(mktemp -d)
    project="$temp_dir/BirdNET-PiPy"
    create_fake_project "$project"

    run run_uninstall_function uninstall_removal_steps "$project" true <<< $'DELETE\nDELETE'
    [ "$status" -eq 0 ]
    [ ! -e "$project" ]
    [[ "$output" != *"preserved"* ]]

    rm -rf "$temp_dir"
}

# ============================================================================
# Integration Tests (full installation flow)
# ============================================================================

@test "integration: repeated media setup preserves one bind and existing child mounts" {
    # Real kernel mounts, but only a temporary directory and an empty tmpfs.
    # No block devices, formatting commands, application data or containers.
    run python3 - "$PROJECT_DIR" <<'PYMOUNT'
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile

spec = importlib.util.spec_from_file_location('mounts', Path(sys.argv[1]) / 'deployment/storage_mounts.py')
mounts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mounts)

with tempfile.TemporaryDirectory() as directory:
    # Native systemd hosts have a shared parent. A self-bind inherits its peer
    # group unless explicitly detached, causing each child mount to appear twice.
    subprocess.run(['mount', '--bind', directory, directory], check=True)
    subprocess.run(['mount', '--make-rshared', directory], check=True)
    root = Path(directory) / 'media'
    root.mkdir()
    # Also cover upgrading an already-created bind with the wrong peer group.
    subprocess.run(['mount', '--bind', str(root), str(root)], check=True)
    mounts.MEDIA_ROOT = root
    mounts.prepare_root()
    assert not os.path.ismount(root), 'Fixture must exercise a same-filesystem bind mount'
    # Mirror Docker's rslave view and verify it still receives later mounts.
    observer = Path(directory) / 'container-view'
    observer.mkdir()
    subprocess.run(['mount', '--bind', str(root), str(observer)], check=True)
    subprocess.run(['mount', '--make-rslave', str(observer)], check=True)
    mounts.prepare_root()
    child = root / 'synthetic-child'
    child.mkdir()
    subprocess.run(['mount', '-t', 'tmpfs', '-o', 'size=1m', 'tmpfs', str(child)], check=True)
    sentinel = child / 'preserved.txt'
    sentinel.write_text('existing media remains visible')

    def entries():
        return [line for line in Path('/proc/self/mountinfo').read_text().splitlines()
                if line.split()[4] == str(root) or line.split()[4].startswith(str(root) + '/')]

    before = entries()
    assert len(before) == 2, before
    for attempt in range(5):
        mounts.prepare_root()
        assert entries() == before, 'Repeated setup added mount layers'
        assert sentinel.read_text() == 'existing media remains visible'
        assert (observer / 'synthetic-child/preserved.txt').read_text() == 'existing media remains visible'
        print(f'Repeated setup {attempt + 1}/5: mount IDs and child contents preserved', flush=True)
    subprocess.run(['umount', str(child)], check=True)
    assert not mounts.is_mountpoint(observer / 'synthetic-child')
    subprocess.run(['umount', str(observer)], check=True)
    subprocess.run(['umount', str(root)], check=True)
    subprocess.run(['umount', directory], check=True)
PYMOUNT
    echo "Mount regression output: $output"
    [ "$status" -eq 0 ]
}

@test "integration: host storage upgrade works with stock update permissions" {
    # First restart after a stock updater fetched the new release: the new
    # checkout/images exist, but the helper and its sudo permissions do not.
    # This test creates no formatting request and formats no drives.
    install -d -o testuser -g testuser "$PROJECT_DIR/data/flags"
    rm -f /etc/sudoers.d/testuser
    cat > /etc/sudoers.d/birdnet-pipy <<EOF
testuser ALL=(ALL) NOPASSWD: $PROJECT_DIR/install.sh --update
testuser ALL=(ALL) NOPASSWD: $PROJECT_DIR/install.sh --update --branch *
EOF
    chmod 440 /etc/sudoers.d/birdnet-pipy
    run visudo -cf /etc/sudoers.d/birdnet-pipy
    [ "$status" -eq 0 ]
    [ ! -e /usr/local/libexec/birdnet-pipy/storage-format.py ]
    run sudo -u testuser env TEST_PROJECT="$PROJECT_DIR" bash -c '
        source <(sed "/^main$/d" "$TEST_PROJECT/deployment/birdnet-service.sh")
        PROJECT_ROOT="$TEST_PROJECT"
        ensure_host_storage_setup
    '
    local setup_status="$status"
    local setup_output="$output"
    # Restore the test harness permission even if setup failed.
    echo 'testuser ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/testuser
    chmod 440 /etc/sudoers.d/testuser
    echo "Host upgrade output: $setup_output"
    [ "$setup_status" -eq 0 ]
    [[ "$setup_output" == *"Host storage integration is ready"* ]]
    [[ "$setup_output" == *"no images fetched or built"* ]]
    for helper in storage-format.py storage_mounts.py; do
        assert_file_executable "/usr/local/libexec/birdnet-pipy/$helper"
        [ "$(stat -c '%U:%G:%a' "/usr/local/libexec/birdnet-pipy/$helper")" = root:root:755 ]
    done
    assert_sudoers_valid /etc/sudoers.d/birdnet-pipy
    assert_service_enabled birdnet-media-mounts
    assert_file_contains "$PROJECT_DIR/.env" 'BIRDNET_MANAGED_MEDIA_PROPAGATION=rslave'
    run bash -c "cd '$PROJECT_DIR' && docker compose config --format json | python3 -c '
import json, sys
services = json.load(sys.stdin)[\"services\"]
for name in (\"api\", \"main\", \"model-server\"):
    mount = next(v for v in services[name][\"volumes\"] if v[\"target\"] == \"/managed-media\")
    assert mount[\"source\"] == \"/var/lib/birdnet-pipy/media\"
    assert mount[\"bind\"][\"propagation\"] == \"rslave\"
'"
    [ "$status" -eq 0 ]
    assert_service_enabled birdnet-storage-format.path
    assert_file_exists "$PROJECT_DIR/data/flags/storage-format-available"
    # No helper has run just to advertise availability.
    [ "$(systemctl show birdnet-storage-format.service -p ExecMainStartTimestampMonotonic --value)" = 0 ]
    # Publish an expired synthetic request atomically. It must fail before any
    # disk commands, while exercising the real file event and one-shot service.
    run sudo -u testuser python3 -c "
import json, os
from pathlib import Path
flags = Path('$PROJECT_DIR/data/flags')
temporary = flags / '.synthetic-format-request'
temporary.write_text(json.dumps({'id': 'integration-expired', 'created_at': 0}))
os.rename(temporary, flags / 'storage-format-request.json')
"
    [ "$status" -eq 0 ]
    for attempt in {1..30}; do
        if [ -f "$PROJECT_DIR/data/flags/storage-format-status.json" ] && [ ! -e "$PROJECT_DIR/data/flags/storage-format-request.json" ]; then break; fi
        sleep 1
    done
    run python3 -c "import json; p=json.load(open('$PROJECT_DIR/data/flags/storage-format-status.json')); assert p['state']=='failed'; assert 'expired' in p['message']"
    [ "$status" -eq 0 ]
    [ ! -e "$PROJECT_DIR/data/flags/storage-format-request.json" ]
    local stamp started
    stamp=$(stat -c '%Y' "$PROJECT_DIR/data/flags/storage-format-status.json")
    started=$(systemctl show birdnet-storage-format.service -p ExecMainStartTimestampMonotonic --value)
    [ "$started" != 0 ]
    sleep 6
    [ "$(stat -c '%Y' "$PROJECT_DIR/data/flags/storage-format-status.json")" = "$stamp" ]
    [ "$(systemctl show birdnet-storage-format.service -p ExecMainStartTimestampMonotonic --value)" = "$started" ]
    [ "$(systemctl show birdnet-storage-format.service -p ActiveState --value)" = inactive ]
    run sudo -u testuser env TEST_PROJECT="$PROJECT_DIR" bash -c '
        source <(sed "/^main$/d" "$TEST_PROJECT/deployment/birdnet-service.sh")
        PROJECT_ROOT="$TEST_PROJECT"
        ensure_host_storage_setup
    '
    [ "$status" -eq 0 ]
    [[ "$output" != *"Installing host storage integration"* ]]
}

@test "integration: full installation completes successfully" {
    # Run installation with --no-reboot --skip-build
    # --skip-build skips Docker image build (which doesn't work in DinD due to overlay issues)
    # This tests all other installation steps: Docker setup, PulseAudio, systemd, sudoers, etc.
    # SUDO_USER must be set explicitly since we're running as root in the container
    # --port 8080 exercises the custom web port path end-to-end; the update
    # tests below then verify the choice survives updates untouched
    run sudo SUDO_USER=testuser bash "$PROJECT_DIR/install.sh" --no-reboot --skip-build --port 8080
    echo "Install output: $output"
    [ "$status" -eq 0 ]
    assert_service_enabled birdnet-storage-format.path
    run systemctl is-active birdnet-storage-format.path
    [ "$status" -eq 0 ]
    assert_file_exists "$PROJECT_DIR/data/flags/storage-format-available"
    [ "$(systemctl show birdnet-storage-format.service -p ActiveState --value)" = inactive ]
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

@test "integration: web port choice is recorded in .env" {
    # From the --port 8080 passed to the full installation test
    assert_file_contains "$PROJECT_DIR/.env" "BIRDNET_WEB_PORT=8080"
}

@test "integration: runtime script is executable" {
    assert_file_executable "$PROJECT_DIR/deployment/birdnet-service.sh"
}

# ============================================================================
# Update Mode Tests
# ============================================================================

@test "integration: unattended install runs as direct root for the --user account" {
    # How an image's first-boot service calls it: plain root (no sudo, so no
    # SUDO_USER), the account named explicitly, and no --no-reboot: unattended
    # must never reboot on its own (a reboot here would take the container down)
    run env -u SUDO_USER bash "$PROJECT_DIR/install.sh" --unattended --user testuser --skip-build
    echo "Install output: $output"
    [ "$status" -eq 0 ]
    [[ "$output" == *"Reboot skipped (--unattended"* ]]

    assert_file_contains "/etc/systemd/system/birdnet-pipy.service" "User=testuser"
    assert_service_enabled "birdnet-pipy"
    assert_sudoers_valid "/etc/sudoers.d/birdnet-pipy"
    assert_user_in_group testuser docker
}

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

    # Assert the web port chosen at install time survived the update
    # (.env is untracked, so git sync must not touch it)
    assert_file_contains "$PROJECT_DIR/.env" "BIRDNET_WEB_PORT=8080"
}

@test "integration: update on non-release branch falls back to local build" {
    setup_fake_origin
    push_synthetic_commit "backend/core/test_update_marker.py" "TEST_MARKER = \"$(date +%s)\""

    run sudo SUDO_USER=testuser bash "$PROJECT_DIR/install.sh" --update --skip-build
    echo "Update output: $output"
    [ "$status" -eq 0 ]
    [[ "$output" == *"has no pre-built images, building locally"* ]]
}

@test "integration: uninstall removes the storage format watcher and availability" {
    # Independent fixture so this cleanup check can run on its own.
    install -d -o testuser -g testuser "$PROJECT_DIR/data/flags"
    touch "$PROJECT_DIR/data/flags/storage-format-available"
    cp "$PROJECT_DIR/deployment/birdnet-storage-format.service" /etc/systemd/system/
    sed "s|@REQUEST_PATH@|$PROJECT_DIR/data/flags/storage-format-request.json|" \
        "$PROJECT_DIR/deployment/birdnet-storage-format.path" > /etc/systemd/system/birdnet-storage-format.path
    systemctl daemon-reload
    systemctl enable --now birdnet-storage-format.path
    assert_file_exists "$PROJECT_DIR/data/flags/storage-format-available"
    mkdir -p /var/lib/birdnet-pipy
    printf '["synthetic-preserved-registry"]\n' > /var/lib/birdnet-pipy/media-mounts.json
    uninstall_storage_from_project() {
        # The library loader uses /dev/fd; the real invocation uses the repo.
        SCRIPT_DIR="$PROJECT_DIR"
        remove_sudoers
    }
    run run_uninstall_function uninstall_storage_from_project
    echo "Uninstall output: $output"
    [ "$status" -eq 0 ]
    [ ! -e /etc/systemd/system/birdnet-storage-format.path ]
    [ ! -e /etc/systemd/system/birdnet-storage-format.service ]
    [ ! -e "$PROJECT_DIR/data/flags/storage-format-available" ]
    assert_file_contains /var/lib/birdnet-pipy/media-mounts.json synthetic-preserved-registry
}
