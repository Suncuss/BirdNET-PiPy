# test_helpers.bash - Shared helper functions for BATS tests
#
# Usage in test files:
#   load 'test_helpers'
#
# Requires:
#   - PROJECT_DIR environment variable pointing to the test project directory

# Setup test repository in a writable location
# Usage: setup_test_repo
setup_test_repo() {
    if [ -z "$PROJECT_DIR" ]; then
        echo "ERROR: PROJECT_DIR not set" >&2
        return 1
    fi

    # Ensure project directory exists and is owned by testuser
    if [ ! -d "$PROJECT_DIR" ]; then
        sudo mkdir -p "$PROJECT_DIR"
        sudo chown testuser:testuser "$PROJECT_DIR"
    fi
}

# Assert that a file contains a specific string
# Usage: assert_file_contains <file_path> <expected_string>
assert_file_contains() {
    local file_path="$1"
    local expected="$2"

    if [ ! -f "$file_path" ]; then
        echo "File does not exist: $file_path" >&2
        return 1
    fi

    if ! grep -q "$expected" "$file_path"; then
        echo "File '$file_path' does not contain: $expected" >&2
        echo "File contents:" >&2
        cat "$file_path" >&2
        return 1
    fi
}

# Assert that a file does not contain a specific string
# Usage: assert_file_not_contains <file_path> <unexpected_string>
assert_file_not_contains() {
    local file_path="$1"
    local unexpected="$2"

    if [ ! -f "$file_path" ]; then
        # File doesn't exist, so it doesn't contain the string
        return 0
    fi

    if grep -q "$unexpected" "$file_path"; then
        echo "File '$file_path' unexpectedly contains: $unexpected" >&2
        return 1
    fi
}

# Assert that a command exists
# Usage: assert_command_exists <command_name>
assert_command_exists() {
    local cmd="$1"

    if ! command -v "$cmd" &> /dev/null; then
        echo "Command not found: $cmd" >&2
        return 1
    fi
}

# Assert that a systemd service is enabled
# Usage: assert_service_enabled <service_name>
assert_service_enabled() {
    local service="$1"

    if ! systemctl is-enabled "$service" &> /dev/null; then
        echo "Service is not enabled: $service" >&2
        systemctl status "$service" 2>&1 || true
        return 1
    fi
}

# Assert that a systemd service file exists
# Usage: assert_service_exists <service_name>
assert_service_exists() {
    local service="$1"
    local service_file="/etc/systemd/system/${service}.service"

    if [ ! -f "$service_file" ]; then
        echo "Service file does not exist: $service_file" >&2
        return 1
    fi
}

# Assert that a user is in a specific group
# Usage: assert_user_in_group <username> <group_name>
assert_user_in_group() {
    local username="$1"
    local group="$2"

    if ! groups "$username" 2>/dev/null | grep -qw "$group"; then
        echo "User '$username' is not in group '$group'" >&2
        echo "User groups: $(groups "$username" 2>/dev/null)" >&2
        return 1
    fi
}

# Assert that a directory exists
# Usage: assert_directory_exists <dir_path>
assert_directory_exists() {
    local dir_path="$1"

    if [ ! -d "$dir_path" ]; then
        echo "Directory does not exist: $dir_path" >&2
        return 1
    fi
}

# Assert that a file exists
# Usage: assert_file_exists <file_path>
assert_file_exists() {
    local file_path="$1"

    if [ ! -f "$file_path" ]; then
        echo "File does not exist: $file_path" >&2
        return 1
    fi
}

# Assert that a file is executable
# Usage: assert_file_executable <file_path>
assert_file_executable() {
    local file_path="$1"

    if [ ! -x "$file_path" ]; then
        echo "File is not executable: $file_path" >&2
        ls -la "$file_path" 2>&1 || true
        return 1
    fi
}

# Assert that sudoers file is valid
# Usage: assert_sudoers_valid <sudoers_file>
assert_sudoers_valid() {
    local sudoers_file="$1"

    if [ ! -f "$sudoers_file" ]; then
        echo "Sudoers file does not exist: $sudoers_file" >&2
        return 1
    fi

    if ! sudo visudo -c -f "$sudoers_file" >/dev/null 2>&1; then
        echo "Sudoers file has invalid syntax: $sudoers_file" >&2
        sudo visudo -c -f "$sudoers_file" 2>&1 || true
        return 1
    fi
}

# Wait for a condition with timeout
# Usage: wait_for <command> <timeout_seconds> [message]
wait_for() {
    local cmd="$1"
    local timeout="$2"
    local message="${3:-Waiting for condition}"

    local count=0
    while ! eval "$cmd" 2>/dev/null; do
        if [ $count -ge $timeout ]; then
            echo "Timeout ($timeout s) waiting for: $message" >&2
            return 1
        fi
        sleep 1
        ((count++))
    done
}

# Run install.sh with common test options
# Usage: run_install [additional_args...]
run_install() {
    sudo -E "$PROJECT_DIR/install.sh" --no-reboot "$@"
}

# Check if Docker images with a specific prefix exist
# Usage: assert_docker_images_exist <prefix>
assert_docker_images_exist() {
    local prefix="$1"

    local count=$(docker images 2>/dev/null | grep -c "$prefix" || true)
    if [ "$count" -eq 0 ]; then
        echo "No Docker images found with prefix: $prefix" >&2
        echo "Available images:" >&2
        docker images 2>&1 || true
        return 1
    fi
}
