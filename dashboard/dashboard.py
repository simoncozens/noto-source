from gftools.builder import GFBuilder
from gftools.builder.autohint import autohint
from pybars import Compiler
from github import Github

from collections import defaultdict
import sys
import glob
import re
import urllib.parse
import logging
import os
import subprocess
import json
import requests


TOKEN = os.environ["GITHUB_TOKEN"]
COMMIT_URL = "https://github.com/googlefonts/noto-source/commit"
BLACKLISTED = [
    "Noto Sans",
    "Noto Serif",
    "Noto Sans Mono",
    "Noto Sans Italic",
    "Arimo",
    "Arimo-Italic",
]
DASHBOARD_URL = "https://simoncozens.github.io/noto-source/"
STATE_URL = DASHBOARD_URL + "state.json"
MAX_BUILD = 20


class NotoBuilder(GFBuilder):
    def __init__(self, source):
        family = self.get_family_name(source)
        self.config = {
            "sources": [source],
            "familyName": family,
            "outputDir": "fonts",
            "buildVariable": True,
            "autohintTTF": False,
            "buildWebfont": False,
            "vfDir": "output/%s/unhinted/variable-ttf" % family,
            "otDir": "output/%s/unhinted/otf" % family,
            "ttDir": "output/%s/unhinted/ttf" % family,
        }
        self.outputs = set()
        self.logger = logging.getLogger("GFBuilder")
        self.fill_config_defaults()

    def get_family_name(self, source=None):
        if not source:
            source = self.config["sources"][0]
        source, _ = os.path.splitext(os.path.basename(source))
        fname = re.sub(r"([a-z])([A-Z])", r"\1 \2", source)
        fname = re.sub("-?MM$", "", fname)
        return fname

    def post_process_ttf(self, filename):
        super().post_process_ttf(filename)
        self.outputs.add(filename)
        hinted_dir = "output/%s/hinted/ttf" % self.get_family_name()
        os.makedirs(hinted_dir, exist_ok=True)
        hinted = filename.replace("unhinted", "hinted")
        try:
            autohint(filename, hinted)
            self.outputs.add(hinted)
        except Exception as e:
            self.logger.error("Couldn't autohint %s: %s" % (filename, e))

    def post_process(self, filename):
        super().post_process(filename)
        self.outputs.add(filename)

    def build_variable(self):
        try:
            super().build_variable()
        except Exception as e:
            self.logger.error("Couldn't build variable font: %s" % e)


def build_and_test_file(file):
    nb = NotoBuilder(file)
    family = nb.get_family_name()
    os.makedirs("output/%s" % family, exist_ok=True)
    log = logging.getLogger()
    for hdlr in log.handlers[:]:
        log.removeHandler(hdlr)
    log.addHandler(logging.FileHandler("output/%s/build.log" % family))
    log.addHandler(logging.StreamHandler())
    print("\n::group::%s (%i/%i)\n" % (family, ix + 1, len(to_build)), file=sys.stderr)
    errors = None
    report = None
    try:
        nb.build()
    except Exception as e:
        errors = str(e)
    os.makedirs("output/%s/badges" % family, exist_ok=True)
    # We just run fontbakery on static TTF + variable
    interesting_outputs = sorted(
        [x for x in nb.outputs if "unhinted/ttf" in x or "unhinted/variable" in x]
    )
    if interesting_outputs:
        subprocess.run(
            [
                "fontbakery",
                "check-googlefonts",
                "--config", "fontbakery.yml",
                "-n",
                "-l",
                "INFO",
                "-x",
                "com.google.fonts/check/family/single_directory",
                "--html",
                ("output/%s/fontbakery-report.html" % family),
                "--badges",
                ("output/%s/badges/" % family),
                *interesting_outputs,
            ],
            capture_output=True,
        )
        report = "%s/fontbakery-report.html" % family
    paths = [x.replace("output/", "") for x in sorted(nb.outputs)]
    outputs = {}
    for p in paths:
        if "variable" in p:
            outputs.setdefault("variable", []).append(
                {"path": p, "display": os.path.basename(p)}
            )
        elif "unhinted" in p:
            outputs.setdefault("unhinted", []).append(
                {"path": p, "display": os.path.basename(p)}
            )
        elif "hinted" in p:
            outputs.setdefault("hinted", []).append(
                {"path": p, "display": os.path.basename(p)}
            )
    print("\n::endgroup::", file=sys.stderr)
    return {
        "family": family,
        "commit": last_commit(file),
        "log": "%s/build.log" % family,
        "errors": errors,
        "fontbakery": report,
        "badges": [
            urllib.parse.quote_plus(x.replace("output/", DASHBOARD_URL)).replace(
                "+", "%2520"
            )
            for x in glob.glob("output/%s/badges/*.json" % family)
        ],
        "outputs": outputs,
    }


os.makedirs("output", exist_ok=True)  # Stop it being deleted

script_projects = {}
# Try to load state here
try:
    script_projects = requests.get(STATE_URL).json()
except Exception as e:
    logging.getLogger().error(e)


def last_commit(file):
    log = subprocess.check_output(
        ["git", "log", "-1", "--abbrev-commit", "--follow", "--pretty=reference", file]
    ).decode("utf-8")
    log = re.sub(r"^(\w+)", fr'<a href="{COMMIT_URL}/\1">\1</a>', log)
    return log


all_files = sorted([*glob.glob("src/*.glyphs"), *glob.glob("src/*/*.designspace")])

# Work out which we're building
to_build = []
for ix, file in enumerate(all_files):
    nb = NotoBuilder(file)
    family = nb.get_family_name()
    if family in BLACKLISTED:
        continue
    if (
        family not in script_projects
        or last_commit(file) != script_projects[family]["commit"]
    ):
        to_build.append(file)
    if len(to_build) > MAX_BUILD:
        break

for ix, file in enumerate(to_build):
    results = build_and_test_file(file)
    script_projects[results["family"]] = results


g = Github(TOKEN)

issues = defaultdict(list)

try:
    repo = g.get_repo("googlefonts/noto-fonts")
    open_issues = repo.get_issues(state="open")
    for issue in open_issues:
        for label in issue.labels:
            if label.name.startswith("Script-"):
                issues[label.name.replace("Script-", "")].append(
                    {"id": issue.number, "title": issue.title}
                )
except Exception as e:
    logger.getLogger().error("Couldn't get list of issues: %s" % e)

for project, value in script_projects.items():
    # It's unfortunate that we do a double loop here, but it's
    # also actually pretty useful at finding things which are
    # labeled in ambiguous ways. e.g "Script-Nastaliq" and
    # "Script-Urdu" will both end up in the "Noto Nastaliq Urdu"
    # project.
    for script, script_issues in issues.items():
        if script in project:
            value["issues"] = list(script_issues)

compiler = Compiler()
template = open("dashboard/template.html", "r").read()
template = compiler.compile(template)
output = template({"projects": script_projects})
with open("output/index.html", "w") as fh:
    fh.write(output)

with open("output/state.json", "w") as fh:
    json.dump(script_projects, fh)
