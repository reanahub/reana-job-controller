#!/bin/bash

######## Execution ##########
# Note: Double quoted arguments are broken
# and passed as multiple arguments
# in bash for some reason, working that
# around by dumping command to a
# temporary wrapper file.
tmpjob=$(mktemp -p .)
chmod +x $tmpjob
echo "command to execute:" $@
echo  "$@" > $tmpjob
bash $tmpjob
res=$?
rm $tmpjob

if [ $res != 0 ]; then
    echo "[Error] Execution failed with error code: $res"
    exit $res
fi
