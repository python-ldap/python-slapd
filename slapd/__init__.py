import os
import socket
import sys
import time
import subprocess
import logging
import atexit
from logging.handlers import SysLogHandler
from shutil import which
from urllib.parse import quote_plus

HERE = os.path.abspath(os.path.dirname(__file__))

SLAPD_CONF_TEMPLATE = r"""dn: cn=config
objectClass: olcGlobal
cn: config
olcServerID: %(serverid)s
olcLogLevel: stats stats2
olcAllows: bind_v2
olcAuthzRegexp: {0}"gidnumber=%(root_gid)s\+uidnumber=%(root_uid)s,cn=peercred,cn=external,cn=auth" "%(rootdn)s"
olcAuthzRegexp: {1}"C=DE, O=python-ldap, OU=slapd-test, CN=([A-Za-z]+)" "ldap://ou=people,dc=local???($1)"
olcTLSCACertificateFile: %(cafile)s
olcTLSCertificateFile: %(servercert)s
olcTLSCertificateKeyFile: %(serverkey)s
olcTLSVerifyClient: try

dn: cn=module,cn=config
objectClass: olcModuleList
cn: module
olcModuleLoad: back_%(database)s

dn: olcDatabase=%(database)s,cn=config
objectClass: olcDatabaseConfig
objectClass: olcMdbConfig
olcDatabase: %(database)s
olcSuffix: %(suffix)s
olcRootDN: %(rootdn)s
olcRootPW: %(rootpw)s
olcDbDirectory: %(directory)s
"""


def _add_sbin(path):
    """Add /sbin and related directories to a command search path"""
    directories = path.split(os.pathsep)
    if sys.platform != "win32":
        for sbin in "/usr/local/sbin", "/sbin", "/usr/sbin":
            if sbin not in directories:
                directories.append(sbin)
    return os.pathsep.join(directories)


def combinedlogger(
    log_name,
    log_level=logging.WARN,
    syslogger_format="%(levelname)s %(message)s",
    consolelogger_format="%(asctime)s %(levelname)s %(message)s",
):
    """
    Returns a combined SysLogHandler/StreamHandler logging instance
    with formatters
    """
    if "LOGLEVEL" in os.environ:
        log_level = os.environ["LOGLEVEL"]
        try:
            log_level = int(log_level)
        except ValueError:
            pass
    # for writing to syslog
    newlogger = logging.getLogger(log_name)
    if syslogger_format and os.path.exists("/dev/log"):
        my_syslog_formatter = logging.Formatter(
            fmt=" ".join((log_name, syslogger_format))
        )
        my_syslog_handler = logging.handlers.SysLogHandler(
            address="/dev/log",
            facility=SysLogHandler.LOG_DAEMON,
        )
        my_syslog_handler.setFormatter(my_syslog_formatter)
        newlogger.addHandler(my_syslog_handler)
    if consolelogger_format:
        my_stream_formatter = logging.Formatter(fmt=consolelogger_format)
        my_stream_handler = logging.StreamHandler()
        my_stream_handler.setFormatter(my_stream_formatter)
        newlogger.addHandler(my_stream_handler)
    newlogger.setLevel(log_level)
    return newlogger  # end of combinedlogger()


class Slapd:
    """
    Controller class for a slapd instance, OpenLDAP's server.

    This class creates a temporary data store for slapd, runs it
    listening on a private Unix domain socket and TCP port,
    and initializes it with a top-level entry and the root user.

    When a reference to an instance of this class is lost, the slapd
    server is shut down.

    An instance can be used as a context manager. When exiting the context
    manager, the slapd server is shut down and the temporary data store is
    removed.

    :param schemas: A list of schema names or schema paths to
        load at startup. By default this only contains `core`.

    :param host: The host on which the slapd server will listen to.
        The default value is `127.0.0.1`.

    :param port: The port on which the slapd server will listen to.
        If `None` a random available port will be chosen.

    :param log_level: The verbosity of Slapd.
        The default value is `logging.WARNING`.

    :param suffix: The LDAP suffix for all objects. The default is
        `dc=slapd-test,dc=python-ldap,dc=org`.

    :param root_cn: The root user common name. The default value is `Manager`.

    :param root_pw: The root user password. The default value is `password`.

    :param datadir_prefix: The prefix of the temporary directory where the slapd
        configuration and data will be stored. The default value is `python-ldap-test`.

    :param debug: Wether to launch slapd with debug verbosity on. When `True` debug is enabled,
        when `False` debug is disabled, when `None`, debug is only enable when *log_level* is
        `logging.DEBUG`. Default value is `None`.
    """

    TMPDIR = os.environ.get("TMP", os.getcwd())
    if "SCHEMA" in os.environ:
        SCHEMADIR = os.environ["SCHEMA"]
    elif os.path.isdir("/etc/openldap/schema"):
        SCHEMADIR = "/etc/openldap/schema"
    elif os.path.isdir("/etc/ldap/schema"):
        SCHEMADIR = "/etc/ldap/schema"
    else:
        SCHEMADIR = None

    BIN_PATH = os.environ.get("BIN", os.environ.get("PATH", os.defpath))
    SBIN_PATH = os.environ.get("SBIN", _add_sbin(BIN_PATH))

    def __init__(
        self,
        host=None,
        port=None,
        log_level=logging.WARN,
        schemas=None,
        database="mdb",
        suffix="dc=slapd-test,dc=python-ldap,dc=org",
        root_cn="Manager",
        root_pw="password",
        datadir_prefix=None,
        debug=None,
    ):
        self.logger = combinedlogger("python-ldap-test", log_level=log_level)
        self.schemas = schemas or ("core.ldif",)

        self.database = database
        self.suffix = suffix
        self.root_cn = root_cn
        self.root_pw = root_pw
        self.host = host or "127.0.0.1"

        self._proc = None
        self.port = port or self._avail_tcpport()
        self.server_id = self.port % 4096
        self.testrundir = os.path.join(
            self.TMPDIR, "%s-%d" % (datadir_prefix or "python-ldap-test", self.port)
        )
        self._slapd_conf = os.path.join(self.testrundir, "slapd.d")
        self._db_directory = os.path.join(self.testrundir, "openldap-data")
        self.ldap_uri = "ldap://%s:%d/" % (self.host, self.port)
        self.debug = debug
        have_ldapi = hasattr(socket, "AF_UNIX")
        if have_ldapi:
            ldapi_path = os.path.join(self.testrundir, "ldapi")
            self.ldapi_uri = "ldapi://%s" % quote_plus(ldapi_path)
            self.default_ldap_uri = self.ldapi_uri
            # use SASL/EXTERNAL via LDAPI when invoking OpenLDAP CLI tools
            self.cli_sasl_external = True
        else:
            self.ldapi_uri = None
            self.default_ldap_uri = self.ldap_uri
            # Use simple bind via LDAP uri
            self.cli_sasl_external = False

        self._find_commands()

        if self.SCHEMADIR is None:
            raise ValueError("SCHEMADIR is None, ldap schemas are missing.")

        self.cafile = os.path.join(HERE, "certs/ca.pem")
        self.servercert = os.path.join(HERE, "certs/server.pem")
        self.serverkey = os.path.join(HERE, "certs/server.key")
        self.clientcert = os.path.join(HERE, "certs/client.pem")
        self.clientkey = os.path.join(HERE, "certs/client.key")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()

    @property
    def root_dn(self):
        return "cn={self.root_cn},{self.suffix}".format(self=self)

    def _find_commands(self):
        self.PATH_LDAPADD = self._find_command("ldapadd")
        self.PATH_LDAPDELETE = self._find_command("ldapdelete")
        self.PATH_LDAPMODIFY = self._find_command("ldapmodify")
        self.PATH_LDAPWHOAMI = self._find_command("ldapwhoami")
        self.PATH_SLAPADD = self._find_command("slapadd")
        self.PATH_SLAPCAT = self._find_command("slapcat")

        self.PATH_SLAPD = os.environ.get("SLAPD", None)
        if not self.PATH_SLAPD:
            self.PATH_SLAPD = self._find_command("slapd", in_sbin=True)

    def _find_command(self, cmd, in_sbin=False):
        if in_sbin:
            path = self.SBIN_PATH
            var_name = "SBIN"
        else:
            path = self.BIN_PATH
            var_name = "BIN"
        command = which(cmd, path=path)
        if command is None:
            raise ValueError(
                "Command '{}' not found. Set the {} environment variable to "
                "override slapd's search path.".format(cmd, var_name)
            )
        return command

    def _setup_rundir(self):
        """
        creates rundir structure

        for setting up a custom directory structure you have to override
        this method
        """
        os.mkdir(self.testrundir)
        os.mkdir(self._db_directory)
        dir_name = os.path.join(self.testrundir, "slapd.d")
        self.logger.debug("Create directory %s", dir_name)
        os.mkdir(dir_name)

    def _cleanup_rundir(self):
        """
        Recursively delete whole directory specified by `path'
        """
        if not os.path.exists(self.testrundir):
            return

        self.logger.debug("clean-up %s", self.testrundir)
        for dirpath, dirnames, filenames in os.walk(self.testrundir, topdown=False):
            for filename in filenames:
                self.logger.debug("remove %s", os.path.join(dirpath, filename))
                os.remove(os.path.join(dirpath, filename))
            for dirname in dirnames:
                self.logger.debug("rmdir %s", os.path.join(dirpath, dirname))
                os.rmdir(os.path.join(dirpath, dirname))
        os.rmdir(self.testrundir)
        self.logger.info("cleaned-up %s", self.testrundir)

    def _avail_tcpport(self):
        """
        find an available port for TCP connection
        """
        sock = socket.socket()
        try:
            sock.bind((self.host, 0))
            port = sock.getsockname()[1]
        finally:
            sock.close()

        self.logger.info("Found available port %d", port)
        return port

    def _gen_config(self):
        """
        generates a slapd.conf and returns it as one string

        for generating specific static configuration files you have to
        override this method
        """
        config_dict = {
            "serverid": hex(self.server_id),
            "database": self.database,
            "directory": self._db_directory,
            "suffix": self.suffix,
            "rootdn": self.root_dn,
            "rootpw": self.root_pw,
            "root_uid": os.getuid(),
            "root_gid": os.getgid(),
            "cafile": self.cafile,
            "servercert": self.servercert,
            "serverkey": self.serverkey,
        }
        return SLAPD_CONF_TEMPLATE % config_dict

    def _write_config(self):
        """Loads the slapd.d configuration."""
        self.logger.debug("importing configuration: %s", self._slapd_conf)

        self.slapadd(self._gen_config(), ["-n0"])
        ldif_paths = [
            schema if os.path.exists(schema) else os.path.join(self.SCHEMADIR, schema)
            for schema in self.schemas
        ]
        for ldif_path in ldif_paths:
            self.slapadd(None, ["-n0", "-l", ldif_path])

        self.logger.debug("import ok: %s", self._slapd_conf)

    def _test_config(self):
        self.logger.debug("testing config %s", self._slapd_conf)
        popen_list = [
            self.PATH_SLAPD,
            "-Ttest",
            "-F",
            self._slapd_conf,
            "-u",
            "-v",
            "-d",
            "config",
        ]
        p = subprocess.run(popen_list, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if p.returncode != 0:
            self.logger.error(p.stdout.decode("utf-8"))
            raise RuntimeError("configuration test failed")
        self.logger.info("config ok: %s", self._slapd_conf)

    def _start_slapd(self):
        """
        Spawns/forks the slapd process
        """
        urls = [self.ldap_uri]
        if self.ldapi_uri:
            urls.append(self.ldapi_uri)
        slapd_args = [
            self.PATH_SLAPD,
            "-F",
            self._slapd_conf,
            "-h",
            " ".join(urls),
        ]
        if self.debug is True or (
            self.debug is None and self.logger.isEnabledFor(logging.DEBUG)
        ):
            slapd_args.extend(["-d", "-1"])
        else:
            slapd_args.extend(["-d", "0"])

        self.logger.info("starting slapd: %r", " ".join(slapd_args))
        self._proc = subprocess.Popen(slapd_args)
        deadline = time.monotonic() + 10
        while True:
            if self._proc.poll() is not None:  # pragma: no cover
                self._stopped()
                raise RuntimeError("slapd exited before opening port")
            try:
                self.logger.debug("slapd connection check to %s", self.default_ldap_uri)
                self.ldapwhoami()
            except RuntimeError:
                if time.monotonic() >= deadline:  # pragma: no cover
                    break
                time.sleep(0.2)
            else:
                return
        raise RuntimeError("slapd did not start properly")  # pragma: no cover

    def start(self):
        """
        Starts the slapd server process running, and waits for it to come up.
        """

        if self._proc is not None:
            return

        atexit.register(self.stop)
        self._cleanup_rundir()
        self._setup_rundir()
        self._write_config()
        self._test_config()
        self._start_slapd()
        self.logger.debug(
            "slapd with pid=%d listening on %s and %s",
            self._proc.pid,
            self.ldap_uri,
            self.ldapi_uri,
        )

    def stop(self):
        """
        Stops the slapd server, and waits for it to terminate and cleans up
        """
        if self._proc is not None:
            self.logger.debug("stopping slapd with pid %d", self._proc.pid)
            self._proc.terminate()
            self.wait()
        self._cleanup_rundir()
        atexit.unregister(self.stop)

    def restart(self):
        """
        Restarts the slapd server with same data
        """
        self._proc.terminate()
        self.wait()
        self._start_slapd()

    def wait(self):
        """Waits for the slapd process to terminate by itself."""
        if self._proc:
            self._proc.wait()
            self._stopped()

    def _stopped(self):
        """Called when the slapd server is known to have terminated"""
        if self._proc is not None:
            self.logger.info("slapd[%d] terminated", self._proc.pid)
            self._proc = None

    def _cli_auth_args(self):
        if self.cli_sasl_external:
            authc_args = [
                "-Y",
                "EXTERNAL",
            ]
            if not self.logger.isEnabledFor(logging.DEBUG):
                authc_args.append("-Q")
        else:
            authc_args = [
                "-x",
                "-D",
                self.root_dn,
                "-w",
                self.root_pw,
            ]
        return authc_args

    def _cli_popen(
        self,
        ldapcommand,
        extra_args=None,
        ldap_uri=None,
        stdin_data=None,
        expected=0,
    ):
        if isinstance(expected, int):
            expected = [expected]

        if ldap_uri is None:
            ldap_uri = self.default_ldap_uri

        if ldapcommand.split("/")[-1].startswith("ldap"):
            args = [ldapcommand, "-H", ldap_uri] + self._cli_auth_args()
        else:
            args = [ldapcommand, "-F", self._slapd_conf]

        args += extra_args or []

        self.logger.debug("Run command: %r", " ".join(args))
        proc = subprocess.run(
            args, input=stdin_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        self.logger.debug(
            "stdin_data=%s", stdin_data.decode("utf-8") if stdin_data else stdin_data
        )

        if proc.stdout is not None:
            self.logger.debug("stdout=%s", proc.stdout.decode("utf-8"))

        if proc.stderr is not None:
            self.logger.debug("stderr=%s", proc.stderr.decode("utf-8"))

        if proc.returncode not in expected:
            raise RuntimeError(
                "Unexpected process return code (expected {}, got {}): {!r}".format(
                    expected, proc.returncode, " ".join(args)
                )
            )
        return proc

    def ldapwhoami(self, extra_args=None, expected=0):
        """
        Runs ldapwhoami on this slapd instance

        :param extra_args: Extra argument to pass to *ldapwhoami*.
        :param expected: Expected return code. Defaults to `0`.
        :type expected: An integer or a list of integers

        :return: A :class:`subprocess.CompletedProcess` with the *ldapwhoami* execution data.
        """
        return self._cli_popen(
            self.PATH_LDAPWHOAMI, extra_args=extra_args, expected=expected
        )

    def ldapadd(self, ldif, extra_args=None, expected=0):
        """
        Runs ldapadd on this slapd instance, passing it the ldif content

        :param ldif: The ldif content to pass to the *ldapadd* standard input.
        :param extra_args: Extra argument to pass to *ldapadd*.
        :param expected: Expected return code. Defaults to `0`.
        :type expected: An integer or a list of integers

        :return: A :class:`subprocess.CompletedProcess` with the *ldapadd* execution data.
        """
        return self._cli_popen(
            self.PATH_LDAPADD,
            extra_args=extra_args,
            stdin_data=ldif.encode("utf-8") if ldif else None,
            expected=expected,
        )

    def ldapmodify(self, ldif, extra_args=None, expected=0):
        """
        Runs ldapadd on this slapd instance, passing it the ldif content

        :param ldif: The ldif content to pass to the *ldapmodify* standard input.
        :param extra_args: Extra argument to pass to *ldapmodify*.
        :param expected: Expected return code. Defaults to `0`.
        :type expected: An integer or a list of integers

        :return: A :class:`subprocess.CompletedProcess` with the *ldapmodify* execution data.
        """
        return self._cli_popen(
            self.PATH_LDAPMODIFY,
            extra_args=extra_args,
            stdin_data=ldif.encode("utf-8") if ldif else None,
            expected=expected,
        )

    def ldapdelete(self, dn, recursive=False, extra_args=None, expected=0):
        """
        Runs ldapdelete on this slapd instance, deleting 'dn'

        :param dn: The distinguished name of the element to delete.
        :param recursive: Whether to delete sub-elements. Defaults to `False`.
        :param extra_args: Extra argument to pass to *ldapdelete*.
        :param expected: Expected return code. Defaults to `0`.
        :type expected: An integer or a list of integers

        :return: A :class:`subprocess.CompletedProcess` with the *ldapdelete* execution data.
        """
        if extra_args is None:
            extra_args = []
        if recursive:
            extra_args.append("-r")
        extra_args.append(dn)
        return self._cli_popen(
            self.PATH_LDAPDELETE, extra_args=extra_args, expected=expected
        )

    def slapadd(self, ldif, extra_args=None, expected=0):
        """
        Runs slapadd on this slapd instance, passing it the ldif content

        :param ldif: The ldif content to pass to the *slapadd* standard input.
        :param extra_args: Extra argument to pass to *slapadd*.
        :param expected: Expected return code. Defaults to `0`.
        :type expected: An integer or a list of integers

        :return: A :class:`subprocess.CompletedProcess` with the *slapadd* execution data.
        """
        return self._cli_popen(
            self.PATH_SLAPADD,
            stdin_data=ldif.encode("utf-8") if ldif else None,
            extra_args=extra_args,
            expected=expected,
        )

    def slapcat(self, extra_args=None, expected=0):
        """
        Runs slapadd on this slapd instance, passing it the ldif content

        :param extra_args: Extra argument to pass to *slapcat*.
        :param expected: Expected return code. Defaults to `0`.
        :type expected: An integer or a list of integers

        :return: A :class:`subprocess.CompletedProcess` with the *slapcat* execution data.
        """
        return self._cli_popen(
            self.PATH_SLAPCAT,
            extra_args=extra_args,
            expected=expected,
        )
