"""Password gate for the hosted (online) copy of the tool.

Active only when the environment variable BIM7D_PASSWORD is set (e.g. on the hosting service).
Run locally with start.bat / start.sh, the variable is not set and nothing changes.
After a correct password the browser keeps a signed cookie for 30 days.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import os
import time
from urllib.parse import parse_qs, quote

from fastapi import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

COOKIE = "bim7d_access"
MAX_AGE = 30 * 24 * 3600
OPEN_PATHS = {"/login", "/logout", "/healthz", "/favicon.ico"}


def password() -> str:
    return os.environ.get("BIM7D_PASSWORD", "")


def enabled() -> bool:
    return bool(password())


def _sign(ts: str) -> str:
    key = hashlib.sha256(("bim7d|" + password()).encode()).digest()
    return hmac.new(key, ts.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    ts = str(int(time.time()))
    return f"{ts}.{_sign(ts)}"


def valid(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    ts, sig = token.split(".", 1)
    if not ts.isdigit() or time.time() - int(ts) > MAX_AGE:
        return False
    return hmac.compare_digest(sig, _sign(ts))


def _safe_next(nxt: str) -> str:
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else "/"


PAGE = """<!doctype html><html lang="el"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>7D-BIM · Είσοδος</title>
<style>
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:#f3f5f8;color:#1d2733}}
.card{{background:#fff;border-radius:14px;box-shadow:0 6px 30px rgba(0,0,0,.08);padding:36px 34px;width:min(380px,90vw)}}
h1{{font-size:20px;margin:0 0 4px}} p{{margin:0 0 22px;color:#5b6775;font-size:14px;line-height:1.45}}
label{{font-size:13px;color:#5b6775}} input{{width:100%;box-sizing:border-box;margin:6px 0 16px;padding:11px 12px;
border:1px solid #cfd6df;border-radius:8px;font-size:15px}}
button{{width:100%;padding:11px;border:0;border-radius:8px;background:#1f5f99;color:#fff;font-size:15px;cursor:pointer}}
.err{{color:#b42318;font-size:13px;margin:-6px 0 14px}} .foot{{margin-top:18px;font-size:12px;color:#8a95a3}}
</style></head><body><form class="card" method="post" action="/login">
<h1>Μοντέλο 7D-BIM · Κηφισιά</h1>
<p>Διπλωματική εργασία «Ανάπτυξη μοντέλου 7D-BIM και ανάλυση κύκλου ζωής κτιριακού έργου».</p>
{err}<label for="pw">Κωδικός πρόσβασης</label>
<input id="pw" name="password" type="password" autofocus autocomplete="current-password">
<input type="hidden" name="next" value="{nxt}">
<button type="submit">Είσοδος</button>
<div class="foot">Η πρώτη φόρτωση μπορεί να διαρκέσει έως ένα λεπτό.</div>
</form></body></html>"""


def login_page(nxt: str = "/", error: bool = False) -> HTMLResponse:
    err = '<div class="err">Λάθος κωδικός.</div>' if error else ""
    return HTMLResponse(PAGE.format(err=err, nxt=html.escape(_safe_next(nxt))), status_code=401 if error else 200)


def install(app) -> None:
    """Register the login routes and the gate middleware on the FastAPI app."""
    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/login")
    def login_get(next: str = "/"):  # noqa: A002
        return login_page(next)

    @app.post("/login")
    async def login_post(request: Request):
        form = parse_qs((await request.body()).decode("utf-8", "replace"))
        pw = (form.get("password") or [""])[0]
        nxt = _safe_next((form.get("next") or ["/"])[0])
        if enabled() and hmac.compare_digest(pw.encode(), password().encode()):
            r = RedirectResponse(nxt, status_code=303)
            r.set_cookie(COOKIE, make_token(), max_age=MAX_AGE, httponly=True, samesite="lax",
                         secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
            return r
        if not enabled():
            return RedirectResponse(nxt, status_code=303)
        time.sleep(1.0)  # slow down guessing
        return login_page(nxt, error=True)

    @app.get("/logout")
    def logout():
        r = RedirectResponse("/login", status_code=303)
        r.delete_cookie(COOKIE)
        return r

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path
        if not enabled() or path in OPEN_PATHS or valid(request.cookies.get(COOKIE)):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Απαιτείται είσοδος με κωδικό."}, status_code=401)
        target = path + (("?" + request.url.query) if request.url.query else "")
        return RedirectResponse("/login?next=" + quote(target, safe=""), status_code=303)
