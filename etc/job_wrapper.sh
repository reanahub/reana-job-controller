#!/bin/bash

######## Execution ##########
# Note: Double quoted arguments are broken
# and passed as multiple arguments
# in bash for some reason, working that
# around by dumping command to a
# temporary wrapper file.
tmpjob=$(mktemp -p .)
chmod +x "$tmpjob"
echo "command to execute:"
# $@ input is base64 encoded string of command to execute
# shellcheck disable=SC2068,SC2294
eval $@

echo "$@" "|bash" >"$tmpjob"
bash "$tmpjob"
res=$?
rm "$tmpjob"

if [ $res != 0 ]; then
    echo "[Error] Execution failed with error code: $res"
    exit $res
fi
