"""Microsoft Graph, done by hand: the device code sign-in, token refresh, and the handful of calls the board needs
(who am I, my calendars, a calendar's view over a date range, my To Do lists and their tasks).

No SDK and no third-party integration: this is the whole of what Family Board knows about Microsoft, and it is the
same sign-in FamilyHub uses, so the Family Hub app registration serves both. The parsers at the bottom are pure and
tested without Home Assistant."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

import aiohttp

_LOGGER = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["offline_access", "User.Read", "Calendars.Read", "Tasks.ReadWrite"]
REFRESH_MARGIN = 120            # seconds before expiry at which the access token is renewed
PAGE = 100                      # events or tasks per page
COMPLETED_KEEP_DAYS = 30        # completed tasks older than this are left out of a list's items


class GraphError(Exception):
    """Graph or the login service said no, or could not be reached."""


class GraphAuthError(GraphError):
    """The account must sign in again (refresh token revoked, consent withdrawn, sign-in declined or expired)."""


def authority(tenant: str) -> str:
    return f"https://login.microsoftonline.com/{tenant or 'common'}/oauth2/v2.0"


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: float               # epoch seconds
    scope: str = ""

    @classmethod
    def from_response(cls, data: dict[str, Any], previous: Tokens | None = None) -> Tokens:
        return cls(access_token=str(data["access_token"]),
                   refresh_token=str(data.get("refresh_token") or (previous.refresh_token if previous else "")),
                   expires_at=time.time() + float(data.get("expires_in") or 3600), scope=str(data.get("scope") or ""))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Tokens:
        return cls(access_token=str(data.get("access_token") or ""), refresh_token=str(data.get("refresh_token") or ""),
                   expires_at=float(data.get("expires_at") or 0), scope=str(data.get("scope") or ""))

    def to_dict(self) -> dict[str, Any]:
        return {"access_token": self.access_token, "refresh_token": self.refresh_token, "expires_at": self.expires_at,
                "scope": self.scope}

    def expired(self, margin: int = REFRESH_MARGIN) -> bool:
        return time.time() >= self.expires_at - margin


# ---- signing in -------------------------------------------------------------------------------------------------------


async def start_device_login(session: aiohttp.ClientSession, client_id: str, tenant: str = "common") -> dict[str, Any]:
    """Ask for a code to show the person: returns device_code, user_code, verification_uri, expires_in, interval."""
    async with session.post(f"{authority(tenant)}/devicecode", data={"client_id": client_id, "scope": " ".join(SCOPES)}) as resp:
        data = await resp.json(content_type=None)
    if resp.status != 200 or "device_code" not in data:
        raise GraphError(str(data.get("error_description") or data.get("error") or f"HTTP {resp.status}"))
    return data


async def poll_device_login(session: aiohttp.ClientSession, client_id: str, device_code: str, interval: int, expires_in: int,
                            tenant: str = "common") -> Tokens:
    """Wait for the person to finish signing in on their phone. Raises GraphAuthError when they decline or the code expires."""
    wait = max(1, int(interval or 5))
    deadline = time.monotonic() + max(30, int(expires_in or 900))
    while time.monotonic() < deadline:
        await asyncio.sleep(wait)
        async with session.post(f"{authority(tenant)}/token", data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code", "client_id": client_id, "device_code": device_code}) as resp:
            data = await resp.json(content_type=None)
        if resp.status == 200 and "access_token" in data:
            return Tokens.from_response(data)
        error = str(data.get("error") or "")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            wait += 5
            continue
        if error in ("authorization_declined", "expired_token", "bad_verification_code"):
            raise GraphAuthError(error)
        raise GraphError(str(data.get("error_description") or error or f"HTTP {resp.status}"))
    raise GraphAuthError("expired_token")


async def refresh_tokens(session: aiohttp.ClientSession, client_id: str, tokens: Tokens, tenant: str = "common") -> Tokens:
    async with session.post(f"{authority(tenant)}/token", data={
            "grant_type": "refresh_token", "client_id": client_id, "refresh_token": tokens.refresh_token, "scope": " ".join(SCOPES)}) as resp:
        data = await resp.json(content_type=None)
    if resp.status == 200 and "access_token" in data:
        return Tokens.from_response(data, tokens)
    error = str(data.get("error") or "")
    if error in ("invalid_grant", "interaction_required", "invalid_client", "unauthorized_client") or resp.status in (400, 401):
        raise GraphAuthError(str(data.get("error_description") or error))
    raise GraphError(str(data.get("error_description") or error or f"HTTP {resp.status}"))


# ---- the client ------------------------------------------------------------------------------------------------------


class GraphClient:
    """One signed-in Microsoft account. Tokens are renewed as needed and handed back through `on_tokens` to be stored."""

    def __init__(self, session: aiohttp.ClientSession, client_id: str, tokens: Tokens, tenant: str = "common",
                 on_tokens: Callable[[Tokens], Awaitable[None] | None] | None = None) -> None:
        self._session = session
        self.client_id = client_id
        self.tenant = tenant or "common"
        self.tokens = tokens
        self._on_tokens = on_tokens
        self._lock = asyncio.Lock()

    async def _bearer(self, force: bool = False) -> str:
        async with self._lock:
            if force or self.tokens.expired():
                if not self.tokens.refresh_token:
                    raise GraphAuthError("no refresh token")
                self.tokens = await refresh_tokens(self._session, self.client_id, self.tokens, self.tenant)
                if self._on_tokens is not None:
                    result = self._on_tokens(self.tokens)
                    if asyncio.iscoroutine(result):
                        await result
            return self.tokens.access_token

    async def request(self, method: str, url: str, *, params: dict[str, Any] | None = None, json: Any = None,
                      headers: dict[str, str] | None = None, retry: bool = True) -> dict[str, Any] | None:
        if not url.startswith("http"):
            url = f"{GRAPH}{url}"
        hdrs = {"Authorization": f"Bearer {await self._bearer()}", "Accept": "application/json"}
        if headers:
            hdrs.update(headers)
        try:
            async with self._session.request(method, url, params=params, json=json, headers=hdrs, timeout=aiohttp.ClientTimeout(total=40)) as resp:
                if resp.status == 204:
                    return None
                if resp.status == 401 and retry:
                    await self._bearer(force=True)
                    return await self.request(method, url, params=params, json=json, headers=headers, retry=False)
                data = await resp.json(content_type=None) if resp.content_length != 0 else {}
                if resp.status >= 400:
                    err = (data or {}).get("error") or {}
                    message = err.get("message") if isinstance(err, dict) else str(err)
                    if resp.status in (401, 403):
                        raise GraphAuthError(message or f"HTTP {resp.status}")
                    raise GraphError(message or f"HTTP {resp.status}")
                return data or {}
        except aiohttp.ClientError as err:
            raise GraphError(f"Graph unreachable: {err}") from err
        except asyncio.TimeoutError as err:
            raise GraphError("Graph timed out") from err

    async def get_all(self, path: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> list[dict[str, Any]]:
        """Every page of a collection."""
        out: list[dict[str, Any]] = []
        url: str | None = path
        first = True
        while url:
            data = await self.request("GET", url, params=params if first else None, headers=headers) or {}
            out.extend(v for v in data.get("value") or [] if isinstance(v, dict))
            url = data.get("@odata.nextLink")
            first = False
        return out

    # ---- what the board asks for ----

    async def me(self) -> dict[str, Any]:
        return await self.request("GET", "/me", params={"$select": "id,displayName,userPrincipalName,mail"}) or {}

    async def calendars(self) -> list[dict[str, Any]]:
        return await self.get_all("/me/calendars", params={"$select": "id,name,isDefaultCalendar,canEdit,owner,color"})

    async def calendar_view(self, calendar_id: str, start: datetime, end: datetime, tz: str) -> list[dict[str, Any]]:
        """Every occurrence in the range, times in the given IANA zone (all-day events then land on their own dates)."""
        params = {"startDateTime": start.astimezone(timezone.utc).isoformat(), "endDateTime": end.astimezone(timezone.utc).isoformat(),
                  "$top": PAGE, "$orderby": "start/dateTime",
                  "$select": "id,iCalUId,subject,start,end,isAllDay,isCancelled,location,bodyPreview,showAs,sensitivity,categories,seriesMasterId,type,webLink"}
        return await self.get_all(f"/me/calendars/{calendar_id}/calendarView", params=params, headers={"Prefer": f'outlook.timezone="{tz}"'})

    async def todo_lists(self) -> list[dict[str, Any]]:
        return await self.get_all("/me/todo/lists")

    async def tasks(self, list_id: str) -> list[dict[str, Any]]:
        return await self.get_all(f"/me/todo/lists/{list_id}/tasks", params={"$top": PAGE})

    async def create_task(self, list_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", f"/me/todo/lists/{list_id}/tasks", json=body) or {}

    async def update_task(self, list_id: str, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self.request("PATCH", f"/me/todo/lists/{list_id}/tasks/{task_id}", json=body) or {}

    async def delete_task(self, list_id: str, task_id: str) -> None:
        await self.request("DELETE", f"/me/todo/lists/{list_id}/tasks/{task_id}")


# ---- parsing what Graph returns (pure) --------------------------------------------------------------------------------

WINDOWS_ZONES = {   # the handful Graph is likely to answer with for this family when it will not echo an IANA name
    "GMT Standard Time": "Europe/London", "W. Europe Standard Time": "Europe/Berlin", "Central European Standard Time": "Europe/Warsaw",
    "Romance Standard Time": "Europe/Paris", "UTC": "UTC", "FLE Standard Time": "Europe/Helsinki",
    "Pacific Standard Time": "America/Los_Angeles", "Eastern Standard Time": "America/New_York",
}


def zone_of(name: str | None, fallback: ZoneInfo) -> ZoneInfo:
    if not name:
        return fallback
    if name.upper() == "UTC":
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001  (not an IANA name)
        mapped = WINDOWS_ZONES.get(name)
        if mapped:
            return ZoneInfo(mapped)
        return fallback


def graph_datetime(value: dict[str, Any] | None, fallback: ZoneInfo) -> datetime | None:
    """A dateTimeTimeZone ({dateTime, timeZone}) as an aware datetime."""
    if not isinstance(value, dict) or not value.get("dateTime"):
        return None
    text = str(value["dateTime"])
    if "." in text:                                         # Graph writes seven fractional digits; Python reads six
        head, frac = text.split(".", 1)
        text = f"{head}.{frac[:6]}" if frac[:6].isdigit() else head
    text = text.rstrip("Z")
    try:
        naive = datetime.fromisoformat(text)
    except ValueError:
        return None
    if naive.tzinfo is not None:
        return naive
    return naive.replace(tzinfo=zone_of(value.get("timeZone"), fallback))


def parse_event(raw: dict[str, Any], tz: ZoneInfo) -> dict[str, Any] | None:
    """A Graph event as the shape Home Assistant's CalendarEvent takes: start/end are dates for an all-day event and
    aware datetimes otherwise. Cancelled events are dropped."""
    if not isinstance(raw, dict) or raw.get("isCancelled"):
        return None
    start = graph_datetime(raw.get("start"), tz)
    end = graph_datetime(raw.get("end"), tz)
    if start is None:
        return None
    if end is None or end < start:
        end = start
    all_day = bool(raw.get("isAllDay"))
    summary = str(raw.get("subject") or "").strip() or "(untitled)"
    if raw.get("sensitivity") == "private" and raw.get("showAs") in ("busy", "oof", "tentative"):
        summary = str(raw.get("subject") or "").strip() or "Private"
    location = (raw.get("location") or {}).get("displayName") if isinstance(raw.get("location"), dict) else None
    out: dict[str, Any] = {
        "uid": str(raw.get("iCalUId") or raw.get("id") or ""),
        "summary": summary,
        "description": (raw.get("bodyPreview") or "").strip() or None,
        "location": (location or "").strip() or None,
        "all_day": all_day,
        "categories": [str(c) for c in raw.get("categories") or []],
        "show_as": raw.get("showAs"),
        "web_link": raw.get("webLink"),
    }
    if all_day:
        out["start"] = start.date()
        out["end"] = end.date() if end.date() > start.date() else start.date() + timedelta(days=1)
    else:
        out["start"] = start
        out["end"] = end if end > start else start + timedelta(minutes=30)
    return out


def parse_task(raw: dict[str, Any], tz: ZoneInfo, now: datetime | None = None) -> dict[str, Any] | None:
    """A Graph todoTask as a Home Assistant to-do item (uid, summary, status, due, description), plus when it was
    completed. Tasks completed more than COMPLETED_KEEP_DAYS ago are left out."""
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    status = str(raw.get("status") or "notStarted")
    done = status == "completed"
    completed = graph_datetime(raw.get("completedDateTime"), tz)
    if done and completed is not None:
        reference = now or datetime.now(tz)
        if reference - completed > timedelta(days=COMPLETED_KEEP_DAYS):
            return None
    due = graph_datetime(raw.get("dueDateTime"), tz)
    body = raw.get("body") if isinstance(raw.get("body"), dict) else {}
    description = str(body.get("content") or "").strip() if body.get("contentType") in (None, "text") else None
    return {
        "uid": str(raw["id"]),
        "summary": str(raw.get("title") or "").strip() or "(untitled)",
        "status": "completed" if done else "needs_action",
        "due": due.date() if due else None,
        "description": description or None,
        "completed": completed.isoformat() if completed else None,
        "importance": raw.get("importance"),
        "recurring": bool(raw.get("recurrence")),
    }


def task_body(summary: str | None = None, status: str | None = None, due: date | datetime | None = None,
              description: str | None = None, clear_due: bool = False) -> dict[str, Any]:
    """What to PATCH or POST for a change made in Home Assistant."""
    body: dict[str, Any] = {}
    if summary is not None:
        body["title"] = summary
    if status is not None:
        body["status"] = "completed" if status == "completed" else "notStarted"
    if due is not None:
        when = due if isinstance(due, datetime) else datetime.combine(due, datetime.min.time())
        body["dueDateTime"] = {"dateTime": when.replace(tzinfo=None).isoformat(), "timeZone": "UTC"}
    elif clear_due:
        body["dueDateTime"] = None
    if description is not None:
        body["body"] = {"content": description, "contentType": "text"}
    return body
