# Authentication and user management

Brief sections 7 and 8. Code: `app/auth/` (login, tokens, FastAPI dependencies) and
`app/services/users.py` (admin user management). Settings: `auth` in `config/app.yaml`;
the signing key is `JWT_SECRET_KEY` in the environment.

## Login

`AuthService.login(username, password)`:
- Passwords are stored only as argon2 hashes (`argon2-cffi`).
- Wrong username, wrong password and disabled accounts all fail with the same
  `INVALID_CREDENTIALS` and *"The username or password is not correct."*; the real reason is
  only in the audit log. When the username does not exist a dummy hash is still verified,
  so the response time does not reveal which usernames exist.
- Success returns an access token, its lifetime and the user's identity, and records
  `login` in the audit log (with `last_login_at`). Failures record `login_failed` with the
  attempted username and the reason (`unknown_user`, `wrong_password`, `disabled`).

## Access tokens (JWT)

| Claim | Meaning |
| --- | --- |
| `sub` | user ID |
| `ver` | token version of the user at login |
| `iss` | issuer (`auth.issuer`) |
| `iat`, `exp` | issued and expiry time (`auth.access_token_minutes`, 60) |
| `jti` | unique token ID |

- Signed with HS256 and `JWT_SECRET_KEY`; in production the key must be at least 32
  characters.
- `decode` checks the signature, the algorithm (no `none`), the issuer, the expiry and
  that every claim is present. Expired tokens give `TOKEN_EXPIRED`, anything else
  `INVALID_TOKEN` (both HTTP 401 in Step 18).
- **The token carries no role or region.** `AuthService.authenticate(token)` loads the
  user, role and region from the database on every call, refuses disabled users and
  refuses tokens whose `ver` differs from the user's current `token_version`.

## Revoking tokens

`token_version` is increased when a user is **disabled** or their **password is reset**
(also by the seed when a demo password changes). Every token issued before stops working
at once; re-enabling a user does not revive old tokens. A role or region change does not
need revocation because the role and region are read from the database on every request.

## FastAPI dependencies (`app/auth/dependencies.py`)

- `CurrentUser`: reads `Authorization: Bearer <token>`, validates it with
  `AuthService.authenticate` and returns the `AuthenticatedUser` (user ID, username, role,
  region) that the agent receives. Missing, invalid, expired, tampered or revoked tokens
  are refused.
- `AdminUser`: the same, and the role must be `admin` (`ADMIN_ONLY`, HTTP 403).

## Admin user management (`UserAdminService`)

| Action | Rules | Audit event |
| --- | --- | --- |
| `list_users` | admin only | (read only) |
| `create_user(username, display_name, password, role, region)` | username `^[a-z][a-z0-9._-]{2,63}$`, unique; password at least `min_password_length` (10); a sales manager needs exactly one region, other roles none | `user_created` |
| `set_active(user_id, active)` | admins cannot disable themselves; disabling bumps `token_version` | `user_disabled` / `user_enabled` |
| `reset_password(user_id, new_password)` | password rules; bumps `token_version` | `password_reset` |
| `assign_role(user_id, role, region)` | same role/region rules | `role_assigned` |

Every action requires an active admin (`ADMIN_ONLY` otherwise). A newly created user can
log in at once, and their region is enforced by the database from their first question.

## Tests

- `tests/unit/test_tokens.py`: valid, expired, foreign-key, tampered, `none`-algorithm,
  wrong-issuer and incomplete tokens; production key length; no role or region in the
  token.
- `tests/integration/test_auth_db.py`: correct login, wrong password, `disabled.user` and
  unknown users refused and audited (scenario 1); expired and invalid tokens refused
  (scenario 2); a role change applies to an existing token; a disabled user's old token
  stops working; password reset revokes tokens; only admins manage users; input
  validation; every action audited; an admin creates `test.nordics` with region Europe,
  who logs in and immediately sees only European data through the agent (scenario 24).
