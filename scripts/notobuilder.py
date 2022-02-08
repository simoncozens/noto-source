"""Build a Noto font from one or more source files.

By default, places unhinted TTF, hinted TTF, OTF and (if possible) variable
fonts into the ``output/`` directory.

Currently does not support building from Monotype sources.

Example:

    python3 scripts/notobuilder.py src/NotoSans-MM.glyphs src/NotoSans-ItalicMM.glyphs
"""
import logging
import os
import re
import sys

from gftools.builder import GFBuilder
from gftools.builder.autohint import autohint


class NotoBuilder(GFBuilder):
    def fill_config_defaults(self):
        family = self.config["familyName"] = self.get_family_name()
        if not "vfDir" in self.config:
            self.config["vfDir"] = "output/%s/unhinted/variable-ttf" % family
        if not "otDir" in self.config:
            self.config["otDir"] = "output/%s/unhinted/otf" % family
        if not "ttDir" in self.config:
            self.config["ttDir"] "output/%s/unhinted/ttf" % family,
        super().fill_config_defaults()

    def get_family_name(self):
        source = self.config["sources"][0]
        source, _ = os.path.splitext(os.path.basename(source))
        fname = re.sub(r"([a-z])([A-Z])", r"\1 \2", source)
        fname = re.sub("-?MM$", "", fname)
        return fname

    def post_process_ttf(self, filename):
        self.logger.debug("Autohinting")
        hinted_dir = "output/%s/hinted/ttf" % self.config["familyName"]
        os.makedirs(hinted_dir, exist_ok=True)
        hinted = filename.replace("unhinted", "hinted")
        autohint(filename, hinted, add_script=True)
        self.post_process(filename)


if __name__ == '__main__':
    import argparse

    # https://stackoverflow.com/a/20422915
    class ActionNoYes(argparse.Action):
        def __init__(self, option_strings, dest, default=None, required=False, help=None):

            if default is None:
                raise ValueError('You must provide a default with Yes/No action')
            if len(option_strings)!=1:
                raise ValueError('Only single argument is allowed with YesNo action')
            opt = option_strings[0]
            if not opt.startswith('--'):
                raise ValueError('Yes/No arguments must be prefixed with --')

            opt = opt[2:]
            opts = ['--' + opt, '--no-' + opt]
            super(ActionNoYes, self).__init__(opts, dest, nargs=0, const=None, 
                                              default=default, required=required, help=help)
        def __call__(self, parser, namespace, values, option_strings=None):
            if option_strings.startswith('--no-'):
                setattr(namespace, self.dest, False)
            else:
                setattr(namespace, self.dest, True)

    parser = argparse.ArgumentParser(description='Build a Noto font')
    parser.add_argument('sources', metavar='FILE', nargs='+',
                        help='source files')
    parser.add_argument('--variable', action=ActionNoYes, default=True,
                        help='build a variable font')
    parser.add_argument('--otf', action=ActionNoYes, default=True,
                        help='build an OTF')
    parser.add_argument('--verbose','-v', action="store_true", help='verbose logging')

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO)
    builder = NotoBuilder(args.sources)
    builder.config["buildVariable"] = args.variable
    builder.config["buildOTF"] = args.otf
    builder.build()
    print("Produced the following files:")
    for o in sorted(builder.outputs):
        print("* "+o)
