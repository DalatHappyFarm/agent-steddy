"""The learning loop: rule keys in the lessons file and the repeat notice.

A lessons entry has a Rule line, `- Rule [commit-by-path]: <text>`; the key, a lowercase slug, names the rule so that the same rule recorded again is counted and not read twice.
A rule seen THRESHOLD times and not promoted is due; a promoted rule's lines end with ` [promoted -> <path>]`.
Every function takes the paths it works on, so the tests call them directly.
Reading is plain file reads and no git.
"""
import collections
import difflib
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
from local_state import Refuse  # noqa: E402

THRESHOLD = 2  # "seen a second time" in the gates skill
MAX_KEY = 40
ALIKE = 0.45  # similarity from which two texts look alike: on sample pairs paraphrases of one rule scored 0.43 to 0.9, unrelated rules 0.15 to 0.25 and different rules in one sentence frame up to 0.8; a crude measure, so the report only proposes
SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
STOP_WORDS = {"a", "an", "the", "to", "of", "and", "or", "is", "are", "be", "it", "in", "on", "for", "with", "that", "this", "you", "your", "when", "do", "does"}

HEADING = re.compile(r"## (\S+) - (.*?)(?: - roles: (.*))?")
RULE = re.compile(r"- Rule(?: \[(%s)\])?: ?(.*)" % SLUG)
MARK = re.compile(r"(.*) \[promoted -> ([^\]]+)\]")

# the entry's date, its task, its roles, its key (None on an old line), the rule text without the marker, the marker's path (None), and the index of the Rule line
Entry = collections.namedtuple("Entry", "date task roles key rule promoted line")


def is_none(rule):
    return rule.strip().lower() == "none"


def plural(count, word="time"):
    return f"{count} {word}{'' if count == 1 else 's'}"


def headings(lines):
    """The indexes of the `## ` headings that are not inside a code fence."""
    fenced, found = False, []
    for index, line in enumerate(lines):
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith("## "):
            found.append(index)
    return found


def parse(text):
    """The entries of a lessons file that have a Rule line, in file order (newest first when the commands wrote it)."""
    lines = text.split("\n")
    marks = headings(lines)
    entries = []
    for number, start in enumerate(marks):
        head = HEADING.fullmatch(lines[start].rstrip())
        end = marks[number + 1] if number + 1 < len(marks) else len(lines)
        for index in range(start + 1, end if head else start):
            rule = RULE.fullmatch(lines[index].rstrip())
            if rule:
                body, promoted = rule.group(2), None
                done = MARK.fullmatch(body)
                if done:
                    body, promoted = done.groups()
                roles = [role.strip() for role in (head.group(3) or "").split(",") if role.strip()]
                entries.append(Entry(head.group(1), head.group(2), roles, rule.group(1), body.strip(), promoted, index))
                break
    return entries


def read(path):
    """The entries of the lessons file; [] when it is missing or unreadable."""
    try:
        return parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def groups(entries):
    """key -> its entries, newest first (by date, then by place in the file), for the keyed rules."""
    found = {}
    for entry in entries:
        if entry.key:
            found.setdefault(entry.key, []).append(entry)
    return {key: sorted(group, key=lambda entry: (entry.date, -entry.line), reverse=True) for key, group in found.items()}


def is_promoted(group):
    return any(entry.promoted for entry in group)


def due(entries):
    """(key, entries) of every rule seen THRESHOLD times and not promoted: most seen first, then by key."""
    found = [(key, group) for key, group in groups(entries).items() if len(group) >= THRESHOLD and not is_promoted(group)]
    return sorted(found, key=lambda item: (-len(item[1]), item[0]))


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def similarity(a, b):
    """From 0 to 1: the mean of difflib's ratio on the words of both texts and the share of words they have in common."""
    words_a, words_b = words(a), words(b)
    if not words_a or not words_b:
        return 0.0
    ratio = difflib.SequenceMatcher(None, " ".join(words_a), " ".join(words_b)).ratio()
    return (ratio + len(set(words_a) & set(words_b)) / len(set(words_a) | set(words_b))) / 2


def suggest_key(text):
    """A slug from the first words of a rule text: up to four words, stop words dropped, at most MAX_KEY characters."""
    picked = [word for word in words(text) if word not in STOP_WORDS][:4]
    while len(picked) > 1 and len("-".join(picked)) > MAX_KEY:
        picked.pop()
    return "-".join(picked)[:MAX_KEY].strip("-") or "rule"


def valid_key(key):
    if not (re.fullmatch(SLUG, key) and len(key) <= MAX_KEY):
        raise Refuse(f"bad key {key!r}: use lowercase letters and digits joined by single hyphens, at most {MAX_KEY} characters, such as {suggest_key(key)}", 2)


def closest(entries, rule, limit=5):
    """The recorded keys whose rule texts look most like `rule`: (score, key, entries), best first, ties by key."""
    ranked = [(round(max(similarity(rule, entry.rule) for entry in group), 3), key, group) for key, group in groups(entries).items()]
    return sorted(ranked, key=lambda item: (-item[0], item[1]))[:limit]


def missing_key(entries, rule):
    """The refusal text for a rule recorded with no key: what is closest, and what to run next."""
    lines = ["a rule needs a key, so that the same rule recorded again is counted; nothing was written"]
    ranked = closest(entries, rule)
    if not ranked:
        lines.append(f"no keyed rule is recorded yet; re-run with --key <new-slug> (lowercase words joined by hyphens, at most {MAX_KEY} characters)")
        return "\n".join(lines)
    lines.append("closest recorded rules:")
    for _, key, group in ranked:
        promoted = ", promoted" if is_promoted(group) else ""
        lines.append(f"  {key} (seen {plural(len(group))}{promoted}): {group[0].rule}")
    lines.append("re-run with --key <existing> if it is the same rule, or --key <new-slug> if it is new")
    return "\n".join(lines)


def role_counts(group):
    """(role, number of entries that name it) for the entries of one key, most common first."""
    counts = collections.Counter(role for entry in group for role in set(entry.roles))
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def promote_hint(key, group):
    """The lines that say how to promote a due rule."""
    roles = role_counts(group)
    lines = [f"agent-steddy lessons promote {key} --to {roles[0][0] if roles else '<role>'}"]
    if roles:
        lines.append("roles in these entries, most common first: " + ", ".join(f"{role} ({count})" for role, count in roles))
    lines.append("a rule about safety, data or money goes --to walls instead")
    return lines


def repeat_notice(path, key):
    """What to print after a rule was recorded under `key`: nothing, or the count and the way to promote it."""
    group = groups(read(path)).get(key, [])
    if len(group) < THRESHOLD or is_promoted(group):
        return []
    return [f"{key} is now seen {len(group)} times", *promote_hint(key, group)]
