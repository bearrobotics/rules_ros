#!/usr/bin/env python
import sys
from third_party.legacy_roslaunch import main

main.main(['roslaunch'] + sys.argv[1:])
