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

######## Setup environment #############
# @TODO: This should be done in a prologue
# in condor via +PreCmd, eventually.
#############################
# Export HOME to condor scratch directory
export SINGULARITY_CACHEDIR=$_CONDOR_SCRATCH_DIR

populate
find_singularity
if [ $? != 0 ]; then
    echo "[Error]: Singularity could not be found in the sytem." >&2
    exit 127
fi

######## Execution ##########
# exec "$singularity_path" "$@"
# Note: Double quoted arguments are broken
# and passed as multiple arguments
# in bash for some reason, working that
# around by dumping command to a
# temporary wrapper file.
tmpjob=$(mktemp -p .)
chmod +x $tmpjob 
echo "$singularity_path" "$@" > $tmpjob
exec bash $tmpjob
res=$?
rm $tmpjob

###### Stageout ###########
# TODO: This shoul be done in an epilogue
# via +PostCmd, eventually.
# Not implemented yet
# Stage out depending on the protocol
# E.g.:
# - file: will be transferred via condor_chirp
# - xrootd://<redirector:port>//store/user/path:file: will be transferred via XRootD
# Dependencies could be handled via vc3-builder
# E.g.: vc3-builder --require xrootd <stageout cmd>


exit $res
