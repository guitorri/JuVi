"""
Python wrapper for Virtuoso shell.

To be used in conjunction with IPython/Jupyter.
"""

import re
import signal
import pexpect
from pexpect import EOF
from subprocess import check_output
import subprocess


class VirtuosoExceptions(Exception):
    """
    To handle errors throws by the virtuoso shell
    """
    def __init__(self, value):
        self.value = value
        super(VirtuosoExceptions, self).__init__(value)

    def __str__(self):
        return repr(self.value)


class VirtuosoShell(object):
    """
    This class gives a python interface to the Virtuoso shell.j
    """
    prompt = '\r\n> $'
    _banner = None
    _version_re = None
    _output = ""
    _exec_error = None  # None means no error in last execution

    @property
    def banner(self):
        """
        Virtuoso shell's banner
        """
        if self._banner is None:
            self._banner = check_output(['/bin/tcsh', '-c', 'virtuoso -V'],
                                        stderr=subprocess.STDOUT)
            self._banner = self._banner.decode('utf-8')
        return self._banner

    @property
    def language_version(self):
        """
        Language version
        """
        __match__ = self._version_re.search(self.banner)
        return __match__.group(1)

    @property
    def output(self):
        """
        Last output returned by the shell
        """
        return self._output

    def __init__(self, *args, **kwargs):
        super(VirtuosoShell, self).__init__(*args, **kwargs)
        self._start_virtuoso()
        self._version_re = re.compile(r'version (\d+(\.\d+)+)')
        self._error_re = re.compile(r'\("(.*?)"\s+(\d+)\s+t\s+'
                                    r'nil\s+\((.*?)\)\s*\)')
        self._output_re = re.compile(r'(^[\S\s]*?)(?=(?:\r\n)?nil$)')

    def _start_virtuoso(self):
        """
        Spawn a virtuoso shell.
        """
        # Signal handlers are inherited by forked processes, and we can't
        # easily # reset it from the subprocess. Since kernelapp ignores SIGINT
        # except in # message handlers, we need to temporarily reset the SIGINT
        # handler here # so that virtuoso and its children are interruptible.
        sig = signal.signal(signal.SIGINT, signal.SIG_DFL)
        try:
            # I could use 'setPrompts' for setting SKILL prompt, but,
            # not relevant for Jupyter
            self._shell = pexpect.spawn('tcsh -c "virtuoso -nograph"',
                                        echo=False)
            self._shell.expect('\r\n> ')
        finally:
            signal.signal(signal.SIGINT, sig)

    def _parse_output(self):
        """
        Parse the virtuoso shell's output and handle error.

        #TODO: Can I use the skill debugger somehow?

        In case of error, set status to a tuple of the form :
            (etype, evalue, tb)
        else, set to None
        """
        self._exec_error = None
        if self._output != 'nil':
            # non-error results are returned in a list
            self._output = self._output[1:-1]

        # The output can have a stream of text ending
        # with the following format if there is an error:
        # ("errorClass" errorNumber t nil ("Error Message"))
        _parsed_output = self._error_re.search(self._error_output)
        self._exec_error = None
        _printed_out = ''
        if _parsed_output is not None:
            self._exec_error = _parsed_output.groups()
            self._exec_error = (self._exec_error[0],
                                int(self._exec_error[1]),
                                self._exec_error[2])
            _printed_out = self._error_output[:_parsed_output.start()]
        else:
            _parsed_output = self._output_re.search(self._error_output)
            _printed_out = _parsed_output.group(1)

        self._output = _printed_out + '\r\n' + self._output

        # If the shell reported any errors, throw exception
        if self._exec_error is not None:
            raise VirtuosoExceptions(self._exec_error)

    def run_cell(self, code):
        """
        Executes the 'code'

        #TODO: use 'store_history' and 'silent' similar to IPython
        """
        # Intercept errors in execution using 'errset' function
        _code_framed = '_exc_res=errset({' + code + '}) errset.errset'

        self._shell.sendline(_code_framed)
        self.wait_ready()
        # if successful, return is 'nil',
        # else, return is a list with error message
        # printed messages can precede the error message
        self._error_output = self._shell.before

        # get the result of execution
        self._shell.sendline('_exc_res')
        self.wait_ready()
        # if successful, return is a list
        # else, return is 'nil'
        self._output = self._shell.before

        # Check the output and throw exception in case of error
        self._parse_output()

        return self.output

    def get_matches(self, token):
        """
        Return a list of functions and variables starting with *token*
        """
        _cmd = 'listFunctions("^%s")' % token
        self._shell.sendline(_cmd)
        self.wait_ready()
        _matches = []
        _output = self._shell.before
        if (_output) != 'nil':
            if _output[0] == '(':
                _output = _output[1:-1]
            _matches = _output.split()

        _cmd = 'listVariables("^%s")' % token
        self._shell.sendline(_cmd)
        self.wait_ready()
        _output = self._shell.before
        if (_output) != 'nil':
            if _output[0] == '(':
                _output = _output[1:-1]
            _matches.extend(_output.split())
        return _matches

    def get_info(self, token):
        """
        Returns info on the requested object

        # TODO: get info on variables also
        """
        _cmd = 'help(%s)' % token
        self._shell.sendline(_cmd)
        self.wait_ready()
        if (self._shell.before) != 'nil':
            return self._shell.before
        return ''

    def interrupt(self):
        """
        Send an interrupt to the virtuoso shell
        """
        self._shell.sendintr()

    def wait_ready(self):
        """
        Find the prompt after the shell output.
        """
        self._shell.expect(self.prompt)

    def shutdown(self, restart):
        """
        Shutdown the shell

        #TODO: use 'restart'
        """
        try:
            self.run_cell('exit()')
        except EOF:
            self._shell.close()
