"""C13 — RBAC + ABAC.

Dev-mode JWT auth (no users/passwords — this is a demo): POST /api/auth/token {role}
returns a signed token carrying the role. Clients send `Authorization: Bearer <token>`.

Backward compatible: no token -> role "researcher" (so the QA harness and current
frontend keep working). The frontend may also pass `role_ctx` in the search body;
a valid token always wins over the body role.

Roles: researcher, analyst, project_lead, admin, external_partner.

Capability matrix (see CAPABILITIES):
                       search  view_internal  export  patch/review  audit  subscribe
  researcher             ✓          ✓           ✓          ✗           ✗        ✓
  analyst                ✓          ✓           ✓          ✗           ✗        ✓
  project_lead           ✓          ✓           ✓          ✓           ✓        ✓
  admin                  ✓          ✓           ✓          ✓           ✓        ✓
  external_partner       ✓          ✗           ✗          ✗           ✗        ✓

ABAC (attribute filtering, enforced in retrieval): external_partner never sees
documents whose section ∈ {Статьи, Доклады} OR whose sensitivity == "internal".
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, Header, HTTPException
from jose import JWTError, jwt

JWT_SECRET = os.getenv("SCITANGLE_JWT_SECRET", "dev-secret-sci-tangle-2026")
JWT_ALG = "HS256"
JWT_TTL_HOURS = int(os.getenv("SCITANGLE_JWT_TTL_HOURS", "24"))

ROLES = {"researcher", "analyst", "project_lead", "admin", "external_partner"}
DEFAULT_ROLE = "researcher"

# capability -> set of roles allowed
CAPABILITIES = {
    "search": ROLES,
    "subscribe": ROLES,
    "view_internal": {"researcher", "analyst", "project_lead", "admin"},
    "export": {"researcher", "analyst", "project_lead", "admin"},
    "review": {"project_lead", "admin"},        # PATCH edge + assertion review
    "audit": {"project_lead", "admin"},
    "analytics": ROLES,
}

# sections hidden from external_partner (ABAC)
INTERNAL_SECTIONS = {"Статьи", "Доклады"}


def issue_token(role: str) -> str:
    if role not in ROLES:
        raise HTTPException(status_code=400, detail=f"unknown role '{role}'")
    now = datetime.now(timezone.utc)
    payload = {
        "role": role,
        "sub": f"demo-{role}",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_TTL_HOURS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_role(authorization: Optional[str]) -> str:
    """Extract role from an `Authorization: Bearer <jwt>` header.

    Missing / malformed / expired token -> DEFAULT_ROLE (backward compatible).
    """
    if not authorization:
        return DEFAULT_ROLE
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return DEFAULT_ROLE
    try:
        payload = jwt.decode(parts[1], JWT_SECRET, algorithms=[JWT_ALG])
    except JWTError:
        return DEFAULT_ROLE
    role = payload.get("role")
    return role if role in ROLES else DEFAULT_ROLE


def current_role(authorization: Optional[str] = Header(None)) -> str:
    """FastAPI dependency: resolve the caller's role from the JWT (or default)."""
    return decode_role(authorization)


def can(role: str, capability: str) -> bool:
    return role in CAPABILITIES.get(capability, set())


def require(capability: str):
    """Dependency factory enforcing a capability; raises 403 otherwise."""
    def _dep(role: str = Depends(current_role)) -> str:
        if not can(role, capability):
            raise HTTPException(
                status_code=403,
                detail=f"role '{role}' is not permitted to '{capability}'",
            )
        return role
    return _dep


def doc_visible(role: str, section: Optional[str], sensitivity: Optional[str]) -> bool:
    """ABAC visibility check for a single document (used at retrieval level)."""
    if role != "external_partner":
        return True
    if section in INTERNAL_SECTIONS:
        return False
    if (sensitivity or "").lower() == "internal":
        return False
    return True
