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
| `output.directory`           | where results are written                                               |
| `output.write_csv`           | also write `friends.csv` / `subscribers.csv` / `subscriptions.csv`      |
| `output.timestamped`         | put each run in its own dated subfolder                                 |

`config.json` and `session.json` are gitignored — only `config.example.json` is
meant to be committed.

## Run

```bash
python tracker.py
python tracker.py --config other.json --output-dir results --fresh-login
```

Results land in `output/report.json` plus the CSV files.

## Notes

- Instagram rate limits aggressively. The session cache exists so that repeated
  runs don't trigger a fresh login each time; use `--fresh-login` only when the
  cached session breaks.
- A large following/follower list takes a while, since it is paginated.
- If Instagram issues a login challenge, approve the attempt in the Instagram
  app and re-run.
- You can only list followers/following of your own account or a public one.
