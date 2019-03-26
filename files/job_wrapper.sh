#! /bin/bash

# Replicate input files directory structure
# @TODO: This could be executed 
# in +PreCmd as a separate script.
populate(){
    inputlist=$(cat $_CONDOR_JOB_AD  | grep "TransferInput =" | awk '{print $3}'| sed -e 's/^"//' -e 's/"$//')
    IFS=',' read -r -a inputs <<< "$inputlist"
    for file in "${inputs[@]}"; do
        filepath=$(dirname "$file")
        filename=$(basename "$file")
        mkdir -p "$_CONDOR_SCRATCH_DIR/$filepath"
        if [ -e "$filename" ]; then
            mv "$filename" "$_CONDOR_SCRATCH_DIR/$filepath"
        fi
    done
}

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

populate
find_singularity
if [ $? != 0 ]; then
    echo "[Error]: Singularity could not be found in the sytem." >&2
    exit 127
fi

$singularity_path "$@"
