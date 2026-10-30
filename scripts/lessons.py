"""The learning loop: rule keys in the lessons file, the repeat notice, `lessons check` and `lessons promote`.

A lessons entry has a Rule line, `- Rule [commit-by-path]: <text>`; the key, a lowercase slug, names the rule so that the same rule recorded again is counted and not read twice.
A rule seen THRESHOLD times and not promoted is due: it moves up into the Pitfalls of a role card, or into the walls file, and every Rule line with its key then ends with ` [promoted -> <path>]`.
Every function takes the paths it works on, so the tests call them directly.
Reading is plain file reads and no git, so the prompt hook can call `nudge`.
"""
import collections
import difflib
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import project_config  # noqa: E402
from local_state import Refuse  # noqa: E402

THRESHOLD = 2  # "seen a second time" in the gates skill
MAX_KEY = 40
MAX_PITFALLS = 12  # a card with more bullets than this is due for pruning
ALIKE = 0.45  # similarity from which two texts look alike: on sample pairs paraphrases of one rule scored 0.43 to 0.9, unrelated rules 0.15 to 0.25 and different rules in one sentence frame up to 0.8; a crude measure, so the report only proposes
SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
STOP_WORDS = {"a", "an", "the", "to", "of", "and", "or", "is", "are", "be", "it", "in", "on", "for", "with", "that", "this", "you", "your", "when", "do", "does"}

WALLS_HEADER = """# Walls

Rules that no role crosses.
Every role reads this file at gate 2 (Recall).
A rule moves here from the lessons when it is about safety, data or money, or when a role keeps breaking it.
Add them with `agent-steddy lessons promote <key> --to walls`.

"""

HEADING = re.compile(r"## (\S+) - (.*?)(?: - roles: (.*))?")
RULE = re.compile(r"- Rule(?: \[(%s)\])?: ?(.*)" % SLUG)
MARK = re.compile(r"(.*) \[promoted -> ([^\]]+)\]")
PLACEHOLDER = re.compile(r"- (?:None recorded yet.*|<.*>\.?)")  # the empty bullets of the templates and the example cards
LESSONS_SUFFIX = re.compile(r" \(lessons: [^)]*\)$")

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


def nudge(path):
    """The line for the prompt reminder, empty when no rule is due. One file read, no git."""
    keys = [key for key, _ in due(read(path))]
    if not keys:
        return ""
    shown = ", ".join(keys[:3]) + (", ..." if len(keys) > 3 else "")
    return f"Learning loop: {len(keys)} rule(s) seen twice and not promoted ({shown}); run agent-steddy lessons check."


def pitfalls_span(lines):
    """(index of the `## Pitfalls` heading, index where its section ends); None when the card has none."""
    marks = headings(lines)
    for number, start in enumerate(marks):
        if lines[start][3:].strip().lower() == "pitfalls":
            return start, (marks[number + 1] if number + 1 < len(marks) else len(lines))
    return None


def pitfall_texts(text):
    """The first line of each bullet of a card's Pitfalls, without its `(lessons: ...)` note; the template placeholders are not pitfalls."""
    lines = text.split("\n")
    span = pitfalls_span(lines)
    bullets = [line for line in lines[span[0] + 1:span[1]] if line.startswith("- ") and not PLACEHOLDER.fullmatch(line.rstrip())] if span else []
    return [LESSONS_SUFFIX.sub("", bullet[2:].rstrip()) for bullet in bullets]


def alike_lines(texts, describe):
    """One line per pair of texts that looks alike, best first: `describe(score, i, j)` words it. At most 10, then a count of the rest.

    ponytail: every pair is compared, which is fine for hundreds of lines; add a cheap pre-filter if a file grows to thousands.
    """
    found = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            score = round(similarity(texts[i], texts[j]), 2)
            if score >= ALIKE:
                found.append((score, i, j))
    found.sort(key=lambda item: (-item[0], item[1], item[2]))
    lines = [describe(*item) for item in found[:10]]
    return lines + ([f"  ... and {len(found) - 10} more pairs"] if len(found) > 10 else [])


def clip(text, size=60):
    return text if len(text) <= size else text[:size - 3] + "..."


def due_lines(entries):
    lines = []
    for key, group in due(entries):
        lines.append(f"  {key}: seen {len(group)} times ({', '.join(sorted(entry.date for entry in group))})")
        lines.append("    tasks: " + "; ".join(entry.task for entry in group))
        lines += ["    " + line for line in promote_hint(key, group)]
    return lines


def unkeyed_lines(entries):
    unkeyed = [entry for entry in entries if not entry.key and not entry.promoted and entry.rule and not is_none(entry.rule)]
    lines = []
    for entry in unkeyed:
        lines += [f"  {entry.date} - {entry.task}: {clip(entry.rule, 100)}", f"    suggested key: {suggest_key(entry.rule)}"]

    def describe(score, i, j):
        return f"  looks alike ({score}): {unkeyed[i].date} - {unkeyed[i].task} and {unkeyed[j].date} - {unkeyed[j].task}; give both the same key"

    return lines + alike_lines([entry.rule for entry in unkeyed], describe)


def prune_lines(folder):
    lines = []
    try:
        cards = sorted(Path(folder).glob("*.md"))
    except OSError:
        cards = []
    for card in cards:
        try:
            texts = pitfall_texts(card.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if len(texts) > MAX_PITFALLS:
            lines.append(f"  {card.stem}: {len(texts)} pitfalls, more than {MAX_PITFALLS}; merge duplicates and drop stale ones")
        lines += alike_lines(texts, lambda score, i, j, name=card.stem, texts=texts: f'  {name}: "{clip(texts[i])}" looks like "{clip(texts[j])}" ({score}); merge them')
    return lines


def check(project, config):
    """The `lessons check` report: due rules, rule lines with no key, and role cards to prune. Every section says `none` when empty."""
    project = Path(project)
    entries = read(project / project_config.get(config, "records", "lessons"))
    sections = [
        (f"Due: rules seen {THRESHOLD} or more times and not promoted", due_lines(entries)),
        ("Unkeyed: Rule lines with no key (add the key to the line by hand, or record the rule again with --key)", unkeyed_lines(entries)),
        (f"Cards to prune: role cards with more than {MAX_PITFALLS} pitfalls, and pitfalls that look alike", prune_lines(project / project_config.get(config, "records", "roles"))),
    ]
    out = []
    for title, lines in sections:
        out += [*([""] if out else []), title, *(lines or ["  none"])]
    return out


def relative(project, path):
    return Path(os.path.relpath(path, project)).as_posix()


def add_pitfall(text, bullet):
    """The text of a role card with `bullet` as the last bullet of its Pitfalls; the section is added at the end when the card has none. A placeholder bullet is replaced."""
    lines = text.split("\n")
    span = pitfalls_span(lines)
    if span is None:
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join([*lines, "", "## Pitfalls", "", bullet, ""])
    start, end = span
    body = [line for line in lines[start + 1:end] if not PLACEHOLDER.fullmatch(line.rstrip())]
    while body and not body[-1].strip():
        body.pop()
    lines[start + 1:end] = [*(body or [""]), bullet, ""]  # the blank line keeps the next heading apart, and ends the file with a newline
    return "\n".join(lines)


def add_wall(path, bullet):
    """Append `bullet` to the walls file, creating it with a short header when it is missing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(WALLS_HEADER, encoding="utf-8")
    newline = "" if path.read_bytes().endswith(b"\n") else "\n"
    with path.open("a", encoding="utf-8") as lines:
        lines.write(f"{newline}{bullet}\n")


def promote(project, config, key, to, text=None, force=False):
    """Move a repeated rule up: its bullet goes to the Pitfalls of the role card `to`, or to the walls file when `to` is `walls`, and its Rule lines get a marker. Returns what was written.

    Refuses (exit 2) an unknown key, a key seen less than THRESHOLD times unless `force`, a key that is already promoted, a role with no card, and an empty or multi-line text.
    """
    project = Path(project)
    lessons_path = project / project_config.get(config, "records", "lessons")
    shown = relative(project, lessons_path)
    try:
        source = lessons_path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        source = ""
    group = groups(parse(source)).get(key)
    if not group:
        raise Refuse(f"no rule has the key {key!r} in {shown}; run agent-steddy lessons check to see the keys", 2)
    if is_promoted(group):
        raise Refuse(f"{key} is already promoted: {next(entry.promoted for entry in group if entry.promoted)}", 2)
    if len(group) < THRESHOLD and not force:
        raise Refuse(f"{key} is seen {plural(len(group))}, fewer than {THRESHOLD}; promote it when it repeats, or pass --force", 2)
    if to == "walls":
        target = project / project_config.get(config, "records", "walls")
    else:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", to):
            raise Refuse(f"bad target {to!r}: --to is a role (the file name of its card without .md) or walls", 2)
        target = project / project_config.get(config, "records", "roles") / f"{to}.md"
        if not target.is_file():
            raise Refuse(f"the role card {relative(project, target)} does not exist; copy templates/roles/role-card.md from the plugin to it and fill it in, or pass the role that has a card", 2)
    wording = (text if text is not None else group[0].rule).strip()
    if not wording or "\n" in wording or "\r" in wording:
        raise Refuse("the text must be a single line that is not empty; pass --text with the final wording", 2)
    if "[promoted ->" in wording:
        raise Refuse("the text must not contain '[promoted ->'; the command writes that marker", 2)
    bullet = f"- {wording} (lessons: {', '.join(sorted(entry.date for entry in group))})"
    # ponytail: read, write the target, then the lessons file - a crash in between leaves the bullet in the target and the rules unmarked; two agents promoting at once could lose a change
    if to == "walls":
        add_wall(target, bullet)
    else:
        target.write_text(add_pitfall(target.read_text(encoding="utf-8"), bullet), encoding="utf-8")
    marker = f" [promoted -> {relative(project, target)}]"
    lines = source.split("\n")
    for entry in group:
        lines[entry.line] = lines[entry.line].rstrip() + marker
    lessons_path.write_text("\n".join(lines), encoding="utf-8")
    return [f"added to {relative(project, target)}: {bullet}", f"marked {plural(len(group), 'Rule line')} of {key} in {shown} as{marker}"]
