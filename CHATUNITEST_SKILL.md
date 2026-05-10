# ChatUniTest to Defects4J Evaluation Workflow

## Objective
Establish an isolated Conda environment containing Java 11 and Perl, compile the core and Maven plugin for ChatUniTest, apply it to a benchmark project from Defects4J (e.g., Lang), and retrieve the test generation pass rate and statistics.

## Prerequisites
- Conda installed on the Linux system.
- OpenAI API Key (for ChatUniTest execution).

## Step-by-Step Process

### 1. Environment Setup (Conda)
Create a clean Conda environment resolving conflicts between ChatUniTest and Defects4J dependencies.
- **Java Requirement:** Defects4J currently requires **Java 11**. Critical Note: JDK versions must include a decimal point (e.g., `11.0.0`) to avoid Maven build errors.
- **Perl Requirement:** Defects4J requires Perl and `cpanm` to install `cpanfile` dependencies.

```bash
conda create -n chatunitest_env -c conda-forge openjdk=11.0 perl perl-app-cpanminus -y
conda activate chatunitest_env
```

### 2. Defects4J Initialization
Defects4J requires specific initialization before use.
```bash
cd /home/red_pandaymh/HieraTest/defects4j-master
cpanm --installdeps .
./init.sh
export PATH=$PATH:"/home/red_pandaymh/HieraTest/defects4j-master/framework/bin"
```

### 3. Compile ChatUniTest Modules
Compile the core library first, then the Maven plugin.
```bash
# 1. Compile core
cd /home/red_pandaymh/HieraTest/chatunitest-core
mvn clean install

# 2. Compile Maven plugin
cd /home/red_pandaymh/HieraTest/chatunitest
mvn clean install
```

### 4. Defects4J Project Checkout (e.g., Lang)
Checkout a buggy version of a benchmark project.
```bash
# Checkout Lang bug 1, buggy version (1b)
defects4j checkout -p Lang -v 1b -w /tmp/lang_1_buggy
cd /tmp/lang_1_buggy
defects4j compile
```

### 5. Configure ChatUniTest in the Target Project
Modify the `pom.xml` in `/tmp/lang_1_buggy` to include the `chatunitest-starter` dependency and `chatunitest-maven-plugin` configuration.
- Add Starter dependency (version `1.4.0`).
- Add Plugin configuration, including `<apiKeys>`.

### 6. Run ChatUniTest Generation
Execute the maven plugin to generate tests for the class or project.
```bash
# Generate tests for a specific class (example)
mvn chatunitest:class -DselectClass=TargetClassName

# OR generate for the whole project (WARNING: consumes high tokens)
mvn chatunitest:project
```

### 7. Collect and Evaluate Results
- Move generated tests into the target testing folder using `mvn chatunitest:copy`.
- Run the tests within the Defects4J environment to verify pass rate and defect triggering:
```bash
defects4j test
defects4j coverage
```
- Aggregate terminal test results, generation pass rate, and coverage outputs, and report back to the user.
