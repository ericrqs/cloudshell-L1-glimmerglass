# CloudShell L1 driver SSH, Telnet, or TL1 connection
#
# Uses the standard CloudShell CLI package.
#
# Edit this file to define command modes (enable mode, config mode) and custom CLI commands
# (including interactive y/n responses) for your device.
#
# For TL1, prompts and modes are ignored.
#
# Note that prompt regexes can also be overridden from the runtime configuration JSON.
#

from cloudshell.cli.cli import CLI
from cloudshell.cli.command_mode_helper import CommandModeHelper
from cloudshell.cli.command_template.command_template import CommandTemplate
from cloudshell.cli.session.scpi_session import SCPISession
from cloudshell.cli.session.ssh_session import SSHSession
from cloudshell.cli.session.telnet_session import TelnetSession
from cloudshell.cli.session.tl1_session import TL1Session
from cloudshell.cli.session_pool_manager import SessionPoolManager
from cloudshell.cli.command_mode import CommandMode


class GlimmerglassRawCommandMode(CommandMode):
    PROMPT_REGEX = r'DUMMY_PROMPT'
    ENTER_COMMAND = ''
    EXIT_COMMAND = ''

    def __init__(self):
        CommandMode.__init__(self,
                             GlimmerglassRawCommandMode.PROMPT_REGEX,
                             GlimmerglassRawCommandMode.ENTER_COMMAND,
                             GlimmerglassRawCommandMode.EXIT_COMMAND)

CommandMode.RELATIONS_DICT = {
    GlimmerglassRawCommandMode: {}
}

TL1_COMMAND = CommandTemplate('{command}')
SCPI_COMMAND = CommandTemplate('{command}')


class GlimmerglassCliConnection:

    def __init__(self, logger, session_pool_size=1):
        """
        :param logger: qs_logger
        :param cli_type: str: 'ssh', 'telnet', 'tl1'
        :param session_pool_size:
        """
        self._logger = logger
        self._logger.info('Create GlimmerglassCliConnection')

        self.on_session_start = None
        self.resource_address = None
        self.port = None
        self.username = None
        self.password = None
        self.cli_type = None

        session_pool = SessionPoolManager(max_pool_size=session_pool_size, pool_timeout=100)
        self._cli = CLI(session_pool=session_pool)
        modes = CommandModeHelper.create_command_mode()
        self.raw_mode = modes[GlimmerglassRawCommandMode]

    def set_resource_address(self, addr):
        self.resource_address = addr

    def set_port(self, port):
        self.port = port

    def set_username(self, username):
        self.username = username

    def set_password(self, password):
        self.password = password

    def set_cli_type(self, cli_type):
        self.cli_type = cli_type

    def _make_session(self):
        if self.cli_type.lower() == 'ssh':
            return SSHSession(self.resource_address, self.username, self.password, self.port, self.on_session_start,
                              loop_detector_max_action_loops=10000)
        elif self.cli_type.lower() == 'telnet':
            return TelnetSession(self.resource_address, self.username, self.password, self.port, self.on_session_start,
                                 loop_detector_max_action_loops=10000)
        elif self.cli_type.lower() == 'tl1':
            return TL1Session(self.resource_address, self.username, self.password, self.port, self.on_session_start,
                              loop_detector_max_action_loops=10000)
        elif self.cli_type.lower() == 'scpi':
            return SCPISession(self.resource_address, self.port, self.on_session_start,
                               loop_detector_max_action_loops=10000)
        else:
            raise Exception('Unsupported CLI type "%s"' % self.cli_type)

    def get_raw_session(self):
        return self._cli.get_session(self._make_session(), self.raw_mode, self._logger)

    def scpi_command(self, cmd, ):
        """
        Executes an arbitrary SCPI command

        :param cmd: An SCPI command like ":OXC:SWITch:CONNect:STATe?"
        :return: str: SCPI command output including the status
        :raises: Exception: If the command status is < 0
        """
        with self.get_raw_session() as session:
            return session.send_command(**SCPI_COMMAND.get_command(command=cmd))

    def tl1_command(self, cmd):
        """
        Executes an arbitrary TL1 command, with the switch name and incrementing command number managed automatically.

        :param cmd: A TL1 command like "RTRV-NETYPE:{name}::{counter}:;", where "{name}" and "{counter}" will be automatically substituted with the switch name and an incrementing counter
        :return: str: TL1 command output including the status
        :raises: Exception: If the command status is not COMPLD
        """
        with self.get_raw_session() as session:
            return session.send_command(**TL1_COMMAND.get_command(command=cmd))
