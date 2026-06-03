from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional
import csv
import io
import json
import re

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.db.session import get_db
from app.db.models import User, Application, Environment, Credential, ApplicationModule, RBACScan
from app.core.dependencies import get_current_user
from app.core.security import encrypt_credential, decrypt_credential
from app.schemas.workspace import ApplicationResponse, EnvironmentResponse

router = APIRouter()


@router.get("/{application_id}", response_model=ApplicationResponse)
async def get_application(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Application).where(Application.id == application_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return ApplicationResponse.model_validate(app)


@router.get("/{application_id}/environments", response_model=list[EnvironmentResponse])
async def list_environments(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Environment).where(Environment.application_id == application_id)
    )
    return [EnvironmentResponse.model_validate(e) for e in result.scalars().all()]


@router.get("/{application_id}/modules")
async def list_modules(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApplicationModule)
        .where(ApplicationModule.application_id == application_id)
        .where(ApplicationModule.parent_id == None)
        .order_by(ApplicationModule.order_index)
    )
    modules = result.scalars().all()
    return [
        {
            "id": m.id,
            "name": m.name,
            "description": m.description,
            "url_pattern": m.url_pattern,
            "icon": m.icon,
            "semantic_tags": m.semantic_tags or [],
        }
        for m in modules
    ]


class ApplicationSettingsUpdate(BaseModel):
    description: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@router.patch("/{application_id}/settings")
async def update_application_settings(
    application_id: str,
    payload: ApplicationSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Application).where(Application.id == application_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    if payload.description is not None:
        app.description = payload.description

    if payload.username or payload.password:
        cred_result = await db.execute(
            select(Credential).where(Credential.application_id == application_id).limit(1)
        )
        cred = cred_result.scalar_one_or_none()
        if cred:
            if payload.username:
                cred.username = payload.username
            if payload.password:
                cred.password_encrypted = encrypt_credential(payload.password)
        else:
            if payload.username and payload.password:
                cred = Credential(
                    application_id=application_id,
                    username=payload.username,
                    password_encrypted=encrypt_credential(payload.password),
                )
                db.add(cred)

    await db.commit()
    return {"status": "ok"}


# ─── Role Credentials ─────────────────────────────────────────────────────────

class RoleCredentialIn(BaseModel):
    role_name: str
    username: str
    password: str


@router.get("/{application_id}/role-credentials")
async def list_role_credentials(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Credential)
        .where(Credential.application_id == application_id)
        .where(Credential.label != None)
        .where(Credential.label != "")
        .order_by(Credential.label)
    )
    creds = result.scalars().all()
    return [
        {
            "id": c.id,
            "role_name": c.label,
            "username": c.username,
        }
        for c in creds
    ]


@router.post("/{application_id}/role-credentials", status_code=201)
async def add_role_credential(
    application_id: str,
    payload: RoleCredentialIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cred = Credential(
        application_id=application_id,
        label=payload.role_name.strip(),
        username=payload.username.strip(),
        password_encrypted=encrypt_credential(payload.password),
    )
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    return {"id": cred.id, "role_name": cred.label, "username": cred.username}


@router.delete("/{application_id}/role-credentials/{credential_id}", status_code=204)
async def delete_role_credential(
    application_id: str,
    credential_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id,
            Credential.application_id == application_id,
        )
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    await db.delete(cred)
    await db.commit()


def _prettify_role_name(prefix: str) -> str:
    """Convert KEY_PREFIX to 'Key Prefix' for display."""
    return " ".join(w.capitalize() for w in prefix.split("_") if w)


def _parse_env_style(text: str) -> list[dict]:
    """
    Parse .env / properties-style files where credentials are stored as paired keys:
        ROLE_USERNAME=user
        ROLE_PASSWORD=pass
    Also handles simpler variants like:
        ROLE_USER=user  /  ROLE_PASS=pass
        ROLE_EMAIL=user /  ROLE_PWD=pass
    Lines starting with # or not containing = are skipped.
    Non-credential keys (BASE_URL, LAB_NAME, etc.) are ignored automatically.
    """
    kv: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        kv[key.strip().upper()] = val.strip()

    # Suffix groups to detect: prefer the longer/more-specific suffix first
    USERNAME_SUFFIXES = ("_USERNAME", "_USER", "_EMAIL", "_LOGIN")
    PASSWORD_SUFFIXES = ("_PASSWORD", "_PASS", "_PWD", "_SECRET")

    results = []
    seen_prefixes: set[str] = set()

    for key in kv:
        for us in USERNAME_SUFFIXES:
            if key.endswith(us):
                prefix = key[: -len(us)]
                if not prefix or prefix in seen_prefixes:
                    break
                # Find the matching password key
                pwd_val = None
                for ps in PASSWORD_SUFFIXES:
                    pwd_val = kv.get(prefix + ps)
                    if pwd_val:
                        break
                if pwd_val:
                    seen_prefixes.add(prefix)
                    results.append({
                        "role_name": _prettify_role_name(prefix),
                        "username": kv[key],
                        "password": pwd_val,
                    })
                break  # matched a username suffix — no need to try others

    return results


def _parse_credential_file(content: bytes, filename: str) -> list[dict]:
    """
    Parse credentials from any file format.
    Supported formats:
      - .env / properties style  (KEY_USERNAME=x  KEY_PASSWORD=y pairs)
      - CSV / TSV / TXT          (3-column tabular, header row optional)
      - JSON                     (array of objects with role/user/pass keys)
      - Excel (.xlsx / .xls)     (first sheet, 3-column tabular)
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"

    rows: list[list[str]] = []

    if ext in ("xlsx", "xls"):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        ws = wb.active
        for row in ws.iter_rows(values_only=True):
            rows.append([str(c).strip() if c is not None else "" for c in row])
        return _extract_role_rows(rows)

    if ext == "json":
        data = json.loads(content.decode("utf-8", errors="replace"))
        if isinstance(data, list):
            return _normalise_json_rows(data)
        raise ValueError("JSON must be an array of objects")

    # Text-based formats (csv, tsv, txt, env, properties, ini, conf, …)
    text = content.decode("utf-8", errors="replace")

    # ── Detect .env / KEY=VALUE style ──────────────────────────────────────────
    # Heuristic: majority of non-blank lines contain = and at least one key ends
    # with _USERNAME, _USER, _EMAIL, _PASSWORD, _PASS, or _PWD.
    non_blank = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    has_eq = sum(1 for l in non_blank if "=" in l)
    upper_kv = [l for l in non_blank if "=" in l and l.split("=", 1)[0].strip().isupper()]
    has_cred_keys = any(
        l.split("=", 1)[0].strip().upper().endswith(s)
        for l in non_blank
        for s in ("_USERNAME", "_USER", "_EMAIL", "_PASSWORD", "_PASS", "_PWD")
    )

    if has_cred_keys and has_eq >= len(non_blank) * 0.5:
        return _parse_env_style(text)

    # ── Tabular CSV / TSV / TXT ─────────────────────────────────────────────────
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t|;")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "," if "," in sample else "\t" if "\t" in sample else None

    if delimiter:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        for row in reader:
            rows.append([c.strip() for c in row])
    else:
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                rows.append(re.split(r"\s{2,}|\t", line) or line.split())

    return _extract_role_rows(rows)


def _normalise_json_rows(data: list[dict]) -> list[dict]:
    ROLE_KEYS = {"role", "role_name", "rolename", "role name"}
    USER_KEYS = {"username", "user", "email", "login"}
    PASS_KEYS = {"password", "pass", "pwd", "secret"}

    results = []
    for obj in data:
        lower = {k.lower().replace(" ", "_"): v for k, v in obj.items()}
        role = next((lower[k] for k in ROLE_KEYS if k in lower), None)
        user = next((lower[k] for k in USER_KEYS if k in lower), None)
        pwd = next((lower[k] for k in PASS_KEYS if k in lower), None)
        if role and user and pwd:
            results.append({"role_name": str(role).strip(), "username": str(user).strip(), "password": str(pwd).strip()})
    return results


def _extract_role_rows(rows: list[list[str]]) -> list[dict]:
    if not rows:
        return []

    ROLE_ALIASES = {"role", "role_name", "rolename", "role name"}
    USER_ALIASES = {"username", "user", "email", "login", "user name"}
    PASS_ALIASES = {"password", "pass", "pwd", "secret"}

    # Detect header row
    first = [c.lower().replace(" ", "_") for c in rows[0]]
    has_header = any(h in ROLE_ALIASES | USER_ALIASES | PASS_ALIASES for h in first)

    if has_header:
        role_idx = next((i for i, h in enumerate(first) if h in ROLE_ALIASES), None)
        user_idx = next((i for i, h in enumerate(first) if h in USER_ALIASES), None)
        pass_idx = next((i for i, h in enumerate(first) if h in PASS_ALIASES), None)
        data_rows = rows[1:]
    else:
        # Assume positional: col 0 = role, col 1 = username, col 2 = password
        role_idx, user_idx, pass_idx = 0, 1, 2
        data_rows = rows

    results = []
    for row in data_rows:
        if len(row) < 3:
            continue
        try:
            role = row[role_idx].strip() if role_idx is not None else row[0].strip()
            user = row[user_idx].strip() if user_idx is not None else row[1].strip()
            pwd = row[pass_idx].strip() if pass_idx is not None else row[2].strip()
        except IndexError:
            continue
        if role and user and pwd:
            results.append({"role_name": role, "username": user, "password": pwd})
    return results


@router.post("/{application_id}/role-credentials/bulk")
async def bulk_import_role_credentials(
    application_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Application).where(Application.id == application_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Application not found")

    content = await file.read()
    try:
        parsed = _parse_credential_file(content, file.filename or "upload.csv")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse file: {exc}")

    if not parsed:
        raise HTTPException(status_code=422, detail="No valid rows found. Expected columns: role_name, username, password")

    imported = 0
    skipped = 0
    for row in parsed:
        # Skip duplicates (same role_name already stored for this app)
        dup = await db.execute(
            select(Credential).where(
                Credential.application_id == application_id,
                Credential.label == row["role_name"],
            )
        )
        if dup.scalar_one_or_none():
            skipped += 1
            continue
        db.add(Credential(
            application_id=application_id,
            label=row["role_name"],
            username=row["username"],
            password_encrypted=encrypt_credential(row["password"]),
        ))
        imported += 1

    await db.commit()
    return {
        "imported": imported,
        "skipped": skipped,
        "total_in_file": len(parsed),
        "message": f"Imported {imported} role credential(s). {skipped} duplicate(s) skipped.",
    }


# ─── RBAC Scan ────────────────────────────────────────────────────────────────

@router.post("/{application_id}/rbac-scan", status_code=202)
async def start_rbac_scan(
    application_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Application).where(Application.id == application_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Application not found")

    # Check there are role credentials to scan
    cred_res = await db.execute(
        select(Credential)
        .where(Credential.application_id == application_id)
        .where(Credential.label.isnot(None))
        .where(Credential.label != "")
        .limit(1)
    )
    if not cred_res.scalar_one_or_none():
        raise HTTPException(status_code=422, detail="No role credentials configured for this application")

    scan = RBACScan(
        application_id=application_id,
        status="pending",
        triggered_by=current_user.id,
    )
    db.add(scan)
    await db.commit()
    await db.refresh(scan)

    from app.rbac.scanner import run_rbac_scan
    background_tasks.add_task(run_rbac_scan, scan.id, application_id)

    return {"scan_id": scan.id, "status": "pending"}


@router.get("/{application_id}/rbac-scan/latest")
async def get_latest_rbac_scan(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scan_res = await db.execute(
        select(RBACScan)
        .where(RBACScan.application_id == application_id)
        .order_by(RBACScan.created_at.desc())
        .limit(1)
    )
    scan = scan_res.scalar_one_or_none()
    if not scan:
        return None

    return {
        "id": scan.id,
        "status": scan.status,
        "started_at": scan.started_at.isoformat() if scan.started_at else None,
        "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
        "results": scan.results or {},
        "error_message": scan.error_message,
    }
