#!/usr/bin/env bash
#
# Exit the shell script immediately if any of the subsequent commands fails.
# immediately
set -e
#

# TODO: Major and the coverage tools should be moved to framework/lib
################################################################################
# This script initializes Defects4J. In particular, it downloads and sets up:
# - the project's version control repositories
# - the Major mutation framework
# - the supported test generation tools
# - the supported code coverage tools (TODO)
################################################################################

HOST_URL="https://defects4j.org/downloads"

# Directories for project repositories and external libraries
BASE="$(cd "$(dirname "$0")"; pwd)"
DIR_REPOS="$BASE/project_repos"
DIR_LIB_GEN="$BASE/framework/lib/test_generation/generation"
DIR_LIB_RT="$BASE/framework/lib/test_generation/runtime"
DIR_LIB_GRADLE="$BASE/framework/lib/build_systems/gradle"

################################################################################

main() {
    echo "Checking system configuration ... "
    # Check whether wget is available on OSX
    if [ "$(uname)" = "Darwin" ] ; then
        if ! wget --version > /dev/null 2>&1; then
            print_error_and_exit "Couldn't find wget to download dependencies. Please install wget and re-run this script."
        fi
    fi
    
    # Check whether curl is available
    if ! curl --version > /dev/null 2>&1; then
        print_error_and_exit "Couldn't find curl to download dependencies. Please install curl and re-run this script."
    fi
    
    # Check whether unzip is available
    if ! unzip -v > /dev/null 2>&1; then
        print_error_and_exit "Couldn't find unzip to extract dependencies. Please install unzip and re-run this script."
    fi

    # Create lib folders if necessary
    mkdir -p "$DIR_LIB_GEN" && mkdir -p "$DIR_LIB_RT" && mkdir -p "$DIR_LIB_GRADLE"

    ############################################################################
    #
    # Download project repositories if necessary
    #
    echo "Setting up project repositories ... "
    cd "$DIR_REPOS" && ./get_repos.sh

    ############################################################################
    #
    # Download Major
    #
    # Adapt Major's default wrapper scripts:
    # - set headless to true to support Chart on machines without X.
    # - do not mutate code unless an MML is specified (for historical reasons,
    #   major v1 was sometimes called without specifying an MML to simply act as
    #   javac; Major v2+'s default is to generate all mutants as opposed to none).
    #
    echo
    echo "Setting up Major ... "
    MAJOR_VERSION="3.0.1"
    MAJOR_URL="https://mutation-testing.org/downloads"
    MAJOR_ZIP="major-${MAJOR_VERSION}_jre11.zip"
    cd "$BASE" && rm -rf major \
               && download_url_and_unzip "$MAJOR_URL/$MAJOR_ZIP" \
               && rm "$MAJOR_ZIP" \
               && perl -pi -e '$_ .= qq(    -Djava.awt.headless=true \\\n) if /CodeCacheSize/' \
                    major/bin/ant \
               && perl -pi -e '$_ .= qq(\nif [ -z "\$MML" ]; then javac \$*; exit \$?; fi\n) if /^REFACTOR=/' \
                    major/bin/major \
               && perl -pi -e '$_ = qq(REFACTOR=\${REFACTOR:-"enable.decl.refactor enable.method.refactor"}\n) if /^REFACTOR=/' \
                    major/bin/major \

    ############################################################################
    #
    # Download EvoSuite
    #
    echo
    echo "Setting up EvoSuite ... "
    EVOSUITE_VERSION="1.1.0"
    EVOSUITE_URL="https://github.com/EvoSuite/evosuite/releases/download/v${EVOSUITE_VERSION}"
    EVOSUITE_JAR="evosuite-${EVOSUITE_VERSION}.jar"
    EVOSUITE_RT_JAR="evosuite-standalone-runtime-${EVOSUITE_VERSION}.jar"
    cd "$DIR_LIB_GEN" && download_url "$EVOSUITE_URL/$EVOSUITE_JAR"
    cd "$DIR_LIB_RT"  && download_url "$EVOSUITE_URL/$EVOSUITE_RT_JAR"
    # Set symlinks for the supported version of EvoSuite
    (cd "$DIR_LIB_GEN" && ln -sf "$EVOSUITE_JAR" "evosuite-current.jar")
    (cd "$DIR_LIB_RT" && ln -sf "$EVOSUITE_RT_JAR" "evosuite-rt.jar")

    ############################################################################
    #
    # Download Randoop
    #
    echo
    echo "Setting up Randoop ... "
    RANDOOP_VERSION="4.3.4"
    RANDOOP_URL="https://github.com/randoop/randoop/releases/download/v${RANDOOP_VERSION}"
    RANDOOP_ZIP="randoop-${RANDOOP_VERSION}.zip"
    RANDOOP_JAR="randoop-all-${RANDOOP_VERSION}.jar"
    REPLACECALL_JAR="replacecall-${RANDOOP_VERSION}.jar"
    COVEREDCLASS_JAR="covered-class-${RANDOOP_VERSION}.jar"
    (cd "$DIR_LIB_GEN" && download_url_and_unzip "$RANDOOP_URL/$RANDOOP_ZIP")
    # Set symlink for the supported version of Randoop
    (cd "$DIR_LIB_GEN" && ln -sf "randoop-${RANDOOP_VERSION}/$RANDOOP_JAR" "randoop-current.jar")
    (cd "$DIR_LIB_GEN" && ln -sf "randoop-${RANDOOP_VERSION}/$REPLACECALL_JAR" "replacecall-current.jar")
    (cd "$DIR_LIB_GEN" && ln -sf "randoop-${RANDOOP_VERSION}/$COVEREDCLASS_JAR" "covered-class-current.jar")
    (cd "$DIR_LIB_GEN" && ln -sf "randoop-${RANDOOP_VERSION}/jacocoagent.jar" "jacocoagent.jar")
}
