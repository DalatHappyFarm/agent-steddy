"""The diagrams, their JSON specs and the README must agree: each spec has an SVG, the SVG carries the spec's text as its title, and the README shows it with the same alt text."""
import html
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPECS = sorted((ROOT / "docs" / "diagrams").glob("*.json"))
README = (ROOT / "README.md").read_text(encoding="utf-8")
# the comment that names the spec, then the image; the alt text may run over several lines
EMBED = re.compile(r"<!-- diagram source: (\S+) -->\n!\[(.*?)\]\((\S+?)\)", re.S)


def words(text):
    return " ".join(text.split())


class Diagrams(unittest.TestCase):
    def test_there_are_two_diagrams(self):
        self.assertEqual([path.stem for path in SPECS], ["architecture", "flow"])

    def test_every_svg_is_drawn_from_its_spec_and_has_no_outside_requests(self):
        for spec in SPECS:
            title = json.loads(spec.read_text(encoding="utf-8"))["title"]
            svg = spec.with_suffix(".svg").read_text(encoding="utf-8")
            self.assertEqual(html.unescape(re.search(r"<title>(.*?)</title>", svg, re.S).group(1)), title, spec.name)
            self.assertEqual(re.findall(r"https?://[^\s\"']+", svg), ["http://www.w3.org/2000/svg"], spec.name)

    def test_the_readme_shows_each_diagram_with_the_spec_title_as_alt_text(self):
        shown = {source: (words(alt), image) for source, alt, image in EMBED.findall(README)}
        for spec in SPECS:
            source = f"docs/diagrams/{spec.name}"
            title = json.loads(spec.read_text(encoding="utf-8"))["title"]
            self.assertIn(source, shown)
            self.assertEqual(shown[source], (words(title), f"docs/diagrams/{spec.stem}.svg"), spec.name)
        self.assertEqual(len(shown), len(SPECS))


if __name__ == "__main__":
    unittest.main()
