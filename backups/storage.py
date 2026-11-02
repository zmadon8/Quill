"""Off-site copies of backups.

A tiny storage interface (put / list / get / delete) with two implementations:

* ``NoOpStorage``: the default. Does nothing, so an unconfigured app behaves exactly as before.
* ``S3CompatibleStorage``: talks to any S3-compatible service (Backblaze B2, Cloudflare R2, ...)
  using only the standard library (AWS Signature Version 4 over urllib). No boto3.

Configuration comes only from environment variables (see ``docs/HOSTING_AND_DEPLOY.md``).
Secrets are never logged, never stored in the database and never put in error messages.
"""

import datetime
import hashlib
import hmac
import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

ENV_ENDPOINT = "OFFSITE_BACKUP_ENDPOINT"
ENV_BUCKET = "OFFSITE_BACKUP_BUCKET"
ENV_KEY_ID = "OFFSITE_BACKUP_ACCESS_KEY_ID"
ENV_SECRET = "OFFSITE_BACKUP_SECRET_ACCESS_KEY"
ENV_REGION = "OFFSITE_BACKUP_REGION"
ENV_PREFIX = "OFFSITE_BACKUP_PREFIX"

TIMEOUT_SECONDS = 60


class StorageError(Exception):
    """An off-site storage problem. The message is safe to show and to log (it never holds secrets)."""


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    last_modified: datetime.datetime  # timezone-aware, UTC


class NoOpStorage:
    """Used when off-site backup is not set up."""

    configured = False
    destination = ""

    def put(self, key, data):
        return None

    def list(self):
        return []

    def get(self, key):
        raise StorageError("Off-site backup is not set up.")

    def delete(self, key):
        return None


# ---- AWS Signature Version 4 (pure functions, easy to test against published vectors) ----


def _hmac(key, message):
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def signing_key(secret, date_stamp, region, service="s3"):
    k_date = _hmac(("AWS4" + secret).encode("utf-8"), date_stamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    return _hmac(k_service, "aws4_request")


def canonical_request(method, path, query, headers, signed_headers, payload_hash):
    """``query`` is a list of (name, value) pairs; ``headers`` a dict of lower-case names."""
    canonical_query = "&".join(
        f"{urllib.parse.quote(k, safe='-_.~')}={urllib.parse.quote(v, safe='-_.~')}" for k, v in sorted(query)
    )
    canonical_headers = "".join(f"{name}:{' '.join(headers[name].split())}\n" for name in signed_headers)
    return "\n".join([method, path, canonical_query, canonical_headers, ";".join(signed_headers), payload_hash])


def string_to_sign(amz_date, scope, canonical):
    return "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode("utf-8")).hexdigest()])


def signature(secret, date_stamp, region, service, to_sign):
    key = signing_key(secret, date_stamp, region, service)
    return hmac.new(key, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()


class S3CompatibleStorage:
    """Path-style requests: ``https://endpoint/bucket/prefix/name``."""

    configured = True

    def __init__(self, endpoint, bucket, access_key_id, secret_access_key, region="auto", prefix=""):
        self.endpoint = endpoint.rstrip("/")
        if not self.endpoint.startswith("https://"):
            raise StorageError("The off-site backup address must start with https://")
        self.bucket = bucket
        self.access_key_id = access_key_id
        self._secret = secret_access_key
        self.region = region or "auto"
        self.prefix = prefix.strip("/")
        self.host = urllib.parse.urlsplit(self.endpoint).netloc

    def __repr__(self):  # never show the secret
        return f"S3CompatibleStorage({self.destination})"

    @property
    def destination(self):
        return f"{self.host}/{self.bucket}" + (f"/{self.prefix}" if self.prefix else "")

    def _full_key(self, key):
        return f"{self.prefix}/{key}" if self.prefix else key

    def _request(self, method, key="", query=(), body=b"", now=None):
        now = now or datetime.datetime.now(datetime.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        path = "/" + urllib.parse.quote(self.bucket, safe="-_.~") + ("/" + urllib.parse.quote(key, safe="-_.~/") if key else "")
        payload_hash = hashlib.sha256(body).hexdigest()
        headers = {"host": self.host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
        signed = sorted(headers)
        scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        canonical = canonical_request(method, path, list(query), headers, signed, payload_hash)
        sig = signature(self._secret, date_stamp, self.region, "s3", string_to_sign(amz_date, scope, canonical))
        auth = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key_id}/{scope}, "
            f"SignedHeaders={';'.join(signed)}, Signature={sig}"
        )
        url = self.endpoint + path
        if query:
            url += "?" + "&".join(f"{urllib.parse.quote(k, safe='-_.~')}={urllib.parse.quote(v, safe='-_.~')}" for k, v in sorted(query))
        request = urllib.request.Request(url, data=body if method == "PUT" else None, method=method)
        for name, value in headers.items():
            if name != "host":
                request.add_header(name, value)
        request.add_header("Authorization", auth)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise StorageError(f"The storage service refused the request (HTTP {exc.code}).") from None
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise StorageError(f"Could not reach the storage service ({reason.__class__.__name__}).") from None

    def put(self, key, data):
        self._request("PUT", self._full_key(key), body=data)

    def get(self, key):
        return self._request("GET", self._full_key(key))

    def delete(self, key):
        self._request("DELETE", self._full_key(key))

    def list(self):
        found = []
        token = None
        while True:
            query = [("list-type", "2")]
            if self.prefix:
                query.append(("prefix", self.prefix + "/"))
            if token:
                query.append(("continuation-token", token))
            root = ET.fromstring(self._request("GET", "", query))
            ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
            for item in root.findall(f"{ns}Contents"):
                full = item.findtext(f"{ns}Key") or ""
                stamp = (item.findtext(f"{ns}LastModified") or "").replace("Z", "+00:00")
                try:
                    modified = datetime.datetime.fromisoformat(stamp)
                except ValueError:
                    continue
                if modified.tzinfo is None:
                    modified = modified.replace(tzinfo=datetime.timezone.utc)
                name = full[len(self.prefix) + 1 :] if self.prefix else full
                found.append(StoredObject(name, int(item.findtext(f"{ns}Size") or 0), modified))
            if (root.findtext(f"{ns}IsTruncated") or "").lower() == "true":
                token = root.findtext(f"{ns}NextContinuationToken")
                if not token:
                    break
            else:
                break
        return found


def get_storage(environ=None):
    """The storage chosen by environment variables; NoOpStorage unless all required ones are set."""
    env = os.environ if environ is None else environ
    endpoint, bucket = env.get(ENV_ENDPOINT, "").strip(), env.get(ENV_BUCKET, "").strip()
    key_id, secret = env.get(ENV_KEY_ID, "").strip(), env.get(ENV_SECRET, "").strip()
    if not (endpoint and bucket and key_id and secret):
        return NoOpStorage()
    return S3CompatibleStorage(endpoint, bucket, key_id, secret, env.get(ENV_REGION, "").strip() or "auto", env.get(ENV_PREFIX, "").strip())
