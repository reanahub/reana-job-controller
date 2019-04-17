#! /bin/bash

# Replicate input files directory structure
# @TODO: This could be executed 
# in +PreCmd as a separate script.

# Get static version of parrot.
# Note: We depend on curl for this.
# Assumed to be available on HPC worker nodes (might need to transfer a static version otherwise).
get_parrot(){
    curl --retry 5 -o parrot_static_run http://download.virtualclusters.org/builder-files/parrot_static_run_v7.0.11
    if [ -e "parrot_static_run" ]; then
        chmod +x parrot_static_run
    else
        echo "[Error] Could not download parrot"
        exit 210
    fi
}

populate(){
    if [ ! -x "$_CONDOR_SCRATCH_DIR/parrot_static_run" ]; then get_parrot; fi
    mkdir -p "$_CONDOR_SCRATCH_DIR/$reana_workflow_dir"
    local parent="$(dirname $reana_workflow_dir)"
    $_CONDOR_SCRATCH_DIR/parrot_static_run -T 30 cp --no-clobber -r "/chirp/CONDOR/$reana_workflow_dir" "$_CONDOR_SCRATCH_DIR/$parent"
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
bash $tmpjob
res=$?
rm $tmpjob

if [ $res != 0 ]; then
    echo "[Error] Execution failed with error code: $res"
    exit $res
fi

###### Stageout ###########
# TODO: This shoul be done in an epilogue
# via +PostCmd, eventually.
# Not implemented yet.
# Read files from $reana_workflow_outputs
# and write them into $reana_workflow_dir
# Stage out depending on the protocol
# E.g.:
# - file: will be transferred via condor_chirp
# - xrootd://<redirector:port>//store/user/path:file: will be transferred via XRootD
# Only chirp transfer supported for now.
# Use vc3-builder to get a static version
# of parrot (eventually, a static version
# of the chirp client only).
if [ "x$reana_workflow_dir" == "x" ]; then
    echo "[Info]: Nothing to stage out"
    exit $res
fi

parent="$(dirname $reana_workflow_dir)"
# TODO: Check for parrot exit code and propagate it in case of errors.
./parrot_static_run -T 30 cp --no-clobber -r "$_CONDOR_SCRATCH_DIR/$reana_workflow_dir" "/chirp/CONDOR/$parent"

exit $res
