#!/usr/bin/env python3
import os
import sys
import subprocess
import argparse
from glob import glob
import xml.etree.ElementTree as ET
import json
import shlex




class TestSummary:
    """Class for storing the test summary"""

    def __init__(self, total=0, errors=0, failures=0, skipped=0):
        """Initialize with default values"""

        self.total = total
        self.errors = errors
        self.failures = failures
        self.skipped = skipped

    @classmethod
    def fromString(cls, summary_str):
        """Initialize from string"""

        # summary string format: 'Summary: 6 tests, 1 errors, 2 failures, 3 skipped'
        try:
            # list format: ['6 tests', ' 1 errors', ' 2 failures', ' 3 skipped']
            summary_list = summary_str.strip('Summary: ').split(',')

            total = summary_list[0].strip().split(' ')[0]
            errors = summary_list[1].strip().split(' ')[0]
            failures = summary_list[2].strip().split(' ')[0]
            skipped = summary_list[3].strip().split(' ')[0]

        except:
            print('Test summary error: bad format')
            total = -1
            errors = -1
            failures = -1
            skipped = -1

        finally:
            return cls(total, errors, failures, skipped)

    def toDict(self):
        """Convert to dictionary"""

        return {
            'total': self.total,
            'errors': self.errors,
            'failures': self.failures,
            'skipped': self.skipped
        }





class Package:
    """Class to store package information"""

    def __init__(self, name, path='', summary=TestSummary(), has_test=None, out='', err='', is_metapackage=None):
        """Initialization"""

        self.name = name
        self.path = path
        self.summary = summary
        self.out = out
        self.err = err
        self.is_metapackage = is_metapackage
        self.has_test = has_test
        self.execution_status = ''
        self.use_branch_coverage = '0'
        self.coverage = 0

        if is_metapackage == None:
            self.is_metapackage = self.isMetapackage()

        if has_test == None:
            self.has_test = self.hasTest()


    def setSummary(self, summary):
        """Set test summary"""

        if isinstance(summary, str):
            self.summary = TestSummary.fromString(summary)
        elif isinstance(summary, TestSummary):
            self.summary = summary
        else:
            print('Error initializing test summary: wrong format')


    def setExecutionStatus(self, return_code):
        """Set test status given the resturn code
        0 - success
        not 0 - fail
        """
        if return_code == 0:
            self.execution_status = 'executed'
        else:
            self.execution_status = 'failed'


    def toDict(self):
        """Convert object to dictionary"""

        return {
            'name': self.name,
            'path': self.path,
            'has_test': self.has_test,
            'summary': self.summary.toDict(),
            # 'out': self.out,
            # 'err': self.err,
            'is_metapackage': self.is_metapackage
        }


    def isMetapackage(self):
        """Search CMakeLists.txt to determine if is a metapackage
        
        Returns true if the package is defined as a metapackage 
        """
        cmake_file = os.path.join(self.path, 'CMakeLists.txt')
        with open(cmake_file, 'r') as file:
            lines = file.read()

        return 'catkin_metapackage' in lines


    
    def hasTest(self):
        """Search CMakeLists.txt to determine if there are tests defined"""

        self.has_test = False
        cmake_file = os.path.join(self.path, 'CMakeLists.txt')
        with open(cmake_file, 'r') as file:
            lines = file.read().split()

        for line in lines:
            line = line.strip()
            if line.startswith('#'): 
                line = ''
            if 'catkin_add_gtest' in line or 'add_rostest_gtest' in line:
                self.has_test = True
                break        

        return self.has_test 


    def run_lcov_cmd(self, params):
        cmd = ['lcov']
        cmd.extend(shlex.split(params))

        process = subprocess.Popen(cmd,
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE,
                        universal_newlines=True)

        stdout, stderr = process.communicate()

        return stdout, stderr


    def build_for_coverage(self):
        """Build package with test coverage required flags"""

        extra_parms = '--cmake-args -DCMAKE_CXX_FLAGS="-g -O0 -Wall -fprofile-arcs -ftest-coverage" -DCMAKE_EXE_LINKER_FLAGS="-fprofile-arcs -ftest-coverage"'
        cmd = ['catkin', 'build', self.name ]
        cmd.extend(shlex.split(extra_parms))

        process = subprocess.Popen(cmd,
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE,
                        universal_newlines=True)

        process.communicate()

        return process.returncode


    def run_test_coverage(self, build=False):
        """Run unit tests with test coverage parameters"""

        # print('Running unit tests for package %s' % package)
        if self.is_metapackage:
            self.out = 'This is a metapackage'
            return 0

        if not self.has_test:
            self.out = 'No tests defined on CMakeLists.txt'
            return 0

        if build:
            self.build_for_coverage()            

        # Capture initial zero coverage data
        self.run_lcov_cmd('--rc lcov_branch_coverage=' + self.use_branch_coverage + ' --directory build --zerocounters')
        self.run_lcov_cmd('--rc lcov_branch_coverage=' + self.use_branch_coverage + ' --capture --initial --directory build/' + self.name + ' --output-file build/lcov.base')

        # Run tests with coverage flags
        extra_parms = '--no-deps --cmake-args -DCMAKE_CXX_FLAGS="-g -O0 -Wall -fprofile-arcs -ftest-coverage" -DCMAKE_EXE_LINKER_FLAGS="-fprofile-arcs -ftest-coverage"'
        cmd = ['catkin', 'run_tests', self.name]
        cmd.extend(shlex.split(extra_parms))

        process = subprocess.Popen(cmd,
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE,
                        universal_newlines=True)

        self.out , self.err = process.communicate()

        self.setSummary(self.get_test_summary())
        self.setExecutionStatus(process.returncode)

        if process.returncode != 0:
            return process.returncode

        # Capture coverage data after running tests
        self.run_lcov_cmd('--rc lcov_branch_coverage=' + self.use_branch_coverage + ' --no-checksum --directory build/' + self.name + ' --capture --output-file build/lcov.info')

        # Add baseline counters
        out, err = self.run_lcov_cmd('--rc lcov_branch_coverage=' + self.use_branch_coverage + ' --add-tracefile build/lcov.base --add-tracefile build/lcov.info --output-file build/lcov.total')

        # Remove coverage data for a particular set of files from the tracefile
        out, err = self.run_lcov_cmd('--rc lcov_branch_coverage=' + self.use_branch_coverage + ' --remove build/lcov.total /usr* /opt* */test/* */CMakeFiles/* */build/* --output-file build/lcov.total.cleaned')
        
        # Extract line coverage from output
        if 'lines......:' in out:
            self.coverage = float(out.split('lines......: ')[1].split('%')[0])
        else:
            self.coverage = 0

        return 0


    def run_test(self):
        """Run unit tests"""

        # print('Running unit tests for package %s' % package)
        if self.is_metapackage:
            self.out = 'This is a metapackage'
            return 0

        if not self.has_test:
            self.out = 'No tests defined on CMakeLists.txt'
            return 0
        
        extra_parms = '--no-deps --make-args -s -- --catkin-make-args run_tests --make-args tests'.split(' ')
        cmd = ['catkin', 'build', self.name]
        cmd.extend(extra_parms)

        process = subprocess.Popen(cmd,
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE,
                        universal_newlines=True)

        self.out , self.err = process.communicate()

        self.setSummary(self.get_test_summary())
        self.setExecutionStatus(process.returncode)

        return process.returncode


    def get_test_summary(self):
        """Get summary from catkin_test_results"""

        last_line = 'None'
        cmd = ['catkin_test_results', 'build/%s' % self.name ]
        try:
            process = subprocess.Popen(cmd,
                            stdout=subprocess.PIPE, 
                            stderr=subprocess.PIPE,
                            universal_newlines=True)
            stdout, stderr = process.communicate()
            # Extract the summary line
            # Summary: 0 tests, 0 errors, 0 failures, 0 skipped
            last_line = stdout.strip().split('\n')[-1]
        finally:
            return last_line


def get_packages(path):
    """Traverse a given directory and returns all package.xml found
    
    Returns a list of Package objects
    """

    files = [y for x in os.walk(path) for y in glob(os.path.join(x[0], 'package.xml'))]
    packages = []
    for file in files:
        tree = ET.parse(file)
        root = tree.getroot()

        name = root.find('name').text
        path = os.path.dirname(os.path.abspath(file))
        
        packages.append(Package(name, path))

    return packages


def print_table_header():
    """Print output header"""

    double_line = '='*169
    header = '{} \t {} \t {} \t {} \t {} \t {} \t {} \t {} \t {}'.format(
            'Package name'.ljust(40),
            'is metapkg?'.ljust(10),
            'has tests?'.ljust(10),
            'status'.ljust(10),
            'total'.ljust(10),
            'errors'.ljust(10),
            'failures'.ljust(10),
            'skipped'.ljust(10),
            'coverage'.ljust(10))

    print(double_line)
    print(header) 
    print(double_line)

    if args.output:
        with open(args.output, 'a') as f:
            f.write(double_line + '\n')
            f.write(header + '\n')
            f.write(double_line + '\n')


def print_table_row(package):
    """Print package test summary"""

    row = '{} \t {} \t {} \t {} \t {} \t {} \t {} \t {} \t {}'.format(
        package.name.ljust(40),
        str(package.is_metapackage).ljust(10),
        str(package.has_test).ljust(10),
        str(package.execution_status).ljust(10),
        str(package.summary.total).ljust(10),
        str(package.summary.errors).ljust(10),
        str(package.summary.failures).ljust(10),
        str(package.summary.skipped).ljust(10),
        (str(package.coverage) + '%').ljust(10),
    )

    print(row) 
    if args.output:
        with open(args.output, 'a') as f:
            f.write(row + '\n')



def run_test(package):
    if args.cov:
        ret = package.run_test_coverage(args.build)
    else:
        ret = package.run_test()
    if package.has_test:
        print_table_row(package)

    if ret != 0:
        print("Test returned a non-zero code (" + ret + ")")
        print(package.err)

    return ret


def main(args):
    packages = get_packages(args.path)    
    print_table_header()
    ret_list = map(run_test, packages)
    sys.exit(sum(ret_list))

    
if __name__ == "__main__":
   parser = argparse.ArgumentParser(usage='%(prog)s <command> [<options> ...]')
   parser.add_argument('path', help='Source code path')
   parser.add_argument('--cov', help='Use test coverage', action='store_true')
   parser.add_argument('--build', help='Build project using code coverage flags', action='store_true')
   parser.add_argument('-o', '--output', help='Write test summary to file')
   args = parser.parse_args()

   main(args)

