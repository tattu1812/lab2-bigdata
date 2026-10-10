#!/usr/bin/env bash

export NS="${NS:-bd-g01}"
export STORE_ID="${STORE_ID:-${NS}-objects}"

export S3_ENDPOINT="http://objects:8333"
export RAW_BUCKET="research-raw"
export RELEASE_BUCKET="research-release"

export INPUT_PREFIX="lab2/inputs/batch-01"
export STAGING_PREFIX="lab2/staging"
export RELEASE_PREFIX="lab2/releases"

export SCHEMA_VERSION="research-telemetry-v1"
export AS_OF="2026-02-09T00:00:00Z"
