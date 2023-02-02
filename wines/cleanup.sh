#!/bin/bash

set -e
# checks that we are in wines directory and exits if we aren't with a warning

if [ ! -f cleanup.sh ]; then
    echo "Please run this script from the wines directory"
    exit 1
fi

# remove all subdirectories
rm -Rf */

# remove all unnecessary files files
rm -f *.bin *.mapping *.xml *.log
