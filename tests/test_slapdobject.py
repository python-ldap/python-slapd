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
    ldif = (
        "dn: dc=slapd-test,dc=python-ldap,dc=org\n"
        "objectClass: dcObject\n"
        "objectClass: organization\n"
        "dc: slapd-test\n"
        "o: slapd-test\n"
        "\n"
        "dn: cn=Manager,dc=slapd-test,dc=python-ldap,dc=org\n"
        "objectClass: applicationProcess\n"
        "cn: Manager\n"
        "\n"
        "dn: ou=home,dc=slapd-test,dc=python-ldap,dc=org\n"
        "objectClass: organizationalUnit\n"
        "ou: home\n"
    )
    server.ldapadd(ldif)

    assert (
        "dn: ou=home,dc=slapd-test,dc=python-ldap,dc=org"
        in server.slapcat().stdout.decode("utf-8")
    )

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
