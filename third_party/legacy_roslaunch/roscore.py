#!/usr/bin/env python
import sys
from third_party.legacy_roslaunch import main

main.main(['roscore', '--core'] + sys.argv[1:])
