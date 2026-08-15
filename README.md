# ig-subs-tracker

Pulls the followers and following lists of an Instagram account and splits them
into three mutually exclusive buckets:

| Bucket          | Meaning                                        |
| --------------- | ---------------------------------------------- |
| `friends`       | mutual — they follow you and you follow them   |
| `subscribers`   | they follow you, you do not follow them back   |
| `subscriptions` | you follow them, they do not follow you back   |

The full raw lists are kept too, as `all_followers` and `all_following`.

## Setup

```bash
pip install -r requirements.txt
cp config.example.json config.json
```

Fill in `config.json`:

| Key                          | Description                                                             |
| ---------------------------- | ----------------------------------------------------------------------- |
| `instagram.username`         | your Instagram login                                                    |
| `instagram.password`         | your Instagram password                                                 |
| `instagram.verification_code`| current 2FA code, if your account uses an authenticator app (optional)   |
| `instagram.session_file`     | where the logged-in session is cached, so you don't log in every run     |
| `target_username`            | account to scan; leave empty to use your own                            |
| `proxy`                      | optional, e.g. `http://user:pass@host:port`                             |
| `request_delay`              | `[min, max]` seconds of random delay between API requests               |
| `output.directory`           | parent folder the per-run result folders are created in                 |

`config.json` and `session.json` are gitignored — only `config.example.json` is
meant to be committed.

## Run

```bash
python tracker.py
python tracker.py --config other.json --output-dir results --fresh-login
```

## Output

Every run creates its own folder, stamped with the UTC date and time it started:

```
output/
└── someaccount_2026-08-15_16-42-07/
    ├── report.json         everything: account, fetched_at, counts, all buckets
    ├── friends.json
    ├── subscribers.json
    └── subscriptions.json
```

Nothing is ever overwritten, so runs can be diffed against each other. Each of
the per-bucket files is a JSON array of user records:

```json
[
  {
    "pk": "1234567890",
    "username": "someone",
    "full_name": "Some One",
    "is_private": false,
    "is_verified": false,
    "profile_url": "https://www.instagram.com/someone/"
  }
]
```

## Notes

- Instagram rate limits aggressively. The session cache exists so that repeated
  runs don't trigger a fresh login each time; use `--fresh-login` only when the
  cached session breaks.
- A large following/follower list takes a while, since it is paginated.
- If Instagram issues a login challenge, approve the attempt in the Instagram
  app and re-run.
- You can only list followers/following of your own account or a public one.
