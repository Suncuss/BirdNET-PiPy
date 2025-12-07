# Authentication System

This document describes the optional password-based authentication system for BirdNET-PiPy.

## Overview

The authentication system protects sensitive features (settings and audio stream) while keeping detection data publicly accessible. It's designed to be:

- **Optional** - Disabled by default, enable when needed
- **Simple** - Single shared password, no user accounts
- **Persistent** - 7-day sessions via cookies
- **Recoverable** - Password reset via file creation on the Pi

## What's Protected

| Resource | Public | Protected |
|----------|:------:|:---------:|
| Dashboard | ✓ | |
| Bird Gallery | ✓ | |
| Bird Details | ✓ | |
| Charts | ✓ | |
| Detection data APIs | ✓ | |
| Live Feed page (view only) | ✓ | |
| **Audio stream playback** | | ✓ |
| **Settings page & API** | | ✓ |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         BROWSER                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Settings.vue│  │ LiveFeed.vue│  │ Session Cookie          │  │
│  │ (protected) │  │ (stream)    │  │ {authenticated: true}   │  │
│  └──────┬──────┘  └──────┬──────┘  └─────────────────────────┘  │
└─────────┼────────────────┼──────────────────────────────────────┘
          │                │
          ▼                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         NGINX                                    │
│                                                                  │
│  /api/settings ──────────────────────► Flask API                │
│                                         (@require_auth)          │
│                                                                  │
│  /stream/* ─────► auth_request ─────► /api/auth/verify          │
│                   (internal)           │                         │
│                        │               ▼                         │
│                        │         200 OK or 401                   │
│                        │               │                         │
│                        ▼               │                         │
│                   Allow/Deny ◄─────────┘                         │
│                        │                                         │
│                        ▼                                         │
│                   Icecast Server                                 │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FLASK API SERVER                              │
│                                                                  │
│  Auth Endpoints:                                                 │
│  ├── GET  /api/auth/status    - Check auth state                │
│  ├── POST /api/auth/setup     - Set initial password            │
│  ├── POST /api/auth/login     - Authenticate with password      │
│  ├── POST /api/auth/logout    - Clear session                   │
│  ├── GET  /api/auth/verify    - Internal: 200 or 401            │
│  ├── POST /api/auth/toggle    - Enable/disable auth             │
│  └── POST /api/auth/change-password - Change password           │
│                                                                  │
│  Protected Endpoints (use @require_auth decorator):             │
│  ├── GET  /api/settings                                         │
│  └── PUT  /api/settings                                         │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CREDENTIAL STORAGE                            │
│                                                                  │
│  data/config/auth.json                                          │
│  {                                                               │
│    "password_hash": "$2b$12$...",  // bcrypt hash               │
│    "auth_enabled": true,                                        │
│    "session_secret": "hex...",     // Flask session signing     │
│    "created_at": "2025-12-06T...", // ISO timestamp             │
│    "last_modified": "2025-12-06T..."                            │
│  }                                                               │
│                                                                  │
│  File permissions: 0600 (owner read/write only)                 │
└─────────────────────────────────────────────────────────────────┘
```

## User Flows

### Enabling Authentication (First Time)

```
1. User navigates to Settings page
2. Toggles "Require Authentication" ON
3. "Set Up Authentication" modal appears
4. User enters password (min 4 chars) + confirms
5. Clicks "Enable Authentication"
   │
   ▼
Backend:
   - Hashes password with bcrypt (12 rounds)
   - Saves to auth.json with auth_enabled: true
   - Sets session cookie (7-day expiry)
   │
   ▼
6. User sees "Authentication enabled" message
7. User is now authenticated (session cookie set)
```

### Returning User Login

```
1. User navigates to Settings or tries to play audio stream
2. Router guard or stream check detects auth required
3. Login modal appears
4. User enters password
5. Clicks "Login"
   │
   ▼
Backend:
   - Verifies password against stored hash
   - Sets session cookie if valid
   │
   ▼
6. User gains access for 7 days
```

### Password Reset (Forgot Password)

```
1. SSH to Raspberry Pi
2. Create reset file:
   $ touch /path/to/data/config/RESET_PASSWORD

3. Next auth check on any protected route:
   - Backend detects RESET_PASSWORD file
   - Deletes auth.json (clears password)
   - Deletes RESET_PASSWORD file
   - Auth is now disabled

4. User can set new password via Settings
```

### Disabling Authentication

```
1. User (authenticated) goes to Settings
2. Toggles "Require Authentication" OFF
3. Backend sets auth_enabled: false in auth.json
4. All resources become public immediately
   (password hash is preserved for re-enabling)
```

## Technical Details

### Password Hashing

- **Algorithm**: bcrypt
- **Cost factor**: 12 rounds (~250ms to hash)
- **Salt**: Automatically generated per password

```python
# Hashing
bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12))

# Verification
bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
```

### Session Management

- **Type**: Flask signed cookies
- **Duration**: 7 days
- **Secret**: Auto-generated 32-byte hex, stored in auth.json
- **Cookie flags**: HttpOnly, SameSite=Lax

```python
# Session configuration in Flask
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
```

### Nginx Stream Protection

The audio stream is protected using nginx's `auth_request` directive:

```nginx
# Internal auth verification endpoint
location = /internal/auth {
    internal;
    proxy_pass http://api:5002/api/auth/verify;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header Cookie $http_cookie;
}

# Protected stream
location ^~ /stream/ {
    auth_request /internal/auth;
    error_page 401 = @stream_unauthorized;
    # ... proxy to Icecast
}
```

### No Restart Required

Unlike other settings that require a service restart, authentication changes take effect immediately because:

1. `@require_auth` decorator reads `auth.json` on every protected request
2. Nginx's `auth_request` calls `/api/auth/verify` on every stream request
3. Session cookies are checked dynamically

## File Locations

| File | Purpose |
|------|---------|
| `data/config/auth.json` | Credentials and settings |
| `data/config/RESET_PASSWORD` | Create to trigger password reset |
| `backend/core/auth.py` | Auth module (hashing, sessions, decorator) |
| `frontend/src/composables/useAuth.js` | Vue auth state management |
| `frontend/src/components/LoginModal.vue` | Login/setup UI component |

## API Reference

### GET /api/auth/status

Returns current authentication state.

**Response:**
```json
{
  "auth_enabled": true,
  "setup_complete": true,
  "authenticated": true
}
```

### POST /api/auth/setup

Set initial password (first-time setup only).

**Request:**
```json
{
  "password": "mypassword"
}
```

**Response (success):**
```json
{
  "message": "Password set successfully",
  "authenticated": true
}
```

### POST /api/auth/login

Authenticate with password.

**Request:**
```json
{
  "password": "mypassword"
}
```

**Response (success):**
```json
{
  "message": "Login successful"
}
```

**Response (failure):**
```json
{
  "error": "Invalid password"
}
```

### POST /api/auth/logout

Clear session.

**Response:**
```json
{
  "message": "Logged out"
}
```

### GET /api/auth/verify

Internal endpoint for nginx auth_request.

- Returns `200 OK` if authenticated or auth disabled
- Returns `401 Unauthorized` if auth required but not authenticated

### POST /api/auth/toggle

Enable or disable authentication (requires auth if currently enabled).

**Request:**
```json
{
  "enabled": true
}
```

**Response:**
```json
{
  "message": "Authentication enabled",
  "auth_enabled": true
}
```

### POST /api/auth/change-password

Change password (requires current password).

**Request:**
```json
{
  "current_password": "oldpassword",
  "new_password": "newpassword"
}
```

**Response (success):**
```json
{
  "message": "Password changed successfully"
}
```

## Security Considerations

1. **Password Storage**: Only bcrypt hashes are stored, never plaintext
2. **File Permissions**: auth.json is set to 0600 (owner only)
3. **Session Secret**: Unique per installation, auto-generated
4. **HTTPS**: Recommended for production to protect cookies in transit
5. **Brute Force**: No rate limiting currently implemented (consider adding for production)
6. **Minimum Password**: 4 characters (simple for home use, increase for public deployments)

## Troubleshooting

### "Authentication required" when auth is disabled

1. Check auth.json exists and `auth_enabled` is false
2. Clear browser cookies and refresh
3. Check nginx config is correctly proxying cookies

### Can't reset password

1. Ensure RESET_PASSWORD file is created in correct directory
2. File must be in `data/config/` (same directory as auth.json)
3. Try accessing any protected page to trigger the reset check

### Session expires too quickly

1. Check server time is correct
2. Verify SESSION_LIFETIME is 7 days in Flask config
3. Ensure cookies are not being blocked by browser
