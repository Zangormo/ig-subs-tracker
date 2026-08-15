#!/usr/bin/env python3
"""Fetch an Instagram account's followers and following, then categorize them.

Buckets are mutually exclusive:
    friends        - mutual: they follow you and you follow them
    subscribers    - they follow you, you do not follow back
    subscriptions  - you follow them, they do not follow back

Results are written as JSON into a per-run folder named
<output.directory>/<account>_<YYYY-MM-DD_HH-MM-SS> (UTC).

Usage:
    python tracker.py [--config config.json] [--output-dir output] [--fresh-login]
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from instagrapi import Client
    from instagrapi.exceptions import (
        BadPassword,
        ChallengeRequired,
        LoginRequired,
        PleaseWaitFewMinutes,
        TwoFactorRequired,
    )
except ImportError:
    sys.exit("instagrapi is not installed. Run: pip install -r requirements.txt")


DEFAULT_CONFIG = "config.json"


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #

def load_config(path):
    config_path = Path(path)
    if not config_path.exists():
        sys.exit(
            f"Config file not found: {config_path}\n"
            "Copy config.example.json to config.json and fill in your credentials."
        )

    with config_path.open(encoding="utf-8") as fh:
        try:
            config = json.load(fh)
        except json.JSONDecodeError as exc:
            sys.exit(f"Config file is not valid JSON: {exc}")

    account = config.get("instagram") or {}
    if not account.get("username") or not account.get("password"):
        sys.exit(
            f"Fill in instagram.username and instagram.password in {config_path}."
        )

    return config


# --------------------------------------------------------------------------- #
# login
# --------------------------------------------------------------------------- #

def build_client(config):
    client = Client()

    delay = config.get("request_delay") or [1, 3]
    client.delay_range = [int(delay[0]), int(delay[1])]

    proxy = config.get("proxy")
    if proxy:
        client.set_proxy(proxy)

    return client


def login(client, config, fresh_login=False):
    account = config["instagram"]
    username = account["username"]
    password = account["password"]
    session_file = Path(account.get("session_file") or "session.json")

    # A cached session avoids a fresh login (and the challenges that come with
    # it) on every run. Instagram flags accounts that log in repeatedly.
    if session_file.exists() and not fresh_login:
        try:
            client.load_settings(session_file)
            client.login(username, password)
            client.get_timeline_feed()  # cheap call that proves the session works
            print(f"Reused session from {session_file}")
            return
        except (LoginRequired, ChallengeRequired, json.JSONDecodeError) as exc:
            print(f"Cached session unusable ({type(exc).__name__}), logging in fresh.")
            client.set_settings({})

    verification_code = (account.get("verification_code") or "").strip()
    try:
        client.login(username, password, verification_code=verification_code)
    except TwoFactorRequired:
        code = input("Two-factor code: ").strip()
        client.login(username, password, verification_code=code)
    except BadPassword:
        sys.exit("Instagram rejected the password in your config.")
    except ChallengeRequired:
        sys.exit(
            "Instagram issued a challenge. Open the Instagram app, approve the "
            "login attempt, then run this script again."
        )
    except PleaseWaitFewMinutes:
        sys.exit("Instagram is rate limiting this account. Try again later.")

    client.dump_settings(session_file)
    print(f"Logged in as {username}, session saved to {session_file}")


# --------------------------------------------------------------------------- #
# fetching
# --------------------------------------------------------------------------- #

def to_record(user):
    """Flatten an instagrapi UserShort into a plain dict."""
    return {
        "pk": str(user.pk),
        "username": user.username,
        "full_name": user.full_name or "",
        "is_private": bool(getattr(user, "is_private", False)),
        "is_verified": bool(getattr(user, "is_verified", False)),
        "profile_url": f"https://www.instagram.com/{user.username}/",
    }


def fetch_relations(client, user_id):
    print("Fetching followers ...")
    followers = client.user_followers(user_id, amount=0)
    print(f"  {len(followers)} followers")

    time.sleep(2)  # small breather between two heavy paginated calls

    print("Fetching following ...")
    following = client.user_following(user_id, amount=0)
    print(f"  {len(following)} following")

    followers = {str(pk): to_record(user) for pk, user in followers.items()}
    following = {str(pk): to_record(user) for pk, user in following.items()}
    return followers, following


# --------------------------------------------------------------------------- #
# categorizing
# --------------------------------------------------------------------------- #

def categorize(followers, following):
    follower_ids = set(followers)
    following_ids = set(following)

    def sort_users(records):
        return sorted(records, key=lambda record: record["username"].lower())

    mutual_ids = follower_ids & following_ids

    return {
        "friends": sort_users(followers[pk] for pk in mutual_ids),
        "subscribers": sort_users(
            followers[pk] for pk in follower_ids - following_ids
        ),
        "subscriptions": sort_users(
            following[pk] for pk in following_ids - follower_ids
        ),
        "all_followers": sort_users(followers.values()),
        "all_following": sort_users(following.values()),
    }


# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #

def save_results(config, target_username, buckets):
    output = config.get("output") or {}

    # Every run gets its own dated folder, so results are never overwritten.
    fetched_at = datetime.now(timezone.utc)
    stamp = fetched_at.strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = Path(output.get("directory") or "output") / f"{target_username}_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "account": target_username,
        "fetched_at": fetched_at.isoformat(),
        "counts": {name: len(records) for name, records in buckets.items()},
        **buckets,
    }

    written = [_write_json(output_dir / "report.json", report)]
    for name in ("friends", "subscribers", "subscriptions"):
        written.append(_write_json(output_dir / f"{name}.json", buckets[name]))

    return report, written


def _write_json(path, payload):
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return path


def print_summary(report, written):
    counts = report["counts"]
    print()
    print(f"Account:       {report['account']}")
    print(f"Followers:     {counts['all_followers']}")
    print(f"Following:     {counts['all_following']}")
    print("-" * 32)
    print(f"Friends:       {counts['friends']}       (mutual)")
    print(f"Subscribers:   {counts['subscribers']}       (follow you, no follow back)")
    print(f"Subscriptions: {counts['subscriptions']}       (you follow, no follow back)")
    print()
    for path in written:
        print(f"Saved {path}")


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def parse_args():
    parser = argparse.ArgumentParser(
        description="Categorize Instagram followers and following."
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="path to config file")
    parser.add_argument("--output-dir", help="override output.directory from config")
    parser.add_argument(
        "--fresh-login",
        action="store_true",
        help="ignore the cached session and log in from scratch",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config(args.config)

    if args.output_dir:
        config.setdefault("output", {})["directory"] = args.output_dir

    client = build_client(config)
    login(client, config, fresh_login=args.fresh_login)

    target_username = (config.get("target_username") or "").strip()
    if not target_username:
        target_username = config["instagram"]["username"]

    user_id = client.user_id_from_username(target_username)
    followers, following = fetch_relations(client, user_id)

    buckets = categorize(followers, following)
    report, written = save_results(config, target_username, buckets)
    print_summary(report, written)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")
