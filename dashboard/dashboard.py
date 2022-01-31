from gftools.builder import GFBuilder
from gftools.builder.autohint import autohint
from pybars import Compiler

import sys
import glob
import re
import logging
import os
import subprocess


COMMIT_URL = "https://github.com/googlefonts/noto-source/commit"


class NotoBuilder(GFBuilder):
    def __init__(self, source):
        family = self.get_family_name(source)
        self.config = {
            "sources": [source],
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
        fname = re.sub("-MM$", "", fname)
        return fname

    def post_process_ttf(self, filename):
        super().post_process_ttf(filename)
        self.outputs.add(filename)
        hinted_dir = "output/%s/unhinted/ttf" % self.get_family_name()
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


os.makedirs("output", exist_ok=True)  # Stop it being deleted

script_projects = []


def last_commit(file):
    log = subprocess.check_output(
        ["git", "log", "-1", "--abbrev-commit", "--follow", "--pretty=reference", file]
    ).decode("utf-8")
    log = re.sub(r"^(\w+)", fr'<a href="{COMMIT_URL}/\1">\1</a>', log)
    return log


for file in [*glob.glob("src/*.glyphs"), *glob.glob("src/*/*.designspace")]:
    nb = NotoBuilder(file)
    family = nb.get_family_name()
    os.makedirs("output/%s" % family, exist_ok=True)
    logging.basicConfig(
        filename="output/%s/build.log" % family, level=logging.INFO
    )
    print("\n## %s ##\n" % family)
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
                "check-notofonts",
                "-l",
                "WARN",
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
    script_projects.append(
        {
            "family": family,
            "commit": last_commit(file),
            "log": "%s/build.log" % family,
            "errors": errors,
            "fontbakery": report,
            "badges": [
                x.replace("output/", "")
                for x in glob.glob("output/%s/badges/*.json" % family)
            ],
            "outputs": outputs,
        }
    )


compiler = Compiler()
template = open("dashboard/template.html", "r").read()
template = compiler.compile(template)
output = template({"projects": script_projects})
with open("output/dashboard.html", "w") as fh:
    fh.write(output)
