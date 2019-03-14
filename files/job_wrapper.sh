#! /bin/bash

# Discover singularity binary path
# by trying different methods


find_singularity(){
    # Method 1: Find in environment
    singularity_path="$(which singularity 2>/dev/null)"
    if [ "x$singularity_path" != "x" ]; then return 0; fi
    
    # Method 2: Use module, then find in environment
    alias module 2>/dev/null
    if [ $? == 0 ];then
        MODULE_LIST=(singularity tacc-singularity)
        for var in ${MODULE_LIST[*]}; do
            module load $var 2>/dev/null
            singularity_path="$(which singularity 2>/dev/null)"
            if [ "x$singularity_path" != "x"]; then return 0; fi
        done
    fi

    return 1
}

find_singularity
if [ $? != 0 ]; then
    echo "[Error]: Singularity could not be found in the sytem." >&2
    exit 127
fi

$singularity_path "$@"
