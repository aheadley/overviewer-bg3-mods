#!/bin/bash

# default? ~/.steam/steam/steamapps/
DEST_STEAMAPPS_DIR="" # steam library steamapps path
DEST_GAME_DATA_PATH="" # game-install-path/Data
DEST_APPDATA_PATH="" # AppData/Local/Larian Studios/Baldur's Gate 3

SRC_BASE_PATH="$(pwd)"
SRC_GAME_DATA_PATH="${SRC_BASE_PATH}/Data"
SRC_APPDATA_PATH="${SRC_BASE_PATH}/Baldur's Gate 3"


function print_usage {
    echo "Usage: $0 <DEST_STEAMAPPS_DIR>"
}

function error_out {
    local error_type="${1:=E_UNKNOWN}"
    local error_msg="${2:=Unknown Error}"
    local exit_code="${3:=1}"

    echo "${error_type}: ${error_msg}"
    if [ "$exit_code" -le 2 ]; then
        print_usage
    fi
    exit "$exit_code"
}

function check_src_paths {
    if [ -z "${SRC_APPDATA_PATH}" ] || [ ! -d "${SRC_APPDATA_PATH}" ]; then
        error_out "E_INVALID_PATH: Invalid source appdata path: ${SRC_APPDATA_PATH}" 2
    fi
    if [ -z "${SRC_GAME_DATA_PATH}" ] || [ ! -d "${SRC_GAME_DATA_PATH}" ]; then
        error_out "E_INVALID_PATH: Invalid source game data path: ${SRC_GAME_DATA_PATH}" 2
    fi
}

function set_dest_paths {
    DEST_STEAMAPPS_DIR="$1"
    if [ -z "${DEST_STEAMAPPS_DIR}" ]; then
        error_out "E_INVALID_PATH" "No steamapps dir given" "2"
    fi
    if [ ! -d "${DEST_STEAMAPPS_DIR}" ]; then
        error_out "E_INVALID_PATH" "Path is not a directory: ${DEST_STEAMAPPS_DIR}" "2"
    fi

    DEST_GAME_DATA_PATH="${DEST_STEAMAPPS_DIR}/common/Baldurs Gate 3/Data"
    if [ ! -d "${DEST_GAME_DATA_PATH}" ]; then
        error_out "E_INVALID_PATH" "Path is not a directory: ${DEST_GAME_DATA_PATH}" "2"
    fi

    DEST_APPDATA_PATH="${DEST_STEAMAPPS_DIR}/compatdata/1086940/pfx/drive_c/users/steamuser/AppData/Local/Larian Studios/Baldur's Gate 3"
    if [ ! -d "${DEST_APPDATA_PATH}" ]; then
        error_out "E_INVALID_PATH" "Path is not a directory: ${DEST_APPDATA_PATH}" "2"
    fi
}

function sync_src_to_dest {
    local src="$1"
    local dest="$2"
    echo "Syncing: '${src}' to '${dest}'"
    rsync -avxh "$src" "$dest" || error_out E_SYNC_FAIL "Failed to sync '${src}' to '${dest}'" 3
}

function deploy_to_dest {
    sync_src_to_dest "${SRC_APPDATA_PATH}/" "${DEST_APPDATA_PATH}/"
    sync_src_to_dest "${SRC_GAME_DATA_PATH}/" "${DEST_GAME_DATA_PATH}/"
}

function main {
    if [[ "$1" == *"-h"* ]]; then
        print_usage
    else
        check_src_paths
        set_dest_paths "$*"
        deploy_to_dest
    fi
}

main "$*"
