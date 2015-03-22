#!/usr/bin/env python3
# Goshu IRC Bot
# written by Daniel Oaks <daniel@danieloaks.net>
# licensed under the BSD 2-clause license

import sys

from gbot.libs.girclib import escape, remove_control_codes

if len(sys.argv) < 2:
    print('USAGE:')
    print('\t', sys.argv[0], '<logfile>')
    exit()

oldlog = open(sys.argv[1], 'r', encoding='utf8')
newlog = open(sys.argv[1] + '.new', 'w', encoding='utf8')

line = escape(oldlog.readline())

while line != '':
    new_line = remove_control_codes(line)

    newlog.write(new_line)
    line = escape(oldlog.readline())
    new_line = ''

oldlog.close()
newlog.close()
