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
        echo "[Error] Could not download parrot" >&2
        exit 210
    fi
}

populate(){
    if [ ! -x "$_CONDOR_SCRATCH_DIR/parrot_static_run" ]; then get_parrot; fi
    mkdir -p "$_CONDOR_SCRATCH_DIR/$reana_workflow_dir"
    local parent="$(dirname $reana_workflow_dir)"
    $_CONDOR_SCRATCH_DIR/parrot_static_run -T 30 cp --no-clobber -r "/chirp/CONDOR/$reana_workflow_dir" "$_CONDOR_SCRATCH_DIR/$parent"
}

find_module(){
    module > /dev/null 2>&1
    if [ $? == 0 ]; then
        return 0
    elif [ -e /etc/profile.d/modules.sh ]; then
        source /etc/profile.d/modules.sh
    fi
    module > /dev/null 2>&1
    return $?
}

# Discover the container technology available.
# Currently searching for: Singularity or Shifter.
# Returns 0: Successful discovery of a container
#         1: Couldn't find a container
find_container(){
    declare -a search_list=("singularity" "shifter")
    declare -a module_list=(singularity tacc-singularity shifter)
    declare -a found_list=()
    local default="singularity"

    for cntr in "${search_list[@]}"; do
        cntr_path="$(which $cntr 2>/dev/null)"
        if [[ -x "$cntr_path" ]] # Checking binaries in path
        then
            if [ "$(basename "$cntr_path")" == "$default" ]; then 
                container_path="$cntr_path"
                return 0
            else
                found_list+=("$cntr_path")
            fi
        fi
        # Checking if modules are available
        find_module
        if [ $? == 0 ];then
            for var in ${MODULE_LIST[*]}; do
                module load $var 2>/dev/null
                var_path="$(which $var 2>/dev/null)"
                if [ "$(basename "$var_path")" == "$default" ]; then
                    container_path="$var_path"
                    return 0
                else
                    found_list+=("$var_path")
                fi
            done
        fi
    done

    # If default wasn't found but a container was found, use that
    if (( "${#found_list[@]}" >= 1 )); then
        container_path=${found_list[0]}
        return 0
    else
        return 1 # No containers found
    fi
}

######## Setup environment #############
# @TODO: This should be done in a prologue
# in condor via +PreCmd, eventually.
#############################
# Send cache to $SCRATCH or to the condor scratch directory
# otherwise
if [ "x$SCRATCH" == "x" ]; then
    export SINGULARITY_CACHEDIR="$_CONDOR_SCRATCH_DIR"
else
    export SINGULARITY_CACHEDIR="$SCRATCH"
fi

find_container
if [ $? != 0 ]; then
    echo "[Error]: Container technology could not be found in the sytem." >&2
    exit 127
fi
populate

######## Execution ##########
# exec "$singularity_path" "$@"
# Note: Double quoted arguments are broken
# and passed as multiple arguments
# in bash for some reason, working that
# around by dumping command to a
# temporary wrapper file.
tmpjob=$(mktemp -p .)
chmod +x $tmpjob 
echo "$container_path" "$@" > $tmpjob
bash $tmpjob
res=$?
rm $tmpjob

if [ $res != 0 ]; then
    echo "[Error] Execution failed with error code: $res" >&2
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
