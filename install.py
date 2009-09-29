#!/usr/bin/env python
"""
install.py

This script provides a general installation interface for the genomedata
package. It is designed to be downloaded separately from the genomedata
source. Upon execution, it interacts with the user to setup easy_install,
download and install the necessary dependencies, and download and install
genomedata.

(c) 2009: Orion Buske <orion.buske@gmail.com>
"""

import os
import sys

from urllib import urlretrieve
from string import Template
from subprocess import PIPE, Popen

assert sys.version_info >= (2, 4)

MIN_HDF5_VERSION = (1, 8)
MIN_NUMPY_VERSION = (1, 2)


HDF5_DOWNLOAD_VERSION = (1, 8, 2)  # Should match URL below (displayed to user)
HDF5_URL = "http://www.hdfgroup.org/ftp/HDF5/prev-releases/hdf5-1.8.2/src/hdf5-1.8.2.tar.gz"

EZ_SETUP_URL = "http://peak.telecommunity.com/dist/ez_setup.py"


EASY_INSTALL_PROMPT = "May I install %s and dependencies?"
HDF5_INSTALL_MESSAGE = "\nHDF5 is very large and installation usually takes 5-10 minutes. Please be patient.\nIt is common to see many warnings during compilation."

# Template for cfg file contents
CFG_FILE_TEMPLATE = """
[install]
prefix = $prefix
exec_prefix = $prefix
install_platlib = $platlib
install_purelib = $platlib
install_scripts = $scripts

[easy_install]
install_dir = $platlib
script_dir = $scripts
"""

# One command per line
HDF5_INSTALL_SCRIPT = """
if [ ! -e $file ]; then wget $url -O $file; fi
if [ ! -d $filebase ]; then tar -xzf $file; fi
cd $filebase
./configure --prefix=$dir
make
make install
"""

############################ CLASSES ##########################
class InstallationError(Exception):
    pass

class ShellManager(object):
    """Class to manage details of shells.

    Provides an interface for writing to shell rc files and
    setting and testing environment variables.

    Attributes:
    file: The shell rc file, or None if none known
    has_file: True if there is a known shell rc file
    name: The string name of the shell (e.g. "bash", "csh", etc.)
      or "" if unknown
    """
    def __init__(self, shell=None):
        """Creates a ShellManager given a shell string.

        If shell is None, tries to use environment variable SHELL.
        self.name: basically same as shell, but if shell is None, self.name = ""
        """
        self.name = shell
        if shell is None:
            try:
                shell = os.path.basename(os.environ["SHELL"])
                self.name = shell
            except KeyError:
                self.name = ""
                
        if self.name.endswith("csh"):
            self._env_format = "setenv %s %s"
        elif self.name.endswith("sh"):
            self._env_format = "export %s=%s"
        else:
            self._env_format = "set %s to %s"  # Console output
            
        # What RC file are we using, or are we printing to the terminal?
        if self.name.endswith("sh"):
            self.file = os.path.join("~", ".%src" % shell)
        else:
            self.file = None  # Print to terminal
            if shell is None:
                print >>sys.stderr, "SHELL variable missing or confusing."
            else:
                print >>sys.stderr, "Unrecognized shell: %s" % shell
            
        if self.file is None:
            print "Shell-specific commands will be printed to the terminal"
            
        self._out = None  # Output file not yet open
        self.has_file = (self.file is not None)
        
    def set_rc_env(self, variable, value):
        """Write the given variable and value the the shell rc file (or stdout)
        """
        if self._out is None:
            if self.file is None:
                self._out = sys.stderr
            else:
                self._out = open(os.path.expanduser(self.file), "a")
        
        cmd = self._env_format % (variable, value)
        print >>self._out, "\n%s  # Added in genomedata installation\n" % cmd
            
    def add_to_rc_env(self, variable, value):
        """Prepend the value to the variable in the shell rc file (or stdout)
        """
        full_value = "%s:$%s" % (value, variable)
        self.set_rc_env(variable, full_value)

    def set_env(self, variable, value):
        """Set the environment variable to the given value.
        """
        os.environ[variable] = value

    def add_to_env(self, variable, value):
        """Prepend value to the value of the environment variable.
        """
        if variable in os.environ:
            value = "%s:%s" % (value, os.environ[variable])

        self.set_env(variable, value)

    def in_env(self, variable, value):
        """Checks if value is in environment variable.

        Returns true if variable found and value is one of the ':'-
        delimited values in it.
        """
        try:
            env = os.environ[variable]
            env_values = env.strip().split(":")
            return value in env_values
        except KeyError:
            return False

    def close(self):
        """Close the open rc file, if one exists
        """
        if self._out not in [None, sys.stdout, sys.stderr]:
            try:
                self._out.close()
            except ValueError:
                pass

############################## MAIN #########################
def main(args=sys.argv[1:]):
    # Set up shell details
    try:
        shell_name = os.path.basename(os.environ["SHELL"])
    except KeyError:
        shell_name = None
    shell = ShellManager(shell_name)
                
    try:
        # Set up arch_home
        query = "\nWhere should platform-specific files be installed?"
        default_arch_home = get_default_arch_home()
        arch_home = prompt_user(query, default_arch_home)
        make_dir(arch_home)
        
        
        # Set up python home
        query = "\nWhere should new Python packages be installed?"
        default_python_home = get_default_python_home(arch_home)
        python_home = fix_path(prompt_user(query, default_python_home))
        make_dir(python_home)
        
        # Add python_home to PYTHONPATH
        prompt_add_to_env(shell, "PYTHONPATH", python_home)
                
        # Set up bin directory
        query = "\nWhere should new scripts and executables be installed?"
        default_script_home = os.path.join(arch_home, "bin")
        script_home = fix_path(prompt_user(query, default_script_home))
        make_dir(script_home)

        # Add script_home to PATH
        prompt_add_to_env(shell, "PATH", script_home)

        # Maybe create pydistutils.cfg
        prompt_create_cfg(arch_home, python_home, default_python_home,
                          script_home, default_script_home)
            
        # Add HDF5, if necessary
        hdf5_dir = prompt_install_hdf5(arch_home)
        if hdf5_dir:
            print >>sys.stderr,"\nPyTables uses the environment variable HDF5DIR to locate HDF5."
            prompt_set_env(shell, "HDF5_DIR", hdf5_dir)


        # Add NumPy, if necessary
        prompt_install_numpy()

        # Install genomedata (and dependencies)
        prompt_install_genomedata()

        # Test package installations
        prompt_test_packages(arch_home=arch_home)
        
        print >>sys.stderr, "Installation complete"
        
    finally:  # Clean up
        shell.close()

######################## UTIL FUNCTIONS ####################
def get_default_arch_home():
    (sysname, nodename, release, version, machine) = os.uname()
    arch = "-".join([sysname, machine])
    return os.path.expanduser("~/arch/%s" % arch)

def get_default_python_home(arch_home):
    python_version = sys.version[:3]
    return os.path.join(arch_home, "lib", "python%s" % python_version)
    
def prompt_add_to_env(shell, variable, value):
    if shell.in_env(variable, value):
        print >>sys.stderr, "\nFound %s already in your %s!" % (value, variable)
    else:
        shell.add_to_env(variable, value)
        query = "\nMay I edit your %s to add %s to your %s?" % (shell.file, value, variable) 
        permission = prompt_yes_no(query)
        if permission:
            shell.add_to_rc_env(variable, value)
        
def prompt_set_env(shell, variable, value):
    shell.set_env(variable, value)
    query = "\nMay I edit your %s to set your %s to %s?" % (shell.file, variable, value) 
    permission = prompt_yes_no(query)
    if permission:
        shell.set_rc_env(variable, value)

def fix_path(path):
    # Put path in standard form
    return os.path.abspath(os.path.expanduser(path))
        
def make_dir(dirname, verbose=True):
    """Make directory if it does not exist"""
    absdir = fix_path(dirname)
    if not os.path.isdir(absdir):
        os.makedirs(absdir)
        if verbose:
            print >>sys.stderr, "Created directory: %s" % dirname

def substitute_template(template, fields):
    return Template(template).substitute(fields)

########################## CFG FILE ##########################
def prompt_create_cfg(arch_home, python_home, default_python_home,
                      script_home, default_script_home,
                      cfg_file="~/.pydistutils.cfg"):
    cfg_path = fix_path(cfg_file)
    if os.path.isfile(cfg_path):
        print >>sys.stderr, "\nFound your %s! (hopefully the configuration matches)" % cfg_file
    else:
        query = "\nMay I create %s? It will be used by distutils to install new Python modules into this directory (and subdirectories) automatically." % cfg_file
        permission = prompt_yes_no(query)
        if permission:
            write_pydistutils_cfg(cfg_path, arch_home,
                                  python_home, default_python_home,
                                  script_home, default_script_home)
    
def write_pydistutils_cfg(cfg_file, arch_home,
                          python_home, default_python_home,
                          script_home, default_script_home):
    """Write a pydistutils.cfg file
    """
    fields = {}
    fields["prefix"] = arch_home
    
    if python_home == default_python_home:
        platlib = "$platbase/lib/python$py_version_short"
    else:
        platlib = python_home
    fields["platlib"] = platlib

    if script_home == default_script_home:
        scripts = "$platbase/bin"
    else:
        scripts = script_home
    fields["scripts"] = scripts

    cfg_file_contents = substitute_template(CFG_FILE_TEMPLATE, fields)

    ofp = open(cfg_file, "w")
    try:
        print >>ofp, cfg_file_contents
    finally:
        close(ofp)
    
    
########################### GET VERSION ########################
def get_program_version(progname):
    progname_lower = progname.lower()
    if progname_lower == "hdf5":
        return get_hdf5_version()
    elif progname_lower == "numpy":
        return get_numpy_version()
    else:
        raise NotImplementedError
    
def get_hdf5_version():
    """Returns HDF5 version as tuple (or None if not found or installed)

    Only works if h52gif is installed and in current user path
    """
    try:
        cmd = Popen("h52gif -V", shell=True, stdout=PIPE, stderr=PIPE)
        res = cmd.stdout.readlines()[0].strip()
        if "Version" in res:
            # HDF5 Found!
            ver = res.split("Version ")[1]
            return version2tuple(ver)
        else:
            return None
    except (OSError, IndexError):
        return None

def get_numpy_version():
    """Returns NumPy version as a tuple (or None if not found or installed)
    """
    try:
        import numpy
        return version2tuple(numpy.__version__)
    except (AttributeError, ImportError):
        return None

def get_genomedata_version():
    """Returns Genomedata version as a tuple (or None if not found or installed)
    """
    try:
        import genomedata
        return version2tuple(genomedata.__version__)
    except (AttributeError, ImportError):
        return None

    
def get_setuptools_version():
    """Returns setuptools version as a tuple (or None if not found or installed)
    """
    try:
        import setuptools
        return version2tuple(setuptools.__version__)
    except (AttributeError, ImportError):
        return None
    
def version2str(ver):  # (#, #[, #]) -> #.#[.#]
    return ".".join([str(val) for val in ver])

def version2tuple(ver):  #  version -> (#, #[, #])
    import re
    components = re.split("[^0-9]+", ver)
    res = []
    for component in components:
        try:
            if len(component) > 0:
                val = int(component)
                res.append(val)
        except ValueError:
            break

    if len(res) > 0:
        return tuple(res)
    else:
        return None

##################### SPECIFIC PROGRAM INSTALLERS ################
def prompt_install_hdf5(arch_home):
    return _installer("HDF5", install_hdf5, get_hdf5_version,
                      install_message=HDF5_INSTALL_MESSAGE, arch_home=arch_home,
                      version=HDF5_DOWNLOAD_VERSION)

def prompt_install_numpy():
    return _installer("NumPy", install_numpy, get_numpy_version,
                      min_version=MIN_NUMPY_VERSION,
                      install_prompt = EASY_INSTALL_PROMPT)

def prompt_install_genomedata():
    return _installer("genomedata", install_genomedata, get_genomedata_version,
                      install_prompt = EASY_INSTALL_PROMPT)
                  
def install_hdf5(arch_home, *args, **kwargs):
    hdf5_dir = prompt_install_path("HDF5", arch_home)
    install_dir = install_script("HDF5", hdf5_dir, HDF5_INSTALL_SCRIPT,
                                 url=HDF5_URL)

    return install_dir

def install_numpy(min_version=MIN_NUMPY_VERSION, *args, **kwargs):
    return easy_install("numpy", min_version=min_version)

def install_genomedata(*args, **kwargs):
    return easy_install("genomedata")
    
#################### GENERIC INSTALL METHODS ###################         
def _installer(progname, install_func, version_func=None,
               install_message=None, *args, **kwargs):
    """Program installation wrapper method.

    Input:
    progname: string name of program
    install_func: function to call with *args, **kwargs to install progname
    version_func: function to call with *args, **kwargs to find progname version
    install_message: helpful message to print if user chooses to install program

    Checks if program is installed in a succificent version,
    if not, prompts user and installs program.
    """
    found = _check_install(progname, version_func, *args, **kwargs)
    if not found:
        permission = prompt_install(progname, *args, **kwargs)
        if permission:
            if install_message: print >>sys.stderr, str(install_message)
            success = _abort_skip_install(install_func, *args, **kwargs)
            if success:
                print >>sys.stderr, "%s successfully installed." % progname
            else:
                print >>sys.stderr, "%s not installed." % progname

def _abort_skip_install(func, *args, **kwargs):
    """Calls func with args. If it fails, prompts user to abort or skip.

    On success, returns what the function would.
    On failure and skip, returns None
    On failure and abort, program terminates
    """
    try:
        return func(*args, **kwargs)
    except InstallationError:
        query = "\nWould you like to continue the installation without this program?"
        default = "n"
        permission = prompt_yes_no(query, default)
        if permission:
            return None
        else:
            die("Installation aborted")
            
def _check_install(progname, version_func, min_version=None, *args, **kwargs):
    """Returns True if program found with at least min_version, False otherwise

    version_func should be a function that, when called, returns the version of
    the installation (or None if not found/unavailable) as a tuple
    """
    print >>sys.stdout, "\nSearching for %s..." % progname,
    sys.stdout.flush()
    version = version_func()
    if version is not None:
        print >>sys.stderr, "found!"
        if min_version is not None and min_version > version:
            print >>sys.stderr, "Found version: %s. Version %s or above required." % (version2str(version), version2str(min_version))
        else:
            return True
    else:
        print >>sys.stderr, "not found."

    return False

def easy_install(progname, min_version=None):
    """Easy-installs the given program (can specifiy minimum version).
    """
    if get_setuptools_version() == None:
        query = "Unable to find setuptools. This is necessary to install this program and many of its dependencies. May I download and install %s?"
        permission = prompt_install("setuptools", install_prompt=query)
        if permission:
            try:
                urlretrieve(EZ_SETUP_URL)
                from ez_setup import use_setuptools
                use_setuptools(delay=0)
            except:
                print >>sys.stderr, "Error occurred while trying to install setuptools"
                raise InstallationError()
        else:
            raise InstallationError()
    
    cmd = "easy_install %s" % progname.lower()
    if min_version is not None:  # Add version requirement
        cmd += ' "%s>=%s"' % (progname, version2str(min_version))

    if os.path.isdir(progname):
        print >>sys.stderr, "\nWarning: installation may fail because there is a subdirectory named %s at your current path."

    print >>sys.stderr, ">> %s" % cmd
    proc = Popen(cmd, shell=True, stdout=None, stderr=None)
    code = proc.wait()

    if code != 0:
        print >>sys.stderr, "Error occured installing %s" % progname
        raise InstallationError()
    else:
        return True

def install_script(progname, prog_dir, script, **kwargs):
    """Tries to install the specified program, given a script, url

    Returns installation directory if installation is successful (or True if unknown),
    and None otherwise.
    """
    fields = kwargs

    # Set fields for template substitution
    if "dir" not in fields:
        fields["dir"] = prog_dir
        
    if "url" in fields:
        filename = os.path.basename(fields["url"])
        if "file" not in fields:
            fields["file"] = filename
        if "filebase" not in fields:
            fields["filebase"] = filename[:-7]  # minus .tar.gz
    
    script = substitute_template(script, fields).strip().splitlines()

    cwd = os.getcwd()  # Keep track of cwd state

    if prog_dir is not None:
        os.chdir(prog_dir)  # Move to installation directory
        
    for line in script:
        line = line.strip()
        print >>sys.stderr, ">> %s" % line
        # Intercept cd lines and update directory state
        if line.startswith("cd"):
            try:
                path = line.split()[1]
                os.chdir(fix_path(path))
                continue
            except IndexError:
                die("Invalid cd command: %s" % line)
                
        # Run command in shell
        proc = Popen(line, shell=True, stdout=None, stderr=None)
        code = proc.wait()
        if code != 0:
            print >>sys.stderr, "Error installing: %s" % progname
            print >>sys.stderr, "Command failed: %s" % line
            os.chdir(cwd)
            raise InstallationError()

    os.chdir(cwd)
    return prog_dir

def reinstall_program(progname, *args, **kwargs):
    """Reinstall program given name and arguments."""
    progname = progname.lower()
    if progname == "hdf5":
        install_hdf5(*args, **kwargs)
    elif progname == "numpy":
        install_numpy(*args, **kwargs)
    elif progname == "genomedata":
        install_genomedata(*args, **kwargs)

########################## PROGRAM TESTING ######################
def prompt_test_packages(*args, **kwargs):
    """Run each dependency's unit tests and if they fail, prompt reinstall
    XXX: implement this! (but numpy fails test even when correctly installed!)
    """
    prompt_test_pytables(*args, **kwargs)

def prompt_test_pytables(*args, **kwargs):
    query = "May I test the PyTables installation? This should provide a reasonable test of the HDF5 and NumPy installations as well."
    permission = prompt_yes_no(query)
    if permission:
        try:
            import tables
            tables.test()
            print >>sys.stderr, "Test passed!"
        except:
            print >>sys.stderr, "There seems to be an error with the PyTables installation!"
            query = "Would you like to reinstall HDF5, NumPy, genomedata (with pytables), or none of these programs?"
            choice = prompt_user(query, default="none",
                                 choices=("hdf5", "numpy",
                                          "genomedata", "none"))
            reinstall_program(choice, *args, **kwargs)
            
                

########################## USER INTERACTION #######################
def prompt_install(progname, install_prompt = None,
                   version=None, default="Y", *args, **kwargs):
    if version is not None:
        info = "%s %s" % (progname, version2str(version))
    else:
        info = "%s" % progname

    if install_prompt is None:
        install_prompt = "May I download and install %s?"
        
    query = install_prompt % info
    return prompt_yes_no(query, default=default)

def prompt_install_path(progname, default):
    query = "\nWhere should %s be installed?" % progname
    path = prompt_user(query, default)
    return fix_path(path)

def prompt_yes_no(query, default="Y"):
    """Prompt user with query, given default and return boolean response

    Returns True if the user responds y/Y/Yes, and False if n/N/No
    """
    # Loop until we get a valid response
    while True:
        # Query user and get response
        print "%s (Y/n) [%s] " % (query, default),
        sys.stdin.flush()
        response = raw_input().strip().lower()
        if len(response) == 0:
            response = default.strip().lower()
            
        if response.startswith("y"):
            return True
        elif response.startswith("n"):
            return False
        else:
            print "Please enter yes or no."
        
def prompt_user(query, default, choices=None):
    """Prompt user with query, given default answer and optional choices
    """
    
    if choices is None:
        prompt = str(query)
    else:
        try:
            # Uniquify and convert to strings
            str_choices = list(str(choice) for choice in set(choices))
            assert(len(str_choices) > 1)
            lower_choices = list(choice.lower() for choice in str_choices)
                
            prompt = "%s (%s)" % (query, " / ".join(choices))
        except (AssertionError, TypeError):
            die("Invalid choice list: %s" % choices)
        
    # Loop until we get a valid response
    while True:
        # Query user and get response
        print "%s [%s] " % (prompt, default),
        sys.stdin.flush()
        response = raw_input().strip()

        if len(response) == 0:  # User didn't enter a response
            return default
        elif choices is None:
            return response
        else:
            # Ensure the user picked from the set of choices
            matches = []
            for choice in lower_choices:
                if choice.startswith(response) or response.startswith(choice):
                    matches.append(choice)

            matched = len(matches)
            if matched == 0:
                print "Invalid answer: %s" % response
                print "Please select one of: (%s)" % ",".join(str_choices)
            elif matched == 1:
                return matches[0]
            else:
                print "Response matched multiple choices. Please be more specific"
                
def die(message):
    print >>sys.stderr, str(message)
    sys.exit(1)


    
if __name__ == "__main__":
    sys.exit(main())
