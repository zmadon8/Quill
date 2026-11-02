import datetime
import unittest

from backups import storage

SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"  # the public example secret from the AWS documentation
EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class SigV4VectorTests(unittest.TestCase):
    def test_signing_key_matches_aws_documented_value(self):
        key = storage.signing_key(SECRET, "20150830", "us-east-1", "iam")
        self.assertEqual(key.hex(), "c4afb1cc5771d871763a393e44b703571b55cc28424d1a5e86da6ed3c154a4b9")

    def test_signature_matches_aws_documented_example(self):
        headers = {
            "content-type": "application/x-www-form-urlencoded; charset=utf-8",
            "host": "iam.amazonaws.com",
            "x-amz-date": "20150830T123600Z",
        }
        canonical = storage.canonical_request(
            "GET", "/", [("Action", "ListUsers"), ("Version", "2010-05-08")], headers, sorted(headers), EMPTY_SHA
        )
        to_sign = storage.string_to_sign("20150830T123600Z", "20150830/us-east-1/iam/aws4_request", canonical)
        self.assertEqual(
            storage.signature(SECRET, "20150830", "us-east-1", "iam", to_sign),
            "5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7",
        )


class GetStorageTests(unittest.TestCase):
    def test_unconfigured_is_noop(self):
        chosen = storage.get_storage({})
        self.assertIsInstance(chosen, storage.NoOpStorage)
        self.assertFalse(chosen.configured)
        self.assertIsNone(chosen.put("a", b"x"))
        self.assertEqual(chosen.list(), [])

    def test_partly_configured_is_noop(self):
        self.assertIsInstance(storage.get_storage({storage.ENV_BUCKET: "b"}), storage.NoOpStorage)

    def test_configured_and_secret_not_in_repr(self):
        env = {
            storage.ENV_ENDPOINT: "https://example.invalid",
            storage.ENV_BUCKET: "bucket",
            storage.ENV_KEY_ID: "KEYID",
            storage.ENV_SECRET: "supersecretvalue",
        }
        chosen = storage.get_storage(env)
        self.assertTrue(chosen.configured)
        self.assertNotIn("supersecretvalue", repr(chosen))
        self.assertEqual(chosen.destination, "example.invalid/bucket")

    def test_plain_http_refused(self):
        with self.assertRaises(storage.StorageError):
            storage.S3CompatibleStorage("http://example.invalid", "b", "k", "s")


class FakeResponseListTests(unittest.TestCase):
    def test_list_parses_objects_and_strips_prefix(self):
        xml = (
            '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated>'
            "<Contents><Key>jd/one.json.gz</Key><LastModified>2026-01-02T03:04:05.000Z</LastModified><Size>12</Size></Contents>"
            "</ListBucketResult>"
        )
        s3 = storage.S3CompatibleStorage("https://example.invalid", "b", "k", "s", prefix="jd")
        s3._request = lambda *a, **kw: xml.encode()
        [obj] = s3.list()
        self.assertEqual((obj.key, obj.size), ("one.json.gz", 12))
        self.assertEqual(obj.last_modified, datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc))


if __name__ == "__main__":
    unittest.main()
