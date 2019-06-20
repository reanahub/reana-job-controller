#!/bin/bash

# Replicate input files directory structure
# @TODO: This could be executed 
# in +PreCmd as a separate script.

# Expected arguments from htcondor_job_manager:
# $1: workflow_workspace
# $2: DOCKER_IMG
# $3 -> : cmd 

# Defining inputs
DOCKER_IMG=$2
REANA_WORKFLOW_DIR=$1

# Get static version of parrot.
# Note: We depend on curl for this.
# Assumed to be available on HPC worker nodes (might need to transfer a static version otherwise).
get_parrot(){
    curl --retry 5 -o parrot_static_run http://download.virtualclusters.org/builder-files/parrot_static_run_v7.0.11 > /dev/null 2>&1 
    if [ -e "parrot_static_run" ]; then
        chmod +x parrot_static_run
    else
        echo "[Error] Could not download parrot" >&2
        exit 210
    fi
}

populate(){
    if [ ! -x "$_CONDOR_SCRATCH_DIR/parrot_static_run" ]; then get_parrot; fi
    mkdir -p "$_CONDOR_SCRATCH_DIR/$REANA_WORKFLOW_DIR"
    local parent="$(dirname $REANA_WORKFLOW_DIR)"
    $_CONDOR_SCRATCH_DIR/parrot_static_run -T 4 cp --no-clobber -r "/chirp/CONDOR/$REANA_WORKFLOW_DIR" "$_CONDOR_SCRATCH_DIR/$parent"
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
    declare -a found_list=()
    local default="shifter"
    local cont_found=false
    

    for cntr in "${search_list[@]}"; do
        cntr_path="$(command -v $cntr)"
        if [[ -x "$cntr_path" ]] # Checking binaries in path
        then
            if [ "$(basename "$cntr_path")" == "$default" ]; then 
                CONTAINER_PATH="$cntr_path"
                return 0
            else
                found_list+=("$cntr_path")
                cont_found=true
            fi
        fi
    done
    # If VC3 didn't automatically load a module (fail-safe)
    if [ ! "$cont_found" ]; then
        for cntr in "${search_list[@]}"; do
            find_module
            module_found=$?
            if [ $module_found == 0 ]; then
                for var in ${search_list[*]}; do
                    module load $var 2>/dev/null
                    var_path="$(command -v $var 2>/dev/null)"
                    if [ "$(basename "$var_path")" == "$default" ]; then
                        CONTAINER_PATH="$var_path"
                        return 0
                    else
                        found_list+=("$var_path")
                        cont_found=true
                    fi
                done
            fi
        done
    fi

    # If default wasn't found but a container was found, use that
    if (( "${#found_list[@]}" >= 1 )); then
        CONTAINER_PATH=${found_list[0]}
        return 0
    else
        return 1 # No containers found
    fi
}

# Setting up cmd line args for singularity
# Print's stdout the argument line for running singularity utilizing
setup_singularity(){
    # TODO: Cleanup calling of this function

    # Send cache to $SCRATCH or to the condor scratch directory
    # otherwise
    if [ -z "$SCRATCH" ]; then
        CONTAINER_ENV="SINGULARITY_CACHEDIR=\"\$_CONDOR_SCRATCH_DIR\""
    else
        CONTAINER_ENV="SINGULARITY_CACHEDIR=\"\$SCRATCH\""
    fi

    CNTR_ARGUMENTS="exec -B ./$REANA_WORKFLOW_DIR:$REANA_WORKFLOW_DIR docker://$DOCKER_IMG"

}

# Setting up shifter. Pull the docker_img into the shifter image gateway
# and dump required arguments into stdout to be collected by a function call
setup_shifter(){
    #TODO: Cleanup calling of this function
    # Check for shifterimg
    if [[ ! $(command -v shifterimg 2>/dev/null) ]]; then
        echo "Error: shifterimg not found..." >&2
        exit 127
    fi

    # Attempt to pull image into image-gateway
    if ! shifterimg pull "$DOCKER_IMG" >/dev/null 2>&1; then
        echo "Error: Could not pull img: $DOCKER_IMG" >&2 
        exit 127
    fi

    # Put arguments into stdout to collect.
    echo "--image=docker:${DOCKER_IMG} --volume=$(pwd -P)/reana:/reana -- "
}

# Setting up the arguments to pass to a container technology.
# Currently able to setup: Singularity and Shifter.
# Creates cmd line arguements for containers and pull image if needed (shifter)
# Global arguments is used as the arguments to a container
setup_container(){
    # Need to cleanup to make more automated.
    # i.e. run through the same list in find_container
    local container=$(basename "$CONTAINER_PATH")

    if [ "$container" == "singularity" ]; then
        setup_singularity 
    elif [ "$container" == "shifter" ]; then
        CNTR_ARGUMENTS=$(setup_shifter)
    else
        echo "Error: Unrecognized container: $(basename $CONTAINER_PATH)" >&2
        exit 127
    fi
}

######## Setup environment #############
# @TODO: This should be done in a prologue
# in condor via +PreCmd, eventually.
#############################

find_container
if [ $? != 0 ]; then
    echo "[Error]: Container technology could not be found in the sytem." >&2
    exit 127
fi
populate
setup_container

######## Execution ##########
# Note: Double quoted arguments are broken
# and passed as multiple arguments
# in bash for some reason, working that
# around by dumping command to a
# temporary wrapper file named tmpjob.
tmpjob=$(mktemp -p .)
chmod +x $tmpjob 
if command -v aprun; then
    echo -n "aprun -b -n 1 -- " > $tmpjob
fi

echo "$CONTAINER_ENV" "$CONTAINER_PATH" "$CNTR_ARGUMENTS" "${@:3} " >> $tmpjob
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
# and write them into $REANA_WORKFLOW_DIR
# Stage out depending on the protocol
# E.g.:
# - file: will be transferred via condor_chirp
# - xrootd://<redirector:port>//store/user/path:file: will be transferred via XRootD
# Only chirp transfer supported for now.
# Use vc3-builder to get a static version
# of parrot (eventually, a static version
# of the chirp client only).
if [ "x$REANA_WORKFLOW_DIR" == "x" ]; then
    echo "[Info]: Nothing to stage out"
    exit $res
fi

parent="$(dirname $REANA_WORKFLOW_DIR)"
# TODO: Check for parrot exit code and propagate it in case of errors.
./parrot_static_run -T 4 cp --no-clobber -r "$_CONDOR_SCRATCH_DIR/$REANA_WORKFLOW_DIR" "/chirp/CONDOR/$parent"

exit $res
