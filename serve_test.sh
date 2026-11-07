#!/usr/bin/env bash
set -euo pipefail

/bin/bash -e ./install_test.sh
./test_project/task.sh documentation:serve
