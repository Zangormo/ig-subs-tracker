#!/usr/bin/env python3
"""Compare two tracker.py runs and report what changed between them.

Buckets describe the move from the older run to the newer one:
    new_subscribers    - started following you
    lost_subscribers   - stopped following you (they unsubscribed)
    new_subscriptions  - accounts you started following
    lost_subscriptions - accounts you stopped following (you unsubscribed)
    new_friends        - became mutual since the older run
    lost_friends       - were mutual, no longer are
    renamed            - same account (same pk), different username

Users are matched by pk, not username, so a rename is not mistaken for one
account leaving and another arriving.

Results are written as JSON into
    <output.directory>/diff_<account>_<old-stamp>__<new-stamp>
using the same record format tracker.py writes.

Usage:
    python analyzer.py                       # two most recent runs
    python analyzer.py --old DIR --new DIR   # specific run folders
    python analyzer.py --account zangormo    # only runs of one account
    python analyzer.py --list                # show available runs
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_CONFIG = "config.json"

# tracker.py names each run folder <account>_<YYYY-MM-DD_HH-MM-SS>.
RUN_DIR_RE = re.compile(
    r"^(?P<account>.+)_(?P<stamp>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})$"
)

# This script's own folders sit next to the runs and end in a stamp too, so
# they would otherwise be mistaken for runs.
DIFF_PREFIX = "diff_"

BUCKETS = (
    "new_subscribers",
    "lost_subscribers",
    "new_subscriptions",
    "lost_subscriptions",
    "new_friends",
    "lost_friends",
    "renamed",
)


# --------------------------------------------------------------------------- #
# locating runs
# --------------------------------------------------------------------------- #

def output_directory(config_path, override):
    if override:
        return Path(override)

    config_file = Path(config_path)
    if config_file.exists():
        with config_file.open(encoding="utf-8") as fh:
            try:
                config = json.load(fh)
            except json.JSONDecodeError as exc:
                sys.exit(f"Config file is not valid JSON: {exc}")
        return Path((config.get("output") or {}).get("directory") or "output")

    return Path("output")


def list_runs(output_dir, account=None):
    """Return (stamp, account, path) for every run folder, oldest first."""
    if not output_dir.is_dir():
        sys.exit(f"Output directory not found: {output_dir}")

    runs = []
    for path in output_dir.iterdir():
        if not path.is_dir() or path.name.startswith(DIFF_PREFIX):
            continue
        match = RUN_DIR_RE.match(path.name)
        if not match:
            continue  # anything else that ended up in the output directory
        if account and match.group("account") != account:
            continue
        runs.append((match.group("stamp"), match.group("account"), path))

    runs.sort(key=lambda run: run[0])
    return runs


def pick_runs(output_dir, account):
    runs = list_runs(output_dir, account)
    if len(runs) < 2:
        scope = f" for account {account}" if account else ""
        sys.exit(
            f"Need at least two runs{scope} in {output_dir} to compare, "
            f"found {len(runs)}.\n"
            "Run tracker.py again, or pass --old and --new explicitly."
        )
    return runs[-2][2], runs[-1][2]


def run_label(path):
    """The (account, stamp) pair for a run folder, best effort."""
    match = RUN_DIR_RE.match(path.name)
    if match:
        return match.group("account"), match.group("stamp")
    return path.name, path.name


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #

def load_run(path):
    """Read one run folder into (followers, following, fetched_at)."""
    if not path.is_dir():
        sys.exit(f"Run folder not found: {path}")

    report_file = path / "report.json"
    if report_file.exists():
        report = _read_json(report_file)
        followers = report.get("all_followers")
        following = report.get("all_following")
        if followers is not None and following is not None:
            return _index(followers), _index(following), report.get("fetched_at")

        # Older reports only carried the three exclusive buckets.
        friends = report.get("friends") or []
        return (
            _index(friends + (report.get("subscribers") or [])),
            _index(friends + (report.get("subscriptions") or [])),
            report.get("fetched_at"),
        )

    # No report.json: rebuild the two sets from the per-bucket files.
    friends = _read_json(path / "friends.json")
    subscribers = _read_json(path / "subscribers.json")
    subscriptions = _read_json(path / "subscriptions.json")
    return _index(friends + subscribers), _index(friends + subscriptions), None


def _read_json(path):
    if not path.exists():
        sys.exit(f"Expected file is missing: {path}")
    with path.open(encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError as exc:
            sys.exit(f"{path} is not valid JSON: {exc}")


def _index(records):
    return {str(record["pk"]): record for record in records}


# --------------------------------------------------------------------------- #
# comparing
# --------------------------------------------------------------------------- #

def sort_users(records):
    return sorted(records, key=lambda record: record["username"].lower())


def compare(old_followers, old_following, new_followers, new_following):
    gained_followers = set(new_followers) - set(old_followers)
    lost_followers = set(old_followers) - set(new_followers)
    gained_following = set(new_following) - set(old_following)
    lost_following = set(old_following) - set(new_following)

    old_friends = set(old_followers) & set(old_following)
    new_friends = set(new_followers) & set(new_following)

    # Accounts that vanished only have a record in the old run.
    old_records = {**old_followers, **old_following}
    new_records = {**new_followers, **new_following}

    def gone(pks):
        return sort_users(old_records[pk] for pk in pks)

    def here(pks):
        return sort_users(new_records[pk] for pk in pks)

    return {
        "new_subscribers": here(gained_followers),
        "lost_subscribers": gone(lost_followers),
        "new_subscriptions": here(gained_following),
        "lost_subscriptions": gone(lost_following),
        "new_friends": here(new_friends - old_friends),
        "lost_friends": gone(old_friends - new_friends),
        "renamed": find_renames(old_records, new_records),
    }


def find_renames(old_records, new_records):
    """Accounts present in both runs whose username changed."""
    renames = []
    for pk, new_record in new_records.items():
        old_record = old_records.get(pk)
        if old_record and old_record["username"] != new_record["username"]:
            renames.append({**new_record, "previous_username": old_record["username"]})
    return sort_users(renames)


# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #

def save_results(output_dir, account, old_path, new_path, old_meta, new_meta, buckets):
    old_stamp = run_label(old_path)[1]
    new_stamp = run_label(new_path)[1]

    diff_dir = output_dir / f"diff_{account}_{old_stamp}__{new_stamp}"
    diff_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "account": account,
        "compared_at": datetime.now(timezone.utc).isoformat(),
        "old_run": {"directory": str(old_path), **old_meta},
        "new_run": {"directory": str(new_path), **new_meta},
        "counts": {name: len(buckets[name]) for name in BUCKETS},
        **{name: buckets[name] for name in BUCKETS},
    }

    written = [_write_json(diff_dir / "report.json", report)]
    for name in BUCKETS:
        written.append(_write_json(diff_dir / f"{name}.json", buckets[name]))

    return report, written


def _write_json(path, payload):
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return path


def print_summary(report, written):
    counts = report["counts"]
    old_run = report["old_run"]
    new_run = report["new_run"]

    print()
    print(f"Account: {report['account']}")
    print(
        f"  from {old_run['fetched_at'] or old_run['directory']}"
        f"  ({old_run['followers']} followers, {old_run['following']} following)"
    )
    print(
        f"  to   {new_run['fetched_at'] or new_run['directory']}"
        f"  ({new_run['followers']} followers, {new_run['following']} following)"
    )
    print("-" * 60)
    print(f"New subscribers:    +{counts['new_subscribers']}   (started following you)")
    print(f"Lost subscribers:   -{counts['lost_subscribers']}   (unfollowed you)")
    print(f"New subscriptions:  +{counts['new_subscriptions']}   (you started following)")
    print(f"Lost subscriptions: -{counts['lost_subscriptions']}   (you unfollowed)")
    print(f"New friends:        +{counts['new_friends']}   (became mutual)")
    print(f"Lost friends:       -{counts['lost_friends']}   (no longer mutual)")
    print(f"Renamed:             {counts['renamed']}   (same account, new username)")

    for name in BUCKETS:
        records = report[name]
        if not records:
            continue
        print()
        print(f"{name}:")
        for record in records:
            if name == "renamed":
                suffix = f"  (was @{record['previous_username']})"
            elif record["full_name"]:
                suffix = f"  ({record['full_name']})"
            else:
                suffix = ""
            print(f"  @{record['username']}{suffix}")

    print()
    for path in written:
        print(f"Saved {path}")


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare two tracker.py runs and report follower changes."
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="path to config file")
    parser.add_argument("--output-dir", help="override output.directory from config")
    parser.add_argument("--old", help="older run folder (default: second newest run)")
    parser.add_argument("--new", help="newer run folder (default: newest run)")
    parser.add_argument("--account", help="only consider runs for this account")
    parser.add_argument(
        "--list",
        action="store_true",
        help="list the available run folders and exit",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    output_dir = output_directory(args.config, args.output_dir)

    if args.list:
        runs = list_runs(output_dir, args.account)
        if not runs:
            sys.exit(f"No run folders found in {output_dir}.")
        for stamp, account, path in runs:
            print(f"{stamp}  {account}  {path}")
        return

    if bool(args.old) != bool(args.new):
        sys.exit("Pass both --old and --new, or neither.")

    if args.old:
        old_path, new_path = Path(args.old), Path(args.new)
    else:
        old_path, new_path = pick_runs(output_dir, args.account)

    old_followers, old_following, old_fetched = load_run(old_path)
    new_followers, new_following, new_fetched = load_run(new_path)

    account = args.account or run_label(new_path)[0]
    buckets = compare(old_followers, old_following, new_followers, new_following)

    report, written = save_results(
        output_dir,
        account,
        old_path,
        new_path,
        {
            "fetched_at": old_fetched,
            "followers": len(old_followers),
            "following": len(old_following),
        },
        {
            "fetched_at": new_fetched,
            "followers": len(new_followers),
            "following": len(new_following),
        },
        buckets,
    )
    print_summary(report, written)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")
