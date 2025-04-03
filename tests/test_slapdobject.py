import pytest

import slapd


def test_nominal_case():
    server = slapd.Slapd()
    server.start()
    server.restart()
    server.stop()


def test_context_manager():
    with slapd.Slapd() as server:
        assert server._proc is not None
    assert server._proc is None
    server.stop()


def test_context_manager_after_start():
    server = slapd.Slapd()
    server.start()
    assert server._proc is not None
    with server:
        assert server._proc is not None
    assert server._proc is None
    server.stop()


def test_commands():
    server = slapd.Slapd()
    server.start()
    assert (
        "dn:cn=manager,dc=slapd-test,dc=python-ldap,dc=org\n"
        == server.ldapwhoami().stdout.decode("utf-8")
    )
    server.ldapsearch("ou=home", "dc=slapd-test,dc=python-ldap,dc=org", expected=32)

    server.init_tree()

    ldif = (
        "dn: ou=home,dc=slapd-test,dc=python-ldap,dc=org\n"
        "objectClass: organizationalUnit\n"
        "ou: home\n"
    )
    server.ldapadd(ldif)

    assert (
        "dn: ou=home,dc=slapd-test,dc=python-ldap,dc=org"
        in server.slapcat().stdout.decode("utf-8")
    )

    server.ldapsearch("ou=home", "dc=slapd-test,dc=python-ldap,dc=org")

    ldif = (
        "dn: ou=home,dc=slapd-test,dc=python-ldap,dc=org\n"
        "changetype: modify\n"
        "add: description\n"
        "description: foobar\n"
    )
    server.ldapmodify(ldif)

    assert "foobar" in server.slapcat().stdout.decode("utf-8")

    server.ldapdelete("ou=home,dc=slapd-test,dc=python-ldap,dc=org", True)
    assert (
        "dn: ou=home,dc=slapd-test,dc=python-ldap,dc=org"
        not in server.slapcat().stdout.decode("utf-8")
    )

    server.stop()


def test_ldapadd_config_database():
    server = slapd.Slapd()
    server.start()

    assert "dn: cn={1}myschema,cn=schema,cn=config" not in server.slapcat(
        ["-n0"]
    ).stdout.decode("utf-8")

    ldif = (
        "dn: cn=myschema,cn=schema,cn=config\n"
        "objectClass: olcSchemaConfig\n"
        "cn: myschema\n"
        "olcAttributeTypes: (  1.3.6.1.4.1.56207.1.1.1 NAME 'myAttribute'\n"
        "        EQUALITY caseExactMatch\n"
        "        ORDERING caseExactOrderingMatch\n"
        "        SUBSTR caseExactSubstringsMatch\n"
        "        SYNTAX 1.3.6.1.4.1.1466.115.121.1.15\n"
        "        SINGLE-VALUE\n"
        "        USAGE userApplications\n"
        "        X-ORIGIN 'mySchema1' )\n"
        "olcObjectClasses: ( 1.3.6.1.4.1.56207.1.1.2 NAME 'myObject'\n"
        "        SUP top\n"
        "        STRUCTURAL\n"
        "        MUST  (\n"
        "              cn $\n"
        "              myAttribute\n"
        "        )\n"
        "        X-ORIGIN 'mySchema2' )\n"
    )
    server.ldapadd(ldif)

    assert "dn: cn={1}myschema,cn=schema,cn=config" in server.slapcat(
        ["-n0"]
    ).stdout.decode("utf-8")


def test_return_codes():
    server = slapd.Slapd()
    server.start()

    with pytest.raises(RuntimeError):
        server.ldapadd("bad ldif")
    server.ldapadd("bad ldif", expected=247)
    server.ldapadd("bad ldif", expected=(0, 247))

    server.stop()
