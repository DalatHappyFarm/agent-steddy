"""The learning loop: rule keys in the lessons file, the repeat notice, `lessons check`, `find`, `promote` and `retire`.

A lessons entry has one or more Rule lines, `- Rule [commit-by-path]: <text>`, each with a `  - When: <situation>` line below it and, for feedback from the owner or a review, a `  - From: owner` line.
The key, a lowercase slug, names the rule so that the same rule recorded again is counted and not read twice; the When line says when it applies, in the words an agent would use then, so `find` can fetch it.
A rule seen THRESHOLD times and not promoted is due: it moves up into the Pitfalls of a role card, or into the walls file, and every Rule line with its key then ends with ` [promoted -> <path>]`.
A promoted rule recorded again broke after its promotion, and needs a check that a machine runs; a rule that no longer holds ends with ` [retired]` or ` [retired -> <key>]`.
Every function takes the paths it works on, so the tests call them directly.
Reading is plain file reads and no git, so the prompt hook can call `nudge` and `recall`.
"""
import collections
import difflib
import math
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
NEAR = 0.38  # score from which a new key is refused as a possible repeat of a recorded rule: on five real lessons files, six pairs of one rule under two keys scored 0.39 to 0.59 and only six of the other 19,700 pairs of keys scored 0.38 or more; replayed in date order, 2 of 199 new keys were refused; a crude measure, since a repeat in other words and another situation passes
PROMOTED_NEAR = 0.30  # NEAR for a new key whose closest recorded rule is promoted; lower, since a promoted rule that breaks again is the repeat that most needs to be seen: on a real lessons file a promoted rule broke again days later under a new key and scored 0.35 to 0.37 (0.35 when the promoted entries have no When line), so the line sits 0.05 below it; on five real files replayed in date order it and NEAR refuse 5 of 199 new keys, against 35 when any score counts
SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
STOP_WORDS = {"a", "an", "the", "to", "of", "and", "or", "is", "are", "be", "it", "in", "on", "for", "with", "that", "this", "you", "your", "when", "do", "does"}
# find drops more function words than suggest_key does, since a prompt is longer and looser than a rule
FIND_STOP = STOP_WORDS | {"i", "we", "my", "our", "me", "as", "by", "at", "from", "not", "no", "so", "if", "then", "than", "its", "into", "was", "were", "has", "have", "had", "can", "will", "would", "should", "could", "please", "let", "us",
                          "every", "each", "all", "any", "some", "which", "what", "who", "how", "tell", "they", "them", "their", "these", "those", "there", "here", "also", "just"}
K1, B = 1.5, 0.75  # the usual BM25 constants: how fast repeats of a word stop adding, and how much a long rule is held back
RECALL_TOP = 3  # rules the prompt hook adds at most
SOURCES = ("self", "owner", "review")  # who found what a rule is about; self is the default and is not written

WALLS_HEADER = """# Walls

Rules that no role crosses.
Every role reads this file at gate 2 (Recall).
A rule moves here from the lessons when it is about safety, data or money, or when a role keeps breaking it.
Add them with `agent-steddy lessons promote <key> --to walls`.

"""

HEADING = re.compile(r"## (\S+) - (.*?)(?: - roles: (.*))?")
RULE = re.compile(r"- Rule(?: \[(%s)\])?: ?(.*)" % SLUG)
DETAIL = re.compile(r"  - (When|From): (.*)")  # the lines right below a Rule line
MARK = re.compile(r"(.*) \[(promoted|retired)(?: -> ([^\]]+))?\]")  # at the end of a Rule line, written by promote and retire
PLACEHOLDER = re.compile(r"- (?:None recorded yet.*|<.*>\.?)")  # the empty bullets of the templates and the example cards
LESSONS_SUFFIX = re.compile(r" \(lessons: [^)]*\)$")

# One Rule line: its entry's date, task and roles, its key (None on an old line), the rule text without the markers, its When text (None),
# who found it (self, owner or review), the promoted marker's path (None), the retired marker (None, "" with no successor, or the successor's key), and the index of the Rule line
Entry = collections.namedtuple("Entry", "date task roles key rule when source promoted retired line")


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
    """The Rule lines of a lessons file, one Entry each, in file order (newest first when the commands wrote it)."""
    lines = text.split("\n")
    marks = headings(lines)
    entries = []
    for number, start in enumerate(marks):
        head = HEADING.fullmatch(lines[start].rstrip())
        if not head:
            continue
        end = marks[number + 1] if number + 1 < len(marks) else len(lines)
        roles = [role.strip() for role in (head.group(3) or "").split(",") if role.strip()]
        for index in range(start + 1, end):
            rule = RULE.fullmatch(lines[index].rstrip())
            if not rule:
                continue
            body, found = rule.group(2), {}
            while MARK.fullmatch(body):
                body, kind, target = MARK.fullmatch(body).groups()
                found.setdefault(kind, target or "")
            details = {}
            for below in lines[index + 1:end]:
                detail = DETAIL.fullmatch(below.rstrip())
                if not detail:
                    break
                details.setdefault(detail.group(1), detail.group(2).strip())
            source = details.get("From", "").lower()
            entries.append(Entry(head.group(1), head.group(2), roles, rule.group(1), body.strip(), details.get("When") or None,
                                 source if source in SOURCES else "self", found.get("promoted") or None, found.get("retired"), index))
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


def promoted_to(group):
    return next((entry.promoted for entry in group if entry.promoted), None)


def is_retired(group):
    return any(entry.retired is not None for entry in group)


def successor(group):
    """The key that replaced a retired rule, "" when none did, None when the rule is not retired."""
    return next((entry.retired for entry in group if entry.retired is not None), None)


def due(entries):
    """(key, entries) of every rule seen THRESHOLD times and not promoted or retired: most seen first, then by key."""
    found = [(key, group) for key, group in groups(entries).items() if len(group) >= THRESHOLD and not is_promoted(group) and not is_retired(group)]
    return sorted(found, key=lambda item: (-len(item[1]), item[0]))


def broken(entries, cased=()):
    """(key, entries, the entries recorded after the promotion) of every promoted rule recorded again since, that has no eval case yet: most recorded again first, then by key.

    promote marks every Rule line of the key, so a line of a promoted key with no marker was recorded after the promotion.
    `cased` holds the keys that have an eval case, the check that a rule broken after its promotion needs.
    """
    found = []
    for key, group in groups(entries).items():
        after = [entry for entry in group if not entry.promoted]
        if is_promoted(group) and not is_retired(group) and after and key not in cased:
            found.append((key, group, after))
    return sorted(found, key=lambda item: (-len(item[2]), item[0]))


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
        state = ", promoted" if is_promoted(group) else ""
        state += "" if successor(group) is None else f", retired{' by ' + successor(group) if successor(group) else ''}"
        lines.append(f"  {key} (seen {plural(len(group))}{state}): {group[0].rule}")
    lines.append("re-run with --key <existing> if it is the same rule, or --key <new-slug> if it is new")
    return "\n".join(lines)


def key_refusal(entries, rule, key, new=False, when=None):
    """Why `rule` (with its `when`) cannot be recorded under `key`, or None when it can.

    A retired key takes no new lines.
    A new key is refused unless `new` when the closest recorded rule that is not retired scores NEAR or more, since a repeat under a new key is never counted,
    or PROMOTED_NEAR or more when that rule is promoted, since the same failure under a new key would hide that a promoted rule broke again.
    """
    known = groups(entries)
    if key in known:
        if successor(known[key]) is None:
            return None
        after = successor(known[key])
        return f"{key} is retired{' by ' + after if after else ''}; record the rule under {after or 'a new key'}; nothing was written"
    if new:
        return None
    ranked = [item for item in nearest(entries, rule, when) if item[0]]  # a rule that shares no term with the new one is not close
    if not ranked:
        return None
    score, near, group = ranked[0]
    promoted = is_promoted(group)
    if score < (PROMOTED_NEAR if promoted else NEAR):
        return None
    return "\n".join([
        f"{key} is a new key, and the closest recorded rule is promoted to {promoted_to(group)}:" if promoted else f"{key} is a new key, and it looks like a rule that is already recorded:",
        *(f"  {name} (seen {plural(len(rules))}{', promoted -> ' + promoted_to(rules) if is_promoted(rules) else ''}): {rules[0].rule}" for _, name, rules in ranked),
        f"if this is the same failure, the rule broke after its promotion: re-run with --key {near}" if promoted else "if it is the same rule, re-run with --key <existing>",
        "if it is a different rule, re-run with --new; nothing was written",
    ])


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


def break_hint(key):
    return [
        "a rule broken after its promotion needs a check that a machine runs, not another note: a commands.deny entry, a handback.required item, a hook or a test",
        f"keep it as an eval case with `Key: {key}` and a Check command that fails on this case, and run agent-steddy lessons eval",
    ]


def repeat_notice(path, key):
    """What to print after a rule was recorded under `key`: nothing, the count and the way to promote it, or that a promoted rule broke again."""
    group = groups(read(path)).get(key, [])
    if is_promoted(group):
        if all(entry.promoted for entry in group):
            return []
        return [f"{key} is seen again after its promotion to {promoted_to(group)} ({plural(len(group))} in all)", *break_hint(key)]
    if len(group) < THRESHOLD:
        return []
    return [f"{key} is now seen {len(group)} times", *promote_hint(key, group)]


def shortlist(keys):
    return ", ".join(keys[:3]) + (", ..." if len(keys) > 3 else "")


def nudge(path, cased=()):
    """The line for the prompt reminder, empty when no rule is due or broken after its promotion. One file read, no git."""
    entries = read(path)
    due_keys = [key for key, _ in due(entries)]
    broken_keys = [key for key, _, _ in broken(entries, cased)]
    parts = [f"{len(due_keys)} rule(s) seen twice and not promoted ({shortlist(due_keys)})"] if due_keys else []
    parts += [f"{len(broken_keys)} rule(s) broken after promotion ({shortlist(broken_keys)})"] if broken_keys else []
    return f"Learning loop: {'; '.join(parts)}; run agent-steddy lessons check." if parts else ""


def stem(word):
    """A crude English stem that drops -ing, -ed or a plural -s, so that runs and run, passed and pass match.

    ponytail: suffix stripping, not a stemmer (stated and state still differ); swap in a Porter stemmer if recall misses on word forms.
    """
    for suffix in ("ing", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3 and not (suffix == "s" and word[-2] in "siu"):
            return word[:-len(suffix)]
    return word


def terms(text):
    """The search terms of a text: its words in any script, lower case, function words dropped, stemmed."""
    return [stem(word) for word in re.findall(r"\w+", text.lower()) if word not in FIND_STOP]


def near_terms(rule, when=None):
    return set(terms(f"{rule} {when or ''}"))


def nearest(entries, rule, when=None, limit=3):
    """The recorded keys that are not retired and look most like `rule` with its `when`: (score, key, entries), best first, ties by key.

    A key scores as its best entry, and an entry is its rule text with its When line, so the situation counts as much as the wording.
    The score is the cosine of the two sets of search terms: the terms they share over the square root of the product of their sizes, from 0 to 1.
    """
    wanted = near_terms(rule, when)

    def score(entry):
        have = near_terms(entry.rule, entry.when)
        return len(wanted & have) / math.sqrt(len(wanted) * len(have)) if wanted and have else 0.0

    ranked = [(round(max(score(entry) for entry in group), 3), key, group) for key, group in groups(entries).items() if not is_retired(group)]
    return sorted(ranked, key=lambda item: (-item[0], item[1]))[:limit]


def find(entries, query, top=5):
    """(score, matched terms, key, entries) of the rules that match `query`, best first, ties by key; retired rules are left out.

    One document per key: the key's words, every rule text and every When line of its entries.
    The score is BM25 with the constants K1 and B; only keys that share a term with the query are returned.
    """
    keyed = {key: group for key, group in groups(entries).items() if not is_retired(group)}
    docs = {key: terms(" ".join([key.replace("-", " "), *(entry.rule for entry in group), *(entry.when for entry in group if entry.when)])) for key, group in keyed.items()}
    wanted = set(terms(query))
    if not docs or not wanted:
        return []
    size = sum(len(doc) for doc in docs.values()) / len(docs) or 1
    df = collections.Counter(word for doc in docs.values() for word in set(doc))
    ranked = []
    for key, doc in docs.items():
        counts = collections.Counter(doc)
        hits = [word for word in wanted if counts[word]]
        if hits:
            score = sum(math.log(1 + (len(docs) - df[word] + 0.5) / (df[word] + 0.5)) * counts[word] * (K1 + 1) / (counts[word] + K1 * (1 - B + B * len(doc) / size)) for word in hits)
            ranked.append((round(score, 3), len(hits), key, keyed[key]))
    return sorted(ranked, key=lambda item: (-item[0], item[2]))[:top]


def rule_lines(key, group):
    """Two lines for a found rule: the key, how often it was seen, where it was promoted and whether the owner gave it, the newest rule text; then its newest When."""
    notes = [f"seen {plural(len(group))}"]
    notes += [f"promoted -> {promoted_to(group)}"] if is_promoted(group) else []
    notes += [f"from the {source}" for source in SOURCES[1:] if any(entry.source == source for entry in group)]
    when = next((entry.when for entry in group if entry.when), None)
    return [f"{key} ({', '.join(notes)}): {group[0].rule}", *([f"  when: {when}"] if when else [])]


def find_lines(entries, query, top=5):
    """The `lessons find` output."""
    out = []
    for _, _, key, group in find(entries, query, top):
        out += rule_lines(key, group)
    return out or ["no recorded rule matches; try the words of the situation, such as the command, the file or the step"]


def recall(path, prompt):
    """The lines the prompt hook adds: up to RECALL_TOP rules that share two terms or more with the prompt (one, for a prompt of one term). One file read."""
    need = min(2, len(set(terms(prompt))))
    hits = [hit for hit in find(read(path), prompt, RECALL_TOP) if need and hit[1] >= need]
    if not hits:
        return []
    out = ["Lessons that may apply to this prompt (agent-steddy lessons find; read the whole entry in the lessons file before you lean on one):"]
    for _, _, key, group in hits:
        first, *rest = rule_lines(key, group)
        out += [clip(f"- {first}", 400), *(clip(line, 400) for line in rest)]
    return out


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


def broken_lines(entries, cased):
    lines = []
    for key, group, after in broken(entries, cased):
        lines.append(f"  {key}: promoted -> {promoted_to(group)}, recorded again on {', '.join(sorted(entry.date for entry in after))}")
        lines.append("    tasks: " + "; ".join(entry.task for entry in after))
        lines += ["    " + line for line in break_hint(key)]
    return lines


def no_when_lines(entries):
    lines = []
    for key, group in sorted(groups(entries).items()):
        if not is_retired(group) and not any(entry.when for entry in group):
            lines.append(f"  {key}: add a line '  - When: <the situation, in the words an agent would use then>' under its Rule line of {group[0].date} - {group[0].task}")
    return lines


def check(project, config, cased=()):
    """The `lessons check` report: due rules, rules broken after their promotion, rules with no When, rule lines with no key, and role cards to prune. Every section says `none` when empty.

    `cased` holds the keys that have an eval case (evals.case_keys), which takes a rule off the broken list.
    """
    project = Path(project)
    entries = read(project / project_config.get(config, "records", "lessons"))
    sections = [
        (f"Due: rules seen {THRESHOLD} or more times and not promoted", due_lines(entries)),
        ("Broken after promotion: promoted rules recorded again since, with no eval case", broken_lines(entries, cased)),
        ("No When: rules that find can only match by their text (add the line by hand)", no_when_lines(entries)),
        ("Unkeyed: Rule lines with no key (add the key to the line by hand, or record the rule again with --key)", unkeyed_lines(entries)),
        (f"Cards to prune: role cards with more than {MAX_PITFALLS} pitfalls, and pitfalls that look alike", prune_lines(project / project_config.get(config, "records", "roles"))),
    ]
    out = []
    for title, lines in sections:
        out += [*([""] if out else []), title, *(lines or ["  none"])]
    return out


def has_marker(text):
    return "[promoted" in text or "[retired" in text


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

    Refuses (exit 2) an unknown key, a key seen less than THRESHOLD times unless `force`, a key that is already promoted or retired, a role with no card, and an empty or multi-line text.
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
        raise Refuse(f"{key} is already promoted: {promoted_to(group)}", 2)
    if is_retired(group):
        raise Refuse(f"{key} is retired; a retired rule is not promoted", 2)
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
    if has_marker(wording):
        raise Refuse("the text must not contain '[promoted' or '[retired'; the commands write those markers", 2)
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


def retire(project, config, key, by=None):
    """Mark every Rule line of `key` as retired, ` [retired]`, or ` [retired -> <by>]` when another rule replaced it. Returns what was written.

    A retired rule is no longer due, broken or found, and takes no new lines; refuses (exit 2) an unknown or retired key, and a `by` that is the key itself or no recorded key.
    A promoted rule keeps its bullet in the role card or the walls file: what to do with that bullet is a judgment, so the command only names it.
    """
    project = Path(project)
    lessons_path = project / project_config.get(config, "records", "lessons")
    shown = relative(project, lessons_path)
    try:
        source = lessons_path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        source = ""
    known = groups(parse(source))
    group = known.get(key)
    if not group:
        raise Refuse(f"no rule has the key {key!r} in {shown}; run agent-steddy lessons check to see the keys", 2)
    if is_retired(group):
        raise Refuse(f"{key} is already retired", 2)
    if by is not None:
        valid_key(by)
        if by == key or by not in known or is_retired(known[by]):
            raise Refuse(f"--by must name another recorded rule that is not retired; record {by} first, or retire {key} without --by", 2)
    marker = f" [retired -> {by}]" if by else " [retired]"
    lines = source.split("\n")
    for entry in group:
        lines[entry.line] = lines[entry.line].rstrip() + marker
    lessons_path.write_text("\n".join(lines), encoding="utf-8")
    out = [f"marked {plural(len(group), 'Rule line')} of {key} in {shown} as{marker}"]
    if is_promoted(group):
        out.append(f"{key} was promoted to {promoted_to(group)}: edit or remove its bullet there by hand")
    return out
